from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Transition:
    kind: str
    new_open: bool
    timestamp: float
    duration_seconds: int | None
    previous_alert_sent: bool


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS current_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    garage_open INTEGER,
                    state_since REAL,
                    alert_sent INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL
                );

                INSERT OR IGNORE INTO current_state
                    (id, garage_open, state_since, alert_sent, updated_at)
                VALUES (1, NULL, NULL, 0, NULL);

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_ts REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    garage_open INTEGER NOT NULL,
                    duration_seconds INTEGER,
                    source TEXT NOT NULL DEFAULT 'shelly'
                );

                CREATE INDEX IF NOT EXISTS idx_events_ts ON events(event_ts DESC);

                CREATE TABLE IF NOT EXISTS commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    command_ts REAL NOT NULL,
                    command_type TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    detail TEXT
                );
                """
            )

    def get_current_state(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT garage_open, state_since, alert_sent, updated_at "
                "FROM current_state WHERE id = 1"
            ).fetchone()
        assert row is not None
        return {
            "garage_open": (
                bool(row["garage_open"]) if row["garage_open"] is not None else None
            ),
            "state_since": row["state_since"],
            "alert_sent": bool(row["alert_sent"]),
            "updated_at": row["updated_at"],
        }

    def reconcile(self, new_open: bool, now: float) -> Transition | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT garage_open, state_since, alert_sent "
                "FROM current_state WHERE id = 1"
            ).fetchone()
            assert row is not None

            old_value = row["garage_open"]
            old_open = bool(old_value) if old_value is not None else None
            state_since = row["state_since"]
            alert_sent = bool(row["alert_sent"])

            if old_open is None:
                connection.execute(
                    "UPDATE current_state SET garage_open=?, state_since=?, "
                    "alert_sent=0, updated_at=? WHERE id=1",
                    (int(new_open), now, now),
                )
                connection.execute(
                    "INSERT INTO events(event_ts, event_type, garage_open, source) "
                    "VALUES (?, 'INITIAL', ?, 'startup')",
                    (now, int(new_open)),
                )
                return Transition("INITIAL", new_open, now, None, False)

            if old_open == new_open:
                connection.execute(
                    "UPDATE current_state SET updated_at=? WHERE id=1", (now,)
                )
                return None

            duration: int | None = None
            kind = "OPEN"
            if not new_open:
                kind = "CLOSE"
                if old_open and state_since is not None:
                    duration = max(0, int(now - float(state_since)))

            connection.execute(
                "INSERT INTO events(event_ts, event_type, garage_open, "
                "duration_seconds, source) VALUES (?, ?, ?, ?, 'shelly')",
                (now, kind, int(new_open), duration),
            )
            connection.execute(
                "UPDATE current_state SET garage_open=?, state_since=?, "
                "alert_sent=0, updated_at=? WHERE id=1",
                (int(new_open), now, now),
            )
            return Transition(kind, new_open, now, duration, alert_sent)

    def mark_alert_sent(self, now: float) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE current_state SET alert_sent=1, updated_at=? "
                "WHERE id=1 AND garage_open=1",
                (now,),
            )

    def list_events(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, event_ts, event_type, garage_open, duration_seconds, source "
                "FROM events ORDER BY event_ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def log_command(self, now: float, success: bool, detail: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO commands(command_ts, command_type, success, detail) "
                "VALUES (?, 'PULSE', ?, ?)",
                (now, int(success), detail[:1000]),
            )

    def stats_between(self, start: float, end: float) -> dict[str, int]:
        if end <= start:
            return {"openings": 0, "open_seconds": 0}

        with self._connect() as connection:
            before = connection.execute(
                "SELECT event_ts, garage_open FROM events "
                "WHERE event_ts <= ? ORDER BY event_ts DESC LIMIT 1",
                (start,),
            ).fetchone()
            rows = connection.execute(
                "SELECT event_ts, garage_open, event_type FROM events "
                "WHERE event_ts > ? AND event_ts <= ? ORDER BY event_ts ASC",
                (start, end),
            ).fetchall()

        is_open = bool(before["garage_open"]) if before is not None else False
        cursor = start
        open_seconds = 0.0
        openings = 0

        for row in rows:
            timestamp = min(max(float(row["event_ts"]), start), end)
            if is_open:
                open_seconds += max(0.0, timestamp - cursor)
            new_open = bool(row["garage_open"])
            if row["event_type"] == "OPEN":
                openings += 1
            is_open = new_open
            cursor = timestamp

        if is_open:
            open_seconds += max(0.0, end - cursor)

        return {"openings": openings, "open_seconds": int(open_seconds)}
