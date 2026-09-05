# Class 11 — GDPR Article 17 erasure verification

**OWASP:** LLM08:2025 · **ATLAS:** — (a control check, not an attack technique) · **NIST:** MEASURE 2.7 · **Surfaces:** vector DB, tracing, agent memory, semantic cache, model/fine-tune, search index, eval set, backup · **Probe ids:** `gdpr-erasure-verification`, `gdpr-subject-erasure-verification`

Checking, surface by surface, that none of a tenant's markers is still
retrievable after a right-to-erasure request — and stating explicitly which
surfaces were not checked.

Two probes verify erasure at two granularities. `gdpr-erasure-verification`
verifies **tenant-level** erasure — none of a tenant's markers remain after the
tenant's data is erased. `gdpr-subject-erasure-verification` verifies a **data
subject's** erasure (a GDPR Article 17 DSR for one user *within* a tenant) as a
post-deletion check: after the customer's own deletion has run, it confirms the
subject's records are gone by id and by content fingerprint, without a
plant/erase flow of its own. The method and coverage model below are the tenant
probe's; the subject probe applies the same anti-over-claim verdicts at
data-subject granularity — over a **narrower surface set**. It verifies by id on
the vector DB, semantic cache, and tracing, and by content fingerprint on the
vector DB, model adapter, agent memory, and search index. The eval set and backup
surfaces are not scanned by the subject probe and read `NOT_COVERED` in its
attestation; only the tenant probe covers all eight. On the model adapter the
fingerprint check is prefix-continuation with two control arms: the subject's
prefix must complete to the trailing part; a same-shaped prefix naming nobody
must not (so `@example.com` after any local part, or `Smith` after `John`, is a
generic completion, not recall); and on a model that routes per tenant, the same
prefix as a tenant that trained nothing must not either (so `Hussein Obama`
after `Barack` is the base model's world knowledge, not the tenant's residual).
The scrambled control works for any script, not only Latin, and both controls
apply to the whole-phrase echo too (a chatty base model that restates the prompt
is not recall — on shared weights included, where the model restating the
scrambled prompt is what gives it away). On the vector store the fingerprint is
a top-50 similarity query; a page that comes back full without the phrase makes
that phrase unverifiable (a stored document ranked past the page is
indistinguishable from an erased one), so the surface reads `NOT_COVERED` for the
subject rather than `ERASED`. On a model that merges every tenant's weights
(`SHARED_WEIGHTS`) there is no untrained tenant to ask, so a completion cannot be
told apart from the base model's own knowledge: the model surface reads
`NOT_COVERED` for the subject rather than signing a residual it cannot attribute. An email is cut inside its local part. A phrase the check cannot
verify — a trailing part under six characters, a bare two-word name, a prefix
with no scrambled form — is counted and the verifiable phrases are still
scanned: the model surface reads `RESIDUAL` if any of them is recalled, else
`NOT_COVERED` for the subject (never `ERASED` while something was unchecked), and
the run says how many supplied fingerprints it could not check. The tenant probe's canary scan uses the
same continuation test, so a real LoRA that memorised a canary and continues it
(rather than echoing it) is `RESIDUAL`, not invisible.

## Goal

Confirm that, after an erasure request, none of a target tenant's canary markers
remain observable.

## Method

Pre-erasure, confirm the target tenant's hard canaries are present. Trigger the
erasure flow. Post-erasure, re-scan for any residual marker.

## Detection

A residual marker after erasure is an itemized erasure failure. A surface with
no pre-erasure baseline is reported as inconclusive — never as a vacuous pass.

A surface whose backend exposes **no programmatic per-tenant erasure API** at
all (for example Helicone or Datadog APM, where deletion is governed by a
retention policy) is reported as **attestable-with-caveat**, distinct from a
failure: the tenant's data is presumed retained until it ages out of the
retention window, but the gap is a documented backend limitation rather than a
defect in the customer's erasure flow (the engineering spec, §7, Class 11,
hiding place #8). It is never a clean pass — the data genuinely remains.

## Coverage — the attestation never over-claims

Every erasure surface gets an explicit, machine-readable **coverage verdict** in
the evidence pack (`RunMetrics.erasure_coverage`, surface → `CoverageVerdict`):

| Verdict | Meaning |
|---|---|
| `ERASED` | Covered and clean — a baseline existed and no marker is retrievable through the erased tenant's own read path after erasure. A backend that retains the data while revoking that path is indistinguishable, from outside, from one that purged it. |
| `RESIDUAL` | Covered and failed — the backend was asked to erase and a marker survived. |
| `ATTESTABLE_WITH_CAVEAT` | Covered, but the backend exposes no per-tenant erasure API — data presumed retained. |
| `NOT_COVERED` | Out of scope, not scanned, or no pre-erasure baseline — **never** evidence of erasure. |

The guarantee is anti-over-claim: a surface that was not scanned can only ever be
`NOT_COVERED` — it can never read as `ERASED`. The overall run is "fully erased"
only when every scanned surface is `ERASED` **and** the attestation states which
surfaces were `NOT_COVERED`. The audit pack renders a **Coverage & caveats**
matrix so a DPO or auditor can see, surface by surface, exactly what was and was
not verified.

## Scoping a run — the single-surface "snapshot"

By default `sectum-ai erasure` verifies every configured surface. Pass `--scope`
to verify a subset — a cheaper single-surface *snapshot* engagement (for example
verifying just the vector DB):

```sh
# Verify only the vector store; every other surface is reported NOT_COVERED.
sectum-ai erasure --target-tenant "Acme Robotics" --scope vector_db

# Verify a couple of surfaces.
sectum-ai erasure --target-tenant "Acme Robotics" --scope vector_db,tracing
```

`--scope` takes a comma-separated list of erasure surfaces: `vector_db`,
`tracing`, `agent_memory`, `semantic_cache`, `model_adapter`, `search_index`,
`eval_set`, `backup`. An unknown surface name is a configuration error (exit 3).
Surfaces outside the scope are not scanned and are recorded `NOT_COVERED`, so the
snapshot pack still states its own boundary honestly.

## Output

`sectum-ai erasure` produces an attestation pack — a PDF for the Data Protection
Officer and a JSON evidence pack — control-mapped to GDPR Article 17 and CCPA
§1798.105 when a live surface scanned to `ERASED` or `RESIDUAL` (an erasure run
never asserts the isolation rows such as Article 32; a run against the built-in
fakes asserts no mapping at all). The
pack carries the per-surface coverage block above, and the PDF renders it as a
Coverage & caveats matrix.

## Status

Implemented for **eight surfaces**: the vector store (Phase 3) and, in
post-Phase-5 hardening, observability / tracing, agent / long-term memory,
semantic / application cache, model / fine-tune adapter, derived search index,
eval golden set, and backup / snapshot store. `ErasureProbe` accepts a vector
store plus optional observability, memory, cache, model, search-index, eval-set,
and backup adapters, scans each independently (or a `--scope`-selected subset),
and reports a per-surface verdict plus the full coverage block above. A backup /
snapshot store (hiding place #7) is recorded *attestable-with-caveat* when it
exposes no per-tenant erasure API (the common immutable-snapshot case). The
remaining hiding place — third-party subprocessor residue — has no scanning
adapter yet, so it is out of scope (`NOT_COVERED`) until its adapter family lands. The canonical
surface set is `sectum_ai.probes.ERASURE_SURFACES`. Walkthrough:
[`examples/erasure-attestation`](https://github.com/sectum-ai/sectum-ai/tree/main/examples/erasure-attestation).
