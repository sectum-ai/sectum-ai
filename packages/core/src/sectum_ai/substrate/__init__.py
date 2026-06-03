"""The Sectum AI marker substrate: synthetic tenants, corpora, and markers.

This is part of the ``sectum`` core distribution (the engineering spec, section
6). The leak-detection pipeline lives in ``sectum_ai.probes`` (see ADR-0004).
"""

from sectum_ai.substrate.build import build_substrate
from sectum_ai.substrate.scenario import default_scenario

__all__ = ["build_substrate", "default_scenario"]
