"""Channel-quality defects applied to recorded frames.

These model instrumentation and transport problems, not machine faults. They are
applied *after* the physics, because that is where they occur in a real
installation: the machine behaved one way and the recording says something else.
Telling these two apart is the entire point of the ``SENSOR_CHECK`` decision.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from flowlens.contracts.schemas import SignalFrame

DEFECT_KINDS = frozenset(
    {"dropout", "stuck", "bias", "clip", "delay", "swap", "packet_loss", "quality_drop"}
)


class UnknownDefect(ValueError):
    pass


def _window(defect: dict[str, Any], t_ms: int) -> bool:
    start = defect.get("start_ms")
    end = defect.get("end_ms")
    if start is not None and t_ms < start:
        return False
    if end is not None and t_ms > end:
        return False
    return True


def apply_defects(
    frames: list[SignalFrame], defects: list[dict[str, Any]], rng: np.random.Generator
) -> list[SignalFrame]:
    """Return a new frame list with every declared defect applied in order."""
    for defect in defects:
        kind = defect.get("kind")
        if kind not in DEFECT_KINDS:
            raise UnknownDefect(f"unsupported channel defect kind: {kind!r}")
        frames = _APPLIERS[kind](frames, defect, rng)
    return frames


def _dropout(
    frames: list[SignalFrame], defect: dict[str, Any], _rng: np.random.Generator
) -> list[SignalFrame]:
    channel = defect["channel"]
    for frame in frames:
        if _window(defect, frame.timestamp_ms):
            frame.signals.pop(channel, None)
            frame.quality.pop(channel, None)
    return frames


def _stuck(
    frames: list[SignalFrame], defect: dict[str, Any], _rng: np.random.Generator
) -> list[SignalFrame]:
    channel = defect["channel"]
    held: float | None = None
    for frame in frames:
        if not _window(defect, frame.timestamp_ms):
            continue
        if channel not in frame.signals:
            continue
        if held is None:
            held = frame.signals[channel]
        frame.signals[channel] = held
        frame.quality[channel] = min(frame.quality.get(channel, 1.0), 0.45)
    return frames


def _bias(
    frames: list[SignalFrame], defect: dict[str, Any], _rng: np.random.Generator
) -> list[SignalFrame]:
    channel = defect["channel"]
    offset = float(defect.get("offset", 0.0))
    scale = float(defect.get("scale", 1.0))
    for frame in frames:
        if _window(defect, frame.timestamp_ms) and channel in frame.signals:
            frame.signals[channel] = round(frame.signals[channel] * scale + offset, 4)
            frame.quality[channel] = min(frame.quality.get(channel, 1.0), 0.70)
    return frames


def _clip(
    frames: list[SignalFrame], defect: dict[str, Any], _rng: np.random.Generator
) -> list[SignalFrame]:
    channel = defect["channel"]
    ceiling = float(defect["max"])
    for frame in frames:
        if _window(defect, frame.timestamp_ms) and channel in frame.signals:
            if frame.signals[channel] > ceiling:
                frame.signals[channel] = ceiling
                frame.quality[channel] = min(frame.quality.get(channel, 1.0), 0.60)
    return frames


def _delay(
    frames: list[SignalFrame], defect: dict[str, Any], _rng: np.random.Generator
) -> list[SignalFrame]:
    """Shift one channel later in time, leaving other channels in place."""
    channel = defect["channel"]
    shift_ms = int(defect.get("shift_ms", 100))
    by_time = {f.timestamp_ms: f for f in frames}
    originals = {f.timestamp_ms: f.signals.get(channel) for f in frames}
    for frame in frames:
        if not _window(defect, frame.timestamp_ms):
            continue
        source_t = frame.timestamp_ms - shift_ms
        if source_t in by_time and originals.get(source_t) is not None:
            frame.signals[channel] = originals[source_t]  # type: ignore[assignment]
            frame.quality[channel] = min(frame.quality.get(channel, 1.0), 0.65)
        else:
            frame.signals.pop(channel, None)
            frame.quality.pop(channel, None)
    return frames


def _swap(
    frames: list[SignalFrame], defect: dict[str, Any], _rng: np.random.Generator
) -> list[SignalFrame]:
    a, b = defect["channel_a"], defect["channel_b"]
    for frame in frames:
        if not _window(defect, frame.timestamp_ms):
            continue
        if a in frame.signals and b in frame.signals:
            frame.signals[a], frame.signals[b] = frame.signals[b], frame.signals[a]
            frame.quality[a] = min(frame.quality.get(a, 1.0), 0.5)
            frame.quality[b] = min(frame.quality.get(b, 1.0), 0.5)
    return frames


def _packet_loss(
    frames: list[SignalFrame], defect: dict[str, Any], rng: np.random.Generator
) -> list[SignalFrame]:
    rate = float(defect.get("rate", 0.05))
    kept: list[SignalFrame] = []
    for frame in frames:
        if _window(defect, frame.timestamp_ms) and rng.random() < rate:
            continue
        kept.append(frame)
    return kept


def _quality_drop(
    frames: list[SignalFrame], defect: dict[str, Any], _rng: np.random.Generator
) -> list[SignalFrame]:
    channel = defect["channel"]
    value = float(defect.get("quality", 0.4))
    for frame in frames:
        if _window(defect, frame.timestamp_ms) and channel in frame.quality:
            frame.quality[channel] = min(frame.quality[channel], value)
    return frames


_APPLIERS = {
    "dropout": _dropout,
    "stuck": _stuck,
    "bias": _bias,
    "clip": _clip,
    "delay": _delay,
    "swap": _swap,
    "packet_loss": _packet_loss,
    "quality_drop": _quality_drop,
}
