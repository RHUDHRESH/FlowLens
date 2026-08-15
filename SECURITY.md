# Security

FlowLens is a **read-only** diagnostic laboratory.

## What it will not do

The API, planner, and engine have no code path that can:

* issue a motion command;
* reset or clear an alarm;
* close a contactor;
* release a brake;
* bypass, bridge, suppress, or override a safety circuit;
* authorize return to service.

Recommended tests are selected from `configs/permitted_tests.yaml` only. Safety-class `ACTUATING` entries are rejected even if they appear in a fixture whitelist. See `docs/safety_case.md` and `tests/safety/`.

## Reporting

If you find a path that could be construed as actuation, open an issue on the evaluation repository and do not demonstrate it against equipment.

## Secrets

Do not commit API keys, private PlantLens weights, or site credentials. Public demo configuration is synthetic.
