# ADR-0009 - ATLAS technique IDs are validated against the live MITRE catalog before each release

## Status

Accepted (2026-05-23).

## Context

Every probe declares a tuple of MITRE ATLAS technique IDs
(`atlas_techniques: tuple[str, ...]`); every `Finding` is stamped with them and
they land in `evidence.json`, the audit-pack PDF (the per-finding `[ATLAS …]`
suffix), and the auditor's eye. **Wrong IDs ship as wrong evidence**, and
silently:

- An ID that the catalog has renamed or retired looks valid to anyone reading
  the code, but a real auditor checking against
  [atlas.mitre.org](https://atlas.mitre.org) will see a mismatch.
- A typo (`AML.TOO24` vs `AML.T0024`) passes mypy and ruff. There is no
  natural type-system guard against an ID typo.
- A technique that was a *defensible* fit at one release may have been
  superseded by a better, more specific technique added to the catalog later
  (e.g., the catalog gained `AML.T0053` LLM Plugin Compromise and
  `AML.T0020`-family poisoning techniques that fit Class 7 / Class 3 more
  precisely than the generic `AML.T0024` exfiltration).

The May 2026 review (the work that produced PR #8) confirmed three concrete
ID additions: Class 3 rag-poisoning gained `AML.T0020` (Poison Training
Data), Class 7 agent-tool-hijack gained `AML.T0053` (LLM Plugin
Compromise), and Class 9 lora-cross-tenant gained `AML.T0024.000` (Infer
Training Data Membership). That review was ad-hoc; this ADR turns it into a
release-gate process.

## Decision

Before tagging a release, the maintainer **re-validates every probe's ATLAS
IDs against the current MITRE ATLAS catalog** using the MISP galaxy mirror
as the canonical machine-readable source:

```
https://raw.githubusercontent.com/MISP/misp-galaxy/main/clusters/mitre-atlas-attack-pattern.json
```

The validation is a three-step sweep:

1. **Existence.** Every `AML.T*` ID assigned anywhere in the probe catalog
   must appear in the mirror, with a canonical name unchanged from the
   release the ID was first added in. Any retired or renamed ID is a
   release blocker.
2. **Fit.** A short pass per probe (one paragraph in the PR description)
   re-states why each ID is the right fit for the probe's attack class.
   Any newly-added catalog technique that fits a probe better must be
   considered and either added or explicitly rejected with a reason.
3. **Source-of-truth comment.** The per-class rationale for non-obvious
   assignments lives as a one-line comment above each `atlas_techniques`
   tuple in the probe source (see e.g.
   `packages/probes/src/sectum_ai/probes/rag_poisoning/probe.py`); the
   per-class attack-catalog doc (`docs/attack-catalog/class-NN-*.md`)
   surfaces the same IDs in its header. Both stay in sync at every
   re-validation.

The MISP mirror is preferred over scraping `atlas.mitre.org` directly: it
is structured JSON, versioned in git, easy to diff between releases, and
maintained by a security community without imposing a license burden on
this project.

**Rejected**: an automated CI check that fetches the mirror and fails the
build on any unknown ID. The mirror is an external dependency outside this
project's release cadence; making it a CI gate trades one source of
flakiness (a maintainer forgetting the sweep) for another (the mirror or
its CDN being temporarily down). The sweep is a manual release-time act,
not a per-PR enforcement.

## Consequences

- The release engineer carries one extra checklist item: run the ATLAS
  sweep, paste the result into the release-PR description (or the
  CHANGELOG entry for the release), and note any ID added, retired, or
  renamed. The sweep is cheap — under ten minutes for the twelve
  attack classes the catalog currently covers.
- A future addition of an attack class (a Class 14, a sub-probe) inherits
  the same gate: the probe ships with both an ATLAS assignment **and** a
  one-line comment justifying it.
- An empty `atlas_techniques: tuple[str, ...] = ()` is a valid outcome and
  stays explicit (Class 5 KV-cache timing and Class 11 erasure carry no
  ATLAS technique because they are not attack techniques in the catalog's
  taxonomy); the sweep verifies the *absence* is still defensible against
  any newly-added technique.
- This ADR does not commit to any particular ATLAS version: the catalog is
  versioned, and the next release records the ATLAS revision it was
  validated against.
- An **offline existence + format tripwire** (`tests/unit/test_atlas_ids.py`)
  pins the set of IDs verified by the most recent sweep and rejects any malformed
  ID (`AML.TOO24`) per PR. It closes the typo gap this ADR names while staying
  offline, so it does **not** reintroduce the rejected network dependency: it
  cannot judge renames or fit (that stays the manual release-time sweep), only
  that every ID in use is well-formed and was verified in the log below.

## Validation log

- **2026-06-01** — swept every probe's `atlas_techniques` against the MISP galaxy
  ATLAS mirror. All assigned IDs are present with unchanged canonical names:
  `AML.T0020` (Poison Training Data), `AML.T0024` (Exfiltration via ML Inference
  API), `AML.T0024.000` (Infer Training Data Membership), `AML.T0024.001` (Invert
  ML Model), `AML.T0053` (LLM Plugin Compromise), `AML.T0057` (LLM Data Leakage).
  No ID was retired or renamed and no newly-added technique was judged a better
  fit. `AML.T0024.000` is confirmed valid — ATLAS sub-techniques are numbered
  from `.000`, unlike MITRE ATT&CK. This verified set is pinned in
  `tests/unit/test_atlas_ids.py`.

- **2026-07-18** (at v0.7.0) — swept every probe's `atlas_techniques` against the
  MISP galaxy ATLAS mirror (cluster *MITRE ATLAS Attack Pattern*, version 14, 91
  techniques). All six assigned IDs are present under **unchanged** canonical
  names — `AML.T0020`, `AML.T0024`, `AML.T0024.000`, `AML.T0024.001`,
  `AML.T0053`, `AML.T0057` — and none carries a deprecation, revocation or
  supersession marker. No rename, no retirement.

  Fit review of the techniques we do *not* use: the only family touching this
  domain is `AML.T0051` LLM Prompt Injection (`.000` Direct, `.001` Indirect).
  It was **not adopted**, deliberately:

  - Class 3 rag-poisoning plants a document that ranks highly and carries a
    canary; it smuggles no instruction the model is meant to obey, so poisoning
    plus retrieval exfiltration (`AML.T0020` + `AML.T0024`) stays the accurate
    pair — indirect *prompt injection* would overstate what the probe does.
  - Class 7's tool-description-injection sub-probe is the closest candidate for
    `AML.T0051.001`, but `AML.T0053` (LLM Plugin Compromise) already names the
    surface it attacks, and `atlas_techniques` is declared per probe rather than
    per sub-probe. That makes it a refinement, not a correction — left to a
    deliberate decision rather than folded into a sweep.
  - The Class 2/10/13 organic-bleed probes are explicitly non-adversarial (no
    injection is used), so `AML.T0051` would misdescribe them.

  Classes 5 (kv-cache-timing) and 11 (erasure, subject-erasure) remain
  intentionally unmapped: ATLAS carries no timing-side-channel technique, and
  erasure is a control check rather than an adversary technique.
