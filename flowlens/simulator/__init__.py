"""Deterministic elevator incident simulator and fault-injection harness.

The simulator is the only component that knows ground truth. It hands the
diagnostic engine an :class:`~flowlens.contracts.schemas.ObservableRun` and keeps
labels on the side in :class:`~flowlens.contracts.schemas.GroundTruth`.
"""

from flowlens.simulator.faults import Mechanism, apply_injections, mechanism_fields
from flowlens.simulator.runner import simulate, simulate_scenario
from flowlens.simulator.scenarios import (
    DEMO_BUTTONS,
    get_scenario,
    list_scenarios,
)

__all__ = [
    "Mechanism",
    "apply_injections",
    "mechanism_fields",
    "simulate",
    "simulate_scenario",
    "get_scenario",
    "list_scenarios",
    "DEMO_BUTTONS",
]
