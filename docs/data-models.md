# Core data models

Sectum AI's data contracts are Pydantic v2 models in the `sectum_ai.spec` package
(distributed as `sectum-ai-spec`, imported as `sectum_ai.spec`). They are the stable
interface between the substrate, the probes, and the evidence chain, and their
**JSON Schema is published** so a third party can validate an evidence pack
without running Sectum.

## The models

| Model | Purpose |
|---|---|
| `Scenario` | The run definition: `scenario_id`, `seed`, `tenants`, `corpus_profile`, `shared_entities`, `embedding_models`. |
| `SyntheticTenantSpec` | One synthetic tenant: `tenant_id`, `display_name`, `industry`, `corpus_size`, and optional `users`. |
| `Principal` | An isolation boundary Sectum verifies — a tenant, or a user within one (ADR-0006). |
| `Marker` | A planted canary: `marker_id`, `marker_type`, `owner_tenant_id`, `owner_user_id?`, `plaintext`, `embedding_ref?`, `planted_locations[]`. |
| `PlantedLocation` | Where a marker was planted in a document — `doc_id` plus the field (`body`, `title`, `metadata`). |
| `CorpusDocument` | One synthetic document: `doc_id`, `tenant_id`, `doc_type`, `title`, `content`, `metadata`, `marker_ids`. |
| `GroundTruthManifest` | The authoritative marker record: `manifest_id`, `scenario_hash`, `markers[]`. Its canonical hash anchors the evidence chain. |
| `Substrate` | The seeded world: the scenario, tenants, documents, and manifest. |
| `ProbeStep` | One planned action: `step_id`, `probe_id`, `actor_tenant_id`, `actor_user_id?`, `action`, `payload`. |
| `Observation` | A step's result: `step_id`, `surface`, `raw_response`, `structured?`, `latency_ms?`, `access_outcome?`. |
| `Finding` | A detected leak: severity, confidence, status (`confirmed`/`unverified`), owner vs observed principal, `marker_id?`, `evidence_span`, `surface`, and the OWASP/ATLAS/NIST control IDs. |
| `RunMetrics` | Headline metrics: per-probe counts, the Retrieval-Pivot Rate, erasure residue counts, the per-surface erasure **coverage** block (surface → `CoverageVerdict`), side-channel effect sizes, and the Class 3/6/10 rates. |
| `RunResult` | A whole run: ids, timestamps, scenario/manifest hashes, adapter and probe versions, `findings[]`, `metrics`. |
| `EvidencePack` | The signed bundle: the run result, manifest hash, timestamp token, Rekor proof, control mappings, PDF reference, and `schema_version`. |
| `ControlMapping` | A finding's mapped compliance control (framework, control id, assertion) — see the [compliance mappings](compliance-mappings.md). |

`Scenario`, `GroundTruthManifest`, `Substrate`, `RunResult`, and `EvidencePack`
each carry a `schema_version`, so a verifier can refuse a pack whose major/minor
schema it does not understand. The current `SCHEMA_VERSION` is **0.5.0** — it
added the Retrieval-Pivot Rate's binomial counts (`retrieval_pivot_n`,
`retrieval_pivot_k`) and a Wilson confidence interval (`retrieval_pivot_rate_ci`)
to `RunMetrics`, so the headline rate's uncertainty is reproducible from the
signed evidence (see the
[Class 2 attack catalog page](attack-catalog/class-02-rag-entity-bleed.md)). The
prior **0.4.0** added the per-surface erasure `coverage` block to `RunMetrics`
(see the [erasure attack catalog page](attack-catalog/class-11-erasure.md)).

## Published JSON Schema

The Draft 2020-12 JSON Schemas are generated from the Pydantic models by
[`scripts/gen_schemas.py`](https://github.com/sectum-ai/sectum-ai/blob/main/scripts/gen_schemas.py)
and committed under
[`packages/spec/src/sectum_ai/spec/schemas/`](https://github.com/sectum-ai/sectum-ai/tree/main/packages/spec/src/sectum_ai/spec/schemas)
(shipped inside the `sectum-ai-spec` wheel). Each schema's version-pinned `$id`
embeds the `SCHEMA_VERSION`. A parity test fails CI if a committed schema drifts
from its model, so the published schema always matches the code.

The committed schemas are: `Scenario`, `Marker`, `CorpusDocument`,
`GroundTruthManifest`, `Substrate`, `ProbeStep`, `Observation`, `Finding`,
`RunMetrics`, `RunResult`, `EvidencePack`, and `ControlMapping`. (`Scenario`
embeds `SyntheticTenantSpec` inline, so that nested model has no standalone
schema file.)

## Canonical hashing

Hashes throughout (the scenario hash, the manifest hash, the run digest) are
computed over a **canonical JSON form** — sorted keys, compact separators, UTF-8,
finite floats via CPython's deterministic shortest round-tripping `repr`, and an
explicit refusal of non-finite floats (ADR-0021). The same logical content always
produces the same digest across machines, which is what makes the
[reproducibility contract](substrate.md#reproducibility-contract) and the
[evidence chain](evidence-chain.md) verifiable by an independent party.

## See also

- [Marker substrate](substrate.md) — how `Marker`, `GroundTruthManifest`, and
  `Substrate` are produced.
- [Evidence chain](evidence-chain.md) — how `RunResult` becomes an
  `EvidencePack`.
- [Compliance mappings](compliance-mappings.md) — how a `Finding`'s control IDs
  map to SOC 2, ISO 27001, GDPR, and the rest.
