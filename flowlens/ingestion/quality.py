"""Per-channel integrity assessment.

Three distinct failure modes are separated here, because they lead to different
product decisions:

* **missing**   - the channel is absent from frames. Evidence that needs it is
  simply unavailable.
* **stuck**     - the channel is present but frozen. This is the dangerous case:
  the numbers look plausible and will silently distort features.
* **degraded**  - the channel is present and moving but its reported quality is
  low. Evidence still counts, at reduced weight.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from flowlens.config import thresholds
from flowlens.contracts.schemas import ChannelQuality, ObservableRun

#: Channels expected to vary during a journey. A frozen value on one of these is
#: a defect; a frozen value on a genuinely constant channel is not.
VARYING_CHANNELS: frozenset[str] = frozenset(
    {
        "motor_current_a",
        "speed_mps",
        "accel_mps2",
        "position_m",
        "dc_bus_v",
        "drive_temp_c",
        "vibration_rms",
        "brake_current_a",
    }
)

EXPECTED_CHANNELS: tuple[str, ...] = (
    "dc_bus_v",
    "motor_current_a",
    "speed_mps",
    "speed_ref_mps",
    "accel_mps2",
    "brake_current_a",
    "door_current_a",
    "drive_temp_c",
    "vibration_rms",
    "position_m",
)

#: A frozen run shorter than this is normal (the car really is standing still).
STUCK_MIN_MS = 900


@dataclass
class StreamQuality:
    """Whole-stream transport health, independent of any single channel."""

    frame_count: int
    nominal_interval_ms: float
    comms_gap_count: int = 0
    timestamp_skew_ratio: float = 0.0
    stuck_channel_count: int = 0
    min_integrity: float = 1.0
    channels: list[ChannelQuality] = field(default_factory=list)

    def by_channel(self, name: str) -> ChannelQuality | None:
        for channel in self.channels:
            if channel.channel == name:
                return channel
        return None

    def usable(self, name: str) -> bool:
        channel = self.by_channel(name)
        return bool(channel and channel.usable)

    def weight(self, name: str) -> float:
        """Evidence weight multiplier for a channel, from its integrity."""
        q = thresholds().quality
        channel = self.by_channel(name)
        if channel is None or not channel.present:
            return 0.0
        integrity = channel.integrity
        if integrity < float(q.get("unusable_integrity", 0.55)):
            return 0.0
        degraded = float(q.get("degraded_integrity", 0.85))
        if integrity >= degraded:
            return 1.0
        floor = float(q.get("degraded_weight_floor", 0.25))
        span = max(degraded - float(q.get("unusable_integrity", 0.55)), 1e-6)
        return floor + (1.0 - floor) * (integrity - float(q.get("unusable_integrity", 0.55))) / span


def _longest_constant_run_ms(times: list[int], values: list[float]) -> int:
    if len(values) < 2:
        return 0
    best = 0
    start = 0
    for i in range(1, len(values)):
        if abs(values[i] - values[i - 1]) > 1e-9:
            best = max(best, times[i - 1] - times[start])
            start = i
    return max(best, times[-1] - times[start])


def assess_quality(run: ObservableRun) -> StreamQuality:
    """Build the per-channel integrity report for a run."""
    frames = run.frames
    frame_times = [f.timestamp_ms for f in frames]
    total = len(frames)

    if total < 2:
        return StreamQuality(frame_count=total, nominal_interval_ms=0.0, min_integrity=0.0)

    intervals = np.diff(np.asarray(frame_times, dtype=float))
    nominal = float(np.median(intervals))
    comms_gaps = int(np.count_nonzero(intervals > nominal * 1.5))
    skew = float(np.std(intervals) / nominal) if nominal > 0 else 0.0

    channels: list[ChannelQuality] = []
    stuck_count = 0

    seen = {name for frame in frames for name in frame.signals}
    for name in sorted(set(EXPECTED_CHANNELS) | seen):
        times = [f.timestamp_ms for f in frames if name in f.signals]
        values = [float(f.signals[name]) for f in frames if name in f.signals]
        qualities = [float(f.quality.get(name, 1.0)) for f in frames if name in f.signals]

        present = bool(values)
        coverage = len(values) / total if total else 0.0
        mean_quality = float(np.mean(qualities)) if qualities else 0.0

        defects: list[str] = []
        if not present:
            defects.append("missing")
        else:
            if coverage < 0.98:
                defects.append(f"partial_coverage({coverage:.0%})")
            if name in VARYING_CHANNELS:
                frozen_ms = _longest_constant_run_ms(times, values)
                if frozen_ms >= STUCK_MIN_MS:
                    defects.append(f"stuck({frozen_ms}ms)")
                    stuck_count += 1
            if mean_quality < 0.9:
                defects.append(f"reported_quality({mean_quality:.2f})")

        integrity = 0.0 if not present else mean_quality * coverage
        channels.append(
            ChannelQuality(
                channel=name,
                present=present,
                mean_quality=mean_quality,
                coverage=coverage,
                defects=defects,
                usable=integrity >= float(thresholds().quality.get("unusable_integrity", 0.55)),
            )
        )

    required = [c for c in channels if c.channel in EXPECTED_CHANNELS]
    min_integrity = min((c.integrity for c in required), default=0.0)

    return StreamQuality(
        frame_count=total,
        nominal_interval_ms=nominal,
        comms_gap_count=comms_gaps,
        timestamp_skew_ratio=skew,
        stuck_channel_count=stuck_count,
        min_integrity=min_integrity,
        channels=channels,
    )
