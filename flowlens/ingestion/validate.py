"""Timestamp and schema validation for an incoming run."""

from __future__ import annotations

from dataclasses import dataclass

from flowlens.contracts.schemas import ObservableRun


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    fatal: bool = False


def validate_run(run: ObservableRun) -> list[ValidationIssue]:
    """Structural checks that do not depend on any diagnostic model."""
    issues: list[ValidationIssue] = []

    if not run.frames:
        issues.append(ValidationIssue("no_frames", "run carries no signal frames", fatal=True))
    if not run.events:
        issues.append(ValidationIssue("no_events", "run carries no journey events", fatal=True))
    if not run.frames or not run.events:
        return issues

    event_times = [e.timestamp_ms for e in run.events]
    if event_times != sorted(event_times):
        issues.append(
            ValidationIssue("events_unordered", "journey events are not monotonically ordered")
        )

    frame_times = [f.timestamp_ms for f in run.frames]
    if frame_times != sorted(frame_times):
        issues.append(
            ValidationIssue("frames_unordered", "signal frames are not monotonically ordered")
        )
    if len(set(frame_times)) != len(frame_times):
        issues.append(ValidationIssue("duplicate_frames", "duplicate frame timestamps present"))

    mismatched = {e.journey_id for e in run.events} | {f.journey_id for f in run.frames}
    if len(mismatched) > 1:
        issues.append(
            ValidationIssue(
                "journey_id_mismatch",
                f"run mixes journey ids: {sorted(mismatched)}",
                fatal=True,
            )
        )

    span_ms = frame_times[-1] - frame_times[0]
    if span_ms <= 0:
        issues.append(ValidationIssue("zero_span", "frame stream has no duration", fatal=True))

    return issues
