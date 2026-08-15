"""Healthy normalization constants.

Every ratio feature is expressed against what a *healthy* journey on this asset
class looks like. Those constants are fitted from the healthy training split by
``flowlens fit`` and written to ``configs/generated/baselines.json``; the values
below are only a bootstrap so the pipeline can run before the first fit.

Keeping them in a generated file - rather than hard-coded - is what lets the
model card state honestly which numbers came from data and which were authored.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

GENERATED_DIR = Path(__file__).resolve().parent.parent.parent / "configs" / "generated"
BASELINES_PATH = GENERATED_DIR / "baselines.json"


@dataclass(frozen=True)
class Baselines:
    """Normalization constants for feature extraction."""

    source: str = "bootstrap"
    bus_v: float = 560.0
    motor_current_peak_a: float = 22.0
    motor_current_rms_a: float = 15.0
    brake_current_a: float = 1.15
    door_current_peak_a: float = 2.80
    door_close_ms: float = 1600.0
    contactor_delay_ms: float = 120.0
    brake_release_delay_ms: float = 180.0
    temp_rise_c: float = 1.0
    vibration_rms: float = 0.26
    encoder_noise: float = 0.0035
    rated_accel_mps2: float = 0.80
    rated_speed_mps: float = 1.0

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)


def load_baselines() -> Baselines:
    """Fitted baselines if they exist, otherwise the bootstrap values."""
    if BASELINES_PATH.exists():
        data = json.loads(BASELINES_PATH.read_text(encoding="utf-8"))
        known = {f for f in Baselines.__dataclass_fields__}
        return Baselines(**{k: v for k, v in data.items() if k in known})
    return Baselines()


def save_baselines(baselines: Baselines) -> Path:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    BASELINES_PATH.write_text(baselines.to_json(), encoding="utf-8")
    return BASELINES_PATH
