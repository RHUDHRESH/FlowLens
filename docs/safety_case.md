# Safety case

## Claim

FlowLens is advisory software. It cannot change the state of an elevator.

## Allowed

- Ingest recorded or simulated data.
- Rank hypotheses and show support, contradictions, and uncertainty.
- Recommend reviewed, whitelisted, non-actuating observations/tests.
- Generate a report for trained personnel.

## Forbidden

- Motion commands, alarm resets, contactor close, brake release.
- Bypass, bridge, jumper, suppress, or override of a safety circuit.
- Authorization of return to service.
- LLM-generated procedures.

## Controls

1. No actuation API routes (`tests/integration/test_demo_and_api.py`).
2. Planner rejects `ACTUATING` even in a fixture whitelist (`tests/safety/`).
3. Whitelist vocabulary scan for bypass/energize instructions that are not clearly prohibitions.
4. De-energized inspections require `OUT_OF_SERVICE` or `MAINTENANCE_MODE`.
5. Envelope `safety_notice` is mandatory and appears in the HTML report.
6. Model confidence cannot override safety class.

This is **not** a passenger-safety certification and does not replace KONE service tools or site procedure.
