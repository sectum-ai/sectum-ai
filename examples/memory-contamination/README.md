# Memory Contamination — persistent cross-tenant memory leakage

This example reproduces **Attack Class 8**: agent / long-term memory carrying
one tenant's content into another tenant's session. It shows how a memory
store that has lost tenant scope serves tenant A's written-once note back to
tenant B on recall.

## The attack

Agents persist memory between sessions — long-term recollections, scratch
notes, summarised context, tool-call results — through a memory store
(framework-native: LangGraph checkpointers, AutoGen memory, CrewAI memory
plugins; framework-agnostic: a vector index used as memory, Mem0, Letta,
Zep). If a memory store does not bind every read and write to the
authenticated caller, the contamination is persistent and pull-based:

- Tenant A writes a note ("remember the customer's account number is …").
- Tenant B starts an unrelated session and asks anything that semantically
  brushes against the note's tokens.
- The store recalls tenant A's entry into tenant B's context window.

This is the SpAIware-class pattern: a memory write by one principal
contaminates every later session that triggers a recall. Unlike a cache
contamination, it survives across runs; unlike a retrieval-pivot bleed, it
needs no shared organic entity — a single write into the wrong scope is
enough.

This is **OWASP LLM08:2025 — Vector and Embedding Weaknesses**, on the
persistent-memory surface (the long-term/agent memory store named in §7
of the [engineering spec](https://github.com/sectum-ai/sectum-ai/blob/main/CLAUDE.md)).

## What the demo does

`run.sh` runs the Class 8 probe end to end:

1. **`sectum-ai seed`** provisions four synthetic tenants and their canary markers.
2. **`sectum-ai probe --probe memory-contamination`** writes each tenant's hard
   canary into its memory as the owning principal (`memory.write`), then from
   every other principal issues a recall query for it (`memory.recall`) against
   a memory store whose tenant boundary has been removed.
3. **`sectum-ai report`** assembles a tamper-evident evidence pack.
4. **`sectum-ai verify`** independently re-checks the pack.

## Run it

```sh
./run.sh
```

Artifacts are written to `out/`.

## What the report tells you

Every cross-tenant recall surfaces a foreign canary, so the probe confirms
a leak on each. The evidence pack itemises every finding the probe
confirmed: the marker's owning tenant, the observing tenant, the leaked
memory text (the recalled note carrying the canary), per-finding control
IDs (OWASP / ATLAS / NIST), and a remediation pointer.

```
ran 1 probe: 24 confirmed cross-tenant findings
```

`sectum-ai probe` exits with code 2 because it confirmed cross-tenant leaks,
and `sectum-ai verify` confirms the evidence pack is intact. The headline
metric is the count of confirmed Class 8 leaks; on a memory store that
binds every read and write to the authenticated principal, the same probe
yields zero findings.

## What's *not* in this example

The probe exercises the in-memory `FakeMemory` adapter with its
`shared_memory` knob switched on — a deliberately broken substrate that
collapses every tenant into one keyspace. Real engagements point the same
probe at the customer's actual long-term-memory store via a `MemoryAdapter`
implementation. Two live memory adapters ship — Redis and Mem0 (see
[adapters](../../docs/adapters.md)); the remaining agent-framework memory plugins
(LangGraph checkpointers, AutoGen memory, CrewAI memory, Letta, Zep) are future
work — the Class 8 probe and `MemoryAdapter` interface are the SDK piece those
adapters plug into.
