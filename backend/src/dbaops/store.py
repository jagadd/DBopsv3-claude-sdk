"""SQLite store for runs, the per-incident event trace, and approvals."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from typing import Any

from .models import ACTIVE_RUN_STATUSES, Approval, ApprovalStatus, RunStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    ticket_number TEXT NOT NULL,
    status TEXT NOT NULL,
    ticket TEXT NOT NULL,
    session_id TEXT,
    summary TEXT,
    num_turns INTEGER,
    cost_usd REAL,
    started_at TEXT NOT NULL,
    ended_at TEXT
);
CREATE INDEX IF NOT EXISTS runs_ticket ON runs(ticket_number);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    ticket_number TEXT NOT NULL,
    ts TEXT NOT NULL,
    agent TEXT NOT NULL,
    kind TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_ticket ON events(ticket_number, id);
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    ticket_number TEXT NOT NULL,
    agent TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    tool_input TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    decided_at TEXT,
    approver TEXT,
    comment TEXT
);
CREATE INDEX IF NOT EXISTS approvals_ticket ON approvals(ticket_number);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class Store:
    def __init__(self, path: str):
        self._path = path
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            with conn:
                yield conn

    # ----- runs -----

    def recover_after_restart(self) -> None:
        """Runs and approvals that were live when the process stopped can't resume."""
        active = ",".join("?" * len(ACTIVE_RUN_STATUSES))
        with self._connect() as conn:
            conn.execute(
                f"UPDATE runs SET status = ?, ended_at = ? WHERE status IN ({active})",  # noqa: S608
                (RunStatus.INTERRUPTED, _now(), *ACTIVE_RUN_STATUSES),
            )
            conn.execute(
                "UPDATE approvals SET status = ?, decided_at = ? WHERE status = ?",
                (ApprovalStatus.EXPIRED, _now(), ApprovalStatus.PENDING),
            )

    def start_run(self, run_id: str, ticket_number: str, ticket: dict[str, Any]) -> bool:
        """Create a run unless the ticket already has an active one. Atomic."""
        active = ",".join("?" * len(ACTIVE_RUN_STATUSES))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            busy = conn.execute(
                f"SELECT 1 FROM runs WHERE ticket_number = ? AND status IN ({active})",  # noqa: S608
                (ticket_number, *ACTIVE_RUN_STATUSES),
            ).fetchone()
            if busy:
                return False
            conn.execute(
                "INSERT INTO runs (run_id, ticket_number, status, ticket, started_at) VALUES (?, ?, ?, ?, ?)",
                (run_id, ticket_number, RunStatus.RUNNING, json.dumps(ticket), _now()),
            )
        return True

    def update_run(self, run_id: str, **fields: Any) -> None:
        allowed = {"status", "session_id", "summary", "num_turns", "cost_usd", "ended_at"}
        if set(fields) - allowed:
            raise ValueError(f"Unknown run fields {set(fields) - allowed}")
        if fields.get("status") and fields["status"] not in ACTIVE_RUN_STATUSES:
            fields.setdefault("ended_at", _now())
        assignments = ", ".join(f"{k} = ?" for k in fields)
        with self._connect() as conn:
            conn.execute(f"UPDATE runs SET {assignments} WHERE run_id = ?", (*fields.values(), run_id))  # noqa: S608

    def list_runs(self, ticket_number: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE ticket_number = ? ORDER BY started_at DESC", (ticket_number,)
            ).fetchall()
        return [{**dict(r), "ticket": json.loads(r["ticket"])} for r in rows]

    # ----- events -----

    def add_event(self, run_id: str, ticket_number: str, agent: str, kind: str, data: Any) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO events (run_id, ticket_number, ts, agent, kind, data) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, ticket_number, _now(), agent, kind, json.dumps(data, default=str)),
            )

    def list_events(
        self,
        ticket_number: str,
        run_id: str | None = None,
        agent: str | None = None,
        kind: str | None = None,
        after_id: int = 0,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM events WHERE ticket_number = ? AND id > ?"
        params: list[Any] = [ticket_number, after_id]
        for column, value in (("run_id", run_id), ("agent", agent), ("kind", kind)):
            if value:
                sql += f" AND {column} = ?"
                params.append(value)
        sql += " ORDER BY id LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [{**dict(r), "data": json.loads(r["data"])} for r in rows]

    # ----- approvals -----

    def save_approval(self, a: Approval) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO approvals (id, run_id, ticket_number, agent, tool_name, tool_input, status, "
                "requested_at, decided_at, approver, comment) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    a.id,
                    a.run_id,
                    a.ticket_number,
                    a.agent,
                    a.tool_name,
                    json.dumps(a.tool_input),
                    a.status,
                    a.requested_at.isoformat(),
                    a.decided_at.isoformat() if a.decided_at else None,
                    a.approver,
                    a.comment,
                ),
            )

    def list_approvals(self, ticket_number: str | None = None, status: str | None = None) -> list[Approval]:
        sql, params = "SELECT * FROM approvals WHERE 1 = 1", []
        if ticket_number:
            sql += " AND ticket_number = ?"
            params.append(ticket_number)
        if status:
            sql += " AND status = ?"
            params.append(status)
        with self._connect() as conn:
            rows = conn.execute(sql + " ORDER BY requested_at DESC", params).fetchall()
        return [Approval(**{**dict(r), "tool_input": json.loads(r["tool_input"])}) for r in rows]
