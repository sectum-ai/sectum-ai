# sectum-ai-adapters

The adapter SDK for [Sectum AI](https://github.com/sectum-ai/sectum-ai) —
the connectors that point the marker substrate and the attack catalog at real
systems.

Every adapter family ships a deterministic in-memory `fake` (used by the unit
suite and offline runs) plus live backends, each behind a capability-reporting
interface so probes can declare what they require:

- **Vector stores** — pgvector, Chroma, Weaviate, Qdrant, Pinecone, Milvus, OpenSearch, Azure AI Search
- **RAG pipelines** — generic HTTP, LangChain
- **Observability** — Langfuse, LangSmith, Phoenix, Helicone, Datadog APM, generic OpenTelemetry
- **Agents** — LangGraph, AutoGen, CrewAI, OpenAI Assistants, Anthropic tool-use, generic HTTP
- **MCP** — stdio + streamable-HTTP Model Context Protocol clients
- **Cache** — Redis
- **Model** — HuggingFace + PEFT LoRA, vLLM (serving-only)

```sh
pip install sectum-ai-adapters
# live backends are opt-in extras, e.g.:
pip install "sectum-ai-adapters[pgvector]"   # or [redis], [langgraph], [anthropic-tooluse], ...
```

Most users install the umbrella package [`sectum-ai`](https://pypi.org/project/sectum-ai/)
instead, which pulls this in automatically.

- Adapter configuration reference: <https://docs.sectum.ai>
- Source: <https://github.com/sectum-ai/sectum-ai>

Apache-2.0.
