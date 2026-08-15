"""First-deviation localization.

The earliest well-supported departure from the expected journey carries more
causal weight than any downstream alarm, because downstream alarms are usually
the *consequence*. This module finds every deviation it can support, orders them
in time, and hands the earliest one to the inference stage as a constraint.

It never declares the first deviation to be the root cause. It says where the
journey stopped behaving, and which subsystems could produce that.
"""

from __future__ import annotations

import numpy as np

from flowlens.config import JourneyModel, journey_model
from flowlens.contracts.enums import DeviationType, JourneyPhase
from flowlens.contracts.schemas import FirstDeviation, ObservableRun
from flowlens.diagnosis.compiler import CompiledJourney
from flowlens.ingestion.quality import StreamQuality

#: Phases whose natural end is the end of the journey, so "no successor" is not
#: itself a deviation.
BENIGN_TERMINALS: frozenset[JourneyPhase] = frozenset(
    {JourneyPhase.IDLE, JourneyPhase.DOOR_OPEN, JourneyPhase.MAINTENANCE}
)

#: Minimum sustained disagreement before a signal/event inconsistency is raised.
INCONSISTENCY_HOLD_MS = 300
MOTION_EVIDENCE_MPS = 0.10
SPEED_DISAGREEMENT_FRACTION = 0.30

#: A phase must fall well short of its minimum dwell before being called
#: premature. Marginal undershoot is normal variation, and flagging it would put
#: a deviation on every healthy journey.
PREMATURE_FRACTION = 0.6

#: Sustained shortfall of measured speed against the commanded reference. This
#: is what a car that cannot keep up looks like, whatever the cause.
TRACKING_SHORTFALL_FRACTION = 0.35
TRACKING_HOLD_MS = 700


def localize_deviations(
    run: ObservableRun,
    compiled: CompiledJourney,
    quality: StreamQuality,
    model: JourneyModel | None = None,
) -> list[FirstDeviation]:
    """All supported deviations, earliest first."""
    model = model or journey_model()
    found: list[FirstDeviation] = []
    found += _transition_deviations(compiled, model)
    found += _retry_loops(compiled, model)
    found += _prohibited_transitions(compiled, model)
    found += _contradictory_states(compiled, model)
    found += _signal_event_inconsistencies(run, compiled, quality, model)

    found.sort(key=lambda d: (d.timestamp_ms, -d.confidence))

    # Two detectors can legitimately fire on the same moment for the same reason
    # (a lost channel is both "absent" and "disagreeing"). Keep the strongest.
    deduped: list[FirstDeviation] = []
    seen: set[tuple[JourneyPhase, DeviationType, int]] = set()
    for deviation in found:
        key = (deviation.phase, deviation.type, deviation.timestamp_ms)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(deviation)
    return deduped


def first_deviation(deviations: list[FirstDeviation]) -> FirstDeviation | None:
    """The earliest deviation with enough support to act on."""
    for deviation in deviations:
        if deviation.confidence >= 0.4:
            return deviation
    return deviations[0] if deviations else None


# --------------------------------------------------------------------------- #
# Transition timing
# --------------------------------------------------------------------------- #


def _domains(model: JourneyModel, phase: JourneyPhase) -> list[str]:
    return list(model.spec(phase).affected_domains)


def _transition_deviations(
    compiled: CompiledJourney, model: JourneyModel
) -> list[FirstDeviation]:
    out: list[FirstDeviation] = []
    segments = compiled.segments

    for index, segment in enumerate(segments):
        spec = model.spec(segment.phase)
        expected = spec.primary_next
        guard = spec.guard_ms
        successor = segments[index + 1].phase if index + 1 < len(segments) else None
        dwell = segment.dwell_ms or 0

        if successor is None:
            if segment.phase in BENIGN_TERMINALS or spec.terminal or expected is None:
                continue
            if guard is not None and dwell > guard:
                out.append(
                    FirstDeviation(
                        phase=segment.phase,
                        type=DeviationType.MISSING_TRANSITION,
                        timestamp_ms=segment.start_ms + guard,
                        expected_next=expected,
                        guard_ms=guard,
                        observed_delay_ms=dwell - guard,
                        statement=(
                            f"Expected {segment.phase.value} -> {expected.value} within "
                            f"{guard} ms. Observed: the journey never left "
                            f"{segment.phase.value}. {expected.value} was never established."
                        ),
                        affected_domains=_domains(model, segment.phase),
                        confidence=0.95,
                    )
                )
            continue

        if successor == expected:
            if guard is not None and dwell > guard:
                out.append(
                    FirstDeviation(
                        phase=segment.phase,
                        type=DeviationType.LATE_TRANSITION,
                        timestamp_ms=segment.start_ms + guard,
                        expected_next=expected,
                        guard_ms=guard,
                        observed_delay_ms=dwell - guard,
                        statement=(
                            f"Expected {segment.phase.value} -> {expected.value} within "
                            f"{guard} ms. Observed: the transition took {dwell} ms, "
                            f"{dwell - guard} ms beyond its guard."
                        ),
                        affected_domains=_domains(model, segment.phase),
                        confidence=0.9,
                    )
                )
            elif dwell < spec.dwell_min_ms * PREMATURE_FRACTION and index > 0:
                out.append(
                    FirstDeviation(
                        phase=segment.phase,
                        type=DeviationType.PREMATURE_TRANSITION,
                        timestamp_ms=segment.start_ms + dwell,
                        expected_next=expected,
                        guard_ms=guard,
                        observed_delay_ms=dwell - spec.dwell_min_ms,
                        statement=(
                            f"{segment.phase.value} lasted only {dwell} ms, below its "
                            f"expected minimum of {spec.dwell_min_ms} ms."
                        ),
                        affected_domains=_domains(model, segment.phase),
                        confidence=0.55,
                    )
                )
            continue

        # Successor is an incident/maintenance exit rather than the expected next.
        if expected is not None and successor in model.always_allowed_next:
            timestamp = segment.start_ms + guard if guard is not None else segment.start_ms + dwell
            out.append(
                FirstDeviation(
                    phase=segment.phase,
                    type=DeviationType.MISSING_TRANSITION,
                    timestamp_ms=min(timestamp, segments[index + 1].start_ms),
                    expected_next=expected,
                    guard_ms=guard,
                    observed_delay_ms=(dwell - guard) if guard is not None else None,
                    statement=(
                        f"Expected {segment.phase.value} -> {expected.value}"
                        + (f" within {guard} ms" if guard is not None else "")
                        + f". Observed: {segment.phase.value} -> {successor.value} after "
                        f"{dwell} ms. {expected.value} was never established."
                    ),
                    affected_domains=_domains(model, segment.phase),
                    confidence=0.95,
                )
            )
    return out


# --------------------------------------------------------------------------- #
# Retry loops
# --------------------------------------------------------------------------- #


def _retry_loops(compiled: CompiledJourney, model: JourneyModel) -> list[FirstDeviation]:
    out: list[FirstDeviation] = []
    facts = compiled.facts
    threshold = model.retry_loop_threshold

    if facts.door_close_attempts > 1:
        segment = compiled.segment_for(JourneyPhase.DOOR_CLOSING)
        start = segment.start_ms if segment else 0
        out.append(
            FirstDeviation(
                phase=JourneyPhase.DOOR_CLOSING,
                type=DeviationType.RETRY_LOOP,
                timestamp_ms=start,
                expected_next=JourneyPhase.LOCK_PROVED,
                statement=(
                    f"Door close was commanded {facts.door_close_attempts} times with "
                    f"{facts.door_reopen_count} reopen event(s). A single close sequence "
                    "is expected."
                ),
                affected_domains=_domains(model, JourneyPhase.DOOR_CLOSING),
                confidence=0.85 if facts.door_close_attempts > threshold else 0.6,
            )
        )

    if facts.lock_toggle_count > threshold and not facts.lock_proof_achieved:
        segment = compiled.segment_for(JourneyPhase.DOOR_CLOSING)
        start = facts.lock_true_ms[0][0] if facts.lock_true_ms else (segment.start_ms if segment else 0)
        hold = model.spec(JourneyPhase.LOCK_PROVED).entry_hold_ms
        out.append(
            FirstDeviation(
                phase=JourneyPhase.DOOR_CLOSING,
                type=DeviationType.RETRY_LOOP,
                timestamp_ms=start,
                expected_next=JourneyPhase.LOCK_PROVED,
                statement=(
                    f"Lock proof changed state {facts.lock_toggle_count} times and never "
                    f"held for the required {hold} ms. LOCK_PROVED was never established."
                ),
                affected_domains=_domains(model, JourneyPhase.DOOR_CLOSING),
                confidence=0.92,
            )
        )

    if facts.chain_toggle_count > threshold and not facts.chain_proved:
        segment = compiled.segment_for(JourneyPhase.LOCK_PROVED)
        start = segment.start_ms if segment else 0
        hold = model.spec(JourneyPhase.SAFETY_CHAIN_PROVED).entry_hold_ms
        out.append(
            FirstDeviation(
                phase=JourneyPhase.LOCK_PROVED,
                type=DeviationType.RETRY_LOOP,
                timestamp_ms=start,
                expected_next=JourneyPhase.SAFETY_CHAIN_PROVED,
                statement=(
                    f"Safety chain changed state {facts.chain_toggle_count} times after a "
                    f"clean lock proof and never held for the required {hold} ms."
                ),
                affected_domains=_domains(model, JourneyPhase.LOCK_PROVED),
                confidence=0.92,
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Illegal and contradictory states
# --------------------------------------------------------------------------- #


def _prohibited_transitions(
    compiled: CompiledJourney, model: JourneyModel
) -> list[FirstDeviation]:
    out: list[FirstDeviation] = []
    for timestamp, source, target in compiled.rejected_transitions:
        prohibited = model.is_prohibited(source, target)
        out.append(
            FirstDeviation(
                phase=source,
                type=(
                    DeviationType.PROHIBITED_TRANSITION
                    if prohibited
                    else DeviationType.PREMATURE_TRANSITION
                ),
                timestamp_ms=timestamp,
                expected_next=model.spec(source).primary_next,
                statement=(
                    f"Evidence for {target.value} appeared while the journey was in "
                    f"{source.value}, which is "
                    + ("prohibited" if prohibited else "not an expected successor")
                    + " for that phase."
                ),
                affected_domains=_domains(model, source),
                confidence=0.7 if prohibited else 0.45,
            )
        )
    return out


def _contradictory_states(
    compiled: CompiledJourney, model: JourneyModel
) -> list[FirstDeviation]:
    """Motion reached without the full permission chain being evidenced."""
    out: list[FirstDeviation] = []
    reached_motion = [s for s in compiled.segments if s.phase in model.motion_phases]
    if not reached_motion:
        return out
    first_motion = reached_motion[0]
    missing = [p for p in model.motion_permission_chain if not compiled.reached(p)]
    if missing:
        out.append(
            FirstDeviation(
                phase=first_motion.phase,
                type=DeviationType.CONTRADICTORY_STATE,
                timestamp_ms=first_motion.start_ms,
                statement=(
                    f"{first_motion.phase.value} was reached without evidence for "
                    + ", ".join(p.value for p in missing)
                    + ". Motion is not reachable without the full permission chain."
                ),
                affected_domains=["safety chain", "controller input mapping", "communications"],
                confidence=0.8,
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Signal / event inconsistency
# --------------------------------------------------------------------------- #


def _position_speed(run: ObservableRun) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Timestamps, measured speed (nan where absent) and position-derived speed."""
    times = np.array([f.timestamp_ms for f in run.frames], dtype=float)
    measured = np.array(
        [float(f.signals["speed_mps"]) if "speed_mps" in f.signals else np.nan for f in run.frames]
    )
    positions = np.array(
        [float(f.signals["position_m"]) if "position_m" in f.signals else np.nan for f in run.frames]
    )
    derived = np.full_like(positions, np.nan)
    window = 5
    for i in range(len(positions)):
        lo = max(0, i - window)
        if np.isnan(positions[i]) or np.isnan(positions[lo]) or times[i] == times[lo]:
            continue
        derived[i] = (positions[i] - positions[lo]) / ((times[i] - times[lo]) / 1000.0)
    return times, measured, derived


def _sustained_windows(times: np.ndarray, flags: np.ndarray, hold_ms: int) -> list[int]:
    """Start timestamps of runs of True lasting at least ``hold_ms``."""
    starts: list[int] = []
    run_start: int | None = None
    for i, flag in enumerate(flags):
        if flag and run_start is None:
            run_start = i
        elif not flag and run_start is not None:
            if times[i - 1] - times[run_start] >= hold_ms:
                starts.append(int(times[run_start]))
            run_start = None
    if run_start is not None and times[-1] - times[run_start] >= hold_ms:
        starts.append(int(times[run_start]))
    return starts


def _signal_event_inconsistencies(
    run: ObservableRun,
    compiled: CompiledJourney,
    quality: StreamQuality,
    model: JourneyModel,
) -> list[FirstDeviation]:
    out: list[FirstDeviation] = []
    facts = compiled.facts
    if facts.torque_commanded_ms is None or len(run.frames) < 5:
        return out

    times, measured, derived = _position_speed(run)
    commanded = times >= facts.torque_commanded_ms
    moving = np.nan_to_num(derived, nan=0.0) > MOTION_EVIDENCE_MPS

    # (a) The car is demonstrably moving but the speed channel is absent.
    absent = commanded & moving & np.isnan(measured)
    for start in _sustained_windows(times, absent, INCONSISTENCY_HOLD_MS):
        phase = compiled.phase_at(start) or JourneyPhase.TORQUE_BUILD
        out.append(
            FirstDeviation(
                phase=phase,
                type=DeviationType.SIGNAL_EVENT_INCONSISTENCY,
                timestamp_ms=start,
                statement=(
                    "Torque was commanded and the independent position reference shows the "
                    "car moving, but the speed feedback channel carries no value. The "
                    "machine and the measurement disagree."
                ),
                affected_domains=["encoder feedback", "feedback wiring", "instrumentation"],
                confidence=0.9,
            )
        )

    # (b) The speed channel is frozen while position keeps changing.
    with np.errstate(invalid="ignore"):
        delta = np.abs(np.diff(measured, prepend=measured[0]))
    frozen = commanded & moving & (~np.isnan(measured)) & (delta < 1e-9)
    for start in _sustained_windows(times, frozen, 900):
        phase = compiled.phase_at(start) or JourneyPhase.CRUISE
        out.append(
            FirstDeviation(
                phase=phase,
                type=DeviationType.SIGNAL_EVENT_INCONSISTENCY,
                timestamp_ms=start,
                statement=(
                    "The speed channel is held at a constant value while the independent "
                    "position reference continues to change. The channel is frozen, not "
                    "the car."
                ),
                affected_domains=["instrumentation", "encoder feedback", "communications"],
                confidence=0.88,
            )
        )

    # (c) The car cannot hold its commanded speed. This covers every cause of a
    # shortfall - drag, a collapsed bus, added resistance - without naming one.
    reference = np.array(
        [
            float(f.signals["speed_ref_mps"]) if "speed_ref_mps" in f.signals else np.nan
            for f in run.frames
        ]
    )
    with np.errstate(invalid="ignore"):
        shortfall = (reference - np.nan_to_num(measured, nan=0.0)) > (
            TRACKING_SHORTFALL_FRACTION * (facts.rated_speed_ref or 1.0)
        )
    lagging = commanded & (~np.isnan(reference)) & np.nan_to_num(shortfall, nan=False)
    for start in _sustained_windows(times, lagging, TRACKING_HOLD_MS):
        phase = compiled.phase_at(start) or JourneyPhase.ACCELERATION
        out.append(
            FirstDeviation(
                phase=phase,
                type=DeviationType.SIGNAL_EVENT_INCONSISTENCY,
                timestamp_ms=start,
                statement=(
                    "Measured speed stayed more than "
                    f"{TRACKING_SHORTFALL_FRACTION:.0%} of rated speed below the commanded "
                    f"reference for over {TRACKING_HOLD_MS} ms. The car did not follow its "
                    "speed profile."
                ),
                affected_domains=list(model.spec(phase).affected_domains)
                or ["brake", "drive", "supply", "mechanical resistance"],
                confidence=0.82,
            )
        )

    # (d) Both channels present but disagreeing.
    rated = facts.rated_speed_ref or 1.0
    with np.errstate(invalid="ignore"):
        disagreement = np.abs(measured - derived) > SPEED_DISAGREEMENT_FRACTION * rated
    disagree = commanded & moving & (~np.isnan(measured)) & np.nan_to_num(disagreement, nan=False)
    for start in _sustained_windows(times, disagree, 500):
        phase = compiled.phase_at(start) or JourneyPhase.ACCELERATION
        out.append(
            FirstDeviation(
                phase=phase,
                type=DeviationType.SIGNAL_EVENT_INCONSISTENCY,
                timestamp_ms=start,
                statement=(
                    "Measured speed and the position-derived speed disagree by more than "
                    f"{SPEED_DISAGREEMENT_FRACTION:.0%} of rated speed while the car is moving."
                ),
                affected_domains=["encoder feedback", "drive regulation", "instrumentation"],
                confidence=0.75,
            )
        )

    return out
