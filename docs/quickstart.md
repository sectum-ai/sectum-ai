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
sectum-ai verify .sectum-ai/evidence.json --allow-unanchored
```

The quickstart pack is timestamped by the offline local-dev token, which anyone
can regenerate — so `verify` requires `--allow-unanchored` to accept it as an
integrity-only check. A production pack built with `report --tsa --rekor`
verifies without the flag, as independently anchored tamper evidence.

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
| `sectum-ai verify` | Independently verify an evidence pack. |
| `sectum-ai erasure` | Run the GDPR Article 17 erasure-verification workflow. |
| `sectum-ai baseline` | Save a regression baseline, or compare a run against it. |
| `sectum-ai diff` | Compare two runs (or evidence packs); flag new/resolved leaks. |
| `sectum-ai adapters` | List installed adapters and their capabilities. |

Exit codes: `0` no confirmed leaks; `2` a gating result — confirmed leaks
(`sectum-ai probe`), a regression (`sectum-ai diff` / `baseline --compare`), or
residual / attestable-with-caveat data on an erased surface (`sectum-ai erasure`,
where data is presumed retained); `3` config or adapter error; `4` evidence
verification failure.

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
capped at SARIF `note`, and the signed `evidence.json` stays the canonical record.

For a GRC platform or auditor, pass `--output oscal` to emit a **NIST OSCAL 1.1.x
assessment-results** document so the run can be ingested as a machine-readable,
control-mapped assessment:

```sh
sectum-ai probe --workdir .sectum-ai --output oscal > assessment-results.json
```

It carries one OSCAL *observation* per finding (the marker-grounded evidence) and
one OSCAL *finding* per mapped framework control (SOC 2, ISO 27001, GDPR, …) whose
`status.state` reflects the run honestly — `not-satisfied` when a cross-tenant leak
was *confirmed*, otherwise `satisfied` ("tested, no confirmed cross-tenant
leakage"). An unverified candidate is recorded as evidence but never on its own
flips a control to failed, and the coverage disclaimer (these mappings are
test-coverage assertions, not legal certification) rides in the metadata remarks.
The OSCAL is a derived, unsigned projection; the signed `evidence.json` stays the
canonical record.

The summary carries the `run_id`, the probe count, the confirmed-finding
count, the headline Retrieval-Pivot Rate (and per-embedding-model breakdown
when Class 2 swept models), the per-probe finding counts, and a `run_path`
pointer to the full `run.json` on disk. Errors still print to stderr and
exit codes are unchanged.

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
