"""Sectum AI: leak detection and the multi-tenant attack catalog.

This is the ``sectum.probes`` namespace package (the engineering spec, section
7). It also hosts the leak-detection pipeline (see ADR-0004).
"""

from sectum.probes.agent_tool_hijack import AgentToolHijackProbe
from sectum.probes.base import Probe, ProbeRegistry
from sectum.probes.detection import (
    DetectionPipeline,
    EmbeddingProvider,
    FakeEmbeddingProvider,
    FakeJudge,
    Judge,
    JudgeVerdict,
    confirmed_findings,
    dedupe_findings,
)
from sectum.probes.embedding_inversion import EmbeddingInversionProbe
from sectum.probes.erasure import ErasureProbe, ErasureReport, SurfaceErasure
from sectum.probes.ikea_extraction import IkeaExtractionProbe
from sectum.probes.lora_cross_tenant import LoraCrossTenantProbe
from sectum.probes.memory_contam import MemoryContamProbe
from sectum.probes.rag_entity_bleed import RagEntityBleedProbe
from sectum.probes.semantic_cache import SemanticCacheProbe
from sectum.probes.tenant_boundary import TenantBoundaryProbe

__all__ = [
    "AgentToolHijackProbe",
    "DetectionPipeline",
    "EmbeddingInversionProbe",
    "EmbeddingProvider",
    "ErasureProbe",
    "ErasureReport",
    "FakeEmbeddingProvider",
    "FakeJudge",
    "IkeaExtractionProbe",
    "Judge",
    "JudgeVerdict",
    "LoraCrossTenantProbe",
    "MemoryContamProbe",
    "Probe",
    "ProbeRegistry",
    "RagEntityBleedProbe",
    "SemanticCacheProbe",
    "SurfaceErasure",
    "TenantBoundaryProbe",
    "confirmed_findings",
    "dedupe_findings",
]
