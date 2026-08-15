"""FlowLens command line interface.

Every ``make`` target delegates here, so the developer interface behaves
identically on Windows, macOS and Linux whether or not ``make`` is installed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _print_scenarios(args: argparse.Namespace) -> int:
    from flowlens.simulator.scenarios import DEMO_BUTTONS, list_scenarios

    buttons = {scenario_id: label for label, scenario_id in DEMO_BUTTONS}
    print(f"{'scenario':40s} {'family':16s} {'demo button':16s} expected decision")
    print("-" * 100)
    for spec in list_scenarios():
        print(
            f"{spec.scenario_id:40s} {spec.family:16s} "
            f"{buttons.get(spec.scenario_id, '-'):16s} "
            f"{spec.expected_decision.value if spec.expected_decision else '(ambiguous by design)'}"
        )
    return 0


def _simulate(args: argparse.Namespace) -> int:
    from flowlens.simulator.runner import simulate_scenario

    record = simulate_scenario(args.scenario, seed=args.seed)
    if args.out:
        Path(args.out).write_text(record.model_dump_json(indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(
            f"{record.run_id}: {len(record.events)} events, {len(record.frames)} frames, "
            f"config {record.config_hash[:19]}"
        )
    return 0


def _fit(args: argparse.Namespace) -> int:
    from flowlens.diagnosis.engine import get_engine
    from flowlens.diagnosis.fitting import fit_all, fit_conformal

    print("Fitting baselines, evidence models and novelty model from the training split...")
    report = fit_all(limit=args.limit, verbose=True)
    print(f"  {report.features_fitted} features fitted over {report.healthy_runs} healthy runs")
    print(f"  fault coverage: {len(report.fault_runs)} modelled faults")

    get_engine(refresh=True)
    print("Calibrating conformal threshold on the calibration split...")
    fit_conformal(limit=args.limit, verbose=True)
    get_engine(refresh=True)
    print("Done. Generated artifacts are in configs/generated/.")
    return 0


def _features(args: argparse.Namespace) -> int:
    from flowlens.diagnosis.compiler import compile_journey
    from flowlens.features.baselines import load_baselines
    from flowlens.features.extract import extract_features
    from flowlens.ingestion.quality import assess_quality
    from flowlens.simulator.runner import simulate_scenario

    record = simulate_scenario(args.scenario, seed=args.seed)
    run = record.observable()
    quality = assess_quality(run)
    compiled = compile_journey(run)
    features = extract_features(run, compiled, quality, load_baselines())

    print(f"# {args.scenario} (seed {args.seed})")
    for key, value in sorted(features.values.items()):
        print(f"  {key:34s} {value: .4f}")
    for key, reason in sorted(features.unavailable.items()):
        print(f"  {key:34s} unavailable - {reason}")
    return 0


def _diagnose(args: argparse.Namespace) -> int:
    from flowlens.diagnosis.engine import get_engine
    from flowlens.simulator.runner import simulate_scenario

    record = simulate_scenario(args.scenario, seed=args.seed)
    envelope = get_engine().diagnose(
        record.observable(), run_id=record.run_id, scenario_id=record.scenario_id
    ).envelope

    if args.json:
        print(envelope.model_dump_json(indent=2))
        return 0

    _render_envelope(envelope, record)
    return 0


def _render_envelope(envelope, record=None) -> None:
    print("=" * 92)
    print(f"  {envelope.decision.value}  -  {envelope.headline}")
    print("=" * 92)
    if record is not None:
        truth = record.ground_truth
        labels = ", ".join(sorted(f.fault_id.value for f in truth.injected_faults)) or "none"
        print(f"  ground truth (not seen by the engine): {labels}")
    print(f"  reason: {envelope.abstention.reason}")
    print(f"  rule:   {envelope.abstention.triggered_rule}")

    if envelope.first_deviation:
        deviation = envelope.first_deviation
        print("\n  FIRST DEVIATION")
        print(f"    {deviation.phase.value} / {deviation.type.value} at {deviation.timestamp_ms} ms")
        print(f"    {deviation.statement}")
        if deviation.affected_domains:
            print(f"    candidate domains: {', '.join(deviation.affected_domains)}")

    print("\n  HYPOTHESES")
    for index, hypothesis in enumerate(envelope.top_hypotheses, start=1):
        print(f"    {index}. {hypothesis.label:44s} p={hypothesis.probability:.3f}")
        for item in hypothesis.support[:3]:
            print(f"         + {item.statement}")
        for item in hypothesis.contradictions[:3]:
            print(f"         - {item.statement}")

    if envelope.abstention.novelty:
        novelty = envelope.abstention.novelty
        print(
            f"\n  NOVELTY  score={novelty.score:.2f} threshold={novelty.threshold:.2f} "
            f"novel={novelty.is_novel}"
        )
        if novelty.worst_features:
            print(f"    most abnormal: {', '.join(novelty.worst_features[:4])}")

    if envelope.abstention.conformal:
        conformal = envelope.abstention.conformal
        print(
            f"  CONFORMAL  {(1 - conformal.alpha):.0%} coverage set "
            f"({conformal.set_size}): {', '.join(conformal.label_set) or 'empty'}"
        )

    if envelope.next_test:
        test = envelope.next_test
        print("\n  NEXT BEST TEST")
        print(f"    {test.name}  [{test.safety_class.value}, {test.duration_minutes:.0f} min]")
        print(
            f"    expected information gain {test.expected_entropy_reduction_bits:.3f} bits "
            f"of {test.prior_entropy_bits:.3f}"
        )
        for effect in test.outcome_effects:
            print(
                f"      if '{effect['outcome_id']}' (p={effect['probability']:.2f}) -> "
                f"{effect['would_lead_to']} at {effect['would_reach']:.0%}"
            )

    degraded = [c for c in envelope.channel_quality if c.defects]
    if degraded:
        print("\n  CHANNEL QUALITY")
        for channel in degraded:
            print(f"    {channel.channel:18s} {', '.join(channel.defects)}")

    print(f"\n  alarms: {', '.join(envelope.alarms) or 'none'}")
    print(f"  latency: {envelope.latency_ms:.1f} ms   trace {envelope.raw_trace_hash[:23]}")


def _demo(args: argparse.Namespace) -> int:
    from flowlens.diagnosis.engine import get_engine
    from flowlens.simulator.runner import simulate_scenario
    from flowlens.simulator.scenarios import DEMO_BUTTONS

    engine = get_engine()
    for label, scenario_id in DEMO_BUTTONS:
        record = simulate_scenario(scenario_id, seed=args.seed)
        envelope = engine.diagnose(
            record.observable(), run_id=record.run_id, scenario_id=scenario_id
        ).envelope
        print(f"\n\n########  {label}  ########")
        _render_envelope(envelope, record)
    return 0


def _benchmark(args: argparse.Namespace) -> int:
    from benchmarks.run_benchmark import main as run_benchmark

    return run_benchmark(
        limit=args.limit,
        out_dir=Path(args.out or REPO_ROOT / "benchmarks" / "published_results"),
    )


def _report(args: argparse.Namespace) -> int:
    from flowlens.diagnosis.engine import get_engine
    from flowlens.reporting.render import render_report
    from flowlens.simulator.runner import simulate_scenario

    record = simulate_scenario(args.scenario, seed=args.seed)
    envelope = get_engine().diagnose(
        record.observable(), run_id=record.run_id, scenario_id=record.scenario_id
    ).envelope
    out = Path(args.out or REPO_ROOT / "artifacts" / f"incident_report_{args.scenario}.html")
    path = render_report(envelope, out)
    print(f"wrote {path}")
    return 0


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("apps.api.main:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def _generate(args: argparse.Namespace) -> int:
    from flowlens.dataset import generate_scenarios

    out = Path(args.out) if args.out else REPO_ROOT / "artifacts" / "datasets"
    hashes = generate_scenarios(seed=args.seed, out_dir=out, write_golden=not args.skip_golden)
    print(f"wrote {len(hashes)} scenarios to {out}")
    return 0


def _offline_bundle(args: argparse.Namespace) -> int:
    import shutil
    import zipfile

    from flowlens.diagnosis.engine import get_engine
    from flowlens.reporting.render import render_report
    from flowlens.simulator.runner import simulate_scenario
    from flowlens.simulator.scenarios import DEMO_BUTTONS

    dest = Path(args.out or REPO_ROOT / "artifacts" / "offline-bundle")
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for name in ("README.md", "CONTEXT.md", "BUILD_PLAN.md", "SECURITY.md", "NOTICE"):
        src = REPO_ROOT / name
        if src.exists():
            shutil.copy2(src, dest / name)
    docs = REPO_ROOT / "docs"
    if docs.exists():
        shutil.copytree(docs, dest / "docs")
    shutil.copytree(REPO_ROOT / "configs", dest / "configs")

    engine = get_engine()
    reports = dest / "sample_reports"
    reports.mkdir()
    for _label, scenario_id in DEMO_BUTTONS:
        record = simulate_scenario(scenario_id, seed=args.seed)
        envelope = engine.diagnose(
            record.observable(), run_id=record.run_id, scenario_id=scenario_id
        ).envelope
        render_report(envelope, reports / f"{scenario_id}.html")

    zip_path = REPO_ROOT / "artifacts" / "flowlens-offline-bundle.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in dest.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(dest.parent))
    print(f"wrote {dest} and {zip_path}")
    return 0


def _verify(args: argparse.Namespace) -> int:
    """Check that every required demo scenario behaves as the checklist demands."""
    from flowlens.contracts.enums import ABSTAINING_DECISIONS, Decision
    from flowlens.diagnosis.engine import get_engine
    from flowlens.simulator.runner import simulate_scenario
    from flowlens.simulator.scenarios import DEMO_BUTTONS, get_scenario

    engine = get_engine()
    failures: list[str] = []
    rows: list[tuple[str, str, str, str]] = []

    for label, scenario_id in DEMO_BUTTONS:
        spec = get_scenario(scenario_id)
        record = simulate_scenario(scenario_id, seed=args.seed)
        envelope = engine.diagnose(record.observable(), scenario_id=scenario_id).envelope
        expected = spec.expected_decision
        got = envelope.decision

        if expected is None:
            ok = got in ABSTAINING_DECISIONS or got == Decision.KNOWN_FAULT
            note = "ambiguous by design"
        else:
            ok = got == expected
            note = f"expected {expected.value}"
        if not ok:
            failures.append(f"{scenario_id}: got {got.value}, {note}")
        rows.append((label, scenario_id, got.value, "ok" if ok else "FAIL"))

        if envelope.next_test is not None:
            from flowlens.contracts.enums import RECOMMENDABLE_SAFETY_CLASSES

            if envelope.next_test.safety_class not in RECOMMENDABLE_SAFETY_CLASSES:
                failures.append(f"{scenario_id}: recommended a non-permitted safety class")
        for hypothesis in envelope.top_hypotheses:
            if hypothesis.faults and not hypothesis.support and not hypothesis.contradictions:
                failures.append(f"{scenario_id}: hypothesis {hypothesis.label} exposes no evidence")

    print(f"{'button':18s} {'scenario':40s} {'decision':20s} result")
    print("-" * 92)
    for label, scenario_id, decision, result in rows:
        print(f"{label:18s} {scenario_id:40s} {decision:20s} {result}")

    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("\nAll required demo scenarios behave as specified.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flowlens",
        description="FlowLens RCA Lab - read-only elevator fault isolation and root cause analysis",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("scenarios", help="list every reproducible scenario").set_defaults(
        func=_print_scenarios
    )

    p = sub.add_parser("simulate", help="run one scenario and optionally write the record")
    p.add_argument("scenario")
    p.add_argument("--seed", type=int, default=20260915)
    p.add_argument("--out")
    p.set_defaults(func=_simulate)

    p = sub.add_parser("fit", help="fit baselines, evidence models, novelty and calibration")
    p.add_argument("--limit", type=int, default=None, help="runs per scenario per split")
    p.set_defaults(func=_fit)

    p = sub.add_parser("features", help="dump the feature vector for one scenario")
    p.add_argument("scenario")
    p.add_argument("--seed", type=int, default=20260915)
    p.set_defaults(func=_features)

    p = sub.add_parser("diagnose", help="diagnose one scenario")
    p.add_argument("scenario")
    p.add_argument("--seed", type=int, default=20260915)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_diagnose)

    p = sub.add_parser("demo", help="run every required demo scenario in order")
    p.add_argument("--seed", type=int, default=20260915)
    p.set_defaults(func=_demo)

    p = sub.add_parser("verify", help="assert the required demo behaviour")
    p.add_argument("--seed", type=int, default=20260915)
    p.set_defaults(func=_verify)

    p = sub.add_parser("benchmark", help="regenerate baselines, ablations and metrics")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--out")
    p.set_defaults(func=_benchmark)

    p = sub.add_parser("report", help="render an incident report")
    p.add_argument("scenario")
    p.add_argument("--seed", type=int, default=20260915)
    p.add_argument("--out")
    p.set_defaults(func=_report)

    p = sub.add_parser("serve", help="run the API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true")
    p.set_defaults(func=_serve)

    p = sub.add_parser("generate-scenarios", help="write parquet dataset and golden hashes")
    p.add_argument("--seed", type=int, default=20260915)
    p.add_argument("--out")
    p.add_argument("--skip-golden", action="store_true")
    p.set_defaults(func=_generate)

    p = sub.add_parser("offline-bundle", help="pack docs, configs and sample reports")
    p.add_argument("--seed", type=int, default=20260915)
    p.add_argument("--out")
    p.set_defaults(func=_offline_bundle)

    return parser


def main(argv: list[str] | None = None) -> int:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
