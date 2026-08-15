# ADR 0003 — HTML report with optional print-to-PDF

- Status: accepted
- Date: 2026-08-15

WeasyPrint needs native libraries and would make `docker compose up --build` fragile. The committed renderer emits a self-contained HTML file from the same `IncidentEnvelope` the console displays. Judges print to PDF from a browser. WeasyPrint remains an optional extra.
