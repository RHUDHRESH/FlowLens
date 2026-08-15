"""Phase-conditioned physics and event features.

Two rules govern everything here:

1. **A feature that cannot be computed is ``None``, never zero.** Substituting a
   default would let missing data masquerade as a healthy reading, which is the
   single most dangerous failure mode in this product.

2. **Features are computed from what the recording actually says**, not from
   what the machine physically did. If a channel is frozen, the features derived
   from it will be wrong - and it is the channel-integrity evidence, not a quiet
   correction, that stops a wrong conclusion being drawn.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from flowlens.contracts.enums import JourneyPhase
from flowlens.contracts.schemas import ObservableRun
from flowlens.diagnosis.compiler import CompiledJourney
from flowlens.features.baselines import Baselines, load_baselines
from flowlens.ingestion.quality import StreamQuality

#: Which journey phase each feature is conditioned on, for display and for
#: first-deviation alignment.
FEATURE_PHASE: dict[str, JourneyPhase] = {
    "lock_proof_toggle_count": JourneyPhase.DOOR_CLOSING,
    "lock_proof_achieved": JourneyPhase.DOOR_CLOSING,
    "lock_proof_stable_ratio": JourneyPhase.DOOR_CLOSING,
    "door_close_attempts": JourneyPhase.DOOR_CLOSING,
    "door_current_peak_ratio": JourneyPhase.DOOR_CLOSING,
    "door_reopen_count": JourneyPhase.DOOR_CLOSING,
    "door_close_duration_ratio": JourneyPhase.DOOR_CLOSING,
    "safety_chain_toggle_count": JourneyPhase.LOCK_PROVED,
    "safety_chain_proved": JourneyPhase.LOCK_PROVED,
    "start_permit_present": JourneyPhase.SAFETY_CHAIN_PROVED,
    "contactor_confirm_delay_ratio": JourneyPhase.START_PERMIT,
    "brake_release_proof": JourneyPhase.BRAKE_RELEASE,
    "brake_current_ratio": JourneyPhase.BRAKE_RELEASE,
    "brake_release_delay_ratio": JourneyPhase.BRAKE_RELEASE,
    "dc_bus_min_ratio": JourneyPhase.TORQUE_BUILD,
    "dc_bus_sag_depth": JourneyPhase.TORQUE_BUILD,
    "motor_current_peak_ratio": JourneyPhase.TORQUE_BUILD,
    "current_without_motion_ratio": JourneyPhase.TORQUE_BUILD,
    "accel_deficit_ratio": JourneyPhase.ACCELERATION,
    "speed_feedback_coverage": JourneyPhase.ACCELERATION,
    "speed_feedback_dropout_ratio": JourneyPhase.ACCELERATION,
    "speed_track_error_ratio": JourneyPhase.ACCELERATION,
    "encoder_noise_ratio": JourneyPhase.ACCELERATION,
    "encoder_internal_consistency": JourneyPhase.ACCELERATION,
    "motor_current_rms_ratio": JourneyPhase.CRUISE,
    "vibration_rms_ratio": JourneyPhase.CRUISE,
    "drive_temp_rise_ratio": JourneyPhase.CRUISE,
    "cruise_current_position_slope": JourneyPhase.CRUISE,
}


@dataclass
class FeatureVector:
    """Computed features plus an explicit record of what could not be computed."""

    values: dict[str, float] = field(default_factory=dict)
    unavailable: dict[str, str] = field(default_factory=dict)

    def get(self, key: str) -> float | None:
        return self.values.get(key)

    def set(self, key: str, value: float | None, reason: str = "required channel missing") -> None:
        if value is None or (isinstance(value, float) and not np.isfinite(value)):
            self.unavailable[key] = reason
        else:
            self.values[key] = float(value)

    @property
    def usable_count(self) -> int:
        return len(self.values)

    def phase_of(self, key: str) -> JourneyPhase | None:
        return FEATURE_PHASE.get(key)


def _channel(run: ObservableRun, name: str) -> tuple[np.ndarray, np.ndarray]:
    """Timestamps and values for the frames that actually carry a channel."""
    times = np.array(
        [f.timestamp_ms for f in run.frames if name in f.signals], dtype=float
    )
    values = np.array(
        [float(f.signals[name]) for f in run.frames if name in f.signals], dtype=float
    )
    return times, values


def _derived_speed(run: ObservableRun) -> tuple[np.ndarray, np.ndarray]:
    """Speed inferred from the independent position reference."""
    times, positions = _channel(run, "position_m")
    if len(times) < 6:
        return np.array([]), np.array([])
    window = 5
    derived = np.zeros_like(positions)
    for i in range(len(positions)):
        lo = max(0, i - window)
        dt = (times[i] - times[lo]) / 1000.0
        derived[i] = (positions[i] - positions[lo]) / dt if dt > 0 else 0.0
    return times, derived


def _peak_accel(times: np.ndarray, speeds: np.ndarray, window: int = 5) -> float | None:
    if len(speeds) < window + 1:
        return None
    best = 0.0
    for i in range(window, len(speeds)):
        dt = (times[i] - times[i - window]) / 1000.0
        if dt <= 0:
            continue
        best = max(best, (speeds[i] - speeds[i - window]) / dt)
    return best


def extract_features(
    run: ObservableRun,
    compiled: CompiledJourney,
    quality: StreamQuality,
    baselines: Baselines | None = None,
) -> FeatureVector:
    """Compute the full feature vector for one run."""
    b = baselines or load_baselines()
    facts = compiled.facts
    fv = FeatureVector()

    rated_speed = facts.rated_speed_ref or b.rated_speed_mps
    motion_from = facts.torque_commanded_ms
    brake_from = facts.brake_command_ms

    def window_mask(times: np.ndarray, start: int | None) -> np.ndarray:
        if start is None:
            return np.zeros_like(times, dtype=bool)
        return times >= start

    # ------------------------------------------------------------------ #
    # Door and lock
    # ------------------------------------------------------------------ #
    fv.set("lock_proof_toggle_count", float(facts.lock_toggle_count))
    fv.set("lock_proof_achieved", 1.0 if facts.lock_proof_achieved else 0.0)
    fv.set("lock_proof_stable_ratio", facts.lock_stable_ratio)
    fv.set("door_close_attempts", float(facts.door_close_attempts))
    fv.set("door_reopen_count", float(facts.door_reopen_count))

    if quality.usable("door_current_a"):
        _, door_current = _channel(run, "door_current_a")
        fv.set(
            "door_current_peak_ratio",
            float(np.max(door_current)) / b.door_current_peak_a if len(door_current) else None,
        )
    else:
        fv.set("door_current_peak_ratio", None, "door current channel unusable")

    if facts.door_close_start_ms is not None:
        end = facts.door_closed_ms
        if end is None:
            end = compiled.segments[-1].end_ms or facts.door_close_start_ms
        fv.set("door_close_duration_ratio", (end - facts.door_close_start_ms) / b.door_close_ms)
    else:
        fv.set("door_close_duration_ratio", None, "no door close command observed")

    # ------------------------------------------------------------------ #
    # Safety chain and start permission
    # ------------------------------------------------------------------ #
    fv.set("safety_chain_toggle_count", float(facts.chain_toggle_count))
    fv.set("safety_chain_proved", 1.0 if facts.chain_proved else 0.0)
    fv.set("start_permit_present", 1.0 if facts.permit_present else 0.0)
    delay = facts.contactor_delay_ms
    fv.set(
        "contactor_confirm_delay_ratio",
        delay / b.contactor_delay_ms if delay is not None else None,
        "contactor command/confirm pair not observed",
    )

    # ------------------------------------------------------------------ #
    # Brake
    # ------------------------------------------------------------------ #
    fv.set("brake_release_proof", 1.0 if facts.brake_release_proof else 0.0)
    release_delay = facts.brake_release_delay_ms
    fv.set(
        "brake_release_delay_ratio",
        release_delay / b.brake_release_delay_ms if release_delay is not None else None,
        "brake release proof never observed",
    )

    if quality.usable("brake_current_a") and brake_from is not None:
        times, brake_current = _channel(run, "brake_current_a")
        mask = window_mask(times, brake_from)
        fv.set(
            "brake_current_ratio",
            float(np.mean(brake_current[mask])) / b.brake_current_a if mask.any() else None,
            "no frames after brake release command",
        )
    else:
        fv.set("brake_current_ratio", None, "brake current channel unusable")

    # ------------------------------------------------------------------ #
    # Power
    # ------------------------------------------------------------------ #
    if quality.usable("dc_bus_v"):
        times, bus = _channel(run, "dc_bus_v")
        mask = window_mask(times, motion_from)
        window = bus[mask] if mask.any() else bus
        fv.set("dc_bus_min_ratio", float(np.min(window)) / b.bus_v)
        # Depth of the dip relative to the channel's own resting level. A biased
        # sensor shifts the whole trace but keeps a shallow dip; a real sag does
        # the opposite. Comparing against nominal alone cannot tell them apart.
        fv.set(
            "dc_bus_sag_depth",
            float(np.percentile(window, 90) - np.min(window)) / b.bus_v,
        )
    else:
        fv.set("dc_bus_min_ratio", None, "DC bus channel unusable")
        fv.set("dc_bus_sag_depth", None, "DC bus channel unusable")

    # ------------------------------------------------------------------ #
    # Drive current and thermal
    # ------------------------------------------------------------------ #
    if quality.usable("motor_current_a") and motion_from is not None:
        times, current = _channel(run, "motor_current_a")
        mask = window_mask(times, motion_from)
        if mask.any():
            fv.set("motor_current_peak_ratio", float(np.max(current[mask])) / b.motor_current_peak_a)
            fv.set(
                "motor_current_rms_ratio",
                float(np.sqrt(np.mean(current[mask] ** 2))) / b.motor_current_rms_a,
            )
        else:
            fv.set("motor_current_peak_ratio", None, "no frames after torque command")
            fv.set("motor_current_rms_ratio", None, "no frames after torque command")
    else:
        fv.set("motor_current_peak_ratio", None, "motor current channel unusable")
        fv.set("motor_current_rms_ratio", None, "motor current channel unusable")

    if quality.usable("drive_temp_c"):
        _, temps = _channel(run, "drive_temp_c")
        fv.set(
            "drive_temp_rise_ratio",
            (float(np.max(temps)) - float(temps[0])) / b.temp_rise_c if len(temps) else None,
        )
    else:
        fv.set("drive_temp_rise_ratio", None, "drive temperature channel unusable")

    # Current drawn while the car is demonstrably not moving. Uses the
    # independent position reference so a lost encoder cannot fake it.
    dtimes, dspeed = _derived_speed(run)
    if (
        quality.usable("motor_current_a")
        and brake_from is not None
        and len(dtimes)
        and motion_from is not None
    ):
        ctimes, current = _channel(run, "motor_current_a")
        aligned = np.interp(ctimes, dtimes, dspeed) if len(dtimes) > 1 else np.zeros_like(ctimes)
        mask = window_mask(ctimes, brake_from)
        if mask.any():
            stalled = (current[mask] > 0.3 * b.motor_current_peak_a) & (np.abs(aligned[mask]) < 0.05)
            fv.set("current_without_motion_ratio", float(np.mean(stalled)))
        else:
            fv.set("current_without_motion_ratio", None, "no frames after brake release")
    else:
        fv.set("current_without_motion_ratio", None, "motor current or position reference missing")

    # ------------------------------------------------------------------ #
    # Feedback
    # ------------------------------------------------------------------ #
    motion_frames = [f for f in run.frames if motion_from is not None and f.timestamp_ms >= motion_from]
    if motion_frames:
        with_speed = [f for f in motion_frames if "speed_mps" in f.signals]
        fv.set("speed_feedback_coverage", len(with_speed) / len(motion_frames))

        if quality.usable("motor_current_a"):
            drawing = [
                f
                for f in motion_frames
                if float(f.signals.get("motor_current_a", 0.0)) > 0.3 * b.motor_current_peak_a
            ]
            missing = [f for f in drawing if "speed_mps" not in f.signals]
            fv.set(
                "speed_feedback_dropout_ratio",
                len(missing) / len(drawing) if drawing else 0.0,
            )
        else:
            fv.set("speed_feedback_dropout_ratio", None, "motor current channel unusable")

        pairs = [
            (float(f.signals["speed_ref_mps"]), float(f.signals["speed_mps"]))
            for f in motion_frames
            if "speed_ref_mps" in f.signals and "speed_mps" in f.signals
        ]
        fv.set(
            "speed_track_error_ratio",
            float(np.mean([abs(r - m) for r, m in pairs])) / rated_speed if pairs else None,
            "speed or reference channel absent through motion",
        )

        stimes = np.array([f.timestamp_ms for f in with_speed], dtype=float)
        speeds = np.array([float(f.signals["speed_mps"]) for f in with_speed])
        if len(speeds) >= 8:
            # Second difference isolates high-frequency content from the real ramp.
            noise = float(np.std(np.diff(speeds, n=2)))
            fv.set("encoder_noise_ratio", noise / b.encoder_noise)
            peak = _peak_accel(stimes, speeds)
            fv.set(
                "accel_deficit_ratio",
                max(0.0, 1.0 - peak / b.rated_accel_mps2) if peak is not None else None,
            )
        else:
            fv.set("encoder_noise_ratio", None, "too few speed samples during motion")
            fv.set("accel_deficit_ratio", None, "too few speed samples during motion")

        # Agreement between the encoder and the independent position reference.
        if len(dtimes) > 1 and len(stimes):
            reference = np.interp(stimes, dtimes, dspeed)
            moving = reference > 0.10
            if moving.any():
                disagreement = float(np.mean(np.abs(speeds[moving] - reference[moving]))) / rated_speed
                fv.set("encoder_internal_consistency", float(np.clip(1.0 - disagreement, 0.0, 1.0)))
            else:
                fv.set("encoder_internal_consistency", None, "car never demonstrably moved")
        elif motion_from is not None and not with_speed:
            # Torque commanded, no speed feedback at all: maximally inconsistent.
            fv.set("encoder_internal_consistency", 0.0)
        else:
            fv.set("encoder_internal_consistency", None, "position reference unusable")
    else:
        for key in (
            "speed_feedback_coverage",
            "speed_feedback_dropout_ratio",
            "speed_track_error_ratio",
            "encoder_noise_ratio",
            "accel_deficit_ratio",
            "encoder_internal_consistency",
        ):
            fv.set(key, None, "journey never reached a commanded-motion phase")

    # ------------------------------------------------------------------ #
    # Vibration
    # ------------------------------------------------------------------ #
    if quality.usable("vibration_rms") and motion_from is not None:
        times, vib = _channel(run, "vibration_rms")
        mask = window_mask(times, motion_from)
        fv.set(
            "vibration_rms_ratio",
            float(np.mean(vib[mask])) / b.vibration_rms if mask.any() else None,
            "no frames after torque command",
        )
    else:
        fv.set("vibration_rms_ratio", None, "vibration channel unusable")

    # ------------------------------------------------------------------ #
    # Travel-dependent resistance
    #
    # At constant commanded speed the force the drive must produce should be
    # flat: friction does not care where in the shaft the car is. A current that
    # climbs with position means resistance that grows with travel. No fault in
    # the public graph declares this feature, so it contributes only to the
    # healthy novelty model - which is precisely how an unmodelled mechanism is
    # supposed to announce itself.
    # ------------------------------------------------------------------ #
    if quality.usable("motor_current_a") and quality.usable("position_m") and motion_from is not None:
        cruise = [
            f
            for f in run.frames
            if f.timestamp_ms >= motion_from
            and "motor_current_a" in f.signals
            and "position_m" in f.signals
            and float(f.signals.get("speed_ref_mps", 0.0)) >= 0.95 * rated_speed
        ]
        if len(cruise) >= 10:
            positions = np.array([float(f.signals["position_m"]) for f in cruise])
            currents = np.array([float(f.signals["motor_current_a"]) for f in cruise])
            span = float(positions.max() - positions.min())
            if span > 0.5:
                slope = float(np.polyfit(positions, currents, 1)[0])
                fv.set("cruise_current_position_slope", slope / b.motor_current_peak_a)
            else:
                fv.set("cruise_current_position_slope", None, "car covered too little distance at speed")
        else:
            fv.set("cruise_current_position_slope", None, "journey never held its reference speed")
    else:
        fv.set("cruise_current_position_slope", None, "motor current or position reference unusable")

    # ------------------------------------------------------------------ #
    # Data integrity
    # ------------------------------------------------------------------ #
    fv.set("min_channel_integrity", quality.min_integrity)
    fv.set("comms_gap_count", float(quality.comms_gap_count))
    fv.set("stuck_channel_count", float(quality.stuck_channel_count))
    fv.set("timestamp_skew_ratio", quality.timestamp_skew_ratio)

    return fv
