# Sample evidence packs

These artifacts were produced by the runnable end-to-end examples in
[`examples/`](https://github.com/sectum-ai/sectum-ai/tree/main/examples) — they
are real outputs of `sectum report` and `sectum erasure`, checked in so a
prospective auditor, DPO, or CISO can see what they get without installing
anything.

Two erasure flavours ship side-by-side so prospects can see both:

- **Happy path** (`erasure-attestation-*`) — the controller followed up on a
  GDPR Article 17 request and all seven surfaces are ERASED. The DPO-shaped
  attestation that closes the regulator ticket.
- **Residual data** (`erasure-attestation-residual-data-*`) — the controller
  ran soft-delete (the common bug: a tombstone, not a purge). Every surface
  comes back RESIDUAL DATA. This is the failure mode the pack is designed
  to catch *before* the regulator does.

| File | Source example | Size | What it is |
|---|---|---|---|
| [`retrieval-pivot-audit-pack.pdf`](retrieval-pivot-audit-pack.pdf) | `examples/retrieval-pivot` | 33 KB | The auditor-facing PDF: executive summary, scope / methodology, all 321 findings (with per-finding OWASP / ATLAS / NIST IDs and remediation pointers), compliance-control coverage, and the integrity / verification block. |
| [`retrieval-pivot-attestation.intoto.json`](retrieval-pivot-attestation.intoto.json) | `examples/retrieval-pivot` | 4 KB | The [in-toto](https://in-toto.io/) attestation envelope: the run digest, the timestamp token, and the manifest hash that pin the test condition. |
| [`erasure-attestation-audit-pack.pdf`](erasure-attestation-audit-pack.pdf) | `examples/erasure-attestation` | 4 KB | The DPO-facing GDPR Article 17 erasure attestation, **happy path**: per-surface verdicts ERASED across all seven configured surfaces. |
| [`erasure-attestation-evidence.json`](erasure-attestation-evidence.json) | `examples/erasure-attestation` | 3 KB | The machine-readable evidence pack for the happy-path erasure run (the JSON sibling of the PDF, schema-versioned). |
| [`erasure-attestation-attestation.intoto.json`](erasure-attestation-attestation.intoto.json) | `examples/erasure-attestation` | 3 KB | The happy-path erasure attestation's in-toto envelope. |
| [`erasure-attestation-residual-data-audit-pack.pdf`](erasure-attestation-residual-data-audit-pack.pdf) | `examples/erasure-attestation` (`--soft-delete`) | 6 KB | The DPO-facing PDF when the erasure was **partial** — per-surface RESIDUAL DATA verdicts with the residual marker counts. This is the artefact the controller would attach when remediating the gap. |
| [`erasure-attestation-residual-data-evidence.json`](erasure-attestation-residual-data-evidence.json) | `examples/erasure-attestation` (`--soft-delete`) | 14 KB | Machine-readable evidence pack for the residual-data run; carries the per-marker residual hits so a DPO or controller can trace which canaries survived which surface. |
| [`erasure-attestation-residual-data-attestation.intoto.json`](erasure-attestation-residual-data-attestation.intoto.json) | `examples/erasure-attestation` (`--soft-delete`) | 3 KB | The residual-data run's in-toto envelope. |

## Verifying these packs

Every pack here verifies under the open-source `sectum verify`:

```sh
uv run sectum verify docs/samples/erasure-attestation-evidence.json
```

A `VERIFIED` outcome means the whole-pack attested digest matches the
timestamped token and the manifest hash agrees between the run and the pack.
Mutating a single byte of the attested content makes `verify` exit `4` with a
`[FAIL]` line — that demonstrates the tamper-evident property end to end.

## Regenerating

These files snapshot a deterministic run; re-running the example
overwrites them only if you copy the new outputs over. To refresh:

```sh
./examples/retrieval-pivot/run.sh
cp examples/retrieval-pivot/out/audit-pack.pdf docs/samples/retrieval-pivot-audit-pack.pdf
cp examples/retrieval-pivot/out/attestation.intoto.json docs/samples/retrieval-pivot-attestation.intoto.json

# Happy path — all surfaces ERASED.
./examples/erasure-attestation/run.sh
cp examples/erasure-attestation/out/erasure-attestation.pdf docs/samples/erasure-attestation-audit-pack.pdf
cp examples/erasure-attestation/out/erasure-evidence.json docs/samples/erasure-attestation-evidence.json
cp examples/erasure-attestation/out/erasure-attestation.intoto.json docs/samples/erasure-attestation-attestation.intoto.json

# Residual-data path — soft-delete leaves RESIDUAL DATA on every surface.
# Re-seed into a separate workdir so the happy-path artifacts survive,
# then run erasure with --soft-delete to reproduce the failure mode.
mkdir -p examples/erasure-attestation/out-residual
uv run sectum seed --workdir examples/erasure-attestation/out-residual
uv run sectum erasure \
  --workdir examples/erasure-attestation/out-residual \
  --target-tenant "Acme Robotics" \
  --soft-delete
cp examples/erasure-attestation/out-residual/erasure-attestation.pdf docs/samples/erasure-attestation-residual-data-audit-pack.pdf
cp examples/erasure-attestation/out-residual/erasure-evidence.json docs/samples/erasure-attestation-residual-data-evidence.json
cp examples/erasure-attestation/out-residual/erasure-attestation.intoto.json docs/samples/erasure-attestation-residual-data-attestation.intoto.json
```

The full retrieval-pivot `evidence.json` is intentionally *not* checked in
(~271 KB with 321 findings); run the example locally to inspect the JSON
structure, or read the
[`Finding`](https://github.com/sectum-ai/sectum-ai/blob/main/packages/spec/src/sectum/spec/models.py)
schema.
