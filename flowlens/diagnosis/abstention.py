"""The abstention gate.

Uncertainty is a product state here, not a disclaimer appended to a guess. The
gate returns one of seven distinct decisions and never collapses an unsupported
case into a low-confidence named fault.

Rule order matters and is deliberate:

1. **Can we read the data at all?**       -> ``INSUFFICIENT_DATA`` / ``OUT_OF_SCOPE``
2. **Is the data itself the problem?**    -> ``SENSOR_CHECK``
3. **Is this outside anything calibrated?** -> ``UNKNOWN_FAULT``
4. **Did anything actually go wrong?**    -> ``HEALTHY``
5. **Is one explanation clearly ahead?**  -> ``KNOWN_FAULT`` else ``HUMAN_REVIEW``

Data integrity is checked *before* novelty and before any named fault, because a
frozen channel can look both novel and like a machine fault while the machine is
perfectly fine.
"""

from __future__ import annotations

from flowlens.config import thresholds
from flowlens.contracts.enums import Decision, FaultId, JourneyPhase, MaintenanceState
from flowlens.contracts.schemas import (
    AbstentionReport,
    ConformalReport,
    FirstDeviation,
    NoveltyReport,
)
from flowlens.diagnosis.compiler import CompiledJourney
from flowlens.diagnosis.evidence import FaultEvidence
from flowlens.diagnosis.inference import InferenceResult
from flowlens.features.extract import FeatureVector
from flowlens.ingestion.quality import StreamQuality

#: Faults that describe the recording rather than the machine.
INSTRUMENTATION_FAULTS: frozenset[FaultId] = frozenset(
    {FaultId.SENSOR_FAULT, FaultId.COMMS_CORRUPTION, FaultId.DOOR_POSITION_SENSOR_FAULT}
)

#: Channels a motion diagnosis cannot be asserted without.
CRITICAL_CHANNELS: tuple[str, ...] = ("motor_current_a", "speed_mps", "dc_bus_v", "position_m")

#: A runner-up this close to the leader counts as materially tied.
MATERIAL_TIE_FRACTION = 0.5

#: How many leading states count as "surviving candidates" when deciding whether
#: an unexplained observation really is unexplained.
TOP_CANDIDATES_FOR_RESIDUAL = 5


def explained_features(faults, evidence: dict[FaultId, FaultEvidence]) -> set[str]:
    """Features the given faults actually account for.

    Only *positive* contributions count. Declaring an expectation for a feature
    is not the same as explaining the observed value: a fault that expects normal
    vibration does not explain vibration at three times normal - it is
    contradicted by it. Counting declarations rather than support would let a
    poorly fitting label absorb the very observations that rule it out.
    """
    keys: set[str] = set()
    for fault in faults:
        record = evidence.get(fault)
        if record is None:
            continue
        keys |= {
            feature for feature, contribution in record.per_feature.items() if contribution > 0
        }
    return keys


def build_conformal(inference: InferenceResult, threshold: float, alpha: float) -> ConformalReport:
    """Adaptive prediction set: the smallest set of labels reaching the calibrated mass.

    Labels are taken in descending probability until their cumulative mass
    reaches the threshold calibrated on the held-out calibration split. This is
    the adaptive (APS) construction rather than a fixed per-label cutoff, because
    a fixed cutoff on a mixture containing genuinely hard scenarios degenerates
    into "include almost everything".
    """
    label_set: list[str] = []
    cumulative = 0.0
    for state in inference.states:
        label_set.append(state.label)
        cumulative += state.probability
        if cumulative >= threshold:
            break
    return ConformalReport(
        alpha=alpha,
        nonconformity_threshold=round(threshold, 4),
        label_set=label_set,
        set_size=len(label_set),
        covers_healthy="healthy" in label_set,
    )


def decide(
    *,
    inference: InferenceResult,
    features: FeatureVector,
    quality: StreamQuality,
    novelty: NoveltyReport,
    deviation: FirstDeviation | None,
    evidence: dict[FaultId, FaultEvidence],
    compiled: CompiledJourney,
    conformal: ConformalReport,
    novelty_model=None,
    maintenance_state: MaintenanceState = MaintenanceState.IN_SERVICE,
) -> AbstentionReport:
    cfg = thresholds().abstention
    top = inference.top

    # ---------------------------------------------------------------- #
    # 1. Is there enough data to say anything?
    # ---------------------------------------------------------------- #
    if features.usable_count < int(cfg.get("min_usable_features", 6)):
        return AbstentionReport(
            decision=Decision.INSUFFICIENT_DATA,
            reason=(
                f"Only {features.usable_count} usable features could be computed; "
                f"at least {int(cfg.get('min_usable_features', 6))} are required before any "
                "diagnosis is asserted."
            ),
            triggered_rule="min_usable_features",
            novelty=novelty,
            conformal=conformal,
            blocking_channels=sorted(features.unavailable),
        )

    if not compiled.reached(JourneyPhase.DOOR_CLOSING):
        return AbstentionReport(
            decision=Decision.OUT_OF_SCOPE,
            reason=(
                "The recording does not contain a recognizable elevator journey; "
                "FlowLens is calibrated on no-start and interrupted-run journeys only."
            ),
            triggered_rule="no_journey_recognized",
            novelty=novelty,
            conformal=conformal,
        )

    # ---------------------------------------------------------------- #
    # 2. Is the recording itself the problem?
    # ---------------------------------------------------------------- #
    blocking = [
        channel.channel
        for channel in quality.channels
        if channel.channel in CRITICAL_CHANNELS
        and (not channel.usable or any(d.startswith("stuck") for d in channel.defects))
    ]
    sensor_strength = max(
        (evidence[f].log_lr for f in INSTRUMENTATION_FAULTS if f in evidence), default=0.0
    )
    equipment_strength = max(
        (
            evidence[f].log_lr
            for f in evidence
            if f not in INSTRUMENTATION_FAULTS
        ),
        default=0.0,
    )
    dominance = float(cfg.get("sensor_dominance", 0.45))

    if top is not None and top.faults & INSTRUMENTATION_FAULTS:
        return AbstentionReport(
            decision=Decision.SENSOR_CHECK,
            reason=(
                "The strongest explanation is an instrumentation or data defect, not an "
                "equipment failure. Resolve the data problem before acting on any "
                "machine diagnosis derived from these channels."
            ),
            triggered_rule="instrumentation_fault_leads",
            margin=round(inference.margin, 4),
            novelty=novelty,
            conformal=conformal,
            blocking_channels=blocking,
        )

    if blocking and sensor_strength >= dominance * max(equipment_strength, 1e-6):
        return AbstentionReport(
            decision=Decision.SENSOR_CHECK,
            reason=(
                f"Channel(s) {', '.join(blocking)} are missing or frozen, and the data-defect "
                "evidence is strong enough to explain the apparent fault. An equipment "
                "diagnosis built on these channels would not be safe to assert."
            ),
            triggered_rule="critical_channel_defect",
            margin=round(inference.margin, 4),
            novelty=novelty,
            conformal=conformal,
            blocking_channels=blocking,
        )

    # ---------------------------------------------------------------- #
    # 3. Is this outside anything we calibrated on?
    # ---------------------------------------------------------------- #
    # A named fault is only credible if it fits this run about as well as that
    # same fault fits its own training runs. A leading label that fits far worse
    # than usual, on a journey that is clearly abnormal, is the signature of a
    # mechanism the graph does not contain.
    name_confidence = float(cfg.get("name_confidence", 0.75))
    if (
        novelty.is_novel
        and top is not None
        and top.faults
        and novelty_model is not None
        and top.probability < name_confidence
    ):
        # Test the residual against *every* surviving candidate, not just the
        # leader. If a second candidate accounts for what the leader misses, the
        # case is ambiguous - not unknown. Only an observation that no candidate
        # explains points outside the modelled fault set.
        candidates = {
            fault for state in inference.states[:TOP_CANDIDATES_FOR_RESIDUAL] for fault in state.faults
        }
        explained_keys = explained_features(candidates, evidence)
        reached = frozenset(segment.phase for segment in compiled.segments)
        _, worst_z, worst_unexplained = novelty_model.unexplained_score(
            features, explained_keys, reached
        )

        if worst_z > novelty_model.unexplained_threshold:
            return AbstentionReport(
                decision=Decision.UNKNOWN_FAULT,
                reason=(
                    f"The journey is clearly abnormal, no explanation reaches the "
                    f"{name_confidence:.0%} confidence required to name a fault, and an "
                    f"observation that none of the candidate explanations predicts is "
                    f"{worst_z:.1f} standard deviations from healthy (anything past "
                    f"{novelty_model.unexplained_threshold:.1f} is outside the calibrated "
                    "range). Unexplained: "
                    + ", ".join(worst_unexplained[:3])
                    + ". This pattern is outside the modelled fault set."
                ),
                triggered_rule="observation_unexplained_by_any_candidate",
                margin=round(inference.margin, 4),
                novelty=novelty,
                conformal=conformal,
            )

    # ---------------------------------------------------------------- #
    # 4. Did anything actually go wrong?
    # ---------------------------------------------------------------- #
    healthy_ceiling = float(cfg.get("healthy_novelty_ceiling", 2.0))
    if (
        top is not None
        and not top.faults
        and deviation is None
        and novelty.score <= healthy_ceiling
        and not compiled.facts.alarms
    ):
        return AbstentionReport(
            decision=Decision.HEALTHY,
            reason=(
                "The journey completed its expected phase sequence within every time "
                "guard, raised no alarm, and its features sit inside the healthy range."
            ),
            triggered_rule="clean_journey",
            margin=round(inference.margin, 4),
            novelty=novelty,
            conformal=conformal,
        )

    # ---------------------------------------------------------------- #
    # 5. Is one explanation clearly ahead?
    # ---------------------------------------------------------------- #
    if top is None:
        return AbstentionReport(
            decision=Decision.INSUFFICIENT_DATA,
            reason="Inference produced no candidate state.",
            triggered_rule="empty_beam",
            novelty=novelty,
            conformal=conformal,
        )

    min_confidence = float(cfg.get("min_confidence", 0.55))
    min_margin = float(cfg.get("min_margin", 0.12))

    # A prediction set larger than one only forces review when its members are
    # materially competitive. Calibrated coverage over a mixture containing
    # genuinely hard scenarios makes the set permissive; letting bare set size
    # drive the decision would abstain on cases that are not actually close.
    runner_up = inference.states[1].probability if len(inference.states) > 1 else 0.0
    materially_tied = conformal.set_size > 1 and runner_up >= MATERIAL_TIE_FRACTION * top.probability

    if materially_tied:
        return AbstentionReport(
            decision=Decision.HUMAN_REVIEW,
            reason=(
                f"At {(1 - conformal.alpha):.0%} calibrated coverage the evidence admits "
                f"{conformal.set_size} explanations that cannot be separated: "
                + ", ".join(conformal.label_set[:4])
                + f". The runner-up reaches {runner_up:.0%} against the leader's "
                f"{top.probability:.0%}, which is too close to call. A technician's "
                "judgement is required."
            ),
            triggered_rule="materially_tied_hypotheses",
            margin=round(inference.margin, 4),
            novelty=novelty,
            conformal=conformal,
        )

    if top.probability < min_confidence or inference.margin < min_margin:
        return AbstentionReport(
            decision=Decision.HUMAN_REVIEW,
            reason=(
                f"The leading explanation reaches only {top.probability:.0%} with a "
                f"{inference.margin:.0%} margin over the next; the thresholds for asserting "
                f"a named fault are {min_confidence:.0%} and {min_margin:.0%}."
            ),
            triggered_rule="below_confidence_or_margin",
            margin=round(inference.margin, 4),
            novelty=novelty,
            conformal=conformal,
        )

    if not top.faults:
        return AbstentionReport(
            decision=Decision.HUMAN_REVIEW,
            reason=(
                "The healthy state scores highest, but the journey deviated from its "
                "expected sequence or raised an alarm. That combination is not something "
                "FlowLens will sign off automatically."
            ),
            triggered_rule="healthy_leads_but_journey_deviated",
            margin=round(inference.margin, 4),
            novelty=novelty,
            conformal=conformal,
        )

    return AbstentionReport(
        decision=Decision.KNOWN_FAULT,
        reason=(
            f"{top.label.replace('_', ' ')} explains the first deviation, carries the "
            f"strongest supporting evidence, and reaches {top.probability:.0%} with a "
            f"{inference.margin:.0%} margin over the next explanation."
        ),
        triggered_rule="supported_named_fault",
        margin=round(inference.margin, 4),
        novelty=novelty,
        conformal=conformal,
    )
