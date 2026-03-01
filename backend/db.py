from __future__ import annotations

import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "performance_review.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"

DEFAULT_CRITERIA = [
    (
        "Выполнение текущих задач",
        "Насколько стабильно сотрудник закрывает свою операционную работу.",
        30,
        1,
    ),
    (
        "Качество работы",
        "Насколько аккуратно, точно и без переделок выполнены задачи.",
        20,
        2,
    ),
    (
        "Соответствие ценностям",
        "Насколько поведение сотрудника соответствует нормам компании.",
        20,
        3,
    ),
    (
        "Вклад в развитие компании",
        "Идеи, улучшения и участие в развитии процессов.",
        15,
        4,
    ),
    (
        "Инициативность",
        "Насколько сотрудник сам двигает вопросы и не ждет контроля.",
        10,
        5,
    ),
    (
        "Командное взаимодействие",
        "Насколько сотрудник конструктивен и помогает коллегам.",
        5,
        6,
    ),
]


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(schema)
        seed_default_criteria(conn)


def seed_default_criteria(conn: sqlite3.Connection) -> None:
    exists = conn.execute("SELECT COUNT(1) FROM criteria").fetchone()[0]
    if exists:
        return

    conn.executemany(
        """
        INSERT INTO criteria (name, description, weight, is_active, sort_order)
        VALUES (?, ?, ?, 1, ?)
        """,
        [(name, description, weight, sort_order) for name, description, weight, sort_order in DEFAULT_CRITERIA],
    )


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]
