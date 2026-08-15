"""Dataset partitioning.

Partitioning is by **complete run**, keyed on the seed. Every frame of a journey
lands in exactly one split, so no window from a journey can leak between
training and test. This is the single most common way a temporal fault-detection
benchmark accidentally reports an inflated number, so it is enforced in code
rather than left to convention.

At least one fault mechanism is withheld entirely (see
``simulator.scenarios.withheld_scenarios``); it appears only in ``test``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SplitName = Literal["train", "val", "calibration", "test"]

#: Seed ranges per split. Disjoint by construction.
SPLIT_SEEDS: dict[SplitName, tuple[int, ...]] = {
    "train": tuple(range(1_000, 1_032)),
    "val": tuple(range(2_000, 2_012)),
    "calibration": tuple(range(3_000, 3_024)),
    "test": tuple(range(4_000, 4_024)),
}


@dataclass(frozen=True)
class RunKey:
    scenario_id: str
    seed: int
    split: SplitName


def split_of(seed: int) -> SplitName | None:
    for name, seeds in SPLIT_SEEDS.items():
        if seed in seeds:
            return name
    return None


def assert_disjoint() -> None:
    """Fail loudly if the split seed ranges ever overlap."""
    seen: dict[int, SplitName] = {}
    for name, seeds in SPLIT_SEEDS.items():
        for seed in seeds:
            if seed in seen:
                raise AssertionError(
                    f"seed {seed} appears in both {seen[seed]} and {name}; splits must be disjoint"
                )
            seen[seed] = name


def keys_for(
    scenario_ids: list[str], split: SplitName, limit: int | None = None
) -> list[RunKey]:
    seeds = SPLIT_SEEDS[split]
    if limit is not None:
        seeds = seeds[:limit]
    return [RunKey(scenario_id=s, seed=seed, split=split) for s in scenario_ids for seed in seeds]
