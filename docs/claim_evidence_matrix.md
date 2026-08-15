# Claim–evidence matrix

Every numerical or behavioural claim intended for the screening deck must map to a committed artifact. Language: **achieved simulated result** unless marked otherwise.

Seed: `20260915`. Command: `python -m flowlens verify`. Date: 15 August 2026.

| Claim | Kind | Evidence |
|---|---|---|
| Healthy journey completes with no alarm and decision HEALTHY | Achieved simulated | `python -m flowlens verify` → HEALTHY; pytest `test_healthy_journey_reaches_cruise_and_door_open` |
| Door-lock bounce: first deviation in DOOR_CLOSING (retry loop), decision KNOWN_FAULT, top hypothesis door_lock_bounce at 0.999 | Achieved simulated | verify + diagnose dump; first deviation `LOCK_PROVED` never established; alarm `LOCK_PROOF_TIMEOUT` |
| Encoder dropout: first deviation ACCELERATION / SIGNAL_EVENT_INCONSISTENCY, KNOWN_FAULT, top encoder_dropout 0.978 | Achieved simulated | verify; alarm `SPEED_FEEDBACK_LOST` |
| Brake drag: first deviation TORQUE_BUILD, KNOWN_FAULT, top brake_drag 0.950, contradiction “brake release feedback is asserted” | Achieved simulated | verify; next test `review_brake_release_trace` (OBSERVATION) |
| Compound brake-drag + encoder-noise: HUMAN_REVIEW, not a forced single label | Achieved simulated | verify; leading `brake_drag` 0.567 vs compound alternative; next test `compare_encoder_channels` |
| Sensor stuck-speed: SENSOR_CHECK | Achieved simulated | verify; rule `instrumentation_fault_leads` |
| Unknown mechanical resistance: UNKNOWN_FAULT, not KNOWN_FAULT | Achieved simulated | verify; rule `observation_unexplained_by_any_candidate`; withheld from fitting |
| Same seed/config is bit-stable | Achieved simulated | `tests/unit/test_simulator.py` + `tests/golden_replay/hashes.json` |
| Ground truth never enters the engine | Achieved simulated | `tests/unit/test_contracts.py` |
| Planner cannot recommend ACTUATING tests | Achieved simulated | `tests/safety/test_safety_boundary.py` |
| Report HTML contains the same incident id and trace hash as the envelope | Achieved simulated | `tests/integration/test_demo_and_api.py` |
| First-deviation localization accuracy 1.0 on committed simulated single-fault scenarios with an expected phase | Achieved simulated | `benchmarks/published_results/smoke_summary.json` field `first_deviation_accuracy_single_fault` |
| Unknown scenario never forced into KNOWN_FAULT (`unknown_forced_into_known`: 0) | Achieved simulated | same summary |
| FlowLens label accuracy 0.708 vs alarm lookup 0.417 vs rule DAG 0.292 on 24 simulated scenarios | Achieved simulated | same summary; **not** field accuracy |
| First-deviation accuracy ≥ 95% on clean single-fault **field** data | **Target / not claimed** | Development target in BUILD_PLAN Phase 2. Not evidenced. |
| Field-proven accuracy, KONE integration, or safety certification | **Not claimed** | Out of scope |

Probabilities are softmax scores over the public demo beam. They are not calibrated field posteriors.
