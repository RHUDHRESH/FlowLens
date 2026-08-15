"""Golden replay hashes for the seven demo scenarios."""

from __future__ import annotations

import json

from flowlens.dataset import GOLDEN_PATH, record_hash
from flowlens.diagnosis.compiler import compile_journey
from flowlens.diagnosis.deviation import first_deviation, localize_deviations
from flowlens.ingestion.quality import assess_quality
from flowlens.simulator.runner import simulate_scenario
from flowlens.simulator.scenarios import DEMO_BUTTONS, get_scenario

SEED = 20260915


def test_golden_hashes_exist_and_match():
    assert GOLDEN_PATH.exists(), "run python -m flowlens generate-scenarios first"
    payload = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert payload["seed"] == SEED
    for _label, scenario_id in DEMO_BUTTONS:
        record = simulate_scenario(scenario_id, seed=SEED)
        assert record_hash(record) == payload["hashes"][scenario_id], scenario_id


def test_first_deviation_matches_scenario_expectation():
    for _label, scenario_id in DEMO_BUTTONS:
        spec = get_scenario(scenario_id)
        if spec.expected_first_deviation_phase is None:
            continue
        record = simulate_scenario(scenario_id, seed=SEED)
        run = record.observable()
        compiled = compile_journey(run)
        quality = assess_quality(run)
        deviation = first_deviation(localize_deviations(run, compiled, quality))
        assert deviation is not None, scenario_id
        assert deviation.phase == spec.expected_first_deviation_phase, (
            f"{scenario_id}: got {deviation.phase.value}, "
            f"expected {spec.expected_first_deviation_phase.value}"
        )


def test_healthy_has_no_first_deviation(healthy_run):
    run = healthy_run.observable()
    compiled = compile_journey(run)
    quality = assess_quality(run)
    deviation = first_deviation(localize_deviations(run, compiled, quality))
    assert deviation is None
