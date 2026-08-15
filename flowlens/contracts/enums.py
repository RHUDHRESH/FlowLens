"""Canonical vocabularies for journeys, events, faults and decisions.

These names are part of the public contract. Renaming a member is a breaking
change and requires a schema version bump plus regenerated golden fixtures.
"""

from __future__ import annotations

from enum import StrEnum


class JourneyPhase(StrEnum):
    """Diagnostic abstraction of an elevator journey.

    This is not a real elevator controller state machine. It is the phase
    vocabulary FlowLens reconstructs in order to reason about *when* a journey
    first departed from its expected behaviour.
    """

    IDLE = "IDLE"
    CALL_ACCEPTED = "CALL_ACCEPTED"
    DOOR_CLOSING = "DOOR_CLOSING"
    LOCK_PROVED = "LOCK_PROVED"
    SAFETY_CHAIN_PROVED = "SAFETY_CHAIN_PROVED"
    START_PERMIT = "START_PERMIT"
    BRAKE_RELEASE = "BRAKE_RELEASE"
    TORQUE_BUILD = "TORQUE_BUILD"
    ACCELERATION = "ACCELERATION"
    CRUISE = "CRUISE"
    DECELERATION = "DECELERATION"
    LEVELING = "LEVELING"
    BRAKE_SET = "BRAKE_SET"
    DOOR_OPENING = "DOOR_OPENING"
    DOOR_OPEN = "DOOR_OPEN"
    INCIDENT_STOP = "INCIDENT_STOP"
    MAINTENANCE = "MAINTENANCE"


#: Phases in which the car is permitted to be in motion. Reaching any of these
#: without the full permission chain is a prohibited transition.
MOTION_PHASES: frozenset[JourneyPhase] = frozenset(
    {
        JourneyPhase.ACCELERATION,
        JourneyPhase.CRUISE,
        JourneyPhase.DECELERATION,
        JourneyPhase.LEVELING,
    }
)

#: Evidence that must exist before any motion phase may be entered.
MOTION_PERMISSION_CHAIN: tuple[JourneyPhase, ...] = (
    JourneyPhase.LOCK_PROVED,
    JourneyPhase.SAFETY_CHAIN_PROVED,
    JourneyPhase.START_PERMIT,
    JourneyPhase.BRAKE_RELEASE,
)


class EventType(StrEnum):
    """Controller-like discrete events, normalized by the journey compiler."""

    CALL_REGISTERED = "CALL_REGISTERED"
    DOOR_CLOSE_COMMANDED = "DOOR_CLOSE_COMMANDED"
    DOOR_POSITION_CHANGED = "DOOR_POSITION_CHANGED"
    DOOR_REOPEN_TRIGGERED = "DOOR_REOPEN_TRIGGERED"
    LOCK_PROOF_CHANGED = "LOCK_PROOF_CHANGED"
    SAFETY_CHAIN_CHANGED = "SAFETY_CHAIN_CHANGED"
    START_PERMIT_CHANGED = "START_PERMIT_CHANGED"
    CONTACTOR_CHANGED = "CONTACTOR_CHANGED"
    BRAKE_COMMAND_CHANGED = "BRAKE_COMMAND_CHANGED"
    BRAKE_PROOF_CHANGED = "BRAKE_PROOF_CHANGED"
    SPEED_REFERENCE_CHANGED = "SPEED_REFERENCE_CHANGED"
    MOTION_DETECTED = "MOTION_DETECTED"
    LEVEL_REACHED = "LEVEL_REACHED"
    DOOR_OPEN_COMMANDED = "DOOR_OPEN_COMMANDED"
    ALARM_RAISED = "ALARM_RAISED"
    COMMS_GAP = "COMMS_GAP"
    PHASE_ENTERED = "PHASE_ENTERED"
    RUN_ABORTED = "RUN_ABORTED"


class SignalChannel(StrEnum):
    """Continuous measurement channels available to the diagnostic engine."""

    DC_BUS_V = "dc_bus_v"
    MOTOR_CURRENT_A = "motor_current_a"
    SPEED_MPS = "speed_mps"
    SPEED_REF_MPS = "speed_ref_mps"
    ACCEL_MPS2 = "accel_mps2"
    BRAKE_CURRENT_A = "brake_current_a"
    DOOR_CURRENT_A = "door_current_a"
    DRIVE_TEMP_C = "drive_temp_c"
    VIBRATION_RMS = "vibration_rms"
    POSITION_M = "position_m"


#: Channels without which a motion diagnosis cannot be supported.
CRITICAL_MOTION_CHANNELS: tuple[SignalChannel, ...] = (
    SignalChannel.MOTOR_CURRENT_A,
    SignalChannel.SPEED_MPS,
    SignalChannel.DC_BUS_V,
)


class FaultId(StrEnum):
    """Elevator subsystem fault ontology for the public demo graph.

    Deliberately generic: no proprietary KONE fault codes, subcodes or manual
    text appear anywhere in this repository.
    """

    # Door subsystem
    DOOR_OBSTRUCTION = "door_obstruction"
    DOOR_LOCK_PROOF_ABSENT = "door_lock_proof_absent"
    DOOR_LOCK_BOUNCE = "door_lock_bounce"
    DOOR_MOTOR_OVERLOAD = "door_motor_overload"
    DOOR_POSITION_SENSOR_FAULT = "door_position_sensor_fault"

    # Safety / start-permission subsystem
    SAFETY_CHAIN_INTERMITTENT = "safety_chain_intermittent"
    START_PERMIT_MISSING = "start_permit_missing"
    CONTACTOR_DELAY = "contactor_delay"
    COMMS_CORRUPTION = "comms_corruption"

    # Power and drive subsystem
    SUPPLY_SAG = "supply_sag"
    DC_BUS_UNDERVOLTAGE = "dc_bus_undervoltage"
    DRIVE_OVERCURRENT = "drive_overcurrent"
    DRIVE_COOLING_DEGRADATION = "drive_cooling_degradation"

    # Motion / feedback subsystem
    ENCODER_DROPOUT = "encoder_dropout"
    ENCODER_DRIFT = "encoder_drift"
    SPEED_MISMATCH = "speed_mismatch"

    # Brake / mechanical subsystem
    BRAKE_RELEASE_FAILURE = "brake_release_failure"
    BRAKE_DRAG = "brake_drag"
    MECHANICAL_RESISTANCE = "mechanical_resistance"

    # Instrumentation and data subsystem
    SENSOR_FAULT = "sensor_fault"


#: Fault mechanisms deliberately withheld from evidence fitting and calibration
#: so the unknown-fault path can be evaluated honestly. The engine must never
#: contain an evidence model for these.
WITHHELD_FAULTS: frozenset[FaultId] = frozenset({FaultId.MECHANICAL_RESISTANCE})


class Subsystem(StrEnum):
    """Coarse grouping used for technician-facing routing and UI colouring."""

    DOOR = "door"
    SAFETY = "safety"
    POWER = "power"
    DRIVE = "drive"
    FEEDBACK = "feedback"
    BRAKE = "brake"
    INSTRUMENTATION = "instrumentation"
    UNKNOWN = "unknown"


FAULT_SUBSYSTEM: dict[FaultId, Subsystem] = {
    FaultId.DOOR_OBSTRUCTION: Subsystem.DOOR,
    FaultId.DOOR_LOCK_PROOF_ABSENT: Subsystem.DOOR,
    FaultId.DOOR_LOCK_BOUNCE: Subsystem.DOOR,
    FaultId.DOOR_MOTOR_OVERLOAD: Subsystem.DOOR,
    FaultId.DOOR_POSITION_SENSOR_FAULT: Subsystem.INSTRUMENTATION,
    FaultId.SAFETY_CHAIN_INTERMITTENT: Subsystem.SAFETY,
    FaultId.START_PERMIT_MISSING: Subsystem.SAFETY,
    FaultId.CONTACTOR_DELAY: Subsystem.SAFETY,
    FaultId.COMMS_CORRUPTION: Subsystem.INSTRUMENTATION,
    FaultId.SUPPLY_SAG: Subsystem.POWER,
    FaultId.DC_BUS_UNDERVOLTAGE: Subsystem.POWER,
    FaultId.DRIVE_OVERCURRENT: Subsystem.DRIVE,
    FaultId.DRIVE_COOLING_DEGRADATION: Subsystem.DRIVE,
    FaultId.ENCODER_DROPOUT: Subsystem.FEEDBACK,
    FaultId.ENCODER_DRIFT: Subsystem.FEEDBACK,
    FaultId.SPEED_MISMATCH: Subsystem.FEEDBACK,
    FaultId.BRAKE_RELEASE_FAILURE: Subsystem.BRAKE,
    FaultId.BRAKE_DRAG: Subsystem.BRAKE,
    FaultId.MECHANICAL_RESISTANCE: Subsystem.UNKNOWN,
    FaultId.SENSOR_FAULT: Subsystem.INSTRUMENTATION,
}


class DeviationType(StrEnum):
    """How an observed journey departed from the expected phase automaton."""

    MISSING_TRANSITION = "MISSING_TRANSITION"
    LATE_TRANSITION = "LATE_TRANSITION"
    PREMATURE_TRANSITION = "PREMATURE_TRANSITION"
    PROHIBITED_TRANSITION = "PROHIBITED_TRANSITION"
    CONTRADICTORY_STATE = "CONTRADICTORY_STATE"
    RETRY_LOOP = "RETRY_LOOP"
    SIGNAL_EVENT_INCONSISTENCY = "SIGNAL_EVENT_INCONSISTENCY"


class Decision(StrEnum):
    """Top-level outcome of the abstention gate.

    These are distinct product states, never collapsed into a low-confidence
    named fault.
    """

    HEALTHY = "HEALTHY"
    KNOWN_FAULT = "KNOWN_FAULT"
    UNKNOWN_FAULT = "UNKNOWN_FAULT"
    SENSOR_CHECK = "SENSOR_CHECK"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


ABSTAINING_DECISIONS: frozenset[Decision] = frozenset(
    {
        Decision.UNKNOWN_FAULT,
        Decision.SENSOR_CHECK,
        Decision.INSUFFICIENT_DATA,
        Decision.HUMAN_REVIEW,
        Decision.OUT_OF_SCOPE,
    }
)


class SafetyClass(StrEnum):
    """Safety classification of a permitted diagnostic test.

    FlowLens only ever recommends OBSERVATION or DE_ENERGIZED_INSPECTION tests.
    ACTUATING exists solely so the safety tests can prove such tests are
    rejected by the planner.
    """

    OBSERVATION = "OBSERVATION"
    DE_ENERGIZED_INSPECTION = "DE_ENERGIZED_INSPECTION"
    ACTUATING = "ACTUATING"


#: The only safety classes the planner is permitted to recommend.
RECOMMENDABLE_SAFETY_CLASSES: frozenset[SafetyClass] = frozenset(
    {SafetyClass.OBSERVATION, SafetyClass.DE_ENERGIZED_INSPECTION}
)


class MaintenanceState(StrEnum):
    """Operational state of the asset when a test would be performed."""

    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    MAINTENANCE_MODE = "MAINTENANCE_MODE"
