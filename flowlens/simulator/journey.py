"""The elevator journey state machine and its signal generation.

One :class:`JourneySimulation` produces one journey: a stream of controller-like
events and a stream of sampled signal frames. Phase guards come from
``configs/journey_phases.yaml``, so the simulator and the diagnostic engine share
a single definition of what "expected" means.

Determinism: all randomness comes from the injected ``numpy`` generator. Given
the same seed, mechanism and configuration, the output is bit-stable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from flowlens.config import JourneyModel, journey_model
from flowlens.contracts.enums import EventType, JourneyPhase
from flowlens.contracts.schemas import JourneyEvent, SignalFrame
from flowlens.simulator.faults import Mechanism
from flowlens.simulator.physics import (
    AssetProfile,
    door_current,
    thermal_step,
    trapezoid_reference,
    vibration,
)

DT_S = 0.02
DT_MS = 20
MAX_JOURNEY_MS = 40_000

#: Generic alarm vocabulary. These are FlowLens' own synthetic alarm names and
#: are deliberately not modelled on any manufacturer's fault-code set.
ALARM_BY_PHASE: dict[JourneyPhase, str] = {
    JourneyPhase.CALL_ACCEPTED: "DOOR_CLOSE_TIMEOUT",
    JourneyPhase.DOOR_CLOSING: "LOCK_PROOF_TIMEOUT",
    JourneyPhase.LOCK_PROVED: "SAFETY_CIRCUIT_OPEN",
    JourneyPhase.SAFETY_CHAIN_PROVED: "START_PERMIT_TIMEOUT",
    JourneyPhase.START_PERMIT: "CONTACTOR_FEEDBACK_TIMEOUT",
    JourneyPhase.BRAKE_RELEASE: "BRAKE_RELEASE_TIMEOUT",
    JourneyPhase.TORQUE_BUILD: "TORQUE_BUILD_TIMEOUT",
    JourneyPhase.ACCELERATION: "MOTION_TIMEOUT",
    JourneyPhase.CRUISE: "MOTION_TIMEOUT",
    JourneyPhase.DECELERATION: "MOTION_TIMEOUT",
    JourneyPhase.LEVELING: "LEVELING_TIMEOUT",
    JourneyPhase.BRAKE_SET: "BRAKE_SET_TIMEOUT",
    JourneyPhase.DOOR_OPENING: "DOOR_OPEN_TIMEOUT",
    JourneyPhase.DOOR_OPEN: "DOOR_OPEN_TIMEOUT",
}


@dataclass
class _State:
    t_ms: int = 0
    phase: JourneyPhase = JourneyPhase.IDLE
    phase_entry_ms: int = 0
    guard_alarmed: bool = False
    aborted: bool = False

    # door
    door_pos: float = 1.0  # 1.0 fully open, 0.0 fully closed
    door_dir: int = 0  # -1 closing, +1 opening, 0 still
    door_attempts: int = 0
    obstructions_used: int = 0
    door_reopening_until_ms: int = 0
    door_closed_reported: bool = False

    # lock / safety / permit
    lock_proof: bool = False
    lock_true_since: int | None = None
    lock_latched: bool = False
    bounce_remaining: int = 0
    bounce_next_ms: int = 0

    chain: bool = False
    chain_true_since: int | None = None
    chain_latched: bool = False
    chatter_remaining: int = 0
    chatter_next_ms: int = 0

    permit: bool = False
    contactor: bool = False
    contactor_cmd_ms: int | None = None

    # brake
    brake_cmd_release: bool = False
    brake_cmd_ms: int | None = None
    brake_engagement: float = 1.0
    brake_proof: bool = False
    brake_current: float = 0.0

    # motion
    position_m: float = 0.0
    velocity_mps: float = 0.0
    accel_mps2: float = 0.0
    applied_force_n: float = 0.0
    motion_elapsed_s: float = 0.0
    speed_ref: float = 0.0
    torque_commanded: bool = False

    # thermal
    temp_c: float = 0.0

    # feedback health
    feedback_lost_since: int | None = None
    speed_dev_since: int | None = None

    alarms: list[str] = field(default_factory=list)


class JourneySimulation:
    """Simulates one elevator journey under a given mechanism."""

    def __init__(
        self,
        *,
        mechanism: Mechanism,
        asset_id: str,
        journey_id: str,
        seed: int,
        profile: AssetProfile,
        model: JourneyModel | None = None,
    ) -> None:
        self.mech = mechanism
        self.asset_id = asset_id
        self.journey_id = journey_id
        self.profile = profile
        self.model = model or journey_model()
        self.rng = np.random.default_rng(seed)
        self.events: list[JourneyEvent] = []
        self.frames: list[SignalFrame] = []
        self.s = _State(temp_c=profile.ambient_temp_c)

    # ------------------------------------------------------------------ #
    # Emission helpers
    # ------------------------------------------------------------------ #

    def _emit(
        self,
        event_type: EventType,
        value: bool | int | float | str | None = None,
        detail: str | None = None,
    ) -> None:
        self.events.append(
            JourneyEvent(
                asset_id=self.asset_id,
                journey_id=self.journey_id,
                timestamp_ms=self.s.t_ms,
                event_type=event_type,
                value=value,
                detail=detail,
            )
        )

    def _alarm(self, name: str) -> None:
        if name in self.s.alarms:
            return
        self.s.alarms.append(name)
        self._emit(EventType.ALARM_RAISED, value=name, detail=f"phase={self.s.phase.value}")

    def _enter(self, phase: JourneyPhase) -> None:
        self.s.phase = phase
        self.s.phase_entry_ms = self.s.t_ms
        self.s.guard_alarmed = False
        self._emit(EventType.PHASE_ENTERED, value=phase.value)

    def _abort(self, reason: str) -> None:
        self._emit(EventType.RUN_ABORTED, value=reason)
        self._enter(JourneyPhase.INCIDENT_STOP)
        self.s.aborted = True
        self.s.torque_commanded = False
        self.s.brake_cmd_release = False

    @property
    def _dwell_ms(self) -> int:
        return self.s.t_ms - self.s.phase_entry_ms

    # ------------------------------------------------------------------ #
    # Main loop
    # ------------------------------------------------------------------ #

    def run(self) -> tuple[list[JourneyEvent], list[SignalFrame], JourneyPhase, list[str]]:
        self._emit(EventType.CALL_REGISTERED, value=True, detail="landing call, up")
        self._enter(JourneyPhase.CALL_ACCEPTED)

        while self.s.t_ms <= MAX_JOURNEY_MS:
            self._step_logic()
            self._step_physics()
            self._emit_frame()
            self._check_guard()

            if self.s.phase in (JourneyPhase.INCIDENT_STOP, JourneyPhase.MAINTENANCE):
                # Record a short tail so the console has post-incident context.
                if self._dwell_ms >= 600:
                    break
            if self.s.phase == JourneyPhase.IDLE and self.s.t_ms > 0:
                break

            self.s.t_ms += DT_MS

        return self.events, self.frames, self.s.phase, self.s.alarms

    # ------------------------------------------------------------------ #
    # Controller / logic layer
    # ------------------------------------------------------------------ #

    def _step_logic(self) -> None:
        s = self.s
        match s.phase:
            case JourneyPhase.CALL_ACCEPTED:
                if self._dwell_ms >= 400:
                    self._command_door_close()
                    self._enter(JourneyPhase.DOOR_CLOSING)
            case JourneyPhase.DOOR_CLOSING:
                self._logic_door_closing()
            case JourneyPhase.LOCK_PROVED:
                self._logic_lock_proved()
            case JourneyPhase.SAFETY_CHAIN_PROVED:
                self._logic_safety_proved()
            case JourneyPhase.START_PERMIT:
                self._logic_start_permit()
            case JourneyPhase.BRAKE_RELEASE:
                self._logic_brake_release()
            case JourneyPhase.TORQUE_BUILD:
                self._logic_torque_build()
            case JourneyPhase.ACCELERATION:
                self._logic_acceleration()
            case JourneyPhase.CRUISE:
                self._logic_cruise()
            case JourneyPhase.DECELERATION:
                self._logic_deceleration()
            case JourneyPhase.LEVELING:
                self._logic_leveling()
            case JourneyPhase.BRAKE_SET:
                self._logic_brake_set()
            case JourneyPhase.DOOR_OPENING:
                self._logic_door_opening()
            case JourneyPhase.DOOR_OPEN:
                if self._dwell_ms >= 1200:
                    self._enter(JourneyPhase.IDLE)
            case _:
                pass

        self._update_lock_signal()
        self._update_chain_signal()

    def _command_door_close(self) -> None:
        self.s.door_attempts += 1
        self.s.door_dir = -1
        self._emit(EventType.DOOR_CLOSE_COMMANDED, value=self.s.door_attempts)

    def _logic_door_closing(self) -> None:
        s = self.s
        if s.t_ms < s.door_reopening_until_ms:
            return
        if s.door_reopening_until_ms and s.t_ms >= s.door_reopening_until_ms and s.door_dir == 1:
            s.door_reopening_until_ms = 0
            self._command_door_close()
            return

        # Obstruction fires partway through the close travel.
        if (
            self.mech.door_obstruction_count > s.obstructions_used
            and s.door_dir == -1
            and s.door_pos <= 0.45
        ):
            s.obstructions_used += 1
            s.door_dir = 1
            s.door_reopening_until_ms = s.t_ms + self.profile.door_reopen_ms
            self._emit(EventType.DOOR_REOPEN_TRIGGERED, value=s.obstructions_used)
            return

        if s.door_dir == -1 and s.door_pos <= 0.0 and not s.door_closed_reported:
            s.door_closed_reported = True
            if self.mech.door_position_stuck:
                # The sensor never reports the closed position even though the
                # operator current profile shows the door completed its travel.
                self._emit(
                    EventType.DOOR_POSITION_CHANGED,
                    value="CLOSING",
                    detail="position sensor did not confirm closed",
                )
            else:
                self._emit(EventType.DOOR_POSITION_CHANGED, value="CLOSED")
                self._begin_lock_proof()

        if s.lock_latched:
            self._enter(JourneyPhase.LOCK_PROVED)

    def _begin_lock_proof(self) -> None:
        s = self.s
        if self.mech.lock_proof_blocked:
            return
        if self.mech.lock_bounce_count > 0:
            s.bounce_remaining = self.mech.lock_bounce_count
            s.bounce_next_ms = s.t_ms
        else:
            s.lock_proof = True
            s.lock_true_since = s.t_ms
            self._emit(EventType.LOCK_PROOF_CHANGED, value=True)

    def _update_lock_signal(self) -> None:
        s = self.s
        if s.bounce_remaining > 0 and s.t_ms >= s.bounce_next_ms:
            s.lock_proof = not s.lock_proof
            s.lock_true_since = s.t_ms if s.lock_proof else None
            self._emit(EventType.LOCK_PROOF_CHANGED, value=s.lock_proof)
            s.bounce_remaining -= 1
            # Bounce period is shorter than the latch window, so proof never holds.
            s.bounce_next_ms = s.t_ms + 140
            if s.bounce_remaining == 0:
                # The contact settles open: proof is never established.
                if s.lock_proof:
                    s.lock_proof = False
                    s.lock_true_since = None
                    self._emit(EventType.LOCK_PROOF_CHANGED, value=False)
                s.bounce_next_ms = MAX_JOURNEY_MS + 1

        if s.lock_proof and s.lock_true_since is not None and not s.lock_latched:
            if s.t_ms - s.lock_true_since >= self.profile.lock_latch_ms:
                s.lock_latched = True

    def _logic_lock_proved(self) -> None:
        s = self.s
        if s.chain_true_since is None and s.chatter_remaining == 0 and not s.chain:
            if self._dwell_ms >= self.profile.safety_assert_delay_ms:
                if self.mech.safety_chain_chatter > 0:
                    s.chatter_remaining = self.mech.safety_chain_chatter
                    s.chatter_next_ms = s.t_ms
                else:
                    s.chain = True
                    s.chain_true_since = s.t_ms
                    self._emit(EventType.SAFETY_CHAIN_CHANGED, value=True)
        if s.chain_latched:
            self._enter(JourneyPhase.SAFETY_CHAIN_PROVED)

    def _update_chain_signal(self) -> None:
        s = self.s
        if s.chatter_remaining > 0 and s.t_ms >= s.chatter_next_ms:
            s.chain = not s.chain
            s.chain_true_since = s.t_ms if s.chain else None
            self._emit(EventType.SAFETY_CHAIN_CHANGED, value=s.chain)
            s.chatter_remaining -= 1
            s.chatter_next_ms = s.t_ms + 120
            if s.chatter_remaining == 0:
                # The contact settles open: the chain is never proved.
                if s.chain:
                    s.chain = False
                    s.chain_true_since = None
                    self._emit(EventType.SAFETY_CHAIN_CHANGED, value=False)
                s.chatter_next_ms = MAX_JOURNEY_MS + 1

        if s.chain and s.chain_true_since is not None and not s.chain_latched:
            if s.t_ms - s.chain_true_since >= self.profile.safety_latch_ms:
                s.chain_latched = True

    def _logic_safety_proved(self) -> None:
        s = self.s
        if self._dwell_ms >= self.profile.permit_assert_delay_ms and not s.permit:
            if self.mech.start_permit_blocked:
                return
            s.permit = True
            self._emit(EventType.START_PERMIT_CHANGED, value=True)
        if s.permit:
            s.contactor_cmd_ms = s.t_ms
            self._emit(EventType.CONTACTOR_CHANGED, value="COMMANDED")
            self._enter(JourneyPhase.START_PERMIT)

    def _logic_start_permit(self) -> None:
        s = self.s
        if not s.contactor and s.contactor_cmd_ms is not None:
            if s.t_ms - s.contactor_cmd_ms >= self.mech.contactor_delay_ms:
                s.contactor = True
                self._emit(
                    EventType.CONTACTOR_CHANGED,
                    value="CONFIRMED",
                    detail=f"delay_ms={s.t_ms - s.contactor_cmd_ms}",
                )
        if s.contactor and self._dwell_ms >= self.profile.brake_command_delay_ms:
            s.brake_cmd_release = True
            s.brake_cmd_ms = s.t_ms
            self._emit(EventType.BRAKE_COMMAND_CHANGED, value="RELEASE")
            self._enter(JourneyPhase.BRAKE_RELEASE)

    def _logic_brake_release(self) -> None:
        s = self.s
        spec = self.model.spec(JourneyPhase.BRAKE_RELEASE)
        guard = spec.guard_ms or 800
        if s.brake_proof:
            s.torque_commanded = True
            self._emit(EventType.SPEED_REFERENCE_CHANGED, value=self.profile.rated_speed_mps)
            self._enter(JourneyPhase.TORQUE_BUILD)
        elif self._dwell_ms > guard:
            # The drive still builds torque against an unproven brake. This is
            # what produces the current-without-motion signature of a brake that
            # never released.
            s.torque_commanded = True
            self._emit(
                EventType.SPEED_REFERENCE_CHANGED,
                value=self.profile.rated_speed_mps,
                detail="brake release proof absent",
            )
            self._enter(JourneyPhase.TORQUE_BUILD)

    def _logic_torque_build(self) -> None:
        s = self.s
        if abs(s.velocity_mps) >= self.profile.motion_confirm_mps:
            self._emit(EventType.MOTION_DETECTED, value=round(s.velocity_mps, 4))
            self._enter(JourneyPhase.ACCELERATION)

    def _logic_acceleration(self) -> None:
        s = self.s
        if s.velocity_mps >= self.profile.rated_speed_mps * 0.97:
            self._enter(JourneyPhase.CRUISE)
        elif self._remaining_m() <= self._stop_distance_m():
            self._emit(EventType.SPEED_REFERENCE_CHANGED, value=0.0, detail="deceleration")
            self._enter(JourneyPhase.DECELERATION)

    def _logic_cruise(self) -> None:
        if self._remaining_m() <= self._stop_distance_m():
            self._emit(EventType.SPEED_REFERENCE_CHANGED, value=0.0, detail="deceleration")
            self._enter(JourneyPhase.DECELERATION)

    def _logic_deceleration(self) -> None:
        s = self.s
        if s.velocity_mps <= 0.12 or self._remaining_m() <= 0.06:
            self._emit(EventType.LEVEL_REACHED, value=round(s.position_m, 4))
            self._enter(JourneyPhase.LEVELING)

    def _logic_leveling(self) -> None:
        s = self.s
        if abs(s.velocity_mps) <= 0.01:
            s.torque_commanded = False
            s.brake_cmd_release = False
            self._emit(EventType.BRAKE_COMMAND_CHANGED, value="SET")
            self._enter(JourneyPhase.BRAKE_SET)

    def _logic_brake_set(self) -> None:
        s = self.s
        if s.brake_engagement >= 0.95:
            if not s.brake_proof:
                self._emit(EventType.BRAKE_PROOF_CHANGED, value="SET")
            s.door_dir = 1
            self._emit(EventType.DOOR_OPEN_COMMANDED, value=True)
            self._enter(JourneyPhase.DOOR_OPENING)

    def _logic_door_opening(self) -> None:
        if self.s.door_pos >= 1.0:
            self._emit(EventType.DOOR_POSITION_CHANGED, value="OPEN")
            self._enter(JourneyPhase.DOOR_OPEN)

    def _remaining_m(self) -> float:
        return max(self.profile.travel_m - self.s.position_m, 0.0)

    def _stop_distance_m(self) -> float:
        return (self.s.velocity_mps**2) / (2.0 * self.profile.rated_accel_mps2)

    # ------------------------------------------------------------------ #
    # Physical layer
    # ------------------------------------------------------------------ #

    def _step_physics(self) -> None:
        s = self.s
        p = self.profile

        # Doors -------------------------------------------------------- #
        door_speed = 1.0 / (p.door_close_ms / 1000.0) / max(self.mech.door_speed_factor, 0.2)
        if s.door_dir == -1:
            s.door_pos = max(0.0, s.door_pos - door_speed * DT_S)
        elif s.door_dir == 1:
            open_speed = 1.0 / (p.door_open_ms / 1000.0)
            s.door_pos = min(1.0, s.door_pos + open_speed * DT_S)
            if s.door_pos >= 1.0 and s.phase == JourneyPhase.DOOR_OPENING:
                s.door_dir = 0

        # Brake -------------------------------------------------------- #
        if s.brake_cmd_release and not self.mech.brake_release_blocked:
            residual = min(self.mech.brake_drag_force_n / p.max_brake_force_n, 1.0)
            target = residual
            rate = (1.0 - residual) / (p.brake_release_ms / 1000.0)
            s.brake_engagement = max(target, s.brake_engagement - rate * DT_S)
            s.brake_current = p.nominal_brake_current_a * (1.0 - s.brake_engagement)
            if s.brake_engagement <= 0.30 and not s.brake_proof:
                s.brake_proof = True
                self._emit(EventType.BRAKE_PROOF_CHANGED, value="RELEASED")
        elif s.brake_cmd_release and self.mech.brake_release_blocked:
            # Coil is energized but the armature does not move.
            s.brake_engagement = 1.0
            s.brake_current = 0.25 * p.nominal_brake_current_a
        else:
            s.brake_engagement = min(1.0, s.brake_engagement + DT_S / 0.25)
            s.brake_current = p.nominal_brake_current_a * (1.0 - s.brake_engagement)
            if s.brake_engagement >= 0.95:
                s.brake_proof = False

        # Resistive forces --------------------------------------------- #
        drag_n = self.mech.brake_drag_force_n
        if self.mech.brake_release_blocked:
            drag_n = p.max_brake_force_n
        resistance_n = self.mech.position_resistance_gain * s.position_m

        # Drive -------------------------------------------------------- #
        if s.torque_commanded:
            s.motion_elapsed_s += DT_S
            ref_v, ref_a = trapezoid_reference(p, s.position_m, s.motion_elapsed_s)
            s.speed_ref = ref_v
            # Closed-loop velocity regulation. The reference is generated on a
            # time base, so a car that cannot keep up produces a real and growing
            # speed deviation - which is exactly the symptom a dragging brake or
            # a collapsed bus creates in the field.
            a_cmd = ref_a + p.speed_gain_per_s * (ref_v - s.velocity_mps)
            a_cmd = float(np.clip(a_cmd, -p.max_accel_cmd_mps2, p.max_accel_cmd_mps2))
            required = p.effective_mass_kg * a_cmd + p.base_friction_n + drag_n + resistance_n
            limit = p.force_limit_n * self.mech.current_limit_factor
            target = float(np.clip(required, -limit, limit))
            step = p.force_rate_n_per_s * DT_S
            s.applied_force_n = float(
                np.clip(target, s.applied_force_n - step, s.applied_force_n + step)
            )
        else:
            s.speed_ref = 0.0
            s.applied_force_n = max(0.0, s.applied_force_n - p.force_rate_n_per_s * DT_S)

        net = s.applied_force_n - p.base_friction_n - drag_n - resistance_n
        if abs(s.velocity_mps) < 1e-6 and net <= 0.0:
            accel = 0.0
        else:
            accel = net / p.effective_mass_kg
        s.velocity_mps = max(0.0, s.velocity_mps + accel * DT_S)
        if not s.torque_commanded and s.brake_engagement > 0.5:
            s.velocity_mps = max(0.0, s.velocity_mps - 2.0 * DT_S)
        s.accel_mps2 = accel
        s.position_m = min(p.travel_m, s.position_m + s.velocity_mps * DT_S)

        # Bus and thermal ---------------------------------------------- #
        # A supply sag is a *transient* that follows the load, which is what
        # separates it from a permanently biased voltage channel. An
        # undervoltage condition, by contrast, is present throughout.
        load_fraction = min(s.applied_force_n / max(p.force_limit_n, 1.0), 1.0)
        sag = self.mech.supply_sag_depth * load_fraction + self.mech.bus_undervoltage_depth
        current = p.force_to_current(s.applied_force_n, p.nominal_bus_v * (1.0 - sag))
        current *= self.mech.current_surge_factor
        s.temp_c = thermal_step(p, s.temp_c, current, self.mech.cooling_factor, DT_S)
        self._last_current = current
        self._last_bus = p.nominal_bus_v * (1.0 - sag) - p.bus_droop_v_per_amp * current

        # Independent alarm conditions --------------------------------- #
        if self._last_bus < p.nominal_bus_v * 0.80:
            self._alarm("DC_BUS_UNDERVOLTAGE")
        if current > p.nominal_motor_current_a * 1.90:
            self._alarm("DRIVE_OVERCURRENT")
            if self.mech.current_surge_factor > 1.0 and not s.aborted:
                self._abort("DRIVE_OVERCURRENT")
        if s.temp_c > p.ambient_temp_c + 9.0:
            self._alarm("DRIVE_OVERTEMP")

    # ------------------------------------------------------------------ #
    # Measurement layer
    # ------------------------------------------------------------------ #

    def _measured_speed(self) -> float | None:
        s = self.s
        dropout_from = self.mech.encoder_dropout_from_ms
        if dropout_from is not None and s.t_ms >= dropout_from:
            return None
        noise = float(self.rng.normal(0.0, 0.0025 * self.mech.encoder_noise_gain))
        return max(0.0, s.velocity_mps * self.mech.encoder_scale_error + noise)

    def _emit_frame(self) -> None:
        s = self.s
        p = self.profile
        current = getattr(self, "_last_current", 0.0)
        bus = getattr(self, "_last_bus", p.nominal_bus_v)

        measured_speed = self._measured_speed()
        door_moving = s.door_dir != 0 and 0.0 < s.door_pos < 1.0
        travel_fraction = 1.0 - s.door_pos if s.door_dir == -1 else s.door_pos

        signals: dict[str, float] = {
            "dc_bus_v": round(bus + float(self.rng.normal(0.0, 0.6)), 4),
            "motor_current_a": round(max(0.0, current + float(self.rng.normal(0.0, 0.05))), 4),
            "speed_ref_mps": round(s.speed_ref, 4),
            "brake_current_a": round(max(0.0, s.brake_current), 4),
            "door_current_a": round(
                door_current(p, travel_fraction, self.mech.door_friction, door_moving), 4
            ),
            "drive_temp_c": round(s.temp_c + float(self.rng.normal(0.0, 0.05)), 4),
            "vibration_rms": round(
                max(
                    0.0,
                    vibration(
                        p,
                        s.velocity_mps,
                        p.max_brake_force_n
                        if self.mech.brake_release_blocked
                        else self.mech.brake_drag_force_n,
                        self.mech.position_resistance_gain * s.position_m,
                    )
                    + float(self.rng.normal(0.0, 0.012)),
                ),
                4,
            ),
        }
        # Car position comes from an independent landing/shaft reference, which
        # is why an encoder dropout can be told apart from the car genuinely
        # standing still.
        signals["position_m"] = round(s.position_m + float(self.rng.normal(0.0, 0.002)), 4)

        if measured_speed is not None:
            signals["speed_mps"] = round(measured_speed, 4)
            signals["accel_mps2"] = round(
                s.accel_mps2 + float(self.rng.normal(0.0, 0.01 * self.mech.encoder_noise_gain)), 4
            )
            if s.feedback_lost_since is not None:
                s.feedback_lost_since = None
        else:
            if s.feedback_lost_since is None:
                s.feedback_lost_since = s.t_ms
                self._alarm("SPEED_FEEDBACK_LOST")
            elif (
                s.t_ms - s.feedback_lost_since >= self.profile.feedback_loss_trip_ms
                and not s.aborted
                and s.torque_commanded
            ):
                self._abort("SPEED_FEEDBACK_LOST")

        # Speed deviation watchdog on the measured channel.
        if measured_speed is not None and s.torque_commanded:
            if abs(s.speed_ref - measured_speed) > 0.35 * p.rated_speed_mps:
                if s.speed_dev_since is None:
                    s.speed_dev_since = s.t_ms
                elif s.t_ms - s.speed_dev_since >= 700:
                    self._alarm("SPEED_DEVIATION")
                    if s.t_ms - s.speed_dev_since >= 2500 and not s.aborted:
                        self._abort("SPEED_DEVIATION")
            else:
                s.speed_dev_since = None

        quality = {key: 1.0 for key in signals}
        self.frames.append(
            SignalFrame(
                asset_id=self.asset_id,
                journey_id=self.journey_id,
                timestamp_ms=s.t_ms,
                signals=signals,
                quality=quality,
            )
        )

    # ------------------------------------------------------------------ #
    # Guards
    # ------------------------------------------------------------------ #

    def _check_guard(self) -> None:
        s = self.s
        if s.aborted or s.phase in (JourneyPhase.INCIDENT_STOP, JourneyPhase.MAINTENANCE):
            return
        spec = self.model.spec(s.phase)
        if spec.guard_ms is None:
            return
        dwell = self._dwell_ms
        if dwell > spec.guard_ms and not s.guard_alarmed:
            s.guard_alarmed = True
            alarm = ALARM_BY_PHASE.get(s.phase)
            if s.phase == JourneyPhase.DOOR_CLOSING and s.door_pos > 0.0:
                alarm = "DOOR_CLOSE_TIMEOUT"
            if alarm:
                self._alarm(alarm)
        if dwell > spec.guard_ms * self.profile.guard_grace_factor:
            self._abort(f"{s.phase.value}_GUARD_EXPIRED")
