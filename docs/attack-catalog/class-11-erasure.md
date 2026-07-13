# Class 11 — GDPR Article 17 erasure verification

**OWASP:** LLM08:2025 · **ATLAS:** — (a control check, not an attack technique) · **NIST:** MEASURE 2.7 · **Surfaces:** vector DB, tracing, agent memory, semantic cache, model/fine-tune, search index, eval set, backup · **Probe id:** `gdpr-erasure-verification`

Proving a tenant's data has actually left an AI system after a right-to-erasure
request.

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
| `ERASED` | Covered and clean — a baseline existed and no marker survived erasure. |
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
Officer and a JSON evidence pack — control-mapped to GDPR Articles 17 and 32. The
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
