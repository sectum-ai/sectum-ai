# GDPR Article 17 Erasure Attestation

This example reproduces **Attack Class 11**: verifying that a tenant's data has
actually left an AI system after a right-to-erasure request.

## The problem

GDPR Article 17 gives a data subject the right to erasure. When a tenant churns,
its data must leave *every* AI surface — not only the primary database, but the
vector index, prompt and completion logs, caches, fine-tuning sets, backups, and
derived search indexes. "We deleted the row" is not the same as "the data is
gone." A store that *soft-deletes* — marks a vector deleted but leaves it
queryable — fails Article 17 silently.

A Data Protection Officer needs evidence, not assurances.

## What the demo does

`run.sh` runs the erasure-verification workflow:

1. **`sectum-ai seed`** provisions the marker substrate.
2. **`sectum-ai erasure --target-tenant "Acme Robotics"`** confirms the tenant's
   canary markers are present in the vector store, triggers erasure, re-scans
   the vector store for residual markers, and writes an **attestation pack**:
   `erasure-attestation.pdf` (for the DPO) and `erasure-evidence.json`.
3. **`sectum-ai verify`** independently re-checks the attestation's integrity.

The probe verifies erasure across **eight surfaces** — the vector store,
observability / tracing, agent / long-term memory, semantic / application cache,
model / fine-tune adapter, derived search index, eval golden set, and backup /
snapshot store — scanning each independently and reporting a per-surface verdict
plus a full coverage block. Surfaces with no adapter configured (or excluded via
`--scope`) are reported `NOT_COVERED`, never `ERASED`; third-party subprocessor
residue remains on the roadmap. The attestation always states which surfaces it
covers. Pass `--scope vector_db` (or a comma-separated list) to verify just a
subset — a cheaper single-surface "snapshot" engagement.

## Run it

```sh
./run.sh
```

Artifacts are written to `out/`.

## Expected result

Against backends that hard-delete, every marker is gone after erasure and the
run reports a per-surface verdict:

```
vector_db: 2 markers before, 0 after -> ERASED
tracing: 2 markers before, 0 after -> ERASED
agent_memory: 2 markers before, 0 after -> ERASED
semantic_cache: 2 markers before, 0 after -> ERASED
model_adapter: 2 markers before, 0 after -> ERASED
search_index: 2 markers before, 0 after -> ERASED
eval_set: 2 markers before, 0 after -> ERASED
backup: 2 markers before, 0 after -> ERASED
ERASURE VERIFIED: no residual marker on vector_db, tracing, agent_memory,
semantic_cache, model_adapter, search_index, eval_set, backup.
```

`sectum-ai verify` then confirms the attestation pack is intact.

## See a failing erasure

After `./run.sh` has populated `out/`, model a store that only soft-deletes —
the common, silent Article 17 failure — from this directory:

```sh
uv run sectum-ai erasure --workdir out --soft-delete
```

The residual markers are itemized per surface, the run reports `ERASURE FAILED`,
and it exits with code 2.

## Tamper-evidence

The attestation is tamper-evident. Editing `erasure-evidence.json` after the
fact makes `sectum-ai verify` fail with a clear reason and exit code 4 — so an
attestation that verifies is an attestation that has not been altered.
