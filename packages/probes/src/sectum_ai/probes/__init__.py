"""Sectum AI: leak detection and the multi-tenant attack catalog.

This is the ``sectum_ai.probes`` namespace package (the engineering spec, section
7). It also hosts the leak-detection pipeline (see ADR-0004).
"""

from sectum_ai.probes.agent_framework_hijack import AgentFrameworkHijackProbe
from sectum_ai.probes.agent_tool_hijack import AgentToolHijackProbe
from sectum_ai.probes.base import Probe, ProbeRegistry, load_probe_manifest
from sectum_ai.probes.calibrate import (
    CalibrationExample,
    CalibrationResult,
    ThresholdScore,
    calibrate_threshold,
)
from sectum_ai.probes.detection import (
    DEFAULT_SEMANTIC_THRESHOLD,
    MODEL_THRESHOLDS,
    DetectingProbe,
    DetectionPipeline,
    DetectionProviders,
    EmbeddingProvider,
    FakeEmbeddingProvider,
    FakeJudge,
    Judge,
    JudgeVerdict,
    confirmed_findings,
    dedupe_findings,
    is_cross_principal,
    resolve_semantic_threshold,
)
from sectum_ai.probes.embedding_inversion import EmbeddingInversionProbe
from sectum_ai.probes.erasure import (
    ERASURE_SURFACES,
    ErasureProbe,
    ErasureReport,
    SurfaceErasure,
)
from sectum_ai.probes.ikea_extraction import IkeaExtractionProbe
from sectum_ai.probes.kv_cache_timing import KvCacheTimingProbe, KvCacheTimingReport, TimingSignal
from sectum_ai.probes.lora_cross_tenant import LoraCrossTenantProbe
from sectum_ai.probes.memory_contam import MemoryContamProbe
from sectum_ai.probes.providers import (
    AnthropicJudge,
    OpenAIEmbeddingProvider,
    OpenAIJudge,
)
from sectum_ai.probes.rag_entity_bleed import RagEntityBleedProbe
from sectum_ai.probes.rag_pipeline_bleed import RagPipelineBleedProbe
from sectum_ai.probes.rag_poisoning import RagPoisoningProbe
from sectum_ai.probes.semantic_cache import SemanticCacheProbe
from sectum_ai.probes.tenant_boundary import TenantBoundaryProbe

__all__ = [
    "DEFAULT_SEMANTIC_THRESHOLD",
    "ERASURE_SURFACES",
    "MODEL_THRESHOLDS",
    "AgentFrameworkHijackProbe",
    "AgentToolHijackProbe",
    "AnthropicJudge",
    "CalibrationExample",
    "CalibrationResult",
    "DetectingProbe",
    "DetectionPipeline",
    "DetectionProviders",
    "EmbeddingInversionProbe",
    "EmbeddingProvider",
    "ErasureProbe",
    "ErasureReport",
    "FakeEmbeddingProvider",
    "FakeJudge",
    "IkeaExtractionProbe",
    "Judge",
    "JudgeVerdict",
    "KvCacheTimingProbe",
    "KvCacheTimingReport",
    "LoraCrossTenantProbe",
    "MemoryContamProbe",
    "OpenAIEmbeddingProvider",
    "OpenAIJudge",
    "Probe",
    "ProbeRegistry",
    "RagEntityBleedProbe",
    "RagPipelineBleedProbe",
    "RagPoisoningProbe",
    "SemanticCacheProbe",
    "SurfaceErasure",
    "TenantBoundaryProbe",
    "ThresholdScore",
    "TimingSignal",
    "calibrate_threshold",
    "confirmed_findings",
    "dedupe_findings",
    "is_cross_principal",
    "load_probe_manifest",
    "resolve_semantic_threshold",
]
