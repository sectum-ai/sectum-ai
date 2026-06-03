# BYOC runner — Snapshot subscription wrapper

The minimum wrapper that turns the OSS `sectum` CLI into a Snapshot
subscription: a monthly cron job that runs the probe suite against the
customer's stack, builds a tamper-evident evidence pack, and uploads it
to Sectum Cloud. Sectum Cloud emails the customer + the operator a
7-day presigned download link per file.

## Why BYOC

The Snapshot deliverable is the *signed evidence pack*. The probes
have to read the customer's actual stack — vector DB, RAG pipeline,
agent framework, MCP servers — so they run inside the customer's
environment (BYOC) rather than in Sectum Cloud. Only the signed pack
leaves the customer's network.

This is consistent with how every BYOC-mode Sectum engagement works
(see [the threat model](https://sectum.ai/docs/threat-model/)): the
customer keeps their secrets, the pack carries no raw customer
content, the evidence chain (RFC 3161 + Sigstore Rekor + in-toto) is
verifiable by any third party.

## What's in this directory

- [`upload-evidence-pack.sh`](./upload-evidence-pack.sh) — POSTs the
  pack to `/evidence/upload` with the bearer secret Sectum Cloud
  issued at subscription time.
- [`sectum.yaml.example`](./sectum.yaml.example) — minimal config
  pointing at the customer's adapters (Pinecone vector DB + Langfuse
  observability is the most common shape).
- [`crontab.example`](./crontab.example) — the 4-line cron entry that
  drives a monthly run.

## Wiring up

### 1. Subscribe (one-time)

Subscribe to Snapshot on [sectum.ai/pricing/](https://sectum.ai/pricing/).
Sectum Cloud issues you a bearer secret + a customer ID; both arrive
in the welcome email. Store the bearer in your secret manager (AWS
SSM SecureString, Hashicorp Vault, 1Password, kubectl secret —
whatever you use for everything else).

### 2. Author your `sectum.yaml` (one-time)

Copy `sectum.yaml.example` to `/etc/sectum/sectum.yaml` and edit:

- Point each adapter at your actual stack (vector DB DSN reference,
  RAG endpoint, observability backend, etc.). Use env-var references
  for credentials; the YAML never carries plaintext secrets.
- Choose the scenario seed (default `2026` is the spec-recommended
  starting point; reproducible).

Scaffold a config, then validate it parses by seeding into a scratch workdir you
discard afterwards (`sectum-ai seed` has no dry-run mode):

```sh
sectum-ai init --output /etc/sectum/sectum.yaml.draft
sectum-ai seed --workdir /tmp/sectum-validate --config /etc/sectum/sectum.yaml
rm -rf /tmp/sectum-validate
```

### 3. Install the wrapper + cron (one-time)

```sh
sudo install -m 0755 upload-evidence-pack.sh /usr/local/bin/sectum-upload
sudo crontab -u sectum /path/to/crontab.example
```

### 4. Wait for the first run

The cron fires at 03:00 on the 1st of every month. The runner:

1. Drops the existing `.sectum/` work directory (we want a fresh
   substrate every cycle — running against the same canaries month
   over month would let an attacker game the markers).
2. `sectum-ai seed` — provisions synthetic tenants + plants canaries.
3. `sectum-ai probe --output json` — runs the suite; pipes the run
   summary into the log so it's grepable for alerting.
4. `sectum-ai report` — builds the evidence pack
   (`evidence.json` + `audit-pack.pdf` + `attestation.intoto.json`,
   plus the RFC 3161 timestamp + optional Sigstore Rekor inclusion
   proof).
5. `sectum-upload` — POSTs the pack to Sectum Cloud, which emails the
   customer + operator the download links.

A typical run finishes in 5-15 minutes depending on adapter count.

## What you'll see

- An email to your `customer_email` with subject *"Sectum AI — your
  evidence pack for engagement &lt;eid-prefix&gt; is ready"* and one
  signed S3 URL per file in the pack.
- An identical email to your Sectum operator (CC) so they know the
  run landed.
- Your auditor / DPO can independently verify the pack with the OSS
  `sectum-ai verify` command — no Sectum installation needed beyond
  `pip install sectum-ai`.

## Failure modes

| Symptom | Cause | Action |
|---|---|---|
| `HTTP 401` from upload | Bearer secret expired or revoked | Re-fetch from the dashboard; rotate the env var |
| `HTTP 503` from upload | Sectum Cloud is bootstrapping or the secret has not been populated | Retry in 5 minutes; the runner is idempotent |
| `sectum-ai probe` exits 2 | Confirmed cross-tenant findings on the stack | Expected behaviour — the pack still uploads and your auditor sees the findings |
| `sectum-ai verify` exits 4 (your auditor's check) | Pack was tampered with in transit | Re-run the cycle; if it happens twice, contact us |

## Source

The shipping copy of this directory lives at
[`examples/byoc-runner/`](https://github.com/sectum-ai/sectum-ai/tree/main/examples/byoc-runner)
in the OSS repo. Apache 2.0. Fork it and adapt to your environment.
