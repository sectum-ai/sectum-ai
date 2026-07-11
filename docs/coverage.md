# Coverage: what Sectum verifies today

Sectum verifies **multi-tenant isolation across the AI surfaces** of a RAG / LLM /
agent application. A run exercises the probe catalog against the adapters you
configure, so what is *runnable* is the intersection of two things: the **backends**
Sectum speaks to, and the **probes** each surface unlocks. This page is that map —
useful for scoping a run (or an engagement) and for knowing exactly what a
`sectum-ai probe` will cover against your stack, versus what falls back to the
synthetic substrate.

## Adapter coverage (live backends)

| Surface (family) | Live backends (`kind:`) | Fake (offline) |
|---|---|---|
| Vector store | `pgvector`, `qdrant`, `chroma`, `weaviate`, `pinecone`, `milvus`, `opensearch`, `azure-search` | ✅ |
| RAG pipeline | `langchain`, `http` | ✅ |
| Model (inference) | `huggingface` (PEFT LoRA), `vllm`, `tgi` — all self-hosted | ✅ |
| Observability / tracing | `langfuse`, `langsmith`, `phoenix`, `otel`, `helicone`, `datadog` | ✅ |
| Semantic / application cache | `redis` | ✅ |
| Agent framework | `langgraph`, `crewai`, `autogen`, `openai-assistants`, `anthropic-tooluse`, `http` | ✅ |
| MCP server | `stdio`, `http` | ✅ |
| Embedding provider (Class 2 sweep) | `openai`, `sentence-transformers` | ✅ |
| Long-term / agent memory | `redis` | ✅ |
| Full-text search index | `opensearch` | ✅ |
| Eval / golden set | — *(fake only)* | ✅ |
| Backup / snapshot | — *(fake only)* | ✅ |

See [Adapters](adapters.md) for how to configure each backend.

## Probe → the surface it needs

| Probe (class) | Requires | Runs when your stack has |
|---|---|---|
| Direct tenant-boundary fetch (1) | vector store | any live vector backend |
| RAG entity-bleed (2) | vector store | any live vector backend |
| RAG pipeline-bleed (2) | RAG pipeline | LangChain (or an HTTP RAG endpoint) |
| Adversarial RAG poisoning (3) | vector store | any live vector backend |
| Semantic-cache contamination (4) | cache | Redis |
| KV-cache timing side channel (5) | model | a self-hosted model (vLLM/TGI/HF) — real signal needs a GPU |
| Embedding inversion (6) | vector store | any live vector backend |
| Agent tool-call hijack (7) | MCP | an MCP server (`stdio`/`http`) |
| Agent-framework hijack (7) | agent | LangGraph / CrewAI / AutoGen / OpenAI-Assistants / Anthropic-tooluse |
| Persistent memory contamination (8) | memory | Redis (or the fake, offline) |
| LoRA cross-tenant influence (9) | model | a self-hosted model with per-tenant adapters (HF + PEFT) |
| IKEA-style benign extraction (10) | vector store | any live vector backend |
| GDPR Art. 17 erasure — canary (11) | vector store (+ optional cache / tracing / memory / model / search / eval / backup) | vector always; each extra surface needs its adapter |
| Data-subject erasure — A3 DSR | vector store + cache (+ optional model, tracing, memory, search index) | vector + cache; model / tracing / memory / search index when configured |

## A worked example

A typical multi-tenant RAG product — **pgvector + LangChain + Langfuse + Redis** with
an **OpenAI embedding model**, a **self-hosted vLLM** for generation, and **CrewAI**
agents — runs Classes **1, 2, 3, 4, 6, 7, 8, 10, 11** and the **A3 DSR** check out of
the box (Class 8 against a Redis-backed agent memory), plus **Class 5** (with a GPU)
and **Class 9** (with per-tenant LoRA) — so no probe class falls back to the synthetic
substrate for this stack. Every one of the erasure scan's ten "hiding places" now has a
live backend too — the search index (**OpenSearch**), the eval set (**LangSmith
Datasets**), and the backup store (**S3**) were the last three fake-only surfaces.

## Known coverage gaps

- **Some live adapters are opt-in (credential- or endpoint-gated), not run in CI.** The
  eval set (**LangSmith Datasets**) and backup (**S3**) adapters — like the hosted
  vector stores (Pinecone, Azure AI Search) — are exercised by opt-in live tests that
  skip without credentials, so their contract is verified offline against a mock and
  live against a real backend on demand (S3 against a local MinIO). The search index
  (**OpenSearch**), agent memory (**Redis**), and the self-hosted vector stores run
  against docker-compose backends in CI every push. A mem0 / Zep memory adapter can
  follow the same seam.
- **The model probes need a self-hosted model.** Classes 5 (KV timing) and 9 (LoRA)
  require a model adapter that exposes latency and per-tenant adapters — vLLM, TGI, or
  HuggingFace + PEFT. A stack that reaches generation only through a hosted API
  (OpenAI / Anthropic) cannot run them as-is; the Class 2 embedding sweep still does.
- **Embedding providers**: the Class 2 rate sweep ships `openai` and
  `sentence-transformers`. Cohere / Voyage / Bedrock embeddings are not wired yet.

## What a run delivers

Every run produces a portable, tamper-evident deliverable — the report you hand to a
security reviewer, auditor, or DPO, not a hand-written summary:

| Output | Command | For |
|---|---|---|
| Signed `evidence.json` | `report` (`--tsa --rekor` to anchor) | Independent verification via `sectum-ai verify` |
| DPO / executive **PDF** audit pack | `report --pdf-engine weasyprint` | Humans — DPO, security lead, buyer |
| **SARIF** 2.1.0 | `probe --output sarif` | The repository's Security → Code-scanning tab |
| **OSCAL** 1.1.x assessment-results | `probe --output oscal` | GRC platforms, control-mapped |
| Portable **`run-pack.zip`** | `pack` | One self-verifying bundle for the auditor |

Named suites bundle the classes for a specific buyer: `--suite soc2-tenant-isolation`
(the direct cross-tenant checks — SOC 2 CC6.1 / CC6.6 / CC6.7, ISO 27001) and
`--suite owasp-llm08` (the full adversarial catalog). See [SKUs and suites](skus.md).
