"""Factorial temporal beam inference over joint fault states.

The latent state at each journey step is a *set* of active faults, not a single
label - so a compound fault is a first-class hypothesis rather than a
post-processing hack. The forward recursion is the one described in
``CONTEXT.md``::

    score_t(z) = evidence(z, phase, quality)
               + logsumexp over z' of ( score_{t-1}(z') + transition(z' -> z) )

with state-level terms - fault priors, compound penalty, first-deviation
alignment and downstream alarm coverage - applied once at the end.

Two things keep the state space small enough to be auditable and fast:

* expansion is limited to no change, one onset, or one clear per step;
* a joint state may only contain faults declared compatible in the public graph.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from flowlens.config import FaultGraph, fault_graph, thresholds
from flowlens.contracts.enums import FaultId, JourneyPhase
from flowlens.contracts.schemas import FirstDeviation
from flowlens.diagnosis.compiler import CompiledJourney
from flowlens.diagnosis.evidence import FaultEvidence

NEG_INF = float("-inf")

FaultSet = frozenset[FaultId]


def _logaddexp(a: float, b: float) -> float:
    if a == NEG_INF:
        return b
    if b == NEG_INF:
        return a
    hi, lo = (a, b) if a > b else (b, a)
    return hi + math.log1p(math.exp(lo - hi))


@dataclass
class StateResult:
    faults: FaultSet
    log_score: float
    probability: float = 0.0
    onset_phase: JourneyPhase | None = None
    first_deviation_fit: float = 0.0
    downstream_coverage: float = 0.0

    @property
    def label(self) -> str:
        return "healthy" if not self.faults else " + ".join(sorted(f.value for f in self.faults))


@dataclass
class InferenceResult:
    states: list[StateResult] = field(default_factory=list)
    posterior: dict[str, float] = field(default_factory=dict)
    steps: list[JourneyPhase | None] = field(default_factory=list)
    beam_width: int = 0

    @property
    def top(self) -> StateResult | None:
        return self.states[0] if self.states else None

    @property
    def margin(self) -> float:
        if len(self.states) < 2:
            return 1.0
        return self.states[0].probability - self.states[1].probability


class FactorialBeam:
    def __init__(self, graph: FaultGraph | None = None) -> None:
        self.graph = graph or fault_graph()
        cfg = thresholds().inference
        self.beam_width = int(cfg.get("beam_width", 12))
        self.max_active = int(cfg.get("max_active_faults", 2))
        self.onset_penalty = float(cfg.get("onset_log_penalty", -2.4))
        self.clear_penalty = float(cfg.get("clear_log_penalty", -3.0))
        self.persistence_bonus = float(cfg.get("persistence_log_bonus", 0.35))
        self.deviation_weight = float(cfg.get("first_deviation_weight", 2.2))
        self.coverage_weight = float(cfg.get("downstream_coverage_weight", 0.8))
        self.compound_penalty = float(cfg.get("compound_log_penalty", -1.6))

    # ------------------------------------------------------------------ #

    def _compatible(self, faults: FaultSet) -> bool:
        if len(faults) <= 1:
            return True
        if len(faults) > self.max_active:
            return False
        members = sorted(faults, key=lambda f: f.value)
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                if not self.graph.is_compatible(members[i], members[j]):
                    return False
        return True

    def _expansions(self, state: FaultSet) -> list[FaultSet]:
        out: list[FaultSet] = [state]
        for fault in self.graph.modelled_faults():
            if fault in state:
                out.append(state - {fault})
            else:
                candidate = state | {fault}
                if self._compatible(candidate):
                    out.append(candidate)
        return out

    def _transition(self, source: FaultSet, target: FaultSet) -> float:
        if source == target:
            return self.persistence_bonus
        onsets = target - source
        clears = source - target
        cost = 0.0
        for fault in onsets:
            prior = min(max(self.graph.faults[fault].prior, 1e-4), 0.5)
            cost += self.onset_penalty + math.log(prior / (1.0 - prior))
        cost += self.clear_penalty * len(clears)
        return cost

    # ------------------------------------------------------------------ #

    def run(
        self,
        compiled: CompiledJourney,
        evidence: dict[FaultId, FaultEvidence],
        deviation: FirstDeviation | None,
        alarms: list[str],
    ) -> InferenceResult:
        steps = self._steps(compiled)
        buckets = self._feature_buckets(evidence, steps)

        def step_evidence(state: FaultSet, phase: JourneyPhase | None) -> float:
            total = 0.0
            for feature in buckets.get(phase, ()):
                total += self._combine(state, feature, evidence)
            return total

        beam: dict[FaultSet, float] = {frozenset(): 0.0}
        onset: dict[FaultSet, JourneyPhase | None] = {frozenset(): None}

        for phase in steps:
            candidates: dict[FaultSet, float] = {}
            best_from: dict[FaultSet, tuple[float, FaultSet]] = {}
            for source, score in beam.items():
                for target in self._expansions(source):
                    total = score + self._transition(source, target) + step_evidence(target, phase)
                    candidates[target] = _logaddexp(candidates.get(target, NEG_INF), total)
                    if target not in best_from or total > best_from[target][0]:
                        best_from[target] = (total, source)

            ordered = sorted(candidates.items(), key=lambda item: -item[1])[: self.beam_width]
            beam = dict(ordered)

            new_onset: dict[FaultSet, JourneyPhase | None] = {}
            for state in beam:
                source = best_from[state][1]
                if state and state != source:
                    new_onset[state] = phase
                else:
                    new_onset[state] = onset.get(state, onset.get(source))
            onset = new_onset

        # ---------------------------------------------------------- #
        # State-level terms, applied once.
        # ---------------------------------------------------------- #
        results: list[StateResult] = []
        for state, score in beam.items():
            fit = self._deviation_fit(state, deviation)
            coverage = self._coverage(state, alarms)
            final = score + self.deviation_weight * fit + self.coverage_weight * (coverage - 0.5)
            if len(state) >= 2:
                final += self.compound_penalty
            results.append(
                StateResult(
                    faults=state,
                    log_score=final,
                    onset_phase=onset.get(state),
                    first_deviation_fit=round(fit, 4),
                    downstream_coverage=round(coverage, 4),
                )
            )

        if results:
            peak = max(r.log_score for r in results)
            partition = sum(math.exp(r.log_score - peak) for r in results)
            for result in results:
                result.probability = math.exp(result.log_score - peak) / partition

        results.sort(key=lambda r: -r.log_score)
        return InferenceResult(
            states=results,
            posterior={r.label: round(r.probability, 6) for r in results},
            steps=steps,
            beam_width=self.beam_width,
        )

    # ------------------------------------------------------------------ #

    @staticmethod
    def _steps(compiled: CompiledJourney) -> list[JourneyPhase | None]:
        """Phase occupancy order, then a final step for stream-wide evidence."""
        ordered: list[JourneyPhase | None] = []
        for segment in compiled.segments:
            if not ordered or ordered[-1] != segment.phase:
                ordered.append(segment.phase)
        ordered.append(None)
        return ordered

    @staticmethod
    def _feature_buckets(
        evidence: dict[FaultId, FaultEvidence], steps: list[JourneyPhase | None]
    ) -> dict[JourneyPhase | None, tuple[str, ...]]:
        """Group every scored feature under the step at which it is evaluated.

        Features belonging to a phase the journey never reached fall into the
        final ``None`` step, so a run that stopped early still has all of its
        evidence counted exactly once.
        """
        from flowlens.features.extract import FEATURE_PHASE

        visited = {phase for phase in steps if phase is not None}
        seen: set[str] = set()
        for record in evidence.values():
            seen |= set(record.per_feature)

        buckets: dict[JourneyPhase | None, list[str]] = {phase: [] for phase in steps}
        for feature in sorted(seen):
            phase = FEATURE_PHASE.get(feature)
            buckets.setdefault(phase if phase in visited else None, []).append(feature)
        return {phase: tuple(features) for phase, features in buckets.items()}

    @staticmethod
    def _combine(
        state: FaultSet, feature: str, evidence: dict[FaultId, FaultEvidence]
    ) -> float:
        """Contribution of one observation to one joint state.

        Support is taken as the **maximum** across the faults that predict this
        feature, not the sum: an observation explained by brake drag is not
        additional evidence just because a second fault would also have produced
        it. Contradictions are summed, so a joint state cannot bury an
        inconvenient observation by adding another member.
        """
        best_support = 0.0
        contradiction_total = 0.0
        for fault in state:
            record = evidence.get(fault)
            if record is None:
                continue
            value = record.per_feature.get(feature)
            if value is None:
                continue
            if value > 0:
                best_support = max(best_support, value)
            else:
                contradiction_total += value
        return best_support + contradiction_total

    def _deviation_fit(self, state: FaultSet, deviation: FirstDeviation | None) -> float:
        if deviation is None:
            # A clean journey is evidence for healthy and mildly against any
            # named fault that would have produced a visible deviation.
            return 0.0 if not state else -0.25
        if not state:
            # The journey demonstrably departed from its expected behaviour, so
            # "healthy" has to answer for that.
            return -1.0

        best = -1.0
        for fault in state:
            spec = self.graph.faults[fault]
            phase_match = deviation.phase in spec.deviation_phases
            type_match = deviation.type in spec.deviation_types
            if phase_match and type_match:
                best = max(best, 1.0)
            elif phase_match:
                best = max(best, 0.5)
            elif type_match:
                best = max(best, -0.25)
        return best * deviation.confidence

    def _coverage(self, state: FaultSet, alarms: list[str]) -> float:
        if not alarms:
            return 0.5
        if not state:
            return 0.0
        explained: set[str] = set()
        for fault in state:
            explained |= set(self.graph.faults[fault].downstream_alarms)
        return len(set(alarms) & explained) / len(set(alarms))
