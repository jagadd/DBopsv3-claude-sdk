import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT UNIQUE,
    short_description TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    configuration_item TEXT NOT NULL,
    assignment_group TEXT NOT NULL,
    priority INTEGER NOT NULL,
    category TEXT,
    state TEXT NOT NULL DEFAULT 'New',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS work_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT NOT NULL REFERENCES incidents(number),
    kind TEXT NOT NULL,
    author TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

INCIDENT_COLUMNS = (
    "number, short_description, description, configuration_item, assignment_group, "
    "priority, category, state, created_at, updated_at"
)
UPDATABLE = {"assignment_group", "state", "priority"}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@contextmanager
def connect(path: str) -> Iterator[sqlite3.Connection]:
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        with conn:
            yield conn


def init(path: str) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)


def create_incident(path: str, data: dict[str, Any]) -> str:
    now = _now()
    with connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO incidents (short_description, description, configuration_item, assignment_group, "
            "priority, category, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data["short_description"],
                data["description"],
                data["configuration_item"],
                data["assignment_group"],
                data["priority"],
                data["category"],
                now,
                now,
            ),
        )
        number = f"INC{10000 + cur.lastrowid:07d}"
        conn.execute("UPDATE incidents SET number = ? WHERE id = ?", (number, cur.lastrowid))
    return number


def get_incident(path: str, number: str) -> dict[str, Any] | None:
    with connect(path) as conn:
        row = conn.execute(f"SELECT {INCIDENT_COLUMNS} FROM incidents WHERE number = ?", (number,)).fetchone()  # noqa: S608
    return dict(row) if row else None


def list_incidents(path: str) -> list[dict[str, Any]]:
    with connect(path) as conn:
        rows = conn.execute(f"SELECT {INCIDENT_COLUMNS} FROM incidents ORDER BY id DESC").fetchall()  # noqa: S608
    return [dict(r) for r in rows]


def update_incident(path: str, number: str, **fields: Any) -> None:
    unknown = set(fields) - UPDATABLE
    if unknown:
        raise ValueError(f"Cannot update {unknown}")
    assignments = ", ".join(f"{name} = ?" for name in fields)
    with connect(path) as conn:
        conn.execute(
            f"UPDATE incidents SET {assignments}, updated_at = ? WHERE number = ?",  # noqa: S608
            (*fields.values(), _now(), number),
        )


def add_work_note(path: str, number: str, kind: str, author: str, text: str, created_at: str | None = None) -> None:
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO work_notes (number, kind, author, text, created_at) VALUES (?, ?, ?, ?, ?)",
            (number, kind, author, text, created_at or _now()),
        )
        conn.execute("UPDATE incidents SET updated_at = ? WHERE number = ?", (_now(), number))


def list_work_notes(path: str, number: str) -> list[dict[str, Any]]:
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT id, kind, author, text, created_at FROM work_notes WHERE number = ? ORDER BY id DESC",
            (number,),
        ).fetchall()
    return [dict(r) for r in rows]
