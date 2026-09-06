# ADR-0022: marker-substrate depth — embedding refs, multi-field planting, secret shapes

- Status: Accepted
- Date: 2026-06-03
- Deciders: Dmitry Maranik

## Context

The marker substrate is the moat (the engineering spec, section 1.3). Section 6.3
specifies more than the first cut shipped:

- the ground-truth manifest records an `embedding_ref` per marker;
- markers are planted "in document bodies, document metadata, and ... titles", not
  the body alone;
- a `SECRET_CANARY` is "a fake but plausible secret (API-key-shaped string, fake
  SSN-shaped pattern)" detected by "exact + format detector" — a path distinct
  from `HARD_CANARY`'s plain exact match.

The earlier substrate populated none of these: `embedding_ref` was always `None`,
every marker was planted in the body only, and `SECRET_CANARY` shared
`HARD_CANARY`'s exact scan with a branded `SECTUM-SECRET-` prefix. This ADR
records the decisions made closing that gap.

## Decision

**1. `embedding_ref` is a model-scoped content address, populated for ENTITY
canaries only.** ENTITY canaries are the sole type matched semantically, so they
are the only markers with a stored embedding to reference; HARD and SECRET stay
`None`. The ref is `"{model}/{sha256(plaintext)[:16]}"`, where `model` is the
scenario's first declared embedding model (or the offline default). The detection
pipeline indexes its entity vectors by this ref and reads them back through it, so
the *attested test condition* — which model embedded the entity — is bound into
the manifest hash and provable after the fact (the spec, section 8).

**2. Each marker is planted in its pivot document's body, title, and metadata.**
All three `planted_locations` are recorded, and the in-memory vector store searches
all three fields, so a leak is caught whichever field surfaces and a query naming a
marker or entity in any field retrieves the document. The marker still rides in the
body, so body-scoped detection is unchanged; title/metadata planting is additive.

**3. `SECRET_CANARY` takes realistic shapes and a dedicated format detector.** The
substrate plants an OpenAI-style `sk-` key, an AWS `AKIA` access-key id, and a US
SSN shape whose `9xx` area the SSA never issues — rotated across tenants so the
default scenario exercises all three. Detection moves SECRET out of the HARD exact
scan into a `_secret_format` pass that confirms a foreign secret by exact substring
*or* by recovering a credential-shaped token from surrounding bytes (e.g. a key
embedded in a JSON blob). It confirms only against a manifest marker, so the
zero-false-positive invariant holds; it always includes the plain-substring test,
so it can never miss what the old exact path caught (zero false negatives). A third
arm, added later, recovers the marker's tokens contiguous and in order: the two
branches above fail *together* on a secret whose hyphens the surface re-rendered
(the format patterns need the ASCII hyphen too), and the exact and semantic tiers
already carried that arm.

**Secrets are never committed.** Secret plaintexts are generated at runtime from
the seed; only the manifest *hash* is published, and the checked-in sample packs
carry no secret value. A non-issuable `9xx` SSN and random `sk-`/`AKIA` strings
cannot be, or be mistaken for, a live credential, and nothing in the repository
trips secret scanning.

**Demo corpus default is ~500 documents/tenant** (the spec, section 6.2). Tests and
the checked-in example samples pin a small corpus (24) — the flagship
retrieval-pivot showcase reads better small and keeps a high Retrieval-Pivot Rate —
while a default `sectum-ai seed` produces the realistic demo scale.

## Consequences

- The manifest hash changes (embedding refs, multi-field planting, new secret
  shapes), so the reproducibility golden hash and the committed sample packs are
  regenerated in the same change. No `sectum_ai.spec` model field changes, so the
  committed JSON Schemas and `SCHEMA_VERSION` are untouched.
- New invariants are pinned: `embedding_ref` population and model-scoping, planting
  in all three fields, the SECRET format detector's three shapes, zero-FP for a
  secret-shaped non-marker, and a zero-false-negative test asserting every marker
  type and every planted field is detected when it surfaces cross-tenant.
- A live embedding provider makes the entity `embedding_ref` name the real model;
  the deterministic offline default keeps tests and samples reproducible.
