"""Turn a scenario plus a seed into a reproducible :class:`RunRecord`."""

from __future__ import annotations

import numpy as np

from flowlens.config import config_hash
from flowlens.contracts.schemas import RunRecord, ScenarioSpec
from flowlens.simulator.defects import apply_defects
from flowlens.simulator.faults import Mechanism, apply_injections, describe
from flowlens.simulator.journey import JourneySimulation
from flowlens.simulator.physics import DEMO_PROFILE, AssetProfile
from flowlens.simulator.scenarios import get_scenario
from flowlens.version import SIMULATOR_VERSION


def simulate(
    spec: ScenarioSpec,
    *,
    seed: int = 20260915,
    asset_id: str = "demo_elevator_01",
    journey_index: int = 42,
    profile: AssetProfile | None = None,
) -> RunRecord:
    """Run one scenario deterministically.

    The same ``(spec, seed, profile, configuration)`` always yields byte-identical
    events and frames. Ground truth is attached to the record but is not part of
    :meth:`RunRecord.observable`, which is all the engine ever sees.
    """
    profile = profile or DEMO_PROFILE
    journey_id = f"journey_{journey_index:05d}"
    run_id = f"{spec.scenario_id}_{seed}_{journey_index}"

    mechanism, _onsets = apply_injections(Mechanism(), list(spec.injections))

    sim = JourneySimulation(
        mechanism=mechanism,
        asset_id=asset_id,
        journey_id=journey_id,
        seed=seed,
        profile=profile,
    )
    events, frames, terminal_phase, alarms = sim.run()

    if spec.channel_defects:
        # A separate stream so that adding a defect cannot perturb the physics RNG.
        defect_rng = np.random.default_rng(seed ^ 0x5EED_DEFEC)
        frames = apply_defects(frames, list(spec.channel_defects), defect_rng)

    from flowlens.contracts.schemas import GroundTruth

    ground_truth = GroundTruth(
        scenario_id=spec.scenario_id,
        seed=seed,
        injected_faults=list(spec.injections),
        true_first_deviation_phase=spec.expected_first_deviation_phase,
        is_withheld_mechanism=spec.withheld,
        notes=(
            f"terminal_phase={terminal_phase.value}; alarms={','.join(alarms) or 'none'}; "
            f"mechanism={describe(mechanism)}"
        ),
    )

    return RunRecord(
        run_id=run_id,
        scenario_id=spec.scenario_id,
        asset_id=asset_id,
        journey_id=journey_id,
        seed=seed,
        config_hash=config_hash(),
        simulator_version=SIMULATOR_VERSION,
        events=events,
        frames=frames,
        ground_truth=ground_truth,
        asset_profile=profile.profile_id,
    )


def simulate_scenario(scenario_id: str, *, seed: int = 20260915, **kwargs) -> RunRecord:
    return simulate(get_scenario(scenario_id), seed=seed, **kwargs)
