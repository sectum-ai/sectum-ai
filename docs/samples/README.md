# Sample evidence packs

These artifacts were produced by the runnable end-to-end examples in
[`examples/`](https://github.com/sectum-ai/sectum-ai/tree/main/examples) — they
are real outputs of `sectum-ai report` and `sectum-ai erasure`, checked in so a
prospective auditor, DPO, or CISO can see what they get without installing
anything.

Two erasure flavours ship side-by-side so prospects can see both:

- **Happy path** (`erasure-attestation-*`) — the controller followed up on a
  GDPR Article 17 request and all eight surfaces are ERASED. The *shape* of the
  DPO-facing pack that closes a regulator ticket; this run is synthetic, and the
  PDF says so ("a demonstration, not an attestation") — see "Verifying these
  packs" below.
- **Residual data** (`erasure-attestation-residual-data-*`) — the controller
  ran soft-delete (the common bug: a tombstone, not a purge). Every surface
  comes back RESIDUAL DATA. This is the failure mode the pack is designed
  to catch *before* the regulator does.

| File | Source example | What it is |
|---|---|---|
| [`retrieval-pivot-audit-pack.pdf`](retrieval-pivot-audit-pack.pdf) | `examples/retrieval-pivot` | The auditor-facing PDF: executive summary, scope / methodology, all 343 findings (each with its OWASP LLM and NIST ids; ATLAS ids and remediation pointers where the probe declares them), the compliance-control section (it reads "No control mappings were recorded.": every surface of this demo run is the built-in fake, and a mapping needs evidence from a live surface), and the integrity / verification block. |
| [`retrieval-pivot-attestation.intoto.json`](retrieval-pivot-attestation.intoto.json) | `examples/retrieval-pivot` | The [in-toto](https://in-toto.io/) attestation statement: the run digest as its subject, and a predicate carrying the scenario and manifest hashes, the metrics, the finding count, the control mappings, and which integrity anchors the pack has. |
| [`erasure-attestation-audit-pack.pdf`](erasure-attestation-audit-pack.pdf) | `examples/erasure-attestation` | The DPO-facing GDPR Article 17 erasure attestation, **happy path**: per-surface verdicts ERASED across all eight configured surfaces, with the Coverage & caveats matrix. |
| [`erasure-attestation-evidence.json`](erasure-attestation-evidence.json) | `examples/erasure-attestation` | The machine-readable evidence pack for the happy-path erasure run (the JSON sibling of the PDF, schema-versioned). |
| [`erasure-attestation-attestation.intoto.json`](erasure-attestation-attestation.intoto.json) | `examples/erasure-attestation` | The happy-path erasure attestation's in-toto envelope. |
| [`erasure-attestation-residual-data-audit-pack.pdf`](erasure-attestation-residual-data-audit-pack.pdf) | `examples/erasure-attestation` (`--soft-delete`) | The DPO-facing PDF when the erasure was **partial** — per-surface `RESIDUAL` verdicts (the per-marker residual counts are in the JSON's `metrics.erasure_residue`, not the PDF). This is the artefact the controller would attach when remediating the gap. |
| [`erasure-attestation-residual-data-evidence.json`](erasure-attestation-residual-data-evidence.json) | `examples/erasure-attestation` (`--soft-delete`) | Machine-readable evidence pack for the residual-data run; carries the per-marker residual hits so a DPO or controller can trace which canaries survived which surface. |
| [`erasure-attestation-residual-data-attestation.intoto.json`](erasure-attestation-residual-data-attestation.intoto.json) | `examples/erasure-attestation` (`--soft-delete`) | The residual-data run's in-toto envelope. |

## Verifying these packs

The two erasure `evidence.json` packs verify under the open-source
`sectum-ai verify`, given two flags that say plainly what they are.

`verify` finds a pack's audit PDF and sidecars by their *generated* names beside
it (`erasure-attestation.pdf` next to `erasure-evidence.json`). Every copy in
this directory is renamed with a `retrieval-pivot-` or `erasure-attestation-`
prefix, so the command below checks the JSON pack alone and says so on its
`audit-pdf` line — run the example's `run.sh` to check the PDF binding against
the pack it was generated with. (The retrieval-pivot `evidence.json` is not
committed at all — ~293 KB — so its PDF and sidecar have no pack here to bind
to.) These are produced by the offline demo flow, so:

- their timestamp is the local-dev token — `--allow-unanchored` accepts
  integrity-only verification (a production pack built with `report --tsa <url> --rekor`
  verifies without the flag, as an independently anchored attestation);
- every surface they exercised was Sectum's built-in in-memory fake, not a
  configured backend — `--allow-synthetic` accepts that. Without it `verify`
  refuses, because every other check concerns the integrity of the *bytes* and
  passes just as cleanly for a run that touched nothing real. The `run-scope`
  check reports the provenance either way.

```sh
uv run sectum-ai verify docs/samples/erasure-attestation-evidence.json \
  --allow-unanchored --allow-synthetic
```

An `INTEGRITY OK - UNANCHORED` outcome (the verdict `--allow-unanchored` produces;
plain `VERIFIED` is reserved for a TSA- or Rekor-anchored pack) means the whole-pack attested digest matches the
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
uv run sectum-ai seed --workdir examples/erasure-attestation/out-residual \
  --config examples/erasure-attestation/sectum-ai.yaml
uv run sectum-ai erasure \
  --workdir examples/erasure-attestation/out-residual \
  --target-tenant "Acme Robotics" \
  --soft-delete
cp examples/erasure-attestation/out-residual/erasure-attestation.pdf docs/samples/erasure-attestation-residual-data-audit-pack.pdf
cp examples/erasure-attestation/out-residual/erasure-evidence.json docs/samples/erasure-attestation-residual-data-evidence.json
cp examples/erasure-attestation/out-residual/erasure-attestation.intoto.json docs/samples/erasure-attestation-residual-data-attestation.intoto.json
```

**The two erasure PDFs are guarded; the retrieval-pivot one is not.**
`tests/invariants/test_sample_packs_verify.py` re-renders each committed erasure
PDF from its committed pack and fails if they differ, so a renderer change cannot
leave them stating a rule the tool no longer follows. That guard needs a
committed pack to render *from*, and the retrieval-pivot pack is not committed
(next paragraph) — so its PDF is the one shipped artifact that can drift
silently. Regenerate all three together, and re-read the regenerated
retrieval-pivot PDF when the renderer changes.

The full retrieval-pivot `evidence.json` is intentionally *not* checked in
(~293 KB with 343 findings); run the example locally to inspect the JSON
structure, or read the
[`Finding`](https://github.com/sectum-ai/sectum-ai/blob/main/packages/spec/src/sectum_ai/spec/models.py)
schema.
