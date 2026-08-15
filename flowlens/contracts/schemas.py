"""Versioned Pydantic contracts for every FlowLens boundary.

Design rules enforced here:

* ``GroundTruth`` is never reachable from anything the diagnostic engine
  consumes. It lives on ``RunRecord`` alongside - not inside - the observable
  ``events`` and ``frames``. ``RunRecord.observable()`` is the only handle the
  engine is given.
* Every externally visible model carries ``schema_version``.
* Every hypothesis carries both support and contradictions. A hypothesis with
  no evidence items at all is rejected by validation.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from flowlens.contracts.enums import (
    Decision,
    DeviationType,
    EventType,
    FaultId,
    JourneyPhase,
    MaintenanceState,
    SafetyClass,
)
from flowlens.version import SCHEMA_VERSION


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False, use_enum_values=False)


class _Versioned(_Base):
    schema_version: str = Field(default=SCHEMA_VERSION)


# --------------------------------------------------------------------------- #
# Observable inputs
# --------------------------------------------------------------------------- #


class JourneyEvent(_Versioned):
    """A discrete controller-like event.

    ``quality`` is the transport/decode confidence in the event itself, not the
    confidence that the underlying condition is real.
    """

    asset_id: str
    journey_id: str
    timestamp_ms: int
    source: str = "controller_sim"
    event_type: EventType
    value: bool | int | float | str | None = None
    detail: str | None = None
    quality: float = Field(default=1.0, ge=0.0, le=1.0)

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"[{self.timestamp_ms:>6} ms] {self.event_type.value}={self.value}"


class SignalFrame(_Versioned):
    """One sampled frame of continuous measurements.

    A channel absent from ``signals`` is genuinely missing (dropout / packet
    loss). A channel present with a low ``quality`` entry is present but
    untrustworthy. The two cases are handled differently downstream, so they are
    represented differently here.
    """

    asset_id: str
    journey_id: str
    timestamp_ms: int
    signals: dict[str, float] = Field(default_factory=dict)
    quality: dict[str, float] = Field(default_factory=dict)

    @field_validator("quality")
    @classmethod
    def _quality_in_range(cls, v: dict[str, float]) -> dict[str, float]:
        for key, value in v.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"quality[{key}]={value} outside [0, 1]")
        return v


# --------------------------------------------------------------------------- #
# Simulation-side records (ground truth lives here, never in engine inputs)
# --------------------------------------------------------------------------- #


class FaultInjection(_Base):
    """A declared fault mechanism applied to a simulated run.

    ``mechanism`` names the single physical or data pathway the fault is allowed
    to modify. The simulator asserts that no other pathway changed.
    """

    fault_id: FaultId
    mechanism: str
    onset_ms: int = 0
    severity: float = Field(default=1.0, ge=0.0, le=1.0)
    params: dict[str, float] = Field(default_factory=dict)


class GroundTruth(_Base):
    """Simulator truth. Never passed to the diagnostic engine."""

    scenario_id: str
    seed: int
    injected_faults: list[FaultInjection] = Field(default_factory=list)
    true_first_deviation_phase: JourneyPhase | None = None
    true_first_deviation_type: DeviationType | None = None
    is_withheld_mechanism: bool = False
    notes: str = ""

    @property
    def fault_ids(self) -> frozenset[FaultId]:
        return frozenset(f.fault_id for f in self.injected_faults)


class ObservableRun(_Versioned):
    """Exactly what the diagnostic engine is allowed to see."""

    asset_id: str
    journey_id: str
    events: list[JourneyEvent]
    frames: list[SignalFrame]
    maintenance_state: MaintenanceState = MaintenanceState.IN_SERVICE
    asset_profile: str = "demo_profile_a"


class RunRecord(_Versioned):
    """A complete simulated run: observable data plus separated ground truth."""

    run_id: str
    scenario_id: str
    asset_id: str
    journey_id: str
    seed: int
    config_hash: str
    simulator_version: str
    events: list[JourneyEvent]
    frames: list[SignalFrame]
    ground_truth: GroundTruth
    maintenance_state: MaintenanceState = MaintenanceState.IN_SERVICE
    asset_profile: str = "demo_profile_a"

    def observable(self) -> ObservableRun:
        """Strip ground truth. The only engine-facing accessor."""
        return ObservableRun(
            asset_id=self.asset_id,
            journey_id=self.journey_id,
            events=list(self.events),
            frames=list(self.frames),
            maintenance_state=self.maintenance_state,
            asset_profile=self.asset_profile,
        )


class ScenarioSpec(_Base):
    """Registry entry describing a reproducible scenario."""

    scenario_id: str
    title: str
    family: Literal["healthy", "single_fault", "compound_fault", "sensor_fault", "unknown_fault"]
    description: str
    injections: list[FaultInjection] = Field(default_factory=list)
    channel_defects: list[dict[str, Any]] = Field(default_factory=list)
    expected_decision: Decision | None = None
    expected_first_deviation_phase: JourneyPhase | None = None
    demo_button: str | None = None
    withheld: bool = False


# --------------------------------------------------------------------------- #
# Journey reconstruction
# --------------------------------------------------------------------------- #


class JourneySegment(_Base):
    """One reconstructed phase occupancy interval."""

    phase: JourneyPhase
    start_ms: int
    end_ms: int | None = None
    entry_evidence: list[str] = Field(default_factory=list)
    expected_next: list[JourneyPhase] = Field(default_factory=list)
    guard_ms: int | None = None
    dwell_ms: int | None = None
    timed_out: bool = False

    @property
    def duration_ms(self) -> int | None:
        if self.end_ms is None:
            return None
        return self.end_ms - self.start_ms


class FirstDeviation(_Base):
    """The earliest well-supported departure from the expected journey.

    This constrains and informs the causal graph. It is deliberately *not*
    declared to be the root cause.
    """

    phase: JourneyPhase
    type: DeviationType
    timestamp_ms: int
    expected_next: JourneyPhase | None = None
    observed_delay_ms: int | None = None
    guard_ms: int | None = None
    statement: str
    affected_domains: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    supporting_event_indices: list[int] = Field(default_factory=list)


class ChannelQuality(_Base):
    """Per-channel data integrity assessment produced before any diagnosis."""

    channel: str
    present: bool
    mean_quality: float = Field(ge=0.0, le=1.0)
    coverage: float = Field(ge=0.0, le=1.0, description="Fraction of frames carrying the channel")
    defects: list[str] = Field(default_factory=list)
    usable: bool = True

    @property
    def integrity(self) -> float:
        return 0.0 if not self.present else self.mean_quality * self.coverage


# --------------------------------------------------------------------------- #
# Diagnosis
# --------------------------------------------------------------------------- #


class EvidenceItem(_Base):
    """One named observation and the direction in which it argues."""

    key: str
    statement: str
    value: float | None = None
    weight: float = 0.0
    direction: Literal["support", "contradiction", "neutral"] = "neutral"
    phase: JourneyPhase | None = None
    channel: str | None = None
    quality: float = 1.0

    @model_validator(mode="after")
    def _weight_matches_direction(self) -> EvidenceItem:
        if self.direction == "support" and self.weight < 0:
            raise ValueError("support evidence cannot carry negative weight")
        if self.direction == "contradiction" and self.weight > 0:
            raise ValueError("contradiction evidence cannot carry positive weight")
        return self


class Hypothesis(_Base):
    """A candidate explanation: one fault, a compound set, or the healthy state."""

    faults: list[FaultId] = Field(default_factory=list)
    probability: float = Field(ge=0.0, le=1.0)
    log_score: float = 0.0
    support: list[EvidenceItem] = Field(default_factory=list)
    contradictions: list[EvidenceItem] = Field(default_factory=list)
    causal_path: list[str] = Field(default_factory=list)
    first_deviation_fit: float = 0.0
    downstream_coverage: float = 0.0
    onset_phase: JourneyPhase | None = None
    rationale: str = ""

    @property
    def label(self) -> str:
        if not self.faults:
            return "healthy"
        return " + ".join(sorted(f.value for f in self.faults))

    @property
    def is_compound(self) -> bool:
        return len(self.faults) > 1

    @model_validator(mode="after")
    def _must_expose_evidence(self) -> Hypothesis:
        if self.faults and not self.support and not self.contradictions:
            raise ValueError(
                f"hypothesis {self.label} exposes neither support nor contradictions; "
                "every hypothesis must be auditable"
            )
        return self


class NoveltyReport(_Base):
    """Healthy-model novelty scoring, used to route unmodelled behaviour."""

    score: float
    threshold: float
    is_novel: bool
    worst_features: list[str] = Field(default_factory=list)
    phase: JourneyPhase | None = None


class ConformalReport(_Base):
    """Set-valued prediction from the calibration split."""

    alpha: float
    nonconformity_threshold: float
    label_set: list[str] = Field(default_factory=list)
    set_size: int = 0
    covers_healthy: bool = False


class AbstentionReport(_Base):
    """Why the gate chose the decision it chose."""

    decision: Decision
    reason: str
    triggered_rule: str
    margin: float | None = None
    novelty: NoveltyReport | None = None
    conformal: ConformalReport | None = None
    blocking_channels: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Test planning
# --------------------------------------------------------------------------- #


class TestOutcome(_Base):
    __test__ = False
    outcome_id: str
    description: str
    likelihood_by_fault: dict[str, float] = Field(default_factory=dict)
    default_likelihood: float = 0.5


class PermittedTest(_Base):
    """A reviewed, non-actuating diagnostic observation.

    The planner may only ever select from the whitelist. It cannot synthesize a
    procedure, and it cannot recommend anything with safety class ACTUATING.
    """

    test_id: str
    name: str
    description: str
    safety_class: SafetyClass
    required_maintenance_state: list[MaintenanceState] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    prohibited_conditions: list[str] = Field(default_factory=list)
    duration_minutes: float = 5.0
    operational_cost: float = 1.0
    risk_penalty: float = 0.0
    discriminates: list[FaultId] = Field(default_factory=list)
    outcomes: list[TestOutcome] = Field(default_factory=list)
    reviewed_by: str = "unassigned"

    @model_validator(mode="after")
    def _no_actuating_without_marker(self) -> PermittedTest:
        if self.safety_class == SafetyClass.ACTUATING and "safety_test_fixture" not in self.test_id:
            raise ValueError(
                f"test {self.test_id} is ACTUATING; actuating tests may only exist as "
                "safety test fixtures and are never recommendable"
            )
        return self


class NextTest(_Base):
    """The planner's recommendation, with its full justification."""

    test_id: str
    name: str
    reason: str
    safety_class: SafetyClass
    expected_entropy_reduction_bits: float
    prior_entropy_bits: float
    expected_posterior_entropy_bits: float
    utility: float
    duration_minutes: float
    outcome_effects: list[dict[str, Any]] = Field(default_factory=list)
    alternatives: list[dict[str, Any]] = Field(default_factory=list)


class TestOutcomeReport(_Base):
    """A technician-reported result fed back into the engine (read-only update)."""

    test_id: str
    outcome_id: str
    observed_at_ms: int | None = None
    note: str = ""


# --------------------------------------------------------------------------- #
# Envelope
# --------------------------------------------------------------------------- #


class IncidentEnvelope(_Versioned):
    """The single auditable artifact behind the console and the PDF report.

    Everything a judge or technician sees must be reconstructable from this
    object plus the versioned public configuration. Nothing is computed for
    display only.
    """

    incident_id: str
    asset_id: str
    journey_id: str
    run_id: str | None = None
    scenario_id: str | None = None
    created_at: str

    decision: Decision
    abstention: AbstentionReport
    headline: str

    journey: list[JourneySegment] = Field(default_factory=list)
    terminal_phase: JourneyPhase | None = None
    first_deviation: FirstDeviation | None = None
    deviations: list[FirstDeviation] = Field(default_factory=list)

    channel_quality: list[ChannelQuality] = Field(default_factory=list)
    features: dict[str, float] = Field(default_factory=dict)

    top_hypotheses: list[Hypothesis] = Field(default_factory=list)
    next_test: NextTest | None = None

    alarms: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0
    versions: dict[str, str] = Field(default_factory=dict)
    raw_trace_hash: str = "sha256:unset"
    config_hash: str = "sha256:unset"

    safety_notice: str = (
        "FlowLens is read-only and advisory. It cannot reset faults, command motion, "
        "release a brake, bypass a safety circuit, or authorize return to service. "
        "All recommendations require a trained technician's judgement."
    )

    @property
    def is_abstaining(self) -> bool:
        from flowlens.contracts.enums import ABSTAINING_DECISIONS

        return self.decision in ABSTAINING_DECISIONS
