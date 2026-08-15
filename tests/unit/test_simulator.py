"""Simulator determinism and safety-permission invariants."""

from flowlens.contracts.enums import MOTION_PERMISSION_CHAIN, MOTION_PHASES, JourneyPhase
from flowlens.diagnosis.compiler import compile_journey
from flowlens.simulator.faults import MECHANISM_FIELDS, Mechanism, apply_injections
from flowlens.simulator.runner import simulate_scenario
from flowlens.simulator.scenarios import get_scenario


def test_same_seed_is_bit_stable():
    a = simulate_scenario("healthy", seed=20260915)
    b = simulate_scenario("healthy", seed=20260915)
    assert [e.model_dump() for e in a.events] == [e.model_dump() for e in b.events]
    assert [f.model_dump() for f in a.frames] == [f.model_dump() for f in b.frames]
    assert a.config_hash == b.config_hash


def test_different_seed_changes_the_trace():
    a = simulate_scenario("healthy", seed=20260915)
    b = simulate_scenario("healthy", seed=20260916)
    assert [f.model_dump() for f in a.frames] != [f.model_dump() for f in b.frames]


def test_healthy_journey_reaches_cruise_and_door_open(healthy_run):
    compiled = compile_journey(healthy_run.observable())
    phases = {segment.phase for segment in compiled.segments}
    assert JourneyPhase.CRUISE in phases
    assert JourneyPhase.DOOR_OPEN in phases
    assert not compiled.facts.alarms


def test_motion_requires_permission_chain(healthy_run):
    compiled = compile_journey(healthy_run.observable())
    phases = [segment.phase for segment in compiled.segments]
    if any(phase in MOTION_PHASES for phase in phases):
        for required in MOTION_PERMISSION_CHAIN:
            assert required in phases, f"motion without {required.value}"


def test_door_lock_never_enters_motion():
    record = simulate_scenario("door_lock_bounce", seed=20260915)
    compiled = compile_journey(record.observable())
    phases = {segment.phase for segment in compiled.segments}
    assert not (phases & MOTION_PHASES)
    assert JourneyPhase.LOCK_PROVED not in phases or compiled.facts.alarms


def test_fault_injection_only_touches_declared_fields():
    spec = get_scenario("brake_drag")
    mechanism, _ = apply_injections(Mechanism(), list(spec.injections))
    healthy = Mechanism()
    changed = []
    for field in mechanism.__dataclass_fields__:
        if getattr(mechanism, field) != getattr(healthy, field):
            changed.append(field)
    allowed = set()
    for injection in spec.injections:
        allowed.update(MECHANISM_FIELDS[injection.fault_id])
    assert set(changed) <= allowed
