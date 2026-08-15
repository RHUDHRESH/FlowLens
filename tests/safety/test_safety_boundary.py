"""Safety-boundary tests.

These are the tests that must never be weakened. They assert the properties the
safety case in ``docs/safety_case.md`` claims: FlowLens is read-only, it can only
recommend reviewed non-actuating checks, and model confidence can never unlock
anything.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from flowlens.config import permitted_tests
from flowlens.contracts.enums import (
    RECOMMENDABLE_SAFETY_CLASSES,
    Decision,
    FaultId,
    MaintenanceState,
    SafetyClass,
)
from flowlens.contracts.schemas import Hypothesis, PermittedTest, TestOutcome
from flowlens.test_planner.planner import PlannerError, plan_next_test

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_every_permitted_test_is_non_actuating():
    for test in permitted_tests().tests:
        assert test.safety_class in RECOMMENDABLE_SAFETY_CLASSES, (
            f"{test.test_id} has safety class {test.safety_class.value}; the shipped "
            "whitelist must contain only non-actuating checks"
        )


def test_every_permitted_test_names_a_reviewer():
    for test in permitted_tests().tests:
        assert test.reviewed_by and test.reviewed_by != "unassigned", (
            f"{test.test_id} has no accountable reviewer"
        )


def test_de_energized_tests_require_an_out_of_service_state():
    for test in permitted_tests().tests:
        if test.safety_class is SafetyClass.DE_ENERGIZED_INSPECTION:
            assert MaintenanceState.IN_SERVICE not in test.required_maintenance_state, (
                f"{test.test_id} would be offered while the car is in service"
            )
            assert test.prerequisites, f"{test.test_id} declares no isolation prerequisite"


def test_schema_rejects_an_actuating_test():
    """An actuating entry cannot be constructed outside a test fixture."""
    with pytest.raises(ValueError, match="ACTUATING"):
        PermittedTest(
            test_id="release_brake_manually",
            name="Release the brake manually",
            description="prohibited",
            safety_class=SafetyClass.ACTUATING,
            outcomes=[
                TestOutcome(outcome_id="a", description="a"),
                TestOutcome(outcome_id="b", description="b"),
            ],
        )


def test_planner_never_recommends_an_actuating_test():
    """Even if an actuating entry reaches the whitelist, it cannot be selected."""
    from flowlens.config import TestWhitelist

    actuating = PermittedTest(
        test_id="safety_test_fixture_brake_release",
        name="Energize the brake coil",
        description="Deliberately unsafe fixture; must never be recommended.",
        safety_class=SafetyClass.ACTUATING,
        required_maintenance_state=[MaintenanceState.IN_SERVICE],
        duration_minutes=1.0,
        operational_cost=0.0,
        risk_penalty=0.0,
        discriminates=[FaultId.BRAKE_DRAG, FaultId.BRAKE_RELEASE_FAILURE],
        outcomes=[
            TestOutcome(
                outcome_id="moves",
                description="Brake moves",
                likelihood_by_fault={"brake_drag": 0.9, "brake_release_failure": 0.1},
            ),
            TestOutcome(
                outcome_id="stuck",
                description="Brake does not move",
                likelihood_by_fault={"brake_drag": 0.1, "brake_release_failure": 0.9},
            ),
        ],
        reviewed_by="safety fixture",
    )
    whitelist = TestWhitelist(version="fixture", tests=(actuating,))

    hypotheses = [
        _hypothesis(FaultId.BRAKE_DRAG, 0.5),
        _hypothesis(FaultId.BRAKE_RELEASE_FAILURE, 0.5),
    ]

    assert plan_next_test(hypotheses, whitelist=whitelist) is None, (
        "the planner selected an actuating test"
    )


def _hypothesis(fault: FaultId, probability: float) -> Hypothesis:
    from flowlens.contracts.schemas import EvidenceItem

    return Hypothesis(
        faults=[fault],
        probability=probability,
        support=[EvidenceItem(key="k", statement="fixture", weight=1.0, direction="support")],
        contradictions=[],
        rationale="fixture",
    )


def test_planner_respects_the_maintenance_state():
    """A de-energized inspection is never offered on a car that is in service."""
    hypotheses = [_hypothesis(FaultId.BRAKE_DRAG, 0.5), _hypothesis(FaultId.ENCODER_DROPOUT, 0.5)]
    chosen = plan_next_test(hypotheses, maintenance_state=MaintenanceState.IN_SERVICE)
    if chosen is not None:
        test = permitted_tests().by_id(chosen.test_id)
        assert test is not None
        assert MaintenanceState.IN_SERVICE in test.required_maintenance_state


def test_planner_rejects_an_unknown_test_result():
    from flowlens.contracts.schemas import TestOutcomeReport
    from flowlens.test_planner.planner import apply_test_result

    with pytest.raises(PlannerError):
        apply_test_result(
            [_hypothesis(FaultId.BRAKE_DRAG, 1.0)],
            TestOutcomeReport(test_id="not_a_real_test", outcome_id="whatever"),
        )


def test_recommendations_across_every_demo_scenario_stay_inside_the_boundary(engine, demo_scenarios):
    from flowlens.simulator.runner import simulate_scenario

    whitelist = permitted_tests()
    for _label, scenario_id in demo_scenarios:
        record = simulate_scenario(scenario_id, seed=20260915)
        envelope = engine.diagnose(record.observable(), scenario_id=scenario_id).envelope
        if envelope.next_test is None:
            continue
        assert envelope.next_test.safety_class in RECOMMENDABLE_SAFETY_CLASSES
        assert whitelist.by_id(envelope.next_test.test_id) is not None, (
            f"{scenario_id}: recommended a test outside the whitelist"
        )


def test_no_actuating_vocabulary_in_the_shipped_whitelist():
    """Guard against a bypass or energize instruction creeping into the config."""
    banned = (
        "bypass",
        "bridge",
        "jumper",
        "override",
        "energize",
        "reset the fault",
        "return to service",
        "release the brake",
        "close the contactor",
    )
    text = (REPO_ROOT / "configs" / "permitted_tests.yaml").read_text(encoding="utf-8").lower()
    # "no manual release" style prohibitions are allowed; bare instructions are not.
    for phrase in banned:
        for line in text.splitlines():
            if phrase in line and not any(
                marker in line
                for marker in (
                    "no ",
                    "not ",
                    "never",
                    "without",
                    "prohibited",
                    "of any kind",
                    "must not",
                    "do not",
                    "forbidden",
                    "energized",
                    "inspection only",
                    "no bypass",
                )
            ):
                pytest.fail(f"permitted_tests.yaml line reads as an actuating instruction: {line.strip()}")


def test_engine_exposes_no_actuation_surface():
    """The diagnostic package must contain no command/actuation entry point."""
    import flowlens.diagnosis.engine as engine_module
    import flowlens.test_planner.planner as planner_module

    forbidden = ("command", "reset", "energize", "actuate", "release_brake", "close_contactor")
    for module in (engine_module, planner_module):
        for name, obj in inspect.getmembers(module, inspect.isfunction):
            if obj.__module__ != module.__name__:
                continue
            assert not any(name.lower().startswith(f) for f in forbidden), (
                f"{module.__name__}.{name} looks like an actuation entry point"
            )


def test_abstention_states_are_never_collapsed_into_a_named_fault():
    """Each abstention decision must remain distinct from KNOWN_FAULT."""
    from flowlens.contracts.enums import ABSTAINING_DECISIONS

    assert Decision.KNOWN_FAULT not in ABSTAINING_DECISIONS
    assert Decision.HEALTHY not in ABSTAINING_DECISIONS
    assert len(ABSTAINING_DECISIONS) == 5


def test_every_envelope_carries_the_safety_notice(engine, healthy_run):
    envelope = engine.diagnose(healthy_run.observable()).envelope
    notice = envelope.safety_notice.lower()
    for phrase in ("read-only", "cannot reset", "bypass", "return to service"):
        assert phrase in notice
