# Model card

- **System:** DiagnosticEngine (`flowlens/diagnosis/engine.py`) v0.4.0
- **Graph:** `public-demo-1` synthetic YAML
- **Evidence:** Gaussian log-likelihood ratios, fitted means/sds in `configs/generated/evidence_models.json` from simulator training seeds
- **Novelty:** robust diagonal Mahalanobis; threshold = healthy training p99
- **Conformal:** adaptive prediction set; threshold fitted on the calibration split
- **Planner:** information-gain / (time + cost + risk) over the permitted-test whitelist

## Limitations

- Calibrated only on this simulator and this public graph.
- Compound ranking can remain ambiguous by design (`HUMAN_REVIEW`).
- Unknown detection uses residual novelty, not a generative model of every possible mechanism.
- No MAPIE dependency; conformal is implemented directly (ADR 0002).
- Do not quote these probabilities as field posteriors.

## Human boundary

A trained technician must interpret the envelope. FlowLens does not return an elevator to service.
