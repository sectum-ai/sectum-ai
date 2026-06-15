# sectum-ai-evidence

The tamper-evident **evidence chain** for [Sectum AI](https://github.com/sectum-ai/sectum-ai).

This distribution turns a verification run into an auditor-acceptable evidence
pack and verifies it independently:

- canonicalize the run and hash it (SHA-256) into a `run_digest`, then hash the
  whole pack into the `attested_digest` that the anchors bind;
- timestamp the `attested_digest` with an RFC 3161 Time-Stamp Authority;
- record it in a Sigstore Rekor transparency log;
- bundle the canonical run, the hashed ground-truth manifest, the TSA token,
  the Rekor proof, and control mappings into an `in-toto` attestation + a
  human-readable PDF audit pack;
- `sectum-ai verify <pack>` recomputes the digests and validates the TSA token and
  Rekor inclusion proof, reporting PASS/FAIL with reasons — so a third party can
  verify a pack without trusting the producer.

```sh
pip install sectum-ai-evidence
```

Most users install the umbrella package [`sectum-ai`](https://pypi.org/project/sectum-ai/)
instead, which pulls this in automatically.

- Evidence-chain docs: <https://docs.sectum.ai>
- Source: <https://github.com/sectum-ai/sectum-ai>

Apache-2.0.
