# Configuration

`sectum init` scaffolds a `sectum.yaml` configuration file; every CLI command
that runs a workflow (`seed`, `probe`, `report`, `verify`, `erasure`,
`baseline`) accepts `--config sectum.yaml` to read its defaults from that
file. Explicit CLI flags — for example `--seed` or `--workdir` — always
override the values the config supplies.

## Top-level shape

A `sectum.yaml` is a single YAML mapping with four top-level sections, all
optional. Any omitted section uses its built-in defaults.

```yaml
scenario:
  seed: 2026
  corpus_profile: demo
workdir: .sectum
adapters:
  vector_store: ...
  cache: ...
  model: ...
  mcp: ...
  memory: ...
evidence:
  timestamper: local
```

Unknown top-level keys, unknown `evidence.timestamper` values, and malformed
YAML are rejected with a `ConfigError` and the CLI exits with code 3.

## `scenario`

Settings that drive substrate generation.

| Field | Type | Default | Notes |
|---|---|---|---|
| `seed` | int | `2026` | Drives every deterministic generator. |
| `corpus_profile` | str | `demo` | Placeholder for profile-driven corpora. |

## `workdir`

A filesystem path. The CLI writes the substrate, run record, evidence pack,
and audit pack here. Defaults to `.sectum`.

## `adapters`

A mapping from adapter-family name to that family's configuration. Each entry
takes a `kind` plus any backend-specific fields. A family that is omitted
defaults to a plain (non-leaky) fake.

Only the five families `sectum probe` drives — `vector_store`, `cache`,
`model`, `mcp`, `memory` — are read by the resolver today. Other family
names parse successfully but are not yet consumed by the CLI.

### `vector_store`

| `kind` | Fields | Notes |
|---|---|---|
| `fake` | `shared_index: bool = false`, `soft_delete: bool = false` | In-memory store. `shared_index: true` makes one index serve every tenant — the Class 2 retrieval-pivot leak. |
| `pgvector` | `dsn_env: str` *(or `dsn: str`)* | PostgreSQL with the pgvector extension. Prefer the env-var form. |
| `chroma` | `host: str = "localhost"`, `port: int = 8000` | ChromaDB server. Each tenant maps to its own collection. |
| `weaviate` | `host: str = "localhost"`, `port: int = 8080`, `grpc_port: int = 50051` | Weaviate server. Each tenant maps to its own collection. |

### `cache`

| `kind` | Fields | Notes |
|---|---|---|
| `fake` | `tenant_scoped: bool = true` | In-memory cache. `tenant_scoped: false` reproduces the Class 4 shared-key-space leak. |
| `redis` | `host: str = "localhost"`, `port: int = 6379`, `tenant_scoped: bool = true`, `prefix: str = "sectum"` | A Redis server. Keys are prefix-namespaced. |

### `model`

| `kind` | Fields | Notes |
|---|---|---|
| `fake` | `adapter_bleed: bool = false`, `prefix_cache: bool = false` | In-memory model. `adapter_bleed` reproduces Class 9; `prefix_cache` reproduces Class 5. |

No live model adapter is wired into the CLI resolver yet.

### `mcp`

| `kind` | Fields | Notes |
|---|---|---|
| `fake` | `confused_deputy: bool = false`, `token_passthrough: bool = false` | In-memory MCP server; both knobs reproduce the Class 7 flaws. |
| `stdio` | `command: str` *(required)*, `args: list[str] = []`, `tenant_argument: str | null = null` | Launches an MCP server as a subprocess and speaks MCP over stdio. |

### `memory`

| `kind` | Fields | Notes |
|---|---|---|
| `fake` | `shared_memory: bool = false` | In-memory store. `shared_memory: true` reproduces the Class 8 cross-tenant memory leak. |

No live memory adapter is wired into the CLI resolver yet.

## `evidence`

| Field | Type | Default | Notes |
|---|---|---|---|
| `timestamper` | `local` \| `rfc3161` | `local` | The development default is a local timestamper. |
| `tsa_url` | str | — | (`rfc3161` only) URL of the Time-Stamp Authority. |
| `rekor_url` | str | — | URL of the Sigstore Rekor instance. |

## Secrets and environment variables

Credentials never appear inline in `sectum.yaml` (the engineering spec,
section 17: *adapters never embed credentials*). Adapter blocks reference an
environment variable by name; the resolver reads its value at run time:

```yaml
adapters:
  vector_store:
    kind: pgvector
    dsn_env: SECTUM_PGVECTOR_DSN
```

```sh
export SECTUM_PGVECTOR_DSN=postgresql://user:pass@host/db
sectum probe --config sectum.yaml
```

A missing environment variable produces a `ConfigError` (`environment
variable not set: SECTUM_PGVECTOR_DSN`) and the CLI exits with code 3.

## Example: switching to live pgvector

```yaml
scenario:
  seed: 2026
workdir: .sectum
adapters:
  vector_store:
    kind: pgvector
    dsn_env: SECTUM_PGVECTOR_DSN
  cache:
    kind: redis
    host: localhost
    port: 6379
  # model, mcp, memory default to plain fakes
```

```sh
export SECTUM_PGVECTOR_DSN=postgresql://...
docker compose up -d pgvector redis
sectum seed --config sectum.yaml
sectum probe --config sectum.yaml
```

## Schema reference

The schema is implemented as pydantic models in `sectum.config` —
`SectumConfig`, `ScenarioConfig`, `AdapterConfig`, `EvidenceConfig` — and the
adapter resolver is `sectum.config.build_adapters`. `AdapterConfig` accepts
extra fields (the backend-specific `host`, `port`, `dsn_env`, leak knobs);
the per-family `build_*` functions validate them.
