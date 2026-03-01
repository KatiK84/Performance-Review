from __future__ import annotations

import csv
import io
import json
import shutil
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, send_file

try:
    from .calculations import (
        is_employee_active_in_month,
        money_round_down,
        quarter_months,
        weighted_month_score,
    )
    from .db import BASE_DIR, DB_PATH, get_connection, init_db, rows_to_dicts
except ImportError:  # pragma: no cover
    from calculations import (
        is_employee_active_in_month,
        money_round_down,
        quarter_months,
        weighted_month_score,
    )
    from db import BASE_DIR, DB_PATH, get_connection, init_db, rows_to_dicts

try:
    from openpyxl import Workbook
except ImportError:  # pragma: no cover
    Workbook = None

init_db()

app = Flask(__name__, template_folder="templates", static_folder="static")

EXPORTS_DIR = BASE_DIR / "exports"
BACKUPS_DIR = BASE_DIR / "backups"
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)


def json_error(message: str, status: int = 400, details: Any | None = None) -> tuple[Response, int]:
    payload: dict[str, Any] = {"error": message}
    if details is not None:
        payload["details"] = details
    return jsonify(payload), status


def to_int(value: Any, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} должно быть целым числом")


def to_float(value: Any, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} должно быть числом")


def quarter_for_month(month: int) -> int:
    if month < 1 or month > 12:
        raise ValueError("Месяц должен быть в диапазоне 1..12")
    return ((month - 1) // 3) + 1


def get_or_create_period(conn, year: int, month: int) -> dict:
    row = conn.execute(
        "SELECT * FROM periods WHERE year = ? AND month = ?",
        (year, month),
    ).fetchone()
    if row:
        return dict(row)

    quarter = quarter_for_month(month)
    conn.execute(
        """
        INSERT INTO periods (year, month, quarter, status)
        VALUES (?, ?, ?, 'draft')
        """,
        (year, month, quarter),
    )
    row = conn.execute(
        "SELECT * FROM periods WHERE year = ? AND month = ?",
        (year, month),
    ).fetchone()
    return dict(row)


def get_active_criteria(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT *
        FROM criteria
        WHERE is_active = 1
        ORDER BY sort_order ASC, id ASC
        """
    ).fetchall()
    return rows_to_dicts(rows)


def get_criteria_weight_status(conn) -> dict:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(weight), 0) AS total_weight,
               COUNT(1) AS active_count
        FROM criteria
        WHERE is_active = 1
        """
    ).fetchone()
    total = float(row["total_weight"])
    return {
        "total_weight": total,
        "active_count": int(row["active_count"]),
        "is_valid": abs(total - 100.0) < 1e-9,
    }


def get_department(conn, department_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM departments WHERE id = ?",
        (department_id,),
    ).fetchone()
    return dict(row) if row else None


def get_department_employees(conn, department_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT *
        FROM employees
        WHERE department_id = ?
        ORDER BY full_name ASC
        """,
        (department_id,),
    ).fetchall()
    return rows_to_dicts(rows)


def get_monthly_review_snapshot(conn, year: int, month: int, department_id: int) -> dict:
    period = get_or_create_period(conn, year, month)
    criteria = get_active_criteria(conn)

    department = get_department(conn, department_id)
    if not department:
        raise ValueError("Отдел не найден")

    employees = get_department_employees(conn, department_id)
    participating = [
        employee
        for employee in employees
        if is_employee_active_in_month(employee, year, month)
    ]

    employee_ids = [employee["id"] for employee in participating]
    criterion_ids = [criterion["id"] for criterion in criteria]

    scores_map: dict[int, dict[int, dict]] = {employee_id: {} for employee_id in employee_ids}
    if employee_ids and criterion_ids:
        rows = conn.execute(
            f"""
            SELECT employee_id, criterion_id, score, comment
            FROM monthly_scores
            WHERE period_id = ?
              AND employee_id IN ({','.join(['?'] * len(employee_ids))})
              AND criterion_id IN ({','.join(['?'] * len(criterion_ids))})
            """,
            [period["id"], *employee_ids, *criterion_ids],
        ).fetchall()
        for row in rows:
            scores_map[row["employee_id"]][row["criterion_id"]] = {
                "score": row["score"],
                "comment": row["comment"],
            }

    items: list[dict] = []
    monthly_totals: list[float] = []
    for employee in participating:
        by_criterion = scores_map.get(employee["id"], {})
        numeric_scores = {
            criterion_id: payload["score"]
            for criterion_id, payload in by_criterion.items()
        }
        month_score = weighted_month_score(criteria, numeric_scores)
        if month_score is not None:
            monthly_totals.append(month_score)

        missing = [
            criterion["id"]
            for criterion in criteria
            if criterion["id"] not in by_criterion
        ]

        items.append(
            {
                "employee": employee,
                "scores": by_criterion,
                "monthly_score": round(month_score, 4) if month_score is not None else None,
                "missing_criteria": missing,
            }
        )

    department_avg = round(sum(monthly_totals) / len(monthly_totals), 4) if monthly_totals else None

    return {
        "period": period,
        "department": department,
        "criteria": criteria,
        "employees": items,
        "department_avg": department_avg,
        "weights": get_criteria_weight_status(conn),
    }


def get_quarter_metrics(conn, year: int, quarter: int, department_id: int) -> dict:
    department = get_department(conn, department_id)
    if not department:
        raise ValueError("Отдел не найден")

    months = quarter_months(quarter)
    criteria = get_active_criteria(conn)
    employees = get_department_employees(conn, department_id)

    period_rows = conn.execute(
        """
        SELECT *
        FROM periods
        WHERE year = ?
          AND month IN (?, ?, ?)
        """,
        (year, months[0], months[1], months[2]),
    ).fetchall()
    periods_by_month = {row["month"]: dict(row) for row in period_rows}

    period_ids = [row["id"] for row in period_rows]
    employee_ids = [employee["id"] for employee in employees]
    criterion_ids = [criterion["id"] for criterion in criteria]

    score_map: dict[int, dict[int, dict[int, int]]] = {}
    if period_ids and employee_ids and criterion_ids:
        rows = conn.execute(
            f"""
            SELECT employee_id, period_id, criterion_id, score
            FROM monthly_scores
            WHERE period_id IN ({','.join(['?'] * len(period_ids))})
              AND employee_id IN ({','.join(['?'] * len(employee_ids))})
              AND criterion_id IN ({','.join(['?'] * len(criterion_ids))})
            """,
            [*period_ids, *employee_ids, *criterion_ids],
        ).fetchall()
        for row in rows:
            by_employee = score_map.setdefault(row["employee_id"], {})
            by_period = by_employee.setdefault(row["period_id"], {})
            by_period[row["criterion_id"]] = row["score"]

    today = date.today().isoformat()

    metrics: list[dict] = []
    quarter_avg_values: list[float] = []
    for employee in employees:
        monthly_scores: dict[int, float | None] = {}
        scored_months = 0
        quarter_points = 0.0

        for month in months:
            if not is_employee_active_in_month(employee, year, month):
                monthly_scores[month] = None
                continue

            period = periods_by_month.get(month)
            if not period:
                monthly_scores[month] = None
                continue

            employee_period_scores = (
                score_map.get(employee["id"], {}).get(period["id"], {})
            )
            month_score = weighted_month_score(criteria, employee_period_scores)
            if month_score is None:
                monthly_scores[month] = None
                continue

            monthly_scores[month] = round(month_score, 4)
            scored_months += 1
            quarter_points += month_score

        quarter_avg = (quarter_points / scored_months) if scored_months else None
        if quarter_avg is not None:
            quarter_avg_values.append(quarter_avg)

        currently_active = bool(employee["is_active"])
        dismissal_date = employee.get("dismissal_date")
        if dismissal_date and dismissal_date <= today:
            currently_active = False

        metrics.append(
            {
                "employee": employee,
                "monthly_scores": monthly_scores,
                "scored_months": scored_months,
                "quarter_points": round(quarter_points, 4),
                "quarter_avg_score": round(quarter_avg, 4) if quarter_avg is not None else None,
                "is_currently_active": currently_active,
            }
        )

    department_quarter_avg = (
        round(sum(quarter_avg_values) / len(quarter_avg_values), 4)
        if quarter_avg_values
        else None
    )

    return {
        "department": department,
        "year": year,
        "quarter": quarter,
        "months": months,
        "periods": periods_by_month,
        "criteria": criteria,
        "employees": metrics,
        "department_quarter_avg": department_quarter_avg,
    }


def ensure_quarter_months_completed(conn, year: int, quarter: int) -> list[dict]:
    months = quarter_months(quarter)
    period_rows = conn.execute(
        """
        SELECT year, month, status
        FROM periods
        WHERE year = ?
          AND month IN (?, ?, ?)
        ORDER BY month ASC
        """,
        (year, months[0], months[1], months[2]),
    ).fetchall()
    by_month = {row["month"]: dict(row) for row in period_rows}

    missing = []
    for month in months:
        period = by_month.get(month)
        if not period:
            missing.append({"month": month, "reason": "period_missing"})
            continue
        if period["status"] not in ("completed", "locked"):
            missing.append({"month": month, "reason": f"status_{period['status']}"})
    return missing


def calculate_bonus_distribution(
    pool_amount: float,
    threshold_type: str,
    threshold_value: float,
    distribution_mode: str,
    employee_metrics: list[dict],
) -> list[dict]:
    pool = Decimal(str(pool_amount)).quantize(Decimal("0.01"))

    prepared: list[dict] = []
    for item in employee_metrics:
        quarter_points = float(item["quarter_points"])
        quarter_avg = item["quarter_avg_score"]
        scored_months = int(item["scored_months"])

        eligibility_reasons: list[str] = []
        if quarter_avg is None:
            eligibility_reasons.append("no_quarter_score")
        if not item["is_currently_active"]:
            eligibility_reasons.append("inactive_on_calculation_date")

        if threshold_type == "avg_score":
            threshold_ok = quarter_avg is not None and float(quarter_avg) >= threshold_value
            threshold_points_equivalent = threshold_value * max(scored_months, 1)
        else:
            threshold_ok = quarter_points >= threshold_value
            threshold_points_equivalent = threshold_value

        if not threshold_ok:
            eligibility_reasons.append("below_threshold")

        distributable_points = 0.0
        if not eligibility_reasons:
            if distribution_mode == "eligible_full_points":
                distributable_points = quarter_points
            else:
                distributable_points = max(0.0, quarter_points - threshold_points_equivalent)
                if distributable_points <= 0:
                    eligibility_reasons.append("no_points_above_threshold")

        prepared.append(
            {
                **item,
                "is_eligible": len(eligibility_reasons) == 0,
                "eligibility_reasons": eligibility_reasons,
                "threshold_points_equivalent": round(threshold_points_equivalent, 4),
                "distributable_points": round(distributable_points, 6),
                "raw_bonus": Decimal("0.00"),
                "bonus_amount": Decimal("0.00"),
                "fractional": Decimal("0.00"),
            }
        )

    eligible = [x for x in prepared if x["is_eligible"] and x["distributable_points"] > 0]
    total_points = sum(x["distributable_points"] for x in eligible)

    if pool > 0 and total_points > 0:
        total_points_decimal = Decimal(str(total_points))
        for row in eligible:
            raw = pool * Decimal(str(row["distributable_points"])) / total_points_decimal
            rounded = money_round_down(raw)
            row["raw_bonus"] = raw
            row["bonus_amount"] = rounded
            row["fractional"] = raw - rounded

        already_distributed = sum((row["bonus_amount"] for row in eligible), Decimal("0.00"))
        remainder_cents = int((pool - already_distributed) * 100)

        ranked = sorted(
            eligible,
            key=lambda x: (
                x["fractional"],
                Decimal(str(x["quarter_points"])),
                Decimal(str(x["quarter_avg_score"] or 0)),
            ),
            reverse=True,
        )

        for idx in range(remainder_cents):
            ranked[idx % len(ranked)]["bonus_amount"] += Decimal("0.01")

    for row in prepared:
        row["bonus_amount"] = float(row["bonus_amount"])
        row["raw_bonus"] = float(row["raw_bonus"])
        row["fractional"] = float(row["fractional"])

    return prepared


def save_bonus_results(
    conn,
    year: int,
    quarter: int,
    department_id: int,
    pool_amount: float,
    threshold_type: str,
    threshold_value: float,
    distribution_mode: str,
    results: list[dict],
) -> None:
    existing_pool = conn.execute(
        """
        SELECT *
        FROM bonus_pools
        WHERE year = ? AND quarter = ? AND department_id = ?
        """,
        (year, quarter, department_id),
    ).fetchone()

    if existing_pool and existing_pool["is_locked"]:
        raise ValueError("Фонд премий заблокирован, расчет недоступен")

    if existing_pool:
        conn.execute(
            """
            UPDATE bonus_pools
            SET bonus_pool_amount = ?,
                minimum_threshold_type = ?,
                minimum_threshold_value = ?,
                distribution_mode = ?,
                calculated_at = datetime('now'),
                updated_at = datetime('now')
            WHERE year = ? AND quarter = ? AND department_id = ?
            """,
            (
                pool_amount,
                threshold_type,
                threshold_value,
                distribution_mode,
                year,
                quarter,
                department_id,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO bonus_pools (
                year,
                quarter,
                department_id,
                bonus_pool_amount,
                minimum_threshold_type,
                minimum_threshold_value,
                distribution_mode,
                calculated_at,
                is_locked
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), 0)
            """,
            (
                year,
                quarter,
                department_id,
                pool_amount,
                threshold_type,
                threshold_value,
                distribution_mode,
            ),
        )

    conn.execute(
        """
        DELETE FROM bonus_results
        WHERE year = ? AND quarter = ? AND department_id = ?
        """,
        (year, quarter, department_id),
    )

    conn.executemany(
        """
        INSERT INTO bonus_results (
            year,
            quarter,
            department_id,
            employee_id,
            quarter_points,
            quarter_avg_score,
            is_eligible,
            bonus_amount,
            calculation_details,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
        [
            (
                year,
                quarter,
                department_id,
                row["employee"]["id"],
                row["quarter_points"],
                row["quarter_avg_score"],
                1 if row["is_eligible"] else 0,
                row["bonus_amount"],
                json.dumps(
                    {
                        "reasons": row["eligibility_reasons"],
                        "distributable_points": row["distributable_points"],
                        "raw_bonus": row["raw_bonus"],
                        "fractional": row["fractional"],
                    },
                    ensure_ascii=False,
                ),
            )
            for row in results
        ],
    )


@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.get("/api/health")
def health() -> Response:
    return jsonify({"status": "ok", "db": str(DB_PATH)})


@app.get("/api/departments")
def list_departments() -> Response:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM departments
            ORDER BY is_active DESC, name ASC
            """
        ).fetchall()
        return jsonify(rows_to_dicts(rows))


@app.post("/api/departments")
def create_department() -> tuple[Response, int] | Response:
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return json_error("Название отдела обязательно")

    is_active = 1 if payload.get("is_active", True) else 0

    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO departments (name, is_active)
                VALUES (?, ?)
                """,
                (name, is_active),
            )
            row = conn.execute("SELECT * FROM departments WHERE id = last_insert_rowid()")
            return jsonify(dict(row.fetchone())), 201
    except Exception as exc:
        return json_error(f"Не удалось создать отдел: {exc}")


@app.put("/api/departments/<int:department_id>")
def update_department(department_id: int) -> tuple[Response, int] | Response:
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return json_error("Название отдела обязательно")

    is_active = 1 if payload.get("is_active", True) else 0

    with get_connection() as conn:
        exists = get_department(conn, department_id)
        if not exists:
            return json_error("Отдел не найден", 404)

        conn.execute(
            """
            UPDATE departments
            SET name = ?,
                is_active = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (name, is_active, department_id),
        )
        row = conn.execute("SELECT * FROM departments WHERE id = ?", (department_id,)).fetchone()
        return jsonify(dict(row))


@app.get("/api/employees")
def list_employees() -> tuple[Response, int] | Response:
    department_id = request.args.get("department_id")
    active_only = request.args.get("active_only") == "1"

    clauses = ["1=1"]
    params: list[Any] = []

    if department_id:
        try:
            dept_id = to_int(department_id, "department_id")
            clauses.append("e.department_id = ?")
            params.append(dept_id)
        except ValueError as exc:
            return json_error(str(exc))

    if active_only:
        clauses.append("e.is_active = 1")

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT e.*, d.name AS department_name
            FROM employees e
            JOIN departments d ON d.id = e.department_id
            WHERE {' AND '.join(clauses)}
            ORDER BY e.full_name ASC
            """,
            params,
        ).fetchall()
        return jsonify(rows_to_dicts(rows))


@app.post("/api/employees")
def create_employee() -> tuple[Response, int] | Response:
    payload = request.get_json(silent=True) or {}

    full_name = (payload.get("full_name") or "").strip()
    position = (payload.get("position") or "").strip()
    hire_date = (payload.get("hire_date") or "").strip()
    dismissal_date = (payload.get("dismissal_date") or "").strip() or None
    notes = (payload.get("notes") or "").strip() or None

    if not full_name:
        return json_error("ФИО сотрудника обязательно")
    if not hire_date:
        return json_error("Дата приема обязательна")

    try:
        department_id = to_int(payload.get("department_id"), "department_id")
    except ValueError as exc:
        return json_error(str(exc))

    is_active = 1 if payload.get("is_active", True) else 0

    with get_connection() as conn:
        if not get_department(conn, department_id):
            return json_error("Отдел не найден")

        conn.execute(
            """
            INSERT INTO employees (
                full_name,
                department_id,
                position,
                hire_date,
                dismissal_date,
                is_active,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (full_name, department_id, position, hire_date, dismissal_date, is_active, notes),
        )

        row = conn.execute(
            """
            SELECT e.*, d.name AS department_name
            FROM employees e
            JOIN departments d ON d.id = e.department_id
            WHERE e.id = last_insert_rowid()
            """
        ).fetchone()
        return jsonify(dict(row)), 201


@app.put("/api/employees/<int:employee_id>")
def update_employee(employee_id: int) -> tuple[Response, int] | Response:
    payload = request.get_json(silent=True) or {}

    full_name = (payload.get("full_name") or "").strip()
    position = (payload.get("position") or "").strip()
    hire_date = (payload.get("hire_date") or "").strip()
    dismissal_date = (payload.get("dismissal_date") or "").strip() or None
    notes = (payload.get("notes") or "").strip() or None

    if not full_name:
        return json_error("ФИО сотрудника обязательно")
    if not hire_date:
        return json_error("Дата приема обязательна")

    try:
        department_id = to_int(payload.get("department_id"), "department_id")
    except ValueError as exc:
        return json_error(str(exc))

    is_active = 1 if payload.get("is_active", True) else 0

    with get_connection() as conn:
        exists = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
        if not exists:
            return json_error("Сотрудник не найден", 404)
        if not get_department(conn, department_id):
            return json_error("Отдел не найден")

        conn.execute(
            """
            UPDATE employees
            SET full_name = ?,
                department_id = ?,
                position = ?,
                hire_date = ?,
                dismissal_date = ?,
                is_active = ?,
                notes = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                full_name,
                department_id,
                position,
                hire_date,
                dismissal_date,
                is_active,
                notes,
                employee_id,
            ),
        )

        row = conn.execute(
            """
            SELECT e.*, d.name AS department_name
            FROM employees e
            JOIN departments d ON d.id = e.department_id
            WHERE e.id = ?
            """,
            (employee_id,),
        ).fetchone()
        return jsonify(dict(row))


@app.get("/api/criteria")
def list_criteria() -> Response:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM criteria
            ORDER BY sort_order ASC, id ASC
            """
        ).fetchall()
        return jsonify(
            {
                "items": rows_to_dicts(rows),
                "weights": get_criteria_weight_status(conn),
            }
        )


@app.post("/api/criteria")
def create_criterion() -> tuple[Response, int] | Response:
    payload = request.get_json(silent=True) or {}

    name = (payload.get("name") or "").strip()
    description = (payload.get("description") or "").strip() or None

    if not name:
        return json_error("Название критерия обязательно")

    try:
        weight = to_float(payload.get("weight"), "weight")
    except ValueError as exc:
        return json_error(str(exc))

    if weight <= 0:
        return json_error("Вес должен быть положительным")

    sort_order = to_int(payload.get("sort_order", 0), "sort_order")
    is_active = 1 if payload.get("is_active", True) else 0

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO criteria (name, description, weight, is_active, sort_order)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, description, weight, is_active, sort_order),
        )
        row = conn.execute("SELECT * FROM criteria WHERE id = last_insert_rowid()").fetchone()
        return jsonify({"item": dict(row), "weights": get_criteria_weight_status(conn)}), 201


@app.put("/api/criteria/<int:criterion_id>")
def update_criterion(criterion_id: int) -> tuple[Response, int] | Response:
    payload = request.get_json(silent=True) or {}

    name = (payload.get("name") or "").strip()
    description = (payload.get("description") or "").strip() or None

    if not name:
        return json_error("Название критерия обязательно")

    try:
        weight = to_float(payload.get("weight"), "weight")
        sort_order = to_int(payload.get("sort_order", 0), "sort_order")
    except ValueError as exc:
        return json_error(str(exc))

    if weight <= 0:
        return json_error("Вес должен быть положительным")

    is_active = 1 if payload.get("is_active", True) else 0

    with get_connection() as conn:
        exists = conn.execute("SELECT * FROM criteria WHERE id = ?", (criterion_id,)).fetchone()
        if not exists:
            return json_error("Критерий не найден", 404)

        conn.execute(
            """
            UPDATE criteria
            SET name = ?,
                description = ?,
                weight = ?,
                is_active = ?,
                sort_order = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (name, description, weight, is_active, sort_order, criterion_id),
        )

        row = conn.execute("SELECT * FROM criteria WHERE id = ?", (criterion_id,)).fetchone()
        return jsonify({"item": dict(row), "weights": get_criteria_weight_status(conn)})


@app.get("/api/criteria/weights-status")
def criterion_weights_status() -> Response:
    with get_connection() as conn:
        return jsonify(get_criteria_weight_status(conn))


@app.get("/api/reviews/monthly")
def get_monthly_review() -> tuple[Response, int] | Response:
    try:
        year = to_int(request.args.get("year"), "year")
        month = to_int(request.args.get("month"), "month")
        department_id = to_int(request.args.get("department_id"), "department_id")
    except ValueError as exc:
        return json_error(str(exc))

    with get_connection() as conn:
        try:
            payload = get_monthly_review_snapshot(conn, year, month, department_id)
            return jsonify(payload)
        except ValueError as exc:
            return json_error(str(exc))


@app.post("/api/reviews/monthly/save")
def save_monthly_review() -> tuple[Response, int] | Response:
    payload = request.get_json(silent=True) or {}

    try:
        year = to_int(payload.get("year"), "year")
        month = to_int(payload.get("month"), "month")
        department_id = to_int(payload.get("department_id"), "department_id")
    except ValueError as exc:
        return json_error(str(exc))

    entries = payload.get("entries") or []
    if not isinstance(entries, list):
        return json_error("entries должен быть массивом")

    with get_connection() as conn:
        try:
            period = get_or_create_period(conn, year, month)
        except ValueError as exc:
            return json_error(str(exc))

        if period["status"] == "locked":
            return json_error("Период заблокирован", 409)

        department = get_department(conn, department_id)
        if not department:
            return json_error("Отдел не найден")

        criteria = get_active_criteria(conn)
        criterion_ids = {criterion["id"] for criterion in criteria}
        employees = get_department_employees(conn, department_id)
        participant_ids = {
            employee["id"]
            for employee in employees
            if is_employee_active_in_month(employee, year, month)
        }

        for item in entries:
            try:
                employee_id = to_int(item.get("employee_id"), "employee_id")
                criterion_id = to_int(item.get("criterion_id"), "criterion_id")
                score = to_int(item.get("score"), "score")
            except ValueError as exc:
                return json_error(str(exc))

            comment = (item.get("comment") or "").strip() or None

            if employee_id not in participant_ids:
                return json_error(
                    f"Сотрудник #{employee_id} не участвует в оценке за выбранный месяц"
                )
            if criterion_id not in criterion_ids:
                return json_error(f"Критерий #{criterion_id} не активен")
            if score < 1 or score > 10:
                return json_error("Оценка должна быть в диапазоне 1..10")
            if (score <= 4 or score >= 9) and not comment:
                return json_error(
                    "Для оценок <=4 или >=9 комментарий обязателен",
                    details={"employee_id": employee_id, "criterion_id": criterion_id},
                )

            conn.execute(
                """
                INSERT INTO monthly_scores (employee_id, period_id, criterion_id, score, comment)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(employee_id, period_id, criterion_id)
                DO UPDATE SET
                    score = excluded.score,
                    comment = excluded.comment,
                    updated_at = datetime('now')
                """,
                (employee_id, period["id"], criterion_id, score, comment),
            )

        snapshot = get_monthly_review_snapshot(conn, year, month, department_id)
        return jsonify(snapshot)


@app.post("/api/reviews/monthly/complete")
def complete_month() -> tuple[Response, int] | Response:
    payload = request.get_json(silent=True) or {}

    try:
        year = to_int(payload.get("year"), "year")
        month = to_int(payload.get("month"), "month")
        department_id = to_int(payload.get("department_id"), "department_id")
    except ValueError as exc:
        return json_error(str(exc))

    with get_connection() as conn:
        period = get_or_create_period(conn, year, month)
        if period["status"] == "locked":
            return json_error("Период уже заблокирован", 409)

        weight_status = get_criteria_weight_status(conn)
        if not weight_status["is_valid"]:
            return json_error(
                "Сумма весов активных критериев должна быть равна 100",
                details=weight_status,
            )

        snapshot = get_monthly_review_snapshot(conn, year, month, department_id)
        missing = [
            {
                "employee_id": item["employee"]["id"],
                "employee_name": item["employee"]["full_name"],
                "missing_criteria": item["missing_criteria"],
            }
            for item in snapshot["employees"]
            if item["missing_criteria"]
        ]
        if missing:
            return json_error(
                "Нельзя завершить месяц: заполнены не все обязательные оценки",
                details=missing,
            )

        conn.execute(
            """
            UPDATE periods
            SET status = 'completed',
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (period["id"],),
        )

        row = conn.execute("SELECT * FROM periods WHERE id = ?", (period["id"],)).fetchone()
        return jsonify({"period": dict(row), "message": "Период завершен"})


@app.post("/api/reviews/monthly/lock")
def lock_month() -> tuple[Response, int] | Response:
    payload = request.get_json(silent=True) or {}
    try:
        year = to_int(payload.get("year"), "year")
        month = to_int(payload.get("month"), "month")
    except ValueError as exc:
        return json_error(str(exc))

    with get_connection() as conn:
        period = get_or_create_period(conn, year, month)
        conn.execute(
            """
            UPDATE periods
            SET status = 'locked',
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (period["id"],),
        )
        row = conn.execute("SELECT * FROM periods WHERE id = ?", (period["id"],)).fetchone()
        return jsonify({"period": dict(row), "message": "Период заблокирован"})


@app.get("/api/reviews/quarterly")
def quarterly_review() -> tuple[Response, int] | Response:
    try:
        year = to_int(request.args.get("year"), "year")
        quarter = to_int(request.args.get("quarter"), "quarter")
        department_id = to_int(request.args.get("department_id"), "department_id")
    except ValueError as exc:
        return json_error(str(exc))

    with get_connection() as conn:
        try:
            result = get_quarter_metrics(conn, year, quarter, department_id)
            return jsonify(result)
        except ValueError as exc:
            return json_error(str(exc))


@app.post("/api/bonus/calculate")
def calculate_bonus() -> tuple[Response, int] | Response:
    payload = request.get_json(silent=True) or {}

    try:
        year = to_int(payload.get("year"), "year")
        quarter = to_int(payload.get("quarter"), "quarter")
        department_id = to_int(payload.get("department_id"), "department_id")
        bonus_pool_amount = to_float(payload.get("bonus_pool_amount"), "bonus_pool_amount")
        minimum_threshold_value = to_float(payload.get("minimum_threshold_value"), "minimum_threshold_value")
    except ValueError as exc:
        return json_error(str(exc))

    if bonus_pool_amount < 0:
        return json_error("bonus_pool_amount не может быть отрицательным")
    if minimum_threshold_value < 0:
        return json_error("minimum_threshold_value не может быть отрицательным")

    threshold_type = payload.get("minimum_threshold_type", "avg_score")
    distribution_mode = payload.get("distribution_mode", "eligible_full_points")

    if threshold_type not in ("avg_score", "points"):
        return json_error("minimum_threshold_type должен быть avg_score или points")
    if distribution_mode not in ("eligible_full_points", "above_threshold_only"):
        return json_error("distribution_mode должен быть eligible_full_points или above_threshold_only")

    with get_connection() as conn:
        missing_periods = ensure_quarter_months_completed(conn, year, quarter)
        if missing_periods:
            return json_error(
                "Нельзя рассчитать премию: не завершены все 3 месяца квартала",
                details=missing_periods,
            )

        try:
            quarter_data = get_quarter_metrics(conn, year, quarter, department_id)
        except ValueError as exc:
            return json_error(str(exc))

        results = calculate_bonus_distribution(
            bonus_pool_amount,
            threshold_type,
            minimum_threshold_value,
            distribution_mode,
            quarter_data["employees"],
        )

        try:
            save_bonus_results(
                conn,
                year,
                quarter,
                department_id,
                bonus_pool_amount,
                threshold_type,
                minimum_threshold_value,
                distribution_mode,
                results,
            )
        except ValueError as exc:
            return json_error(str(exc), 409)

        return jsonify(
            {
                "meta": {
                    "year": year,
                    "quarter": quarter,
                    "department_id": department_id,
                    "bonus_pool_amount": round(bonus_pool_amount, 2),
                    "minimum_threshold_type": threshold_type,
                    "minimum_threshold_value": minimum_threshold_value,
                    "distribution_mode": distribution_mode,
                },
                "results": results,
            }
        )


@app.get("/api/bonus/results")
def bonus_results() -> tuple[Response, int] | Response:
    try:
        year = to_int(request.args.get("year"), "year")
        quarter = to_int(request.args.get("quarter"), "quarter")
        department_id = to_int(request.args.get("department_id"), "department_id")
    except ValueError as exc:
        return json_error(str(exc))

    with get_connection() as conn:
        pool = conn.execute(
            """
            SELECT bp.*, d.name AS department_name
            FROM bonus_pools bp
            JOIN departments d ON d.id = bp.department_id
            WHERE bp.year = ? AND bp.quarter = ? AND bp.department_id = ?
            """,
            (year, quarter, department_id),
        ).fetchone()

        rows = conn.execute(
            """
            SELECT br.*, e.full_name, e.position
            FROM bonus_results br
            JOIN employees e ON e.id = br.employee_id
            WHERE br.year = ?
              AND br.quarter = ?
              AND br.department_id = ?
            ORDER BY br.bonus_amount DESC, e.full_name ASC
            """,
            (year, quarter, department_id),
        ).fetchall()

        return jsonify(
            {
                "pool": dict(pool) if pool else None,
                "results": rows_to_dicts(rows),
            }
        )


@app.get("/api/reports/employee/<int:employee_id>")
def employee_report(employee_id: int) -> tuple[Response, int] | Response:
    year_raw = request.args.get("year")
    quarter_raw = request.args.get("quarter")

    with get_connection() as conn:
        employee = conn.execute(
            """
            SELECT e.*, d.name AS department_name
            FROM employees e
            JOIN departments d ON d.id = e.department_id
            WHERE e.id = ?
            """,
            (employee_id,),
        ).fetchone()

        if not employee:
            return json_error("Сотрудник не найден", 404)

        params: list[Any] = [employee_id]
        where_clause = "ms.employee_id = ?"

        if year_raw is not None:
            try:
                year = to_int(year_raw, "year")
            except ValueError as exc:
                return json_error(str(exc))
            where_clause += " AND p.year = ?"
            params.append(year)

        monthly_rows = conn.execute(
            f"""
            SELECT
                p.year,
                p.month,
                SUM(ms.score * c.weight) / SUM(c.weight) AS monthly_score
            FROM monthly_scores ms
            JOIN periods p ON p.id = ms.period_id
            JOIN criteria c ON c.id = ms.criterion_id
            WHERE {where_clause}
            GROUP BY p.year, p.month
            ORDER BY p.year, p.month
            """,
            params,
        ).fetchall()

        bonus_row = None
        if year_raw is not None and quarter_raw is not None:
            try:
                quarter = to_int(quarter_raw, "quarter")
                year = to_int(year_raw, "year")
            except ValueError as exc:
                return json_error(str(exc))

            bonus_row = conn.execute(
                """
                SELECT *
                FROM bonus_results
                WHERE year = ?
                  AND quarter = ?
                  AND employee_id = ?
                """,
                (year, quarter, employee_id),
            ).fetchone()

        return jsonify(
            {
                "employee": dict(employee),
                "monthly_scores": rows_to_dicts(monthly_rows),
                "quarter_bonus": dict(bonus_row) if bonus_row else None,
            }
        )


@app.get("/api/reports/department")
def department_report() -> tuple[Response, int] | Response:
    try:
        year = to_int(request.args.get("year"), "year")
        quarter = to_int(request.args.get("quarter"), "quarter")
        department_id = to_int(request.args.get("department_id"), "department_id")
    except ValueError as exc:
        return json_error(str(exc))

    with get_connection() as conn:
        try:
            quarter_data = get_quarter_metrics(conn, year, quarter, department_id)
        except ValueError as exc:
            return json_error(str(exc))

        bonuses = conn.execute(
            """
            SELECT br.*, e.full_name
            FROM bonus_results br
            JOIN employees e ON e.id = br.employee_id
            WHERE br.year = ?
              AND br.quarter = ?
              AND br.department_id = ?
            ORDER BY br.bonus_amount DESC
            """,
            (year, quarter, department_id),
        ).fetchall()

        pool = conn.execute(
            """
            SELECT *
            FROM bonus_pools
            WHERE year = ? AND quarter = ? AND department_id = ?
            """,
            (year, quarter, department_id),
        ).fetchone()

        return jsonify(
            {
                "department": quarter_data["department"],
                "year": year,
                "quarter": quarter,
                "department_quarter_avg": quarter_data["department_quarter_avg"],
                "employees": quarter_data["employees"],
                "bonus_pool": dict(pool) if pool else None,
                "bonus_distribution": rows_to_dicts(bonuses),
            }
        )


def get_export_rows(conn, year: int, quarter: int, department_id: int) -> list[dict]:
    quarter_data = get_quarter_metrics(conn, year, quarter, department_id)
    rows = []

    bonus_rows = conn.execute(
        """
        SELECT *
        FROM bonus_results
        WHERE year = ?
          AND quarter = ?
          AND department_id = ?
        """,
        (year, quarter, department_id),
    ).fetchall()
    bonus_by_employee = {row["employee_id"]: dict(row) for row in bonus_rows}

    for item in quarter_data["employees"]:
        employee = item["employee"]
        bonus = bonus_by_employee.get(employee["id"], {})
        rows.append(
            {
                "employee_id": employee["id"],
                "employee": employee["full_name"],
                "position": employee["position"],
                f"month_{quarter_data['months'][0]}": item["monthly_scores"].get(quarter_data["months"][0]),
                f"month_{quarter_data['months'][1]}": item["monthly_scores"].get(quarter_data["months"][1]),
                f"month_{quarter_data['months'][2]}": item["monthly_scores"].get(quarter_data["months"][2]),
                "quarter_points": item["quarter_points"],
                "quarter_avg_score": item["quarter_avg_score"],
                "is_eligible": bonus.get("is_eligible", 0),
                "bonus_amount": bonus.get("bonus_amount", 0),
            }
        )

    return rows


@app.get("/api/reports/quarter/export.csv")
def export_quarter_csv() -> tuple[Response, int] | Response:
    try:
        year = to_int(request.args.get("year"), "year")
        quarter = to_int(request.args.get("quarter"), "quarter")
        department_id = to_int(request.args.get("department_id"), "department_id")
    except ValueError as exc:
        return json_error(str(exc))

    with get_connection() as conn:
        try:
            rows = get_export_rows(conn, year, quarter, department_id)
        except ValueError as exc:
            return json_error(str(exc))

    if not rows:
        return json_error("Нет данных для экспорта", 404)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()), delimiter=";")
    writer.writeheader()
    writer.writerows(rows)

    filename = f"quarter_report_{year}_Q{quarter}_dept_{department_id}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/reports/quarter/export.xlsx")
def export_quarter_xlsx() -> tuple[Response, int] | Response:
    if Workbook is None:
        return json_error("Для XLSX-экспорта установите openpyxl")

    try:
        year = to_int(request.args.get("year"), "year")
        quarter = to_int(request.args.get("quarter"), "quarter")
        department_id = to_int(request.args.get("department_id"), "department_id")
    except ValueError as exc:
        return json_error(str(exc))

    with get_connection() as conn:
        try:
            rows = get_export_rows(conn, year, quarter, department_id)
        except ValueError as exc:
            return json_error(str(exc))

    if not rows:
        return json_error("Нет данных для экспорта", 404)

    wb = Workbook()
    ws = wb.active
    ws.title = "Quarter Report"

    headers = list(rows[0].keys())
    ws.append(headers)
    for row in rows:
        ws.append([row.get(h) for h in headers])

    xlsx_path = EXPORTS_DIR / f"quarter_report_{year}_Q{quarter}_dept_{department_id}.xlsx"
    wb.save(xlsx_path)
    return send_file(xlsx_path, as_attachment=True)


@app.post("/api/backup")
def backup_database() -> Response:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = BACKUPS_DIR / f"performance_review_{timestamp}.db"
    shutil.copy2(DB_PATH, target)
    return jsonify({"backup_file": str(target)})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
