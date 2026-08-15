"""Asset profile and the reduced-order physical models behind each channel.

The models are deliberately simple: a single effective mass, a rate-limited
force-producing drive, a first-order thermal model and additive vibration terms.
They exist to produce physically *coherent* traces - current, speed, brake and
temperature all moving together in the way a technician would expect - not to be
an accurate elevator simulation. No finite-element or full digital-twin
behaviour is claimed anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AssetProfile:
    """Physical and nominal-signal constants for one simulated asset."""

    profile_id: str = "demo_profile_a"

    # -- mechanical --------------------------------------------------------- #
    effective_mass_kg: float = 1200.0
    base_friction_n: float = 400.0
    #: Peak force the drive can deliver. Brake drag and added resistance matter
    #: precisely because this limit exists.
    force_limit_n: float = 2200.0
    #: How fast the drive may ramp force during torque build.
    force_rate_n_per_s: float = 1800.0
    force_per_amp: float = 61.8
    max_brake_force_n: float = 5000.0

    # -- motion profile ----------------------------------------------------- #
    travel_m: float = 6.0
    rated_speed_mps: float = 1.0
    rated_accel_mps2: float = 0.8
    motion_confirm_mps: float = 0.15
    #: Proportional gain of the drive's velocity regulator. The drive commands
    #: whatever acceleration is needed to track its reference; a fault shows up
    #: precisely when the force needed to do that exceeds `force_limit_n`.
    speed_gain_per_s: float = 3.0
    #: Acceleration envelope the regulator may command while catching up.
    max_accel_cmd_mps2: float = 1.2

    # -- nominal signal levels ---------------------------------------------- #
    nominal_bus_v: float = 560.0
    bus_droop_v_per_amp: float = 0.55
    nominal_motor_current_a: float = 22.0
    nominal_brake_current_a: float = 1.15
    nominal_door_current_a: float = 1.40
    ambient_temp_c: float = 42.0
    base_vibration_rms: float = 0.20

    # -- thermal ------------------------------------------------------------ #
    heat_gain_c_per_s: float = 0.62
    #: Fast enough that the drive approaches a thermal equilibrium within one
    #: journey. Without that, degraded cooling would be invisible over the short
    #: timescale of a single run and the scenario could not be diagnosed at all.
    cool_rate_per_s: float = 0.200

    # -- vibration coupling ------------------------------------------------- #
    vib_speed_gain: float = 0.060
    vib_drag_gain: float = 0.180
    vib_resistance_gain: float = 0.500

    # -- door --------------------------------------------------------------- #
    door_close_ms: int = 1600
    door_open_ms: int = 1500
    door_reopen_ms: int = 900

    # -- controller timing (generic, synthetic) ----------------------------- #
    lock_latch_ms: int = 250
    safety_latch_ms: int = 200
    safety_assert_delay_ms: int = 120
    permit_assert_delay_ms: int = 150
    brake_command_delay_ms: int = 100
    brake_release_ms: int = 250
    brake_current_ramp_ms: int = 150
    feedback_loss_trip_ms: int = 1200
    #: A guard breach raises an alarm immediately but the controller keeps trying
    #: until guard * this factor, which is what makes LATE_TRANSITION observable
    #: rather than every timeout collapsing into MISSING_TRANSITION.
    guard_grace_factor: float = 1.6

    def force_to_current(self, force_n: float, bus_v: float) -> float:
        """Current magnitude needed to produce a force at the present bus voltage.

        Sign is dropped: motoring and regenerating both draw measurable current.
        """
        bus = max(bus_v, self.nominal_bus_v * 0.4)
        return (abs(force_n) / self.force_per_amp) * (self.nominal_bus_v / bus)


DEMO_PROFILE = AssetProfile()


def trapezoid_reference(
    profile: AssetProfile, distance_travelled_m: float, elapsed_s: float
) -> tuple[float, float]:
    """Speed and acceleration reference for a jerk-free trapezoidal profile.

    Returns ``(speed_ref_mps, accel_ref_mps2)``. Deceleration begins once the
    remaining distance equals the distance needed to stop at the rated rate.
    """
    remaining = max(profile.travel_m - distance_travelled_m, 0.0)
    stop_distance = (profile.rated_speed_mps**2) / (2.0 * profile.rated_accel_mps2)

    if remaining <= 1e-6:
        return 0.0, 0.0
    if remaining <= stop_distance:
        # Decelerating leg: speed that can still be stopped inside `remaining`.
        target = (2.0 * profile.rated_accel_mps2 * remaining) ** 0.5
        return min(target, profile.rated_speed_mps), -profile.rated_accel_mps2

    ramp_speed = profile.rated_accel_mps2 * elapsed_s
    if ramp_speed < profile.rated_speed_mps:
        return ramp_speed, profile.rated_accel_mps2
    return profile.rated_speed_mps, 0.0


def door_current(
    profile: AssetProfile, travel_fraction: float, friction: float, moving: bool
) -> float:
    """Door operator current for a point in the door's travel.

    Nominal profile is a breakaway peak followed by a lower running current and a
    small seating rise at the end.
    """
    if not moving:
        return 0.05 * profile.nominal_door_current_a
    x = min(max(travel_fraction, 0.0), 1.0)
    breakaway = 1.25 * (1.0 - x) ** 3
    running = 0.75
    seating = 0.55 * x**4
    return profile.nominal_door_current_a * friction * (breakaway + running + seating)


def thermal_step(
    profile: AssetProfile,
    temp_c: float,
    current_a: float,
    cooling_factor: float,
    dt_s: float,
) -> float:
    """First-order drive thermal model with degradable cooling."""
    load = (current_a / profile.nominal_motor_current_a) ** 2
    cooling = max(cooling_factor, 0.05)
    heating = profile.heat_gain_c_per_s * load
    dissipation = profile.cool_rate_per_s * cooling * (temp_c - profile.ambient_temp_c)
    return temp_c + dt_s * (heating - dissipation)


def vibration(
    profile: AssetProfile,
    speed_mps: float,
    drag_force_n: float,
    resistance_force_n: float,
) -> float:
    """Vibration RMS proxy: baseline plus speed, brake-drag and resistance terms."""
    return (
        profile.base_vibration_rms
        + profile.vib_speed_gain * abs(speed_mps) / profile.rated_speed_mps
        + profile.vib_drag_gain * (drag_force_n / 1243.0)
        + profile.vib_resistance_gain * (resistance_force_n / 2000.0)
    )
