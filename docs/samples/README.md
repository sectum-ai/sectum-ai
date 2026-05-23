# Sample evidence packs

These artifacts were produced by the runnable end-to-end examples in
[`examples/`](https://github.com/sectum-ai/sectum-ai/tree/main/examples) — they
are real outputs of `sectum report` and `sectum erasure`, checked in so a
prospective auditor, DPO, or CISO can see what they get without installing
anything.

| File | Source example | Size | What it is |
|---|---|---|---|
| [`retrieval-pivot-audit-pack.pdf`](retrieval-pivot-audit-pack.pdf) | `examples/retrieval-pivot` | 16 KB | The auditor-facing PDF: executive summary, scope / methodology, all 264 findings (with per-finding OWASP / ATLAS / NIST IDs and remediation pointers), compliance-control coverage, and the integrity / verification block. |
| [`retrieval-pivot-attestation.intoto.json`](retrieval-pivot-attestation.intoto.json) | `examples/retrieval-pivot` | 4 KB | The [in-toto](https://in-toto.io/) attestation envelope: the run digest, the timestamp token, and the manifest hash that pin the test condition. |
| [`erasure-attestation-audit-pack.pdf`](erasure-attestation-audit-pack.pdf) | `examples/erasure-attestation` | 4 KB | The DPO-facing GDPR Article 17 erasure attestation: per-surface verdicts (ERASED / RESIDUAL DATA) across all seven configured surfaces. |
| [`erasure-attestation-evidence.json`](erasure-attestation-evidence.json) | `examples/erasure-attestation` | 3 KB | The machine-readable evidence pack for the erasure run (the JSON sibling of the PDF, schema-versioned). |
| [`erasure-attestation-attestation.intoto.json`](erasure-attestation-attestation.intoto.json) | `examples/erasure-attestation` | 3 KB | The erasure attestation's in-toto envelope. |

## Verifying these packs

Every pack here verifies under the open-source `sectum verify`:

```sh
uv run sectum verify docs/samples/erasure-attestation-evidence.json
```

A `VERIFIED` outcome means the run digest matches the timestamped token and
the manifest hash agrees between the run and the pack. Mutating a single
byte in the JSON makes `verify` exit `4` with a `[FAIL]` line — that
demonstrates the tamper-evident property end to end.

## Regenerating

These files snapshot a deterministic run; re-running the example
overwrites them only if you copy the new outputs over. To refresh:

```sh
./examples/retrieval-pivot/run.sh
cp examples/retrieval-pivot/out/audit-pack.pdf docs/samples/retrieval-pivot-audit-pack.pdf
cp examples/retrieval-pivot/out/attestation.intoto.json docs/samples/retrieval-pivot-attestation.intoto.json

./examples/erasure-attestation/run.sh
cp examples/erasure-attestation/out/erasure-attestation.pdf docs/samples/erasure-attestation-audit-pack.pdf
cp examples/erasure-attestation/out/erasure-evidence.json docs/samples/erasure-attestation-evidence.json
cp examples/erasure-attestation/out/erasure-attestation.intoto.json docs/samples/erasure-attestation-attestation.intoto.json
```

The full retrieval-pivot `evidence.json` is intentionally *not* checked in
(~235 KB with 264 findings); run the example locally to inspect the JSON
structure, or read the
[`Finding`](https://github.com/sectum-ai/sectum-ai/blob/main/packages/spec/src/sectum/spec/models.py)
schema.
