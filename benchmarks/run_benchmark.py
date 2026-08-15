"""Benchmark smoke: FlowLens vs alarm lookup vs a static rule DAG.

Results written here are **achieved simulated results** on the committed
scenario registry. They are not field performance and must not be quoted as such.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

from flowlens.contracts.enums import Decision, FaultId
from flowlens.diagnosis.compiler import compile_journey
from flowlens.diagnosis.engine import get_engine
from flowlens.simulator.runner import simulate_scenario
from flowlens.simulator.scenarios import DEMO_BUTTONS, list_scenarios

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLISHED = Path(__file__).resolve().parent / "published_results"

ALARM_LOOKUP: dict[str, str] = {
    "LOCK_PROOF_TIMEOUT": "door_lock_bounce",
    "DOOR_CLOSE_TIMEOUT": "door_obstruction",
    "START_PERMIT_TIMEOUT": "start_permit_missing",
    "SAFETY_CIRCUIT_OPEN": "safety_chain_intermittent",
    "SPEED_FEEDBACK_LOST": "encoder_dropout",
    "SPEED_DEVIATION": "encoder_drift",
    "TORQUE_BUILD_TIMEOUT": "brake_drag",
    "DRIVE_OVERTEMP": "drive_cooling_degradation",
    "DC_BUS_UNDERVOLTAGE": "dc_bus_undervoltage",
    "COMMS_FRAME_LOST": "comms_corruption",
}


def _alarm_lookup(alarms: list[str]) -> str:
    if not alarms:
        return "healthy"
    for alarm in alarms:
        if alarm in ALARM_LOOKUP:
            return ALARM_LOOKUP[alarm]
    return alarms[0].lower()


def _rule_dag(record) -> str:
    compiled = compile_journey(record.observable())
    phases = [segment.phase.value for segment in compiled.segments]
    alarms = compiled.facts.alarms
    if "LOCK_PROVED" not in phases and "DOOR_CLOSING" in phases:
        return "door_lock_bounce"
    if any("SPEED_FEEDBACK" in a or a == "SPEED_DEVIATION" for a in alarms):
        return "encoder_dropout"
    if "TORQUE_BUILD_TIMEOUT" in alarms:
        return "brake_drag"
    if not alarms:
        return "healthy"
    return _alarm_lookup(alarms)


def _top_label(envelope) -> str:
    if envelope.decision == Decision.HEALTHY:
        return "healthy"
    if envelope.decision == Decision.SENSOR_CHECK:
        return "sensor_fault"
    if envelope.decision == Decision.UNKNOWN_FAULT:
        return "unknown"
    if envelope.decision == Decision.HUMAN_REVIEW and envelope.top_hypotheses:
        return envelope.top_hypotheses[0].label
    if envelope.top_hypotheses:
        return envelope.top_hypotheses[0].label
    return envelope.decision.value.lower()


def _truth_label(record) -> str:
    faults = sorted(f.fault_id.value for f in record.ground_truth.injected_faults)
    if record.ground_truth.is_withheld_mechanism:
        return "unknown"
    if not faults:
        return "healthy"
    if FaultId.SENSOR_FAULT.value in faults:
        return "sensor_fault"
    return " + ".join(faults)


def main(limit: int | None = None, out_dir: Path | None = None) -> int:
    out = Path(out_dir) if out_dir else PUBLISHED
    out.mkdir(parents=True, exist_ok=True)
    engine = get_engine()
    seed = 20260915

    rows: list[dict] = []
    specs = list(list_scenarios())
    if limit:
        specs = specs[:limit]

    started = time.perf_counter()
    for spec in specs:
        record = simulate_scenario(spec.scenario_id, seed=seed)
        observable = record.observable()
        assert not hasattr(observable, "ground_truth")
        envelope = engine.diagnose(observable, scenario_id=spec.scenario_id).envelope
        truth = _truth_label(record)
        compiled = compile_journey(observable)
        rows.append(
            {
                "scenario_id": spec.scenario_id,
                "family": spec.family,
                "truth": truth,
                "flowlens": _top_label(envelope),
                "flowlens_decision": envelope.decision.value,
                "alarm_lookup": _alarm_lookup(compiled.facts.alarms),
                "rule_dag": _rule_dag(record),
                "first_deviation_phase": (
                    envelope.first_deviation.phase.value if envelope.first_deviation else None
                ),
                "expected_first_deviation_phase": (
                    spec.expected_first_deviation_phase.value
                    if spec.expected_first_deviation_phase
                    else None
                ),
                "latency_ms": envelope.latency_ms,
                "unknown_forced": (
                    spec.withheld and envelope.decision == Decision.KNOWN_FAULT
                ),
            }
        )

    elapsed = time.perf_counter() - started
    demo_ids = {scenario_id for _, scenario_id in DEMO_BUTTONS}

    def accuracy(column: str, subset: list[dict] | None = None) -> float:
        data = subset if subset is not None else rows
        if not data:
            return 0.0
        hits = 0
        for row in data:
            predicted = row[column]
            truth = row["truth"]
            if predicted == truth:
                hits += 1
            elif truth in predicted.split(" + ") or predicted in truth.split(" + "):
                hits += 1
        return hits / len(data)

    single = [r for r in rows if r["family"] == "single_fault"]
    demo = [r for r in rows if r["scenario_id"] in demo_ids]
    first_dev_eval = [
        r for r in rows if r["expected_first_deviation_phase"] and r["family"] == "single_fault"
    ]
    first_dev_hits = sum(
        1
        for r in first_dev_eval
        if r["first_deviation_phase"] == r["expected_first_deviation_phase"]
    )

    summary = {
        "notice": (
            "Achieved simulated result on the committed scenario registry. "
            "Not elevator field performance. Not a safety certification."
        ),
        "seed": seed,
        "n_scenarios": len(rows),
        "wall_seconds": round(elapsed, 3),
        "flowlens_label_accuracy_all": round(accuracy("flowlens"), 4),
        "alarm_lookup_accuracy_all": round(accuracy("alarm_lookup"), 4),
        "rule_dag_accuracy_all": round(accuracy("rule_dag"), 4),
        "flowlens_label_accuracy_single_fault": round(accuracy("flowlens", single), 4),
        "first_deviation_accuracy_single_fault": (
            round(first_dev_hits / len(first_dev_eval), 4) if first_dev_eval else None
        ),
        "unknown_forced_into_known": sum(1 for r in rows if r["unknown_forced"]),
        "demo_decisions": {
            r["scenario_id"]: r["flowlens_decision"] for r in demo
        },
        "decision_counts": dict(Counter(r["flowlens_decision"] for r in rows)),
        "mean_latency_ms": round(sum(r["latency_ms"] for r in rows) / max(len(rows), 1), 3),
        "p95_latency_ms": round(
            sorted(r["latency_ms"] for r in rows)[max(int(0.95 * (len(rows) - 1)), 0)], 3
        ),
    }

    (out / "smoke_rows.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (out / "smoke_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"wrote {out / 'smoke_summary.json'}")
    return 0
