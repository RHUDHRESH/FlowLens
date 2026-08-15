# Algorithm

Public demo of an elevator adaptation of PI-FSDBN-CA: physics-informed factorial switching dynamics with calibrated abstention. Production PlantLens weights are **not** in this repository.

## 1. Journey reconstruction

Normalize controller-like events, occupy phases when entry evidence is present, and compare against `configs/journey_phases.yaml`. Motion phases are unreachable in the simulator without lock proof, safety chain, start permit, and brake release.

## 2. First deviation

Deviation types: missing, late, premature, prohibited, contradictory, retry loop, signal-event inconsistency. The earliest well-supported deviation constrains ranking. It is **not** automatically the root cause.

## 3. Evidence (Gaussian LLR)

For each modelled fault and declared feature:

```
llr(feature) = weight * channel_quality * ( log N(x | fault) - log N(x | healthy) )
```

Positive terms are support; negative terms are contradictions. Neither list is authored for display. Per-feature contribution is clipped at ±4.0.

## 4. Factorial temporal beam

Latent state `z` is a set of fault bits (compound faults are first-class). Forward recursion:

```
score_t(z) = evidence(z, phase, quality)
           + logsumexp_{z'} ( score_{t-1}(z') + transition(z' → z) )
```

Expansion: persist, one onset, or one clear. Incompatible compounds are pruned. Support across members of a joint state is the **max** (explaining-away); contradictions are **summed**.

State-level terms applied once: first-deviation alignment, downstream alarm coverage, compound penalty. Softmax over the beam yields probabilities.

## 5. Novelty

Phase-conditioned robust Mahalanobis distance on healthy training features. Instrumentation features do not count as an unknown *machine* fault. Unexplained residual z-scores test whether any surviving candidate actually accounts for the worst observation.

## 6. Conformal / abstention

Adaptive prediction set: accumulate labels until calibrated mass is reached. The gate then emits exactly one of:

`HEALTHY | KNOWN_FAULT | UNKNOWN_FAULT | SENSOR_CHECK | INSUFFICIENT_DATA | HUMAN_REVIEW | OUT_OF_SCOPE`

Unsupported cases are not collapsed into a low-confidence named fault.

## 7. Next-best-test

```
utility(test) = E[hypothesis entropy reduction] / (time + operational_cost + risk)
```

Selector only: the test must exist in `configs/permitted_tests.yaml` and must be `OBSERVATION` or `DE_ENERGIZED_INSPECTION`.
