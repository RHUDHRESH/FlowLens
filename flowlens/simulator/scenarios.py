"""Reproducible scenario registry.

Every scenario is a named, seeded configuration. The seven ``demo_button``
scenarios are the ones a judge can drive from the console; the remainder exist so
the benchmark has enough fault variety to be meaningful.

``expected_decision`` records what the *product* should do, not what the fault
is. For the unknown scenario the correct product behaviour is to abstain.
"""

from __future__ import annotations

from flowlens.contracts.enums import Decision, FaultId, JourneyPhase
from flowlens.contracts.schemas import FaultInjection, ScenarioSpec

_SCENARIOS: list[ScenarioSpec] = [
    # ------------------------------------------------------------------ #
    # Healthy
    # ------------------------------------------------------------------ #
    ScenarioSpec(
        scenario_id="healthy",
        title="Healthy journey",
        family="healthy",
        description="A complete journey with no injected fault and no alarm.",
        injections=[],
        expected_decision=Decision.HEALTHY,
        demo_button="Healthy",
    ),
    ScenarioSpec(
        scenario_id="healthy_warm",
        title="Healthy journey, warm drive",
        family="healthy",
        description="Healthy journey on a drive that starts closer to its warm operating point.",
        injections=[],
        expected_decision=Decision.HEALTHY,
    ),
    # ------------------------------------------------------------------ #
    # Door and lock
    # ------------------------------------------------------------------ #
    ScenarioSpec(
        scenario_id="door_lock_bounce",
        title="Door lock contact bounce",
        family="single_fault",
        description=(
            "The door reaches its closed position but lock proof makes and breaks "
            "repeatedly and never latches. Downstream start and drive timeouts follow."
        ),
        injections=[
            FaultInjection(
                fault_id=FaultId.DOOR_LOCK_BOUNCE,
                mechanism="lock contact chatter during the close window",
                onset_ms=0,
                severity=0.8,
            )
        ],
        expected_decision=Decision.KNOWN_FAULT,
        expected_first_deviation_phase=JourneyPhase.DOOR_CLOSING,
        demo_button="Door Lock",
    ),
    ScenarioSpec(
        scenario_id="door_lock_proof_absent",
        title="Door lock proof never asserts",
        family="single_fault",
        description="The lock proof circuit never asserts at any point in the close sequence.",
        injections=[
            FaultInjection(
                fault_id=FaultId.DOOR_LOCK_PROOF_ABSENT,
                mechanism="lock proof circuit open",
                severity=1.0,
            )
        ],
        expected_decision=Decision.KNOWN_FAULT,
        expected_first_deviation_phase=JourneyPhase.DOOR_CLOSING,
    ),
    ScenarioSpec(
        scenario_id="door_obstruction",
        title="Door obstruction",
        family="single_fault",
        description="An obstruction repeatedly triggers reopen protection during closing.",
        injections=[
            FaultInjection(
                fault_id=FaultId.DOOR_OBSTRUCTION,
                mechanism="obstruction in the door path",
                severity=0.9,
            )
        ],
        expected_decision=Decision.KNOWN_FAULT,
        expected_first_deviation_phase=JourneyPhase.DOOR_CLOSING,
    ),
    ScenarioSpec(
        scenario_id="door_motor_overload",
        title="Door operator overload",
        family="single_fault",
        description="The door operator binds; current stays high and travel time extends.",
        injections=[
            FaultInjection(
                fault_id=FaultId.DOOR_MOTOR_OVERLOAD,
                mechanism="door operator mechanical binding",
                severity=0.8,
            )
        ],
        expected_decision=Decision.KNOWN_FAULT,
        expected_first_deviation_phase=JourneyPhase.DOOR_CLOSING,
    ),
    # ------------------------------------------------------------------ #
    # Safety and start permission
    # ------------------------------------------------------------------ #
    ScenarioSpec(
        scenario_id="door_position_sensor_fault",
        family="single_fault",
        title="Door position sensor defect",
        description=(
            "The door completes its travel - the operator current profile proves it - "
            "but the position sensor never confirms the closed position."
        ),
        injections=[
            FaultInjection(
                fault_id=FaultId.DOOR_POSITION_SENSOR_FAULT,
                mechanism="door position sensor does not report closed",
                severity=1.0,
            )
        ],
        expected_decision=None,
        expected_first_deviation_phase=JourneyPhase.DOOR_CLOSING,
    ),
    ScenarioSpec(
        scenario_id="safety_chain_intermittent",
        title="Safety chain intermittency",
        family="single_fault",
        description=(
            "Lock proof latches cleanly, then the safety chain chatters and start "
            "permission is never granted."
        ),
        injections=[
            FaultInjection(
                fault_id=FaultId.SAFETY_CHAIN_INTERMITTENT,
                mechanism="series safety contact chatter",
                severity=0.8,
            )
        ],
        expected_decision=Decision.KNOWN_FAULT,
        expected_first_deviation_phase=JourneyPhase.LOCK_PROVED,
    ),
    ScenarioSpec(
        scenario_id="start_permit_missing",
        title="Start permission absent",
        family="single_fault",
        description="The safety chain proves but start permission never asserts.",
        injections=[
            FaultInjection(
                fault_id=FaultId.START_PERMIT_MISSING,
                mechanism="start permission logic does not assert",
                severity=1.0,
            )
        ],
        expected_decision=Decision.KNOWN_FAULT,
        expected_first_deviation_phase=JourneyPhase.SAFETY_CHAIN_PROVED,
    ),
    ScenarioSpec(
        scenario_id="contactor_delay",
        title="Main contactor feedback delay",
        family="single_fault",
        description="Contactor confirmation arrives well outside its window, delaying drive enable.",
        injections=[
            FaultInjection(
                fault_id=FaultId.CONTACTOR_DELAY,
                mechanism="degraded contactor auxiliary feedback",
                severity=0.9,
            )
        ],
        expected_decision=Decision.KNOWN_FAULT,
        expected_first_deviation_phase=JourneyPhase.START_PERMIT,
    ),
    # ------------------------------------------------------------------ #
    # Power and drive
    # ------------------------------------------------------------------ #
    ScenarioSpec(
        scenario_id="dc_bus_undervoltage",
        title="DC bus undervoltage",
        family="single_fault",
        description="The DC bus collapses during starting and the drive limits available torque.",
        injections=[
            FaultInjection(
                fault_id=FaultId.DC_BUS_UNDERVOLTAGE,
                mechanism="DC bus below the drive operating window",
                severity=1.0,
            )
        ],
        expected_decision=Decision.KNOWN_FAULT,
        # The car falls behind its speed profile as soon as torque build starts,
        # because the drive is current-limited from the first commanded ramp.
        expected_first_deviation_phase=JourneyPhase.TORQUE_BUILD,
    ),
    ScenarioSpec(
        scenario_id="supply_sag",
        title="AC supply sag",
        family="single_fault",
        description="Incoming supply dips during the high-current starting window.",
        injections=[
            FaultInjection(
                fault_id=FaultId.SUPPLY_SAG,
                mechanism="incoming supply voltage dip",
                severity=0.9,
            )
        ],
        expected_decision=Decision.KNOWN_FAULT,
    ),
    ScenarioSpec(
        scenario_id="drive_overcurrent",
        family="single_fault",
        title="Drive overcurrent trip",
        description="Drive output current exceeds its protection limit and the run is cut short.",
        injections=[
            FaultInjection(
                fault_id=FaultId.DRIVE_OVERCURRENT,
                mechanism="drive output current above the protection limit",
                severity=0.95,
            )
        ],
        expected_decision=Decision.KNOWN_FAULT,
    ),
    ScenarioSpec(
        scenario_id="speed_mismatch",
        family="single_fault",
        title="Commanded / measured speed mismatch",
        description="Measured speed departs from the reference without any loss of feedback.",
        injections=[
            FaultInjection(
                fault_id=FaultId.SPEED_MISMATCH,
                mechanism="feedback scaling inconsistent with the reference",
                severity=0.9,
            )
        ],
        expected_decision=None,
    ),
    ScenarioSpec(
        scenario_id="drive_cooling_degradation",
        title="Drive cooling degradation",
        family="single_fault",
        description="Restricted cooling airflow; drive temperature rises faster than the load explains.",
        injections=[
            FaultInjection(
                fault_id=FaultId.DRIVE_COOLING_DEGRADATION,
                mechanism="restricted drive cooling airflow",
                severity=1.0,
            )
        ],
        expected_decision=Decision.KNOWN_FAULT,
    ),
    # ------------------------------------------------------------------ #
    # Feedback
    # ------------------------------------------------------------------ #
    ScenarioSpec(
        scenario_id="encoder_dropout",
        title="Encoder dropout",
        family="single_fault",
        description=(
            "Torque is commanded and current rises, but speed feedback vanishes "
            "mid-acceleration while the independent position reference keeps moving."
        ),
        injections=[
            FaultInjection(
                fault_id=FaultId.ENCODER_DROPOUT,
                mechanism="encoder feedback lost from onset",
                onset_ms=4200,
                severity=1.0,
            )
        ],
        expected_decision=Decision.KNOWN_FAULT,
        expected_first_deviation_phase=JourneyPhase.ACCELERATION,
        demo_button="Encoder Dropout",
    ),
    ScenarioSpec(
        scenario_id="encoder_drift",
        title="Encoder drift and noise",
        family="single_fault",
        description="Speed feedback stays present but becomes markedly noisy.",
        injections=[
            FaultInjection(
                fault_id=FaultId.ENCODER_DRIFT,
                mechanism="encoder signal noise coupling",
                severity=0.9,
            )
        ],
        expected_decision=Decision.KNOWN_FAULT,
    ),
    # ------------------------------------------------------------------ #
    # Brake
    # ------------------------------------------------------------------ #
    ScenarioSpec(
        scenario_id="brake_drag",
        title="Brake drag",
        family="single_fault",
        description=(
            "Brake release proof appears and current rises, but achieved acceleration "
            "falls short and friction heat and vibration climb."
        ),
        injections=[
            FaultInjection(
                fault_id=FaultId.BRAKE_DRAG,
                mechanism="partial brake release leaving pad contact",
                severity=0.87,
            )
        ],
        expected_decision=Decision.KNOWN_FAULT,
        expected_first_deviation_phase=JourneyPhase.TORQUE_BUILD,
        demo_button="Brake Drag",
    ),
    ScenarioSpec(
        scenario_id="brake_release_failure",
        title="Brake fails to release",
        family="single_fault",
        description="The brake never releases; torque is commanded against a fully applied brake.",
        injections=[
            FaultInjection(
                fault_id=FaultId.BRAKE_RELEASE_FAILURE,
                mechanism="brake armature does not move",
                severity=1.0,
            )
        ],
        expected_decision=Decision.KNOWN_FAULT,
        # The brake never proves release, so the journey first departs from the
        # automaton in BRAKE_RELEASE - before torque build is even reached.
        expected_first_deviation_phase=JourneyPhase.BRAKE_RELEASE,
    ),
    # ------------------------------------------------------------------ #
    # Compound
    # ------------------------------------------------------------------ #
    ScenarioSpec(
        scenario_id="compound_brake_drag_encoder_noise",
        title="Compound: brake drag with a noisy encoder",
        family="compound_fault",
        description=(
            "Two mechanisms at once. Neither single-fault explanation covers the whole "
            "evidence sequence, so the correct output is a compound hypothesis or an "
            "explicit statement of ambiguity - never a confident single label."
        ),
        injections=[
            FaultInjection(
                fault_id=FaultId.BRAKE_DRAG,
                mechanism="partial brake release leaving pad contact",
                severity=0.85,
            ),
            FaultInjection(
                fault_id=FaultId.ENCODER_DRIFT,
                mechanism="encoder signal noise coupling",
                severity=0.7,
            ),
        ],
        expected_decision=None,
        expected_first_deviation_phase=JourneyPhase.TORQUE_BUILD,
        demo_button="Compound",
    ),
    # ------------------------------------------------------------------ #
    # Sensor / data
    # ------------------------------------------------------------------ #
    ScenarioSpec(
        scenario_id="sensor_fault_speed_stuck",
        title="Sensor fault: speed channel stuck",
        family="sensor_fault",
        description=(
            "The machine runs correctly but the recorded speed channel is frozen. "
            "An equipment diagnosis built on that channel would be wrong, so the "
            "correct output is SENSOR_CHECK."
        ),
        injections=[
            FaultInjection(
                fault_id=FaultId.SENSOR_FAULT,
                mechanism="recorded speed channel held at a constant value",
                onset_ms=4000,
                severity=1.0,
            )
        ],
        channel_defects=[
            {"kind": "stuck", "channel": "speed_mps", "start_ms": 4000, "end_ms": 20000},
            {"kind": "stuck", "channel": "accel_mps2", "start_ms": 4000, "end_ms": 20000},
        ],
        expected_decision=Decision.SENSOR_CHECK,
        demo_button="Sensor Fault",
    ),
    ScenarioSpec(
        scenario_id="sensor_fault_bus_bias",
        title="Sensor fault: DC bus channel biased",
        family="sensor_fault",
        description="The DC bus channel reads with a large negative bias while the drive runs normally.",
        injections=[
            FaultInjection(
                fault_id=FaultId.SENSOR_FAULT,
                mechanism="recorded DC bus channel biased low",
                severity=1.0,
            )
        ],
        channel_defects=[
            {"kind": "bias", "channel": "dc_bus_v", "offset": -118.0},
        ],
        expected_decision=Decision.SENSOR_CHECK,
    ),
    ScenarioSpec(
        scenario_id="comms_corruption",
        title="Communications corruption",
        family="sensor_fault",
        description="Frames are lost and timestamps become irregular during the journey.",
        injections=[
            FaultInjection(
                fault_id=FaultId.COMMS_CORRUPTION,
                mechanism="field bus frame loss",
                severity=0.8,
            )
        ],
        channel_defects=[
            {"kind": "packet_loss", "rate": 0.16, "start_ms": 2500, "end_ms": 12000},
            {"kind": "quality_drop", "channel": "motor_current_a", "quality": 0.5},
        ],
        expected_decision=None,
    ),
    # ------------------------------------------------------------------ #
    # Unknown / withheld mechanism
    # ------------------------------------------------------------------ #
    ScenarioSpec(
        scenario_id="unknown_mechanical_resistance",
        title="Unknown: progressive mechanical resistance",
        family="unknown_fault",
        description=(
            "A mechanism deliberately withheld from the fault graph, evidence fitting "
            "and calibration. Resistance grows with travel, so the car starts cleanly "
            "and stalls mid-journey. The correct output is UNKNOWN_FAULT or "
            "HUMAN_REVIEW - never a confident known label."
        ),
        injections=[
            FaultInjection(
                fault_id=FaultId.MECHANICAL_RESISTANCE,
                mechanism="travel-dependent resistance in the guidance path",
                severity=1.0,
            )
        ],
        expected_decision=Decision.UNKNOWN_FAULT,
        expected_first_deviation_phase=JourneyPhase.CRUISE,
        demo_button="Unknown",
        withheld=True,
    ),
]

_BY_ID = {spec.scenario_id: spec for spec in _SCENARIOS}

#: Ordered demo buttons required by the competition checklist.
DEMO_BUTTONS: tuple[tuple[str, str], ...] = (
    ("Healthy", "healthy"),
    ("Door Lock", "door_lock_bounce"),
    ("Encoder Dropout", "encoder_dropout"),
    ("Brake Drag", "brake_drag"),
    ("Compound", "compound_brake_drag_encoder_noise"),
    ("Sensor Fault", "sensor_fault_speed_stuck"),
    ("Unknown", "unknown_mechanical_resistance"),
)

#: Short names accepted by ``make inject FAULT=...``.
FAULT_ALIASES: dict[str, str] = {
    "healthy": "healthy",
    "door_lock": "door_lock_bounce",
    "door_lock_bounce": "door_lock_bounce",
    "encoder_dropout": "encoder_dropout",
    "brake_drag": "brake_drag",
    "compound": "compound_brake_drag_encoder_noise",
    "sensor_fault": "sensor_fault_speed_stuck",
    "unknown": "unknown_mechanical_resistance",
}


def resolve_scenario_id(name: str) -> str:
    return FAULT_ALIASES.get(name, name)


def list_scenarios() -> tuple[ScenarioSpec, ...]:
    return tuple(_SCENARIOS)


def get_scenario(scenario_id: str) -> ScenarioSpec:
    scenario_id = resolve_scenario_id(scenario_id)
    if scenario_id not in _BY_ID:
        known = ", ".join(sorted(_BY_ID))
        raise KeyError(f"unknown scenario {scenario_id!r}; known scenarios: {known}")
    return _BY_ID[scenario_id]


def withheld_scenarios() -> tuple[ScenarioSpec, ...]:
    """Scenarios that must never contribute to fitting or calibration."""
    return tuple(s for s in _SCENARIOS if s.withheld)


def fittable_scenarios() -> tuple[ScenarioSpec, ...]:
    return tuple(s for s in _SCENARIOS if not s.withheld)
