"""Shared fixtures.

The repository root is put on ``sys.path`` so the suite runs from a clean
checkout without an editable install.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEMO_SEED = 20260915


@pytest.fixture(scope="session")
def engine():
    from flowlens.diagnosis.engine import get_engine

    return get_engine()


@pytest.fixture(scope="session")
def demo_scenarios():
    from flowlens.simulator.scenarios import DEMO_BUTTONS

    return DEMO_BUTTONS


@pytest.fixture(scope="session")
def all_scenarios():
    from flowlens.simulator.scenarios import list_scenarios

    return list_scenarios()


@pytest.fixture(scope="session")
def healthy_run():
    from flowlens.simulator.runner import simulate_scenario

    return simulate_scenario("healthy", seed=DEMO_SEED)


@pytest.fixture(scope="session")
def brake_drag_run():
    from flowlens.simulator.runner import simulate_scenario

    return simulate_scenario("brake_drag", seed=DEMO_SEED)
