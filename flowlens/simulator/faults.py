"""Fault mechanisms and the declared-effect discipline that keeps them honest.

Every fault may only modify the mechanism fields it declares in
:data:`MECHANISM_FIELDS`. :func:`apply_injections` verifies this after applying
each injection, so a fault cannot quietly acquire a second physical pathway and
make itself artificially easy to detect.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Any

from flowlens.contracts.enums import FaultId
from flowlens.contracts.schemas import FaultInjection


@dataclass(frozen=True)
class Mechanism:
    """The complete set of physical and logical knobs a fault may turn.

    Defaults describe a perfectly healthy installation. Any field that differs
    from its default is, by construction, attributable to a declared injection.
    """

    # -- door -------------------------------------------------------------- #
    lock_bounce_count: int = 0
    lock_proof_blocked: bool = False
    door_obstruction_count: int = 0
    door_friction: float = 1.0
    door_speed_factor: float = 1.0
    door_position_stuck: bool = False

    # -- safety and start permission --------------------------------------- #
    safety_chain_chatter: int = 0
    start_permit_blocked: bool = False
    contactor_delay_ms: int = 120
    comms_gap_rate: float = 0.0

    # -- power ------------------------------------------------------------- #
    supply_sag_depth: float = 0.0
    bus_undervoltage_depth: float = 0.0

    # -- drive ------------------------------------------------------------- #
    current_limit_factor: float = 1.0
    current_surge_factor: float = 1.0
    cooling_factor: float = 1.0

    # -- feedback ---------------------------------------------------------- #
    encoder_dropout_from_ms: int | None = None
    encoder_noise_gain: float = 1.0
    encoder_scale_error: float = 1.0

    # -- brake and mechanical ---------------------------------------------- #
    brake_release_blocked: bool = False
    brake_drag_force_n: float = 0.0
    position_resistance_gain: float = 0.0


#: Which mechanism fields each fault is permitted to touch. A fault absent from
#: this mapping cannot be injected at all.
MECHANISM_FIELDS: dict[FaultId, tuple[str, ...]] = {
    FaultId.DOOR_LOCK_BOUNCE: ("lock_bounce_count",),
    FaultId.DOOR_LOCK_PROOF_ABSENT: ("lock_proof_blocked",),
    FaultId.DOOR_OBSTRUCTION: ("door_obstruction_count", "door_friction"),
    FaultId.DOOR_MOTOR_OVERLOAD: ("door_friction", "door_speed_factor"),
    FaultId.DOOR_POSITION_SENSOR_FAULT: ("door_position_stuck",),
    FaultId.SAFETY_CHAIN_INTERMITTENT: ("safety_chain_chatter",),
    FaultId.START_PERMIT_MISSING: ("start_permit_blocked",),
    FaultId.CONTACTOR_DELAY: ("contactor_delay_ms",),
    FaultId.COMMS_CORRUPTION: ("comms_gap_rate",),
    FaultId.SUPPLY_SAG: ("supply_sag_depth",),
    FaultId.DC_BUS_UNDERVOLTAGE: ("bus_undervoltage_depth", "current_limit_factor"),
    FaultId.DRIVE_OVERCURRENT: ("current_surge_factor",),
    FaultId.DRIVE_COOLING_DEGRADATION: ("cooling_factor",),
    FaultId.ENCODER_DROPOUT: ("encoder_dropout_from_ms",),
    FaultId.ENCODER_DRIFT: ("encoder_noise_gain",),
    FaultId.SPEED_MISMATCH: ("encoder_scale_error",),
    FaultId.BRAKE_RELEASE_FAILURE: ("brake_release_blocked",),
    FaultId.BRAKE_DRAG: ("brake_drag_force_n",),
    FaultId.MECHANICAL_RESISTANCE: ("position_resistance_gain",),
    # SENSOR_FAULT is realized purely through channel defects applied to the
    # recorded frames. It has no physical mechanism, which is exactly why the
    # engine must be able to tell it apart from equipment failure.
    FaultId.SENSOR_FAULT: (),
}


def mechanism_fields(fault_id: FaultId) -> tuple[str, ...]:
    if fault_id not in MECHANISM_FIELDS:
        raise KeyError(f"fault {fault_id.value} has no declared mechanism")
    return MECHANISM_FIELDS[fault_id]


def _default_effects(fault_id: FaultId, severity: float) -> dict[str, Any]:
    """Nominal mechanism settings for a fault at the given severity.

    Values were chosen so that each scenario produces a visually distinct and
    physically coherent trace. They are demo values, not field measurements.
    """
    s = max(0.0, min(1.0, severity))
    match fault_id:
        case FaultId.DOOR_LOCK_BOUNCE:
            return {"lock_bounce_count": int(round(3 + 4 * s))}
        case FaultId.DOOR_LOCK_PROOF_ABSENT:
            return {"lock_proof_blocked": True}
        case FaultId.DOOR_OBSTRUCTION:
            return {
                "door_obstruction_count": int(round(1 + 2 * s)),
                "door_friction": 1.0 + 0.95 * s,
            }
        case FaultId.DOOR_MOTOR_OVERLOAD:
            return {"door_friction": 1.0 + 1.25 * s, "door_speed_factor": 1.0 + 0.85 * s}
        case FaultId.DOOR_POSITION_SENSOR_FAULT:
            return {"door_position_stuck": True}
        case FaultId.SAFETY_CHAIN_INTERMITTENT:
            return {"safety_chain_chatter": int(round(3 + 3 * s))}
        case FaultId.START_PERMIT_MISSING:
            return {"start_permit_blocked": True}
        case FaultId.CONTACTOR_DELAY:
            return {"contactor_delay_ms": int(round(120 + 900 * s))}
        case FaultId.COMMS_CORRUPTION:
            return {"comms_gap_rate": 0.02 + 0.06 * s}
        case FaultId.SUPPLY_SAG:
            return {"supply_sag_depth": 0.06 + 0.09 * s}
        case FaultId.DC_BUS_UNDERVOLTAGE:
            return {
                "bus_undervoltage_depth": 0.14 + 0.13 * s,
                "current_limit_factor": 1.0 - 0.55 * s,
            }
        case FaultId.DRIVE_OVERCURRENT:
            return {"current_surge_factor": 1.0 + 1.15 * s}
        case FaultId.DRIVE_COOLING_DEGRADATION:
            return {"cooling_factor": 1.0 - 0.62 * s}
        case FaultId.ENCODER_DROPOUT:
            # Onset is supplied by the injection itself; the mechanism only
            # records from when feedback vanishes.
            return {"encoder_dropout_from_ms": 0}
        case FaultId.ENCODER_DRIFT:
            return {"encoder_noise_gain": 1.0 + 4.5 * s}
        case FaultId.SPEED_MISMATCH:
            return {"encoder_scale_error": 1.0 - 0.22 * s}
        case FaultId.BRAKE_RELEASE_FAILURE:
            return {"brake_release_blocked": True}
        case FaultId.BRAKE_DRAG:
            return {"brake_drag_force_n": 620.0 + 720.0 * s}
        case FaultId.MECHANICAL_RESISTANCE:
            return {"position_resistance_gain": 320.0 + 380.0 * s}
        case FaultId.SENSOR_FAULT:
            return {}
        case _:  # pragma: no cover - guarded by mechanism_fields
            raise KeyError(f"no mechanism defined for {fault_id.value}")


class MechanismViolation(RuntimeError):
    """Raised when a fault injection touched an undeclared mechanism field."""


def apply_injections(
    base: Mechanism, injections: list[FaultInjection]
) -> tuple[Mechanism, dict[FaultId, int]]:
    """Apply each injection, verifying it only touched its declared fields.

    Returns the resulting mechanism and a map of fault -> onset_ms, which the
    journey loop uses to activate time-dependent mechanisms.
    """
    current = base
    onsets: dict[FaultId, int] = {}

    for injection in injections:
        allowed = set(mechanism_fields(injection.fault_id))
        effects = _default_effects(injection.fault_id, injection.severity)
        effects.update(injection.params)

        if injection.fault_id == FaultId.ENCODER_DROPOUT:
            effects["encoder_dropout_from_ms"] = injection.onset_ms

        stray = set(effects) - allowed
        if stray:
            raise MechanismViolation(
                f"{injection.fault_id.value} attempted to modify undeclared mechanism "
                f"field(s) {sorted(stray)}; declared fields are {sorted(allowed)}"
            )

        before = current
        current = replace(current, **effects)

        changed = {
            f.name
            for f in fields(Mechanism)
            if getattr(before, f.name) != getattr(current, f.name)
        }
        if not changed <= allowed:
            raise MechanismViolation(
                f"{injection.fault_id.value} changed {sorted(changed - allowed)} "
                "outside its declared mechanism"
            )

        onsets[injection.fault_id] = injection.onset_ms

    return current, onsets


def describe(mechanism: Mechanism) -> dict[str, Any]:
    """Fields differing from healthy defaults. Used only in ground-truth notes."""
    healthy = Mechanism()
    return {
        f.name: getattr(mechanism, f.name)
        for f in fields(Mechanism)
        if getattr(mechanism, f.name) != getattr(healthy, f.name)
    }
