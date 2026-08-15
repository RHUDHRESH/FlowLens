"""The FlowLens diagnostic core.

Pipeline order (see ``docs/architecture.md``)::

    validate -> channel quality -> journey compile -> first deviation
      -> phase-conditioned features -> per-fault evidence + novelty
      -> factorial temporal beam -> causal ranking -> abstention gate
"""

from flowlens.diagnosis.compiler import CompiledJourney, JourneyFacts, compile_journey
from flowlens.diagnosis.deviation import localize_deviations

__all__ = [
    "CompiledJourney",
    "JourneyFacts",
    "compile_journey",
    "localize_deviations",
]
