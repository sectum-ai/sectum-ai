# ADR-0005 - Examples are named for the attack class, not for a metric value

## Status

Accepted (2026-05-18).

## Context

The engineering spec (section 12) sketches the example directory for the
flagship Class 2 walkthrough as `examples/95-percent-leakage/`, echoing the
research finding that 95.4% of benign cross-tenant queries leaked in a hybrid
RAG study.

The Retrieval-Pivot Rate, however, is a property of the *stack under test*, not
a fixed number. Sectum AI's demo stack is a single shared vector index with no
tenant scoping — the worst case — and honestly reports a 100% rate; an isolated
per-tenant store reports 0%. Encoding one stack's measured percentage into an
artifact name would misrepresent a stack-dependent metric and sits poorly with
the spec's positioning rules (section 20: precise, anti-hype).

## Decision

Examples are named for the attack class they demonstrate, not for any metric
value. The flagship Class 2 example ships as `examples/retrieval-pivot/`; the
Class 11 wedge example ships as `examples/erasure-attestation/`.

## Consequences

- Example names stay accurate regardless of what a given stack measures.
- This is a deliberate deviation from the spec's section 12 directory sketch,
  recorded here per the spec's operating rule to flag deviations (section 1.2).
- The Retrieval-Pivot Rate is reported as a measured result inside the example
  and its evidence pack, where it belongs, rather than baked into a path.
