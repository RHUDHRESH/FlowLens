# FlowLens RCA Lab — Build Plan

Project: FlowLens RCA Lab  
Competition: KONE Elevate'26 — PS13, Autonomous Fault Isolation and Root Cause Analysis Assistant  
Owner: Rhudhresh R.  
Target event: 24–25 September 2026

Build philosophy: demonstrate cause isolation, uncertainty handling, and technician value. Do not build a generic predictive-maintenance dashboard or an LLM chatbot.

## 1. Mission

A judge can:

1. Run or replay an elevator journey.
2. Inject a known, compound, sensor, or unseen fault.
3. Observe synchronized controller events and simulated sensor signals.
4. See the first causal deviation from the expected journey.
5. Receive ranked root-cause hypotheses with support and contradictions.
6. Receive the safest permitted next diagnostic test.
7. See the system abstain when evidence is insufficient.
8. Export a versioned incident report.

## 2. Non-negotiable definition of done

See `CONTEXT.md` §20 and the screening checklist in `README.md`. Hard boundaries:

- `docker compose up --build` launches the API and console.
- Seven required scenarios run deterministically.
- Unknown is not forced into a known label.
- Next-best-test is a whitelist of non-actuating observations.
- No proprietary KONE data, logos, or PlantLens production weights.
- No component can reset, bypass, energize, or return an elevator to service.

## 3. Winning product thesis

Alarm codes show where an elevator stopped. FlowLens reconstructs **why** it stopped, isolates the first causal deviation, and chooses the safest next test needed to verify the diagnosis.

## 4. Technical stack

Backend: Python 3.12, FastAPI, Pydantic v2, Uvicorn. Simulator: custom deterministic state machine (not SimPy). DSP/ML: NumPy, SciPy, scikit-learn. Inference: typed custom factorial beam (NetworkX not on the hot path). Storage: SQLite + Parquet. Frontend: React, TypeScript, Vite, Tailwind, Recharts, React Flow. Reports: self-contained HTML (print-to-PDF). Tests: Pytest. Packaging: Docker Compose and Makefile.

Avoid Kubernetes, Kafka, LLM diagnosis, and cloud-only infrastructure.

## 5. Delivery roadmap

| Phase | Objective | Screening status (15 Aug 2026) |
|---|---|---|
| 0 | Screening package + vertical slice | This repository |
| 1 | Contracts and deterministic simulator | Done |
| 2 | Journey compiler and first-deviation localizer | Done |
| 3 | Evidence engine and temporal fault graph | Done (public synthetic graph) |
| 4 | Unknown detection and calibrated abstention | Done on demo scenarios |
| 5 | Next-best-test planner | Done |
| 6 | Judge-facing console | Done |
| 7 | Full baselines/ablations | Smoke only in this tag |
| 8 | Docs and claim traceability | Done; claims limited to simulated evidence |
| 9 | Hardware/edge adapter | Out of this tag |
| 10 | Competition hardening | Partial (CI + compose + offline bundle) |

## 6. Command contract

```
make setup
make demo
make test
make benchmark
make inject FAULT=door_lock_bounce
make inject FAULT=encoder_dropout
make inject FAULT=brake_drag
make inject FAULT=compound
make inject FAULT=sensor_fault
make inject FAULT=unknown
make incident-report
make generate-scenarios
make offline-bundle
```

Windows without Make: `python -m flowlens <subcommand>`.

## 7. Kill list

Reject: generic chat, LLM-generated diagnosis, autonomous reset/control, blockchain, cloud-scale architecture, mobile app, computer vision inside the elevator, fleet optimization, full digital-twin graphics, unsupported field-accuracy claims.

## 8. Calendar

- 15 August 2026 — screening submission (this tag)
- 16–22 August — freeze schemas, expand golden set
- 23–31 August — diagnostic core hardening
- 1–7 September — active diagnosis polish and demo recording
- 8–14 September — evidence, optional hardware
- 15–20 September — hardening; stop adding features after 20 September
- 21–23 September — freeze `v1.0.0-kone-elevate`
- 24–25 September — hackathon
