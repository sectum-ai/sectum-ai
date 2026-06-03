# Evidence chain

Every run produces an `EvidencePack` — a tamper-evident, control-mapped bundle
that an auditor or Data Protection Officer accepts and that a third party
verifies independently.

## Construction

1. The run is canonicalized: run id, timestamps, scenario and manifest hashes,
   adapter and probe versions, and findings, as deterministic JSON.
2. The whole attested pack — the canonical run, the manifest hash, the control
   mappings, the PDF reference, and whether it claims a transparency-log anchor —
   is hashed (SHA-256) into the `attested_digest`. (The run alone also keeps a
   `run_digest`, used as the in-toto attestation subject and shown in the PDF.)
3. The attested digest is timestamped. The development default is a local
   timestamper (a JSON record of the digest and a wall-clock time, with no
   external anchor). Production configures an RFC 3161 Time-Stamp Authority (see
   below) and, optionally, records the digest in a Sigstore Rekor transparency log.
4. The pack bundles the canonical run, the manifest hash, the timestamp token,
   the Rekor inclusion proof (when enabled), the control mappings, the
   `anchored_in_log` flag, and a human-readable PDF.

## Trusted timestamping (RFC 3161)

`sectum-ai report --tsa <url>` (or `evidence.timestamper: rfc3161` in `sectum-ai.yaml`)
submits the run digest to an RFC 3161 Time-Stamp Authority and stores the
returned token in the pack. The token proves the digest existed at the TSA's
attested time, signed by an authority independent of Sectum AI.

A timestamp token is only as trustworthy as the root it is checked against, so
the verifier **never trusts a root carried inside the pack** — that would let a
forged pack ship its own trust anchor. Instead `sectum-ai verify` pins the root
independently: it ships the public [FreeTSA](https://freetsa.org) leaf and root
built in (FreeTSA is the default TSA), and `--tsa-cert`/`--tsa-root` override
them with a customer-pinned authority's certificates.

RFC 3161 support is an optional extra, `sectum-ai-evidence[rfc3161]` (the
`LocalTimestamper` path needs no third-party dependency).

## Transparency log (Sigstore Rekor)

`sectum-ai report --rekor` (or `evidence.rekor: true` in `sectum-ai.yaml`) also records
the run digest in the [Sigstore Rekor](https://docs.sigstore.dev/logging/overview/)
transparency log — a public, append-only Merkle log. The log returns an
*inclusion proof*: the entry's position, the Merkle audit path to the tree root,
and a checkpoint (the signed tree head) committing to that root. The proof is
stored in the pack.

`sectum-ai verify` checks the proof entirely offline: it recomputes the RFC 6962
Merkle root from the entry and the audit path, and verifies the checkpoint that
commits to that root was signed by Rekor. As with the TSA, the checkpoint key is
pinned independently — never read from the pack. The verifier ships the
public-good instance's log keys built in (selected by log id), and `sectum-ai verify
--rekor-key <pem>` pins a private instance's key. No network and no current tree
head are needed to verify; a captured proof verifies indefinitely.

Recording uses an ephemeral signing key: a transparency-log entry's value is the
public, timestamped *inclusion* of the digest, not the signer's identity. Rekor
support is the optional `sectum-ai-evidence[rekor]` extra.

## Verification

`sectum-ai verify <pack>` recomputes the **pack digest** (over the run record, the
manifest hash, the control mappings, the PDF reference, and the transparency-log
flag) and checks it against the timestamp token, the Rekor inclusion proof (when
present), and the manifest-hash consistency. For an RFC 3161 token it also
validates the token's signature against the pinned TSA chain. Any edit to the
attested content — a changed finding, a forged control mapping, a repointed PDF,
an altered hash — changes the digest and fails verification with a clear reason
and exit code 4. A pack anchored in the Rekor log fails if its proof is stripped
(a downgrade), and a `local-dev` timestamp is reported as *unanchored*. Because
`sectum-ai verify` is part of the open-source core, anyone can verify a Sectum AI
evidence pack without trusting Sectum AI. (See [ADR-0016](adr/0016-anchor-the-whole-pack.md).)

## What the pack carries — and what it does not

The pack carries the manifest's *hash*, not the manifest itself. The
ground-truth manifest is sensitive (see the [threat model](threat-model.md)) and
is kept out of an artifact that travels to auditors; its hash still binds the
test condition cryptographically.

## Outputs

- `evidence.json` — machine-readable and schema-versioned.
- `audit-pack.pdf` — an executive summary, scope, methodology, findings table,
  and a control-by-control coverage appendix.
- `attestation.intoto.json` — the same evidence re-expressed as an
  [in-toto Attestation](https://github.com/in-toto/attestation) Statement (v1):
  a tool-agnostic envelope whose *subject* is the run (bound by its canonical
  digest) and whose *predicate* is the verification result (scenario and
  manifest hashes, metrics, control mappings, and which integrity anchors are
  present). It is a derived view of the pack — it adds an interoperable format,
  not new trust — and can be DSSE-signed and logged to Rekor for distribution.
