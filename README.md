# FlowLens RCA Lab

Evidence-first elevator **fault isolation and root cause analysis**. Not a predictive-maintenance dashboard. Not a chatbot.

**Competition:** KONE Elevate'26 · PS13 Autonomous Fault Isolation and Root Cause Analysis Assistant  
**Owner:** Rhudhresh R. · **Event:** 24–25 September 2026

FlowLens reconstructs an elevator journey, finds the first causal deviation, ranks root-cause hypotheses with support **and** contradictions, abstains when evidence is insufficient, and recommends the safest **whitelisted, non-actuating** next diagnostic test.

```text
docker compose up --build
# then open http://localhost:8000
```

Without Docker (Windows / local Python 3.12):

```text
python -m pip install -e ".[dev]"
cd apps/console && npm install && npm run build && cd ../..
python -m flowlens verify
python -m flowlens serve --host 127.0.0.1 --port 8000
```

Or split-process development: `python -m flowlens serve` and `npm run dev` in `apps/console`.

## Demo in 90 seconds

1. Open the console.
2. Click **Door Lock**, then **Run**. Watch the missing `LOCK_PROVED` transition, downstream start alarms, support/contradictions, and the next permitted test.
3. Click **Unknown**. The system must **not** force a known-fault label.
4. Click **Export report**. The HTML is rendered from the same evidence envelope as the UI.

CLI equivalent:

```text
python -m flowlens demo
python -m flowlens inject  # make inject FAULT=door_lock_bounce
python -m flowlens incident-report
```

`make` targets (`setup`, `demo`, `test`, `benchmark`, `inject`, `incident-report`, `generate-scenarios`, `offline-bundle`) match the command contract. On Windows without Make, use `python -m flowlens <command>`.

## Safety boundary

FlowLens is **read-only**. It cannot reset faults, command motion, release a brake, bypass a safety circuit, or authorize return to service. Recommended tests come only from `configs/permitted_tests.yaml`.

## What the numbers mean

Every metric in `benchmarks/published_results/` is an **achieved simulated result** on a deterministic laboratory. It is not elevator field performance and it is not a safety certification. See `docs/claim_evidence_matrix.md`.

## Status (15 August 2026 screening)

| Layer | Status |
|---|---|
| Contracts, simulator, journey compiler, first-deviation localizer | Implemented |
| Evidence engine, factorial beam, novelty, conformal abstention | Implemented |
| Next-best-test planner | Implemented |
| API + judge console + HTML report | Implemented |
| Baselines smoke + golden replay + safety tests | Implemented |
| Full ablation suite / Playwright golden UI / hardware adapter | Not in this tag |

No proprietary KONE data, logos, fault-code manuals, or PlantLens production weights are in this repository.

## Evaluation-use notice

This repository is published for KONE Elevate'26 evaluation. It is **not** licensed as open source. See `NOTICE`.
