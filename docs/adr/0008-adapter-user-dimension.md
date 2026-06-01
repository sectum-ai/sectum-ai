# ADR-0008 - The adapter SDK carries an optional user dimension

## Status

Accepted (2026-05-21).

## Context

ADR-0006 generalized the isolation boundary from a tenant to a *principal* (a
tenant, or a user within a tenant). User-level detection and the Class 1/2 probe
planning then landed: a probe plans cross-user steps and the detection pipeline
flags a marker owned by one user surfacing in another user's session.

But the adapter SDK (the engineering spec, section 11) stayed tenant-keyed -
every method took `tenant: UUID` and nothing finer - and the runner dropped
`ProbeStep.actor_user_id` when it called an adapter. So a user-aware probe could
*plan* a cross-user fetch and *detect* a cross-user leak, yet no adapter could be
asked to scope a read to a user. The consequence: the negative case - a store
that *correctly* isolates users does **not** leak across them - could not be
verified end to end. Only the positive case (an unscoped store leaks) was
reachable, because detection alone surfaces it.

## Decision

Give the adapter reads an optional, keyword-only `user: UUID | None = None`,
thread `ProbeStep.actor_user_id` through the runner into those calls, and add
`CorpusDocument.owner_user_id` so a store can decide what a user may retrieve.
The change lands family by family; `VectorStoreAdapter.query`/`fetch` are first.

- **`user=None` is the tenant-level scope and is byte-identical to prior
  behavior.** Every existing positional call and the entire no-users path are
  unchanged - the parameter is keyword-only with a default.
- A fake reports a new `USER_SCOPED` capability and, with its `user_scoped` knob
  on, isolates by user: a read carrying a `user` returns only that user's own
  documents plus the tenant-shared ones (`owner_user_id is None`). With the knob
  off it scopes by tenant alone and *ignores* `user`, surfacing another user's
  document - the cross-user leak (verified default-deny, ADR-0006).
- A pivot document inherits its planted marker's owner user; filler documents
  (and every document in a scenario that declares no users) are tenant-level.
- **Live adapters accept `user` for interface conformance but do not yet enforce
  per-user scoping** (a per-backend follow-on), so they do **not** report
  `USER_SCOPED`. Capability honesty - already the codebase's pattern - keeps the
  gap explicit rather than silently pretending to isolate users.

Rejected: replacing `tenant: UUID` with a `Principal` value object across every
adapter method. That is a wide breaking change to all adapters, the live
backends, the runner, and every call site, for no behavioral gain over an
additive optional parameter.

## Consequences

- The negative case is now testable end to end: a `user_scoped` fake yields zero
  cross-user findings for the Class 1 probe, while the same store scoped by
  tenant alone yields the leak.
- `CorpusDocument.owner_user_id` is additive (default `None`) and is **not** part
  of `scenario_hash` or `manifest_hash` - those hash the scenario and the
  markers, not the corpus documents - so no evidence-pack digest shifts
  (ADR-0007).
- The user dimension arrives family by family: vector first; cache, memory,
  model, and RAG follow alongside the probes that exercise them. Until a family
  is converted its reads remain tenant-keyed.
- Live per-backend user isolation (a pgvector user column, a Pinecone per-user
  namespace, and so on) is a documented follow-on. The fakes carry the behavior
  the probe suite exercises in CI, consistent with the "fakes are the test
  substrate; live adapters are mock + opt-in" stance (the engineering spec,
  sections 11 and 15).

## Update (2026-05-21) — generalization complete

The user dimension has landed across every adapter family a probe exercises:
**vector, cache, memory, MCP, and model**. Each fake gained a `user_scoped` knob
and reports `USER_SCOPED`; the runner threads `ProbeStep.actor_user_id` into all
of those calls; and the probes are principal-aware end to end - Class 1
(tenant-boundary), Class 2 (flagship rag-entity-bleed), Class 3 (rag-poisoning),
Class 4 (semantic-cache), Class 6 (embedding-inversion), Class 7
(agent-tool-hijack), Class 8 (memory-contamination), Class 9 (lora-cross-tenant),
and Class 10 (ikea-extraction) each verify user isolation with a positive
(tenant-only store leaks) and a negative (user-scoped store does not) case.

The **RAG pipeline** family (`RAGPipelineAdapter.ask`) was *not* given a user
dimension at the time of this decision. `ModelAdapter.measure_latency` likewise
stays tenant-level - the KV-cache timing side channel (Class 5) is shared
infrastructure, not a per-principal scope. The live adapters still accept `user`
for conformance without yet enforcing it (the per-backend follow-on above).

> **Update (2026-06-01):** the original rationale here ("no probe issues a
> `rag.ask` step") is now out of date - the `rag-pipeline-bleed` probe (Class 2,
> RAG-pipeline end) issues a per-principal `rag.ask` step with `actor_user_id`
> set, but `RAGPipelineAdapter.ask` still takes no `user` argument, so the runner
> drops the user at that boundary. The RAG family's user dimension is therefore
> *unverified* rather than *unneeded*; threading `user` through `ask` (with a
> user-scoped fake) remains the open follow-on.
