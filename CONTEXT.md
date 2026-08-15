# FlowLens RCA Lab — Canonical Project Context

This file is the authoritative context for developers, coding agents, reviewers, and
presenters working on FlowLens. Read it before changing architecture, scope, algorithms,
UI, benchmarks, or claims.

If another document conflicts with this file, raise the conflict explicitly. Do not
silently reinterpret the product.

## 1. Project identity

* **Product name:** FlowLens RCA Lab
* **Internal origin:** Elevator-specific adaptation of PlantLens
* **Competition:** KONE Elevate'26
* **Problem statement:** PS13 — Autonomous Fault Isolation and Root Cause Analysis Assistant
* **Owner:** Rhudhresh R.
* **Primary date:** 24–25 September 2026
* **Primary user:** Trained elevator service technician or remote diagnostic expert
* **Secondary users:** Service operations lead, reliability engineer, building/facility manager

## 2. One-sentence definition

FlowLens reconstructs an elevator journey from controller events and physical signals,
identifies the first causal deviation, ranks root causes with supporting and contradictory
evidence, abstains when evidence is inadequate, and selects the safest permitted next
diagnostic test.

## 3. Why the product exists

Elevator incidents often create alarm cascades. A downstream drive or motion alarm may be
caused by an earlier door-lock, safety-chain, supply, feedback, brake, or communication
failure. Alarm lookup tables and independent classifiers tend to rank symptoms without
reconstructing the sequence that produced them.

KONE already operates predictive and connected-maintenance capabilities. Therefore, the
project must not position itself as a generic predictor. The defensible gap is transparent
isolation-to-resolution:

* Which journey transition failed first?
* Which root causes explain the entire evidence sequence?
* Which observations contradict each hypothesis?
* Is the evidence good enough to name a fault?
* What safe, approved test should the technician perform next?

## 4. Winning thesis

The project wins only if it demonstrates all five layers:

1. **Elevator specificity** — a journey/phase model, not generic machinery monitoring.
2. **Causal reasoning** — first deviation and propagation path, not correlation alone.
3. **Uncertainty discipline** — explicit unknown, sensor, and review states.
4. **Technician utility** — next-best-test and evidence report.
5. **Proof** — reproducible simulator, fault injection, baselines, ablations, tests, and
   one-command execution.

The repository is an executable evaluation laboratory with a product interface. It is not a
slide-support website.

## 5. Scope

### In scope

* Elevator no-start incidents.
* Interrupted-run incidents.
* Controller-like event and alarm sequences.
* Drive-current, DC-bus voltage, speed/encoder, brake, door, temperature, and vibration evidence.
* Door, safety-chain, contactor, supply, drive, feedback, brake, cooling, communications, and sensor causes.
* Single and limited compound faults.
* Deterministic simulation and safe PlantLens rig replay.
* Read-only diagnosis and test recommendation.
* Evidence envelope and report generation.

### Out of scope

* Automatic elevator control or recovery.
* Resetting faults.
* Bypassing door locks or safety circuits.
* Energized test execution.
* Passenger safety certification.
* Replacement of KONE service tools or engineering judgement.
* Claims of field-proven accuracy.
* Full elevator mechanical finite-element simulation.
* Full fleet dispatch, traffic control, or modernization optimization.

## 6. Safety boundary

FlowLens is strictly read-only.

**It may:**

* Ingest recorded or simulated data.
* Rank diagnostic hypotheses.
* Display support, contradictions, and uncertainty.
* Recommend only reviewed, whitelisted diagnostic observations/tests.
* Generate a report for trained personnel.

**It may not:**

* Issue motion commands.
* Reset or clear an alarm.
* Close a contactor.
* Release a brake.
* Bypass, bridge, suppress, or override a safety circuit.
* Authorize return to service.
* Generate arbitrary repair instructions through an LLM.

All demo tests must be simulated or performed on the separate safe PlantLens rig under its
approved operating procedure.

## 7. PlantLens inheritance

The PlantLens base algorithm is **PI-FSDBN-CA**: Physics-Informed Factorial Switching
Dynamic Bayesian Network with Calibrated Abstention.

**Retain:** mode-aware temporal reasoning; multi-label/factorial fault states;
physics-informed features; sensor-quality gating; robust healthy novelty detection;
calibrated evidence; conformal or equivalent set-valued abstention; top-K bounded
inference; contradiction evidence; versioned evidence envelope; human approval boundary.

**Replace:** induction-motor operating modes with elevator journey phases; motor/fan fault
ontology with elevator subsystem ontology; rotor-bar and slip-centric features with drive,
PMSM, brake, door, encoder, and event-sequence evidence; industrial process DAG terminology
with elevator journey and causal propagation terminology.

**Add:** journey compiler; first-deviation localizer; time-guard and missing-transition
evidence; next-best-test planner; elevator incident simulator and fault-injection harness;
claim-evidence traceability.

Do not expose private PlantLens graph weights, tuned thresholds, calibration corpora,
contradiction maps, or proprietary fault-injection recipes in the public repository.

## 8. Canonical elevator journey model

```
IDLE
CALL_ACCEPTED
DOOR_CLOSING
LOCK_PROVED
SAFETY_CHAIN_PROVED
START_PERMIT
BRAKE_RELEASE
TORQUE_BUILD
ACCELERATION
CRUISE
DECELERATION
LEVELING
BRAKE_SET
DOOR_OPENING
DOOR_OPEN
INCIDENT_STOP
MAINTENANCE
```

Each phase has: required entry evidence; optional corroborating evidence; expected
dwell-time range; allowed outgoing transitions; prohibited transitions; timeout behaviour;
sensors/features observable in that phase.

Example constraint:

```
DOOR_CLOSING must produce LOCK_PROVED within the configured time guard.
Motion phases are unreachable unless LOCK_PROVED, SAFETY_CHAIN_PROVED,
START_PERMIT, and BRAKE_RELEASE have the required simulated evidence.
```

The journey model is a diagnostic abstraction, not a real elevator controller.

## 9. Initial fault ontology

**Door subsystem** — door obstruction; door-lock proof absent; door-lock contact bounce;
door motor overload; door position sensor stuck or biased.

**Safety/start-permission subsystem** — safety-chain intermittency; start-permit missing;
main contactor delayed, stuck, or inconsistent; input mapping or communications fault.

**Power and drive subsystem** — AC supply sag; DC-bus undervoltage; DC-bus
overvoltage/regeneration anomaly; drive overcurrent; drive cooling degradation; temperature
sensor defect.

**Motion/feedback subsystem** — encoder dropout; encoder drift/noise; commanded-versus-measured
speed mismatch; position/leveling signal inconsistency.

**Brake/mechanical subsystem** — brake fails to release within expected time; brake drag;
unexpected mechanical resistance; load or balancing inconsistency represented as a nuisance
condition, not automatically a fault.

**Instrumentation and data subsystem** — missing channel; stuck value; bias; clipping;
timestamp skew; swapped tag; packet loss or corruption.

The public MVP must not use proprietary KONE fault codes or reproduce confidential manuals.

## 10. Required demonstration scenarios

* **A — Healthy.** Complete journey with no alarm. Expected: `HEALTHY` or no incident.
* **B — Door-lock bounce.** Door reaches closed position but lock proof is intermittent.
  Expected first deviation: unstable or missing `LOCK_PROVED`.
* **C — Encoder dropout.** Torque commanded and current rises, but speed/position feedback
  disappears or becomes inconsistent. Expected: encoder/feedback hypothesis with
  appropriate contradictory checks.
* **D — Brake drag.** Brake-release evidence appears, current rises, acceleration lower than
  expected, thermal/mechanical evidence increases. Expected: brake drag above encoder
  failure when feedback remains internally consistent.
* **E — Compound fault.** Brake drag plus noisy encoder. Expected: compound hypothesis or
  explicit ambiguity; never forced single-label confidence.
* **F — Sensor fault.** A measurement channel is stuck, biased, missing, or delayed.
  Expected: `SENSOR_CHECK` when the data defect explains the apparent fault.
* **G — Unknown.** An unmodelled resistance or event pattern withheld from training and
  calibration. Expected: `UNKNOWN_FAULT` or `HUMAN_REVIEW`.

## 11. Canonical system pipeline

```
Simulator / Replay / Read-only Adapter
                |
                v
Timestamp and Schema Validation
                |
                v
Channel Quality and Sensor Consistency
                |
                v
Journey Segmentation and Phase Reconstruction
                |
                v
First-Deviation Localization
                |
                v
Phase-Conditioned Physics/Event Features
                |
                v
Calibrated Per-Fault Evidence + Healthy Novelty
                |
                v
Factorial Temporal Beam Inference
                |
                v
Causal Path Ranking + Contradictions
                |
                v
Abstention Gate
                |
                v
Next-Best-Test Planner
                |
                v
Evidence Envelope + Console + Incident Report
```

The LLM, if ever added, may paraphrase an already-approved evidence envelope. It must not
generate or modify the diagnosis.

## 12. First-deviation logic

Deviation types: missing transition; late transition; premature transition; prohibited
transition; contradictory simultaneous states; repeated transition/retry loop;
signal-event inconsistency.

The earliest well-supported deviation receives higher causal weight than downstream alarms.
It is not automatically declared the root cause; it constrains and informs the temporal
fault graph.

## 13. Diagnostic inference

At time or event index `t`, the latent state is a vector of fault bits:

```
z_t = [door_lock, safety_chain, contactor, supply, drive, encoder,
       brake_drag, cooling, sensor_fault, communications, ...]
```

Multiple bits may be active. The observed journey phase selects phase-specific feature
baselines and transition behaviour. The bounded forward update retains only the top-K joint
states:

```
score_t(z) = evidence(z, phase, quality)
           + first_deviation_fit(z)
           + compatibility(z)
           + contradiction_penalty(z)
           + logsumexp(previous_score + temporal_transition)
```

Candidate expansion is restricted to no change, one onset/clear, or reviewed compatible
compound changes. The public demo should use a small graph and K no larger than needed for
deterministic low-latency execution.

Root-cause path ranking must consider: upstream posterior; first-deviation alignment;
expected propagation delay; downstream alarm coverage; independent-sensor corroboration;
contradictory evidence; sensor quality.

## 14. Abstention vocabulary

* `KNOWN_FAULT` — sufficiently supported named fault or compound fault.
* `HEALTHY` — no incident and evidence within support.
* `UNKNOWN_FAULT` — anomalous pattern inconsistent with calibrated known faults.
* `SENSOR_CHECK` — instrumentation/data fault must be addressed first.
* `INSUFFICIENT_DATA` — required evidence is missing.
* `HUMAN_REVIEW` — multiple hypotheses remain materially tied or ambiguous.
* `OUT_OF_SCOPE` — phase or asset configuration outside calibrated support.

Do not collapse these states into a low-confidence known fault.

## 15. Next-best-test planner

The planner chooses from `configs/permitted_tests.yaml`. It never invents a test.

Each test contains: identifier and technician-facing name; required maintenance state;
prerequisites; expected duration; operational cost; safety class; observable outcomes;
likelihood of each outcome under each hypothesis; prohibited conditions.

```
utility(test) = expected_hypothesis_entropy_reduction
                / (time_cost + operational_cost + risk_penalty)
```

The UI must explain why the test is recommended and how its possible outcomes would update
the hypothesis ranking. Example test descriptions must remain generic and non-actuating —
reviewing a recorded subcode, inspecting a connector in an approved de-energized
maintenance state, or checking consistency of already-recorded feedback channels. Do not
provide bypass procedures.

## 16. Canonical data contracts

See `flowlens/contracts/schemas.py` for the authoritative, versioned definitions of
`JourneyEvent`, `SignalFrame`, `FaultInjection`, `EvidenceItem`, `Hypothesis`,
`PermittedTest`, and `IncidentEnvelope`.

Probabilities shown in documentation are examples, not achieved results.

## 17. API surface

```
GET  /health
GET  /api/v1/scenarios
POST /api/v1/runs
GET  /api/v1/runs/{run_id}
POST /api/v1/runs/{run_id}/step
POST /api/v1/runs/{run_id}/pause
POST /api/v1/runs/{run_id}/resume
GET  /api/v1/runs/{run_id}/events
GET  /api/v1/runs/{run_id}/diagnosis
POST /api/v1/runs/{run_id}/test-results
GET  /api/v1/incidents/{incident_id}/report
WS   /api/v1/runs/{run_id}/stream
```

All externally visible schemas must be versioned and validated.

## 18. Console requirements

The console is a diagnostic story, not a fleet dashboard. It must show: current phase and
journey status; expected versus observed transition; highlighted first deviation;
event/alarm sequence; synchronized signal charts; active causal graph path; ranked
single/compound hypotheses; support and contradictions; sensor-quality warnings; abstention
state; next-best-test recommendation; version/hash details in a collapsible evidence
drawer; report export.

Avoid decorative 3D elevators, generic KPI tiles, chat-first layouts, and fake live maps.

## 19. Evaluation protocol

**Dataset partitions:** training (evidence-model fitting and healthy-density estimation);
validation (feature and hyperparameter choices); calibration (probability and abstention
thresholds only); test (locked final results).

Partition by asset configuration and complete journey/run. All windows from one journey stay
in one partition. At least one fault mechanism and one operating regime are withheld as
unknown tests.

**Baselines:** alarm lookup; static rule DAG; independent boosted classifiers; optional
simple temporal baseline.

**Required metrics:** first-deviation localization accuracy; root-cause Top-1 and Top-3
accuracy; compound exact match and macro F1; unknown-fault recall and false rejection;
probability calibration; selective risk versus coverage; false confident diagnoses per
1,000 journeys; mean tests to isolation; p95 latency and peak memory.

**Reporting language.** Always distinguish: achieved simulated result; achieved
hardware-rig result; target; assumption; proposed future field validation. Never describe
simulator performance as elevator field performance.

## 20. Engineering invariants

* Simulation ground truth never enters inference inputs.
* Same seed/config/version produce the same golden replay.
* Safety status cannot be overridden by model confidence.
* Missing critical channels reduce evidence or trigger abstention.
* A downstream alarm cannot erase an earlier supported deviation.
* Every hypothesis exposes support and contradictions.
* Every recommended test exists in the whitelist.
* Every report cites the exact evidence-envelope version and trace hash.
* The diagnosis runtime does not depend on an external LLM or internet connection.
* The offline demo does not depend on cloud services.

## 21. Repository commands

```
make setup
make demo
make test
make benchmark
make generate-scenarios
make inject FAULT=door_lock_bounce
make inject FAULT=encoder_dropout
make inject FAULT=brake_drag
make inject FAULT=compound
make inject FAULT=sensor_fault
make inject FAULT=unknown
make incident-report
make offline-bundle
```

Do not introduce an alternate primary command path without updating this file, the README,
CI, and competition instructions.

## 22. Git and release discipline

Protect `main` from experimental onsite changes. Use feature branches and pull requests.
Require tests for diagnostic logic changes. Commit generated benchmark summaries and plots,
not enormous raw datasets. Store large generated data as release assets or regenerate it
deterministically. Tag the competition release `v1.0.0-kone-elevate`. Put the release commit
hash in the final deck and report. Maintain a private configuration/research branch or
separate private repository for proprietary PlantLens material.

## 23. IP and disclosure rules

Publicly disclose only what is needed to demonstrate novelty and reproducibility.

Keep private: tuned fault-to-feature likelihood maps; production graph weights and
contradiction maps; transition/delay priors learned from proprietary data; calibration
corpora; detailed real-equipment fault-injection procedures; unpublished patent claim
language.

Public demo configuration must be synthetic, generic, and clearly labelled. Do not add a
permissive open-source license without an explicit IP decision. In the absence of a chosen
license, include a clear evaluation-use notice and obtain proper legal advice before
commercial release.

## 24. Presentation rules

Lead with technician outcome, not the algorithm acronym. Show one alarm cascade with one
upstream cause. Show the first deviation visually. Demonstrate a contradiction that prevents
the wrong diagnosis. Demonstrate one unknown fault. Demonstrate why the recommended next
test is better than a fixed checklist. Tie value to time-to-isolate, first-time-fix
potential, avoided repeat visits, avoided unnecessary part replacement, and asset-life
extension. Never claim autonomous repair or certified safety.

## 25. Current decisions

* The project is called FlowLens RCA Lab.
* PS13 is the selected problem statement.
* Initial use case is no-start and interrupted-run RCA.
* The system is read-only.
* The primary engine is an elevator adaptation of PI-FSDBN-CA.
* The unique product addition is first-deviation localization plus next-best-test planning.
* The public proof uses deterministic simulation and a sanitized graph.
* A safe PlantLens rig adapter is optional evidence, not the primary product.
* FastAPI plus React is the default stack.
* Docker Compose is the primary execution route.
* A generic chatbot is rejected.

## 26. Open decisions

Resolve these through written architecture decision records:

* Exact public-versus-private repository strategy.
* Final team members and subsystem ownership.
* Whether conformal prediction is implemented directly or through a vetted package.
* Whether the simulator uses a custom event scheduler or SimPy.
* Which report renderer is most reliable offline.
* Exact permitted-test whitelist and review owner.
* Which physical PlantLens rig scenario is safe and visually persuasive.
* What onsite-twist extension point will be kept deliberately modular.

## 27. Reference links

* KONE Elevate page: https://srmeaswari.ac.in/kone-hackathon/
* KONE Rise strategy: https://www.kone.com/global/en/newsroom/releases/2024/kone-announces-its-new-ambitious-strategy-for-2025-2030-2024-09-19.html
* KONE predictive maintenance: https://www.kone.com/global/en/service/kone-predictive-maintenance.html
* KONE drive and EcoDisc context: https://www.kone.com/global/en/newsroom/stories/igbt-supercharging-elevators.html

## 28. Instruction to future coding agents

Before writing code:

1. Read this file and `BUILD_PLAN.md` fully.
2. State which phase and exit gate the change advances.
3. Inspect existing contracts and tests.
4. Preserve the read-only safety boundary.
5. Add or update tests before declaring completion.
6. Run the narrowest relevant tests, then the golden replay suite.
7. Update documentation and claim traceability if behaviour or metrics changed.

Do not add impressive-looking features that do not improve a defined exit gate. The project
wins through causal clarity, safe uncertainty, reproducible proof, and technician usefulness.
