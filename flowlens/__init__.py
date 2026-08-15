"""FlowLens RCA Lab - evidence-first elevator fault isolation.

FlowLens is strictly read-only. It ingests recorded or simulated elevator data,
reconstructs the journey, localizes the first causal deviation, ranks root-cause
hypotheses with support and contradictions, abstains when evidence is inadequate,
and recommends the safest permitted next diagnostic test.

It never commands motion, resets alarms, releases brakes, or bypasses safety circuits.
"""

from flowlens.version import (
    CALIBRATION_VERSION,
    FEATURES_VERSION,
    GRAPH_VERSION,
    MODELS_VERSION,
    SCHEMA_VERSION,
    SIMULATOR_VERSION,
    __version__,
)

__all__ = [
    "__version__",
    "SCHEMA_VERSION",
    "SIMULATOR_VERSION",
    "FEATURES_VERSION",
    "GRAPH_VERSION",
    "MODELS_VERSION",
    "CALIBRATION_VERSION",
]
