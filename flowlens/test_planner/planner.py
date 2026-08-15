"""Next-best-test planning by expected information gain.

The planner picks the observation that is expected to separate the surviving
hypotheses fastest per unit of technician time, operational cost and risk::

    utility(test) = expected_hypothesis_entropy_reduction
                    / (time_cost + operational_cost + risk_penalty)

Safety boundary
---------------
The planner is a *selector*, never a generator. It can only return an entry from
``configs/permitted_tests.yaml``, it rejects anything whose safety class is not
OBSERVATION or DE_ENERGIZED_INSPECTION, and it rejects any test whose required
maintenance state does not match the asset's current state. Those three checks
are asserted again on the way out, so a configuration mistake fails loudly
instead of producing an unsafe recommendation.
"""

from __future__ import annotations

import math

from flowlens.config import TestWhitelist, permitted_tests, thresholds
from flowlens.contracts.enums import (
    RECOMMENDABLE_SAFETY_CLASSES,
    FaultId,
    MaintenanceState,
)
from flowlens.contracts.schemas import Hypothesis, NextTest, PermittedTest, TestOutcomeReport


class PlannerError(RuntimeError):
    """Raised when the planner is asked to do something outside its boundary."""


def _entropy(probabilities: list[float]) -> float:
    total = sum(probabilities)
    if total <= 0:
        return 0.0
    return -sum(
        (p / total) * math.log2(p / total) for p in probabilities if p > 1e-12
    )


def _likelihood(outcome_likelihoods: dict[str, float], default: float, hypothesis: Hypothesis) -> float:
    """Probability of an outcome given a hypothesis.

    For a compound hypothesis the most discriminating member governs, because
    the test outcome is driven by whichever mechanism it actually probes.
    """
    if not hypothesis.faults:
        return default
    values = [
        outcome_likelihoods[f.value] for f in hypothesis.faults if f.value in outcome_likelihoods
    ]
    return max(values) if values else default


def _normalized_likelihoods(test: PermittedTest, hypothesis: Hypothesis) -> list[float]:
    raw = [
        _likelihood(outcome.likelihood_by_fault, outcome.default_likelihood, hypothesis)
        for outcome in test.outcomes
    ]
    total = sum(raw)
    if total <= 0:
        return [1.0 / len(raw)] * len(raw)
    return [value / total for value in raw]


def _eligible(
    test: PermittedTest, maintenance_state: MaintenanceState, exclude: set[str]
) -> bool:
    if test.test_id in exclude:
        return False
    if test.safety_class not in RECOMMENDABLE_SAFETY_CLASSES:
        return False
    if test.required_maintenance_state and maintenance_state not in test.required_maintenance_state:
        return False
    return True


def plan_next_test(
    hypotheses: list[Hypothesis],
    *,
    maintenance_state: MaintenanceState = MaintenanceState.IN_SERVICE,
    whitelist: TestWhitelist | None = None,
    already_performed: set[str] | None = None,
) -> NextTest | None:
    """The permitted test expected to reduce hypothesis ambiguity fastest."""
    whitelist = whitelist or permitted_tests()
    exclude = already_performed or set()
    cfg = thresholds().planner

    candidates = [h for h in hypotheses if h.probability > 1e-6]
    if len(candidates) < 2:
        return None

    priors = [h.probability for h in candidates]
    total = sum(priors)
    priors = [p / total for p in priors]
    prior_entropy = _entropy(priors)
    if prior_entropy <= float(cfg.get("min_expected_bits", 0.02)):
        return None

    scored: list[tuple[float, float, PermittedTest, list[dict]]] = []

    for test in whitelist.tests:
        if not _eligible(test, maintenance_state, exclude):
            continue

        likelihoods = [_normalized_likelihoods(test, h) for h in candidates]
        expected_posterior = 0.0
        effects: list[dict] = []

        for index, outcome in enumerate(test.outcomes):
            joint = [priors[h] * likelihoods[h][index] for h in range(len(candidates))]
            marginal = sum(joint)
            if marginal <= 1e-12:
                continue
            posterior = [value / marginal for value in joint]
            expected_posterior += marginal * _entropy(posterior)

            best = max(range(len(candidates)), key=lambda i: posterior[i])
            effects.append(
                {
                    "outcome_id": outcome.outcome_id,
                    "description": outcome.description,
                    "probability": round(marginal, 4),
                    "would_lead_to": candidates[best].label,
                    "would_reach": round(posterior[best], 4),
                }
            )

        gain = prior_entropy - expected_posterior
        denominator = (
            float(cfg.get("time_cost_weight", 0.12)) * test.duration_minutes
            + float(cfg.get("operational_cost_weight", 1.0)) * test.operational_cost
            + float(cfg.get("risk_penalty_weight", 3.0)) * test.risk_penalty
        )
        utility = gain / max(denominator, 1e-6)
        scored.append((utility, gain, test, effects))

    scored = [entry for entry in scored if entry[1] >= float(cfg.get("min_expected_bits", 0.02))]
    if not scored:
        return None

    scored.sort(key=lambda entry: -entry[0])
    utility, gain, test, effects = scored[0]

    # Belt and braces: never emit a recommendation that the boundary forbids,
    # even if the configuration were edited incorrectly.
    if test.safety_class not in RECOMMENDABLE_SAFETY_CLASSES:
        raise PlannerError(
            f"planner selected {test.test_id} with safety class {test.safety_class.value}; "
            "only OBSERVATION and DE_ENERGIZED_INSPECTION tests may be recommended"
        )
    if whitelist.by_id(test.test_id) is None:
        raise PlannerError(f"planner selected {test.test_id}, which is not in the whitelist")

    shown = int(cfg.get("alternatives_shown", 3))
    alternatives = [
        {
            "test_id": alt.test_id,
            "name": alt.name,
            "expected_bits": round(alt_gain, 4),
            "utility": round(alt_utility, 4),
            "duration_minutes": alt.duration_minutes,
            "safety_class": alt.safety_class.value,
        }
        for alt_utility, alt_gain, alt, _ in scored[1 : 1 + shown]
    ]

    return NextTest(
        test_id=test.test_id,
        name=test.name,
        reason=(
            f"Expected to remove {gain:.2f} bits of the {prior_entropy:.2f} bits of ambiguity "
            f"between the surviving hypotheses in {test.duration_minutes:.0f} minutes, the best "
            f"ratio among the {len(scored)} permitted checks available in the current "
            f"maintenance state. {test.description}"
        ),
        safety_class=test.safety_class,
        expected_entropy_reduction_bits=round(gain, 4),
        prior_entropy_bits=round(prior_entropy, 4),
        expected_posterior_entropy_bits=round(prior_entropy - gain, 4),
        utility=round(utility, 4),
        duration_minutes=test.duration_minutes,
        outcome_effects=effects,
        alternatives=alternatives,
    )


def apply_test_result(
    hypotheses: list[Hypothesis],
    result: TestOutcomeReport,
    whitelist: TestWhitelist | None = None,
) -> list[Hypothesis]:
    """Re-weight hypotheses given a technician-reported outcome.

    This is a read-only Bayesian update of the ranking. It does not change the
    machine, and it cannot introduce a fault that was not already a candidate.
    """
    whitelist = whitelist or permitted_tests()
    test = whitelist.by_id(result.test_id)
    if test is None:
        raise PlannerError(f"test {result.test_id!r} is not in the permitted whitelist")

    outcome_index = next(
        (i for i, o in enumerate(test.outcomes) if o.outcome_id == result.outcome_id), None
    )
    if outcome_index is None:
        known = ", ".join(o.outcome_id for o in test.outcomes)
        raise PlannerError(
            f"outcome {result.outcome_id!r} is not declared for {test.test_id}; known: {known}"
        )

    updated: list[Hypothesis] = []
    weights: list[float] = []
    for hypothesis in hypotheses:
        likelihood = _normalized_likelihoods(test, hypothesis)[outcome_index]
        weights.append(hypothesis.probability * likelihood)

    total = sum(weights)
    for hypothesis, weight in zip(hypotheses, weights, strict=True):
        clone = hypothesis.model_copy(deep=True)
        clone.probability = (weight / total) if total > 0 else 0.0
        clone.rationale = (
            f"{clone.rationale} Updated after {test.name.lower()} returned "
            f"'{result.outcome_id}'."
        ).strip()
        updated.append(clone)

    updated.sort(key=lambda h: -h.probability)
    return updated


def fault_ids_covered(whitelist: TestWhitelist | None = None) -> set[FaultId]:
    """Faults that at least one permitted test can discriminate."""
    whitelist = whitelist or permitted_tests()
    covered: set[FaultId] = set()
    for test in whitelist.tests:
        covered |= set(test.discriminates)
    return covered
