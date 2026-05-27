# IKEA-style implicit benign extraction — Class 10

This example reproduces **Attack Class 10**: the Silent Leaks /
IKEA-style implicit extraction (the engineering spec, §7). A
multi-turn benign query strategy from tenant Y incrementally
reconstructs tenant X content via a shared RAG pipeline — **no
prompt injection required**.

## The attack

The 2025 *Silent Leaks* paper (arXiv 2505.15420) demonstrated that
**91% extraction efficiency** and **96% attack success** are
achievable through nothing more than a sequence of benign-looking
queries — no adversarial prompts, no jailbreaks, no special
tooling. The pattern is what the paper calls **IKEA**: ask in
**I**ncremental, **K**nowledge-**E**xtractive, **A**daptive turns,
where each turn pulls one more piece of a foreign tenant's
content into the conversation context.

The probe automates the IKEA loop: from each tenant, it issues a
plan of benign multi-turn queries calibrated to surface the
target tenant's `ENTITY_CANARY` content via the shared RAG
pipeline. Reconstruction is measured by cumulative canary recall
over the turn sequence; a recall above the configured efficiency
threshold is a confirmed Class 10 finding.

This is **OWASP LLM08:2025**, with the unique property that no
single turn is adversarial — defences keyed on per-turn
adversarial detection do not catch it.

## What the demo does

`run.sh` runs the canonical CLI flow end to end against the in-
memory `FakeRAGPipeline` with shared retrieval (the leaky
condition Class 10 is built to catch):

1. **`sectum seed`** provisions four synthetic tenants and their
   canary markers.
2. **`sectum probe --probe ikea-extraction`** runs the multi-turn
   extraction plan from each tenant against every foreign tenant,
   measuring cumulative canary recall per pair. A pair whose
   recall crosses the efficiency threshold is a confirmed
   finding; the probe exits `2` on at least one such pair.
3. **`sectum report`** assembles the tamper-evident evidence pack.
4. **`sectum verify`** independently re-checks the pack.

## Run it

```sh
./run.sh
```

## What the report tells you

Each Class 10 finding carries:

- the owning tenant (X) + the observing tenant (Y)
- the extraction efficiency (cumulative recall across the turn
  sequence)
- the per-turn `evidence_span`s showing the IKEA loop's progression
- the surface (`RAG_PIPELINE`)
- OWASP / ATLAS / NIST control IDs
- a remediation pointer: tenant-scoped retrieval on every turn
  (the per-turn check is the only place the attack can be
  closed), or query-level rate limits that bound the number of
  related queries one session can issue

## What's *not* in this example

- **A real production LLM adversary.** The probe uses a fixed
  IKEA plan; an adaptive attacker (LLM-driven) is what the
  paper's measurements were against. The probe's plan is a
  conservative lower bound on what a real attacker can recover.
- **Multi-session correlation.** The probe runs within a single
  session per tenant pair; a real attacker spreads queries across
  sessions / API keys / time to evade rate limits. That's a
  detection challenge for runtime guardrails, not for Sectum's
  verification layer.
