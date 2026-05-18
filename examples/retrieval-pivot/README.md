# Retrieval Pivot — benign cross-tenant leakage on a shared vector index

This example reproduces **Attack Class 2**, the flagship probe: the *organic
entity-bleed* Retrieval Pivot. It shows how ordinary, non-adversarial queries —
with no prompt injection — surface one tenant's documents to another when a
multi-tenant RAG system retrieves from a shared vector index.

## The attack

Multi-tenant AI systems claim that tenant A's data cannot reach tenant B. A
shared vector index quietly breaks that claim. Tenants naturally have
overlapping organic entities — a shared vendor, a compliance term such as
SOC 2, a person's name, a monetary amount, a date. A benign query from tenant B
that names one of those entities retrieves the *nearest* documents regardless of
owner, so tenant A's documents come back in tenant B's session.

This is **OWASP LLM08:2025 — Vector and Embedding Weaknesses**. The *Retrieval
Pivot Attacks in Hybrid RAG* research (2026) found that 95.4% of benign
cross-tenant queries leaked this way, and that stronger embedding models leaked
*more*.

## What the demo does

`run.sh` runs the full Sectum AI workflow:

1. **`sectum seed`** provisions four synthetic tenants (Acme, Globex, Initech,
   Hooli), generates their corpora, and plants canary markers. Every tenant
   owns one *pivot document* per marker — a document that names a shared
   organic entity and carries the canary in the same text.
2. **`sectum probe`** runs the probe suite against the demo stack: a single
   shared vector index with no tenant scoping. Class 2 issues one benign query
   per shared entity from each tenant's session.
3. **`sectum report`** assembles a tamper-evident evidence pack (JSON + PDF).
4. **`sectum verify`** independently re-checks the pack's integrity.

## Run it

```sh
./run.sh
```

Artifacts are written to `out/`.

## Expected result

The demo stack is a single shared index — the worst case, zero tenant
isolation. Every benign cross-tenant query retrieves a foreign canary, so the
headline **Retrieval-Pivot Rate is 100%**:

```
ran 5 probes: 225 confirmed cross-tenant findings
retrieval-pivot rate: 100%
```

`sectum probe` exits with code 2 because it confirmed cross-tenant leaks, and
`sectum verify` confirms the evidence pack is intact.

The Retrieval-Pivot Rate measures the *stack under test*, not the tool. Point
the vector-store adapter at a properly isolated store — one namespace per
tenant — and the same probe reports **0%**. That contrast is the evidence: the
rate is a property of the configuration, and Sectum AI proves which one is
running.
