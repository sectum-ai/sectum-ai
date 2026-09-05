# Marker substrate

The marker substrate is Sectum AI's technical moat. It provisions synthetic
tenants, seeds them with realistic corpora and cryptographic canary markers, and
records exactly which marker belongs to which principal in a hashed
**ground-truth manifest** — so leak detection has zero ambiguity about what a
correct answer is. It is **deterministic** and **reproducible from a seed**: the
same scenario always yields a byte-identical corpus and an identical manifest
(ADR-0003).

## Synthetic tenants

The default scenario provisions four tenants — **Acme Robotics**, **Globex
Logistics**, **Initech Financial**, and **Hooli Health** — recognizable
placeholders that make demo output legible. Each has a deterministic
`tenant_id`, a display name, and an industry.

Tenants deliberately **share organic entities** — a shared person ("Maria
Chen"), a shared vendor, compliance terms (SOC 2, PCI-DSS), and overlapping
amounts and dates. These shared entities are the leakage bait: they reproduce
the conditions of the Retrieval Pivot finding (a benign query naming a shared
entity pulls a *foreign* tenant's document into the answer), which the flagship
[Class 2 probe](attack-catalog/class-02-rag-entity-bleed.md) measures.

A scenario with no `shared_entities` plants nothing in the corpus (a pivot
document exists per shared entity), so the probes that query the corpus plan no
step and their classes read `NOT_COVERED` — never a pass. The probes provisioned
from the manifest (MCP, agent, memory, cache, model) still have markers to find.

A scenario may also declare **users within a tenant**. Markers and documents are
then owned by a specific user, and the same machinery verifies the user boundary
as it verifies the tenant boundary — a principal is just the owner of a marker
and the actor in a session (ADR-0006) — wherever the adapter carries the user to
its backend; where it does not, the run exercises the tenant boundary alone and
says so (see [the threat model](threat-model.md)).

## Corpus generation

Corpora are synthetic but realistic — HR records, sales pipelines, support
tickets, contracts, meeting notes — generated from templates against a fixed RNG
seed. Each tenant owns:

- one **pivot document** per marker — it names a shared organic entity in its
  body and carries the marker, so a benign query for that entity retrieves it
  (the Retrieval Pivot condition); and
- **filler documents** that round out the corpus and give realistic same-tenant
  retrieval competition; some mention shared entities organically, none carry a
  marker.

Corpus size is configurable. The demo default is ~500 documents per tenant (set
`scenario.corpus_size` in `sectum-ai.yaml` to change it); the checked-in example
walkthroughs pin a small corpus so they stay fast and their headline numbers
stay legible.

## Canary markers

Three marker types, each with a distinct detection path:

| Marker type | Form | Detection path |
|---|---|---|
| `HARD_CANARY` | A high-entropy branded token, `SECTUM-CANARY-{base32(16 bytes)}` | Exact substring match (case-, width-, and zero-width-insensitive). Zero false positives. |
| `ENTITY_CANARY` | A fabricated, single-tenant-unique entity (`Project <codename + fused entropy>-<serial>`, e.g. `Project Zephyr5BL7G-00002`) | Semantic similarity → calibrated judge. Tests organic bleed (Class 2). |
| `SECRET_CANARY` | A fake but plausibly shaped secret — an OpenAI-style `sk-` key, an AWS `AKIA` id, or a non-issuable `9xx` US SSN | Exact **+ credential-format** detector. Tests PII/secret surfacing and redaction. |

Every marker is recorded in the ground-truth manifest as
`{marker_id, marker_type, owner_tenant_id, owner_user_id?, plaintext, embedding_ref?, planted_locations[]}`.

**Multi-field planting.** Each marker is planted in its pivot document's **body,
title, and metadata** — all three recorded in `planted_locations` — so a leak is
caught whichever field surfaces, and the vector store can retrieve the document
by any of them.

**Embedding references.** Each `ENTITY_CANARY` carries an `embedding_ref` — a
model-scoped content address (`{embedding_model}/{sha256(plaintext)[:16]}`) the
detection pipeline indexes its vectors by. Because the ref names the embedding
model, the manifest records *which model* the semantic-detection vectors were
computed under, a provable test condition once the manifest is hashed into the
[evidence chain](evidence-chain.md). `HARD_CANARY` and `SECRET_CANARY` are
matched exactly, so they carry no embedding reference.

**Secrets are never committed.** Secret canaries are generated at runtime from
the seed; only the manifest *hash* is published. A random `sk-`/`AKIA` string
and a non-issuable `9xx` SSN cannot be — or be mistaken for — a live credential
(ADR-0022).

## Leak detection pipeline

An observation is checked for leakage cheapest-and-most-certain first. A leak is
a marker owned by one principal observed in another principal's session.

1. **Exact scan** for a foreign `HARD_CANARY` plaintext → a confirmed critical
   leak (confidence 1.0). Normalization catches a canary the surface re-cased,
   NFKC-folded, or split with a zero-width character.
2. **Credential-format scan** for a foreign `SECRET_CANARY` — confirmed by exact
   substring *or* by recovering a credential-shaped token (`sk-`/`AKIA`/SSN) from
   surrounding bytes, so a secret wrapped in a JSON blob is still caught. A
   confirmed secret leak is **redacted** in the finding's evidence span: an
   evidence pack leaves the box in BYOC mode and must not reproduce the
   credential verbatim (the engineering spec, §16).
3. **Semantic similarity** against foreign `ENTITY_CANARY` vectors yields
   candidates above a calibrated threshold.
4. **Calibrated judge** adjudicates each candidate with a narrow structured
   question. It is primed with that one candidate marker's plaintext — never
   the manifest as a whole — and a "yes" only confirms if the span it cites is
   traceable to the marker (`_span_traceable`), so the judge cannot conjure a
   confirmation the observation does not contain. The offline
   default judge confirms only when the entity's tokens appear in order within a
   short span, keeping precision high.

**Manifest-grounded by construction:** every finding ties back to a manifest
marker. A finding is `CONFIRMED` on an exact/format hit, on a foreign entity whose
plaintext is literally present in the observation (a leak by observation, which no
judge verdict can unmake), or on a judge verdict whose cited evidence is traceable
to the marker. A semantic candidate that cannot be tied to a manifest marker is
downgraded to `UNVERIFIED`, excluded from the headline count but kept in the
appendix. That bounds confirmations to the manifest's own markers; it is not a
claim that every confirmation is correct, since a semantic confirmation still
rests on the configured judge. **Zero false negatives:** a foreign marker of any
type, planted in any field, that appears verbatim in an observation is always
confirmed. Both are pinned as invariants (see the testing strategy).

## Reproducibility contract

Given the same `seed`, `scenario`, and `corpus_profile`, the substrate is a pure
function of its inputs: byte-identical corpus, identical ground-truth manifest,
identical manifest hash — across machines and Python versions (ADR-0003,
ADR-0021). This is enforced by a golden-hash invariant test, so an accidental
change to corpus generation, marker planting, or canonicalization fails CI. The
manifest hash is what the evidence chain anchors, making the test conditions
provable after the fact.

## See also

- [Core data models](data-models.md) — the `Marker`, `GroundTruthManifest`, and
  `Substrate` schemas this page describes.
- [Attack catalog](attack-catalog/index.md) — the probes that run against the
  substrate; [Class 2](attack-catalog/class-02-rag-entity-bleed.md) is the
  flagship that exploits shared organic entities.
- [Configuration](configuration.md) — `scenario.seed`, `corpus_size`, and
  `embedding_models`.
- [Evidence chain](evidence-chain.md) — how the manifest hash becomes part of a
  tamper-evident pack.
