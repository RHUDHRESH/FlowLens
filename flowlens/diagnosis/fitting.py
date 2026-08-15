"""Fit baselines, evidence models, novelty and conformal thresholds from data.

Ground-truth labels are used *here*, during fitting - which is what supervised
fitting means - and nowhere in the inference path. The withheld mechanism is
excluded from every fitting split, so the unknown-fault result stays honest.

Everything this module produces lands in ``configs/generated/`` and is committed,
so a reviewer can regenerate it with ``flowlens fit`` and diff the result.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from flowlens.config import fault_graph
from flowlens.contracts.schemas import RunRecord
from flowlens.diagnosis.compiler import compile_journey
from flowlens.diagnosis.splits import SPLIT_SEEDS, assert_disjoint
from flowlens.features.baselines import GENERATED_DIR, Baselines, save_baselines
from flowlens.features.extract import extract_features
from flowlens.ingestion.quality import assess_quality
from flowlens.simulator.runner import simulate
from flowlens.simulator.scenarios import fittable_scenarios

EVIDENCE_PATH = GENERATED_DIR / "evidence_models.json"
NOVELTY_PATH = GENERATED_DIR / "novelty_model.json"
CONFORMAL_PATH = GENERATED_DIR / "conformal.json"

#: Standard deviations are floored so a feature that happens to be constant in
#: the training split cannot produce an infinite log-likelihood ratio.
def _floor_sd(mean: float, sd: float) -> float:
    return float(max(sd, 0.10 * max(abs(mean), 0.5), 1e-3))


def _robust(values: list[float]) -> tuple[float, float]:
    """Median and a median-absolute-deviation-derived standard deviation."""
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    if array.size == 0:
        return 0.0, 1.0
    median = float(np.median(array))
    mad = float(np.median(np.abs(array - median)))
    sd = mad * 1.4826 if mad > 0 else float(np.std(array))
    return median, _floor_sd(median, sd)


# --------------------------------------------------------------------------- #
# Raw healthy statistics (computed without baselines, to break the cycle)
# --------------------------------------------------------------------------- #


def _raw_stats(record: RunRecord) -> dict[str, float]:
    run = record.observable()
    compiled = compile_journey(run)
    facts = compiled.facts
    out: dict[str, float] = {}

    def channel(name: str) -> np.ndarray:
        return np.array(
            [float(f.signals[name]) for f in run.frames if name in f.signals], dtype=float
        )

    bus = channel("dc_bus_v")
    if bus.size:
        out["bus_v"] = float(np.median(bus))

    motion_from = facts.torque_commanded_ms
    if motion_from is not None:
        times = np.array([f.timestamp_ms for f in run.frames if "motor_current_a" in f.signals])
        current = channel("motor_current_a")
        if current.size and times.size:
            mask = times >= motion_from
            if mask.any():
                out["motor_current_peak_a"] = float(np.max(current[mask]))
                out["motor_current_rms_a"] = float(np.sqrt(np.mean(current[mask] ** 2)))

        vib_times = np.array([f.timestamp_ms for f in run.frames if "vibration_rms" in f.signals])
        vib = channel("vibration_rms")
        if vib.size and vib_times.size:
            mask = vib_times >= motion_from
            if mask.any():
                out["vibration_rms"] = float(np.mean(vib[mask]))

        speed_times = np.array([f.timestamp_ms for f in run.frames if "speed_mps" in f.signals])
        speeds = channel("speed_mps")
        if speeds.size >= 8:
            mask = speed_times >= motion_from
            if mask.sum() >= 8:
                windowed = speeds[mask]
                wtimes = speed_times[mask]
                out["encoder_noise"] = float(np.std(np.diff(windowed, n=2)))
                best = 0.0
                for i in range(5, len(windowed)):
                    dt = (wtimes[i] - wtimes[i - 5]) / 1000.0
                    if dt > 0:
                        best = max(best, (windowed[i] - windowed[i - 5]) / dt)
                if best > 0:
                    out["rated_accel_mps2"] = best

    brake_from = facts.brake_command_ms
    if brake_from is not None:
        btimes = np.array([f.timestamp_ms for f in run.frames if "brake_current_a" in f.signals])
        brake = channel("brake_current_a")
        if brake.size and btimes.size:
            mask = btimes >= brake_from
            if mask.any():
                out["brake_current_a"] = float(np.mean(brake[mask]))

    door = channel("door_current_a")
    if door.size:
        out["door_current_peak_a"] = float(np.max(door))

    if facts.door_close_start_ms is not None and facts.door_closed_ms is not None:
        out["door_close_ms"] = float(facts.door_closed_ms - facts.door_close_start_ms)
    if facts.contactor_delay_ms is not None:
        out["contactor_delay_ms"] = float(facts.contactor_delay_ms)
    if facts.brake_release_delay_ms is not None:
        out["brake_release_delay_ms"] = float(facts.brake_release_delay_ms)

    temps = channel("drive_temp_c")
    if temps.size:
        out["temp_rise_c"] = float(np.max(temps) - temps[0])
    if facts.rated_speed_ref > 0:
        out["rated_speed_mps"] = facts.rated_speed_ref

    return out


def fit_baselines(healthy_records: list[RunRecord]) -> Baselines:
    """Median healthy behaviour, used to normalize every ratio feature."""
    collected: dict[str, list[float]] = {}
    for record in healthy_records:
        for key, value in _raw_stats(record).items():
            collected.setdefault(key, []).append(value)

    defaults = Baselines()
    fitted: dict[str, float] = {}
    for field_name in Baselines.__dataclass_fields__:
        if field_name == "source":
            continue
        values = collected.get(field_name)
        if values:
            median = float(np.median(values))
            if median > 0:
                fitted[field_name] = median
                continue
        fitted[field_name] = getattr(defaults, field_name)

    return Baselines(source=f"fitted from {len(healthy_records)} healthy training runs", **fitted)


# --------------------------------------------------------------------------- #
# Evidence, novelty and conformal fitting
# --------------------------------------------------------------------------- #


@dataclass
class FitReport:
    healthy_runs: int
    fault_runs: dict[str, int]
    calibration_runs: int
    features_fitted: int
    baselines: Baselines


def _records_for_split(split: str, limit: int | None = None) -> list[RunRecord]:
    seeds = SPLIT_SEEDS[split]  # type: ignore[index]
    if limit is not None:
        seeds = seeds[:limit]
    records: list[RunRecord] = []
    for spec in fittable_scenarios():
        for seed in seeds:
            records.append(simulate(spec, seed=seed))
    return records


def fit_all(limit: int | None = None, verbose: bool = False) -> FitReport:
    """Run the full fitting pipeline and write every generated artifact."""
    assert_disjoint()
    graph = fault_graph()
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    train = _records_for_split("train", limit)
    healthy = [r for r in train if not r.ground_truth.injected_faults]
    if not healthy:
        raise RuntimeError("training split contains no healthy runs; cannot fit baselines")

    baselines = fit_baselines(healthy)
    save_baselines(baselines)
    if verbose:
        print(f"  baselines fitted from {len(healthy)} healthy runs")

    # Feature vectors for the whole training split, using the fitted baselines.
    def features_of(record: RunRecord):
        run = record.observable()
        quality = assess_quality(run)
        compiled = compile_journey(run)
        return extract_features(run, compiled, quality, baselines), quality

    scored = [(record, *features_of(record)) for record in train]
    train_features = [(record, vector.values) for record, vector, _ in scored]

    # Healthy distribution: the reference every likelihood ratio is taken against.
    healthy_values: dict[str, list[float]] = {}
    for record, values in train_features:
        if record.ground_truth.injected_faults:
            continue
        for key, value in values.items():
            healthy_values.setdefault(key, []).append(value)
    healthy_stats = {key: _robust(values) for key, values in healthy_values.items()}

    # Per-fault distributions, restricted to the features the public graph
    # declares for that fault. Weights stay hand-authored; only the
    # distributions are learned.
    fault_stats: dict[str, dict[str, list[float]]] = {}
    fault_counts: dict[str, int] = {}
    for record, values in train_features:
        for injection in record.ground_truth.injected_faults:
            fault = injection.fault_id
            if fault not in graph.faults:
                continue
            fault_counts[fault.value] = fault_counts.get(fault.value, 0) + 1
            declared = {e.feature for e in graph.faults[fault].evidence}
            bucket = fault_stats.setdefault(fault.value, {})
            for key, value in values.items():
                if key in declared:
                    bucket.setdefault(key, []).append(value)

    evidence_models = {
        "version": graph.version,
        "fitted_from": {
            "split": "train",
            "runs": len(train),
            "seeds": list(SPLIT_SEEDS["train"][: limit or len(SPLIT_SEEDS["train"])]),
        },
        "healthy": {key: {"mean": m, "sd": s} for key, (m, s) in healthy_stats.items()},
        "faults": {
            fault: {
                feature: {"mean": _robust(values)[0], "sd": _robust(values)[1]}
                for feature, values in features.items()
            }
            for fault, features in fault_stats.items()
        },
    }
    EVIDENCE_PATH.write_text(json.dumps(evidence_models, indent=2, sort_keys=True), encoding="utf-8")
    if verbose:
        print(f"  evidence models fitted for {len(fault_stats)} faults")

    # Novelty model: robust healthy statistics, plus a threshold set where
    # healthy journeys actually stop - the training p99 with a small margin -
    # rather than at a guessed constant.
    from flowlens.diagnosis.novelty import INSTRUMENTATION_FEATURES

    healthy_scores: list[float] = []
    healthy_worst: list[float] = []
    for record, values in train_features:
        if record.ground_truth.injected_faults:
            continue
        z_scores = [
            abs(value - healthy_stats[key][0]) / max(healthy_stats[key][1], 1e-6)
            for key, value in values.items()
            if key in healthy_stats and key not in INSTRUMENTATION_FEATURES
        ]
        if len(z_scores) >= 5:
            healthy_scores.append(float(np.sqrt(np.mean(np.square(z_scores)))))
            healthy_worst.append(float(max(z_scores)))

    novelty_threshold = (
        float(np.percentile(healthy_scores, 99)) * 1.20 if healthy_scores else 3.25
    )

    # How strongly does each fault score on runs where it is genuinely present?
    # This is what makes the unknown decision principled rather than a magic
    # constant: an unmodelled mechanism produces a leading label that fits far
    # worse than that label normally fits its own runs.
    from flowlens.diagnosis.evidence import EvidenceEngine

    refreshed = EvidenceEngine(graph)
    self_scores: dict[str, list[float]] = {}
    for record, vector, quality in scored:
        for injection in record.ground_truth.injected_faults:
            fault = injection.fault_id
            if fault not in graph.faults:
                continue
            result = refreshed.score_fault(fault, vector, quality)
            self_scores.setdefault(fault.value, []).append(result.log_lr)

    known_fault_llr_p10 = {
        fault: float(np.percentile(values, 10)) for fault, values in self_scores.items() if values
    }

    novelty_model = {
        "fitted_from": {"split": "train", "healthy_runs": len(healthy)},
        "threshold": novelty_threshold,
        "healthy_score_p50": float(np.median(healthy_scores)) if healthy_scores else 0.0,
        "known_fault_llr_p10": known_fault_llr_p10,
        "unexplained_max_z_threshold": (
            float(np.percentile(healthy_worst, 99)) * 1.30 if healthy_worst else 4.0
        ),
        "features": {key: {"mean": m, "sd": s} for key, (m, s) in healthy_stats.items()},
    }
    NOVELTY_PATH.write_text(json.dumps(novelty_model, indent=2, sort_keys=True), encoding="utf-8")

    return FitReport(
        healthy_runs=len(healthy),
        fault_runs=fault_counts,
        calibration_runs=0,
        features_fitted=len(healthy_stats),
        baselines=baselines,
    )


def fit_conformal(limit: int | None = None, verbose: bool = False) -> dict:
    """Calibrate the set-valued abstention threshold on the calibration split.

    The calibration split is used for nothing else - no feature selection, no
    threshold tuning, no model fitting - which is what makes the resulting
    coverage claim meaningful.
    """
    from flowlens.config import thresholds
    from flowlens.diagnosis.engine import diagnose_for_calibration

    alpha = float(thresholds().abstention.get("alpha", 0.10))
    records = _records_for_split("calibration", limit)

    # Adaptive prediction sets: for each calibration run, how much probability
    # mass must be swept up, in descending order, before the true label is
    # included? The (1 - alpha) quantile of that is the threshold.
    masses: list[float] = []
    for record in records:
        truth = record.ground_truth.fault_ids
        label = "healthy" if not truth else " + ".join(sorted(f.value for f in truth))
        posterior = diagnose_for_calibration(record.observable())

        cumulative = 0.0
        found = False
        for candidate, probability in sorted(posterior.items(), key=lambda kv: -kv[1]):
            cumulative += probability
            if candidate == label:
                found = True
                break
        masses.append(min(cumulative, 1.0) if found else 1.0)

    masses.sort()
    if masses:
        index = min(len(masses) - 1, int(np.ceil((len(masses) + 1) * (1.0 - alpha))) - 1)
        threshold = float(masses[max(index, 0)])
    else:
        threshold = 1.0

    payload = {
        "alpha": alpha,
        "nonconformity_threshold": threshold,
        "construction": "adaptive_prediction_set",
        "calibration_runs": len(records),
        "empirical_coverage_at_threshold": float(
            np.mean([m <= threshold for m in masses]) if masses else 0.0
        ),
        "fitted_from": {"split": "calibration"},
    }
    CONFORMAL_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if verbose:
        print(f"  conformal threshold {threshold:.3f} from {len(records)} calibration runs")
    return payload


def load_generated(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
