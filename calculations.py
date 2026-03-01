from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_DOWN
from typing import Iterable


@dataclass
class EmployeeQuarterMetric:
    employee_id: int
    full_name: str
    is_active: bool
    monthly_scores: dict[int, float | None]
    scored_months: int
    quarter_points: float
    quarter_avg_score: float | None


def quarter_months(quarter: int) -> list[int]:
    if quarter not in (1, 2, 3, 4):
        raise ValueError("Quarter must be 1..4")
    start = (quarter - 1) * 3 + 1
    return [start, start + 1, start + 2]


def month_end_date(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def is_employee_active_in_month(employee: dict, year: int, month: int) -> bool:
    period_end = month_end_date(year, month)
    hire_date = parse_iso_date(employee.get("hire_date"))
    dismissal_date = parse_iso_date(employee.get("dismissal_date"))

    if hire_date and hire_date > period_end:
        return False
    if dismissal_date and dismissal_date <= period_end:
        return False
    return True


def weighted_month_score(criteria: Iterable[dict], employee_scores: dict[int, int]) -> float | None:
    criteria_list = list(criteria)
    if not criteria_list:
        return None

    weight_sum = sum(float(c["weight"]) for c in criteria_list)
    if weight_sum <= 0:
        return None

    for criterion in criteria_list:
        if criterion["id"] not in employee_scores:
            return None

    total = 0.0
    for criterion in criteria_list:
        score = employee_scores[criterion["id"]]
        total += float(score) * float(criterion["weight"])

    return total / weight_sum


def money_round_down(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
