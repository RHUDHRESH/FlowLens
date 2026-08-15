# Fault ontology (public demo)

Generic, synthetic, no KONE fault codes.

| Subsystem | Fault ids |
|---|---|
| Door | door_obstruction, door_lock_proof_absent, door_lock_bounce, door_motor_overload, door_position_sensor_fault |
| Safety / start | safety_chain_intermittent, start_permit_missing, contactor_delay, comms_corruption |
| Power / drive | supply_sag, dc_bus_undervoltage, drive_overcurrent, drive_cooling_degradation |
| Feedback | encoder_dropout, encoder_drift, speed_mismatch |
| Brake / mechanical | brake_release_failure, brake_drag, mechanical_resistance (withheld) |
| Instrumentation | sensor_fault |

`mechanical_resistance` is withheld from fitting and calibration so UNKNOWN can be evaluated honestly.

Graph rationale lives in `configs/public_fault_graph.yaml`. Every number there is hand-authored or fitted on the simulator and carries **no field validation**.
