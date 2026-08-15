# ADR 0002 — Direct conformal implementation, not MAPIE

- Status: accepted
- Date: 2026-08-15

The public demo needs an adaptive prediction set over a small discrete label beam, not a sklearn-estimator wrapper. Implementing APS directly in `abstention.build_conformal` avoids a heavy dependency and keeps the calibration artifact a single JSON threshold. MAPIE remains allowed later if set-valued regression over features is added.
