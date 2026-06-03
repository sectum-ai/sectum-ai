# IKEA-style implicit benign extraction — Class 10

This example reproduces **Attack Class 10**: the Silent Leaks /
IKEA-style implicit extraction (the engineering spec, §7). A
multi-turn benign query sequence from tenant Y surfaces tenant X
content from a shared vector index — **no prompt injection
required**.

## The attack

The 2025 *Silent Leaks* paper (arXiv 2505.15420) demonstrated that
**91% extraction efficiency** and **96% attack success** are
achievable through nothing more than a sequence of benign-looking
queries — no adversarial prompts, no jailbreaks, no special
tooling. The pattern is what the paper calls **IKEA**: ask in
**I**ncremental, **K**nowledge-**E**xtractive, **A**daptive turns,
where each turn pulls one more piece of a foreign tenant's
content into the conversation context.

The probe automates the IKEA pattern: for each shared entity, from
every tenant it issues a fixed sequence of benign follow-up turns
("what do we know about {entity}", "tell me more about {entity}",
"summarise every record involving {entity}") against the shared
vector index. Detection flags any turn whose retrieved context
surfaces a *foreign* principal's canary — that turn is the
confirmed cross-tenant extraction.

This is **OWASP LLM08:2025**, with the unique property that no
single turn is adversarial — defences keyed on per-turn
adversarial detection do not catch it.

## What the demo does

`run.sh` runs the canonical CLI flow end to end against the demo
substrate's shared vector store (the leaky condition Class 10 is
built to catch):

1. **`sectum-ai seed`** provisions four synthetic tenants and their
   canary markers.
2. **`sectum-ai probe --probe ikea-extraction`** runs the benign
   multi-turn sequence from every tenant for each shared entity. A
   finding lands on any turn whose retrieved context carries a
   canary owned by a *different* principal; the probe exits `2`
   when at least one turn does.
3. **`sectum-ai report`** assembles the tamper-evident evidence pack.
4. **`sectum-ai verify`** independently re-checks the pack.

## Run it

```sh
./run.sh
```

## What the report tells you

Each Class 10 finding carries:

- the owning principal (tenant X) + the observing principal (tenant Y)
- the `evidence_span` — the retrieved snippet that surfaced the
  foreign canary on that turn
- the `marker_id`, tying the leak back to the ground-truth manifest
- the surface (`VECTOR_DB`)
- OWASP / ATLAS / NIST control IDs
- a remediation pointer: tenant-scoped retrieval on every turn
  (the retrieval boundary is the only place the attack can be
  closed), or query-level rate limits that bound the number of
  related queries one session can issue

## What's *not* in this example

- **A real production LLM adversary.** The probe runs a fixed
  three-turn sequence; an adaptive attacker (LLM-driven) is what
  the paper's measurements were against. The fixed sequence is a
  floor, not a measurement — a single foreign-canary hit already
  confirms the leak, and the verdict doesn't depend on how much an
  adaptive attacker could go on to reconstruct.
- **Multi-session correlation.** The probe runs within a single
  session per tenant pair; a real attacker spreads queries across
  sessions / API keys / time to evade rate limits. That's a
  detection challenge for runtime guardrails, not for Sectum's
  verification layer.
