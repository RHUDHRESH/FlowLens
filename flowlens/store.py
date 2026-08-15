"""SQLite persistence for runs and incident envelopes.

Deliberately minimal: the envelope is the artifact, so it is stored whole as
JSON alongside the hashes needed to tie it back to the exact data and
configuration that produced it. Nothing here is on the diagnostic hot path.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from flowlens.contracts.schemas import IncidentEnvelope, RunRecord

DEFAULT_DB = Path(__file__).resolve().parent.parent / "artifacts" / "flowlens.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    scenario_id  TEXT NOT NULL,
    asset_id     TEXT NOT NULL,
    journey_id   TEXT NOT NULL,
    seed         INTEGER NOT NULL,
    config_hash  TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    payload      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS incidents (
    incident_id     TEXT PRIMARY KEY,
    run_id          TEXT,
    scenario_id     TEXT,
    decision        TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    raw_trace_hash  TEXT NOT NULL,
    config_hash     TEXT NOT NULL,
    envelope        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_incidents_run ON incidents(run_id);
"""


class Store:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------ #

    def save_run(self, record: RunRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?)",
                (
                    record.run_id,
                    record.scenario_id,
                    record.asset_id,
                    record.journey_id,
                    record.seed,
                    record.config_hash,
                    datetime.now(UTC).isoformat(timespec="seconds"),
                    record.model_dump_json(),
                ),
            )

    def load_run(self, run_id: str) -> RunRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return RunRecord.model_validate_json(row["payload"]) if row else None

    def save_incident(self, envelope: IncidentEnvelope) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO incidents VALUES (?,?,?,?,?,?,?,?)",
                (
                    envelope.incident_id,
                    envelope.run_id,
                    envelope.scenario_id,
                    envelope.decision.value,
                    envelope.created_at,
                    envelope.raw_trace_hash,
                    envelope.config_hash,
                    envelope.model_dump_json(),
                ),
            )

    def load_incident(self, incident_id: str) -> IncidentEnvelope | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT envelope FROM incidents WHERE incident_id = ?", (incident_id,)
            ).fetchone()
        return IncidentEnvelope.model_validate_json(row["envelope"]) if row else None

    def list_incidents(self, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT incident_id, run_id, scenario_id, decision, created_at "
                "FROM incidents ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict:
        with self._connect() as conn:
            runs = conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
            incidents = conn.execute("SELECT COUNT(*) AS n FROM incidents").fetchone()["n"]
            by_decision = conn.execute(
                "SELECT decision, COUNT(*) AS n FROM incidents GROUP BY decision"
            ).fetchall()
        return {
            "runs": runs,
            "incidents": incidents,
            "by_decision": {row["decision"]: row["n"] for row in by_decision},
        }


def to_json(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, default=str)
