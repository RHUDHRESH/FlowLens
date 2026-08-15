"""End-to-end demo contract and API surface."""

from fastapi.testclient import TestClient

from flowlens.contracts.enums import ABSTAINING_DECISIONS, Decision
from flowlens.simulator.scenarios import DEMO_BUTTONS, get_scenario


def test_cli_verify_contract(engine, demo_scenarios):
    from flowlens.simulator.runner import simulate_scenario

    for _label, scenario_id in demo_scenarios:
        spec = get_scenario(scenario_id)
        record = simulate_scenario(scenario_id, seed=20260915)
        envelope = engine.diagnose(record.observable(), scenario_id=scenario_id).envelope
        if spec.expected_decision is None:
            assert envelope.decision in ABSTAINING_DECISIONS or envelope.decision == Decision.KNOWN_FAULT
        else:
            assert envelope.decision == spec.expected_decision, (
                f"{scenario_id}: got {envelope.decision.value}"
            )
        if spec.withheld:
            assert envelope.decision != Decision.KNOWN_FAULT
        for hypothesis in envelope.top_hypotheses:
            if hypothesis.faults:
                assert hypothesis.support or hypothesis.contradictions


def test_unknown_is_not_forced_into_a_known_label(engine):
    from flowlens.simulator.runner import simulate_scenario

    record = simulate_scenario("unknown_mechanical_resistance", seed=20260915)
    envelope = engine.diagnose(record.observable(), scenario_id=record.scenario_id).envelope
    assert envelope.decision in {Decision.UNKNOWN_FAULT, Decision.HUMAN_REVIEW}
    assert envelope.decision != Decision.KNOWN_FAULT


def test_sensor_fault_routes_to_sensor_check(engine):
    from flowlens.simulator.runner import simulate_scenario

    record = simulate_scenario("sensor_fault_speed_stuck", seed=20260915)
    envelope = engine.diagnose(record.observable(), scenario_id=record.scenario_id).envelope
    assert envelope.decision == Decision.SENSOR_CHECK


def test_api_health_and_diagnosis_roundtrip():
    from apps.api.main import app

    client = TestClient(app)
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["read_only"] is True

    scenarios = client.get("/api/v1/scenarios")
    assert scenarios.status_code == 200
    labels = [b["label"] for b in scenarios.json()["demo_buttons"]]
    assert labels == [label for label, _ in DEMO_BUTTONS]

    created = client.post("/api/v1/runs", json={"scenario_id": "healthy", "autoplay": True})
    assert created.status_code == 201
    run_id = created.json()["run_id"]

    diagnosis = client.get(f"/api/v1/runs/{run_id}/diagnosis")
    assert diagnosis.status_code == 200
    envelope = diagnosis.json()
    assert envelope["decision"] == "HEALTHY"
    assert envelope["incident_id"]
    assert envelope["raw_trace_hash"].startswith("sha256:")

    report = client.get(f"/api/v1/incidents/{envelope['incident_id']}/report")
    assert report.status_code == 200
    assert envelope["incident_id"] in report.text
    assert envelope["raw_trace_hash"][:16] in report.text
    assert "read-only" in report.text.lower()


def test_api_has_no_actuation_routes():
    from apps.api.main import app

    paths = {getattr(route, "path", "") for route in app.routes}
    forbidden = ("/command", "/reset-fault", "/energize", "/bypass", "/return-to-service")
    for item in forbidden:
        assert all(item not in path for path in paths)
