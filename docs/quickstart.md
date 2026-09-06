# Quickstart

Install Sectum AI from PyPI ([`pip`](https://pip.pypa.io/) or
[`uv`](https://docs.astral.sh/uv/)):

```sh
pip install sectum-ai          # or: uv pip install sectum-ai  (or: uv tool install sectum-ai)
```

This installs the `sectum-ai` CLI and the core packages. Optional backends
(live vector stores, model/agent frameworks) are extras — see
[adapters.md](adapters.md).

## Drive the CLI

```sh
sectum-ai init                 # scaffold a sectum-ai.yaml (optional)
sectum-ai seed   --workdir .sectum-ai
sectum-ai probe  --workdir .sectum-ai
sectum-ai report --workdir .sectum-ai
sectum-ai verify .sectum-ai/evidence.json --allow-unanchored --allow-synthetic
```

Without `--config`, `probe` runs against the built-in demo stack with every leak
knob on, which is why the run reports findings and exits `2`.

The quickstart pack is timestamped by the offline local-dev token, which anyone
can regenerate — so `verify` requires `--allow-unanchored` to accept it as an
integrity-only check. It also ran against no live backend, so `verify` refuses
it as an attestation unless you pass `--allow-synthetic` (the `run-scope` check
says which surfaces were real). A pack built against configured adapters with
`report --tsa <url> --rekor` verifies without either flag, as independently
anchored tamper evidence.

## Run the flagship demo (from a clone)

The bundled examples live in the repo, so clone it to run them
([`uv`](https://docs.astral.sh/uv/) is the only prerequisite):

```sh
git clone https://github.com/sectum-ai/sectum-ai
cd sectum-ai
./examples/retrieval-pivot/run.sh
```

This seeds a four-tenant marker substrate, runs the probe suite against a
deliberately leaky shared vector index, assembles a tamper-evident evidence
pack, and verifies it.

| Command | Purpose |
|---|---|
| `sectum-ai init` | Scaffold a `sectum-ai.yaml` configuration file. |
| `sectum-ai seed` | Provision synthetic tenants, corpora, and canary markers. |
| `sectum-ai probe` | Run the probe suite and record findings. |
| `sectum-ai report` | Assemble a tamper-evident evidence pack (JSON and PDF). |
| `sectum-ai pack` | Bundle a portable, **sensitive** run pack (evidence + run + redacted config) for an auditor. |
| `sectum-ai verify` | Independently verify an evidence pack (or a bundle / run pack). |
| `sectum-ai erasure` | Run the GDPR Article 17 erasure-verification workflow. |
| `sectum-ai score` | Grade the run's multi-tenant isolation posture (A–F) — see the [scorecard](scorecard.md). |
| `sectum-ai calibrate` | Calibrate the semantic-detection threshold for your embedder. |
| `sectum-ai baseline` | Save a regression baseline, or compare a run against it. |
| `sectum-ai diff` | Compare two runs (or evidence packs); flag new/resolved leaks. |
| `sectum-ai adapters` | List the adapter families and the capabilities each built-in fake reports (it does not inspect installed live backends). |

Exit codes: `0` the command completed and found nothing it gates on; `2` a gating
result — confirmed leaks (`sectum-ai probe`), a regression (`sectum-ai diff` /
`baseline --compare` — including a live surface that fell back to the built-in fake
between the two runs, reported as `[SCOPE LOST]`, and a probe whose user-level steps
the later run did not run because its adapter cannot carry a user, reported as
`[BOUNDARY LOST]`, a probe the earlier run exercised and this one did not,
reported as `[COVERAGE LOST]`, an erasure surface the earlier run scanned to a
residue count and this one did not, reported as `[ERASURE NOT RESCANNED]`, and two
runs of different scenarios — a re-seed, other tenants
or users, where every finding "resolves" because its id embeds the markers and
principals — reported as `[SCENARIO CHANGED]`; a record from another schema line
is refused outright — as it is by `report`, `score`, and `verify`, which also
check the run record *inside* a pack), or residual / attestable-with-caveat data on an erased surface
(`sectum-ai erasure`, where data is presumed retained); `3` config or adapter error —
including a `probe` run in which nothing interrogated the stack, and a `report` on
a run that names no probe (or was recorded against a since re-seeded substrate);
`4` evidence verification failure.

`0` means "nothing this command gates on", not "no leaks": the reporting commands do
not gate, so `sectum-ai score` exits `0` whatever the letter — a grade of `F` on a run
riddled with confirmed leaks still exits `0`. `sectum-ai probe` is the CI gate.

## Verify a real data subject's erasure (by id and by content)

`sectum-ai erasure --subject <manifest.yaml>` verifies a **real** data subject's
erasure after your own deletion has run for a GDPR Article 17 / CCPA §1798.105
request, rather than scanning the synthetic canaries. It writes a per-subject signed
attestation, using two methods:

- **By id** — confirm each of the subject's records is gone by id (deterministic);
  the vector store (`fetch`) and semantic cache (`get`) expose a by-id check today,
  as does tracing (`fetch_trace`), supported by the Langfuse, LangSmith, Phoenix,
  Helicone, and Datadog adapters — the generic OpenTelemetry reader has no by-id
  lookup, so its tracing surface reads `NOT_COVERED`.
- **By content fingerprint** — probe the vector store (a semantic query), the model
  (an inference call), the agent-memory store (a keyword recall), and the derived
  full-text search index (a search) with the subject's known content and check whether
  it still surfaces, catching *derived* residual — an embedding copy, residual
  *memorization* in a fine-tune/adapter, a lingering memory entry, or an un-purged
  index document — that a by-id check would miss. The model is checked only on a
  **per-tenant adapter**: a shared-weights model has no untrained tenant to serve
  as a base-knowledge control, so a completion cannot be told apart from what the
  base model already knew, and it reads `NOT_COVERED` — as does a serving-only
  endpoint, which trained nothing.

`records` carries **ids only** (no PII); `fingerprints` carries the subject's
**content** to probe — used only to query, and stored as a **hash** in the
attestation, never in the clear:

```yaml
subject_ref: "dsr-2026-00042"   # your opaque reference for the request; no PII
records:
  vector_db: ["doc-9c1f", "doc-aa20"]   # the subject's vector ids
  semantic_cache: ["qa:7f3e", "qa:1b09"]
fingerprints:
  vector_db: ["Maria Chen", "maria@example.com"]   # content to probe; hashed in the attestation
  model_adapter: ["Maria Chen, 12 Elm Street, Springfield"]  # a specific phrase: see below
  agent_memory: ["Maria Chen"]                     # probe long-term agent memory (recall)
  search_index: ["Maria Chen"]                     # probe the derived full-text search index
```

```sh
sectum-ai erasure --subject subject.yaml --config sectum-ai.yaml
```

A surface is `ERASED` only when every supplied id is gone **and** no supplied content
still surfaces; every other surface reads `NOT_COVERED`, so the attestation never
implies coverage it did not verify. Fingerprint probing is best-effort — a clean
result is evidence the content no longer surfaces, not proof of absence. On the
model surface the check is prefix-continuation against two controls — a
same-shaped prefix naming nobody, and (on a per-tenant model) the same prefix as
a tenant that trained nothing — so a completion any model would produce
(`@example.com`, a common surname, a public figure's full name) is not counted as
recall; give it a specific phrase, since one the check cannot verify — a trailing
part under six characters (which is what makes most bare two-word names
unverifiable: "Doe" is three), or a prefix with no scrambled form — makes the
model surface read
`NOT_COVERED` for the subject, and the run says how many it could not check. Exit
codes match the canary flow: `0` clean, `2` residual remains, `3` inconclusive —
at least one scanned surface could not establish absence (a full similarity page
without the phrase, or no pre-erasure baseline), so the run is not attested even
if other surfaces verified cleanly.

## Bundle a portable run pack

`sectum-ai pack` rolls a completed run into one self-verifying `run-pack.zip` — the
signed evidence pack and its sidecars, plus `run.json`, the (secret-redacted)
config, and a `PACK-README.md` — so an auditor can both verify it and see exactly
what was tested:

```sh
sectum-ai report --workdir .sectum-ai          # produce the evidence pack first
sectum-ai pack   --workdir .sectum-ai --config sectum-ai.yaml
sectum-ai verify .sectum-ai/run-pack.zip --allow-unanchored --allow-synthetic
```

> **A run pack is sensitive.** Unlike the evidence pack — which is redacted — a run
> pack carries `run.json` (evidence spans) and, with `--include-manifest`, the
> ground-truth marker manifest (sealed AES-256-GCM under
> `security.manifest_key_env`). The bundled config has inline secrets redacted —
> secret-named values, `headers` maps, credentials embedded in a URL, and
> credential-shaped strings (`*_env` references are kept) — but the pack still
> reveals what was tested, so share it only with trusted parties.

## Read the probe summary from CI

`sectum-ai probe` defaults to a human-readable summary. Pass `--output json` to
emit a single JSON object on stdout instead — convenient for CI dashboards
that want to act on the headline metrics without scraping prose:

```sh
sectum-ai probe --workdir .sectum-ai --output json | jq '.retrieval_pivot_rate'
```

For GitHub code scanning (or any SAST dashboard), pass `--output sarif` instead to
emit a SARIF 2.1.0 log of the findings — one rule per probe, one result per
finding. Upload it with `github/codeql-action/upload-sarif` and the cross-tenant
findings surface in the repository's **Security** tab. An unverified candidate is
capped at SARIF `note`, and so is a confirmed finding whose backing surface ran
against a built-in fake — its message is prefixed `[synthetic surface - ...]`, as is
one on a surface the record does not describe (`[surface provenance not recorded - ...]`), and each
carries `backingSurface` and `surfaceProvenance`, so a no-`config` demo run is
entirely `note`-level. The signed `evidence.json` stays the canonical record.

For a GRC platform or auditor, pass `--output oscal` to emit a **NIST OSCAL 1.1.x
assessment-results** document so the run can be ingested as a machine-readable,
control-mapped assessment:

```sh
sectum-ai probe --workdir .sectum-ai --output oscal > assessment-results.json
```

It carries one OSCAL *observation* per finding (the marker-grounded evidence) and
one OSCAL *finding* per mapped framework control (SOC 2, ISO 27001, GDPR, …) whose
`status.state` reflects the run honestly — an isolation control is
`not-satisfied` when a cross-principal leak was *confirmed on a live surface*,
otherwise `satisfied`; an erasure control (GDPR Art. 17, CCPA §1798.105, titled
"erasure verification") is `not-satisfied` when a live surface kept a residual
marker after the erasure. A finding from a surface that ran against the built-in
fake moves no control (the result names those surfaces as excluded), an
unverified candidate is recorded as evidence but never on its own flips a control
to failed, and the coverage disclaimer (these mappings are test-coverage
assertions, not legal certification) rides in the metadata remarks. A run with no
live surface — every surface the built-in fake, or provenance unrecorded — states
**no** control finding: its observations still ship, the result says no control
objective was assessed, and the metadata props carry the run's surface provenance
(the SARIF carries it as a run property) so a GRC platform cannot read a demo as
a production assessment.
The OSCAL is a derived, unsigned projection; the signed `evidence.json` stays the
canonical record.

The summary carries the `run_id`, the probe count, the confirmed-finding
count, the headline Retrieval-Pivot Rate (and, when two or more real embedding
models are configured, a **modelled** embedding-model gradient over the sweep's
own shared index — not a breakdown of the measured rate), the per-probe finding
counts, the run's
`surface_provenance` with `confirmed_on_live_surfaces` (the confirmed findings
that describe your stack rather than a built-in fake), `user_steps_dropped`
(probes whose user-level steps were not run because the adapter cannot carry a
user), and a `run_path` pointer to the full `run.json` on disk. Errors still print
to stderr and exit codes are unchanged.

The Retrieval-Pivot Rate is reported with a **95% Wilson confidence interval**
and its sample size, so a small-`n` rate is never presented as a precise number:

```text
retrieval-pivot rate: 81.2% (95% CI 68.1%-89.8%, n=48)
```

The JSON summary carries the same uncertainty as machine-readable fields —
`retrieval_pivot_n` and `retrieval_pivot_k` (the binomial counts behind the rate)
and `retrieval_pivot_rate_ci` (the `[low, high]` interval) — so a CI dashboard can
act on the rate's precision, not a bare point estimate. Because the counts are in
the signed `evidence.json`, the interval is reproducible by a third party.

The per-embedding-model gradient (`retrieval_pivot_rate_by_model`) is **not** a
second measured rate: it is computed over the substrate under a modelled shared
index, not against the adapters the run drove. The text renderer labels it in
place and the JSON summary carries the same words in
`retrieval_pivot_rate_by_model_note`, so a dashboard cannot mistake it for the
headline.
