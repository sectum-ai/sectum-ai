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

1. **`sectum seed`** provisions the marker substrate.
2. **`sectum erasure --target-tenant "Acme Robotics"`** confirms the tenant's
   canary markers are present in the vector store, triggers erasure, re-scans
   the vector store for residual markers, and writes an **attestation pack**:
   `erasure-attestation.pdf` (for the DPO) and `erasure-evidence.json`.
3. **`sectum verify`** independently re-checks the attestation's integrity.

Phase 3 verifies erasure on the **vector store**. The other surfaces named
above — logs, caches, fine-tuning sets, backups, derived indexes — are part of
the erasure roadmap and are wired in later phases; the attestation always
states which surfaces it covers.

## Run it

```sh
./run.sh
```

Artifacts are written to `out/`.

## Expected result

Against a store that hard-deletes, every marker is gone after erasure and the
run reports:

```
vector_db: 2 markers before, 0 after -> ERASED
ERASURE VERIFIED: no residual marker on vector_db.
```

`sectum verify` then confirms the attestation pack is intact.

## See a failing erasure

After `./run.sh` has populated `out/`, model a store that only soft-deletes —
the common, silent Article 17 failure — from this directory:

```sh
uv run sectum erasure --workdir out --soft-delete
```

The residual markers are itemized per surface, the run reports `ERASURE FAILED`,
and it exits with code 2.

## Tamper-evidence

The attestation is tamper-evident. Editing `erasure-evidence.json` after the
fact makes `sectum verify` fail with a clear reason and exit code 4 — so an
attestation that verifies is an attestation that has not been altered.
