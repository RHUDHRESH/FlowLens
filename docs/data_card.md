# Data card

- **Name:** FlowLens RCA Lab simulated journeys
- **Origin:** Deterministic Python state machine (`flowlens/simulator/`), seed `20260915` for demo buttons.
- **Contents:** Controller-like events and 20 ms signal frames (DC bus, motor current, speed, brake, door, temperature, vibration, position).
- **Labels:** Ground truth lives on `RunRecord` and is stripped before inference.
- **Withheld:** `unknown_mechanical_resistance` / `mechanical_resistance` never used in fitting.
- **Not included:** Any KONE field traces, passenger PII, site identifiers, or proprietary fault-code text.
- **Intended use:** Algorithm demonstration and reproducible evaluation for Elevate'26.
- **Out of scope:** Training a field-deployed model; safety certification.
- **Generation:** `python -m flowlens generate-scenarios`

Large Parquet dumps are regenerated, not stored in git.
