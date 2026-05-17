"""Sectum AI adapters: connectors to vector stores, RAG, observability, agents, MCP, and caches.

This is the ``sectum.adapters`` namespace package (the engineering spec, section 11).
"""

from sectum.adapters.base import (
    Adapter,
    AdapterFamily,
    AdapterRegistry,
    AgentAdapter,
    AgentResult,
    CacheAdapter,
    Capability,
    MCPAdapter,
    McpResult,
    ObservabilityAdapter,
    RagAnswer,
    RAGPipelineAdapter,
    TraceHit,
    VectorHit,
    VectorStoreAdapter,
)

__all__ = [
    "Adapter",
    "AdapterFamily",
    "AdapterRegistry",
    "AgentAdapter",
    "AgentResult",
    "CacheAdapter",
    "Capability",
    "MCPAdapter",
    "McpResult",
    "ObservabilityAdapter",
    "RAGPipelineAdapter",
    "RagAnswer",
    "TraceHit",
    "VectorHit",
    "VectorStoreAdapter",
]
