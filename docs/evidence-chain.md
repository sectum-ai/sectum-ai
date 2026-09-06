# Evidence chain

A completed run can be assembled into an `EvidencePack` — a bundle a third
party verifies independently with `sectum-ai verify`, no trust in Sectum AI
required. Two things must be true before it is evidence *about your systems*:
the digest must be bound by an independent anchor (a real RFC 3161 timestamp or
a Rekor inclusion proof — the development default is neither), and at least one
surface must have been live. `verify` refuses a pack missing either, and a run
with no live surface carries no control mappings at all.

## Construction

1. The run is canonicalized: run id, timestamps, scenario and manifest hashes,
   adapter and probe versions, surface provenance, findings, and metrics, as
   deterministic JSON.
2. The whole attested pack — the canonical run, the manifest hash, the control
   mappings, the PDF reference, and whether it claims a transparency-log anchor
   and a real timestamp anchor (`anchored_in_log`, `anchored_with_timestamp`) —
   is hashed (SHA-256) into the `attested_digest`. (The run alone also keeps a
   `run_digest`, used as the in-toto attestation subject and shown in the PDF.)
3. The attested digest is timestamped. The development default is a local
   timestamper (a JSON record of the digest and a wall-clock time, with no
   external anchor). Production configures an RFC 3161 Time-Stamp Authority (see
   below) and, optionally, records the digest in a Sigstore Rekor transparency log.
4. The pack carries the canonical run, the manifest hash, the timestamp token,
   the Rekor inclusion proof (when enabled), the control mappings, the
   `anchored_in_log` and `anchored_with_timestamp` flags, and `pdf_ref` — the
   SHA-256 of the audit PDF's bytes. The PDF travels beside the pack, not within
   it (`sectum-ai pack` is what puts the two in one zip).

## Trusted timestamping (RFC 3161)

`sectum-ai report --tsa <url>` (or `evidence.timestamper: rfc3161` in `sectum-ai.yaml`)
submits the attested digest to an RFC 3161 Time-Stamp Authority and stores the
returned token in the pack. The token proves the digest existed at the TSA's
attested time, signed by an authority independent of Sectum AI.

A timestamp token is only as trustworthy as the root it is checked against, so
the verifier **never trusts a root carried inside the pack** — that would let a
forged pack ship its own trust anchor. Instead `sectum-ai verify` pins the root
independently: it ships the public [FreeTSA](https://freetsa.org) leaf and root
built in (FreeTSA is the default TSA), and `--tsa-cert`/`--tsa-root` override
them with a customer-pinned authority's certificates. Pass them **together**: a
leaf supplied with `--tsa-cert` must be issued by the pinned root, so
`--tsa-cert` alone leaves a customer's leaf checked against FreeTSA's root and
`verify` refuses it. The library keeps the leaf and the roots in one flat trust
store, so without that check a self-signed leaf would anchor its own token.

RFC 3161 support is an optional extra, `sectum-ai-evidence[rfc3161]` (the
`LocalTimestamper` path needs no third-party dependency).

## Transparency log (Sigstore Rekor)

`sectum-ai report --rekor` (or `evidence.rekor: true` in `sectum-ai.yaml`) also records
the attested digest in the [Sigstore Rekor](https://docs.sigstore.dev/logging/overview/)
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
head are needed to verify; a captured proof verifies indefinitely. What the proof
binds is the digest's *inclusion*; the entry's integration time is a field of the
entry that nothing the verifier checks signs, so `verify` reports it as the log's
claim, not as a verified fact.

Recording uses an ephemeral signing key: a transparency-log entry's value is the
public, timestamped *inclusion* of the digest, not the signer's identity. Rekor
support is the optional `sectum-ai-evidence[rekor]` extra.

## Verification

`sectum-ai verify <pack>` recomputes the **pack digest** (over the run record, the
manifest hash, the control mappings, the PDF reference, and the transparency-log
and timestamp-anchor flags) and checks it against the timestamp token, the Rekor
inclusion proof (when
present), and the manifest-hash consistency. For an RFC 3161 token it also
validates the token's signature against the pinned TSA chain. Any edit to the
attested content — a changed finding, a forged control mapping, a repointed PDF,
an altered hash — changes the digest and fails verification with a clear reason
and exit code 4. A pack anchored in the Rekor log fails if its proof is stripped
(a downgrade); likewise a pack that claims a real RFC 3161 timestamp anchor fails
if its binary token is swapped for a `local-dev` one (also a downgrade). A
`local-dev` timestamp on a pack that never claimed an anchor is reported as
*unanchored* — and by default `sectum-ai verify` **refuses** such a pack (exit 4,
a failing `independent-anchor` check): a local-dev token can be regenerated by
anyone over an edited pack, so without a real RFC 3161 timestamp or a Rekor
inclusion proof the digest checks prove internal consistency, not tamper
evidence. Pass `--allow-unanchored` to accept that integrity-only result
explicitly; the verdict then reads `INTEGRITY OK - UNANCHORED`, never plain
`VERIFIED`.

Every check above concerns the **bytes**. A run that touched nothing real passes
all of them, because Sectum falls back to an in-memory fake for every adapter
family it cannot reach — so "the signature is valid" and "this describes a real
system" were unrelated facts, and only the first was checked. The `run-scope`
check closes that: it reports the run's signed
[surface provenance](coverage.md), and `sectum-ai verify` **refuses** (exit 4) a
pack in which no surface was live — or which carries no provenance block at all,
since its subject cannot be established either way. The block covers only the
surfaces the run's probes drove: a live backend in a slot no probe touched (a
tracing adapter, on a probe run) is not recorded, so it cannot stand in for the
probed surfaces at this gate. A third party receiving a vendor's pack is the
party least able to notice what is missing from it, so this fails closed like the
anchor check; pass `--allow-synthetic` to accept a demo pack knowingly. Because
`sectum-ai verify` is part of the open-source core, anyone can verify a Sectum AI
evidence pack without trusting Sectum AI. (See [ADR-0016](adr/0016-anchor-the-whole-pack.md).)

## What the pack carries — and what it does not

The pack carries the manifest's *hash*, not the manifest itself. The
ground-truth manifest is sensitive (see the [threat model](threat-model.md)) and
is kept out of an artifact that travels to auditors; its hash still binds the
test condition cryptographically.

## Outputs

- `evidence.json` — machine-readable and schema-versioned.
- `audit-pack.pdf` — a verification summary (including the probes exercised and
  the confirmed findings by kind), scope and methodology, the findings, the
  compliance control coverage, and an integrity / independent-verification block.
- `attestation.intoto.json` — the same evidence re-expressed as an
  [in-toto Attestation](https://github.com/in-toto/attestation) Statement (v1):
  a tool-agnostic envelope whose *subject* is the run (bound by its canonical
  digest) and whose *predicate* is the verification result (scenario and
  manifest hashes, metrics, control mappings, and which integrity anchors are
  present). It is a derived view of the pack — it adds an interoperable format,
  not new trust — and can be DSSE-signed and logged to Rekor for distribution.
- `evidence.dsse.json` — the in-toto statement wrapped in a
  [DSSE](https://github.com/secure-systems-lab/dsse) envelope (PAE-encoded),
  the signable form for distribution. `report` writes it **unsigned**
  (`signatures: []`); `verify` re-binds the envelope's statement to the pack and
  says so — it verifies no signature, whether or not one is present.

`sectum-ai report` flags that shape these outputs:

- `--pdf-engine {reportlab,weasyprint}` — selects the audit-pack PDF renderer
  (`reportlab` is the default; `weasyprint` needs the optional `weasyprint` extra).
- `--bundle` — writes a single `evidence-bundle.zip` gathering all of the above,
  the artifact `sectum-ai verify <bundle.zip>` checks end to end. The bundle's
  digest manifest is unsigned, so the verifier does not let it vouch for anything:
  `evidence.json` is the pack, always; only the member names Sectum itself writes
  are admitted (any other listed member is refused); every present audit PDF and
  in-toto member is bound to the pack, not just the first found (a bundled PDF
  the pack binds no `pdf_ref` for fails outright); and the
  per-member lines say "matches the unsigned manifest" — with the README, the
  redacted config, and the sealed manifest named as unbound. Member names are the
  archive's own input and are escaped in the verifier's output.
- `--include-manifest` — adds the ground-truth manifest to the bundle, sealed
  AES-256-GCM under the configured `security.manifest_key_env`. Off by default:
  the manifest holds canary plaintexts (the pack otherwise carries only its
  hash — see [the threat model](threat-model.md)).
