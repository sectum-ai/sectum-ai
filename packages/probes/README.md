# sectum-ai-probes

The multi-tenant leakage **attack catalog** and leak-detection pipeline for
[Sectum AI](https://github.com/sectum-ai/sectum-ai).

This distribution implements the Class 1–11 and 13 probes — direct tenant-boundary
fetch, the flagship organic entity-bleed RAG (the 95.4% Retrieval-Pivot
finding), adversarial RAG poisoning, semantic-cache contamination, KV-cache
timing, embedding inversion, agent / MCP tool-call hijacking, persistent-memory
contamination, LoRA cross-tenant influence, IKEA-style benign extraction, the
GDPR Article 17 erasure-verification wedge, and multi-modal RAG entity-bleed —
mostly behind a single pluggable `Probe` interface (the Class 5, 11 and A3
probes predate it and are driven directly by the CLI), plus the exact → semantic →
calibrated-judge detection pipeline that turns observations into
manifest-grounded `Finding`s.

```sh
pip install sectum-ai-probes
```

Most users install the umbrella package [`sectum-ai`](https://pypi.org/project/sectum-ai/)
instead, which pulls this in automatically.

- Attack catalog (one page per class): <https://docs.sectum.ai>
- Source: <https://github.com/sectum-ai/sectum-ai>

Apache-2.0.
