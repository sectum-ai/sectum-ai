# Open WebUI run — Sectum AI against a self-hosted Open WebUI

A push-button harness that runs **Sectum AI** against a **self-hosted
[Open WebUI](https://github.com/open-webui/open-webui)** instance you own and are
authorized to test. It stands up Open WebUI in Docker, provisions four synthetic
tenants from Sectum's seeded marker substrate, and probes Open WebUI's real
multi-tenant surfaces — the flagship being the **organic entity-bleed Retrieval
Pivot (Class 2)** through Open WebUI's chat-with-knowledge endpoint.

> **Lawful-testing note.** This drives **our own** Open WebUI deployment (we run
> the container, we own the data). The corpora are Sectum's **synthetic** marker
> substrate — no real PII or secrets. Detection is **manifest-grounded**: a
> "leak" is a ground-truth canary surfacing in the wrong tenant's session, never
> a heuristic. This is the responsible-disclosure / lawful-testing posture from
> the operator's playbook.

## What this validates

| Mode | Open WebUI config | Expected result | Meaning |
|---|---|---|---|
| `shared` | one **public** knowledge base holds every tenant's docs | **Retrieval-Pivot Rate ≈ 100 %** | the realistic shared-collection misconfiguration leaks across tenants |
| `isolated` | each tenant attaches **only its own Private** knowledge base | **Retrieval-Pivot Rate ≈ 0 %** | a properly scoped deployment does not leak |

The contrast between the two runs *is* the evidence: the rate is a property of
the **configuration**, and Sectum proves which one is deployed (the same point
the [`retrieval-pivot`](../retrieval-pivot/README.md) demo makes, here against a
real product).

## Architecture

```
  sectum-ai probe  ──(rag.ask {tenant,query})──►  rag_shim.py  ──(POST /api/chat/completions
       │                                              │            as the tenant's user,
       │   manifest-grounded detection                │            knowledge collection attached)──►  Open WebUI
       │   scans answer + retrieved chunks            │                                                   │
       ◄──────────────  {answer, retrieved} ──────────┘  ◄────────  sources[].document[] (RAG chunks) ────┘
```

- **Sectum's substrate is ground truth.** `sectum-ai seed` generates the four
  synthetic-tenant corpora and the hashed ground-truth manifest (which
  HARD_CANARY belongs to which tenant). The pivot documents name shared organic
  entities (Maria Chen, Northwind Supply Co, SOC 2, …) **and** carry a canary —
  the Retrieval-Pivot condition.
- **The provisioning script uploads** each tenant's marker-bearing docs into
  Open WebUI via its REST API, preserving the planted canaries verbatim.
- **The RAG shim** bridges Sectum's `{tenant,query} → {answer,retrieved}` HTTP
  contract to Open WebUI's OpenAI-compatible chat-with-knowledge API, querying
  **as the tenant's own user** so Open WebUI's real retrieval + authorization
  path runs.
- **Sectum detects** the foreign canary in Open WebUI's answer + retrieved
  source chunks by exact match against the manifest — zero false positives.

## Adapter mapping (why the RAG shim, not the Chroma adapter)

| Open WebUI surface | Sectum adapter | How |
|---|---|---|
| chat-with-knowledge (`POST /api/chat/completions` + `files:[{type:collection}]`) | **`rag` → `kind: http`** | via `scripts/rag_shim.py`; the Class 2 `rag-pipeline-bleed` probe drives it |
| file object API (`GET /api/v1/files/{id}/content`) | Class 1 analogue | `scripts/class1_boundary_fetch.py` (BOLA-style cross-user fetch) |
| embedded ChromaDB (`$DATA_DIR/vector_db`) | **not** the `chroma` adapter | see below |

**Why not point Sectum's `chroma` adapter at Open WebUI's ChromaDB?** Sectum's
Chroma adapter scopes every read to its *own* per-tenant collection
(`sectum-ai-<tenant.hex>`), and `sectum-ai probe` upserts the substrate into
those collections itself. Pointed at Open WebUI's Chroma it would test Sectum's
own collection layout living inside Open WebUI's Chroma process — **not** Open
WebUI's retrieval isolation. Open WebUI's real isolation boundary is its
chat-with-knowledge API (which enforces per-collection read access by default,
`BYPASS_RETRIEVAL_ACCESS_CONTROL=false`), so that is what we exercise via the
shim. The vector-store adapter therefore stays a fake in the config.

## Class → surface matrix for Open WebUI

| Class | Probe | Open WebUI surface | Status |
|---|---|---|---|
| **1 — boundary fetch** | `tenant-boundary-fetch` (native script) | file object API (`/api/v1/files/{id}/content`) | **READY** — `scripts/class1_boundary_fetch.py` |
| **2 — RAG entity-bleed (FLAGSHIP)** | `rag-pipeline-bleed` | chat-with-knowledge | **READY** — the headline run |
| 3 — RAG poisoning | `rag-poisoning` | knowledge base (write) | **READY-with-setup** — a user with `workspace.knowledge` write can add a poison doc under a lure phrase to a shared KB; not in the default dry-run (needs the write-permission config). Documented in "Extending". |
| 4 — semantic cache | `semantic-cache-contamination` | — | **N/A** — vanilla Open WebUI has no cross-tenant semantic/prompt cache surface (chat responses are not served from a shared semantic cache keyed without tenant identity). |
| 5 — KV-cache timing | `kv-cache-timing` | — | **N/A** — no shared KV prefix-cache timing surface is exposed by the Open WebUI API; this is a model-server property, not Open WebUI's. |
| 6 — embedding inversion | `embedding-inversion` | (vector store) | **N/A here** — requires reading raw cross-tenant embeddings; Open WebUI does not expose foreign-tenant vectors over its API, and the Class 2 shared-collection path already returns the *plaintext* chunk (inversion is unnecessary — "leaky retrieval returns plaintext"). |
| 7 — agent tool-call hijack | `agent-tool-hijack` | tool/`tool_ids` on chat completions | **CONDITIONAL** — Open WebUI's tool-calling exists, but a clean cross-tenant confused-deputy test needs tools provisioned per user; out of scope for the dry-run. Documented in "Extending". |
| 8 — memory contamination | `memory-contamination` | per-user Memories | **READY-with-setup** — Open WebUI has a per-user Memories feature; a cross-user memory-bleed probe is wireable via `/api/v1/memories` (analogous to the file script). Not in the default dry-run. |
| 9 — LoRA cross-tenant | `lora-cross-tenant` | — | **N/A** — Open WebUI does not fine-tune or serve per-tenant LoRA adapters; it proxies to a model backend. |
| 10 — IKEA extraction | `ikea-extraction` | chat-with-knowledge | **READY-with-setup** — the multi-turn benign-extraction variant runs over the same shared-KB surface as Class 2; the flagship single-query pivot already demonstrates the bleed. |
| **11 — erasure (WEDGE)** | `gdpr-erasure-verification` | knowledge base + file + (Chroma) | **READY** — delete a tenant's KB/files via the API, then re-scan to confirm no residual canary; marquee question: do the vectors survive file deletion? See "Class 11". |
| 12 — evidence chain | (cross-cutting) | — | the signed pack `sectum-ai report` / `verify` produces. |

> The dry-run wires the three the operator asked for first — **Class 1, Class 2
> (flagship), and the building blocks for Class 11** — push-button. The
> READY-with-setup classes have a documented config to make them meaningful but
> are not part of the validated dry-run.

## Prerequisites

- Docker (the harness checks `docker info`).
- [`uv`](https://docs.astral.sh/uv/) — the scripts run `sectum-ai` via `uv run`.
- `curl`, `python3` (standard library only — no extra Python deps).

## Quick start (dry-run)

```sh
cd examples/open-webui-run

# 1. configure (lab secrets only; never committed)
cp .env.example .env
# edit .env: set WEBUI_SECRET_KEY (openssl rand -hex 32), admin/tenant passwords.
# leave SECTUM_OWUI_MODE=shared to validate the flagship leak first.

# 2. stand up Open WebUI (pinned v0.9.6) + a tiny Ollama, wait for health, pull the model
./scripts/up.sh

# 3. seed Sectum's substrate + upload each tenant's corpus into Open WebUI Knowledge
./scripts/provision.sh

# 4. start the RAG shim (background) in the mode from .env
./scripts/serve_shim.sh &

# 5. dry-run: flagship Class 2 through chat-with-knowledge + Class 1 file fetch
./scripts/run.sh
```

To validate the **isolated** contrast, set `SECTUM_OWUI_MODE=isolated` in `.env`,
restart the shim (`pkill -f rag_shim.py; ./scripts/serve_shim.sh &`), and re-run
`./scripts/run.sh` — expect Retrieval-Pivot Rate ≈ 0 %.

Tear everything down (removes the Open WebUI data volume + local artifacts):

```sh
./scripts/teardown.sh
```

## Files

| Path | Purpose |
|---|---|
| `compose.yaml` | Open WebUI (pinned) + Ollama, health check, named data volume. |
| `.env.example` | All env vars (image tag, port, secret key, accounts, mode). Copy to `.env`. |
| `scripts/up.sh` | Bring up the lab, wait for health, pull the chat model. |
| `scripts/provision.sh` | `sectum-ai seed` + upload corpora (wraps `provision_owui.py`). |
| `scripts/provision_owui.py` | Registers admin + 4 users, creates KBs, uploads marker docs, writes `out/tenant-map.json`. |
| `scripts/rag_shim.py` | Sectum `{tenant,query}` ⇄ Open WebUI chat-with-knowledge bridge. |
| `scripts/serve_shim.sh` | Launch the shim in the configured mode. |
| `scripts/class1_boundary_fetch.py` | Class 1 cross-user file-fetch probe (manifest-grounded). |
| `scripts/run.sh` | The dry-run: flagship Class 2 + Class 1, prints readiness summary. |
| `scripts/teardown.sh` | Stop + wipe volumes + clear `out/`. |
| `sectum-ai.yaml` | Shared/leak config (RAG → shim). |
| `sectum-ai.isolated.yaml` | Isolated config (expected RPR ≈ 0 %). |

## Environment (what gets created)

- **Image:** `ghcr.io/open-webui/open-webui:v0.9.6` (pinned; latest stable as of
  2026-06, post the 0.9.0 / 0.9.5 cross-tenant CVE fixes) + `ollama/ollama:0.6.8`.
- **URL:** `http://localhost:3000` (override `OWUI_PORT`).
- **Accounts:** `admin@sectum.test` (admin — the first registered user) plus four
  tenant users mapped 1:1 to the substrate tenants:
  `acme@sectum.test` (Acme Robotics), `globex@sectum.test` (Globex Logistics),
  `initech@sectum.test` (Initech Financial), `hooli@sectum.test` (Hooli Health).
- **State:** the named Docker volume `sectum-owui-data` holds `DATA_DIR`
  (`/app/backend/data`): `webui.db` (users, knowledge bases, access grants),
  `uploads/`, and the embedded ChromaDB at `vector_db/`. Wiped by `teardown.sh`.
- **`out/`** (gitignored) holds the seeded substrate, `tenant-map.json` (JWTs —
  treat as a lab secret), shim logs, and Sectum run records / evidence.

### Open WebUI settings that matter (set in `compose.yaml`)

- `WEBUI_SECRET_KEY` — JWT signing key (from `.env`, never inlined).
- `ENABLE_SIGNUP=true` — lets the script register the admin; Open WebUI then
  **auto-disables open signup after the first user**, so the script creates the
  four tenant users via the admin-only `POST /api/v1/auths/add`.
- `BYPASS_MODEL_ACCESS_CONTROL=true` — Open WebUI gates *model* access per user;
  without this a fresh tenant user sees zero models and chat 400s "Model not
  found". This is the **model** boundary only.
- `BYPASS_RETRIEVAL_ACCESS_CONTROL=false` (default) — the **knowledge/retrieval**
  boundary stays **enforced**: a user can only retrieve from a collection it can
  read. The `shared`-mode leak comes from the shared KB being **public-read** and
  holding every tenant's docs — not from disabling this check.

## How the leak is set up (Open WebUI RBAC)

Open WebUI's default RBAC shaped the design (verified empirically against the
live instance):

1. A **regular user cannot create a knowledge base** (`POST
   /api/v1/knowledge/create` needs admin or the `workspace.knowledge`
   permission). So the **admin owns and creates every KB** and uploads the files.
2. Sharing uses **`access_grants`** (v0.9.x): a list of
   `{principal_type, principal_id, permission}`. **Public-read** is the wildcard
   principal `{"principal_type":"user","principal_id":"*","permission":"read"}`;
   a **per-user** grant uses that user's id.
3. The provisioning therefore:
   - grants each tenant's **private KB** read to exactly that tenant user;
   - grants the **shared KB** public read;
   - uploads **separate copies** of each marker doc to the private KB and the
     shared KB (so the private-object boundary stays distinct from the
     by-design public reachability of the shared collection).
4. Tenant users **query as themselves** (their own JWT). In `isolated` mode they
   attach their own private KB (readable → only their own docs). In `shared` mode
   they attach the public shared KB (readable by all → foreign tenants' docs
   surface = the Retrieval Pivot).

## Class 11 (erasure — the wedge)

The building blocks are ready: provisioning records each tenant's KB id and
private file ids in `tenant-map.json`. An erasure attestation deletes a target
tenant's KB + files via `DELETE /api/v1/knowledge/{id}` and
`DELETE /api/v1/files/{id}`, then re-runs the Class 2 query and the Class 1 fetch
to confirm **no residual canary** remains — and, crucially, inspects whether the
**vectors survive file deletion** in the embedded ChromaDB (an orphaned,
still-queryable collection is the marquee Class 11 finding). The operator's
official run wires this with `sectum-ai erasure` once the live KB/file delete
adapters land; until then the two re-scan scripts give a manual attestation.

## Operator's actual run (NOT done by the dry-run)

The dry-run stops at **validated readiness**. The official, evidence-generating
run is the operator's to trigger. The exact sequence, per mode:

```sh
cd examples/open-webui-run
set -a && source .env && set +a

# --- shared (leak) evidence -------------------------------------------------
export SECTUM_OWUI_MODE=shared
./scripts/up.sh
./scripts/provision.sh
pkill -f rag_shim.py 2>/dev/null; ./scripts/serve_shim.sh &

# Flagship Class 2 over Open WebUI chat-with-knowledge:
uv run sectum-ai probe   --workdir out/sectum --config sectum-ai.yaml --probe rag-pipeline-bleed
# Class 1 cross-user file fetch:
python3 scripts/class1_boundary_fetch.py out/sectum/substrate.json out/tenant-map.json

# Signed evidence pack (RFC 3161 timestamp + Rekor transparency log) + verify:
uv run sectum-ai report  --workdir out/sectum --config sectum-ai.yaml \
    --tsa https://freetsa.org/tsr --rekor --bundle
uv run sectum-ai verify  out/sectum/evidence-bundle.zip

# --- isolated (control) evidence -------------------------------------------
export SECTUM_OWUI_MODE=isolated
pkill -f rag_shim.py 2>/dev/null; ./scripts/serve_shim.sh &
uv run sectum-ai probe   --workdir out/sectum-isolated --config sectum-ai.isolated.yaml --probe rag-pipeline-bleed
uv run sectum-ai report  --workdir out/sectum-isolated --config sectum-ai.isolated.yaml \
    --tsa https://freetsa.org/tsr --rekor --bundle
uv run sectum-ai verify  out/sectum-isolated/evidence-bundle.zip

# --- the regression-gate story: shared vs isolated --------------------------
uv run sectum-ai diff out/sectum-isolated/run.json out/sectum/run.json
```

Chain of custody (per the playbook): record the image tag, the two run ids + pack
hashes, the mode/scope, and timestamps under `internal/engagements/` (outside
this OSS repo).

## Extending to the READY-with-setup classes

- **Class 3 (RAG poisoning):** grant a tenant user the `workspace.knowledge`
  *write* permission, have it add a poison doc carrying a lure phrase to the
  shared KB, then run `sectum-ai probe --probe rag-poisoning` so another tenant's
  query of the lure retrieves it.
- **Class 8 (memory contamination):** add a small script mirroring
  `class1_boundary_fetch.py` against `POST/GET /api/v1/memories` to plant and
  cross-read per-user memories.
- **Class 10 (IKEA extraction):** the multi-turn benign-extraction probe runs
  over the same shared-KB surface as Class 2.
