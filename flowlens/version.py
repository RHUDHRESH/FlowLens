"""Component versions stamped into every evidence envelope.

Each version is bumped independently when the corresponding component changes
behaviour. Golden replay fixtures are keyed on these values, so a bump that
changes simulator or feature output requires regenerating golden fixtures.
"""

from __future__ import annotations

__version__ = "0.4.0"

SCHEMA_VERSION = "1.0.0"
SIMULATOR_VERSION = "1.0.0"
FEATURES_VERSION = "1.0.0"
GRAPH_VERSION = "public-demo-1"
MODELS_VERSION = "1.0.0"
CALIBRATION_VERSION = "1.0.0"


def component_versions() -> dict[str, str]:
    """Version block embedded in every IncidentEnvelope."""
    return {
        "flowlens": __version__,
        "schema": SCHEMA_VERSION,
        "simulator": SIMULATOR_VERSION,
        "features": FEATURES_VERSION,
        "graph": GRAPH_VERSION,
        "models": MODELS_VERSION,
        "calibration": CALIBRATION_VERSION,
    }
