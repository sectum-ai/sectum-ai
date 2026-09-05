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
| Embedding provider (Class 2 sweep) | `sentence-transformers` (local), `openai`, `cohere`, `voyage`, `bedrock` (the four hosted opt-in live) | ✅ |
| Long-term / agent memory | `redis` (in CI), `mem0` (opt-in live) | ✅ |
| Full-text search index | `opensearch` | ✅ |
| Application resource API (`app`) | *(live HTTP adapter not yet implemented)* | ✅ |
| Eval / golden set | `langsmith` (opt-in live) | ✅ |
| Backup / snapshot | `s3`, `gcs` (opt-in live) | ✅ |

See [Adapters](adapters.md) for how to configure each backend.

Every family Sectum cannot reach falls back to its in-memory fake, so a run
against an incomplete config still produces a complete-looking result. Which
surfaces were real is not left to the reader to infer: `probe` warns on stderr
about every synthetic surface, and the run records a `surface_provenance` block
(`LIVE` / `SYNTHETIC` per surface) inside the signed evidence, so a third party
reading the pack can tell what the verdicts actually describe. The block is read
off the constructed adapters, so an *omitted* family is recorded as the fake it
resolved to — and it names only the surfaces the run's probes actually drove (an
erasure run: the surfaces it scanned), so a live backend nothing interrogated
cannot make the run look live. Its values are validated on load; a record carrying
anything but `LIVE` / `SYNTHETIC` is refused rather than read as live. (A
misspelled family key — `vector:` for `vector_store:` — no longer reaches this
point: it is rejected at config load, since v0.10.0.)

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
| Persistent memory contamination (8) | memory | Redis (in CI) or mem0 (opt-in live); the fake offline |
| LoRA cross-tenant influence (9) | model | a self-hosted model with per-tenant adapters (HF + PEFT) |
| IKEA-style benign extraction (10) | vector store | any live vector backend |
| GDPR Art. 17 erasure — canary (11) | vector store (+ optional cache / tracing / memory / model / search / eval / backup) | vector always; each extra surface needs its adapter |
| Data-subject erasure — A3 DSR | vector store + cache (+ optional model, tracing, memory, search index) | vector + cache; model / tracing / memory / search index when configured |
| Multi-modal RAG entity-bleed (13) | multi-modal image embedder | offline via the `imagehash-<dim>` sweep (no deps beyond `[multimodal]`), or real CLIP (`[clip]`) — measured by its per-model image-RPR sweep |

## A worked example

A typical multi-tenant RAG product — **pgvector + LangChain + Langfuse + Redis** with
an **OpenAI embedding model**, a **self-hosted vLLM** for generation, and **CrewAI**
agents — runs Classes **1, 2, 3, 4, 6, 7, 8, 10, 11** and the **A3 DSR** check out of
the box (Class 8 against a Redis-backed agent memory), plus **Class 5** (with a GPU)
and **Class 9** (once a per-tenant-LoRA model is configured — the example's serving-only
vLLM covers Class 5 but not Class 9). Every one of the erasure scan's **eight wired
surfaces** now has a live backend too — the search index (**OpenSearch**), the eval set
(**LangSmith Datasets**), and the backup store (**S3**, with **GCS** as a second backend)
were the last three fake-only surfaces. (The remaining hiding place — third-party
subprocessor residue — has no
scanning adapter yet, so it is out of scope, not fake; see the
[Class 11 page](attack-catalog/class-11-erasure.md).)

## Known coverage gaps

- **Some live adapters are opt-in (credential- or endpoint-gated), not run in CI.** The
  eval set (**LangSmith Datasets**) and backup (**S3** / **GCS**) adapters — like the
  hosted vector stores (Pinecone, Azure AI Search) — are exercised by opt-in live tests
  that skip without credentials, so their contract is verified offline against a mock and
  live against a real backend on demand (S3 against a local MinIO, GCS against a local
  fake-gcs-server). The search index
  (**OpenSearch**), agent memory (**Redis**), and the self-hosted vector stores run
  against docker-compose backends in CI every push. The agent-memory surface also has a
  live **mem0** backend (opt-in, since mem0 needs an embedder); a Zep adapter can follow
  the same seam.
- **The model probes need a self-hosted model.** Classes 5 (KV timing) and 9 (LoRA)
  require a model adapter that exposes latency and per-tenant adapters — vLLM, TGI, or
  HuggingFace + PEFT. A stack that reaches generation only through a hosted API
  (OpenAI / Anthropic) cannot run them as-is; the Class 2 embedding sweep still does.
- **Embedding providers**: the Class 2 rate sweep ships `sentence-transformers`
  (local, BYOC-safe) plus the hosted `openai`, `cohere`, `voyage`, and `bedrock`
  (all opt-in live and key/region-gated). The Bedrock adapter covers both invoke-body
  shapes: the **Titan** family (`amazon.titan-embed-text-v2:0`), which embeds one text per
  request, and **Cohere-on-Bedrock** (`cohere.embed-*`), which batches up to 96.

## What a run delivers

Every run produces a portable, tamper-evident deliverable — the report you hand to a
security reviewer, auditor, or DPO, not a hand-written summary:

| Output | Command | For |
|---|---|---|
| Signed `evidence.json` | `report` (`--tsa <url> --rekor` to anchor) | Independent verification via `sectum-ai verify` |
| DPO / executive **PDF** audit pack | `report` (`--pdf-engine weasyprint` optional; `reportlab` is the default) | Humans — DPO, security lead, buyer |
| **SARIF** 2.1.0 | `probe --output sarif` | The repository's Security → Code-scanning tab |
| **OSCAL** 1.1.x assessment-results | `probe --output oscal` | GRC platforms, control-mapped |
| Portable **`run-pack.zip`** | `pack` | One self-verifying bundle for the auditor |

Named suites bundle the classes for a specific buyer: `--suite soc2-tenant-isolation`
(the direct cross-tenant checks — SOC 2 CC6.1 / CC6.6 / CC6.7, ISO 27001) and
`--suite owasp-llm08` (every adversarial probe in the default CLI suite; Class 13's
multi-modal bleed is measured by its own image-embedding sweep, not this run). See
[SKUs and suites](skus.md).
