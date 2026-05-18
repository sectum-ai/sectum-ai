"""The Sectum AI marker substrate: synthetic tenants, corpora, and markers.

This is part of the ``sectum`` core distribution (the engineering spec, section
6). The leak-detection pipeline lives in ``sectum.probes`` (see ADR-0004).
"""

from sectum.substrate.build import build_substrate
from sectum.substrate.scenario import default_scenario

__all__ = ["build_substrate", "default_scenario"]
