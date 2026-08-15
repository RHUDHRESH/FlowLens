# ADR 0001 — Custom event scheduler, not SimPy

- Status: accepted
- Date: 2026-08-15

SimPy does not materially simplify a 20 ms synchronous journey loop with explicit guards. A custom state machine keeps the seed → trace map auditable and bit-stable. Revisit only if asynchronous multi-car scheduling is in scope (it is not).
