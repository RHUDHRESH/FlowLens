"""Pipeline orchestration: an observable run in, an evidence envelope out.

Everything the console and the PDF report display is produced here and nowhere
else. If a number appears in the UI it is in the envelope; if it is in the
envelope it was computed from the run plus the versioned configuration. There is
no display-only computation anywhere downstream.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime

from flowlens.config import config_hash, fault_graph, stable_hash, thresholds
from flowlens.contracts.enums import Decision, FaultId
from flowlens.contracts.schemas import (
    ConformalReport,
    EvidenceItem,
    Hypothesis,
    IncidentEnvelope,
    ObservableRun,
)
from flowlens.diagnosis.abstention import build_conformal, decide
from flowlens.diagnosis.compiler import compile_journey
from flowlens.diagnosis.deviation import first_deviation, localize_deviations
from flowlens.diagnosis.evidence import EvidenceEngine, FaultEvidence
from flowlens.diagnosis.fitting import CONFORMAL_PATH, load_generated
from flowlens.diagnosis.inference import FactorialBeam, InferenceResult
from flowlens.diagnosis.novelty import NoveltyModel
from flowlens.features.baselines import load_baselines
from flowlens.features.extract import extract_features
from flowlens.ingestion.quality import assess_quality
from flowlens.ingestion.validate import validate_run
from flowlens.test_planner.planner import plan_next_test
from flowlens.version import component_versions

#: How many joint states are surfaced as hypotheses.
TOP_HYPOTHESES = 5


@dataclass
class DiagnosisResult:
    envelope: IncidentEnvelope
    inference: InferenceResult
    evidence: dict[FaultId, FaultEvidence]


class DiagnosticEngine:
    """Holds the fitted models so repeated diagnoses do not re-read them."""

    def __init__(self) -> None:
        self.graph = fault_graph()
        self.evidence_engine = EvidenceEngine(self.graph)
        self.novelty_model = NoveltyModel()
        self.beam = FactorialBeam(self.graph)
        self.baselines = load_baselines()
        conformal = load_generated(CONFORMAL_PATH)
        self.conformal_threshold = (
            float(conformal["nonconformity_threshold"]) if conformal else 0.5
        )
        self.conformal_alpha = (
            float(conformal["alpha"]) if conformal else float(thresholds().abstention.get("alpha", 0.10))
        )
        self.conformal_source = "fitted" if conformal else "uncalibrated default"

    # ------------------------------------------------------------------ #

    def diagnose(
        self,
        run: ObservableRun,
        *,
        incident_id: str | None = None,
        run_id: str | None = None,
        scenario_id: str | None = None,
    ) -> DiagnosisResult:
        started = time.perf_counter()

        issues = validate_run(run)
        quality = assess_quality(run)
        compiled = compile_journey(run)
        deviations = localize_deviations(run, compiled, quality)
        deviation = first_deviation(deviations)
        features = extract_features(run, compiled, quality, self.baselines)
        evidence = self.evidence_engine.score_all(features, quality)
        reached = frozenset(segment.phase for segment in compiled.segments)
        novelty = self.novelty_model.score(features, reached)
        inference = self.beam.run(compiled, evidence, deviation, compiled.facts.alarms)

        conformal = build_conformal(inference, self.conformal_threshold, self.conformal_alpha)
        abstention = decide(
            inference=inference,
            features=features,
            quality=quality,
            novelty=novelty,
            deviation=deviation,
            evidence=evidence,
            compiled=compiled,
            conformal=conformal,
            novelty_model=self.novelty_model,
            maintenance_state=run.maintenance_state,
        )

        hypotheses = self._build_hypotheses(inference, evidence, abstention.decision)
        next_test = None
        if abstention.decision != Decision.HEALTHY:
            next_test = plan_next_test(
                hypotheses, maintenance_state=run.maintenance_state
            )

        latency_ms = (time.perf_counter() - started) * 1000.0
        fatal = [issue.code for issue in issues if issue.fatal]

        envelope = IncidentEnvelope(
            incident_id=incident_id or f"incident_{run.journey_id}",
            asset_id=run.asset_id,
            journey_id=run.journey_id,
            run_id=run_id,
            scenario_id=scenario_id,
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            decision=abstention.decision,
            abstention=abstention,
            headline=self._headline(abstention.decision, hypotheses, deviation),
            journey=compiled.segments,
            terminal_phase=compiled.terminal_phase,
            first_deviation=deviation,
            deviations=deviations,
            channel_quality=quality.channels,
            features=dict(sorted(features.values.items())),
            top_hypotheses=hypotheses,
            next_test=next_test,
            alarms=list(compiled.facts.alarms),
            latency_ms=round(latency_ms, 3),
            versions={
                **component_versions(),
                "evidence_source": self.evidence_engine.source,
                "novelty_source": self.novelty_model.source,
                "conformal_source": self.conformal_source,
                **({"validation": ",".join(fatal)} if fatal else {}),
            },
            raw_trace_hash=stable_hash(
                {
                    "events": [e.model_dump(mode="json") for e in run.events],
                    "frames": [f.model_dump(mode="json") for f in run.frames],
                }
            ),
            config_hash=config_hash(),
        )
        return DiagnosisResult(envelope=envelope, inference=inference, evidence=evidence)

    # ------------------------------------------------------------------ #

    def _build_hypotheses(
        self,
        inference: InferenceResult,
        evidence: dict[FaultId, FaultEvidence],
        decision: Decision,
    ) -> list[Hypothesis]:
        out: list[Hypothesis] = []
        for state in inference.states[:TOP_HYPOTHESES]:
            support: dict[str, EvidenceItem] = {}
            contradictions: dict[str, EvidenceItem] = {}
            causal_path: list[str] = []

            for fault in sorted(state.faults, key=lambda f: f.value):
                record = evidence.get(fault)
                if record is None:
                    continue
                for item in record.support:
                    existing = support.get(item.key)
                    if existing is None or item.weight > existing.weight:
                        support[item.key] = item
                for item in record.contradictions:
                    existing = contradictions.get(item.key)
                    if existing is None or item.weight < existing.weight:
                        contradictions[item.key] = item
                causal_path.extend(self.graph.faults[fault].causal_path)

            if state.faults and not support and not contradictions:
                # Every hypothesis must be auditable; if nothing survived the
                # noise floor, say so explicitly rather than showing an empty card.
                contradictions["_no_evidence"] = EvidenceItem(
                    key="_no_evidence",
                    statement=(
                        "No feature moved far enough from the healthy range to count "
                        "either for or against this explanation."
                    ),
                    weight=0.0,
                    direction="contradiction",
                )

            out.append(
                Hypothesis(
                    faults=sorted(state.faults, key=lambda f: f.value),
                    probability=round(state.probability, 6),
                    log_score=round(state.log_score, 4),
                    support=list(support.values()),
                    contradictions=list(contradictions.values()),
                    causal_path=causal_path,
                    first_deviation_fit=state.first_deviation_fit,
                    downstream_coverage=state.downstream_coverage,
                    onset_phase=state.onset_phase,
                    rationale=self._rationale(state, decision),
                )
            )
        return out

    @staticmethod
    def _rationale(state, decision: Decision) -> str:
        if not state.faults:
            return "No fault active: the journey is explained without invoking any modelled fault."
        fit = state.first_deviation_fit
        alignment = (
            "explains the first deviation"
            if fit >= 0.75
            else "is consistent with the deviating phase"
            if fit > 0
            else "does not align with where the journey first deviated"
        )
        return (
            f"{state.label.replace('_', ' ')} {alignment} and covers "
            f"{state.downstream_coverage:.0%} of the raised alarms."
        )

    @staticmethod
    def _headline(decision: Decision, hypotheses: list[Hypothesis], deviation) -> str:
        where = (
            f" First deviation: {deviation.phase.value} ({deviation.type.value.replace('_', ' ').lower()})."
            if deviation
            else ""
        )
        match decision:
            case Decision.HEALTHY:
                return "Journey completed normally. No incident to investigate."
            case Decision.KNOWN_FAULT:
                top = hypotheses[0] if hypotheses else None
                label = top.label.replace("_", " ") if top else "unknown"
                return f"Most likely root cause: {label}.{where}"
            case Decision.UNKNOWN_FAULT:
                return f"Abnormal journey that matches no modelled fault.{where}"
            case Decision.SENSOR_CHECK:
                return f"Data defect must be resolved before any equipment diagnosis.{where}"
            case Decision.INSUFFICIENT_DATA:
                return "Not enough usable evidence to support any diagnosis."
            case Decision.HUMAN_REVIEW:
                labels = ", ".join(h.label.replace("_", " ") for h in hypotheses[:2])
                return f"Ambiguous: {labels} cannot be separated on this evidence.{where}"
            case Decision.OUT_OF_SCOPE:
                return "Recording is outside FlowLens' calibrated support."
        return "Diagnosis complete."


_ENGINE: DiagnosticEngine | None = None


def get_engine(refresh: bool = False) -> DiagnosticEngine:
    global _ENGINE
    if _ENGINE is None or refresh:
        _ENGINE = DiagnosticEngine()
    return _ENGINE


def diagnose(run: ObservableRun, **kwargs) -> IncidentEnvelope:
    return get_engine().diagnose(run, **kwargs).envelope


def diagnose_for_calibration(run: ObservableRun) -> dict[str, float]:
    """Posterior only, used by conformal calibration.

    Deliberately bypasses the abstention gate: calibrating the threshold on
    post-gate output would be circular.
    """
    result = get_engine().diagnose(run)
    return {state.label: state.probability for state in result.inference.states}


def empty_conformal() -> ConformalReport:
    return ConformalReport(alpha=0.1, nonconformity_threshold=1.0, label_set=[], set_size=0)
