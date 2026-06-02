# Changelog

All notable changes to Sectum AI are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **The embedded tool version now comes from the installed package, not a
  hard-coded `0.0.0`.** `cli/app.py` defined `__version__ = "0.0.0"`, and that
  literal was stamped into every `RunResult`'s `adapter_versions` /
  `probe_versions` — so every signed, timestamped evidence pack and audit PDF
  attested tool version `0.0.0` on the shipped `0.1.0` release (and `sectum
  --version` printed it), corrupting the tamper-evident artifact and making
  `baseline` / `diff` version-blind. It now resolves via
  `importlib.metadata.version("sectum-ai")` (with a `0.0.0+unknown` fallback for an
  uninstalled tree); the committed `docs/samples/` packs were regenerated so the
  published samples attest `0.1.0`.
- **`sectum verify` now re-checks the in-toto attestation sidecar.** `report` /
  `erasure` write `attestation.intoto.json` beside the pack, but `verify` never
  re-verified it, so a swapped sidecar handed to an in-toto-aware pipeline got no
  protection from the OSS verifier. `verify` now re-runs `verify_in_toto_statement`
  against any sibling sidecar (itemized as an `in-toto-attestation` check; a
  statement that no longer binds the pack's run digest fails with exit `4`), and
  the command is wrapped in the typed-error decorator so an escaping `SectumError`
  maps to the documented exit code rather than an opaque `1`.
- **A confirmed leak can no longer be dropped from the headline count by an
  earlier unverified duplicate.** `dedupe_findings` collapsed findings that share
  a `finding_id` by keeping the *first* one seen, status-blind — and the
  `finding_id` does not encode status. So when the same marker surfaced on the
  same surface across multiple steps of one probe as both a semantic-only
  `UNVERIFIED` candidate and a judge-`CONFIRMED` leak, whichever came first won;
  an `UNVERIFIED`-first ordering silently discarded the `CONFIRMED` finding and
  undercounted the cross-tenant-leak headline. Dedupe is now status-aware —
  `CONFIRMED` outranks `UNVERIFIED`, then higher severity, then higher confidence
  — so a real leak is always retained regardless of detection order.
- **The CLI config resolver now threads `user_scoped` into the model, memory, and
  MCP fakes.** Only the vector-store and cache fake branches passed the
  `user_scoped` knob through; the `model`, `memory`, and `mcp` fakes dropped it,
  so a `sectum.yaml` requesting per-user (ADR-0006) isolation on those families
  silently built a tenant-only fake and verified the wrong boundary. All three
  fake branches now thread `user_scoped`, with resolver parity tests.
- **The stdlib HTTP adapters now wrap transport and JSON errors in
  `AdapterError`.** The generic HTTP agent (`agent/http.py`), HTTP RAG pipeline
  (`rag/http.py`), and the OpenTelemetry trace store's `query`/`tenant_values`
  (`observability/otel.py`) let a raw `urllib` error (connection refused,
  timeout, HTTP error) or a `json.JSONDecodeError` from a non-JSON response
  escape, bypassing the CLI's typed-error exit code (`3`) and surfacing as an
  opaque traceback. Each now raises `AdapterError` (matching the OTel `purge`
  path), so an unreachable or misbehaving backend fails cleanly.
- **A present-but-corrupt `substrate.json` / `run.json` / `baseline.json` now
  exits `3` (config error) instead of crashing.** The CLI's `_load_substrate`,
  `_load_run`, and `sectum baseline --compare` called `model_validate_json`
  unguarded, so a malformed artifact raised an unhandled `ValidationError` that
  Typer reported as an opaque exit `1` rather than the documented config-error
  exit `3`. Each load now catches the error and exits `3` with a message naming
  the bad file.
- **`sectum baseline --compare` now gates on the full run diff, not metrics
  alone.** It compared only the headline metric counts, so a leak that newly
  *confirmed* (an `UNVERIFIED`→`CONFIRMED` upgrade or a fresh confirmed id) or a
  confirmed leak that *escalated in severity* (e.g. low→critical) between the
  baseline and the current run was reported as "no regression" whenever the
  counts happened to stay level. `--save` now persists the full `RunResult` (not
  just `RunMetrics`) and `--compare` runs `diff_runs` — the same gate as `sectum
  diff` — so a newly confirmed or escalated leak exits `2`. **Breaking:** a
  baseline saved by an earlier version holds only metrics; re-run `sectum
  baseline --save` to refresh it.
- **Semantic detection uses a true cosine, so a real embedder can't crash finding
  construction.** `_cosine` was a bare dot product (no normalization); a live
  embedding provider that returns non-unit vectors could yield a similarity above
  `1.0`, which overflows `Finding.confidence`'s `0..1` bound and aborts the scan
  with a `ValidationError`. It now normalizes by the product of L2 norms (a
  zero-norm vector scores `0.0`), and the semantic confidence is clamped to `1.0`
  defensively. The fake embedder already returns unit vectors, so offline scores
  are unchanged.
- **Erasure attestable-with-caveat findings no longer trigger a false
  regression.** A surface whose backend exposes no per-tenant erasure API
  (Helicone, Datadog) is recorded as *attestable-with-caveat* — a same-tenant
  backend limitation, not a confirmed cross-tenant leak. These findings are now
  `UNVERIFIED` (not `CONFIRMED`), and the erasure run's confirmed-findings count
  excludes them, so onboarding such a backend no longer makes `sectum diff` /
  `sectum baseline --compare` report a regression (exit 2) on the GDPR
  Article 17 wedge path. Completes the "caveats never regress" contract on the
  finding paths, not just the `erasure_caveats` metric. Regenerated sample packs
  in `docs/samples/` also now verify under the post-ADR-0016 whole-pack digest.
- **Example walkthroughs now describe the probes they actually run.** The
  `rag-poisoning` and `ikea-extraction` example READMEs and `run.sh` headers
  documented detection mechanisms the probes do not implement: a
  "baseline-vs-post-poisoning marker-bleed delta" with a `poison_pivot` document
  (Class 3), and a "cumulative-recall / efficiency-threshold" detector running
  against a `FakeRAGPipeline` on a `RAG_PIPELINE` surface (Class 10). Both are
  rewritten to match the shipped single-pass `vector.query` / `VECTOR_DB` probes:
  Class 3 plants one poison document per hard canary under a fixed lure phrase
  and flags any principal whose query retrieves a *foreign* principal's canary;
  Class 10 runs a fixed three-turn benign sequence per shared entity and flags
  any turn whose retrieved context surfaces a foreign canary.
- **A generic OpenTelemetry trace store with no delete API is now
  attestable-with-caveat, not a false erasure success.** When `DELETE` against
  the OTLP-JSON query endpoint returns `405` (Method Not Allowed) or `501` (Not
  Implemented) — the store exposes no programmatic per-tenant delete — the
  adapter now raises `ErasureUnsupported`, so Class 11 itemizes the surface as
  *attestable-with-caveat* (data presumed retained), exactly like the Helicone
  and Datadog adapters. Previously these codes were swallowed as a no-op, so the
  post-erasure re-scan reported the un-deletable spans as a `CONFIRMED` residual
  (gating `sectum diff` / `baseline --compare`) — inconsistent with the other
  observability backends for the same real condition. A `404` still means the
  spans are already absent and remains an idempotent erasure success.
- **`sectum erasure` now itemizes an attestable-with-caveat surface even when a
  genuine residual co-exists.** When a soft-deleting surface (a real erasure
  failure) and a no-erasure-API surface (a caveat) were both present, the
  dominant `ERASURE FAILED` message returned early and the caveat surface was
  never printed, so a DPO reading the CLI summary could miss that a second
  surface still held data. Both are now reported before the exit `2`.
- **In-toto attestations no longer over-claim a timestamp anchor for a local
  development token.** The predicate's `anchors.timestamp` was `true` whenever a
  token was present, but `sectum verify` treats the `local-dev` JSON token as
  *unanchored* (it binds the digest but is not an independent RFC 3161 / Rekor
  anchor). The flag now matches `verify_pack` — only a real (non-JSON, binary)
  TSA token counts as an external timestamp anchor.
- **Canonical hashing raises a clear, typed error for a non-JSON-native value.**
  `to_canonical_json` already refused non-finite floats (`NaN`/`Infinity`); a raw
  `dict`/`list` carrying a `UUID`, `datetime`, `bytes`, or non-`str` key still
  leaked `json`'s bare `TypeError`. It now raises a `TypeError` naming the cause
  ("cannot canonicalize a non-JSON-native value"), so a caller sees why the
  digest could not be computed. Models are unaffected — they normalize via
  `model_dump(mode="json")` first.
- **The KV-cache timing Welch's t-test no longer divides by zero on a
  single-sample group.** `_welch` computed each group's
  `(variance²)/(n-1)` Welch–Satterthwaite term unconditionally; an asymmetric
  `(n=1, n>1)` input raised `ZeroDivisionError`. A group with `n < 2` (no
  variance estimate) now contributes nothing to the denominator. The probe
  collects symmetric trial counts, so this hardens the helper without changing
  any run.

### Documentation

- **Honest build status + repo trust fixes.** The README status note no longer
  overclaims "all six phases complete" — it mirrors `PHASES.md`, which is the
  authoritative gate record and is now published on the docs site
  (`docs/phases.md`, embedded via a snippet). `PHASES.md` Phase 2 moved to **Met**
  (the docker-compose integration CI shipped); Phase 5's full-CLI
  embedding-model-swap path is the one criterion still being closed. Added
  `.github/FUNDING.yml`, and `SECURITY.md` now leads with GitHub private
  vulnerability reporting instead of an all-zeros placeholder PGP fingerprint.
- **Trust-artifact accuracy pass.** The flagship *Retrieval Pivot Attacks in
  Hybrid RAG* result is now cited with its canonical identifier
  [arXiv:2602.08668](https://arxiv.org/abs/2602.08668) (README, glossary) rather
  than a bare "(arXiv, 2026)"; `docs/configuration.md` no longer
  lists `verify` among the commands that accept `--config` (it has none);
  `docs/samples/README.md` reports the retrieval-pivot pack's real size and
  finding count (~33 KB, 321 findings); and ADR-0016's consequences now reflect
  that `pdf_ref` is bound *and populated* end-to-end (it previously stated the CLI
  did not populate it).
- **`sectum.yaml.example` used the wrong vector adapter key.** The example
  config keyed the vector store under `vector:`, but the CLI resolver reads
  `vector_store:` (matching `docs/configuration.md`), so a user who copied the
  example and pointed it at a live vector store had that block silently ignored
  and fell back to the in-memory fake. Renamed the block to `vector_store:`; a new
  resolver-parity test asserts every adapter key in the example is one of the
  eight families the resolver actually reads. Pre-existing since v0.1.0.
- **Docs and example walkthroughs corrected to match shipped behavior.**
  - The Class 2 flagship example (`examples/retrieval-pivot`) no longer claims
    *every* benign cross-tenant query pivots at 100%; it reports the measured
    retrieval-pivot rate from a real run and frames RPR as the fraction of the
    flagship benign queries that surface a foreign marker.
  - The erasure example (`examples/erasure-attestation`) and the Class 11 catalog
    page now state the seven surfaces the probe actually scans (vector store,
    tracing, agent memory, semantic cache, model adapter, search index, eval set)
    with the full per-surface verdict, instead of describing only the vector store
    as wired.
  - `SECURITY.md` lists v0.1.0 as the first supported release instead of "no
    stable release exists"; `glossary.md` describes `SECRET_CANARY` as the branded
    `SECTUM-SECRET-<base32>` token matched exactly (not an "API-key/SSN-shaped"
    string); the core-package quickstart verifies `.sectum/evidence.json` and the
    BYOC example validates with a scratch-workdir seed instead of a nonexistent
    `--dry-run` flag.
  - ADR-0008 carries a dated note that the `rag-pipeline-bleed` probe now issues a
    per-principal `rag.ask` step, so the RAG family's user dimension is
    *unverified* rather than *unneeded* — correcting the original "no probe issues
    a `rag.ask` step" rationale.
  - Doc-tail accuracy nits: `docs/quickstart.md` exit code `2` now spans
    confirmed leaks (`probe`), a regression (`diff` / `baseline --compare`), and
    residual / attestable-with-caveat data (`erasure`), not only "confirmed
    leaks present"; ADR-0002 states the control-mapping table lives in
    `evidence/controls.py` (not `sectum-ai-spec`); the `agent-tool-hijack`
    example README and `run.sh` adapter counts are corrected to the seven shipped
    kinds; the `tenant-boundary-fetch` README drops the `API` surface its probe
    never emits; the Class-5 (KV-cache) page documents that a backend with no
    shared prefix cache yields no signal by construction (absence ≠ isolation);
    `configuration.md` clarifies `corpus_profile` is accepted but not yet
    applied.

### Added

- **Real embedding-provider sweep for the Class 2 per-model Retrieval-Pivot
  Rate.** `retrieval_pivot_rate_by_model` modelled embedding strength with a
  recall knob on the in-memory `FakeVectorStore`, and the CLI recorded it only
  when the configured store *was* that fake — so the flagship "stronger
  embeddings leak more" gradient (arXiv:2602.08668) vanished on a live POC. A new
  provider-agnostic `EmbeddingModel` interface (`sectum.embeddings`) adds a
  deterministic offline `HashingEmbedding` (the CI/demo default) plus opt-in
  `SentenceTransformerEmbedding` (extra `sectum-ai[sentence-transformers]`, local
  and BYOC-safe — the MiniLM-vs-mpnet research pair) and `OpenAIEmbedding` (extra
  `sectum-ai[openai]`). `embedding_provider_sweep` embeds the corpus and benign
  queries with each real model and retrieves by cosine, so the per-model rate
  reflects the actual embeddings and is recorded for **any** vector store;
  `embedding_models` entries resolve by prefix (`st:` / `openai:` / `hash-`), with
  legacy `fake-*` names keeping the recall illustration (still gated to the
  in-memory store). See [ADR-0018](docs/adr/0018-embedding-provider-sweep.md).
- **The docker-compose integration tests now run in CI.** The
  `tests/integration/` suite exercises each live adapter's isolation contract
  against a real backend, but nothing ran it on CI — the default test job skips
  those tests when no backend is reachable, so the pgvector, Chroma, Weaviate,
  Redis, and Phoenix surfaces went untested on every PR while the suite still
  reported green. A dedicated **Integration** job brings the
  [`compose.yaml`](compose.yaml) backends up and runs `pytest -m integration`
  against them; the three backends without an in-container healthcheck (Chroma,
  Weaviate, Phoenix) are gated by an explicit HTTP readiness poll so their
  fixtures cannot silently *skip* and leave a surface untested while the job
  passes. `CONTRIBUTING.md` documents the local workflow.
- **Backup / snapshot surface for erasure verification — the seventh hiding
  place.** A new `BackupAdapter` family (`search`/`delete` over a backup or
  snapshot store) lets `ErasureProbe` attest a configured backup as a first-class
  surface: it scans the target tenant's hard canaries pre- and post-erasure like
  every other surface, and — when the store exposes no per-tenant purge API (the
  common immutable-snapshot case) — records it *attestable-with-caveat* rather
  than a clean pass or a failure, exactly as the observability adapters do. Ships
  with a `FakeBackup` (hard-delete, soft-delete, and no-erasure-API knobs) and
  closes Class 11 hiding place #7 (the engineering spec, §7); only third-party
  subprocessor residue (#8) now remains roadmap.
- **Phase-acceptance record + model-swap regression E2E.** `PHASES.md` records
  each build phase against its §14 acceptance criteria, and a new end-to-end test
  exercises the Phase-5 acceptance bar — build the substrate, run the
  embedding-model sweep with a weak then a strong model, and assert the stronger
  model's higher Retrieval-Pivot Rate is flagged by `compare_metrics().regressed`
  — so "baseline compare detects an injected regression" is enforced in CI rather
  than asserted in prose.
- **Named, sellable probe suites — `sectum probe --suite <name>`.** A *suite*
  fixes a probe set plus the compliance frameworks it provides evidence for, so an
  operator runs a named, control-mapped subset for a specific SKU instead of
  hand-picking probes. Ships `soc2-tenant-isolation` (the curated cross-tenant
  isolation checks → SOC 2 CC6.1/CC6.6/CC6.7, ISO 27001 A.8.3/A.8.12) and
  `owasp-llm08` (the full catalog). `--suite` and `--probe` are mutually exclusive;
  an unknown suite exits `3`. Suite definitions live in `sectum.suites`, their
  probe sets validated against the live catalog. New `docs/skus.md` maps the four
  SKUs (Erasure Attestation, SOC 2 pack, Continuous Verification, Open Sectum) to
  their commands and the OSS-vs-Cloud boundary.
- **An offline ATLAS-ID tripwire guards the manual technique-review gate.** Every
  probe's `atlas_techniques` were re-validated against the MISP galaxy ATLAS mirror
  (all current; `AML.T0024.000`/`.001` are valid ATLAS sub-techniques);
  `tests/unit/test_atlas_ids.py` now pins the verified set and rejects a malformed
  or not-yet-swept id per PR, complementing ADR-0009's manual release-time sweep
  without the network dependency that ADR rejected.
- **Every probe now ships a `probe.yaml` manifest (the engineering spec, §7.0).**
  Each of the 13 probes carries a declarative manifest beside its module — id,
  name, OWASP/ATLAS/NIST mappings, surfaces, required adapters, and a runnable
  example pointer — so the catalog is consumable without importing Python (the
  suite selector, dashboards, external tooling). Manifests are a mirror of the
  authoritative class attributes, generated by `scripts/gen_probe_manifests.py`
  and loadable via `sectum.probes.load_probe_manifest(probe)`; a test enforces
  parity so a manifest can never drift from its class. Closes a standing §7.0
  gap (no manifests previously existed).
- **Optional weasyprint PDF engine for the audit pack.** `sectum report
  --pdf-engine weasyprint` (or `render_audit_pack(..., engine=PdfEngine.WEASYPRINT)`)
  renders the auditor pack from an HTML/CSS template — severity badges, typographic
  tables, page footers — as an alternative to the default reportlab renderer.
  weasyprint is an optional extra (`pip install "sectum-ai[weasyprint]"`); the base
  install stays pure-Python and reportlab remains the default, and both engines
  render identical content. Resolves the spec §21 PDF-engine decision; see
  [ADR-0017](docs/adr/0017-pdf-engine.md).
- **`sectum diff` — compare two runs or evidence packs.** Reports finding-level
  changes — which leaks appeared, were resolved, persist, or changed in place
  (status or severity) — on top of the `baseline --compare` metric deltas, and
  exits `2` when the later run regressed: a worsened metric, a newly confirmed
  finding (a fresh finding id, or an in-place unverified→confirmed upgrade), or a
  severity escalation of a finding confirmed in both runs. Takes a `run.json` or
  an `evidence.json` on either side, plus `--output json`.

### Security

- **The audit-pack PDF is now bound into the tamper-evident digest.** The
  DPO/auditor-facing PDF was never covered by the attested digest, so it could be
  silently swapped while `sectum verify` still reported PASS. `sectum report` /
  `sectum erasure` now render the PDF first, hash its bytes, and bind that SHA-256
  as the pack's `pdf_ref` (which `attested_digest` already covers), so the signed
  digest commits to the exact PDF. `sectum verify` re-hashes the audit PDF when it
  sits beside the pack (`audit-pack.pdf` / `erasure-attestation.pdf`) and fails on
  a mismatch, while still verifying from `evidence.json` alone when the PDF is
  absent. To make the PDF a pure function of pre-signature content (so it hashes
  deterministically before signing), the raw timestamp-token row was dropped from
  the rendered PDF — the token remains in `evidence.json`, and the PDF still
  directs the reader to run `sectum verify`. Both PDF engines render the same
  digest-stable content.
- **Detection hardening (zero false-positive / zero false-negative).** Four
  fixes to the leak-detection pipeline, the technical moat:
  - The judge now confirms a semantic candidate only when the marker's tokens
    appear *in order within a short span* (light paraphrase such as a single
    interposed token is tolerated), not when the observation merely *covers* the
    marker's tokens in any order — a benign sentence reusing an entity's words
    could previously be reported as a confirmed cross-tenant leak.
  - The exact canary scan is case-, Unicode- (NFKC), and zero-width-insensitive,
    so a leaked `HARD_CANARY`/`SECRET_CANARY` that a surface re-cased, folded, or
    split with a zero-width character is no longer missed.
  - `Marker.plaintext` must be non-empty (`min_length=1`); an empty canary would
    otherwise substring-match every observation and confirm a critical leak.
  - `finding_id` carries the surface, so the same marker leaking on two surfaces
    (e.g. a vector store and a model adapter) is two findings rather than one
    silently de-duplicated away.

### Changed

- **Regression comparison reports per-surface erasure _caveats_** as
  informational metric deltas (in `sectum diff` and `sectum baseline --compare`).
  A caveat is a backend coverage limitation (Class 11 hiding place #8), not an
  isolation failure, so it is surfaced for visibility but never counts as a
  regression — kept distinct from erasure _residue_, which does.
- **Class 5 (KV-cache timing) now runs a real statistical test.** The
  side-channel probe performs a two-sided Welch's t-test on the primed-vs-control
  latencies and reports the t-statistic, degrees of freedom, p-value, a 95%
  confidence interval on the timing gap, and Cohen's d. A finding is confirmed
  only when the gap is statistically significant (p < 0.01), practically large
  (d ≥ 0.8), and directional (primed faster) — the spec §7 "avoid over-claiming"
  requirement. Pure standard library (no SciPy/NumPy); the evidence span now
  cites the full test result for the auditor.
- **Evidence schema `0.1.0` → `0.2.0`.** `EvidencePack` gains an
  `anchored_in_log` field, and the cryptographic anchors now bind the whole pack
  (`attested_digest`) rather than only the run record. Packs produced under the
  old scheme do not verify under the new verifier (pre-release; no packs in the
  wild). See [ADR-0016](docs/adr/0016-anchor-the-whole-pack.md).

### Security

- **Evidence packs are tamper-evident across their whole attested surface.** The
  timestamp and Rekor anchors now bind the control mappings, the recorded PDF
  reference, and the manifest hash — not just the run record — so forging the
  compliance claims or altering the recorded PDF reference makes `sectum verify`
  fail.
- **Transparency-log anchoring cannot be silently downgraded.** A pack that was
  Rekor-anchored fails verification if its inclusion proof is stripped
  (`anchored_in_log` is bound into the digest).
- **Forged local timestamp tokens are rejected.** A `local-dev` token is reported
  as *unanchored* (it binds the digest but is not an independent anchor); a JSON
  token impersonating a real RFC 3161 TSA is refused.
- Canonical hashing rejects non-finite floats (`NaN`/`Infinity`, which are
  invalid JSON and non-injective) and normalizes timestamps to UTC, so the digest
  is reproducible by any third-party verifier. See
  [ADR-0007](docs/adr/0007-canonical-hashing-serializes-every-field.md).

### Fixed

- **Regression baselines now catch per-model and per-probe regressions.**
  `compare_metrics` compared only the aggregate Retrieval-Pivot Rate and total
  confirmed count, so the canonical Phase-5 check — swap one embedding model,
  spike that model's RPR while the aggregate holds — was silently missed. It now
  also diffs `retrieval_pivot_rate_by_model` and `per_probe_findings` key by key.
- **The headline Retrieval-Pivot Rate counts both Class-2 probes.** The `sectum
  probe` RPR was computed from the vector-store entity-bleed probe only, reading
  0% when a leak manifested solely at the RAG-pipeline-end surface; it now counts
  steps from both bleed probes (`BLEED_PROBE_IDS`).
- **Malformed probe-step payloads raise a typed error.** The runner's `k` int
  coercion and required-key lookups raised bare `ValueError`/`KeyError`, escaping
  the `SectumError` → exit-code-3 mapping; they now raise `AdapterError` (shared
  `_payload_int`/`_payload_required` helpers, also used by the sweep).
- Baseline metric comparison uses a small float tolerance so JSON round-trip
  noise never reads as a regression.
- The Class 11 *attestable-with-caveat* distinction is now carried end to end,
  not just on the finding. A review pass found that when an observability
  backend raised `ErasureUnsupported` (Helicone / Datadog), the
  `SurfaceErasure` verdict still read `RESIDUAL DATA`, the `sectum erasure`
  CLI printed `ERASURE FAILED`, and it exited 2 — indistinguishable from a
  genuine erasure failure, undercutting the caveat the finding documented.
  `SurfaceErasure` now carries an `erasure_supported` flag; its verdict reads
  `ATTESTABLE WITH CAVEAT`, the CLI prints a distinct caveat message
  (still exit 2, since the data genuinely remains — never a false PASS), and
  `ErasureReport` gains `genuine_residual` / `caveats` so a real failure
  (soft-delete residual) is never blurred with a backend that has no per-tenant
  erasure API.
- The erasure probe's per-surface delete is now uniformly caveat-tolerant: the
  six near-identical surface blocks collapse into one `_erase_surface` helper,
  so `ErasureUnsupported` is handled on *every* surface rather than only
  observability (previously the other five surface deletes were unguarded and
  would crash the run if a future retention-governed adapter raised it).
- `FakeObservability` gains a `no_erasure` knob (parallel to `soft_delete`)
  that raises `ErasureUnsupported` from `delete`, so the caveat path is
  reachable from `sectum.yaml` (`observability: {kind: fake, no_erasure: true}`)
  and covered by a CLI-level test.

### Added

- A per-package `README.md` for all five distributions (`sectum-ai`,
  `sectum-ai-spec`, `sectum-ai-probes`, `sectum-ai-adapters`,
  `sectum-ai-evidence`), each wired in via `readme = "README.md"` in its
  `pyproject.toml`. Caught by a local release rehearsal (`uv build
  --all-packages` + `twine check`): every distribution previously built with
  no `long_description`, so each PyPI project page would have rendered
  **blank**. `twine check` now passes clean on all ten artifacts, and a
  fresh-venv install of the built wheels runs the `sectum` CLI end to end —
  so the v0.1.0 publish (pending the PyPI Trusted Publisher registration)
  will land with proper project pages rather than empty ones.
- Live Helicone and Datadog APM observability adapters
  (`HeliconeObservability`, `DatadogObservability`), completing the spec §11
  observability backend list (Langfuse, LangSmith, Helicone, Phoenix,
  Datadog APM, generic OTel). Both read the tenant's traces over their
  documented query APIs — Helicone's request-query endpoint scoped by a
  custom property (`Helicone-Property-Tenant`), Datadog's spans-search
  endpoint scoped by a span tag (`@tenant:<hex>`) — and scan the
  request/response bodies (Helicone) or span attributes (Datadog) for the
  marker. Standard-library HTTP, no optional extra; adapter logic verified
  by mock-backed unit tests, live wire format opt-in.
- Both adapters are **read-only with respect to erasure**: neither backend
  exposes a documented programmatic per-tenant bulk-delete (Helicone purges
  via retention settings; Datadog via retention policy), so their
  `delete(tenant)` raises the new `ErasureUnsupported(AdapterError)`. The
  Class 11 erasure probe now catches `ErasureUnsupported` per surface and
  records it as *attestable-with-caveat* (spec §7, hiding place #8): the
  surface shows residual = baseline (data presumed retained, never a false
  erasure PASS) with a distinct `erasure-caveat-*` finding whose remediation
  pointer explains it is a backend limitation, not a failure of the
  customer's erasure flow. This distinction matters to a DPO and is the
  honest representation for a compliance attestation.
- `ErasureUnsupported` is exported from `sectum.spec` and subclasses
  `AdapterError`, so callers that don't special-case the caveat still catch
  it under existing adapter-error handling. The CLI resolver accepts
  `kind: helicone` and `kind: datadog` under `observability`;
  `docs/configuration.md` and `sectum.yaml.example` document both, including
  the read-only erasure caveat.
- A live generic OpenTelemetry observability adapter, `OtelObservability`
  (`packages/adapters/src/sectum/adapters/observability/otel.py`). Adds
  the first of the spec §11 named-but-unshipped observability backends.
  OpenTelemetry's SDK is export-only, so the adapter reads traces over a
  small OTLP-JSON HTTP query contract — `POST {base_url}{query_path}`
  with `{"tenant": "<hex>", "marker": "..."}` returning standard
  `resourceSpans` — so one connector reaches any OTel-compatible backend
  (Jaeger / Tempo / Grafana / a vendor backend, or a thin shim) without a
  backend-specific SDK. Scopes by the resource attribute `tenant.id`
  (configurable) and re-scans every span's name + attribute values for
  the marker, so a backend that ignores the tenant filter is itself
  caught as a leak. `delete(tenant)` issues a scoped `DELETE` and treats
  a store with no delete API (404/405/501) idempotently — the residue
  then surfaces at the next scan, the honest Class 11 signal. Standard-
  library HTTP only, so the adapter and its 8 mock-backed unit tests need
  no optional extra. The CLI resolver accepts `kind: otel` under
  `observability`; `docs/configuration.md` and `sectum.yaml.example` are
  updated. (Helicone + Datadog APM, the other two §11-named backends,
  follow on the same injectable-client pattern once their live REST
  schemas + per-tenant delete semantics are verified against the vendor
  APIs.)
- A Class 2 expansion probe, `RagPipelineBleedProbe`
  (`packages/probes/src/sectum/probes/rag_pipeline_bleed/`). Where the
  flagship `RagEntityBleedProbe` issues benign shared-entity queries
  through the vector adapter (`Surface.VECTOR_DB`), this probe issues
  the same queries through the RAG-pipeline adapter
  (`Surface.RAG_PIPELINE`). The customer-facing surface in production
  is usually the RAG endpoint - not the underlying vector store - so a
  shared-index retriever inside a tenant-aware-looking pipeline is the
  exact leak this variant catches against the customer's actual
  contract. Wired into the CLI suite and the default leaky-demo
  config.
- The `FakeRAGPipeline` gains a `shared_index: bool = False` leak knob.
  With it on, the pipeline's retriever searches across every tenant's
  indexed documents - the cross-tenant retrieval pattern the new probe
  is built to catch. The default stays tenant-scoped and now reports
  `Capability.PER_TENANT_NAMESPACE`; `shared_index=True` reports
  `Capability.SHARED_INDEX` (the same capability the leaky
  `FakeVectorStore` advertises). `build_rag(config)` reads the knob
  from extras; the CLI's leaky-demo config flips it on and provisions
  every substrate document into the fake's index automatically.
- A live LangChain RAG pipeline adapter (`LangChainRAGPipeline` in
  `packages/adapters/src/sectum/adapters/rag/langchain.py`). Closes
  the last named v1 RAG kind spec §11 lists — "RAG — a generic HTTP
  RAG adapter + LangChain." The adapter wraps any LangChain
  `Runnable` (typically a composed LCEL chain of retriever + prompt
  + LLM + output parser) and invokes it per-tenant with
  `{"tenant": str(tenant), "query": query}`; tenant-aware retrievers
  filter on `tenant` and isolated ones ignore it — a retriever that
  shares its corpus is the exact leak Class 2 detects, so the
  adapter passes the scope through and lets the substrate verify it.
  The chain's response is parsed into the canonical
  `RagAnswer(answer, retrieved)` whether the chain returns a string,
  the modern `{"answer", "retrieved"}` shape, or the legacy
  `{"result", "source_documents"}` shape; LangChain `Document`
  objects with `page_content` + `metadata` parse into `VectorHit`
  via the metadata's `doc_id` + `score`. `langchain_core` is
  imported only on the live `connect` path; the adapter and its 10
  mock-backed unit tests need no extra dependency. Optional extras
  group: `pip install sectum-ai-adapters[rag-langchain]`. The CLI
  resolver accepts `kind: langchain` under `rag` via a
  `factory: module.path:callable` returning a `Runnable`;
  `docs/configuration.md` and `sectum.yaml.example` are updated.
- A runnable Class 7 walkthrough for the new probe in
  `examples/agent-framework-hijack/` (README + `run.sh` +
  `sectum.yaml`). The script seeds a four-tenant substrate, runs
  `sectum probe --probe agent-framework-hijack` against the in-memory
  `FakeAgent` with both leak knobs on, assembles a tamper-evident
  evidence pack, and verifies it — the same canonical CLI flow the
  other examples follow. Demonstrates 24 confirmed cross-tenant
  findings on the demo agent. README documents both ends of the
  Class 7 surface (the MCP example for the server end, this example
  for the agent caller end) and points at the existing
  `examples/agent-tool-hijack/factories.py` for swapping in a live
  LangGraph / AutoGen / CrewAI / OpenAI Assistants / Anthropic
  tool-use caller. Wired into the e2e example suite
  (`tests/e2e/test_examples.py`).
- A direct agent-framework Class 7 probe, `AgentFrameworkHijackProbe`
  (`packages/probes/src/sectum/probes/agent_framework_hijack/`). Where the
  existing `AgentToolHijackProbe` verifies the MCP server end of an
  agent's tool call, this probe verifies the *agent caller* itself.
  Each tenant's hard canary is provisioned as a resolvable resource the
  agent's built-in `lookup` tool can fetch; from every foreign principal
  the probe issues `agent.run(tenant, "lookup <marker_id>")` and, in a
  second step, the same task carrying `token=<owner-hex>` — the
  confused-deputy + Asana-class token-passthrough pair, but at the
  agent layer. A foreign canary in the agent's final output means the
  framework or its tool layer lost the caller's tenant scope on the way
  to the resource. The probe runs against every shipped v1 agent
  backend (`fake` / `http` / `langgraph` / `autogen` / `crewai` /
  `openai-assistants` / `anthropic-tooluse`) so the attestation pack
  speaks the same language to a DPO regardless of which framework the
  customer ran.
- The in-memory `FakeAgent` gains two leak knobs the new probe drives
  against: `confused_deputy=True` resolves `lookup <key>` across every
  tenant's resources (lost tenant scope), and `tool_call_passthrough=True`
  honours a caller-supplied `token=<tenant-hex>` argument (the
  Asana-class agentic token-passthrough pattern). A `provision(tenant,
  key, value)` test helper registers a tenant's resource; the CLI's
  leaky-demo config flips both knobs on so `sectum probe` reproduces
  the cross-tenant findings the probe is built to catch. The default
  `FakeAgent()` stays non-leaky and now reports
  `Capability.TENANT_SCOPED_TOOLS`.
- The `examples/agent-tool-hijack/` Class 7 walkthrough now ships
  factories for the full v1 agent family: in addition to the
  `langgraph` / `autogen` / `crewai` factories already wired,
  `examples/agent_tool_hijack.factories:make_openai_assistants`
  and `examples/agent_tool_hijack.factories:make_anthropic_tooluse`
  let an operator swap the agent caller across all five named v1
  backends without rewriting the probe. The README's "Swap the agent
  caller" section gains step-by-step blocks for both new kinds, so
  the cross-adapter consistency story (the same Class 7 probe runs
  the same way against every shipped agent framework) covers the
  full v1 set spec §11 names.
- A live Anthropic native tool-use agent adapter
  (`packages/adapters/src/sectum/adapters/agent/anthropic_tooluse.py`):
  an `AnthropicToolUseAgent` that drives the Anthropic Messages API
  in native tool-use mode with one conversation history cached per
  tenant; each `run` posts a user message prefixed with
  `[tenant:<hex>]` and the underlying loop calls `messages.create`,
  executes each `tool_use` block via the python callable carried on
  the tool spec's `__sectum_callable__` sidecar, appends a
  `tool_result` user message, and repeats until
  `stop_reason: end_turn`. The adapter caches one conversation
  per tenant and rolls back the user message on a failed turn so a
  retry sees a clean history. The `anthropic` package is imported
  only on the live `connect` path; the adapter module + 10
  mock-backed unit tests in
  `tests/unit/test_anthropic_tooluse_agent.py` need no extra
  dependency. The live backend lives in
  `packages/adapters/src/sectum/adapters/agent/_anthropic_tooluse_live.py`
  and is exercised end-to-end only when the operator installs the
  optional extras group
  (`pip install sectum-ai-adapters[anthropic-tooluse]`). The CLI
  resolver accepts `kind: anthropic-tooluse` under `agent` via a
  `factory: module.path:callable` returning a client implementing
  the `_AnthropicClient` protocol; `docs/configuration.md` and
  `sectum.yaml.example` are updated to match. Brings the live
  agent-adapter family to **six** (http, langgraph, autogen,
  crewai, openai-assistants, anthropic-tooluse) — the full v1 set
  spec §11 names.
- A live OpenAI Assistants agent adapter
  (`packages/adapters/src/sectum/adapters/agent/openai_assistants.py`):
  an `OpenAIAssistantsAgent` that drives an OpenAI Assistant with one
  `Thread` cached per tenant; each `run` posts a user message
  prefixed with `[tenant:<hex>]` and drives the Assistants
  ``Run`` through the tool-call resolution loop to completion. The
  adapter caches one Thread per tenant on first use and reuses it
  on every subsequent call — the per-tenant isolation property
  Class 7 verifies. The Assistant's persistent server-side state
  (model + system prompt + registered tools) is created once via
  `connect()` and reused across runs.
- The `openai` package is imported only on the live `connect`
  path; the adapter module + 9 mock-backed unit tests in
  `tests/unit/test_openai_assistants_agent.py` need no extra
  dependency. The live backend lives in
  `packages/adapters/src/sectum/adapters/agent/_openai_assistants_live.py`
  and is exercised end-to-end only when the operator installs the
  optional extras group (`pip install sectum-ai-adapters[openai-assistants]`).
  The CLI resolver accepts `kind: openai-assistants` under `agent`
  via a `factory: module.path:callable` returning a 2-tuple
  `(client, assistant_id)`; `docs/configuration.md` and
  `sectum.yaml.example` are updated to match. Brings the live
  agent-adapter family to **five** (http, langgraph, autogen,
  crewai, openai-assistants) — the v1 set spec §11 names.
- Five new example walkthroughs filling in the rest of the attack
  catalog: `examples/tenant-boundary-fetch/` (Class 1, the BOLA-style
  cross-tenant doc-id fetch), `examples/rag-poisoning/` (Class 3,
  cross-tenant adversarial poisoning of a shared index),
  `examples/semantic-cache/` (Class 4, prompt-cache contamination on
  a non-tenant-keyed cache), `examples/embedding-inversion/` (Class 6,
  nearest-neighbour reconstruction across a shared vector index),
  and `examples/ikea-extraction/` (Class 10, Silent-Leaks-style
  multi-turn benign extraction). Each follows the canonical CLI flow
  (seed → probe → report → verify), names the standard remediation
  in the README, and points at the live adapter shipped in v0.1.0
  (Pinecone / pgvector / Weaviate / Chroma / Redis) as the swap
  path for a real-stack probe. Combined with the previously-shipped
  examples (retrieval-pivot, erasure-attestation, mcp-tenant-boundary,
  agent-tool-hijack, memory-contamination, kv-cache-timing,
  lora-cross-tenant), the OSS now has a runnable walkthrough for
  every attack class in the catalog (Classes 1–11). All five were
  smoke-tested on a clean substrate and added to the e2e
  `_EXAMPLES` parametrized tuple.
- A new `examples/lora-cross-tenant/` walkthrough that reproduces Attack
  Class 9 — cross-tenant LoRA / adapter influence — end to end. The
  `lora-cross-tenant` probe trains each tenant's adapter on a small
  corpus that includes the tenant's `HARD_CANARY`, then queries every
  foreign tenant; on a mis-routed or weight-bled stack the canary
  surfaces in the wrong tenant's inference. The demo runs against the
  in-memory `FakeModel` with `adapter_bleed: true` (the leaky
  weight-bleed condition the substrate is built to catch). README
  explains both the routing-failure and weight-bleed shapes of the
  attack, scopes the demo to the fake substrate, and documents the
  `sectum.yaml` swap that points the same probe at the new live
  `HuggingFaceLoraModel` for real-PEFT-stack probing. Smoke-tested on
  a clean substrate: the evidence pack verifies under `sectum verify`.
- A new `examples/kv-cache-timing/` walkthrough that reproduces Attack
  Class 5 — the KV-cache prefix-cache timing side channel — end to
  end against the in-memory `FakeModel` with `prefix_cache: true`.
  The probe runs 24 paired primed-vs-control trials per cross-tenant
  pair and reports the Cohen's d effect size; a confirmed finding
  lands when the effect crosses the 0.8 "large effect" boundary. The
  README explains the statistical workflow, names the remediation
  pointer (per-tenant prefix-cache scoping or disabling the shared
  cache), and scopes the demo to the fake-model substrate while
  pointing at the new live `huggingface` model kind as the on-ramp to
  real-inference-engine probing. Smoke-tested on a clean substrate:
  the evidence pack verifies under `sectum verify`. Joins
  `mcp-tenant-boundary/`, `agent-tool-hijack/`, and
  `memory-contamination/` as the agent-side isolation examples
  alongside the flagship Class 2 `retrieval-pivot/` and the wedge
  Class 11 `erasure-attestation/`.
- A live HuggingFace + PEFT LoRA model adapter
  (`packages/adapters/src/sectum/adapters/model/huggingface.py`): a
  `HuggingFaceLoraModel` that wraps a HuggingFace causal-LM base with
  a per-tenant (and optionally per-user) LoRA managed via `peft`.
  `train_adapter` fine-tunes a tenant-scoped LoRA on a small text
  corpus; `infer` loads that LoRA on top of the shared base model
  and generates a completion; `delete` removes the LoRA dir (or, with
  `soft_delete=True`, routes new inference back to base while leaving
  the on-disk weights as the Class 11 residue). The `adapter_bleed`
  knob merges every tenant's LoRA into every inference — the
  weight-bleed condition Class 9 (LoRA cross-tenant) is built to
  catch. `transformers` / `peft` / `torch` are imported lazily on
  the live `connect` path, so the adapter module + the 13 mock-backed
  unit tests in `tests/unit/test_huggingface_model.py` need no extra
  dependency. The live backend lives in
  `packages/adapters/src/sectum/adapters/model/_huggingface_live.py`
  and is exercised end-to-end against a real base model only when
  the operator installs the optional extras group (`pip install
  sectum-ai-adapters[huggingface]`). The CLI resolver accepts
  `kind: huggingface` under `model` with `base_model_id` and
  `adapters_dir` required and `lora_rank`/`lora_alpha`/`train_epochs`/
  `device_map` knobs forwarded to `connect`.
- A new `examples/memory-contamination/` walkthrough that reproduces Attack
  Class 8 — persistent memory contamination (SpAIware-class) — end to end:
  the `memory-contamination` probe writes a hard canary into every tenant's
  long-term memory as the owning principal and then recalls it from every
  foreign principal, against an in-memory `FakeMemory` whose `shared_memory`
  knob removes the tenant boundary. The walkthrough sits alongside
  `mcp-tenant-boundary/` and `agent-tool-hijack/` as the agent-side
  isolation surface, and the README scopes it to the only memory adapter
  shipped today (the `FakeMemory` substrate) while naming the live
  agent-framework memory plugins (LangGraph checkpointers, AutoGen memory,
  CrewAI memory, Mem0, Letta, Zep) the `MemoryAdapter` interface is built
  to receive. Smoke-tested on a clean substrate: `run.sh` exits with 24
  confirmed Class 8 leak findings and the evidence pack verifies under
  `sectum verify`.
- A new `examples/agent-tool-hijack/` walkthrough that reproduces Attack
  Class 7 from the *agent-adapter* perspective: the same Class 7 probe
  the `examples/mcp-tenant-boundary/` example drives (with confused-deputy
  and token-passthrough sub-probes against the in-memory leaky MCP server),
  but framed around the agent caller and accompanied by
  `factories.py` — copy-pasteable connect-time factory callables for each
  of the four shipped agent kinds (`fake`, `langgraph`, `autogen`,
  `crewai`). README documents the `sectum.yaml` swap for each kind so an
  operator can verify Class 7 with the same agent framework their customer
  actually runs in production. Smoke-tested on a clean substrate:
  `run.sh` exits with the canonical Class 7 leak findings and the evidence
  pack verifies under `sectum verify`.
- A live CrewAI agent adapter (`packages/adapters/src/sectum/adapters/agent/crewai.py`):
  a `CrewAIAgent` that drives a CrewAI `Crew` of agents + tasks through
  `crew.kickoff(inputs={"tenant_id": tenant.hex, "task": task})`, so a
  templated task description interpolates the tenant id and a tenant-aware
  tool reads the scope from its call arguments — the per-tenant isolation
  property Class 7 (agent tool-call hijack) verifies. The adapter walks the
  crew's `tasks_output` and surfaces every tool the agents invoked while
  completing each task — reading both the modern `tool_calls` attribute
  and CrewAI's legacy `tools_calls` (note the trailing 's') and
  `tool_results` shapes — so the Class 7 probes can see which tool fired
  on which task in each tenant's session. The `crewai` package is imported
  only on the live `connect` path, so the mock-backed contract test in
  `tests/unit/test_crewai_agent.py` runs against an in-memory stand-in
  with no extra dependency; the live path needs the optional extras group
  (`pip install sectum-ai-adapters[crewai]`) and is exercised by
  `tests/integration/test_crewai.py` (opt-in via the env-gated
  integration suite). The CLI resolver accepts `kind: crewai` under
  `agent` (via a `factory: module.path:callable` returning a `Crew`);
  `docs/configuration.md` and `sectum.yaml.example` are updated to match.
- A live AutoGen agent adapter (`packages/adapters/src/sectum/adapters/agent/autogen.py`):
  an `AutoGenAgent` that drives an AutoGen `AssistantAgent` + `UserProxyAgent`
  pair through `UserProxyAgent.initiate_chat`, prefixing every user message
  with a `[tenant:<hex>]` token so a tenant-aware tool reads the scope from
  its call arguments — the per-tenant isolation property Class 7 (agent
  tool-call hijack) verifies. The adapter walks the conversation's
  `chat_history` (with a `chat_messages` fallback for the v0.4+ shape) and
  surfaces every tool the assistant called during a run — including both the
  modern OpenAI `tool_calls` array and the legacy single `function_call`
  field — so the Class 7 probes can see *which* tool fired in each tenant's
  session. The `autogen` package is imported only on the live `connect`
  path, so the mock-backed contract test in `tests/unit/test_autogen_agent.py`
  runs against an in-memory stand-in with no extra dependency; the live path
  needs the optional extras group (`pip install sectum-ai-adapters[autogen]`)
  and is exercised by `tests/integration/test_autogen.py` (opt-in via the
  env-gated integration suite). The CLI resolver accepts `kind: autogen`
  under `agent` (via a `factory: module.path:callable` returning
  `(assistant, user_proxy)`); `docs/configuration.md` and
  `sectum.yaml.example` are updated to match.

## [0.1.0] - 2026-05-26

First public release. Sectum AI ships as a five-package `uv` workspace
(`sectum-ai`, `sectum-ai-spec`, `sectum-ai-probes`, `sectum-ai-adapters`,
`sectum-ai-evidence`), Apache-2.0 licensed, with a tamper-evident evidence
chain anyone can verify with `sectum verify` and no Sectum-side trust.
What landed in 0.1.0 is the work that closed the phase-0 through phase-5
build plan; the rest of this section is the per-feature log.

### Added

- A live LangGraph agent adapter (`packages/adapters/src/sectum/adapters/agent/langgraph.py`):
  a `LangGraphAgent` that drives a compiled LangGraph `StateGraph` with one
  `thread_id` per tenant (`config={"configurable": {"thread_id": tenant.hex}}`)
  so per-thread checkpoint or memory cannot bleed across tenants — the
  isolation property Class 7 (agent tool-call hijack) verifies. The adapter
  surfaces every tool the graph called during a run (not just the final
  state) so the Class 7 probes can see *which* tool fired and with what
  arguments. The `langgraph` package is imported only on the live `connect`
  path, so the mock-backed contract test in `tests/unit/test_langgraph_agent.py`
  runs against an in-memory stand-in with no extra dependency; the live path
  needs the optional extras group (`pip install sectum-ai-adapters[langgraph]`)
  and is exercised by `tests/integration/test_langgraph.py`
  (opt-in via the env-gated integration suite). The CLI resolver accepts
  `kind: langgraph` under `agent`; `docs/configuration.md` and
  `sectum.yaml.example` are updated to match.
- Live OpenAI and Anthropic providers for the Class 2 detection pipeline
  (`packages/probes/src/sectum/probes/providers.py`): `OpenAIEmbedder`
  (default `text-embedding-3-small`), `OpenAIJudge` (default `gpt-4o-mini`
  via JSON-mode structured output), and `AnthropicJudge` (default
  `claude-3-5-sonnet` via tool-use structured output). The judge prompt
  enforces the spec §6.4 guardrail — only the candidate entity descriptor
  is shown, never the ground-truth manifest verbatim. No
  `AnthropicEmbedder` ships because Anthropic does not expose an
  embeddings API as of 2026; the gap is documented inline in
  `providers.py`. The CLI resolver now accepts `kind: openai` and
  `kind: anthropic` under `embedder` / `judge` config blocks; mock-backed
  unit tests cover construction, retry, and structured-output parsing,
  and a pair of live-gated integration tests run against the real APIs
  when `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` are set.
- A second flavour of the Erasure Attestation sample in `docs/samples/`: the
  RESIDUAL DATA pack produced by `sectum erasure --soft-delete` against the
  `examples/erasure-attestation` substrate. Three new files
  (`erasure-attestation-residual-data-audit-pack.pdf`,
  `erasure-attestation-residual-data-evidence.json`,
  `erasure-attestation-residual-data-attestation.intoto.json`) sit next to the
  existing happy-path ERASED pack so a prospective DPO can see both the
  successful-erasure deliverable and the failure-mode artefact the pack is
  built to catch — without running anything locally. The samples README now
  describes both verdict flavours, lists the regeneration commands for both,
  and explains that either pack verifies under `sectum verify`; the verdict
  is data, not signal integrity.
- `examples/erasure-attestation/sectum.yaml.production`: a documented
  production-shape config for the engagement, with `evidence.timestamper:
  local` and `evidence.rekor: true` defaults and a comment explaining why
  real engagements should pin a customer-chosen TSA URL (FreeTSA, the OSS
  demo default, has been observed to be unreachable for hours at a time).
  Used by the sample regeneration in `docs/samples/README.md`.
- `sectum probe --output json` emits a single machine-parseable JSON object on
  stdout (the run id, the probe count, the confirmed-finding count, the
  Retrieval-Pivot Rate, the per-probe counts, and a `run_path` pointer) so CI
  pipelines and dashboards can act on the headline metrics without scraping
  the human-readable rendering. `--output text` is the unchanged default.
- The signed release pipeline (`.github/workflows/release.yml`): a `v*` tag
  push builds the five workspace distributions, generates a CycloneDX SBOM per
  distribution, signs every sdist, wheel, and SBOM with Sigstore (keyless,
  OIDC), publishes to PyPI via Trusted Publisher (OIDC), and creates a GitHub
  Release with the matching CHANGELOG section as its body and the SBOMs and
  `.sigstore` bundles as assets. A `pypi` environment fronts the publish step
  so the maintainer's approval is the final human gate; no static PyPI token
  lives in the repository. `scripts/check_release_version.py` blocks a release
  whose tag and `pyproject.toml` versions drift, and
  `scripts/extract_changelog.py` lifts the matching CHANGELOG section (with an
  `Unreleased` fallback for pre-release tags). `scripts/generate_package_sboms.sh`
  emits one SBOM per distribution. `docs/RELEASING.md` is the operator's
  reference (the PyPI Trusted Publisher setup, the per-release checklist, how
  to verify an artifact with `cosign verify-blob`, and the yank procedure);
  `SECURITY.md` and `CONTRIBUTING.md` cross-link the trust model.
- The live HTTP MCP client adapter (`HttpMCPClient`): a generic Model Context
  Protocol client over the SDK's streamable-HTTP transport, so a hosted MCP
  integration is reachable without a stdio subprocess. Like `StdioMCPClient`,
  a generic call carries no tenant identity unless a `tenant_argument` is
  configured; the adapter faithfully transmits tenant context under that key
  so the Class 7 confused-deputy probes can find a server that drops it. The
  CLI resolver now accepts `mcp.kind: http` with `url`, `headers`, `timeout`,
  and `tenant_argument`; verified offline against an in-memory FastMCP server
  and exercised live by `tests/integration/test_mcp_http.py` (opt-in via
  `SECTUM_MCP_HTTP_URL`).
- Phase 0 — repository foundation: a `uv` workspace with five packages
  (`sectum-ai`, `sectum-ai-spec`, `sectum-ai-probes`, `sectum-ai-adapters`,
  `sectum-ai-evidence`).
- Foundation documents: `LICENSE` (Apache-2.0), `SECURITY.md`, `README.md`,
  `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`.
- Continuous integration: lint (ruff), type-check (mypy), test (pytest),
  secret scan (gitleaks), and CodeQL workflows; pre-commit hooks; Dependabot;
  issue and pull-request templates.
- Architecture decision records: ADR-0001 (monorepo packaging layout) and
  ADR-0002 (the evidence layer is fully open source).
- Phase 1 - the marker substrate: `sectum-ai-spec` Pydantic models and JSON
  Schema export; the substrate (deterministic synthetic tenants, templated
  corpus generation, three canary marker types, hashed ground-truth manifest);
  and the exact/semantic/judge detection pipeline with deterministic fake
  embedding and judge providers.
- ADR-0003 (substrate artifacts are pure functions of the seed).
- Phase 2 - the adapter SDK and probe interface: six adapter family interfaces
  with a capability model and registry; the `Probe` protocol and registry;
  deterministic in-memory fake adapters for every family with a contract test
  suite; the `sectum adapters` CLI command; and live pgvector and Chroma
  vector-store adapters verified against docker-compose backends.
- Phase 3 - the attack catalog: the scenario runner; the Class 1
  direct-tenant-boundary probe; the Class 2 flagship organic-entity-bleed RAG
  probe, whose substrate plants every canary in a shared-entity pivot document
  so benign cross-tenant queries reproduce the Retrieval Pivot, with the
  Retrieval-Pivot Rate metric; the Class 4 semantic-cache-contamination probe;
  and the Class 11 GDPR Article 17 erasure-verification wedge.
- Phase 3 - the evidence chain: tamper-evident evidence packs
  (`build_evidence_pack`) and independent verification (`verify_pack`), with a
  pluggable timestamper; the compliance-control mappings (SOC 2, ISO 27001,
  GDPR, EU AI Act, HIPAA, NIST AI RMF, OWASP); and the audit-pack PDF renderer
  (`render_audit_pack`).
- Phase 3 - the CLI: `sectum seed` provisions the substrate, `sectum probe`
  runs the probe suite (recording findings and the Retrieval-Pivot Rate),
  `sectum report` assembles the evidence pack (JSON and PDF), `sectum verify`
  independently verifies it, `sectum erasure` runs the GDPR Article 17
  erasure-verification workflow into an attestation pack, and `sectum init`
  scaffolds a starter `sectum.yaml` config.
- Phase 3 - end-to-end examples: `examples/retrieval-pivot` (the flagship
  Class 2 walkthrough, from seeding through a verified evidence pack) and
  `examples/erasure-attestation` (the Class 11 erasure-verification wedge).
- Phase 4 - the model/adapter layer and the agent surface: a
  `ModelAdapter` adapter family with a deterministic `FakeModel`; the Class 9
  LoRA / adapter cross-tenant-influence probe; and the Class 7 cross-tenant
  agent tool-call hijacking probe (the MCP confused-deputy and token-passthrough
  sub-probes) over an extended `FakeMCP`. Both probes join the `sectum probe`
  suite.
- Phase 4 - the threat model: `docs/threat-model.md` records the
  trust boundaries, the assets (the ground-truth manifest, evidence packs), the
  deployment modes, and Sectum AI's explicit non-goals.
- Phase 4 - a mkdocs-material documentation site: a page per
  implemented attack class, plus the evidence chain, compliance mappings, the
  adapters, the ADRs, and the threat model, with a build-and-deploy workflow.
- Phase 4 - the `sectum probe --probe` filter to run a single
  probe, and the `examples/mcp-tenant-boundary` Class 7 walkthrough.
- Phase 5 - the regression-baseline engine: `sectum baseline`
  saves a run's headline metrics, and `--compare` flags any later run whose
  metrics regressed (more confirmed findings, or a higher Retrieval-Pivot Rate).
- Phase 5 - Class 8, the persistent memory contamination probe,
  over a new `MemoryAdapter` adapter family with a deterministic `FakeMemory`.
- Phase 5 - Class 6, the embedding-inversion probe: a
  partial-fragment query reconstructs a foreign entity canary from a shared
  index.
- Phase 5 - Class 10, the IKEA-style implicit benign extraction
  probe: a multi-turn sequence of benign queries that extracts foreign content.
- Phase 5 - Class 3, the adversarial RAG poisoning probe: a
  planted lure document pivots a tenant's canary into others' retrieval; the
  runner gains a `vector.upsert` action.
- Phase 5 - Class 5, the KV-cache timing side-channel probe: a
  statistical timing test (a Cohen's d effect size over many trials) that
  detects a shared KV prefix cache; the model adapter gains a `measure_latency`
  method, and the run metrics record per-pair side-channel effect sizes.
- Phase 5 - the live Redis cache adapter (`RedisCache`): a key-prefixed,
  tenant-scoped cache over a Redis server, verified against a docker-compose
  backend; it joins pgvector and Chroma as the third live adapter.
- Phase 5 - the live Weaviate vector-store adapter (`WeaviateVectorStore`):
  each tenant maps to its own Weaviate collection, created with self-provided
  vectors and deterministic object ids so an upsert stays idempotent; verified
  against a docker-compose backend.
- Phase 5 - the live HTTP RAG adapter (`HttpRAGPipeline`): a generic connector
  that answers a tenant's query over a JSON HTTP API, so a retrieval pipeline
  is reachable without a backend-specific SDK; standard-library only.
- Phase 5 - the live Phoenix observability adapter (`PhoenixObservability`):
  searches a tenant's traces for a marker over an Arize Phoenix server, with
  each tenant mapped to its own Phoenix project; verified against a
  docker-compose backend.
- Phase 5 - the live HTTP agent adapter (`HttpAgent`): a generic connector
  that runs a tenant's task over a JSON HTTP API and surfaces the agent's tool
  calls, so an agent framework is reachable without a framework-specific SDK;
  standard-library only.
- Phase 5 - the live MCP client adapter (`StdioMCPClient`): a generic Model
  Context Protocol client that launches a stdio MCP server, lists its tools,
  and invokes them; a generic MCP call carries no tenant identity unless a
  tenant-scoping argument is configured.
- The typed `SectumError` exception hierarchy (`ConfigError`, `AdapterError`,
  `EvidenceError`, `DetectionError`) in `sectum-ai-spec` (the engineering spec,
  section 16); the adapter, runner, and substrate error conditions now raise
  the typed errors instead of a bare `ValueError`.
- The CLI maps typed `SectumError`s to the engineering-spec section-10 exit
  codes: an `EvidenceError` exits 4, and other typed errors exit 3, replacing
  the traceback that used to surface from a `seed`, `probe`, `erasure`, or
  `report` invocation.
- A typed `sectum.yaml` configuration loader in `sectum.config`: pydantic
  models for the scenario, adapter, and evidence blocks, and a `load_config`
  function that raises `ConfigError` on a missing file, malformed YAML, or an
  invalid schema. `sectum seed` accepts `--config sectum.yaml` and reads its
  scenario seed and workdir from the file; explicit `--seed`/`--workdir` flags
  override the config.
- A config-driven adapter resolver in `sectum.config`: `build_adapters`
  dispatches each adapter family's `kind` to a concrete `Adapter`, defaulting
  missing families to plain fakes. `sectum probe` accepts `--config` and
  builds its adapter bundle from the file, so a tenant-isolated config (every
  leak knob off) records zero confirmed findings while the default leaky-demo
  config keeps reproducing them. The `sectum init` template now exposes every
  adapter family's leak knobs so the demo round-trips through the resolver.
- The CLI resolver now wires the live adapters: `kind: pgvector`, `chroma`,
  or `weaviate` for `adapters.vector_store`; `kind: redis` for `adapters.cache`;
  and `kind: stdio` for `adapters.mcp`. Secrets reference environment variables
  (`dsn_env: SECTUM_PGVECTOR_DSN`); vector adapters receive a deterministic
  hashing-trick embedder so a sectum-driven verification needs no
  embedding-model account.
- `sectum erasure`, `sectum report`, and `sectum baseline` accept
  `--config sectum.yaml` and use its workdir as a default, completing the
  per-command `--config` coverage for every workflow command.
- A `docs/configuration.md` reference page in the mkdocs nav: the `sectum.yaml`
  top-level shape, every adapter family's supported `kind`s with their fields
  and defaults, the env-var secret pattern, and a live-pgvector example.
- Extend the scenario runner with `rag.ask`, `observability.search`, and
  `agent.run` actions and pair them with new `rag`, `observability`, and
  `agent` fields on `AdapterBundle`; the CLI's `sectum probe` passes the
  three new adapters into the runner. Probes can now drive a RAG pipeline,
  search observability traces, or run an agent task directly through the
  runner; the config resolver wires the three new families to their fakes.
- The CLI resolver wires the live HTTP RAG, Phoenix observability, and HTTP
  agent adapters: `kind: http` in `adapters.rag` or `adapters.agent` selects
  `HttpRAGPipeline`/`HttpAgent`; `kind: phoenix` in `adapters.observability`
  selects `PhoenixObservability`. New `_float` and `_str_dict` helpers parse
  timeouts and header maps from the config.
- `sectum probe` accepts `--max-concurrency N` (default 1) to run probes in
  parallel via a thread pool. N > 1 requires both thread-safe adapters and
  that probe-order interactions don't matter; the demo's in-memory fakes
  share state across mutating and reading probes, so concurrent execution
  there yields nondeterministic findings (the exit code is still stable).
- Class 11 (`sectum erasure`) now checks the observability surface. The
  `ObservabilityAdapter` interface gains `delete(tenant)`; `FakeObservability`
  gets a `soft_delete` knob mirroring `FakeVectorStore`; `PhoenixObservability`
  removes the tenant's project on delete. `ErasureProbe` accepts an optional
  `observability` adapter and scans the tracing surface for residual markers,
  and `sectum erasure` seeds traces and passes a `FakeObservability` through
  so the workflow round-trips through both the vector and tracing surfaces.
- Class 11 (`sectum erasure`) now also checks the agent/long-term memory surface
  (a third of the spec's "ten hiding places"). The `MemoryAdapter` interface
  gains `delete(tenant)`; `FakeMemory` gets a `soft_delete` knob; `ErasureProbe`
  accepts an optional `memory` adapter and scans it (via `recall`) for residual
  markers, and `sectum erasure` seeds memory and passes a `FakeMemory` through
  so the workflow round-trips the vector, tracing, and memory surfaces.
- Class 11 (`sectum erasure`) now also checks the semantic/application cache
  surface. The `CacheAdapter` interface gains `delete(tenant)` and `values(tenant)`
  (the values a tenant can read - the tenant's own when scoped, all of them when
  not, which is itself the leak); `FakeCache` gets a `soft_delete` knob and
  `RedisCache` deletes/scans the tenant's prefixed keys. `ErasureProbe` accepts
  an optional `cache` adapter and scans its values for residual markers, and
  `sectum erasure` seeds the cache through, so the workflow now round-trips the
  vector, tracing, memory, and cache surfaces. An unscoped cache that cannot
  isolate a tenant's entries is itself an erasure failure.
- Class 11 (`sectum erasure`) now also checks the model / fine-tune-adapter
  surface. The `ModelAdapter` interface gains `delete(tenant)`; `FakeModel` gets
  a `soft_delete` knob; `ErasureProbe` accepts an optional `model` adapter and
  scans it by querying the model with the canary - a memorized canary surfaces
  only while the tenant's adapter exists - and `sectum erasure` trains and
  threads a `FakeModel` through, so the workflow now round-trips the vector,
  tracing, memory, cache, and model surfaces (five of the "ten hiding places").
- Class 11 (`sectum erasure`) now also checks the derived full-text search-index
  surface (the tenth "hiding place"). A new `SearchIndexAdapter` family
  (`search` + `delete`, capability `TEXT_SEARCH`) and its `FakeSearchIndex` (with
  a `soft_delete` knob) model a keyword index built from the corpus, distinct
  from the embedding vector store; `ErasureProbe` accepts an optional
  `search_index` adapter and scans it for residual markers, and `sectum erasure`
  indexes and threads a `FakeSearchIndex` through. The workflow now round-trips
  six of the "ten hiding places". There is no live search-index adapter yet, so
  the fake carries the behavior.
- Class 11 (`sectum erasure`) now also checks the evaluation / golden-set surface
  (the fourth "hiding place" - test fixtures and eval datasets that may copy
  tenant content). A new `EvalSetAdapter` family (`search` + `delete`, reusing
  the `TEXT_SEARCH` capability) and its `FakeEvalSet` (with a `soft_delete` knob)
  model an eval set; `ErasureProbe` accepts an optional `eval_set` adapter and
  scans it for residual markers, and `sectum erasure` seeds and threads a
  `FakeEvalSet` through. The workflow now round-trips seven of the "ten hiding
  places". There is no live eval-set adapter yet, so the fake carries the
  behavior.
- The live Pinecone vector-store adapter (`PineconeVectorStore`): each tenant
  maps to its own namespace within one index, so a query or fetch is
  tenant-scoped. Pinecone is a hosted service with no local backend, so it is
  verified by a mock-backed contract test plus an opt-in live test (the
  engineering spec, section 13); the CLI resolver wires `kind: pinecone` for
  `adapters.vector_store`.
- The live Langfuse observability adapter (`LangfuseObservability`): Langfuse's
  public SDK binds one project per key pair and cannot enumerate projects, so
  each tenant is scoped by trace `user_id` within a single project (unlike the
  per-project Phoenix adapter); a search matches the marker in the tenant's
  traces and erasure bulk-deletes them. Targets the Langfuse v3 SDK; verified by
  a mock-backed contract test plus an opt-in live test. The CLI resolver wires
  `kind: langfuse` for `adapters.observability`.
- The live LangSmith observability adapter (`LangSmithObservability`): each
  tenant maps to its own LangSmith tracing project (like Phoenix), so a search
  scans that project's runs and erasure deletes the project. Verified by a
  mock-backed contract test plus an opt-in live test; the CLI resolver wires
  `kind: langsmith` for `adapters.observability`.
- ADR-0004 (acyclic package graph; the detection pipeline moved into
  `sectum-ai-probes`).
- ADR-0005 (examples are named for the attack class, not a metric value).
- The principal isolation model: the spec gains `PrincipalKind`, a `Principal`
  value model (a tenant, or a user within a tenant), `SyntheticUserSpec`,
  `SyntheticTenantSpec.users`, `Marker.owner_user_id`, and
  `Substrate.principals()`. The substrate distributes a tenant's markers
  round-robin across its declared users; tenant-level behavior is unchanged (the
  new fields default to the tenant case). User-level detection and probing are a
  deferred phase.
- ADR-0006 (the isolation boundary is a principal - a tenant or a user within a
  tenant - generalizing the substrate without repositioning the tenant wedge).
- User-level (principal) leak detection (ADR-0006 update): the detection
  pipeline's predicate is now principal-aware - within a tenant, a marker owned
  by one user surfacing in another user's session is a leak (verified
  default-deny). `ProbeStep` gains `actor_user_id` and `Finding` gains
  `owner_user_id`/`observed_in_user_id` (optional, tenant-level default), and
  the flagship Class 2 probe (`rag-entity-bleed`) plans from every principal, so
  against a store that is not user-scoped a user's benign query surfaces another
  user's data. Tenant-level behavior is unchanged. Generalizing the remaining
  probes (and the user-aware adapters they need) and the intended-vs-actual
  access-policy model are the documented follow-ons.
- The Class 1 direct-tenant-boundary probe (`tenant-boundary-fetch`) is now
  principal-aware (ADR-0006): it plans a direct fetch of every hard-canary
  document from each principal to which the marker is foreign - cross-tenant as
  before, and cross-user within a tenant when users are declared - so negative
  authorization is verified at both granularities. The `is_cross_principal`
  predicate is now public so probe planning and detection share one definition
  of "foreign." With no users declared the plan is byte-identical to the prior
  per-tenant plan.
- The adapter SDK gains an optional user dimension (ADR-0008), starting with the
  vector family. `VectorStoreAdapter.query`/`fetch` take a keyword-only
  `user: UUID | None = None`; the runner threads `ProbeStep.actor_user_id` into
  them; and `CorpusDocument` gains `owner_user_id` (a pivot document inherits its
  marker's owner). `FakeVectorStore` gains a `user_scoped` knob and reports the
  new `USER_SCOPED` capability: scoped, it returns only a user's own documents
  plus the tenant-shared ones; unscoped, it ignores the user and surfaces another
  user's document. The Class 1 boundary probe now verifies user isolation end to
  end - a user-scoped store yields no cross-user leak, a tenant-only store does.
  `user=None` is the tenant-level scope and is unchanged; the live vector
  adapters accept `user` for conformance but do not yet report `USER_SCOPED`
  (per-backend user isolation is a follow-on).
- The user dimension reaches the cache family (ADR-0008). `CacheAdapter.get`/`set`
  take a keyword-only `user`; the runner threads it; and `FakeCache` gains a
  `user_scoped` knob that folds the user into the key (reporting `USER_SCOPED`),
  so one user never reads a sibling user's entry. The Class 4 semantic-cache
  probe (`semantic-cache-contamination`) is now principal-aware - it primes an
  entry as the owning principal and fetches it from every foreign principal - so
  it verifies cache-key tenancy at the user granularity too: a user-scoped cache
  yields no cross-user leak, a tenant-only cache serves one user another's
  answer. `user=None` is unchanged.
- The live `RedisCache` now *enforces* user scoping: with `user_scoped: true` it
  folds the user into the Redis key (and reports `USER_SCOPED`), so a sibling
  user cannot read another user's entry within the tenant; the tenant-level
  `values`/`delete` globs still capture the user-folded keys. The cache resolver
  exposes `user_scoped` for both the fake and Redis. Verified by an opt-in Redis
  integration test (the key folding is correct by construction). This is the
  exemplar for bringing the remaining live adapters (pgvector, Chroma, Weaviate,
  Pinecone) to per-backend `USER_SCOPED` enforcement.
- The live `PgVectorStore` now *enforces* user scoping: with `user_scoped: true`
  it records each document's `owner_user` (an idempotent `ADD COLUMN` migration)
  and filters `query`/`fetch` to the caller's own rows plus tenant-shared ones
  (reporting `USER_SCOPED`), so one user cannot retrieve a sibling user's
  document within the tenant. The tenant-level `delete`/`list_namespaces` are
  unchanged. The vector resolver exposes `user_scoped` for the fake and pgvector.
  Verified against a live PostgreSQL + pgvector backend by the integration tests.
- The live `ChromaVectorStore` now *enforces* user scoping: with
  `user_scoped: true` it records each document's owning user in Chroma metadata
  (an empty sentinel marks tenant-level documents) and filters `query`/`fetch`
  with a metadata `where` clause to the caller's own documents plus the
  tenant-shared ones (reporting `USER_SCOPED`). `user=None` is the tenant-level
  scope and is unchanged. The vector resolver exposes `user_scoped` for Chroma.
  Verified against a live ChromaDB backend by the integration tests.
- The live `WeaviateVectorStore` now *enforces* user scoping: with
  `user_scoped: true` it records each document's owning user in a FIELD-tokenized
  `owner_user` property and filters `query` (server-side) and `fetch`
  (post-lookup) to the caller's own documents plus tenant-shared ones (reporting
  `USER_SCOPED`). A non-empty sentinel marks tenant-level documents (Weaviate
  rejects an `equal("")` filter). `user=None` is the tenant-level scope and is
  unchanged. The vector resolver exposes `user_scoped` for Weaviate. Verified
  against a live Weaviate backend by the integration tests.
- The live `PineconeVectorStore` now *enforces* user scoping: with
  `user_scoped: true` it records each document's owning user in metadata (an
  empty sentinel marks tenant-level documents) and filters `query` (a Pinecone
  metadata filter) and `fetch` (post-lookup) to the caller's own documents plus
  tenant-shared ones (reporting `USER_SCOPED`). `user=None` is the tenant-level
  scope and is unchanged. `connect` and the vector resolver expose `user_scoped`.
  A non-empty `owner_user` sentinel marks tenant-level documents (avoiding the
  empty-string `$in` edge that bit Weaviate, since Pinecone is not live-verified
  here). Verified by the mock-backed contract tests - Pinecone's established
  level ("mock + opt-in live"). With this, **every live adapter** enforces user
  isolation and reports `USER_SCOPED`: Redis, pgvector, Chroma, and Weaviate each
  verified against a live backend, and Pinecone mock-verified (the live opt-in
  test runs when credentials are set). This completes the ADR-0008 live-adapter
  follow-on.
- Per-finding control mappings (the engineering spec, sections 9 and 18). Every
  probe now populates `atlas_techniques` (MITRE ATLAS) and `nist_rmf` (NIST AI
  RMF), and the detection pipeline stamps each `Finding` with the probe's
  `owasp_llm`/`atlas`/`nist`, so the evidence pack carries per-finding control
  IDs (it previously had only the run-level `controls.py` table). NIST is
  `MEASURE 2.7` (security/resilience measurement) across the catalog; ATLAS uses
  conservative, verified techniques - `AML.T0024` (Exfiltration via AI Inference
  API) for the exfiltration probes, `AML.T0024.001` (Invert AI Model) for
  embedding inversion, `AML.T0057` (LLM Data Leakage) for the data-leakage
  probes - and is intentionally empty where no clean ATLAS technique applies
  (KV-cache timing, erasure verification). A manual `pipeline.detect()` call is
  unchanged (the defaults are the multi-tenant OWASP class and no ATLAS/NIST).
  The per-class ATLAS assignments were then validated against the current MITRE
  ATLAS catalog: rag-poisoning also carries `AML.T0020` (Poison Training Data),
  agent-tool-hijack `AML.T0053` (LLM Plugin Compromise), and lora-cross-tenant
  `AML.T0024.000` (Infer Training Data Membership).
- The audit-pack PDF now renders each finding's mapped control IDs inline
  (`OWASP ...; ATLAS ...; NIST ...`), so an auditor reads per-finding control
  coverage from the findings table rather than only the run-level mapping
  section. Empty frameworks are omitted (an erasure finding shows no ATLAS, an
  unclassified finding shows no suffix). This surfaces the per-finding IDs the
  `Finding` model and `evidence.json` already carried.
- The audit-pack PDF now renders each finding's `remediation_pointer` (as an
  italic line beneath the finding) and a "Scope and methodology" section, so the
  pack covers the full spec section 8.3 layout. The methodology narrative states
  the detection method (synthetic-tenant substrate; exact/semantic/judge;
  manifest-grounded zero false positives) and the limits (Sectum does not
  remediate; the pack asserts test coverage, not legal certification).
- Parallelized the CI test run with `pytest-xdist` (`pytest -n auto`); the test
  step now clocks ~2x faster wall-clock (locally 282s -> 113s on the full
  suite) without weakening the gate. Coverage shards are combined automatically
  (`[tool.coverage.run] parallel = true`). The serial path still works, so a
  developer can run `pytest` without `-n auto` for clearer single-test output.
- The per-class attack-catalog docs (`docs/attack-catalog/class-*.md`) now show
  each probe's MITRE ATLAS and NIST AI RMF technique IDs in the header line, and
  the catalog overview (`index.md`) gains an ATLAS column - so the docs match the
  IDs the source code carries. Also fixes the Class 11 erasure page (and the
  index table) to list all seven configured erasure surfaces (vector DB,
  tracing, agent memory, semantic cache, model/fine-tune, search index, eval
  set) instead of the original five.
- A self-documenting `sectum.yaml.example` at the repo root: every block the
  config schema accepts (scenario, workdir, all eight adapter families with
  per-`kind` placeholders for the live backends, evidence chain, security/
  manifest-at-rest, detection providers and semantic threshold) with copy-and-
  edit annotations. Validated to load cleanly under `sectum.config.load_config`.
  The README quickstart now points at it.
- README now carries the spec section 20 storefront elements: an "Open Sectum
  vs Sectum Cloud" two-column comparison (both share the same evidence format,
  Cloud is hosted/managed) and a Support section linking to GitHub Sponsors
  and a commercial-support contact.
- The audit-pack PDF now renders each finding's `evidence_span` as a quoted
  italic line beneath the finding - the captured leak text from the detection
  pipeline (the engineering spec, section 6.4) IS the auditor's proof. Order
  per finding: summary (with controls), evidence (proof), remediation (action).
  Empty spans are guarded so a pipeline finding without a captured span renders
  nothing extra.
- ADR-0009 records the release-time ATLAS technique-review process:
  re-validate every probe's MITRE ATLAS IDs against the MISP-galaxy mirror of
  the catalog, restate fit, and update the per-probe source comment and
  per-class doc together. The May 2026 ad-hoc sweep that produced PR #8
  (adding T0020 / T0053 / T0024.000) becomes a per-release gate.
- `docs/samples/` now ships real outputs of the runnable examples - the
  retrieval-pivot audit-pack PDF (264 findings, all per-finding control IDs
  and remediation pointers rendered) and the GDPR Article 17 erasure
  attestation pack (per-surface ERASED/RESIDUAL DATA verdicts) - so a
  prospective auditor or DPO can see what they get without installing
  anything. Each pack ships its in-toto attestation envelope; `sectum verify
  docs/samples/erasure-attestation-evidence.json` demonstrates the
  tamper-evident chain end to end.
- `docs/glossary.md` mirrors the spec section 23 vocabulary - tenant, principal,
  marker types, ground-truth manifest, Retrieval-Pivot Rate, surface, probe,
  finding, evidence pack, BYOC, wedge - with cross-links into the attack
  catalog, evidence chain, compliance mappings, threat model, and sample
  packs. Standard buyer/auditor reference; wired into the mkdocs nav.
- The user dimension reaches the memory family (ADR-0008). `MemoryAdapter.remember`/
  `recall` take a keyword-only `user`; the runner threads it; and `FakeMemory`
  tags each entry with its writer and gains a `user_scoped` knob (reporting
  `USER_SCOPED`) so a recall returns only the caller's own and tenant-shared
  notes. The Class 8 memory-contamination probe (`memory-contamination`) is now
  principal-aware - it writes a note as the owning principal and recalls it from
  every foreign principal - so a user-scoped store yields no cross-user
  contamination while a tenant-only store surfaces a sibling user's note.
  `user=None` is the tenant-level scope and is unchanged.
- The remaining retrieval probes are now principal-aware (ADR-0006), riding on
  the user-aware vector adapter: Class 2 (`rag-entity-bleed`, the flagship),
  Class 3 (`rag-poisoning`), Class 6 (`embedding-inversion`), and Class 10
  (`ikea-extraction`) all plan from `substrate.principals()` and pass the
  observing user to detection, so a benign query - or a planted poison - that
  surfaces a sibling user's content is flagged. The runner stamps a planted
  document's `owner_user_id` with the acting principal so a user-scoped store
  filters it. End to end: against a store scoped by tenant alone these probes
  report a cross-user leak; against a user-scoped store they report none. With
  no users declared every plan is unchanged.
- The user dimension reaches the MCP family (ADR-0008). `MCPAdapter.invoke` takes
  a keyword-only `user`; the runner threads it; and `FakeMCP` records each
  resource's owning user and gains a `user_scoped` knob (reporting `USER_SCOPED`)
  so a `lookup` resolves only the caller's own resources within the tenant - a
  tenant-scoped server resolves a sibling user's resource (the leak). The Class 7
  agent-tool-hijack probe (`agent-tool-hijack`) is now principal-aware: it issues
  the confused-deputy and token-passthrough lookups from every foreign principal,
  so it catches cross-user tool-call hijacking as well as cross-tenant.
  `user=None` is unchanged; the live `StdioMCPClient` accepts `user` for
  conformance but does not yet report `USER_SCOPED`.
- The user dimension reaches the model family (ADR-0008), completing the
  generalization. `ModelAdapter.train_adapter`/`infer` take a keyword-only
  `user`; the runner threads it; and `FakeModel` tags each adapter text with its
  trainer and gains a `user_scoped` knob (reporting `USER_SCOPED`) so inference
  recalls only the caller user's own adapter within the tenant - a tenant-scoped
  model surfaces a sibling user's memorized canary (the cross-user bleed). The
  Class 9 lora-cross-tenant probe (`lora-cross-tenant`) is now principal-aware:
  it trains the adapter as the owning principal and infers from every foreign
  principal. `measure_latency` stays tenant-level (the KV-cache side channel is
  shared infrastructure, not a per-principal scope). `user=None` is unchanged.
- ADR-0007 (canonical hashing serializes every field; reject
  exclude_none/exclude_defaults to keep the evidence digest total and
  unambiguous).
- Hypothesis property tests for marker generation and canonical hashing,
  generalizing the fixed-seed reproducibility and uniqueness invariants to
  arbitrary seeds (the engineering spec, section 15).
- The Class 2 embedding-model sweep (`sectum.sweep.embedding_model_sweep`): runs
  the flagship organic-entity-bleed probe once per configured embedding model
  and records a per-model Retrieval-Pivot Rate
  (`RunMetrics.retrieval_pivot_rate_by_model`), reproducing the "stronger
  embeddings leak more" effect (the engineering spec, section 7). `FakeVectorStore`
  gains a `recall` knob that models embedding strength as how much cross-tenant
  content a query surfaces. The sweep is a fake-substrate illustration: `sectum
  probe` records the per-model rates only for in-memory-store runs whose scenario
  lists more than one embedding model (a live vector adapter records none).
- An end-to-end test suite (`tests/e2e/`) that runs each example walkthrough
  (retrieval-pivot, erasure-attestation, mcp-tenant-boundary) through the CLI to
  a verified evidence pack - the section-14 "reproduce the demo" acceptance,
  gated opt-in by `SECTUM_RUN_E2E` and run on a dedicated CI step. Plus unit
  tests closing the reported coverage gaps (the JSON Schema export, the probe
  registry, the runner's per-action adapter guards, the config-resolver
  helpers), raising line coverage from ~95% to ~97%.
- A real RFC 3161 trusted-timestamping path (`sectum.evidence.Rfc3161Timestamper`,
  `verify_rfc3161_token`): `sectum report --tsa <url>` (or `evidence.timestamper:
  rfc3161` in the config) submits the run digest to a Time-Stamp Authority and
  stores the returned token, and `sectum verify` checks that token against the
  recomputed digest. Trust is pinned independently of the pack: the verifier
  ships the public FreeTSA leaf and root built in, and `sectum verify
  --tsa-cert/--tsa-root` override them for a customer-pinned TSA. Backed by the
  `rfc3161-client` library behind a `sectum-ai-evidence[rfc3161]` extra (pinned
  `>=1.0.3` for CVE-2025-52556); a committed FreeTSA token fixture verifies
  offline in CI, and a live round-trip is opt-in via `SECTUM_RUN_LIVE_TSA`
  (the engineering spec, section 8.2).
- Configurable real embedding and judge providers for the detection pipeline
  (`sectum.probes.providers`): `OpenAIEmbeddingProvider` and an `OpenAIJudge` /
  `AnthropicJudge`, reached over their HTTP APIs (standard library only). A
  `detection` config block selects the embedder and judge (`fake` by default),
  their models, the API-key env var, and the `semantic_threshold`; the resolver
  builds a `DetectionProviders` bundle that `sectum probe` threads through every
  probe's detection. Detection stays provider-agnostic and deterministic-by-
  default; a real embedding model strengthens the Retrieval Pivot and a
  calibrated judge adjudicates candidates (the engineering spec, sections 6.4,
  13). The judge is asked a narrow structured question and never sees the
  ground-truth manifest. Verified with mocked HTTP plus opt-in live tests
  (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY`).
- Release supply-chain integrity (the engineering spec, section 17): the release
  workflow now generates a CycloneDX SBOM of the locked third-party dependencies
  (`scripts/generate_sbom.sh`, from `uv export` through `cyclonedx-py`) and signs
  the built wheels, sdists, and the SBOM with Sigstore keyless signing (the
  workflow's OIDC identity, no stored key), uploading the `.sigstore.json`
  bundles. The SBOM script is reusable locally.
- A job-runner abstraction (`sectum.jobs`): a small `JobRunner` interface
  (`map(func, items) -> list`, results in input order) with two local
  implementations - `SerialJobRunner` and a bounded `ThreadJobRunner` -
  selected by `build_job_runner(max_concurrency)`. `sectum probe` now executes
  its suite through this interface instead of an inline thread pool, so
  `--max-concurrency` is unchanged while the orchestration layer becomes the
  documented seam where a distributed backend (Temporal, Prefect) can drop in
  later without touching call sites (the engineering spec, sections 13 and 21,
  the open job-runner decision).
- At-rest encryption of the seeded substrate (`sectum.crypto`): set
  `security.manifest_key_env` to the name of an environment variable holding a
  base64 32-byte key, and `sectum seed` seals the substrate - which holds the
  ground-truth manifest and the planted canary plaintexts - with AES-256-GCM
  before it touches disk (`substrate.json.enc`); `sectum probe`/`report`/
  `erasure` open it with the same key. A wrong key or any tampering fails
  authentication. The key is referenced from the environment, never inlined
  (the engineering spec, section 17). Backed by `cryptography` behind a
  `sectum-ai[encryption]` extra; the unencrypted path needs nothing extra.
- An in-toto attestation wrapping (`sectum.evidence.to_in_toto_statement`,
  `verify_in_toto_statement`): `sectum report` and `sectum erasure` also emit
  `attestation.intoto.json`, the evidence re-expressed as an in-toto Statement
  (v1) - subject = the run bound by its canonical digest, predicate = the
  verification result (scenario/manifest hashes, metrics, control mappings, and
  which integrity anchors are present). It is a derived, interoperable view of
  the pack and adds no new trust; standard-library only (the engineering spec,
  section 13).
- A Sigstore Rekor transparency-log anchor (`sectum.evidence.RekorTransparencyLog`,
  `verify_rekor_proof`): `sectum report --rekor` (or `evidence.rekor: true`)
  signs the run digest and records a `hashedrekord` entry in a public,
  append-only log, storing the inclusion proof in the pack; `sectum verify`
  recomputes the RFC 6962 Merkle root and checks the signed checkpoint that
  commits to it. As with the TSA, the checkpoint key is pinned independently of
  the pack: the public-good instance's log keys (ECDSA and Ed25519) are shipped
  built in and selected by log id, and `sectum verify --rekor-key <pem>` pins a
  private instance's key. Verification is fully offline (no network, no current
  tree head); a committed real inclusion-proof fixture verifies in CI, and a
  live round-trip is opt-in via `SECTUM_RUN_LIVE_REKOR`. Backed by `cryptography`
  behind a `sectum-ai-evidence[rekor]` extra (the engineering spec, section 8.2).

### Changed

- Trim the README and ADR-0006 to engineering content only: drop the
  commercial Open-vs-Cloud comparison, the competitive positioning, and the
  go-to-market/buyer rationale, so the repository documents the technical
  project only.

### Notes

- Delivery sequencing: the public Apache-2.0 repositories are completed before
  any private repository is started.
- The 85% coverage gate (the engineering spec, section 15) is active as of Phase 1; the
  workspace currently reports 95% line coverage.

[Unreleased]: https://github.com/sectum-ai/sectum-ai/commits/main
