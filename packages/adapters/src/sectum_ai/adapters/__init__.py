"""Sectum AI adapters: connectors to vector stores, RAG, observability, agents, MCP, and caches.

This is the ``sectum_ai.adapters`` namespace package (the engineering spec, section 11).
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

from sectum_ai.adapters.base import (
    Adapter,
    AdapterFamily,
    AdapterRegistry,
    AgentAdapter,
    AgentResult,
    BackupAdapter,
    CacheAdapter,
    Capability,
    EvalSetAdapter,
    MCPAdapter,
    McpResult,
    MemoryAdapter,
    ModelAdapter,
    ObservabilityAdapter,
    RagAnswer,
    RAGPipelineAdapter,
    SearchIndexAdapter,
    TraceHit,
    VectorHit,
    VectorStoreAdapter,
)
from sectum_ai.adapters.fakes import (
    FakeAgent,
    FakeBackup,
    FakeCache,
    FakeEvalSet,
    FakeMCP,
    FakeMemory,
    FakeModel,
    FakeObservability,
    FakeRAGPipeline,
    FakeSearchIndex,
    FakeVectorStore,
)

__all__ = [
    "Adapter",
    "AdapterFamily",
    "AdapterRegistry",
    "AgentAdapter",
    "AgentResult",
    "BackupAdapter",
    "CacheAdapter",
    "Capability",
    "EvalSetAdapter",
    "FakeAgent",
    "FakeBackup",
    "FakeCache",
    "FakeEvalSet",
    "FakeMCP",
    "FakeMemory",
    "FakeModel",
    "FakeObservability",
    "FakeRAGPipeline",
    "FakeSearchIndex",
    "FakeVectorStore",
    "MCPAdapter",
    "McpResult",
    "MemoryAdapter",
    "ModelAdapter",
    "ObservabilityAdapter",
    "RAGPipelineAdapter",
    "RagAnswer",
    "SearchIndexAdapter",
    "TraceHit",
    "VectorHit",
    "VectorStoreAdapter",
    "version",
]


def version() -> str:
    """Return the installed ``sectum-ai-adapters`` distribution version.

    Stamped into ``RunResult.adapter_versions`` so an evidence pack attests the
    version of the *adapters* distribution that produced it, not the core CLI's
    (the engineering spec, section 8.2). Falls back to ``0.0.0+unknown`` in an
    uninstalled / editable tree.
    """
    try:
        return _dist_version("sectum-ai-adapters")
    except PackageNotFoundError:  # pragma: no cover - only in an uninstalled tree
        return "0.0.0+unknown"
