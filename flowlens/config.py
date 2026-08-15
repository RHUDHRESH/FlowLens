"""Versioned configuration loading.

All tunable behaviour lives in ``configs/*.yaml`` so that a diagnosis can be
reconstructed from a committed evidence envelope plus a committed configuration.
Nothing in this module reads the environment or the network.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from flowlens.contracts.enums import (
    DeviationType,
    FaultId,
    JourneyPhase,
    MaintenanceState,
    SafetyClass,
)
from flowlens.contracts.schemas import PermittedTest, TestOutcome


def config_dir() -> Path:
    """Resolve the configuration directory.

    ``FLOWLENS_CONFIG_DIR`` exists so tests can point at a fixture directory. It
    is not used to change behaviour at runtime in the demo.
    """
    override = os.environ.get("FLOWLENS_CONFIG_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "configs"


def _load_yaml(name: str) -> dict[str, Any]:
    path = config_dir() / name
    if not path.exists():
        raise FileNotFoundError(f"required configuration missing: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"configuration {name} did not parse to a mapping")
    return data


# --------------------------------------------------------------------------- #
# Journey model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PhaseSpec:
    phase: JourneyPhase
    entry_evidence: tuple[str, ...]
    expected_next: tuple[JourneyPhase, ...]
    guard_ms: int | None
    dwell_min_ms: int
    dwell_max_ms: int
    prohibited_next: frozenset[JourneyPhase]
    observable: tuple[str, ...]
    affected_domains: tuple[str, ...]
    terminal: bool
    entry_hold_ms: int = 0

    @property
    def primary_next(self) -> JourneyPhase | None:
        return self.expected_next[0] if self.expected_next else None


@dataclass(frozen=True)
class JourneyModel:
    version: str
    phases: dict[JourneyPhase, PhaseSpec]
    always_allowed_next: frozenset[JourneyPhase]
    retry_loop_threshold: int
    motion_permission_chain: tuple[JourneyPhase, ...]
    motion_phases: frozenset[JourneyPhase]

    def spec(self, phase: JourneyPhase) -> PhaseSpec:
        return self.phases[phase]

    def is_allowed(self, src: JourneyPhase, dst: JourneyPhase) -> bool:
        spec = self.phases[src]
        if dst in spec.prohibited_next:
            return False
        return dst in spec.expected_next or dst in self.always_allowed_next

    def is_prohibited(self, src: JourneyPhase, dst: JourneyPhase) -> bool:
        return dst in self.phases[src].prohibited_next


@lru_cache(maxsize=1)
def journey_model() -> JourneyModel:
    raw = _load_yaml("journey_phases.yaml")
    defaults = raw.get("defaults", {})
    phases: dict[JourneyPhase, PhaseSpec] = {}
    for name, body in raw["phases"].items():
        phase = JourneyPhase(name)
        dwell = body.get("dwell_ms") or [0, 600000]
        phases[phase] = PhaseSpec(
            phase=phase,
            entry_evidence=tuple(body.get("entry_evidence") or ()),
            expected_next=tuple(JourneyPhase(p) for p in (body.get("expected_next") or ())),
            guard_ms=body.get("guard_ms"),
            dwell_min_ms=int(dwell[0]),
            dwell_max_ms=int(dwell[1]),
            prohibited_next=frozenset(
                JourneyPhase(p) for p in (body.get("prohibited_next") or ())
            ),
            observable=tuple(body.get("observable") or ()),
            affected_domains=tuple(body.get("affected_domains") or ()),
            terminal=bool(body.get("terminal", False)),
            entry_hold_ms=int(body.get("entry_hold_ms", 0)),
        )
    return JourneyModel(
        version=str(raw.get("version", "0")),
        phases=phases,
        always_allowed_next=frozenset(
            JourneyPhase(p) for p in (defaults.get("always_allowed_next") or ())
        ),
        retry_loop_threshold=int(defaults.get("retry_loop_threshold", 2)),
        motion_permission_chain=tuple(
            JourneyPhase(p) for p in raw.get("motion_permission_chain", ())
        ),
        motion_phases=frozenset(JourneyPhase(p) for p in raw.get("motion_phases", ())),
    )


# --------------------------------------------------------------------------- #
# Fault graph
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FeatureSpec:
    key: str
    description: str
    healthy_mean: float
    healthy_sd: float
    requires: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceSpec:
    feature: str
    mean: float
    sd: float
    weight: float


@dataclass(frozen=True)
class CaveatSpec:
    feature: str
    when: str
    threshold: float
    statement: str


@dataclass(frozen=True)
class FaultSpec:
    fault_id: FaultId
    subsystem: str
    label: str
    prior: float
    deviation_phases: frozenset[JourneyPhase]
    deviation_types: frozenset[DeviationType]
    causal_path: tuple[str, ...]
    downstream_alarms: tuple[str, ...]
    evidence: tuple[EvidenceSpec, ...]
    caveats: tuple[CaveatSpec, ...] = ()


@dataclass(frozen=True)
class FaultGraph:
    version: str
    features: dict[str, FeatureSpec]
    faults: dict[FaultId, FaultSpec]
    compatible_pairs: frozenset[frozenset[FaultId]]
    withheld: frozenset[FaultId]

    def modelled_faults(self) -> tuple[FaultId, ...]:
        return tuple(self.faults.keys())

    def is_compatible(self, a: FaultId, b: FaultId) -> bool:
        return frozenset({a, b}) in self.compatible_pairs


@lru_cache(maxsize=1)
def fault_graph() -> FaultGraph:
    raw = _load_yaml("public_fault_graph.yaml")

    features = {
        key: FeatureSpec(
            key=key,
            description=body.get("description", ""),
            healthy_mean=float(body["healthy_mean"]),
            healthy_sd=float(body["healthy_sd"]),
            requires=tuple(body.get("requires") or ()),
        )
        for key, body in raw["features"].items()
    }

    faults: dict[FaultId, FaultSpec] = {}
    for name, body in raw["faults"].items():
        fault_id = FaultId(name)
        evidence = tuple(
            EvidenceSpec(
                feature=item["feature"],
                mean=float(item["mean"]),
                sd=float(item["sd"]),
                weight=float(item["weight"]),
            )
            for item in body.get("evidence", [])
        )
        for spec in evidence:
            if spec.feature not in features:
                raise ValueError(
                    f"fault {name} references undeclared feature '{spec.feature}'"
                )
            if spec.sd <= 0:
                raise ValueError(f"fault {name} feature {spec.feature} has non-positive sd")
        caveats = tuple(
            CaveatSpec(
                feature=item["feature"],
                when=item.get("when", "high"),
                threshold=float(item.get("threshold", 0.5)),
                statement=item["statement"],
            )
            for item in body.get("caveats", [])
        )
        faults[fault_id] = FaultSpec(
            fault_id=fault_id,
            subsystem=body.get("subsystem", "unknown"),
            label=body.get("label", fault_id.value),
            prior=float(body.get("prior", 0.02)),
            deviation_phases=frozenset(
                JourneyPhase(p) for p in (body.get("deviation_phases") or ())
            ),
            deviation_types=frozenset(
                DeviationType(t) for t in (body.get("deviation_types") or ())
            ),
            causal_path=tuple(body.get("causal_path") or ()),
            downstream_alarms=tuple(body.get("downstream_alarms") or ()),
            evidence=evidence,
            caveats=caveats,
        )

    withheld = frozenset(FaultId(f) for f in raw.get("withheld_from_graph", []))
    leaked = withheld & set(faults)
    if leaked:
        raise ValueError(
            f"withheld fault(s) {sorted(f.value for f in leaked)} have evidence models in the "
            "public graph; the unknown-fault evaluation would be invalid"
        )

    pairs = frozenset(
        frozenset({FaultId(a), FaultId(b)}) for a, b in raw.get("compatible_pairs", [])
    )
    for pair in pairs:
        for member in pair:
            if member not in faults:
                raise ValueError(f"compatible_pairs references unmodelled fault '{member.value}'")

    return FaultGraph(
        version=str(raw.get("version", "0")),
        features=features,
        faults=faults,
        compatible_pairs=pairs,
        withheld=withheld,
    )


# --------------------------------------------------------------------------- #
# Permitted tests
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TestWhitelist:
    version: str
    tests: tuple[PermittedTest, ...]

    def by_id(self, test_id: str) -> PermittedTest | None:
        for test in self.tests:
            if test.test_id == test_id:
                return test
        return None

    def recommendable(self) -> tuple[PermittedTest, ...]:
        from flowlens.contracts.enums import RECOMMENDABLE_SAFETY_CLASSES

        return tuple(t for t in self.tests if t.safety_class in RECOMMENDABLE_SAFETY_CLASSES)


@lru_cache(maxsize=1)
def permitted_tests() -> TestWhitelist:
    raw = _load_yaml("permitted_tests.yaml")
    tests: list[PermittedTest] = []
    for body in raw["tests"]:
        outcomes = [
            TestOutcome(
                outcome_id=o["outcome_id"],
                description=o.get("description", ""),
                likelihood_by_fault={k: float(v) for k, v in (o.get("likelihood_by_fault") or {}).items()},
                default_likelihood=float(o.get("default_likelihood", 0.5)),
            )
            for o in body.get("outcomes", [])
        ]
        if len(outcomes) < 2:
            raise ValueError(
                f"test {body['test_id']} declares fewer than two outcomes and cannot "
                "reduce hypothesis entropy"
            )
        tests.append(
            PermittedTest(
                test_id=body["test_id"],
                name=body["name"],
                description=" ".join(body.get("description", "").split()),
                safety_class=SafetyClass(body["safety_class"]),
                required_maintenance_state=[
                    MaintenanceState(s) for s in body.get("required_maintenance_state", [])
                ],
                prerequisites=list(body.get("prerequisites") or []),
                prohibited_conditions=list(body.get("prohibited_conditions") or []),
                duration_minutes=float(body.get("duration_minutes", 5.0)),
                operational_cost=float(body.get("operational_cost", 1.0)),
                risk_penalty=float(body.get("risk_penalty", 0.0)),
                discriminates=[FaultId(f) for f in body.get("discriminates", [])],
                outcomes=outcomes,
                reviewed_by=body.get("reviewed_by", "unassigned"),
            )
        )
    return TestWhitelist(version=str(raw.get("version", "0")), tests=tuple(tests))


# --------------------------------------------------------------------------- #
# Thresholds
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Thresholds:
    version: str
    inference: dict[str, float] = field(default_factory=dict)
    quality: dict[str, float] = field(default_factory=dict)
    novelty: dict[str, float] = field(default_factory=dict)
    abstention: dict[str, float] = field(default_factory=dict)
    planner: dict[str, float] = field(default_factory=dict)
    simulator: dict[str, Any] = field(default_factory=dict)


@lru_cache(maxsize=1)
def thresholds() -> Thresholds:
    raw = _load_yaml("demo_thresholds.yaml")
    return Thresholds(
        version=str(raw.get("version", "0")),
        inference=raw.get("inference", {}),
        quality=raw.get("quality", {}),
        novelty=raw.get("novelty", {}),
        abstention=raw.get("abstention", {}),
        planner=raw.get("planner", {}),
        simulator=raw.get("simulator", {}),
    )


# --------------------------------------------------------------------------- #
# Hashing
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def config_hash() -> str:
    """Stable hash over every configuration file that can change behaviour.

    Stamped into every envelope so a result can be tied to the exact
    configuration that produced it.
    """
    digest = hashlib.sha256()
    for name in sorted(
        [
            "journey_phases.yaml",
            "public_fault_graph.yaml",
            "permitted_tests.yaml",
            "demo_thresholds.yaml",
        ]
    ):
        path = config_dir() / name
        digest.update(name.encode("utf-8"))
        digest.update(path.read_bytes())
    return f"sha256:{digest.hexdigest()}"


def stable_hash(payload: Any) -> str:
    """Deterministic hash of a JSON-serializable payload."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def reset_caches() -> None:
    """Drop cached configuration. Used by tests that swap config directories."""
    journey_model.cache_clear()
    fault_graph.cache_clear()
    permitted_tests.cache_clear()
    thresholds.cache_clear()
    config_hash.cache_clear()
