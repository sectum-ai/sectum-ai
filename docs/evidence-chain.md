# Evidence chain

Every run produces an `EvidencePack` — a tamper-evident, control-mapped bundle
that an auditor or Data Protection Officer accepts and that a third party
verifies independently.

## Construction

1. The run is canonicalized: run id, timestamps, scenario and manifest hashes,
   adapter and probe versions, and findings, as deterministic JSON.
2. The canonical run is hashed (SHA-256) into a `run_digest`.
3. The digest is timestamped. The development default is a local timestamper
   (a JSON record of the digest and a wall-clock time, with no external anchor).
   Production configures an RFC 3161 Time-Stamp Authority (see below); a
   Sigstore Rekor transparency log is planned.
4. The pack bundles the canonical run, the manifest hash, the timestamp token,
   the control mappings, and a human-readable PDF.

## Trusted timestamping (RFC 3161)

`sectum report --tsa <url>` (or `evidence.timestamper: rfc3161` in `sectum.yaml`)
submits the run digest to an RFC 3161 Time-Stamp Authority and stores the
returned token in the pack. The token proves the digest existed at the TSA's
attested time, signed by an authority independent of Sectum AI.

A timestamp token is only as trustworthy as the root it is checked against, so
the verifier **never trusts a root carried inside the pack** — that would let a
forged pack ship its own trust anchor. Instead `sectum verify` pins the root
independently: it ships the public [FreeTSA](https://freetsa.org) leaf and root
built in (FreeTSA is the default TSA), and `--tsa-cert`/`--tsa-root` override
them with a customer-pinned authority's certificates.

RFC 3161 support is an optional extra, `sectum-ai-evidence[rfc3161]` (the
`LocalTimestamper` path needs no third-party dependency).

## Verification

`sectum verify <pack>` recomputes the run digest and checks it against the
timestamp token. For an RFC 3161 token it also validates the token's signature
against the pinned TSA chain. Any edit to the run record — a changed finding, an
altered hash — changes the digest and fails verification with a clear reason and
exit code 4. Because `sectum verify` is part of the open-source core, anyone can
verify a Sectum AI evidence pack without trusting Sectum AI.

## What the pack carries — and what it does not

The pack carries the manifest's *hash*, not the manifest itself. The
ground-truth manifest is sensitive (see the [threat model](threat-model.md)) and
is kept out of an artifact that travels to auditors; its hash still binds the
test condition cryptographically.

## Outputs

- `evidence.json` — machine-readable and schema-versioned.
- `audit-pack.pdf` — an executive summary, scope, methodology, findings table,
  and a control-by-control coverage appendix.
