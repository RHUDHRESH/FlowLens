"""Per-fault calibrated evidence.

Evidence strength for a fault is the Gaussian log-likelihood ratio of the
observed features under that fault versus under the healthy reference, weighted
by the hand-authored domain weight and by channel integrity::

    llr(feature) = weight * channel_quality * ( logN(x | fault) - logN(x | healthy) )

Support and contradictions are the positive and negative terms of that same sum.
Neither is written by hand for display, which is why a hypothesis can never show
support without also showing whatever argues against it.

Distributions come from ``configs/generated/evidence_models.json`` when it has
been fitted, and fall back to the hand-authored values in the public graph
otherwise. Which source was used is reported in ``EvidenceEngine.source``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from flowlens.config import FaultGraph, fault_graph, thresholds
from flowlens.contracts.enums import FaultId, JourneyPhase
from flowlens.contracts.schemas import EvidenceItem
from flowlens.diagnosis.fitting import EVIDENCE_PATH, load_generated
from flowlens.features.extract import FEATURE_PHASE, FeatureVector
from flowlens.ingestion.quality import StreamQuality

_LOG_2PI = math.log(2.0 * math.pi)

#: No single feature may contribute more than this to a fault's score. Without
#: it, one wildly out-of-range channel could swamp every other observation.
PER_FEATURE_CLIP = 4.0

#: Below this magnitude a term is neither support nor contradiction; it is just
#: uninformative and is not shown to the technician.
EVIDENCE_NOISE_FLOOR = 0.15


def _log_normal(x: float, mean: float, sd: float) -> float:
    sd = max(sd, 1e-6)
    z = (x - mean) / sd
    return -0.5 * z * z - math.log(sd) - 0.5 * _LOG_2PI


@dataclass
class FaultEvidence:
    """The complete, auditable evidence picture for one fault."""

    fault_id: FaultId
    log_lr: float = 0.0
    support: list[EvidenceItem] = field(default_factory=list)
    contradictions: list[EvidenceItem] = field(default_factory=list)
    per_phase: dict[JourneyPhase, float] = field(default_factory=dict)
    #: Contribution of each declared feature. Inference needs this - not just the
    #: per-phase totals - so that a joint state can explain an observation once
    #: instead of counting it once per member fault.
    per_feature: dict[str, float] = field(default_factory=dict)
    used_features: list[str] = field(default_factory=list)
    missing_features: list[str] = field(default_factory=list)

    @property
    def strength(self) -> float:
        """Evidence strength squashed to [0, 1], for threshold comparisons."""
        return 1.0 / (1.0 + math.exp(-self.log_lr / 4.0))


class EvidenceEngine:
    """Scores every modelled fault against one feature vector."""

    def __init__(self, graph: FaultGraph | None = None) -> None:
        self.graph = graph or fault_graph()
        generated = load_generated(EVIDENCE_PATH)
        self.source = "fitted" if generated else "hand-authored priors"
        self._healthy: dict[str, tuple[float, float]] = {}
        self._faults: dict[str, dict[str, tuple[float, float]]] = {}

        if generated:
            self._healthy = {
                key: (float(v["mean"]), float(v["sd"]))
                for key, v in generated.get("healthy", {}).items()
            }
            self._faults = {
                fault: {
                    feature: (float(v["mean"]), float(v["sd"])) for feature, v in features.items()
                }
                for fault, features in generated.get("faults", {}).items()
            }

    # ------------------------------------------------------------------ #

    def healthy_stats(self, feature: str) -> tuple[float, float]:
        if feature in self._healthy:
            return self._healthy[feature]
        spec = self.graph.features[feature]
        return spec.healthy_mean, spec.healthy_sd

    def fault_stats(self, fault: FaultId, feature: str, fallback: tuple[float, float]) -> tuple[float, float]:
        fitted = self._faults.get(fault.value, {}).get(feature)
        return fitted if fitted else fallback

    def channel_weight(self, feature: str, quality: StreamQuality) -> float:
        required = self.graph.features[feature].requires
        if not required:
            return 1.0
        return min(quality.weight(channel) for channel in required)

    # ------------------------------------------------------------------ #

    def score_fault(
        self, fault: FaultId, features: FeatureVector, quality: StreamQuality
    ) -> FaultEvidence:
        spec = self.graph.faults[fault]
        contradiction_weight = float(thresholds().inference.get("contradiction_weight", 1.15))
        out = FaultEvidence(fault_id=fault)

        for term in spec.evidence:
            value = features.get(term.feature)
            if value is None:
                out.missing_features.append(term.feature)
                continue
            channel_weight = self.channel_weight(term.feature, quality)
            if channel_weight <= 0.0:
                out.missing_features.append(term.feature)
                continue

            healthy_mean, healthy_sd = self.healthy_stats(term.feature)
            fault_mean, fault_sd = self.fault_stats(fault, term.feature, (term.mean, term.sd))

            raw = _log_normal(value, fault_mean, fault_sd) - _log_normal(
                value, healthy_mean, healthy_sd
            )
            raw = max(-PER_FEATURE_CLIP, min(PER_FEATURE_CLIP, raw))
            contribution = term.weight * channel_weight * raw
            if contribution < 0:
                contribution *= contradiction_weight

            out.log_lr += contribution
            out.per_feature[term.feature] = contribution
            out.used_features.append(term.feature)
            phase = FEATURE_PHASE.get(term.feature)
            if phase is not None:
                out.per_phase[phase] = out.per_phase.get(phase, 0.0) + contribution

            if abs(contribution) < EVIDENCE_NOISE_FLOOR:
                continue

            description = self.graph.features[term.feature].description
            item = EvidenceItem(
                key=term.feature,
                statement=self._statement(
                    description, value, contribution, fault_mean, healthy_mean, spec.label
                ),
                value=round(value, 4),
                weight=round(contribution, 4),
                direction="support" if contribution > 0 else "contradiction",
                phase=phase,
                channel=(self.graph.features[term.feature].requires or (None,))[0],
                quality=round(channel_weight, 3),
            )
            (out.support if contribution > 0 else out.contradictions).append(item)

        # Narrative caveats: observations that do not change the arithmetic but
        # that a technician must be told before acting on the hypothesis.
        for caveat in spec.caveats:
            value = features.get(caveat.feature)
            if value is None:
                continue
            triggered = (
                value >= caveat.threshold if caveat.when == "high" else value <= caveat.threshold
            )
            if triggered:
                out.contradictions.append(
                    EvidenceItem(
                        key=caveat.feature,
                        statement=caveat.statement,
                        value=round(value, 4),
                        weight=0.0,
                        direction="contradiction",
                        phase=FEATURE_PHASE.get(caveat.feature),
                    )
                )

        out.support.sort(key=lambda i: -i.weight)
        out.contradictions.sort(key=lambda i: i.weight)
        return out

    def score_all(
        self, features: FeatureVector, quality: StreamQuality
    ) -> dict[FaultId, FaultEvidence]:
        return {
            fault: self.score_fault(fault, features, quality)
            for fault in self.graph.modelled_faults()
        }

    # ------------------------------------------------------------------ #

    @staticmethod
    def _statement(
        description: str,
        value: float,
        contribution: float,
        fault_mean: float,
        healthy_mean: float,
        label: str,
    ) -> str:
        direction = "consistent with" if contribution > 0 else "argues against"
        return (
            f"{description}: observed {value:.3g} "
            f"(healthy {healthy_mean:.3g}, {label.lower()} {fault_mean:.3g}) - {direction} {label.lower()}"
        )
