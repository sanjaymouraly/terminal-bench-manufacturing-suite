from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import RunResult
from .util import utc_now

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    task_version TEXT NOT NULL,
    fixture_seed INTEGER,
    agent TEXT NOT NULL,
    model TEXT,
    score REAL NOT NULL,
    passed INTEGER NOT NULL,
    status TEXT NOT NULL,
    failure_category TEXT,
    started_at TEXT NOT NULL,
    elapsed_seconds REAL NOT NULL,
    input_tokens INTEGER,
    cache_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL,
    artifact_dir TEXT NOT NULL,
    command_json TEXT NOT NULL,
    diagnostics_json TEXT NOT NULL,
    harbor_version TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_task_started ON runs(task, started_at DESC);
"""


class RunStore:
    """A deliberately small SQLite ledger for local benchmark provenance."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)
            self._migrate(connection)

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        """Add optional telemetry columns to ledgers created by older suite revisions."""
        existing = {str(row[1]) for row in connection.execute("PRAGMA table_info(runs)")}
        for column, sql_type in (
            ("input_tokens", "INTEGER"),
            ("cache_tokens", "INTEGER"),
            ("output_tokens", "INTEGER"),
            ("cost_usd", "REAL"),
        ):
            if column not in existing:
                connection.execute(f"ALTER TABLE runs ADD COLUMN {column} {sql_type}")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def record(self, result: RunResult, harbor_version: str | None) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO runs (
                    run_id, task, task_version, fixture_seed, agent, model, score,
                    passed, status, failure_category, started_at, elapsed_seconds,
                    input_tokens, cache_tokens, output_tokens, cost_usd, artifact_dir,
                    command_json, diagnostics_json, harbor_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.run_id,
                    result.task,
                    result.task_version,
                    result.fixture_seed,
                    result.agent,
                    result.model,
                    result.score,
                    int(result.passed),
                    result.status,
                    result.failure_category,
                    result.started_at,
                    result.elapsed_seconds,
                    result.input_tokens,
                    result.cache_tokens,
                    result.output_tokens,
                    result.cost_usd,
                    result.artifact_dir,
                    json.dumps(result.command),
                    json.dumps(result.diagnostics),
                    harbor_version,
                    utc_now(),
                ),
            )

    def list_runs(self, *, task: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT * FROM runs"
        params: list[Any] = []
        if task:
            query += " WHERE task = ?"
            params.append(task)
        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def all_runs(self) -> list[dict[str, Any]]:
        return self.list_runs(limit=1_000_000)

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["passed"] = bool(value["passed"])
        value["command"] = json.loads(value.pop("command_json"))
        value["diagnostics"] = json.loads(value.pop("diagnostics_json"))
        return value
