"""Sectum AI: leak detection and the multi-tenant attack catalog.

This is the ``sectum.probes`` namespace package (the engineering spec, section
7). It also hosts the leak-detection pipeline (see ADR-0004).
"""

from sectum.probes.base import Probe, ProbeRegistry
from sectum.probes.detection import (
    DetectionPipeline,
    EmbeddingProvider,
    FakeEmbeddingProvider,
    FakeJudge,
    Judge,
    JudgeVerdict,
    confirmed_findings,
)
from sectum.probes.tenant_boundary import TenantBoundaryProbe

__all__ = [
    "DetectionPipeline",
    "EmbeddingProvider",
    "FakeEmbeddingProvider",
    "FakeJudge",
    "Judge",
    "JudgeVerdict",
    "Probe",
    "ProbeRegistry",
    "TenantBoundaryProbe",
    "confirmed_findings",
]
