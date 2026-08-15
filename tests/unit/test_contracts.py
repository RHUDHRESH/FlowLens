"""Contract and isolation invariants."""

from flowlens.contracts.enums import FaultId
from flowlens.contracts.schemas import EvidenceItem, Hypothesis, ObservableRun


def test_observable_run_has_no_ground_truth(healthy_run):
    observable = healthy_run.observable()
    assert isinstance(observable, ObservableRun)
    assert not hasattr(observable, "ground_truth")
    dumped = observable.model_dump()
    assert "ground_truth" not in dumped
    assert "injected_faults" not in dumped


def test_engine_never_receives_injected_fault_ids(healthy_run, brake_drag_run):
    for record in (healthy_run, brake_drag_run):
        payload = record.observable().model_dump_json()
        assert '"ground_truth"' not in payload
        assert "injected_faults" not in payload


def test_hypothesis_rejects_empty_evidence():
    try:
        Hypothesis(faults=[FaultId.BRAKE_DRAG], probability=0.9)
    except ValueError as exc:
        assert "neither support nor contradictions" in str(exc)
    else:
        raise AssertionError("empty-evidence hypothesis was accepted")


def test_hypothesis_accepts_contradiction_only():
    Hypothesis(
        faults=[FaultId.BRAKE_DRAG],
        probability=0.4,
        contradictions=[
            EvidenceItem(key="k", statement="does not fit", weight=-0.2, direction="contradiction")
        ],
    )
