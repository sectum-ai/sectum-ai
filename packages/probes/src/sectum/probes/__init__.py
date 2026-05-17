"""Sectum AI attack catalog: multi-tenant leakage probe classes (``sectum.probes``).

This is the ``sectum.probes`` namespace package (the engineering spec, section 7).
"""

from sectum.probes.base import Probe, ProbeRegistry

__all__ = ["Probe", "ProbeRegistry"]
