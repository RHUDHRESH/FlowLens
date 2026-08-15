"""Healthy novelty detection.

This answers a different question from the fault evidence models. Those ask
"which known fault best explains this?"; this asks "does this look like anything
we have ever calibrated on?". A pattern can score reasonably against some known
fault and still be far outside the healthy manifold in a direction no modelled
fault predicts - which is exactly what an unmodelled mechanism looks like.

The score is a robust diagonal Mahalanobis distance over the healthy training
distribution. The threshold is the healthy training p99, fitted rather than
guessed, so "novel" means "outside where healthy journeys actually live".
"""

from __future__ import annotations

import math

from flowlens.config import thresholds
from flowlens.contracts.schemas import NoveltyReport
from flowlens.diagnosis.fitting import NOVELTY_PATH, load_generated
from flowlens.features.extract import FeatureVector

#: Features that describe data integrity rather than machine behaviour. A
#: recording problem must not by itself read as an unknown *fault*.
INSTRUMENTATION_FEATURES: frozenset[str] = frozenset(
    {"min_channel_integrity", "comms_gap_count", "stuck_channel_count", "timestamp_skew_ratio"}
)


class NoveltyModel:
    def __init__(self) -> None:
        generated = load_generated(NOVELTY_PATH)
        self.source = "fitted" if generated else "unfitted"
        self._stats: dict[str, tuple[float, float]] = {}
        self._threshold: float | None = None
        self.known_fault_llr_p10: dict[str, float] = {}
        self._unexplained_threshold: float = 4.0
        if generated:
            self._unexplained_threshold = float(
                generated.get("unexplained_max_z_threshold", 4.0)
            )
            self._stats = {
                key: (float(v["mean"]), float(v["sd"]))
                for key, v in generated.get("features", {}).items()
            }
            if "threshold" in generated:
                self._threshold = float(generated["threshold"])
            self.known_fault_llr_p10 = {
                key: float(value)
                for key, value in generated.get("known_fault_llr_p10", {}).items()
            }

    def fits_as_well_as_usual(self, fault_value: str, log_lr: float) -> bool | None:
        """Does this label fit this run as well as it normally fits its own runs?

        ``None`` when the fault has no fitted self-distribution, in which case no
        judgement can be made and the caller must not treat the case as unknown.
        """
        floor = self.known_fault_llr_p10.get(fault_value)
        if floor is None:
            return None
        return log_lr >= floor

    @property
    def threshold(self) -> float:
        if self._threshold is not None:
            return self._threshold
        return float(thresholds().novelty.get("threshold", 3.25))

    @staticmethod
    def _in_scope(key: str, reached: frozenset | None) -> bool:
        """Is this feature meaningful for a journey that reached only these phases?

        A journey that stopped in DOOR_CLOSING has no acceleration behaviour to
        be abnormal about. Scoring it against motion features would make every
        early-stopping fault look novel, which is exactly backwards - those are
        the faults the model knows best.
        """
        if key in INSTRUMENTATION_FEATURES:
            return False
        if reached is None:
            return True
        from flowlens.features.extract import FEATURE_PHASE

        phase = FEATURE_PHASE.get(key)
        return phase is None or phase in reached

    def unexplained_score(
        self, features: FeatureVector, explained: set[str], reached: frozenset | None = None
    ) -> tuple[float, float, list[str]]:
        """Abnormality that no candidate explanation accounts for.

        Returns ``(rms, worst_z, descriptions)``. The decision uses ``worst_z``
        rather than the mean, because a single observation that is wildly
        abnormal and that nothing predicts is exactly the signature of an
        unmodelled mechanism - and averaging it against a dozen normal features
        would hide it.
        """
        deviations: list[tuple[str, float]] = []
        for key, value in features.values.items():
            if key in explained or not self._in_scope(key, reached):
                continue
            stats = self._stats.get(key)
            if stats is None:
                continue
            mean, sd = stats
            deviations.append((key, abs(value - mean) / max(sd, 1e-6)))

        if len(deviations) < 3:
            return 0.0, 0.0, []
        deviations.sort(key=lambda item: -item[1])
        rms = math.sqrt(sum(z * z for _, z in deviations) / len(deviations))
        return (
            rms,
            deviations[0][1],
            [f"{key} ({z:.1f} sigma from healthy)" for key, z in deviations[:5]],
        )

    @property
    def unexplained_threshold(self) -> float:
        """How abnormal a single unexplained observation must be to matter.

        Fitted as the healthy training p99 of the worst per-feature z-score, so
        it means "further from healthy than healthy journeys ever get".
        """
        return self._unexplained_threshold

    def score(self, features: FeatureVector, reached: frozenset | None = None) -> NoveltyReport:
        config = thresholds().novelty
        minimum = int(config.get("min_features", 8))

        deviations: list[tuple[str, float]] = []
        for key, value in features.values.items():
            if not self._in_scope(key, reached):
                continue
            stats = self._stats.get(key)
            if stats is None:
                continue
            mean, sd = stats
            deviations.append((key, abs(value - mean) / max(sd, 1e-6)))

        if len(deviations) < minimum:
            return NoveltyReport(
                score=0.0,
                threshold=self.threshold,
                is_novel=False,
                worst_features=[],
            )

        # Root-mean-square of per-feature z-scores: a diagonal Mahalanobis
        # distance that stays interpretable in "standard deviations".
        magnitude = math.sqrt(sum(z * z for _, z in deviations) / len(deviations))
        deviations.sort(key=lambda item: -item[1])

        return NoveltyReport(
            score=round(magnitude, 4),
            threshold=self.threshold,
            is_novel=magnitude > self.threshold,
            worst_features=[f"{key} ({z:.1f}σ)" for key, z in deviations[:5]],
        )
