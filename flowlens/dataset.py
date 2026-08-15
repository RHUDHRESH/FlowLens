"""Deterministic scenario export and golden-replay hashing."""

from __future__ import annotations

import json
from pathlib import Path

from flowlens.config import stable_hash
from flowlens.contracts.schemas import RunRecord
from flowlens.simulator.runner import simulate_scenario
from flowlens.simulator.scenarios import DEMO_BUTTONS, list_scenarios
from flowlens.version import SIMULATOR_VERSION

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_PATH = REPO_ROOT / "tests" / "golden_replay" / "hashes.json"


def record_hash(record: RunRecord) -> str:
    return stable_hash(
        {
            "events": [e.model_dump(mode="json") for e in record.events],
            "frames": [f.model_dump(mode="json") for f in record.frames],
        }
    )


def generate_scenarios(
    *,
    seed: int = 20260915,
    out_dir: Path | None = None,
    write_golden: bool = True,
) -> dict[str, str]:
    """Write a versioned Parquet/JSON dataset and golden replay hashes."""
    import pandas as pd

    out_dir = out_dir or (REPO_ROOT / "artifacts" / "datasets")
    out_dir.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    index_rows: list[dict] = []

    for spec in list_scenarios():
        record = simulate_scenario(spec.scenario_id, seed=seed)
        digest = record_hash(record)
        hashes[spec.scenario_id] = digest

        events_path = out_dir / f"{spec.scenario_id}_events.json"
        events_path.write_text(
            json.dumps([e.model_dump(mode="json") for e in record.events], indent=2),
            encoding="utf-8",
        )
        frame_rows = []
        for frame in record.frames:
            row = {"timestamp_ms": frame.timestamp_ms, **frame.signals}
            frame_rows.append(row)
        parquet_path = out_dir / f"{spec.scenario_id}_frames.parquet"
        pd.DataFrame(frame_rows).to_parquet(parquet_path, index=False)

        index_rows.append(
            {
                "scenario_id": spec.scenario_id,
                "family": spec.family,
                "seed": seed,
                "run_id": record.run_id,
                "event_count": len(record.events),
                "frame_count": len(record.frames),
                "trace_hash": digest,
                "config_hash": record.config_hash,
                "simulator_version": SIMULATOR_VERSION,
                "withheld": spec.withheld,
            }
        )

    manifest = out_dir / "manifest.json"
    manifest.write_text(json.dumps(index_rows, indent=2), encoding="utf-8")
    pd.DataFrame(index_rows).to_parquet(out_dir / "manifest.parquet", index=False)

    if write_golden:
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "seed": seed,
            "simulator_version": SIMULATOR_VERSION,
            "demo_buttons": [scenario_id for _, scenario_id in DEMO_BUTTONS],
            "hashes": hashes,
        }
        GOLDEN_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    return hashes
