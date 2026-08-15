"""Journey compiler: reconstruct phase occupancy from primitive evidence.

The compiler deliberately **ignores** ``PHASE_ENTERED`` events. A real controller
may or may not publish a state word, and if FlowLens simply believed it there
would be no reconstruction to demonstrate. Phases here are inferred from
commands, feedback signals and time guards only - which is also why a bouncing
lock contact never produces a ``LOCK_PROVED`` segment: the proof never holds for
the configured latch window.

``tests/unit/test_compiler.py`` asserts that stripping every ``PHASE_ENTERED``
event from a run changes nothing about the reconstruction.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from flowlens.config import JourneyModel, journey_model
from flowlens.contracts.enums import EventType, JourneyPhase
from flowlens.contracts.schemas import JourneyEvent, JourneySegment, ObservableRun

#: Phase reached when measured speed confirms the car is at its reference speed.
CRUISE_CONFIRM_FRACTION = 0.97


@dataclass
class JourneyFacts:
    """Event-derived facts the feature extractor needs.

    Kept separate from the segments so that features never have to re-parse the
    event stream and risk disagreeing with the reconstruction.
    """

    door_close_attempts: int = 0
    door_reopen_count: int = 0
    door_close_start_ms: int | None = None
    door_closed_ms: int | None = None

    lock_toggle_count: int = 0
    lock_proof_achieved: bool = False
    lock_true_ms: list[tuple[int, int]] = field(default_factory=list)

    chain_toggle_count: int = 0
    chain_proved: bool = False

    permit_present: bool = False
    contactor_commanded_ms: int | None = None
    contactor_confirmed_ms: int | None = None

    brake_command_ms: int | None = None
    brake_release_proof: bool = False
    brake_proof_ms: int | None = None

    torque_commanded_ms: int | None = None
    motion_detected_ms: int | None = None
    rated_speed_ref: float = 0.0

    alarms: list[str] = field(default_factory=list)
    aborted_reason: str | None = None

    @property
    def contactor_delay_ms(self) -> int | None:
        if self.contactor_commanded_ms is None or self.contactor_confirmed_ms is None:
            return None
        return self.contactor_confirmed_ms - self.contactor_commanded_ms

    @property
    def brake_release_delay_ms(self) -> int | None:
        if self.brake_command_ms is None or self.brake_proof_ms is None:
            return None
        return self.brake_proof_ms - self.brake_command_ms

    @property
    def lock_stable_ratio(self) -> float:
        """Fraction of the pre-motion window during which lock proof was held."""
        if self.door_close_start_ms is None or not self.lock_true_ms:
            return 0.0
        end = self.torque_commanded_ms or max(t for _, t in self.lock_true_ms)
        window = max(end - self.door_close_start_ms, 1)
        held = sum(min(stop, end) - start for start, stop in self.lock_true_ms if start < end)
        return max(0.0, min(1.0, held / window))


@dataclass
class CompiledJourney:
    segments: list[JourneySegment]
    facts: JourneyFacts
    terminal_phase: JourneyPhase
    retry_counts: dict[JourneyPhase, int] = field(default_factory=dict)
    rejected_transitions: list[tuple[int, JourneyPhase, JourneyPhase]] = field(
        default_factory=list
    )

    def segment_for(self, phase: JourneyPhase) -> JourneySegment | None:
        for segment in self.segments:
            if segment.phase == phase:
                return segment
        return None

    def reached(self, phase: JourneyPhase) -> bool:
        return any(s.phase == phase for s in self.segments)

    def phase_at(self, timestamp_ms: int) -> JourneyPhase | None:
        for segment in self.segments:
            if segment.start_ms <= timestamp_ms and (
                segment.end_ms is None or timestamp_ms < segment.end_ms
            ):
                return segment.phase
        return None


def _latch_times(
    events: list[JourneyEvent], event_type: EventType, hold_ms: int
) -> tuple[int | None, int, list[tuple[int, int]]]:
    """When a boolean proof first held for ``hold_ms``, plus its toggle history.

    Returns ``(latch_ms, toggle_count, true_intervals)``. ``latch_ms`` is None if
    the signal never held long enough - which is precisely the contact-bounce
    signature.
    """
    changes = [e for e in events if e.event_type == event_type]
    toggles = len(changes)
    intervals: list[tuple[int, int]] = []
    latch: int | None = None
    horizon = events[-1].timestamp_ms if events else 0

    open_from: int | None = None
    for change in changes:
        truthy = bool(change.value)
        if truthy and open_from is None:
            open_from = change.timestamp_ms
        elif not truthy and open_from is not None:
            intervals.append((open_from, change.timestamp_ms))
            open_from = None
    if open_from is not None:
        intervals.append((open_from, horizon))

    for start, stop in intervals:
        if stop - start >= hold_ms:
            latch = start + hold_ms
            break

    return latch, toggles, intervals


def compile_journey(run: ObservableRun, model: JourneyModel | None = None) -> CompiledJourney:
    """Reconstruct phase occupancy and journey facts from an observable run."""
    model = model or journey_model()
    events = sorted(run.events, key=lambda e: e.timestamp_ms)
    facts = JourneyFacts()

    # ---------------------------------------------------------------- #
    # Pass 1: primitive facts
    # ---------------------------------------------------------------- #
    for event in events:
        match event.event_type:
            case EventType.DOOR_CLOSE_COMMANDED:
                facts.door_close_attempts += 1
                if facts.door_close_start_ms is None:
                    facts.door_close_start_ms = event.timestamp_ms
            case EventType.DOOR_REOPEN_TRIGGERED:
                facts.door_reopen_count += 1
            case EventType.DOOR_POSITION_CHANGED:
                if event.value == "CLOSED" and facts.door_closed_ms is None:
                    facts.door_closed_ms = event.timestamp_ms
            case EventType.START_PERMIT_CHANGED:
                facts.permit_present = facts.permit_present or bool(event.value)
            case EventType.CONTACTOR_CHANGED:
                if event.value == "COMMANDED" and facts.contactor_commanded_ms is None:
                    facts.contactor_commanded_ms = event.timestamp_ms
                elif event.value == "CONFIRMED" and facts.contactor_confirmed_ms is None:
                    facts.contactor_confirmed_ms = event.timestamp_ms
            case EventType.BRAKE_COMMAND_CHANGED:
                if event.value == "RELEASE" and facts.brake_command_ms is None:
                    facts.brake_command_ms = event.timestamp_ms
            case EventType.BRAKE_PROOF_CHANGED:
                if event.value == "RELEASED" and not facts.brake_release_proof:
                    facts.brake_release_proof = True
                    facts.brake_proof_ms = event.timestamp_ms
            case EventType.SPEED_REFERENCE_CHANGED:
                value = float(event.value or 0.0)
                facts.rated_speed_ref = max(facts.rated_speed_ref, value)
                if value > 0.0 and facts.torque_commanded_ms is None:
                    facts.torque_commanded_ms = event.timestamp_ms
            case EventType.MOTION_DETECTED:
                if facts.motion_detected_ms is None:
                    facts.motion_detected_ms = event.timestamp_ms
            case EventType.ALARM_RAISED:
                if isinstance(event.value, str) and event.value not in facts.alarms:
                    facts.alarms.append(event.value)
            case EventType.RUN_ABORTED:
                facts.aborted_reason = str(event.value)
            case _:
                pass

    lock_hold = model.spec(JourneyPhase.LOCK_PROVED).entry_hold_ms or 250
    chain_hold = model.spec(JourneyPhase.SAFETY_CHAIN_PROVED).entry_hold_ms or 200
    lock_latch, lock_toggles, lock_intervals = _latch_times(
        events, EventType.LOCK_PROOF_CHANGED, lock_hold
    )
    chain_latch, chain_toggles, _ = _latch_times(
        events, EventType.SAFETY_CHAIN_CHANGED, chain_hold
    )
    facts.lock_toggle_count = lock_toggles
    facts.lock_true_ms = lock_intervals
    facts.lock_proof_achieved = lock_latch is not None
    facts.chain_toggle_count = chain_toggles
    facts.chain_proved = chain_latch is not None

    # ---------------------------------------------------------------- #
    # Pass 2: candidate phase triggers on a single merged timeline
    # ---------------------------------------------------------------- #
    triggers: list[tuple[int, JourneyPhase, str]] = []

    for event in events:
        match event.event_type:
            case EventType.CALL_REGISTERED:
                triggers.append((event.timestamp_ms, JourneyPhase.CALL_ACCEPTED, "call registered"))
            case EventType.DOOR_CLOSE_COMMANDED:
                triggers.append(
                    (event.timestamp_ms, JourneyPhase.DOOR_CLOSING, "door close commanded")
                )
            case EventType.START_PERMIT_CHANGED if bool(event.value):
                triggers.append(
                    (event.timestamp_ms, JourneyPhase.START_PERMIT, "start permission asserted")
                )
            case EventType.BRAKE_COMMAND_CHANGED if event.value == "RELEASE":
                triggers.append(
                    (event.timestamp_ms, JourneyPhase.BRAKE_RELEASE, "brake release commanded")
                )
            case EventType.SPEED_REFERENCE_CHANGED if float(event.value or 0.0) > 0.0:
                triggers.append(
                    (event.timestamp_ms, JourneyPhase.TORQUE_BUILD, "speed reference commanded")
                )
            case EventType.MOTION_DETECTED:
                triggers.append(
                    (event.timestamp_ms, JourneyPhase.ACCELERATION, "motion confirmed by feedback")
                )
            case EventType.SPEED_REFERENCE_CHANGED if float(event.value or 0.0) == 0.0:
                triggers.append(
                    (event.timestamp_ms, JourneyPhase.DECELERATION, "deceleration commanded")
                )
            case EventType.LEVEL_REACHED:
                triggers.append((event.timestamp_ms, JourneyPhase.LEVELING, "landing zone reached"))
            case EventType.BRAKE_COMMAND_CHANGED if event.value == "SET":
                triggers.append((event.timestamp_ms, JourneyPhase.BRAKE_SET, "brake set commanded"))
            case EventType.DOOR_OPEN_COMMANDED:
                triggers.append(
                    (event.timestamp_ms, JourneyPhase.DOOR_OPENING, "door open commanded")
                )
            case EventType.DOOR_POSITION_CHANGED if event.value == "OPEN":
                triggers.append(
                    (event.timestamp_ms, JourneyPhase.DOOR_OPEN, "door reported fully open")
                )
            case EventType.RUN_ABORTED:
                triggers.append(
                    (event.timestamp_ms, JourneyPhase.INCIDENT_STOP, f"run aborted: {event.value}")
                )
            case _:
                pass

    if lock_latch is not None:
        triggers.append(
            (lock_latch, JourneyPhase.LOCK_PROVED, f"lock proof held {lock_hold} ms")
        )
    if chain_latch is not None:
        triggers.append(
            (chain_latch, JourneyPhase.SAFETY_CHAIN_PROVED, f"safety chain held {chain_hold} ms")
        )

    cruise_ms = _cruise_confirmation(run, facts)
    if cruise_ms is not None:
        triggers.append((cruise_ms, JourneyPhase.CRUISE, "measured speed reached reference"))

    triggers.sort(key=lambda item: (item[0], item[1].value))

    # ---------------------------------------------------------------- #
    # Pass 3: walk the automaton
    # ---------------------------------------------------------------- #
    segments: list[JourneySegment] = [
        JourneySegment(
            phase=JourneyPhase.IDLE,
            start_ms=events[0].timestamp_ms if events else 0,
            entry_evidence=["journey start"],
            expected_next=list(model.spec(JourneyPhase.IDLE).expected_next),
            guard_ms=model.spec(JourneyPhase.IDLE).guard_ms,
        )
    ]
    retry_counts: dict[JourneyPhase, int] = {}
    rejected: list[tuple[int, JourneyPhase, JourneyPhase]] = []

    for timestamp, target, evidence in triggers:
        current = segments[-1]
        if target == current.phase:
            retry_counts[target] = retry_counts.get(target, 0) + 1
            current.entry_evidence.append(f"repeat: {evidence}")
            continue
        if not model.is_allowed(current.phase, target):
            # Kept, not silently dropped: the localizer reports these as
            # prohibited or premature transitions.
            rejected.append((timestamp, current.phase, target))
            continue

        current.end_ms = timestamp
        current.dwell_ms = timestamp - current.start_ms
        spec = model.spec(current.phase)
        if spec.guard_ms is not None and current.dwell_ms > spec.guard_ms:
            current.timed_out = True

        target_spec = model.spec(target)
        segments.append(
            JourneySegment(
                phase=target,
                start_ms=timestamp,
                entry_evidence=[evidence],
                expected_next=list(target_spec.expected_next),
                guard_ms=target_spec.guard_ms,
            )
        )

    last = segments[-1]
    horizon = run.frames[-1].timestamp_ms if run.frames else last.start_ms
    last.end_ms = horizon
    last.dwell_ms = horizon - last.start_ms
    last_spec = model.spec(last.phase)
    if last_spec.guard_ms is not None and last.dwell_ms > last_spec.guard_ms:
        last.timed_out = True

    return CompiledJourney(
        segments=segments,
        facts=facts,
        terminal_phase=segments[-1].phase,
        retry_counts=retry_counts,
        rejected_transitions=rejected,
    )


def _cruise_confirmation(run: ObservableRun, facts: JourneyFacts) -> int | None:
    """First moment measured speed confirms the car reached its reference.

    Derived from the speed channel rather than from any controller state word,
    so a lost encoder means cruise genuinely cannot be confirmed - which is the
    honest outcome.
    """
    if facts.rated_speed_ref <= 0.0 or facts.motion_detected_ms is None:
        return None
    target = facts.rated_speed_ref * CRUISE_CONFIRM_FRACTION
    for frame in run.frames:
        if frame.timestamp_ms <= facts.motion_detected_ms:
            continue
        speed = frame.signals.get("speed_mps")
        if speed is not None and speed >= target:
            return frame.timestamp_ms
    return None
