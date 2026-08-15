# Architecture

FlowLens is a single diagnostic pipeline with a product interface. The simulator is a library loaded by the API, not a third microservice.

```
Simulator / Replay
        |
        v
Timestamp and schema validation
        |
        v
Channel quality and sensor consistency
        |
        v
Journey segmentation and phase reconstruction
        |
        v
First-deviation localization
        |
        v
Phase-conditioned physics/event features
        |
        v
Calibrated per-fault evidence + healthy novelty
        |
        v
Factorial temporal beam inference
        |
        v
Causal path ranking + contradictions
        |
        v
Abstention gate
        |
        v
Next-best-test planner
        |
        v
Evidence envelope + console + incident report
```

## Runtime

- `flowlens/` — contracts, simulator, ingestion, features, diagnosis, planner, reporting.
- `apps/api` — FastAPI. Playback control is not elevator control.
- `apps/console` — React diagnostic console. Every number is copied from the envelope.
- `configs/` — versioned public YAML. Generated JSON under `configs/generated/` is fitted from the simulator, not from field data.

## Isolation

`RunRecord.ground_truth` never enters `ObservableRun`. `DiagnosticEngine.diagnose` accepts only the observable stream.

## Transport

Minimum API: `/health`, `/api/v1/scenarios`, run create/step/pause/resume/events/diagnosis, incident report, WebSocket `/api/v1/runs/{id}/stream`. Schemas are Pydantic v2 and versioned (`schema_version` 1.0.0).
