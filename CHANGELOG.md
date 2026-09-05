# Changelog

All notable changes to Sectum AI are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Schema 0.7.0.** `RunMetrics.user_steps_dropped` (probe id → count) records the
  user-level steps the runner did not run because the adapter cannot carry a user
  identity to its backend, inside the canonical hash. Packs stamped 0.6.x are no
  longer accepted by `verify` (the usual minor-bump rule); regenerate them.

### Fixed

- **A lost live surface still printed `[ok]` for the metrics that matter most.**
  The cycle-6 rule marked a probe unmeasured only when *every* surface it lists
  was lost, but `PROBE_SURFACES` lists alternatives and a run drives one of them,
  so the rule could never fire for the six two-surface probes — the ones feeding
  three of the four headline rates. A vector store that fell back to the fake
  still reported `[ok] poisoning_bleed_delta: 1 -> 0`.
- **`calibrate` still offered a threshold that catches nothing.** The new guard
  keyed on false positives alone, so a default admitting no negative *because it
  admits nothing at all* (zero recall) printed the "apply it" block and exited 0.
  And the fix had landed only on the text renderer: `--output json` still
  published the unusable default as `recommended_threshold` with exit 0, which a
  CI pipeline pipes straight into its config. Both renderers now refuse, the JSON
  nulls the recommendation and carries what the fallback scored.
- **`_load_substrate` was the one loader without the schema-line gate**, so a
  0.6.x `substrate.json` seeded a run whose own stamp then read as current and
  nothing downstream could see where the markers and manifest came from.
- Reading the pack's bytes for the schema stamps moved that read out of the `try`
  that mapped a decode error to exit 3, so `verify` on a non-UTF-8 file
  tracebacked. The runner's dropped-step count counts user-level steps, as the
  field documents (it counted plants too).
- **Repository gates**: `codespell` — the pre-commit hook CONTRIBUTING tells a
  contributor to run — failed on a clean checkout (59 hits, 46 of them in-toto's
  own spelling) and ran nowhere in CI; it now runs in CI with the `toml` extra
  that lets it read the repo's own ignore list. The Action self-test installed
  the *latest published* CLI in both jobs, so the composite wiring was never
  exercised against the checkout; a third job builds the workspace and runs the
  Action against it (`version: skip`). The integration job passed while every
  test skipped for an unreachable backend; it now asserts that tests ran. The
  release recipe stages `docs/index.md`, which step 1 tells you to bump. Core's
  modules ship a `py.typed` marker, so `sectum_ai.config` and its neighbours are
  typed for downstream users as CONTRIBUTING promises.
- **`calibrate` published a threshold its own run measured as admitting 25 of 32
  negatives, and called it "conservative".** When no threshold separated the
  classes, the shipped default was printed as the recommendation with an
  "apply it in sectum-ai.yaml" block, unscored — and that threshold gates which
  semantic candidates become CONFIRMED findings. The fallback is now scored on
  the run's own labeled set, the output says how many negatives it admits, and
  the command exits 3 without an apply block when that number is not zero. (The
  message also blamed "the offline fake embedder" for a run that used a real
  hashing embedder.)
- **The GitHub Action reported a confirmed leak for a probe that never ran.**
  Exit 2 is both "confirmed finding" and Click's usage-error code, so a `version`
  input pinning an older CLI that lacks a flag this Action passes produced
  `::error::sectum-ai confirmed a finding` over a zero-byte report. Exit 2 with
  no report is now reported as a probe that did not run.
- `untrusted()`'s escaping is injective for astral codepoints (`\uXXXX` is a
  minimum width, so U+E0001 and U+E000 followed by "1" rendered identically —
  the property the module argues for at length). The `jobs` docstring no longer
  claims concurrent probes share no mutable state (they share the adapter
  bundle, which is what the plant/read flow needs), and the synthetic-surface
  warning points at the configuration reference rather than at `sectum-ai
  adapters`, which lists only the built-in fakes.
- Docs: the JSON summary's per-model gradient is modelled, not a breakdown of
  the measured rate; the sample PDF's findings carry OWASP and NIST ids, with
  ATLAS ids and remediation pointers only where the probe declares them; the
  threat model, glossary, and substrate reference state that the user boundary
  is verified only where the adapter carries the user; ADR-0008 has an update
  appendix; Class 2's `n` is live-only on a mixed run; the release checklist
  names `docs/index.md`; the compliance table splits the isolation and erasure
  rows and restores "tested" to the EU AI Act row; the scorecard names both
  exit-3 refusals; the evidence-chain PDF section list matches the renderer; the
  extras list includes `gcs`; PHASES states its real vintage; and the README
  counts twelve attack classes, as the catalog index already did.
- **`verify` could not see an unstamped run record.** Deleting
  `run_result.schema_version` leaves the parsed pack — and therefore the attested
  digest — byte-identical, so the cycle-5 check (which reads the parsed model,
  where the field has already defaulted to the current version) passed it, and so
  did every other check. `verify` and the bundle path now read both stamps off the
  bytes; the ordinary upgrade path was the way in.
- **A plant on a user-carrying adapter still ran when no judged step survived.**
  The cycle-5 guard was applied inside the droppable branch, so a probe planting
  on one adapter and reading on another executed its plant, landed in
  `probe_versions`, and graded its class off zero observations. The whole probe is
  now dropped when nothing it would have judged can run.
- **mem0's shape guard fired in the wrong places.** It caught a renamed *row* key
  but not a renamed or re-nested `results` envelope (which came back as an empty
  tenant — an attested erasure); it aborted on a legitimately empty memory value;
  and its truncation refusal counted texts rather than rows, so a full page
  holding any blank row read as a complete listing. The envelope is validated, the
  guard keys on the `memory` key rather than its truthiness, and the cap counts
  rows.
- **A listing refusal must not discard a hit it already found.** mem0's recall and
  the LangSmith eval-set search raised on a full page that *contained* the canary,
  turning a confirmed residual into an aborted run (the trace backends were fixed
  the same way). Only a miss is refused.
- `diff` and `baseline --compare` no longer print `[not measured]` over a pooled
  count that *rose*: a run that measured more, not less, is still a regression.
  A probe is marked unmeasured on a scope loss only when every surface it can run
  against was lost, not when one alternative was.
- **A probe left with only plants graded its class PASS off zero observations.**
  On one tenant whose users are the only foreign principals, with an adapter that
  carries no user, every judged read was dropped and the plants alone ran — which
  put the probe in `probe_versions` and graded Classes 3, 4, 8 and 9 PASS (grade
  A) having asked the stack nothing. When the filter leaves a probe no judged
  step, the plants go too and the probe runs nothing.
- **`report` signed a stale run record under a current pack stamp.** A 0.6.x
  `run.json` (which recorded every adapter slot, including a live one no probe
  drove) was accepted, wrapped in a pack stamped 0.7.0, and `verify` passed
  run-scope on that phantom LIVE slot. Every loader now refuses a record from
  another `major.minor` line — an absent stamp included, since the field defaults
  to the current version — `verify` checks the run record's stamp as well as the
  pack's, and `baseline --compare` is covered like `diff` (the CHANGELOG said it
  already was).
- **Three of the four headline rates still pooled the fakes' hits.** The cycle-4
  fix reached the Retrieval-Pivot Rate only, so the same summary reported 0%
  pivot on the live pipeline beside 100% poisoning bleed, 100% inversion, and 18%
  extraction from the fake vector store, as the configured stack's. All four are
  live-only on a mixed run, and "mixed" is decided by the surfaces the run's steps
  drove (a live adapter no probe touched used to empty the Class 2 rate while the
  scorecard failed Class 2 on the same record).
- **The audit PDF and the CLI summary carried no live/fake split.** An auditor
  read "226 confirmed cross-tenant findings" beside asserted SOC 2 controls while
  the same record's OSCAL said none was confirmed on a live surface. Both now say
  how many describe the operator's systems.
- **The Class 11 trace scan read a capped page as "no trace".** Cycle 4 guarded
  the by-id `fetch_trace`; `search_traces` — what the erasure probe actually scans
  with — read the same single page of 1000 on Datadog, Helicone, LangSmith and
  Phoenix, so a retained canary past the cap attested ERASED. A *miss* on a full
  page is refused on the same rule; a marker found there is a definite residual
  and is still reported.
- **A shared-weights model's world knowledge signed a CONFIRMED residual.** The
  base-knowledge control is "the same prompt as a tenant that trained nothing",
  which a model merging every tenant's weights does not have: one that trained
  nothing and completes "Sherlock Holmes" → "221B Baker Street" produced a
  CONFIRMED HIGH finding at confidence 1.0 in a DSR attestation. Those
  fingerprints are unverifiable and the surface reads NOT_COVERED.
- `diff` and `baseline --compare` no longer print `[ok]` above a `[BOUNDARY LOST]`
  or `[SCOPE LOST]` line: a metric whose probe lost its boundary, or whose backing
  surface fell back to the fake, reads `[not measured]`, and the pooled counts do
  too. A mem0 response whose rows carry no `memory` text is a shape mismatch, not
  an empty tenant (read as empty it became "not recalled" — an attested erasure).
  `score`'s refusal says which case it is: nothing ran, or everything that ran was
  backed only by the fakes.
- **Every live vector store, both Redis adapters, and the HuggingFace model
  claimed to carry the user while discarding it.** With `user_scoped: false`
  (the default) nothing user-specific reaches the backend, yet the adapters
  inherited `carries_user = True`, so with users declared the runner ran
  user-level reads as the tenant and judged them as the user: 12 CONFIRMED
  CRITICAL cross-user leaks on a perfectly tenant-isolated Qdrant — the mem0/MCP
  defect on the default configuration. A live adapter now carries the user only
  when it scopes by user; a source-level test holds every adapter with the knob
  to it. The built-in fakes keep carrying it (the fake is the backend).
- **KV-cache timing findings never counted as live-surface findings.** They name
  the cache surface while provenance is keyed by the model adapter that ran, so
  every live-surface gate dropped them: the JSON summary said 0 confirmed on live
  surfaces and OSCAL rendered `satisfied` over twelve confirmed side channels on
  the only live surface. A finding's surface now maps to the adapter that
  produced it everywhere.
- **`score` graded a mixed-backed class on the fake's findings, and pooled the
  fake's hits into the Retrieval-Pivot Rate.** A leaking fake vector store
  beside a clean live RAG pipeline failed Class 2 and reported the fake's hits as
  the live pipeline's rate — the grade the pack's OSCAL and summary contradicted.
  Only findings on a live backing surface count (the class note says how many
  were withheld), and on a mixed run the rate is computed over the live surfaces'
  steps.
- **A re-seeded later run read every cross-user leak as resolved.** Finding ids
  embed markers and principals, so across a scenario change every finding
  "resolves" and `boundary_lost` could not fire (the later run planned no user
  steps to drop). `diff`/`baseline --compare` flag `[SCENARIO CHANGED]` as a
  regression, and refuse a record from another schema line (a 0.6.x run that
  recorded every adapter slot read as having exercised them all).
- **The recall check's echo branch was still uncontrolled on shared weights.**
  The scrambled control searched for the original phrase in the scrambled
  prompt's completion, which an echo never contains; a model that restates its
  prompt on shared weights (no base-tenant control) signed a CONFIRMED HIGH
  residual and an erasure failure. An echo of the scrambled prompt now voids the
  whole-phrase branch.
- **The A3 vector fingerprint check read a full similarity page as absence.** A
  stored subject document ranked past the top 10 attested ERASED; the page is
  now 50 and a full page without the phrase is unverifiable (NOT_COVERED), never
  erased.
- The "Live surfaces:" suffix and the OSCAL erasure verdict drew on different
  live sets (one kept caveat surfaces, one did not), so a description named a
  surface its own verdict then contradicted; one helper feeds both, and a
  caveat-only erasure run is described as scanned, not verified. The Chroma
  adapter accepts both shapes `list_collections` has returned across chromadb
  releases.
- **An erasure-only attestation asserted every isolation control it never tested.**
  `controls.py` treated any executed probe as isolation evidence, and the erasure
  probe counted — so both shipped erasure sample packs carried all eleven
  framework mappings, including SOC 2 CC6.1/6.6/6.7 *"tested by benign and
  adversarial probing"* and EU AI Act Article 15 *"robustness under adversarial
  conditions"*, on the strength of a deletion check. The isolation requirement now
  excludes the two erasure probe ids (pinned in `controls.py`, since the evidence
  package cannot import the probes, and held to the probes' declarations by a
  test). An erasure-only run asserts exactly GDPR Article 17 and CCPA 1798.105.
  The sample packs are regenerated.
- **The erasure attestation recorded no surface provenance.** v0.9.0 said a run
  "now records what it actually interrogated" and that the fix "closes that at
  all three layers" — true of `probe`, false of `erasure`, whose `RunResult` was
  built without the block. Its packs therefore reported *"predates surface
  provenance"* while stamped with the schema that carries it, the audit PDF
  printed that sentence as fact, and `verify` could not tell a fake-backed DSR
  attestation from a live one. Both erasure paths now record provenance off their
  built adapters, and the tenant-level path warns on stderr about synthetic
  surfaces as the subject path always did.
- A missing `mcp` SDK is now the typed exit-3 `ConfigError` every other extra
  gives, not a raw traceback.
- `sectum-ai adapters` lists the `app` family's fake (under `vector_store`, the
  slot it fills); its help says it lists the built-in
  fakes' capabilities rather than "installed adapters".
- The synthetic-surface warning named a `list-adapters` command that does not
  exist; the pack README said `report --tsa --rekor` where `--tsa` takes a URL;
  `verify_pack`'s docstring called `require_live=True` the default (it is the
  CLI's); the `init` template omitted the `factory` field `langchain` requires;
  the retrieval-pivot example config promised a rate that file alone cannot
  produce (its `run.sh` probes without it).
- **A bundle's unsigned manifest chose which member was "the pack".**
  `verify_bundle` verified whichever member `bundle-manifest.json` named as
  `evidence`, so a bundle carrying a genuine (even anchored) pack under another
  name and arbitrary bytes under `evidence.json` — the file the README and the
  CLI call the canonical record — passed every check. The evidence member is
  `evidence.json`, always; a manifest naming anything else is refused.
- **Bundle member names forged `[ok]` lines in `verify`'s output.** A
  `member:<name>` check echoed the archive's own member name raw, so a newline in
  it printed a fabricated `[ok] independent-anchor` line. Check names and details
  are escaped like every other record string; substrate display names in the
  unknown-tenant message likewise.
- **A live backend no probe drove satisfied the run-scope gate.** The provenance
  block recorded all eight adapter slots, including the tracing slot no catalog
  probe touches, and `verify` passes when *any* recorded surface is live — so a
  run whose every probed surface was the built-in fake verified as a
  configured-stack attestation on the strength of a real tracing adapter. `probe`
  now records provenance only for the surfaces its executed steps touched (the
  KV-timing probe's model surface when it measured anything), and an erasure run
  only for the surfaces it scanned (`--scope vector_db` records one entry). The
  gate itself now counts only an exact `LIVE` as live, and `RunResult` refuses any
  provenance value that is not a member: `"synthetic"`, `"Live"`, or `"bogus"`
  read as not-synthetic in `score` and as live in `verify`.
- **`probe` recorded, and `report` signed, a run that asked the stack nothing.**
  A single `--probe` the stack could not satisfy emptied the suite; `probe` printed
  `ran 0 probes`, exited 0, and wrote a run with no probe and no finding that
  `report` packed into a signed evidence pack, audit PDF, in-toto statement, and
  DSSE envelope, which `verify` passed. Only `score` refused. `probe` now exits 3
  without writing the run, and `report` refuses such a run (exit 3). `report` also
  refuses a run whose scenario or manifest hash no longer matches the workdir's
  substrate (a re-seeded workdir produced a signed pack `verify` then failed on
  manifest consistency).
- **A `NaN` metric read as "no regression".** `json.loads` accepts a bare `NaN`
  and `NaN > baseline` is false, so `diff` and `baseline --compare` on a
  hand-edited run exited 0. Every spec model now refuses non-finite floats on
  construction (`allow_inf_nan=False`), so the run fails to load (exit 3).
- **`diff` tagged a coverage-lost metric `[ok]`.** `_render_diff_text` called the
  verdict helper without the coverage-lost list the `baseline` path passes, and
  the un-bracketed headline metrics (`poisoning_bleed_delta`,
  `inversion_reconstruction_rate`, `extraction_efficiency`, `retrieval_pivot_rate`)
  never matched the `[probe-id]` rule — so a probe that did not run read as
  `[ok] poisoning_bleed_delta: 0.5 -> 0`, a fixed leak. Both now read
  `[not measured]`.
- **An erasure run that verified nothing signed GDPR Art. 17 / CCPA §1798.105 as
  "verified".** The erasure control requirement was "the coverage block is
  non-empty", and the block names every erasure surface — so eight `NOT_COVERED`
  verdicts (no baseline, no adapter, out of scope) carried both deletion mappings
  and the OSCAL projection rendered them `satisfied`. The requirement is now a
  surface scanned to `ERASED` or `RESIDUAL`.
- **A phoenix / langfuse / langsmith observability kind without its extra was a
  raw traceback**, not the typed exit-3 error every other family gives — the
  sibling of the v0.11.0 `mcp` defect.
- **The in-toto verifier accepted a statement with a foreign subject beside the
  genuine one**; a statement now attests exactly one subject.
- **`verify` reported the Rekor integration time as a verified fact.** The
  inclusion proof binds the digest; the integration time is a field nothing the
  verifier checks signs (the same proof verifies with any time), so the check now
  reports it as the log's claim.
- **A judge answering `{"leak": "false"}` read as a leak** (`bool("false")` is
  `True`); the field must be a JSON boolean.
- **SARIF and OSCAL labelled every finding a "cross-tenant leak"** — an erasure
  residual (same tenant on both sides), a cross-user leak inside one tenant, and
  the informational 200-empty candidate all rendered as a confirmed cross-tenant
  breach. Each is now labelled by what it is. Both projections carry the run's
  surface provenance, and an OSCAL document for a run whose every surface was the
  built-in fake states no control finding at all (its result says why).
- **The audit PDF never named the probes that ran** — a one-probe pack and a
  twelve-probe pack rendered identically apart from the digest, while the scope
  paragraph said scope was "limited to the probes exercised". Both engines now
  list them in the summary.
- The DSSE sidecar check said "sidecar binds this pack's run digest" for an
  envelope `report` writes with `signatures: []`; the detail now says the envelope
  is unsigned (or, when signed, that no signature was verified here), and the
  docstring no longer points at a `sigstore` module that does not exist.
- **The RAG-pipeline and agent-framework probes confirmed cross-user leaks of
  sessions that never existed.** `rag.ask` and `agent.run` carry no user, so a
  user-level step ran as the tenant and was judged as the user: on a
  tenant-isolated pipeline and agent, two tenants of two users produced 12 and 8
  CONFIRMED CRITICAL "cross-user" findings from sibling users' markers in the
  tenant's own answers. Both probes plan from tenant-level principals only, as
  ADR-0006 already said the tenant-keyed adapters require; the MCP end of Class 7,
  whose `call_tool` carries the user, keeps its user-level coverage.
- **Subject-erasure prefix-continuation counted any completion as memorization.**
  The trailing half of an email was its domain and of a two-word name its
  surname, so a model never trained on the subject signed a CONFIRMED HIGH
  residual (confidence 1.0) for `alice.brown@example.com` and `John Smith`. The
  check now has a control arm (a same-shaped prefix naming nobody must not
  complete to the same trailing part), cuts an email inside its local part, and
  does not check a phrase whose trailing part is under six characters — that
  surface reads `NOT_COVERED` for it rather than a verdict a guess could produce.
- **Class 5 missed a perfect side channel and diluted a real one.** Zero
  within-arm spread gave an infinite t with zero degrees of freedom (read as
  p = 1) and Cohen's d = 0, so a jitter-free, constant 60 ms cross-tenant gap
  produced no finding; variances are now floored at the timer's resolution. And
  with one prefix per tenant pair, on a backend whose latency call runs inference
  (HuggingFace) the observer's own first trial warmed the primed *and* control
  prefix for every later trial, so a genuine shared cache survived in one trial
  of twenty-four (d ≈ 0.25, no finding); the owner now warms one prefix per trial,
  each measured exactly once, and the control prefix is fresh per trial.
- **A token-identical foreign entity with a changed separator was vetoed by a
  judge "no".** The verbatim rule was a substring test, so `Project Quasar7K2Q
  00001` for the marker `Project Quasar7K2Q-00001` reached the judge alone and a
  cautious real judge downgraded it while the fake judge confirmed it. The
  marker's tokens contiguous and in order are the entity, by observation.
- **A serving-only model turned an otherwise ERASED erasure run INCONCLUSIVE.**
  vLLM/TGI hold no per-tenant weights, so the model surface scanned to a zero
  baseline — `NOT_COVERED`, correctly — but a zero-baseline surface also made the
  report's `erased` false (exit 3). The model is left out of the scan plan when it
  cannot memorize, and reads `NOT_COVERED` through the coverage block alone.
- The `ERASED` verdict's gloss (audit PDF, catalog) now says what it measures:
  no marker retrievable through the erased tenant's own read path. A backend that
  retains data while revoking that path is indistinguishable from outside.
- **The HuggingFace LoRA `soft_delete` hid the retained weights from the erasure
  scan.** A soft delete re-routed inference to the base model while the LoRA
  stayed on disk, so the model surface's post-erasure scan (`marker in
  infer(...)`) found nothing and signed ERASED for weights still there — the
  inverse of the built-in fake, which keeps recalling. A soft delete now keeps the
  LoRA serving, and a hard `delete(tenant)` removes every scope under the tenant
  (the per-user `<tenant>/<user>` LoRAs used to survive a tenant erasure).
- **S3 and GCS backups verified erasure on versioned buckets that kept every
  byte.** On a versioned S3 bucket (Object Lock implies versioning) a plain
  delete inserts a delete marker and keeps the versions, and `list_objects_v2`
  hides the key, so the re-scan read the retained snapshot as gone. The adapter
  now lists and deletes every version, reads versions in its scan, and refuses a
  `delete_objects` call that leaves any key in place. GCS with object versioning
  is the same shape (every generation is listed and deleted), and a bucket whose
  soft-delete policy keeps deleted objects restorable — the default for buckets
  created since 2024 — reports attestable-with-caveat instead of an erasure.
- **Langfuse stopped at 1000 traces and gave up silently.** The listing was
  capped, so `delete` purged the first thousand, waited for a tenant that could
  never empty, and returned; the re-scan (now the older page) showed no marker
  and the tenant verified erased. The listing is paged to exhaustion and refused
  past its budget, `delete` raises when the purge does not settle, and the docs
  name the `user_id` tagging precondition and the observation-level scan gap.
- **A by-id miss on a capped page attested erasure** on Datadog, Helicone,
  LangSmith, and Phoenix (one page of 1000); a miss on a full page is now refused.
  A 200 carrying an error envelope (or no `data` list) is an error, not an empty
  tenant, on Helicone, Datadog, and the OpenTelemetry reader; the OpenTelemetry
  reader treats a `DELETE` `404` as a purge only when its query then shows no
  spans (a router that never implemented DELETE answers 404 too).
- **Pinecone and Azure AI Search read back before the write landed.** Both index
  asynchronously; an upsert followed by an immediate query found no baseline, and
  a delete followed by an immediate re-scan reported the not-yet-purged vectors as
  an erasure failure. `upsert` and `delete` now wait (bounded) for the index to
  reflect them, and raise when it never does.
- **A misspelled adapter field was silently ignored.** `shared_idx: true` built a
  fake with `shared_index=False`; `confused-deputy: true` a fake with no deputy;
  the run then graded the default. A field in an operator's block that the family's
  builder never reads is refused at build (exit 3, naming it) — the field-level
  sibling of the v0.10.0 unknown-family check. The CLI's own internal defaults are
  not held to it.
- mem0 `recall` lists the scope exhaustively instead of a ranked 100-hit window a
  planted marker could fall out of; the OpenSearch search index refuses a search
  whose matches exceed the returned page; the OpenAI Assistants run loop gives up
  after a timeout instead of polling a parked run forever; both OpenSearch
  adapters verify TLS certificates by default; the Chroma adapter no longer
  recreates a deleted tenant's collection on a read.
- The built-in fake vector store now replaces a document on re-upsert (it
  appended, duplicating hits), applies its recall filter before the top-k cut (the
  tenant's own hit could be dropped), and iterates a snapshot under
  `--max-concurrency` (a concurrent first upsert raised mid-scan).
- docs/adapters.md states that the user filter on a by-id `fetch` is applied by the
  adapter, not the store, on six of the eight vector stores, and the two limits of
  the in-band agent tenant scope.
- **A bundle verified with forged auditor-facing members it listed.** The digest
  manifest is unsigned, yet the verifier printed `[ok] member:... digest matches`
  for any listed name and bound only the *first* PDF and in-toto member it found:
  a genuine pack plus a forged `erasure-attestation.pdf`, a forged
  `erasure-attestation.intoto.json`, and an arbitrary `summary-for-auditor.pdf`
  passed. Only the member names Sectum writes are admitted; every present PDF and
  in-toto member is bound to the pack; the per-member lines say "matches the
  unsigned manifest" and name the README, redacted config, and sealed manifest as
  unbound.
- **A finding from the built-in fake moved every control.** On a mixed run, one
  confirmed finding produced by the semantic-cache *fake* flipped all twenty OSCAL
  control findings to `not-satisfied` (the finding `score` says "describes that
  fake"); conversely a clean fake earned `satisfied` for every framework, and a run
  with **no** provenance block rendered every control satisfied. Control mappings
  now require evidence from a live surface (an isolation probe against one; an
  erasure verdict on one), OSCAL derives its verdicts from live-surface findings
  only and names the excluded fake surfaces, and a run with no live surface states
  no control finding. Erasure controls are titled "erasure verification" and their
  verdict speaks of residual markers, not of a "cross-tenant leak"; the demo and
  sample packs, all-synthetic, now carry no mappings.
- **The audit PDF summary called erasure residuals "Confirmed cross-tenant
  findings".** Both engines now count confirmed findings by what they are
  (cross-tenant, cross-user, residual-data); the SARIF rule text does likewise; and
  `probe`'s summary line says "N confirmed findings (...)" whenever they are not
  all cross-tenant.
- **`diff` and `baseline --compare` read a live-to-fake fallback as "no
  regression".** Two records identical except that every surface went LIVE to
  SYNTHETIC diffed as clean, exit 0. A live surface that is the fake (or absent)
  in the later run is `[SCOPE LOST]` and a regression. A headline metric now reads
  `[not measured]` when *any* of its feeding probes was lost, not only when all were.
- The in-toto verifier requires the subject's `name` to be the pack's run id, not
  only its digest.
- **The live MCP clients dropped the user, and the MCP probe confirmed cross-user
  leaks of sessions that never existed.** `invoke(..., user=)` was accepted "for
  interface conformance" and never transmitted, so every user-level Class 7 step
  ran as the tenant and was judged as the user: on a correctly tenant-scoped
  server, two tenants of two users produced 12 CONFIRMED CRITICAL "cross-user"
  findings. Every adapter now declares whether it carries the user
  (`carries_user`); the RAG, agent, and observability contracts never do, the
  live MCP clients do only with the new `user_argument` (the tool argument that
  carries the calling user, beside `tenant_argument`), and the runner drops
  user-level steps for an adapter that does not, so a run claims only the
  boundary it could exercise.
- **Class 5 could not hit a block-granular prefix cache.** vLLM's automatic
  prefix caching hashes whole 16-token blocks and never a partial one; the
  20-character prefix (9-12 tokens) could not produce a single hit, and the probe
  recorded Class 5 PASS against a backend with a shared cache. Each prefix now
  opens with its 20-character key and continues with filler spanning several
  full blocks. The key is a hash of the tenant id (two low-valued ids shared
  their leading hex, so one owner's warm-up primed the other's measurement on a
  correctly scoped cache), and the variance floor is a 1 µs resolution, not the
  1 ns the constant encoded.
- **The subject-erasure control arm was a no-op for non-Latin subjects, and blind
  to world knowledge.** The scramble rotated ASCII letters only, so a Cyrillic,
  Greek, or CJK prefix was its own control and every genuine recall was vetoed —
  a memorised non-Latin subject attested ERASED (and a superscript digit crashed
  it). It now scrambles any script and refuses a prefix it cannot change. A
  second control on per-tenant models asks the same prefix as a tenant that
  trained nothing, so `Hussein Obama` after `Barack` is the base model's
  knowledge, not a CONFIRMED HIGH residual. Fingerprints the check cannot verify
  no longer drop silently: the model surface reads NOT_COVERED for the subject
  and the report counts them. The tenant probe's canary model scan uses the same
  continuation test, so a real LoRA that continues a memorised canary rather than
  echoing it is RESIDUAL, not invisible.
- mem0's `get_all` defaults to a 100-entry limit the SDK pages no further, so the
  "exhaustive" recall was capped at 100; the adapter asks for 10 000 and refuses
  a listing that hits it. The OpenTelemetry query contract states that an empty
  marker matches every span of the tenant (what the 404 check relies on).
- **A run that quietly stopped exercising the user boundary read as a fix.**
  Dropped user-level steps left no trace: removing `user_argument` from a live MCP
  config turned 16 confirmed findings into 4, and `diff` / `baseline --compare`
  read the 12 resolved cross-user leaks as resolved (`[ok]`, exit 0). The count is
  now in the signed metrics, the JSON summary, the PDF's probe line, and a CLI
  warning; `diff` and `baseline --compare` flag it as `[BOUNDARY LOST]`, a
  regression. The runner also runs a user-owned *plant* as its tenant instead of
  dropping it — dropping it starved the tenant-level reads, so a store that leaks
  across tenants read clean with the probe recorded.
- **mem0 and the serving-only models inherited "carries the user".** mem0's flat
  `user_id` space is the tenant, so Class 8 planned user-level steps there and
  confirmed 8 CRITICAL cross-user leaks of sessions that never existed — the same
  defect as the live MCP clients, one adapter over. Both declare `carries_user =
  False`.
- **Isolation controls were asserted on any live surface.** The OWASP LLM08 row
  ("vector and embedding weaknesses") — and every other isolation row — was
  asserted on a run whose only live surface was MCP and whose vector store was the
  leaking fake: twenty `satisfied` OSCAL controls over 213 findings `score`
  withholds. A row about specific surfaces needs one of them live, and every
  mapping in a pack ends with the live surfaces it rests on.
- **The recall check's whole-phrase branch had no control.** A chatty base model
  that restates the prompt ("I have no record matching 'John Smith'") signed a
  RESIDUAL for a tenant that trained nothing, and a hard delete then read as an
  erasure failure; on a live HuggingFace model the Class 11 model baseline could
  come only from such an echo. Both controls now apply to the echo branch. One
  unverifiable fingerprint no longer suppresses the scan of the verifiable ones
  (a measurable residual was replaced by NOT_COVERED).
- **The OSCAL erasure verdict ignored caveat surfaces** (no per-tenant erasure API,
  data presumed retained): "verified the erasure on every live surface" rendered
  over three markers presumed retained, under the isolation narrative. The verdict
  comes from the coverage block and the result describes an erasure run.
- A bundled PDF the pack binds no `pdf_ref` for is refused (the first one rode
  unbound). The JSON summary carries `confirmed_on_live_surfaces` and the run's
  provenance beside `confirmed_findings` (which counts every surface, the fakes
  included), and the Action carries the live count as an output. The LangSmith eval set refuses a search that hit
  its 1000-example cap.
- Docs: the schema-reference paragraph said a misspelled adapter field is silently
  ignored (it is refused); the example config's `openai-assistants` and
  `anthropic-tooluse` blocks said the YAML "only flips the kind" (a `factory` is
  required) and lacked the `app` family; the HuggingFace module docstring still
  described soft delete as routing to the base model; `sectum-ai adapters` lists
  the app fake under `vector_store`; `erasure --help` and `diff --help` under- and
  over-stated their inputs; the rag-poisoning plan queries from principals foreign
  to a planted poison; Langfuse pages where the other four read one page; the
  samples table no longer carries sizes that drift on every regeneration.


## [0.11.0] - 2026-09-01

The first surface outside the AI stack, and the label discipline that made it
safe to add. A stack whose vector store, cache, memory, and agent framework are
all perfectly isolated — but whose `GET /api/documents/{id}` hands over another
tenant's document — is the same breach, and graded `A` before this.

Adding it needed no probe change and no schema change. What it did need was for
every consumer of "which surface is this" to read the adapter rather than a
literal, which is the rest of this release.


### Added

- **`app` — the application's own resource API as a probed surface.** The surfaces
  Sectum verifies are the AI stack; `app` is the application in front of it, reached
  through the *same* contract a vector store is: a write, a search, and a
  read-one-by-id that **is** the Class 1 cross-tenant object-reference primitive. It
  fills the vector slot, so every probe driving that slot runs unmodified — no probe
  changes, and no schema change, since `Surface.API` was already in the enum and in
  the committed JSON Schemas.

  It declares what it is rather than what slot it occupies: `Surface.API`, so its
  findings and the run's provenance both say `api`; and no semantic retrieval, so
  Class 6 and Class 13 are skipped rather than passing vacuously. Configuring both
  `app` and `vector_store` is refused — a run carrying both cannot say which system
  it probed. `kind: fake` only for now; a live HTTP adapter is not implemented, and
  says so rather than falling back.

  Why it exists: a stack whose vector store, cache, memory, and agent framework are
  all perfectly isolated, but whose `GET /api/documents/{id}` returns another
  tenant's document, is the same breach — and graded `A` before this.

### Changed

- `PROBE_SURFACES` now lists every surface a probe's adapter slot may legitimately
  speak for, and a class is attributed to whichever of them the run actually
  recorded. Rule 6 fires when *none* matches, which is the case it was written for;
  an API-backed vector slot is now a supported attribution rather than an
  unaccountable one.
- The probe-skip message no longer offers a LoRA-specific example for every
  capability gate — it names the missing capability and states that the class is
  reported `NOT_COVERED` rather than passed. The example was written when one probe
  used the mechanism and misdescribed every gate added since.

- **The provenance block now reads its surfaces off the adapter too.** v0.10.1
  stopped the runner stamping `Surface.VECTOR_DB` onto every `vector.*`
  observation — but only in `runner.py`. `surface_provenance` carried the
  identical coupling: liveness came off the adapter instance while the *key* came
  from a static slot → surface map. An adapter declaring a different surface would
  have produced findings labelled one way and a provenance block keyed another,
  inside a single signed record. Behaviour-preserving for every adapter shipping
  today, and pinned by a test that the two agree.
- **Scorecard honesty rule 6: a class graded against an unaccountable surface is
  `NOT_COVERED`.** `PROBE_SURFACES` records which surface each probe's adapter slot
  normally speaks for, but an adapter declares its own — so a run's provenance can
  name a surface the catalog cannot tie to a class. Grading it would assert a
  verdict about a system the scorecard cannot identify, so it fails closed, exactly
  as rule 1 does for a class that never ran. A record carrying no provenance at all
  (produced before v0.9.0) is exempt: its absence is not evidence of a mismatch.
  The class note states only what the scorecard knows — which surface it
  expected and that the run does not record it — never the unrelated surfaces
  the run happened to exercise, since naming those would imply the very
  attribution the rule refuses. A run in which *every* class is unattributable
  refuses to grade at all rather than emitting a meaningless letter.
  `METHODOLOGY_VERSION` is **1.2**.


## [0.10.1] - 2026-09-01

Housekeeping with one theme running through it: a label should be declared by
the thing it describes, and a check that cannot be performed should say so rather
than pass. Nothing here changes what any shipping adapter measures — the two
correctness fixes matter for backends that do not exist yet, which is the cheapest
time to fix them.


### Changed

- Dependency floors raised to match the locked versions: `ruff>=0.16.3` (resolves
  to 0.16.5 — no lint or format changes across 288 files), `pillow>=12.3.0`,
  `rfc3161-client>=1.0.8`, `langchain-core>=1.5.4`, `google-cloud-storage>=3.13.1`.
  Drained as one batch rather than five PRs, which each would have
  cascade-conflicted on this file. `pillow` and `rfc3161-client` are in the
  default sync and covered by 38 executing tests; `langchain-core` and
  `google-cloud-storage` sit behind extras that no CI job installs, so those two
  are constraint-only — their locked versions already satisfied the new floors.

- **Classes 6 and 13 now run only where their mechanism exists.** Both describe a
  *vector-space* effect: Class 6 reconstructs a foreign entity from a partial
  fragment and reports it as `AML.T0024.001 Invert ML Model`, and Class 13 is the
  Retrieval Pivot through a shared multi-modal embedding space. Neither declared a
  capability gate, so both ran against any store filling the vector slot. A
  backend that matches on substrings can return a whole document for a fragment
  query with no embedding involved — recorded as embedding inversion, a real
  result attributed to a mechanism the backend does not have — and a backend
  finding nothing scored the class `PASS`, credit for a check that could not be
  performed. Both directions are the failure mode the honesty rules exist to
  prevent. `VectorStoreAdapter.semantic_retrieval` defaults to `True`, so every
  store Sectum ships is unaffected and none can forget the capability; a backend
  that retrieves some other way sets it `False` and those classes report
  `NOT_COVERED`.

- **An observation is labelled by the adapter that produced it, not by its
  action.** The runner stamped a literal onto every observation — a
  `vector.fetch` step always produced `Surface.VECTOR_DB` — which holds only
  while one family can ever fill a slot. That label reaches the signed evidence,
  the scorecard's per-class lines, and the audit pack, so an adapter speaking for
  a different surface would have had its findings filed under the wrong one.
  `Adapter.surface` is now declared by each family base and read by the runner;
  every adapter shipping today keeps exactly the label it had. Same shape as the
  v0.9.0 provenance fix: a fact declared by the thing it describes, rather than
  inferred from something incidental next to it.

### Fixed

- The `README.md` status line advertised **v0.8.1** while the repo shipped
  0.10.0 (two releases stale). Bumped it to v0.10.0 and added a standing test
  (`tests/unit/test_action_version.py`) that ties the README status version to
  the shipped package version, the same guard the Action default already has.

## [0.10.0] - 2026-08-17

The last way a config could look live and probe nothing. v0.9.0 made a synthetic
run *visible* — recorded in the signed evidence, scoped in the grade, refused by
`verify`. All of that reports after the run. This closes the most common way one
started: an adapter family whose key the resolver never reads.

Minor-version rather than patch because a config carrying such a key now fails to
load. If you have one, it has never been doing what you intended.

### Changed

- **An unknown adapter family is now rejected at config load instead of ignored.**
  Every resolver reads its family with `config.adapters.get(name, fake)`, so an
  unrecognised key was never looked up: the family fell back to the built-in
  in-memory fake and the run proceeded as though configured. `vector:` instead of
  `vector_store:` is the whole failure — one character short of a real backend,
  written by an operator who then believed they had probed production. 0.9.0 made
  that visible *after* the fact (the run records the surface as `SYNTHETIC`); this
  closes it before anything is seeded. The error names the key, suggests the
  family it most likely meant, lists the valid set, and says what would otherwise
  have happened.

  **This is a breaking change for a config that carries such a key** — which is
  the point, since it was never doing what its author intended. A family you want
  left synthetic should be *omitted*; omission is deliberate and is still recorded
  as `SYNTHETIC` in the run's surface provenance.

## [0.9.0] - 2026-08-15

Sectum ships an in-memory fake for every adapter family and falls back to one
silently, so a run that touched **nothing real** produced a `GRADE A` at
`confidence: high`, packed into a signature-clean attestation, and rendered an
audit PDF indistinguishable from a production assessment. Every honesty rule the
tool had answered *what did this run check*; none answered *what did it check
against*. This release closes that at all three layers — the signed record, the
grade, and the verifier.

**If you verify packs in CI, read this:** `sectum-ai verify` now refuses a pack in
which no surface was live. A demo or self-test pack needs `--allow-synthetic`
alongside `--allow-unanchored`. A pack from a real, configured run is unaffected.

### Added

- **A run now records what it actually interrogated, not just which adapters it
  named.** `RunResult` carries a `surface_provenance` block — `LIVE` or
  `SYNTHETIC` per surface — inside the canonical hash, so the disclosure is
  signed alongside the findings. Sectum ships an in-memory fake for every adapter
  family and resolves an omitted key to one, which meant a run against eight
  fakes graded `A` at `confidence: high`, packed into a signature-clean
  attestation, and produced an audit PDF that never used the word *synthetic*.
  The only prior trace was `adapter_versions` keys reading `fake-vector`, and an
  adapter's name is a constructor argument any caller can set to anything —
  provenance is now a declared class attribute (`Adapter.synthetic`) read off the
  built instance. A misspelled adapter key (`vector:` instead of `vector_store:`,
  which the open `adapters` mapping accepts silently) is therefore recorded as
  the fake it resolved to, not the backend the config appeared to name.
- `probe` warns on stderr naming every surface that fell back to the synthetic
  stack — the warning the DSR path has always emitted, generalized to the probe
  suite, where the operator can still fix the config.
- **The scorecard states which stack its letter is about** — honesty rule 5, and
  the consequence of the block above. `IsolationScore` carries a `scope` and the
  `synthetic_surfaces` behind it, both rendered beside the grade. A run with no
  live surface is unambiguously the demo (the quickstart configures nothing), so
  it still grades — under a scope line naming the synthetic stack. A run with
  *some* live surfaces was an attempt at a real assessment, and its remaining
  fakes are silent gaps the operator believes were covered: there, a class whose
  probes all ran against fakes is `NOT_COVERED` and drops out of the letter. That
  closes both directions — a pass against a fake was false assurance, and a leak
  from a fake was a false alarm about production. Those findings are still counted
  and named on the class line, so rule 4 still holds: nothing is dropped silently,
  it just no longer moves the grade.

- **`verify` answers what the pack is about, not only whether its bytes are
  intact.** A new `run-scope` check reports the run's signed provenance, and
  `sectum-ai verify` now **refuses** (exit 4) a pack in which no surface was
  live. Every other check in the verifier concerns the bytes — the digest
  recomputes, an anchor binds it, the PDF matches its bound hash — and all of
  them pass just as cleanly for a run against Sectum's own in-memory fakes, so
  "the signature is valid" and "this describes a real system" were unrelated
  facts and only the first was checked. Fails closed like the anchor check,
  because a third party receiving a vendor's pack is the party least able to
  notice what is missing from it; pass `--allow-synthetic` to accept a demo pack
  knowingly. The library's `verify_pack(require_live=...)` defaults off and the
  CLI sets the policy, matching how `require_anchored` already works.
- **The audit PDF states its subject in the first line of "Scope and
  methodology"** — which surfaces were live backends and which were Sectum's
  built-in stores, and, when none were live, that the pack is a demonstration
  rather than an attestation. Shared by both PDF engines so they cannot disagree
  about the paragraph that fixes the document's subject.

### Changed

- `sectum-ai verify` on a demo pack now needs `--allow-synthetic` alongside
  `--allow-unanchored`. The shipped examples, the sample-pack docs, and the
  regenerated sample artifacts all say so.
- `METHODOLOGY_VERSION` is **1.1** (from 1.0) for scorecard honesty rule 5.
  `docs/scorecard.md` publishes the scope table and the reasoning behind the
  asymmetry between an all-synthetic and a partly-synthetic run.
- `SCHEMA_VERSION` is **0.6.0** (from 0.5.0) for the `surface_provenance` block
  and the scorecard's `scope` / `synthetic_surfaces` fields.
  Per the evidence chain's existing compatibility policy, a verifier refuses a
  pack from a different `major.minor` rather than risk mis-verifying it, so packs
  signed under 0.5.0 must be verified with a 0.8.x-or-earlier `sectum-ai verify`.
  The shipped sample packs and the reproducibility goldens are regenerated.

### Fixed

- **The detection module's own docstring described pre-0.8.0 behaviour.** It
  headlined "Zero false positives by construction" — the claim 0.8.1 retracted
  from `docs/substrate.md` and `docs/vs-deepteam.md` — and it described
  confirmation as happening "only on an exact hit or a positive judge verdict",
  which stopped being true in 0.8.0, when a verbatim foreign entity began
  confirming on observation regardless of the judge's verdict. So the file that
  *implements* detection had been documenting a rule the code no longer followed.
  The wording now mirrors the corrected `docs/substrate.md`: confirmations are
  bounded to the manifest's own markers, which is not the same as asserting every
  confirmation is correct — a semantic confirmation still rests on the configured
  judge. The closing invariant is unchanged and still holds: text containing no
  manifest marker can never produce a confirmed finding
  (`tests/invariants/test_zero_fp.py`). The same retracted wording is also
  corrected in the Class 1 attack-catalog page and the open-webui example README.

## [0.8.4] - 2026-08-14

### Fixed

- **The GitHub Action was installing sectum-ai 0.6.0.** `action.yml`'s `version`
  input default is passed straight to `pip install "sectum-ai==<version>"`, and it
  had read `0.6.0` since the v0.6.0 release — so every default run of
  `sectum-ai/sectum-ai@vX.Y.Z` through v0.8.3 installed a CLI six releases old.
  That CLI **predates every correctness fix in 0.8.0**: the Datadog fifteen-minute
  search window that attested still-retained subjects ERASED, the single-token
  subject fingerprint that was never probed for memorisation, the judge verdict
  that could veto a verbatim cross-tenant leak, the KV-cache side-channel findings
  manufactured out of machine drift, and the audit pack's zero-false-positive
  claim. Anyone relying on the Action for CI verification was running the versions
  those releases exist to replace, and should re-run against this one.

  The release runbook is the root cause and is fixed too: `docs/RELEASING.md` listed
  only the five `pyproject.toml` files, so following it faithfully still shipped the
  bug. A test (`tests/unit/test_action_version.py`) now fails the build whenever the
  Action default, the documented default, or the pin example drifts from the shipped
  version — the drift is invisible by construction, since a stale version string
  looks exactly like a current one.

## [0.8.3] - 2026-08-13

Dependency constraints on five optional extras. No probe, detector, evidence, or CLI
behaviour changes, and no effect on what an evidence pack asserts.

### Changed

- **Five optional extras now require newer floors**: `sectum-ai-adapters[huggingface]`
  requires `transformers>=5.14.1` and `peft>=0.20.0`, `[tgi]` requires
  `huggingface_hub>=1.26.1`, `[langgraph]` requires `langgraph>=1.2.10`, and the dev
  group requires `types-pyyaml>=6.0.12.20260724`. Only the optional extras are
  affected; the core install is unchanged. The adapter call surface of each was
  verified against the resolved version rather than trusted to CI, which does not
  install these extras and so never executes the code that depends on them.

### Internal

Not shipped in the distributions (the wheels are built `only-include`
`src/sectum_ai`), recorded here because it changes how dependency bumps are reviewed:
a new `extras-contract` CI job installs the seven third-party packages whose APIs the
live adapters call — at the versions the lockfile resolves — and asserts every
attribute and parameter those adapters pass. Previously a bump to any of them earned a
green check list having executed none of the affected code, which is how a two-major
`cohere` bump passed unexamined in 0.8.2's cycle.

## [0.8.2] - 2026-08-07

Dependency constraints and a documentation-index fix. No probe, detector, evidence,
or CLI behaviour changes, and no effect on what an evidence pack asserts.

### Changed

- **`sectum-ai[cohere]` now requires cohere 7.x** (`>=7.0.5,<8`, was `>=5,<6`), and
  **`sectum-ai-adapters[langfuse]` requires langfuse `>=4.14.0`** (was `>=4`). Only
  the optional extras are affected; the core install is unchanged. The cohere jump
  crosses two majors, so the adapter was checked against the resolved 7.0.8 rather
  than trusted to CI, which never exercises it: the extra is opt-in and not installed
  there, so the client path does not run and the one test touching it asserts the
  package is *absent*. `cohere.Client`, the `embed(texts=, model=, input_type=)`
  parameters, and both response shapes are intact, and `CohereEmbedding._vectors`
  already reads either.

### Fixed

- **The examples index listed a removed example.** `examples/byoc-runner/` was moved
  out of this repository, but `examples/README.md` still listed it, which the standing
  index guard (`tests/unit/test_examples_index.py`) fails on. The stale prose sentence
  and table row are removed, along with the now-dead `_WITHOUT_A_RUNNER` exemption
  naming it — an exemption for a directory that no longer exists is the same
  enumeration drift that test exists to catch.

## [0.8.1] - 2026-08-02

Documentation only — no code, no behaviour change, no effect on an evidence pack.
Three places where the docs described the tool inaccurately, found by auditing the
docs surface against the code after 0.8.0's fifteen fixes.

### Fixed

- **Docs claimed the KV-cache probe ran half as many trials as it does, at a
  significance bar 12× looser.** The Class 5 example README described "24 paired
  trials per tenant pair, half primed and half control" — the probe runs 24 per
  *condition*, so 48 timed prompts per pair (`run.sh` in the same directory said
  "per condition" and was right; the two contradicted each other). The README and
  `run.sh` both quoted the gate as `p < 0.01` while the probe applies a
  Bonferroni-corrected level — `0.01` divided by the number of ordered tenant-pair
  comparisons, so `p < 0.00083` on the four-tenant demo. Both now state the real
  figures, and the README documents why the two conditions are interleaved.
- **Docs overstated the detection guarantee and described a superseded mechanism.**
  `substrate.md` and `vs-deepteam.md` headlined "zero false positives by
  construction"; the property the tests actually pin is that a confirmation ties
  back to a manifest marker, which bounds confirmations rather than proving each
  one correct. `substrate.md` also still said a finding is `CONFIRMED` "only on an
  exact/format hit or a positive judge verdict", which stopped being true in 0.8.0
  when a verbatim foreign entity began confirming on observation regardless of the
  verdict. Both corrected; the accurate `HARD_CANARY` and `calibrate` uses of the
  term were left alone.
- **The Class 2 page presented the modelled embedding gradient as a measurement.**
  0.8.0 relabelled that gradient in the CLI, the metrics, and the config table, but
  the attack-catalog page it links to still read "runs the probe once per model and
  reports a per-model rate" — the exact misreading the relabelling exists to
  prevent. It now states that the sweep builds its own shared index and never
  queries the configured vector store, and that a gradient needs two or more *real*
  models (a mixed config drops `fake-*` names with a warning).

## [0.8.0] - 2026-08-01

Every fix below corrects something the tool **claimed but had not measured** — or,
in one case, claimed on the strength of noise. Several change what a signed evidence
pack asserts, so a pack produced by an earlier version may state a verdict this
version would not: re-run before relying on an erasure attestation, a KV-cache
side-channel finding, or a per-model retrieval gradient.

One change is breaking for configuration: `detection.semantic_threshold` now rejects
values outside `[0.0, 1.0]`, which previously loaded and silently disabled the
semantic detector. A config carrying such a value will fail to load until corrected.

### Fixed

- **A drifting machine manufactured KV-cache side-channel findings.** The Class 5
  timing probe measured all primed trials and then all control trials, so every bit
  of drift during a run — thermal throttling, CPU frequency scaling, a noisy
  neighbour, GC — landed on whichever block ran second, and Welch's t-test read the
  offset as a cross-tenant side channel. Against a model with **no prefix cache at
  all**, so no channel to find, a drift of 0.01 ms per call flagged all 12 tenant
  pairs, each with an identical mean gap of `_TRIALS × slope` — the block-size
  artifact itself rather than a per-pair signal. The two arms are now interleaved,
  alternating which is timed first, so their mean measurement positions are equal
  and a linear drift cancels exactly (`_TRIALS` must stay even for that). A genuine
  shared prefix cache is still caught on every pair.
- **A memorized single-token subject was attested ERASED.** The A3 subject-erasure
  model probe splits a fingerprint in half and prompts with the leading part, but it
  split on whitespace and gave up below two tokens. A subject fingerprint is often
  one token — an email address, an account number, a national id — which is exactly
  what an erasure request turns on. The whole-phrase detector never matches on a real
  autoregressive model (it continues rather than echoes, as the code already
  documented), so both detectors were inert and the model surface reported no
  residual for a subject the model still regurgitates on demand: a false erasure
  claim in the GDPR wedge. A single-token fingerprint is now cut mid-token —
  prompting `alice.brown@exa` and seeing `mple.com` completed is the same extraction
  signal, and the standard probe for a memorized secret.

- **A one-digit config typo could silently switch the semantic detector off.**
  `detection.semantic_threshold` accepted any float — `1.5`, `99`, `-5`, and even
  `nan`/`inf`. A cosine similarity lives in `[0, 1]`, so anything above `1.0` is
  unsatisfiable: every candidate was skipped *before* the judge, a paraphrased
  cross-tenant leak was not recorded even as an unverified candidate, and the run
  still signed a pack asserting isolation. `nan` was worse than unsatisfiable — every
  `<` against it is False, so the gate inverted and admitted everything. The field is
  now bounded to `[0.0, 1.0]` and out-of-range values are rejected at config load.
  `0.0` stays legal (it admits every candidate to the judge, erring toward
  surfacing), as does `auto`. Related to the fix in #270, which made a *verbatim*
  canary bypass this gate entirely — that mitigation does not cover the semantic
  path, which is precisely what the gate governs.

- **A hostile evidence bundle crashed `verify` instead of being refused.** Every
  field of `bundle-manifest.json` is attacker-controlled JSON, but its *shape* was
  assumed rather than checked: a manifest that was a JSON array reached `.get`, a
  `"members": null` reached `sorted()`, and a list-valued `"evidence"` reached a
  dict lookup. Each raised an uncaught `AttributeError`/`TypeError` out of
  `verify_bundle`, so `sectum-ai verify` exited **1 on a traceback instead of 4
  (VERIFICATION FAILED)**. For a tamper-evidence tool that distinction is the
  contract: a CI gate or delivery pipeline keying on exit 4 reads a crash as the
  tool breaking, not as the bundle being bad — and any service verifying uploaded
  bundles had a one-line denial of service. The three shapes are now validated and
  refused with a typed `bundle-manifest` check, the same standard the in-toto
  sidecar already held (a malformed input raises a typed error, never an uncaught
  exception). Detection of altered, missing, unlisted, and duplicate members is
  unchanged.
- **The signed audit pack promised zero false positives.** Its scope/methodology
  narrative told the auditor that "confirmed findings carry no false positives" —
  a guarantee the pipeline cannot make. Marker-traceability bounds confirmations
  to the manifest's own markers; it does not prove each one correct. An exact
  canary match is decided by the observation itself, but a semantic confirmation
  also rests on the configured judge, so an absolute claim overstated the weaker
  of the two paths. The paragraph now states the basis — confirmation requires the
  observed content to trace back to a specific manifest marker, anything
  untraceable is recorded as unverified — and describes confirmed findings as
  manifest-grounded rather than error-free. Both PDF engines share this text, and
  a test now fails if the absolute claim returns. `docs/glossary.md` carried the
  same conflation, plus a second inaccuracy: it said unverified findings "come
  from the semantic or judge step", which stopped being true when a semantic match
  that traces to a marker began confirming. The distinction is traceability, not
  which step fired.
- **A modelled retrieval gradient printed as a measured leak rate.** The
  per-embedding-model sweep builds its *own* index and ranks by cosine over one
  index shared by every tenant — it never queries the configured vector store, so
  the store's real isolation (namespaces, filters, ACLs) is bypassed by
  construction. It nonetheless printed as an indented `retrieval-pivot rate
  [model]: 87%` directly under the genuinely measured `retrieval-pivot rate`,
  reading as that metric broken down by model. It now prints under its own
  heading naming the condition, and `RunMetrics.retrieval_pivot_rate_by_model` —
  which travels inside the signed pack and is diffed by the regression gate — is
  documented as modelled, the one metric there that carried no such caveat. The
  number is unchanged and still useful: it measures the embedding model, not the
  store.
- **A mixed embedding-model config silently dropped models from that gradient.**
  The two-model guard counted *configured* names, not comparable ones. `fake-*`
  names carry a modelled recall rather than real vectors, so they cannot share a
  sweep with a real provider — but they were excluded with nothing said, so an
  operator who configured three models saw a two-model gradient and no indication
  the third was missing. A config with exactly one real name among fakes was worse:
  it produced a single-entry "gradient" — one model compared against nothing,
  recorded into the run's metrics as though it were a sweep. Excluded names are now
  named, and a gradient needs two or more real models or it is not recorded at all.
  The resolver is also consulted once per name rather than twice, so an `st:` spec
  no longer constructs (and potentially downloads) its model twice.
- **A judge's "no" could veto a cross-tenant leak that was sitting in the text.**
  `_exact` applies the "the canary is literally present, so it leaked" standard to
  `HARD_CANARY` only; an `ENTITY_CANARY` went through the semantic path, where the
  LLM judge alone decided. A cautious, flaky, or hostile judge answering "no" over an
  observation that verbatim contained another tenant's entity silently downgraded a
  real leak to an unverified candidate, and a mis-calibrated `semantic_threshold`
  could skip it before the judge was ever consulted. A foreign entity whose plaintext
  is present is now confirmed on observation — ahead of the threshold gate and
  independent of the verdict — reported at confidence `1.0`, exactly as `_exact`
  reports a hard canary. The zero-FP rule is unchanged: near-misses and paraphrases
  still require the judge.
- **A hallucinated quotation could reach the signed audit pack.** `_span_traceable`
  confirms either when the judge's cited span is traceable *or* when the marker
  itself is present in the observation, so for a verbatim leak it returned `True`
  whatever the judge quoted — and that unchecked span was then written to
  `evidence_span` and rendered into the audit-pack PDF. The judge's span is now
  quoted only when the span itself is traceable in the observation; otherwise the
  marker plaintext is. Confirmation is unaffected — only what gets quoted.
- **Datadog attested a still-retained subject as ERASED.** The spans-search client
  hardcoded a 15-minute window (`"from": "now-15m"`), so any span older than that
  read back absent — and `fetch_trace` returning `None` is exactly how the A3
  erasure check concludes a trace is gone. Datadog erasure is retention-driven
  (`delete` raises `ErasureUnsupported`), so the real horizon is days: a 15-minute
  bound made the false ERASED the normal case, not an edge case. The window is now
  configurable (`search_window` in `sectum-ai.yaml`) and defaults to `now-15d`, matching
  Datadog's default span retention; accounts retaining longer must widen it, since
  absence outside the window is not evidence of erasure.

- **The regression gate read "not measured" as "improved".** A narrowed `--suite`
  (or a probe skipped for a missing adapter) dropped every metric that probe fed to
  zero, so `baseline --compare` / `diff` printed `[ok]
  per_probe_findings[rag-poisoning]: 24 -> 0`, `no regression against the baseline`,
  and exited 0 — positively asserting leaks were *fixed* for a run that simply
  stopped testing Class 3 and Class 10. A probe the baseline exercised and the later
  run did not is now reported `[COVERAGE LOST]`, its metrics read `[not measured]`
  rather than `[ok]`, and the gate fails (exit 2). Coverage is compared by probe id,
  never by `per_probe_findings` — that counts findings, so a probe that ran clean is
  absent from it and every clean run would have read as a coverage loss.
- **`verify` false-accused a genuine erasure attestation of tampering.** `report` and
  `erasure` each write their own PDF and sidecars, and one workdir routinely holds
  both; siblings were resolved by scanning a global preference order, so verifying
  `erasure-evidence.json` re-hashed the *probe* pack's `audit-pack.pdf` and
  `attestation.intoto.json` and reported `altered or replaced after signing`
  (exit 4) on evidence written seconds earlier — the worst possible false alarm for a
  tamper-evidence product. Siblings now resolve from the pack they belong to.
  Tamper detection is unchanged: a forged erasure PDF or a re-pointed sidecar still
  fails.


- **The OSCAL export and the audit PDF asserted framework controls the run never
  earned.** Control state was derived from "did this run confirm a leak" alone,
  never from which probes ran, so a run of a single probe emitted the same
  fully-satisfied 22-control, 9-framework assessment as a full suite — including
  GDPR Article 17 and CCPA §1798.105 *deletion*, which the isolation probes
  structurally cannot test (erasure is the separate `sectum-ai erasure` workflow).
  Each mapping now declares the evidence it requires and `control_mappings(run)`
  filters by what the run actually produced: a probe run asserts 20 isolation
  controls and no deletion control, an erasure run asserts both. `score` already
  reported coverage honestly on the same record; the compliance outputs now agree
  with it.
- **The in-toto / DSSE attestation predicate was never verified.** Verification
  checked the statement type and the subject digest only, so a sidecar that kept a
  truthful subject while rewriting its predicate — `finding_count` to 0, every
  metric to 0, `anchors` to timestamped-and-logged, a fabricated control assertion —
  was reported as binding the pack. The predicate *is* the verification result a
  downstream policy engine reads, and every field is recomputable from the pack, so
  it is now compared against a freshly built one. `verify_dsse_envelope` delegates
  here, so both sidecars are covered.
- **A bundled `run.json` was not bound to the signed pack.** `verify_bundle` proved
  each member matched `bundle-manifest.json` — which a forger rebuilds along with
  it — so a run pack whose findings were deleted verified clean, printing an
  affirmative `[ok] digest matches` for the very file the auditor reads. The pack
  already carries the same record, so the binding was free.

## [0.7.1] - 2026-07-25

### Changed

- **Class 7 findings from the tool-description-injection sub-probe now carry
  `AML.T0051.001`** (LLM Prompt Injection: *Indirect*). That sub-probe delivers its
  coordinate through tool metadata the agent ingests rather than through the call, which
  is exactly what the technique describes; the id was verified against the MISP galaxy
  mirror in the 2026-07-18 ADR-0009 sweep. The mapping is scoped **per sub-probe**: the
  three `lookup` sub-probes reach the resource by naming it — a plugin-scope failure
  (`AML.T0053`), not an injection — so their findings are unchanged. `atlas` is a signed
  evidence field, so a finding is stamped with what its own sub-probe demonstrates rather
  than the probe's whole footprint. `agent-framework-hijack` is unchanged (it has no
  injection sub-probe). Auditors re-verifying a pre-0.7.1 pack will see the older, narrower
  Class 7 stamps; nothing about the leaks those packs record has changed.
### Fixed

- **`gdpr-subject-erasure-verification`'s manifest declared two of its three surfaces.**
  `probe.yaml` is the declarative catalog external tooling consumes, and this one had lost
  `tracing` — so a consumer under-reported which surfaces the subject-erasure probe actually
  scans. The manifest is regenerated, and the parity test that should have caught it is
  fixed: it guarded surface and adapter comparison behind `if hasattr(cls, "surfaces")`,
  which skipped exactly the workflow probes whose manifest values come from the generator's
  fallback table rather than a class attribute — a guard that silently passed the only
  probes it needed to check. Those are now asserted against the canonical sets the probe
  scans (`ERASURE_SURFACES` / `SUBJECT_VERIFIABLE_SURFACES`), and the same skip shape in the
  `example` check is pinned too.

## [0.7.0] - 2026-07-18

### Added

- **`sectum-ai score` — the isolation scorecard.** Grades a run's multi-tenant isolation
  posture into one letter (A–F) plus a per-class breakdown, so the catalog's depth is
  legible to an auditor rather than a wall of findings. The grade is **derived, not
  asserted**: every input is the signed `RunResult` (`probe_versions`, `findings`,
  `metrics`), so a third party recomputes the letter from the evidence with the published
  methodology (`docs/scorecard.md`, stamped as `methodology_version` on every scorecard)
  rather than trusting it. Four honesty rules hold the letter down: (1) a class whose
  probe did not run can only ever be `NOT_COVERED` — never `PASS`, so a grade never
  implies a check the stack was never asked to perform; (2) untested classes lower
  *confidence*, never the grade — coverage is reported beside the letter, so a run over
  three classes and one over eleven can both grade `A` and the confidence is what tells
  them apart; (3) the worst failing class's weight *band* caps the letter (the band of the
  class, never the severity of an individual finding), so a critical cross-tenant leak can
  never be averaged away; (4) every confirmed finding lands in a class or the run is not
  graded — a confirmed finding is itself proof its probe ran, and one the catalog cannot
  attribute refuses rather than being silently dropped. A run that exercised no catalog
  class is likewise refused (exit 3) rather than graded. New additive `IsolationScore` / `ClassScore` models
  + `Grade` / `ClassVerdict` / `Confidence` enums (no `SCHEMA_VERSION` change). Class 11
  (erasure) stays out of scope — it is a control check with its own attestation.
  The scorecard carries the graded record's `run_digest` (the SHA-256 the in-toto
  attestation and the audit PDF already bind): `run_id` comes from the scenario, so every
  run against one substrate repeats it and two records can grade `F` and `A` under an
  identical `run_id` — the digest is what ties a letter to one exact record, and a third
  party recomputes it from the record they hold.
- **Class 13 — Multi-modal RAG entity-bleed.** The Class 2 Retrieval Pivot generalised to
  images: multi-modal RAG embeds images (and text) into one vector space, so a benign
  image query for a shared *visual* entity (a chart, a logo, a product photo) surfaces
  another tenant's image, with the canary marker in its caption. New `multimodal-rag-bleed`
  probe (registered in the attack catalog, OWASP LLM08:2025 / ATLAS AML.T0024+T0057), a
  deterministic synthetic-image marker substrate (Pillow, the `[multimodal]` extra), two
  image embedders — `imagehash-<dim>` (a deterministic offline *proxy* for CI/demos, the
  image analogue of the text `hash-<dim>`; not a semantic model, so its per-dim curve is a
  substrate artifact, not a strength measurement) and `clip:<model>` (real CLIP via
  sentence-transformers, the `[clip]` extra, BYOC-safe — sweeping two or more CLIP models
  measures the genuine "stronger embedders leak more" gradient) — and
  `multimodal_provider_sweep`, which reports the per-model **image Retrieval-Pivot Rate**,
  with `multimodal_pivot_counts` reporting the binomial counts (`k` of `n`) a Wilson
  interval can be formed from. Unlike Class 2's rate, these are **not** carried in the
  evidence pack: `RunMetrics` has no multi-modal field and the probe is in no named suite,
  so the counts come from the sweep API rather than a signed record until the CLI wiring
  lands. Runnable, self-asserting example at
  `examples/multimodal-rag-bleed/` (a fixed demo ladder `imagehash-16` ~46% →
  `imagehash-256` 100% offline). The image-RPR is measured by its per-model sweep, as
  Class 2's embedding-strength gradient is; live multi-modal vector-store adapters and
  generic-suite / CLI wiring are a follow-on.

### Changed

- **The `owasp-llm08` suite claim is narrowed to what it runs.** It described itself as
  the full adversarial catalog; Class 13 carries `owasp_llm: LLM08:2025` but runs in
  neither the default CLI suite nor this one, so shipping Class 13 *reduced* the SKU's
  relative LLM08 coverage rather than adding to it. The suite description, `docs/skus.md`
  and `docs/coverage.md` now say "every adversarial probe in the default CLI suite" and
  name Class 13's sweep as the separate path. Nothing about the probes it runs changed —
  only the claim, which had stopped being true.

### Fixed

- **A run that crosses no isolation boundary is refused instead of graded `A`.** Isolation
  is a claim about a boundary *between* principals, so where nothing is foreign to anybody
  no probe can surface a leak however broken the stack is. Nothing enforced that: the same
  maximally-leaking demo stack that grades `F` on four tenants graded **`A`** on one — the
  letter describing the substrate while reading as a verdict on the stack. The record was
  genuine, so there was no tampering to catch: it passed `verify`, in-toto and DSSE, and an
  auditor holding only the pack reproduced the `A`. `probe` now refuses (exit `3`) a
  substrate in which no marker is foreign to any principal, at the source, so the tool
  cannot produce such a record. It refuses on the substrate alone, before building a
  single adapter — a refused run does not seed your vector store, prime your cache or
  train your model. The check asks that question directly rather than counting
  principals, because the count is only a proxy: a tenant with one user has *two* principals
  and no boundary (a tenant owns its users' data), and any number of principals verifies
  nothing if no marker was planted — the latter being the more dangerous shape, since the
  probes do run and Class 2 reports a well-powered `0.0% RPR (95% CI 0.0%-13.8%, n=24)` on
  a question that could never have had an answer. Class 5's probe is likewise recorded on
  what it *measured* rather than on having been asked to run. This refusal is a *global*
  check — some marker is foreign to somebody — so it cannot by itself stop a class that was
  starved of anything to find from grading `PASS`; that is the per-class job of the
  step-based `probe_versions` rule, below.
- **A probe that asked the stack nothing is no longer recorded as having run.**
  `probe_versions` was built from *suite membership*, while `score` reads it as "what
  actually ran" — so a probe whose plan came back empty was recorded, found nothing, and
  graded its class **PASS**: a check the stack was never asked to perform, which is
  exactly what the scorecard's rule 1 exists to forbid. A substrate with one principal
  leaves every cross-principal probe no step to take, so on a maximally-leaking stack
  Classes 1 / 6 / 7 printed `PASS` at `confidence: high`, and the run was then signed into
  an evidence pack that verifies — the tool attesting its own over-claim. `probe_versions`
  now records only probes that took at least one step; those classes read `NOT_COVERED`
  and the loss lands on *confidence*, where rule 2 puts it. A confirmed finding still
  stands on its own (rule 4: the finding is proof its probe ran).
- **A record can no longer forge the output that reports on it — across every command.**
  Sectum reports on records it does not trust, so every string a record carries is hostile
  input the moment it reaches our output. Raw interpolation let a newline forge whole lines
  of Sectum's own reporting and an ANSI escape (`ESC[2J`) wipe the real result off an
  auditor's terminal and reprint a passing one. Every affected surface is now escaped —
  not stripped, so tampering stays visible — via the new `sectum_ai.spec.untrusted`:
    - **`verify`** — the worst of them, and the command that *is* the trust anchor. The
      pack supplies `schema_version`; the compatibility gate reads only its major and
      minor and the attested digest never binds it, so text smuggled after the patch digit
      passed the gate, rendered raw, and printed `[ok]` lines asserting the RFC 3161 and
      Rekor anchoring `verify` exists to establish — on an unanchored pack.
    - **`diff` / `baseline --compare`** — probe ids, finding ids and metric-delta names
      forged a `RESULT: no regression` line inside a run that regressed.
    - **`pack`** — `run_id` in the run pack's `README.md`.
    - **`score`** — `run_id` in the scorecard, and record-supplied probe ids inside the
      rule-4 refusal message (both before release).
  No hand-editing is needed — `run_id` reaches a pack via `scenario_id` — and a validly
  signed pack carries the payload, because the vendor is the signer.

## [0.6.0] - 2026-07-15

### Added

- **GCS backup adapter (`kind: gcs`, the `[gcs]` extra) — the erasure backup surface on
  Google Cloud.** The Google-cloud parallel of the S3 backup: each tenant's snapshots
  live under the object-name prefix `{prefix}/{tenant.hex}/` in one bucket, with the same
  search / per-tenant purge / `no_erasure` (bucket-lock → *attestable-with-caveat*) /
  `soft_delete` (residue) contract Class 11 verifies. Auth falls back to Application
  Default Credentials; `STORAGE_EMULATOR_HOST` targets a local fake-gcs-server. The
  add/search/delete logic is covered offline against an in-memory client, and an opt-in
  live test runs it against fake-gcs-server (skips in CI, like the S3/MinIO test). This
  makes the backup erasure surface attestable on GCP, not just AWS.
- **Cohere-on-Bedrock embedding family for the Class 2 RPR sweep.** `bedrock:<model>`
  now dispatches on the model id: `cohere.embed-*` ids route to Amazon Bedrock's
  Cohere Embed models (batch of up to 96 texts per `invoke_model`, request body
  `{"texts": [...], "input_type": "search_document"}`, vectors under `embeddings`),
  while `amazon.titan-embed-*` keeps the existing one-input-per-call Titan path. Both
  share one `[bedrock]` extra and the boto3 credential chain; the per-family response
  parse is isolated into unit-tested helpers, so no AWS account is needed to exercise
  the dispatch, the ≤96 batching, and the vector coercion.
- **`examples/embedding-rpr-sweep/` walkthrough.** A runnable, deterministic example
  reproducing the flagship Class 2 finding *stronger embeddings leak more* as a
  per-model Retrieval-Pivot Rate sweep: at increasing hashing-embedder dimensions it
  prints the RPR gradient (e.g. `hash-16` 58% → `hash-256` 83%) with no model download
  or API key, and documents swapping in the five real providers
  (`st:`/`openai:`/`cohere:`/`voyage:`/`bedrock:`) or driving it from `sectum-ai probe`
  via `scenario.embedding_models`. `run.py` exits non-zero if the gradient is not
  monotone, so it doubles as a smoke test.

## [0.5.1] - 2026-07-13

### Added

- **Amazon Bedrock (Titan) embedding provider for the Class 2 RPR sweep.** `bedrock:<model>`
  (e.g. `bedrock:amazon.titan-embed-text-v2:0`, the `[bedrock]` extra) resolves to the
  Amazon Bedrock Titan text-embeddings family via boto3's `bedrock-runtime` client;
  credentials and region come from boto3's standard chain (`AWS_REGION` / profile /
  instance role). Titan embeds one input per `invoke_model` call (no batch API), so the
  sweep embeds the corpus one text at a time; the streaming-body JSON parse is isolated
  into a unit-tested `_vector` helper. Cohere-on-Bedrock (a different invoke-body shape)
  is not wired — this is the single-family Titan adapter. Hosted (not BYOC-safe), opt-in
  live like the other hosted embedders. This closes the last named embedding-provider
  gap (`sentence-transformers` / `openai` / `cohere` / `voyage` / `bedrock`).

## [0.5.0] - 2026-07-13

### Added

- **Cohere and Voyage hosted embedding providers for the Class 2 RPR sweep.** The
  per-model Retrieval-Pivot Rate sweep ("stronger embeddings leak more") now accepts
  `cohere:<model>` (e.g. `cohere:embed-english-v3.0`, the `[cohere]` extra,
  `COHERE_API_KEY`) and `voyage:<model>` (e.g. `voyage:voyage-3`, the `[voyage]` extra,
  `VOYAGE_API_KEY`) alongside the existing `st:` / `openai:` / `hash-` specs, so the
  sweep can compare more real embedding models. Both are hosted (they send the
  synthetic corpus to their API — not BYOC-safe, unlike `st:`), so like `openai:` they
  are opt-in live and key-gated. The SDK response-vector extraction is isolated into a
  unit-tested `_vectors` helper (tolerant of Cohere's v1-list vs v5 by-type shapes);
  Voyage requests are chunked to stay under its per-request cap (Cohere's client batches
  internally), and both SDK pins are capped below their next major to avoid a silent
  response-shape break. Amazon Bedrock remains unwired (its per-model-family invoke
  bodies need a dispatch the single-endpoint providers don't).

### Fixed

- **mem0 memory adapter no longer wipes every tenant on a shared-memory erasure.** In
  `shared_memory` mode every tenant maps to a single mem0 `user_id`, so a Class 11
  `delete` (during `sectum-ai erasure`) ran `delete_all` on that shared scope and
  removed *every* tenant's memory, not the target's — while the surface reported
  `NOT_COVERED` (no per-tenant baseline). The adapter now raises `ErasureUnsupported` in
  shared mode (recorded *attestable-with-caveat*, the same honesty that rejects
  `user_scoped`), checked before `soft_delete`. Affects only `kind: memory → mem0` with
  `shared_memory: true` (added in 0.4.0). Surfaced by a code+docs review loop, which
  also corrected a docs over-claim ("all ten erasure hiding places have a live backend"
  → eight are wired) and hardened the hosted-provider live tests to skip, not fail, when
  an API key is set without its SDK extra installed.

## [0.4.0] - 2026-07-11

### Added

- **Live mem0 memory adapter (`kind: memory → mem0`).** A second live backend for the
  Class 8 agent-memory surface beside Redis: a product that keeps per-user long-term
  memory in [mem0](https://github.com/mem0ai/mem0) can now be probed for cross-tenant
  memory contamination. Each tenant maps to a mem0 `user_id`; entries are stored
  verbatim (`infer=False`), so the adapter is a faithful scoped store independent of
  mem0's LLM fact-extraction, and a planted marker is found by its own text.
  `shared_memory=true` collapses every tenant to one shared `user_id` — the Class 8
  leak. It does **not** model `user_scoped` (mem0's flat `user_id` space has no per-user
  erasure boundary; the resolver rejects `user_scoped: true` for `kind: mem0` rather than
  silently ignoring it — use `kind: redis` for that). Opt-in live (mem0 needs an
  embedder; its default is OpenAI), verified offline against a mock. Requires the `mem0`
  extra.
- **Live eval-set (LangSmith Datasets) and backup (S3) adapters — the last two
  fake-only erasure surfaces are closed.** The Class 11 erasure scan's fourth and
  seventh "hiding places" now have live backends, so every one of the erasure scan's
  **eight wired surfaces** can be verified against a real store, not the synthetic
  substrate (the remaining hiding place — subprocessor residue — has no scanning
  adapter yet):
  - **Eval set → LangSmith Datasets** (`kind: eval_set → langsmith`, the `[langsmith]`
    extra): each tenant maps to its own LangSmith Dataset (`{prefix}-{tenant}`); a
    fixture is a dataset example, and `delete` removes the dataset.
  - **Backup → S3** (`kind: backup → s3`, the `[boto3]` extra): each tenant's snapshots
    live under `{prefix}/{tenant}/` in one bucket (AWS S3 or any S3-compatible store via
    `endpoint_url`); `no_erasure=true` models an immutable / object-lock (WORM) bucket
    with no per-tenant purge, so Class 11 records it as *attestable-with-caveat*.
  `eval_set` and `backup` now resolve from `adapters.eval_set` / `adapters.backup` like
  the other surfaces (falling back to the fake), and the `add` seed primitive is promoted
  to both interfaces. Both are opt-in live (credential- / endpoint-gated) like the hosted
  vector stores; verified offline against a mock and live against a backend on demand (the
  S3 adapter end-to-end against a local MinIO, through the full `sectum-ai erasure` flow).

## [0.3.0] - 2026-07-10

### Added

- **A3 subject-erasure fingerprinting reaches the agent-memory and search-index
  surfaces.** `sectum-ai erasure --subject` already fingerprints the vector store and
  the model for a real subject's residual content; it now also probes the agent-memory
  store (a keyword `recall`) and the derived full-text search index (a `search`),
  catching a lingering memory entry or an un-purged index document a by-id check would
  miss. Both are fingerprint-only (no stable by-id primitive), residual when the
  recalled/returned entry still carries the phrase, and — like every fingerprint
  surface — data-minimized: the finding stores only a hash of the probed phrase, so the
  attestation holds no PII. Configure `adapters.memory` / `adapters.search_index` with a
  live backend (Redis / OpenSearch) for a production DSR attestation; the built-in fake
  triggers the synthetic-substrate warning. New `agent_memory` / `search_index` keys are
  accepted in a subject manifest's `fingerprints`.
- **Live OpenSearch search-index adapter (`kind: search_index → opensearch`).** The
  derived full-text search index — the tenth "hiding place", previously fake-only —
  now has a live backend, so the Class 11 erasure scan of the search-index surface
  runs against a real OpenSearch index instead of the synthetic substrate: each
  tenant's documents live in their own index (`{prefix}-{tenant}`), and `delete`
  purges it (`soft_delete=True` leaves the residue). `search_index` is now configured
  via `adapters.search_index` like the other surfaces (falling back to the fake), and
  the `SearchIndexAdapter.index` seed primitive is promoted to the interface. Verified
  end-to-end — adapter and the full `sectum-ai erasure` flow — against a real
  OpenSearch in the docker-compose integration suite.

## [0.2.2] - 2026-07-10

### Added

- **By-id `fetch_trace` for four more observability adapters (A3 tracing).** The A3
  data-subject erasure check verifies a subject's traces are gone by id; previously
  only the Langfuse adapter exposed the `fetch_trace` primitive (every other backend
  read `NOT_COVERED`). LangSmith, Phoenix, Helicone, and Datadog now each look a
  trace up by id within the tenant's own scope, so `erasure --subject` can attest the
  tracing surface for those backends too. The generic OpenTelemetry reader queries by
  content, not id, so it has no by-id lookup and stays `NOT_COVERED` (honest, not a
  false `ERASED`). Verified end-to-end against a real Phoenix in the docker-compose
  integration suite; the rest are covered by mock-backed unit tests.

## [0.2.1] - 2026-07-09

### Added

- **Live Redis memory adapter (`kind: redis` for the memory surface).** The
  long-term / agent-memory surface — previously fake-only — now has a live backend,
  so Class 8 (persistent memory contamination) and the memory erasure surface run
  against a real Redis store, not just the synthetic substrate. Each tenant's entries
  live in a prefixed per-tenant list; `shared_memory=True` models the shared memory
  space Class 8 catches, `user_scoped=True` isolates users within a tenant (ADR-0006),
  and `soft_delete=True` leaves the Class 11 erasure residue. Verified end-to-end
  against a real Redis in the docker-compose integration suite.

## [0.2.0] - 2026-07-07

### Added

- **Prefix-continuation extraction for the A3 model-surface fingerprint.** The
  model-surface residual check now also detects memorization the way a real
  autoregressive model surfaces it: because such a model *continues* a prompt rather
  than echoing it, the probe prompts with the leading half of the subject's content
  and flags residual when the sensitive trailing half is regurgitated — not only the
  whole-phrase recall the in-memory fake exhibits. Backward-compatible (it strictly
  catches more residual) and PII-safe (findings still store only a hash).
- **Live model-surface erasure integration test** (`tests/integration/
  test_subject_erasure_hf_lora.py`) against a real HuggingFace + PEFT LoRA backend:
  a per-tenant LoRA fine-tuned on the subject's content is caught as `RESIDUAL`, and
  after the adapter is deleted the surface reads `ERASED`. Opt-in (needs the
  `huggingface` extras and `SECTUM_RUN_HF_LORA=1`), like the vLLM/TGI live tests.

### Fixed

- **HuggingFace LoRA adapter: transformers 5.x compatibility.** `Trainer`'s
  `tokenizer=` argument was removed in transformers 5.x (the `huggingface` extra
  pins `transformers>=5.13`); the live adapter now passes the tokenizer as
  `processing_class=`, so `train_adapter` works again instead of raising `TypeError`.
- **HuggingFace LoRA adapter: per-tenant base-model isolation.** PEFT injects LoRA
  modules into the model *in place*, so training or scoped inference on the shared
  base model permanently contaminated it — one tenant's fine-tune bled into every
  later base and other-tenant inference and even survived a per-tenant delete. The
  adapter now trains and runs scoped inference on fresh base copies, keeping the
  shared base pristine for base-model inference.

## [0.1.8] - 2026-07-06

### Added

- **Model-surface content-fingerprint verification for `sectum-ai erasure
  --subject` (A3 Phase 2).** The subject manifest's `fingerprints` may now include
  `model_adapter` — the subject's known content — and the run probes the model with
  an inference call to catch residual *memorization* in a per-tenant fine-tune or
  adapter that neither a by-id check nor the vector fingerprint can see. The model
  surface is checked only when the model is trainable (reports `per_tenant_adapter`
  or `shared_weights`); a serving-only endpoint memorized nothing and reads
  `NOT_COVERED`, never a false `ERASED`. As with the vector fingerprint, the content
  is used only to query and is never persisted — the finding records a hash of the
  phrase — and a clean result is best-effort evidence, not proof of absence.

## [0.1.7] - 2026-07-03

### Added

- **By-id tracing verification for `sectum-ai erasure --subject`.** The subject
  manifest's `records` may now include `tracing` trace ids, verified by id against
  the observability backend via a new optional `ObservabilityAdapter.fetch_trace`
  (implemented for the fake and the Langfuse adapter). An adapter without a by-id
  trace fetch leaves the tracing surface `NOT_COVERED`, never a false `ERASED`.
- **Content-fingerprint residual verification for `sectum-ai erasure --subject`
  (A3 Phase 2).** Beyond the by-id check, the subject manifest may now carry
  `fingerprints` — the subject's known content per surface — and the run probes the
  vector store with a semantic query to catch *derived* residual (an embedding copy)
  that by-id enumeration would miss. A vector surface is `ERASED` only when every
  supplied id is gone **and** no supplied content still surfaces. The content is
  used only to query and is never persisted: a fingerprint finding records a hash of
  the phrase, so the attestation holds no PII. Fingerprint probing is best-effort —
  a clean result is evidence the content no longer surfaces, not proof of absence.

## [0.1.6] - 2026-07-03

### Added

- **Data-subject erasure verification by record id (`sectum-ai erasure --subject`).**
  Verifies a *real* data subject's GDPR Article 17 / CCPA §1798.105 erasure by
  record id — after your own deletion has run — rather than scanning the synthetic
  canaries. Reads a YAML manifest (an opaque `subject_ref` plus the subject's
  record ids per surface; ids only, no subject content) and confirms each id is
  gone by id, emitting a per-subject signed attestation that reuses the same
  evidence pack and exit codes as the canary flow. Surfaces with a by-id existence
  check (the vector store and the semantic cache) are verified; every other surface
  reads `NOT_COVERED`, so the attestation never implies coverage it did not verify.
  When a verifiable surface would be checked against the built-in synthetic store
  (no live adapter configured), it warns loudly, so a green verdict is never
  mistaken for a real verification. (The structural-verification phase of the
  planned DSR connector.)

## [0.1.5] - 2026-06-27

### Added

- **TGI model adapter (`kind: tgi`).** A serving-only HuggingFace Text Generation
  Inference adapter, reached over TGI's native text-generation API via the
  `huggingface_hub` client. Like the vLLM adapter it runs inference and measures
  time-to-first-token (Class 5 KV-cache timing) but trains no per-tenant adapter,
  so it declares `shared_prefix_cache` and not `per_tenant_adapter` — `sectum-ai
  probe` skips Class 9 for it and a Class 11 erasure leaves the model surface
  `NOT_COVERED`. The shared serving-only behavior now lives in a `_ServingModel`
  base that vLLM and TGI both build on. Install with
  `pip install sectum-ai-adapters[tgi]`.

### Fixed

- **Class 11 erasure skips model inference for serving-only models.** An `erasure`
  run configured with a serving-only model (`kind: vllm`/`tgi`) issued a live
  completion per canary on the model surface, even though such a model trains no
  per-tenant adapter and can never reproduce one — wasted I/O whose only outcome was
  the correct `NOT_COVERED`, and a transient backend error there aborted the whole
  run. The scan now short-circuits for a model that supports neither
  `per_tenant_adapter` nor `shared_weights`, reading `NOT_COVERED` without a network
  call.

## [0.1.4] - 2026-06-21

### Fixed

- **`sectum-ai pack` no longer over-redacts a config's `max_tokens`.** The redacted
  config carried in a run pack matched secret key names by bare substring, so the
  vLLM adapter's benign `max_tokens` field was written as `<redacted>` and the
  redacted config no longer round-tripped. Secret keys are now matched on a word
  boundary — `api_key`/`secret_key`/`token` still redact, while `max_tokens`,
  `tokenizer`, and `public_key` are kept. The value-shape scrub is also hardened:
  `bearer` is matched case-insensitively, URL userinfo with an embedded `@` is
  fully redacted, and a scalar-only config is scrubbed rather than echoed. No
  secret was ever exposed — this was over-redaction.

## [0.1.3] - 2026-06-21

### Added

- **vLLM model adapter (`kind: vllm`).** A serving-only model adapter that reaches
  a vLLM server over its OpenAI-compatible API to run inference and measure
  time-to-first-token — the Class 5 KV-prefix-cache timing channel. It trains no
  per-tenant adapter, so it reports the `shared_prefix_cache` capability and not
  `per_tenant_adapter`. Probes now declare `requires_any_capability`; `sectum-ai
  probe` skips a probe whose capability no configured adapter provides (so Class 9
  `lora-cross-tenant` is skipped for a serving-only model instead of erroring
  mid-run), and a Class 11 erasure leaves the model surface `NOT_COVERED`. Install
  with `pip install sectum-ai-adapters[vllm]`.

- **Run pack (`sectum-ai pack`).** Bundles a completed run into one self-verifying
  `run-pack.zip` — the signed evidence pack and its sidecars plus `run.json`, the
  config (inline secrets redacted - secret-named values, `headers` maps, embedded
  URL credentials, and credential-shaped strings; `*_env` references kept), and a
  `PACK-README.md`
  — so a recipient can both verify it (`sectum-ai verify run-pack.zip`) and see
  exactly what was tested. Unlike the redacted evidence pack, a run pack is
  **sensitive**: it carries `run.json` (evidence spans) and, with
  `--include-manifest`, the ground-truth marker manifest sealed AES-256-GCM under
  `security.manifest_key_env`. Reuses the content-agnostic bundle, so the existing
  member-digest + `verify_pack` checks cover it.

## [0.1.2] - 2026-06-20

### Added

- **GitHub Action (`action.yml`).** A composite action that installs `sectum-ai`
  from PyPI, seeds a marker substrate, probes your stack for cross-tenant leaks,
  and **fails the build on a confirmed leak** (probe exit 2, toggleable via
  `fail-on-leak`). Inputs cover `version`, `config`, `workdir`, `output`
  (text/json/sarif/oscal) + `output-file`, and `python-version`; outputs expose
  the exit code, report/run paths, confirmed-finding count, and Retrieval-Pivot
  Rate. `output: sarif` feeds the code-scanning Security tab. Usage:
  `uses: sectum-ai/sectum-ai@<ref>` — see [docs/github-action.md](docs/github-action.md).

### Changed

- **Install docs lead with PyPI.** Now that the packages are published, the
  README and `docs/quickstart.md` open with `pip install sectum-ai` (and the
  `uv pip`/`uv tool` equivalents) and use the installed `sectum-ai` command;
  the `git clone` flow is scoped to running the bundled `examples/` demo. ADR-0016
  drops a stale "v0.1.0 is not yet published" aside.

## [0.1.1] - 2026-06-19

### Added

- **The detection pipeline warns on an embedding-model mismatch.** At
  construction it compares the embedder's `model_id` against the model the
  manifest records in each entity marker's `embedding_ref` (the spec, section
  6.3) and logs `detect.embedding_ref.model_mismatch` when they differ - so a run
  whose detection embedder is not the model the manifest's semantic test
  condition assumes (a different embedding space, where a calibrated threshold may
  not apply) is flagged rather than silently trusted. Best-effort: silent unless
  the embedder names itself.
- **Qdrant vector adapter (`kind: qdrant`, `[qdrant]` extra).** A live
  `VectorStoreAdapter` backed by a Qdrant server, one collection per tenant
  (per-tenant isolation), with optional user-scoping via a payload filter +
  post-fetch check (ADR-0006). Deterministic point ids (UUIDv5 of the `doc_id`)
  make upserts idempotent. Ships a docker-compose service and a live integration
  test that skips when the client/server is absent (the repo's standard live-
  adapter pattern).
- **Milvus, OpenSearch, and Azure AI Search vector adapters.** Three more live
  `VectorStoreAdapter`s, each per-tenant isolated (one collection/index per
  tenant), with the same `fetch`-by-id primitive, deterministic UUIDv5 ids, and
  optional user-scoping (a filter on `query` + a post-fetch owner check, ADR-0006)
  as the Qdrant adapter. `kind: milvus` (`[milvus]` extra; strong consistency so a
  verification never reads stale), `kind: opensearch` (`[opensearch]` extra;
  `knn_vector` on the Lucene engine), `kind: azure-search` (`[azure-search]`
  extra; hosted HNSW). OpenSearch ships a docker-compose service and a CI live
  integration test; Milvus ships a `milvus`-profile compose service plus a live
  test run locally (it needs etcd + minio, so it is excluded from CI); Azure AI
  Search is hosted and verified by an opt-in live test (no local backend).
- **Deeper MCP coverage for Class 7 (`agent-tool-hijack`).** The MCP probe now
  runs four manifest-grounded sub-probes per foreign resource instead of two: the
  original confused-deputy and token-passthrough lookups, plus a **cross-server
  confused deputy** (a lookup routed `via` a second MCP server that holds the
  owner's authority — the Asana-class cross-server pattern) and a
  **tool-description injection** (a `search` whose attacker-authored tool
  description smuggles a foreign coordinate the call never named). A foreign
  canary in any tool result is a leak; the detection is unchanged and remains
  zero-FP. The tool-description-injection sub-probe models server-side scope
  enforcement under tool-metadata-supplied coordinates (a simplification of the
  LLM-agent-level description-poisoning attack), documented as such.
- **Offline / BYOC detection mode (`detection.mode: local`).** A "no data leaves
  the box" guarantee for the privacy-sensitive deployment: detection is the only
  stage that embeds or judges tenant content, so `local` mode makes the config
  **fail fast** if any embedder or judge would call a default hosted AI API
  (`openai`/`anthropic` without a `base_url`). Only the offline `fake` providers,
  or providers pointed at an operator-controlled local/in-VPC `base_url` (e.g.
  Ollama), are allowed — so Sectum itself makes no call to a third-party AI
  service. `hosted` (the default) is unchanged. Documented in the threat model;
  the `base_url` target is the operator's trust boundary, not Sectum's.
- **More compliance control mappings (ISO/IEC 42001:2023, CCPA/CPRA).** The
  control-mapped evidence now also speaks to ISO/IEC 42001:2023 (the AI
  management-system standard — Annex A data-governance and operational-monitoring
  controls `A.6.2.6`, `A.7.2`, `A.7.5`) and CCPA/CPRA (the `§1798.105` deletion
  right — the US parallel to the GDPR Art. 17 erasure wedge — plus `§1798.100`/
  `§1798.150` security duties). The new mappings flow through the audit-pack PDF,
  the OSCAL assessment-results export, and the JSON evidence automatically.
  Mappings remain assertions of test coverage, not legal certification.
- **Threshold calibration (`sectum-ai calibrate`) + per-embedding-model semantic
  thresholds.** The semantic-similarity gate was a single hand-picked float
  (0.62) that had to be retuned to ≈ 0.80 for `text-embedding-3-small` on a real
  run. `sectum-ai calibrate` now derives it principally: it builds a labeled set
  from a seeded substrate — positives are a foreign tenant's `ENTITY_CANARY`
  genuinely surfaced into another tenant's session, negatives are same-tenant and
  unrelated text that must not trip the gate — scores each with the configured
  embedder, and recommends the threshold that **maximises F1 subject to zero
  false positives** among the negatives (the zero-FP property is non-negotiable;
  a threshold that admits any negative is never recommended). It prints a
  precision/recall/F1 table and the value to paste; `--embedder <kind:model>`
  (default from config; `st:…`/`openai:…`/`hash-…`/`fake`), `--seed`, `--workdir`,
  `--config`, `--output {text,json}`, deterministic from the seed. Alongside it,
  `detection.semantic_threshold` now accepts the literal `auto`, which resolves to
  a shipped per-model preset (`st:all-MiniLM-L6-v2` 0.55, `st:all-mpnet-base-v2`
  0.60, `openai:text-embedding-3-small` 0.80, `openai:text-embedding-3-large`
  0.78), falling back to 0.62 with a logged warning for an unknown model. A
  numeric threshold is unchanged (back-compat).
- **SARIF output (`sectum-ai probe --output sarif`).** Emits a SARIF 2.1.0 log of
  the run's findings so GitHub code scanning (and other SAST dashboards) ingest
  them and surface cross-tenant findings in a repository's Security tab — one rule
  per probe, one result per finding. The signed `evidence.json` stays the
  canonical record; the SARIF is a derived, unsigned projection. An unverified
  candidate is capped at SARIF `note` **and** floored in `security-severity` to the
  informational bucket — GitHub badges a security alert by `security-severity`, not
  `level`, so capping only the level would still render an unverified candidate as a
  high-severity alert. A probe that produced only unverified candidates likewise
  advertises a `note`/low-severity rule, so the manifest-grounded,
  zero-false-positive headline is never overstated.
- **OSCAL assessment-results output (`sectum-ai probe --output oscal`).** Emits a
  NIST OSCAL 1.1.x `assessment-results` JSON document so GRC platforms and auditors
  can ingest a run as a machine-readable, control-mapped assessment. It carries one
  OSCAL *observation* per finding (the marker-grounded evidence, with the Sectum
  finding id/status/surface in `props` for traceability back to the signed record)
  and one OSCAL *finding* per mapped framework control from `control_mappings()`
  (SOC 2, ISO 27001, ISO/IEC 42001, GDPR, CCPA/CPRA, EU AI Act, HIPAA, NIST AI
  RMF, OWASP LLM Top 10), each
  linking to the observations via `related-observations`. Status is honest:
  `target.status.state` is `not-satisfied` only when a **confirmed**
  (manifest-grounded) cross-tenant leak exists; an UNVERIFIED candidate is recorded
  as evidence but never on its own presents as a control failure, and a run with
  zero confirmed leaks renders a valid "tested, no confirmed cross-tenant leakage"
  attestation rather than an empty document. The `COVERAGE_DISCLAIMER` (mappings are
  test-coverage assertions, not legal certification) is embedded in the metadata
  remarks. All UUIDs are derived deterministically (`uuid5`) from the run id and all
  timestamps come from the run, so the same run renders byte-identical OSCAL. The
  document is a derived, unsigned projection; the signed `evidence.json` stays the
  canonical record. `calibrate` and `diff` reject `--output oscal` (and `sarif`)
  with a clear error, mirroring the existing guard symmetry.
- **Erasure "snapshot" scope (`sectum-ai erasure --scope`).** An engagement can
  now verify a subset of erasure surfaces — for example `--scope vector_db` or
  `--scope vector_db,tracing` — backing a cheaper single-surface snapshot
  attestation. Omitting the flag verifies every configured surface (unchanged).
  An unknown surface name is a clear `ConfigError` (exit 3). Valid surfaces:
  `vector_db`, `tracing`, `agent_memory`, `semantic_cache`, `model_adapter`,
  `search_index`, `eval_set`, `backup` (the canonical
  `sectum_ai.probes.ERASURE_SURFACES`).
- **Honest, anti-over-claim per-surface erasure coverage.** Every erasure
  surface now carries an explicit verdict in the evidence pack
  (`RunMetrics.erasure_coverage`, surface → `CoverageVerdict`): `ERASED`,
  `RESIDUAL`, `ATTESTABLE_WITH_CAVEAT`, or `NOT_COVERED`. A surface that was out
  of scope, had no configured adapter, or showed no pre-erasure baseline is
  `NOT_COVERED` — it can **never** read as `ERASED`. This closes a real defect: a
  recent live run reported the stack "ERASED" overall even though some surfaces
  were never scanned; the pack must never imply more coverage than it verified.
  The audit-pack PDF (both engines) renders a **Coverage & caveats** matrix so a
  DPO/auditor can see, surface by surface, exactly what was and was not verified,
  and the `erasure` command prints the `NOT_COVERED` surfaces.
- **A confidence interval on the headline Retrieval-Pivot Rate.** The flagship
  Class 2 metric is a binomial proportion (`k` of `n` benign cross-tenant queries
  surfaced a foreign marker), so a bare point estimate over-claims precision when
  `n` is small. Every run now reports a **95% Wilson score interval** with the
  sample size next to the rate — `retrieval-pivot rate: 81.2% (95% CI
  68.1%-89.8%, n=48)` in `--output text`, the `retrieval_pivot_rate_ci` array plus
  the `retrieval_pivot_n`/`retrieval_pivot_k` counts in `--output json`, and a
  labelled row in the audit-pack PDF. The counts are recorded in `RunMetrics` and
  the signed evidence so the interval is reproducible by a third party, not just a
  rounded figure. The Wilson interval (chosen over the normal/Wald approximation)
  stays inside [0, 100%] and keeps near-nominal coverage at small `n` or an extreme
  rate. The math is a small, tested, pure-stdlib helper (`sectum_ai.spec.stats`,
  no SciPy/NumPy), mirroring the Class 5 timing channel's statistics; the
  point-estimate definition is unchanged.


- **The detection embedder + judge accept an OpenAI-compatible `base_url`, so the
  semantic pipeline can run against a local Ollama (or vLLM / LM Studio) with no
  OpenAI account.** `detection.embedder.base_url` / `detection.judge.base_url` point
  the `openai` kind at any OpenAI-compatible server — e.g. Ollama at
  `http://localhost:11434/v1` (`embedder.model: nomic-embed-text`,
  `judge.model: qwen2.5`). When `base_url` is set the API key is optional (local
  endpoints ignore it), so the Class 2 semantic ENTITY gradient and the LLM judge
  run fully offline / BYOC-safe. The real OpenAI path still requires its key.

- **`examples/open-webui-run/` — a push-button harness that runs Sectum AI against
  a self-hosted [Open WebUI](https://github.com/open-webui/open-webui).** It stands
  up Open WebUI + Ollama in Docker, provisions four synthetic tenants from Sectum's
  marker substrate, and drives the flagship **Class 2** organic entity-bleed Retrieval
  Pivot through Open WebUI's chat-with-knowledge API (plus **Class 1** cross-user file
  fetch), contrasting a `shared` public-KB config (RPR ≈ 100%) against an `isolated`
  per-tenant config (RPR ≈ 0%) and emitting a signed, `verify`-able evidence pack —
  the same demo as `retrieval-pivot`, here against a real product. Lawful-testing
  posture: our own deployment, synthetic corpora, manifest-grounded detection.

- **Class 1 now flags the "200-empty vs 403" deny ambiguity.** A direct
  cross-tenant fetch that comes back empty is not a proven deny — a backend can
  return `200` with an empty body without ever enforcing authorization. The
  tenant-boundary probe now emits an *unverified, informational* finding for each
  such cross-principal fetch (excluded from the confirmed-leak headline, carrying
  a remediation pointer to return an explicit `403`), so a silent empty response
  can no longer pass for enforced negative authorization. This consumes the
  Class 1 `access_outcome` signal the runner already recorded but nothing read.


- **The marker substrate is deepened to the full section-6.3 design: embedding
  references, multi-field planting, and a real secret-format detector (ADR-0022).**
  The ground-truth manifest now populates `Marker.embedding_ref` for every ENTITY
  canary — a model-scoped content address (`{model}/{sha256(plaintext)[:16]}`) the
  detection pipeline indexes its vectors by and reads back through, so the attested
  test condition (which model embedded the entity) is bound into the manifest hash.
  Each marker is planted in its pivot document's **body, title, and metadata**
  (all three recorded in `planted_locations`), and the in-memory vector store
  searches all three, so a leak is caught whichever field surfaces. `SECRET_CANARY`
  takes **realistic, non-issuable shapes** — an OpenAI-style `sk-` key, an AWS
  `AKIA` access-key id, and a `9xx` SSN the SSA never issues, rotated so the default
  scenario exercises all three — detected by a dedicated `_secret_format` pass
  (the spec's "exact + format detector", a path distinct from `HARD_CANARY`'s exact
  scan) that recovers a credential even when it is wrapped in surrounding bytes
  (e.g. a key inside a JSON blob). Secret plaintexts are generated at runtime from
  the seed and never committed — only the manifest *hash* is published. New
  invariants pin all of it, including a **zero-false-negative** test (every marker
  type, from every planted field, is detected when it surfaces cross-tenant) and a
  zero-false-positive test for a secret-shaped string absent from the manifest. The
  demo `corpus_size` default rises to ~500 documents/tenant (the spec, section 6.2);
  tests and the checked-in example samples pin a small corpus, and the committed
  sample packs and reproducibility golden hash were regenerated (no `sectum_ai.spec`
  model field changed, so the JSON Schemas and `SCHEMA_VERSION` are untouched).

- **The canonical-hash finite-float determinism contract is now pinned (ADR-0021).**
  The evidence chain's reproducibility rests on the canonical hash being stable for
  the float metrics it covers (RPR, effect sizes, confidences). A dedicated
  `tests/unit/test_hashing.py` pins that contract: a finite float reached by
  different arithmetic but equal in IEEE-754 hashes identically (CPython's
  shortest round-tripping `repr` is deterministic — no rounding needed), genuinely
  distinct floats stay distinct (so a real metric change is never masked by a
  rounded collision), and non-finite (NaN/±Inf) and non-JSON values are refused
  with typed errors. ADR-0021 records why finite floats are *not* rounded — the
  rounding alternative was considered and rejected as lossy for a verification
  tool, and `canonical_hash`/`SCHEMA_VERSION` are deliberately left unchanged (no
  artifact churn). Refines, not supersedes, ADR-0007.
- **DSSE in-toto envelope for the evidence pack (the spec §8/§13).** The in-toto
  Statement can now be wrapped in a DSSE (Dead Simple Signing Envelope) — the
  standard signable carrier and the body of a Sigstore Rekor `dsse` log entry.
  `evidence/dsse.py` builds the envelope (base64 payload + the spec's PAE
  encoding), decodes it, and verifies it still binds the pack's run digest. `sectum
  report` now writes `evidence.dsse.json` beside the pack (and into `--bundle`), and
  `sectum-ai verify` re-checks that sidecar — a swapped envelope fails. Standard-library
  only and fully offline-verifiable. *Sigstore keyless (Fulcio/OIDC) signing of this
  envelope is the opt-in layer on top: its OIDC identity flow is not exercisable in
  offline CI, so — to avoid shipping unverifiable signing internals — it is deferred
  rather than stubbed; the DSSE envelope produced here is exactly what that signature
  and a Rekor `dsse` entry attach to.*
- **`sectum-ai verify` gates the pack's `schema_version`.** The attested digest is
  recomputed under a canonical-serialization scheme tied to the schema version, so
  a pack from an incompatible `major.minor` could hash under different rules or
  carry different fields. `verify_pack` now refuses such a pack up front with a
  `schema-version` check (exit `4`) instead of silently mis-verifying it; a
  patch-level difference stays compatible. Every committed in-toto sidecar (incl.
  the retrieval-pivot one, whose large `evidence.json` is not committed and so
  previously went untested) is now pinned as a structurally valid in-toto
  Statement by an invariant test, so no shipped attestation is silently orphaned.
- **Single-archive evidence bundle (`sectum-ai report --bundle`, the spec §8.2).**
  Section 8.2 step 5 calls for bundling a run's attested artifacts into one pack;
  until now `report` wrote three loose sidecars a verifier had to keep together by
  convention. `evidence/bundle.py` builds a deterministic ZIP carrying a
  `bundle-manifest.json` of each member's SHA-256, and `verify_bundle` recomputes
  every digest **and** re-runs `verify_pack` on the contained evidence — so editing
  any member, or the pack itself, fails. `sectum-ai report --bundle` writes
  `evidence-bundle.zip` (with `--include-manifest` sealing the ground-truth manifest
  AES-256-GCM, off by default); `sectum-ai verify <bundle.zip>` verifies the archive
  end to end (exit `4` on failure). The bundler is crypto-agnostic and stays in the
  evidence layer.
- **Class 9 routing assertion: `ModelAdapter.served_by` (the spec, Class 9).**
  Class 9 must verify adapter *routing correctness*, not only weight bleed. A new
  non-abstract `ModelAdapter.served_by(tenant, prompt)` reports which tenant's
  adapter actually served an inference — a real adapter that cannot introspect its
  routing returns `None` (never a finding), while `FakeModel` attributes it
  precisely (a foreign owner under `adapter_bleed`). The runner records a foreign
  `served_by_tenant` on the observation, and the lora probe raises a confirmed
  `routing-*` finding for the mis-route, distinct from the canary weight-bleed
  finding. No schema or sample-pack change — it rides the existing
  `Observation.structured`. (Completes rank 12 with the Class 1 `access_outcome`
  half shipped just prior.)
- **Class 1 deny-semantics: `Observation.access_outcome` (the spec, Class 1).**
  Class 1 flags whether a direct cross-tenant fetch is denied, and the spec calls
  out the ambiguity a shallow scanner misses — a backend that returns `200` with
  an empty body looks like a deny but never enforced one. A new `AccessOutcome`
  enum (`RETURNED` / `EMPTY` / `DENIED`) is recorded on each fetch observation:
  the runner marks a `vector.fetch` `RETURNED` when the object surfaced (a leak if
  foreign) and `EMPTY` when absent (the ambiguous 200-empty), so evidence can
  distinguish the two. (Class 9's companion routing signal, `ModelResult.served_by_tenant`,
  follows in its own change — it reshapes the `ModelAdapter.infer` return across
  the fake and HuggingFace adapters.)
- **Per-probe secondary OWASP mappings (`Finding.owasp_secondary`, the spec §18).**
  Every finding carried only its primary OWASP class (`LLM08:2025`), but §18 also
  maps the catalog to `LLM02`/`LLM06` as secondary. `Finding` now carries
  `owasp_secondary`, stamped from each probe: the leakage probes map to
  `LLM02:2025` (Sensitive Information Disclosure) via a `DetectingProbe` default,
  and the agent/tool probes override to `LLM06:2025` (Excessive Agency). The 13
  `probe.yaml` manifests gained the field (with a parity assertion), and the
  committed JSON Schema artifacts and erasure sample packs were regenerated for the
  widened `Finding`.
- **Headline metrics for Class 3, 6, and 10 (`RunMetrics`, the spec §9 promise).**
  Three attack classes ran and produced findings but had no aggregate metric, so a
  run could not report or regression-gate them. `RunMetrics` now carries
  `poisoning_bleed_delta` (Class 3), `inversion_reconstruction_rate` (Class 6), and
  `extraction_efficiency` (Class 10) — each the fraction of that probe's benign
  query steps that surfaced a confirmed foreign canary, computed by the new
  `confirmed_finding_rate` helper (which `retrieval_pivot_rate` now aliases).
  `sectum-ai probe` records and prints them (and emits them in `--output json`), and
  `sectum-ai diff` / `baseline` flag a rise in any of them as a regression, exactly
  like the Retrieval-Pivot Rate. The committed JSON Schema artifacts and erasure
  sample packs were regenerated for the widened `RunMetrics`.
- **Structured logging with redaction, the last unimplemented §16 convention.**
  The spec requires `structlog`-based logging that never emits secrets or raw
  tenant content above DEBUG, with DEBUG off by default — and the library logged
  nothing at all. `sectum_ai.spec` now exports `get_logger` / `configure_logging` /
  `redact_sensitive`: a JSON renderer to **stderr** (stdout stays reserved for
  command output), DEBUG suppressed by default, and a processor that replaces
  secret-bearing and raw-tenant-content keys with `<redacted>` for every event
  above DEBUG. It is threaded through the runner (run completion), detection (a
  WARNING per confirmed cross-tenant leak — IDs only, never the span), the
  evidence chain (pack assembly), and the adapter registry; the CLI gained a
  global `--debug` flag (env `SECTUM_DEBUG`). `structlog` joins `sectum-ai-spec`'s
  dependencies (ADR-0020).
- **The data models ship as committed, version-pinned JSON Schema artifacts.**
  The spec §9 promise to "publish JSON Schema in `sectum-ai-spec`" was only half
  kept: the export *functions* existed but no schemas were committed or packaged,
  and `RunMetrics` (the headline-RPR block) and `ControlMapping` (the §18 table)
  were absent from the exported set. `sectum/spec/schemas/<Model>.schema.json` now
  holds all twelve models as standalone documents — each carrying a `$schema`
  dialect (draft 2020-12) and a version-pinned `$id`
  (`https://schemas.sectum.ai/<schema_version>/<Model>.schema.json`) — generated by
  `scripts/gen_schemas.py`, shipped in the wheel, and guarded by a drift test that
  fails if a committed artifact no longer matches its model.
- **Probes declare `requires_adapters`, and the runner preflights them.** Each
  plan/detect probe now names the adapter family it drives (the spec §7.0 / §11
  contract; all eleven were previously `()`), and `Runner.preflight` raises a
  config error (exit `3`) up front when a required adapter is not configured —
  instead of failing partway through a probe at the first missing-adapter step.
  The 13 `probe.yaml` manifests were regenerated, and a parity test asserts every
  probe's declared `requires_adapters` equals the slots its `plan()` actually
  drives, so the declaration can never drift from reality.
- **CI enforces the §15 per-package coverage floors.** A new CI step fails the
  build if `core`, `probes`, or `evidence` drops below 85% line coverage
  (`coverage report --include="packages/<pkg>/src/*" --fail-under=85`, reusing the
  test step's `.coverage`). The gate was specified but previously unenforced;
  current coverage is core 94.6% / probes 97.7% / evidence 91.1%.
- **`adapter_versions` is stamped from the `sectum-ai-adapters` distribution.** A
  run's `adapter_versions` recorded the core CLI's `__version__` for every
  adapter; it now resolves the adapters distribution version via the new
  `sectum_ai.adapters.version()` (with a `0.0.0+unknown` fallback) at both the probe
  and erasure sites, so an evidence pack attests the version of the code that
  actually drove each surface. Values are unchanged today (all packages ship in
  lockstep), so there is no canonical-hash or sample-pack change.
- **The backup surface is now covered everywhere, and a meta-test stops a new
  adapter family from landing uncovered.** The `BackupAdapter` family (Class 11
  hiding place #7) shipped but was skipped at every coverage seam: `FakeBackup`
  now runs the shared adapter contract suite, `sectum-ai adapters` lists it (with the
  search-index and eval-set fakes, also previously absent), and `sectum-ai erasure`
  seeds and scans a `FakeBackup` so the backup surface is attested in the erasure
  evidence pack (`adapter_versions`). A new contract meta-test asserts *every*
  `AdapterFamily` has a fake under the suite, so the gap that let backup slip
  cannot recur.
- **Real embedding-provider sweep for the Class 2 per-model Retrieval-Pivot
  Rate.** `retrieval_pivot_rate_by_model` modelled embedding strength with a
  recall knob on the in-memory `FakeVectorStore`, and the CLI recorded it only
  when the configured store *was* that fake — so the flagship "stronger
  embeddings leak more" gradient (arXiv:2602.08668) vanished on a live POC. A new
  provider-agnostic `EmbeddingModel` interface (`sectum_ai.embeddings`) adds a
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
- **Named, sellable probe suites — `sectum-ai probe --suite <name>`.** A *suite*
  fixes a probe set plus the compliance frameworks it provides evidence for, so an
  operator runs a named, control-mapped subset for a specific SKU instead of
  hand-picking probes. Ships `soc2-tenant-isolation` (the curated cross-tenant
  isolation checks → SOC 2 CC6.1/CC6.6/CC6.7, ISO 27001 A.8.3/A.8.12) and
  `owasp-llm08` (the full catalog). `--suite` and `--probe` are mutually exclusive;
  an unknown suite exits `3`. Suite definitions live in `sectum_ai.suites`, their
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
  and loadable via `sectum_ai.probes.load_probe_manifest(probe)`; a test enforces
  parity so a manifest can never drift from its class. Closes a standing §7.0
  gap (no manifests previously existed).
- **Optional weasyprint PDF engine for the audit pack.** `sectum-ai report
  --pdf-engine weasyprint` (or `render_audit_pack(..., engine=PdfEngine.WEASYPRINT)`)
  renders the auditor pack from an HTML/CSS template — severity badges, typographic
  tables, page footers — as an alternative to the default reportlab renderer.
  weasyprint is an optional extra (`pip install "sectum-ai[weasyprint]"`); the base
  install stays pure-Python and reportlab remains the default, and both engines
  render identical content. Resolves the spec §21 PDF-engine decision; see
  [ADR-0017](docs/adr/0017-pdf-engine.md).
- **`sectum-ai diff` — compare two runs or evidence packs.** Reports finding-level
  changes — which leaks appeared, were resolved, persist, or changed in place
  (status or severity) — on top of the `baseline --compare` metric deltas, and
  exits `2` when the later run regressed: a worsened metric, a newly confirmed
  finding (a fresh finding id, or an in-place unverified→confirmed upgrade), or a
  severity escalation of a finding confirmed in both runs. Takes a `run.json` or
  an `evidence.json` on either side, plus `--output json`.


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
- `ErasureUnsupported` is exported from `sectum_ai.spec` and subclasses
  `AdapterError`, so callers that don't special-case the caveat still catch
  it under existing adapter-error handling. The CLI resolver accepts
  `kind: helicone` and `kind: datadog` under `observability`;
  `docs/configuration.md` and `sectum-ai.yaml.example` document both, including
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
  `observability`; `docs/configuration.md` and `sectum-ai.yaml.example` are
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
  `docs/configuration.md` and `sectum-ai.yaml.example` are updated.
- A runnable Class 7 walkthrough for the new probe in
  `examples/agent-framework-hijack/` (README + `run.sh` +
  `sectum-ai.yaml`). The script seeds a four-tenant substrate, runs
  `sectum-ai probe --probe agent-framework-hijack` against the in-memory
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
  leaky-demo config flips both knobs on so `sectum-ai probe` reproduces
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
  `sectum-ai.yaml.example` are updated to match. Brings the live
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
  `sectum-ai.yaml.example` are updated to match. Brings the live
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
  `sectum-ai.yaml` swap that points the same probe at the new live
  `HuggingFaceLoraModel` for real-PEFT-stack probing. Smoke-tested on
  a clean substrate: the evidence pack verifies under `sectum-ai verify`.
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
  the evidence pack verifies under `sectum-ai verify`. Joins
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
  `sectum-ai verify`.
- A new `examples/agent-tool-hijack/` walkthrough that reproduces Attack
  Class 7 from the *agent-adapter* perspective: the same Class 7 probe
  the `examples/mcp-tenant-boundary/` example drives (with confused-deputy
  and token-passthrough sub-probes against the in-memory leaky MCP server),
  but framed around the agent caller and accompanied by
  `factories.py` — copy-pasteable connect-time factory callables for each
  of the four shipped agent kinds (`fake`, `langgraph`, `autogen`,
  `crewai`). README documents the `sectum-ai.yaml` swap for each kind so an
  operator can verify Class 7 with the same agent framework their customer
  actually runs in production. Smoke-tested on a clean substrate:
  `run.sh` exits with the canonical Class 7 leak findings and the evidence
  pack verifies under `sectum-ai verify`.
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
  `docs/configuration.md` and `sectum-ai.yaml.example` are updated to match.
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
  `sectum-ai.yaml.example` are updated to match.

### Changed

- **Entity-canary codenames fuse a high-entropy segment, so the detection
  backstop is sound at the source.** A canary was `Project <codename>-<serial>`
  with a dictionary codeword (e.g. "Zephyr"); the spec §6.4 FP-control ties a
  semantic leak to its marker by a *distinctive* shared token, but a bare
  codeword collides with ordinary text, so a benign mention plus an over-eager
  judge could fabricate a CONFIRMED leak (the only residual bypass the detection-
  side filter could not close, because a human-meaningful codeword is inherently
  collidable). Codenames are now `Project <codeword><base32>-<serial>` — the
  entropy is fused onto the word without a separator, so `_tokenize` sees one
  globally unique token that no benign text can echo. The codeword stays legible
  for demos; Class 2 semantic bleed is unaffected (it rides the shared *organic*
  corpus entities, not the unique canary). This moves the default-scenario
  manifest golden hash (the `scenario_hash` is unchanged — it hashes the Scenario
  inputs, not the generated marker plaintexts) and regenerates the committed
  sample evidence packs; hard- and secret-canary generation is untouched.
- **KV-cache timing applies a Bonferroni correction across tenant pairs.** A run
  performs one Welch's t-test per ordered tenant pair, so judging each at the
  per-pair `_ALPHA` inflated the family-wise false-positive rate. The run now
  divides the significance level by the number of comparisons, so the run-wide
  rate stays at `_ALPHA` - a conservative guard against reporting timing noise as
  a side channel. Each finding's evidence span records the corrected level.
- **The KV-cache timing probe runs on a freshly built model adapter.** It
  previously shared the suite's model instance, which the Class 9 LoRA probe
  trains/mutates - a contaminated adapter state could confound the prefix-cache
  timing. The CLI now builds a fresh model for the timing run (also giving it the
  cold cache its measurement warms).
- **Schema bump `0.3.0` → `0.4.0`** for the new `RunMetrics.erasure_coverage`
  block. The committed JSON Schemas, the default-scenario golden hashes, and the
  shipped sample evidence packs under `docs/samples/` are regenerated to 0.4.0; a
  pre-0.4.0 pack is refused by `sectum-ai verify` (major/minor mismatch), as
  intended.
- **Schema bump `0.4.0` → `0.5.0`** for the new Retrieval-Pivot Rate counts and
  confidence interval on `RunMetrics` (`retrieval_pivot_n`, `retrieval_pivot_k`,
  `retrieval_pivot_rate_ci`). The committed JSON Schemas, the default-scenario
  golden hashes, and the shipped sample evidence packs under `docs/samples/` are
  regenerated to 0.5.0; a pre-0.5.0 pack is refused by `sectum-ai verify`
  (major/minor mismatch), as intended.
- **Real embedding/judge providers retry a transient failure.** A provider HTTP
  call (`_post_json`) now retries a timeout, connection error, or HTTP
  429/500/502/503/504 up to three times with a short bounded backoff; a
  non-retryable client error (4xx other than 429) still raises at once, and the
  final transient failure still raises - a run that cannot detect must fail
  loudly, never yield a partial, falsely-clean attestation. A single rate-limit
  blip no longer aborts a long run.
- **The semantic detector caches window embeddings per observation.** When
  scoring an observation against many foreign markers, each candidate window is
  now embedded once and reused across markers (a per-observation cache) instead
  of being re-embedded per marker, cutting embedding calls on a real provider
  with no change to the result.
- **The leaky example `run.sh` scripts assert the expected leak.** The thirteen
  cross-tenant demo scripts now require `sectum-ai probe` to exit `2` (confirmed
  leaks) and fail loudly otherwise, instead of swallowing the exit code with
  `|| true` - so a regression that silenced a demo's findings can no longer pass
  unnoticed.


- **Rename tail: tooling config, CLI name, and resource-prefix defaults.** The
  default resource-namespace `prefix` for the Redis / Phoenix / LangSmith / Chroma
  adapters changes from `sectum` to `sectum-ai` (it only affects deployments that
  rely on the default key/collection/project prefix; set `prefix:` explicitly to
  pin a value). The `--version` banner now prints `sectum-ai <version>`, the Typer
  app name is `sectum-ai`, and the packaging config that the earlier passes missed
  is corrected — `[tool.coverage] source` and ruff's `known-first-party` now point
  at `sectum_ai` (the coverage gate measured the renamed package correctly only
  after this). A stray, accidentally-committed `examples/retrieval-pivot/.sectum/`
  workdir (matched `.gitignore` but was tracked) is removed.

- **The remaining `sectum` data slugs are renamed too (completes the rename).** The
  default workdir `.sectum` → `.sectum-ai`, the default config filename
  `sectum.yaml` → `sectum-ai.yaml` (and the example configs / `sectum.yaml.example`
  / `sectum.yaml.production`), and the demo `scenario_id` `sectum-demo-{seed}` →
  `sectum-ai-demo-{seed}` (so the run id is `run-sectum-ai-demo-{seed}`). The
  reproducibility golden hashes and every committed sample pack were regenerated
  accordingly. The `sectum.ai` domain is unchanged; the deployed
  `/sectum/platform/...` AWS SSM parameter paths are left to a separate infra
  redeploy.

- **BREAKING — the Python import is renamed `sectum` → `sectum_ai`, and the CLI
  binary `sectum` → `sectum-ai`.** Bare `sectum` is gone as a standalone name; the
  product is **Sectum AI** (prose), `sectum-ai` (distribution / repo / CLI), and
  `sectum_ai` (the valid-identifier import of that distribution). The PyPI
  distribution names are unchanged (`sectum-ai`, `sectum-ai-spec`, `-probes`,
  `-adapters`, `-evidence`); only the imported package and the console script
  change — so `pip install sectum-ai` still works, but code now does `import
  sectum_ai` and the command is `sectum-ai …`. Every package `src/sectum/`
  directory is now `src/sectum_ai/`, all imports/docs/examples are updated, and the
  committed JSON Schemas were regenerated (the change is the docstring reference in
  two `description`s; the `$id` is domain-based and unchanged). The `sectum.ai`
  domain, the `.sectum-ai` workdir, the `sectum-ai.yaml` config filename, and the
  `sectum-demo` scenario id are retained (renaming the latter would churn the
  reproducibility golden hashes and every sample pack). This supersedes the
  original §3 "resolved" import/CLI names by operator decision.


- **Regression comparison reports per-surface erasure _caveats_** as
  informational metric deltas (in `sectum-ai diff` and `sectum-ai baseline --compare`).
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

### Fixed

- **A missing optional adapter dependency fails with a clear error, not a
  traceback.** Selecting a live backend (`kind: pgvector`/`chroma`/`weaviate`/
  `pinecone`/`qdrant`/`redis`) without installing its extra raised an uncaught
  `ModuleNotFoundError` (exit 1) instead of the documented `AdapterError` →
  config/adapter exit code 3 that the model adapter already produced. The resolver
  now maps the missing-dependency `ImportError` to an `AdapterError` with an
  `install sectum-ai-adapters[<extra>]` hint, uniformly for every SDK-backed kind.
- **Demo metrics in the docs match the current code.** The retrieval-pivot
  example showed a stale confirmed-finding count (321 → 325) and an imprecise
  rate, and several places claimed a "100%" Retrieval-Pivot Rate on the
  shared-index demo where the showcase config actually measures **81.2%** (95% CI
  68.1%-89.8%, n=48). Corrected the example READMEs, the showcase config comment,
  the Class 2 attack-catalog page, and ADR-0005 to the measured rate (the product
  is built on honest measurement, so an overstated headline number is a
  credibility bug). Also fixed ADR-0001's residual pre-rename `sectum`
  console-script/namespace references to `sectum-ai` / `sectum_ai`.
- **The zero-false-positive backstop holds for a single-entity-marker manifest.**
  The FP-control demotes the entity template word "project" (shared scaffolding,
  not distinctive evidence) before deciding whether a judge's cited span ties back
  to a marker. That demotion was *statistical* — a token recurring across a
  majority of entity canaries — which a manifest with only one entity marker
  cannot calibrate (a single sample makes every token look equally non-recurring),
  so "project" read as distinctive and a parroting/lying judge could confirm a
  fabricated leak on the bare template word. The template tokens are now demoted
  unconditionally (a constant, kept in sync with the generator by a unit test),
  independent of manifest size. Not reachable through the shipped pipeline (the
  substrate plants ≥2 entity canaries per tenant), but `DetectionPipeline` is
  public and the zero-FP property is contractual. Regression test added.
- **`sectum-ai baseline` maps a config error to exit 3, not exit 1.** The command
  was missing the shared typed-error handler the other commands use, so a
  `ConfigError` surfaced as a generic crash (exit 1) instead of the documented
  config/adapter exit code (3). It now decodes typed errors like its siblings.
- **The Helicone and Datadog observability adapters bound their HTTP calls.** Each
  `urlopen` now uses a 30s timeout and wraps a `URLError`/timeout in `AdapterError`,
  so a hung or unreachable backend fails the run cleanly instead of blocking it or
  surfacing a raw urllib error.
- **A judge "yes" no longer confirms a finding on its own; it must tie back to the
  marker.** The detection pipeline enforces the spec §6.4 false-positive control
  for every judge: a semantic candidate is CONFIRMED only when the marker
  plaintext itself is token-order traceable in the observation, or the judge's
  cited evidence span is traceable AND shares a *distinctive* token with the
  marker - one not in the entity-canary template boilerplate (a token recurring
  across a majority of canaries, e.g. "project") and not a bare serial number
  (low-entropy, collides with everyday numbers), self-calibrated from the
  manifest. A genuine paraphrase of a distinctive canary reproduces its codename. A
  real LLM judge is primed with the marker plaintext, so a parroting or
  hallucinating verdict - or one that cites a real but marker-unrelated phrase,
  even one sharing only the template word - could otherwise place a fabricated
  CONFIRMED finding into the signed audit pack. Such
  affirmations are downgraded to UNVERIFIED candidates with the downgrade reason
  recorded. The deterministic fake judge's behavior is unchanged (it cites the
  marker plaintext, which confirms via the marker-presence path).
- **`calibrate` publishes the full-precision threshold.** The recommended
  threshold was rounded to 4 decimals for display, which could move the gate
  below a negative example the sweep had certified as excluded - silently
  breaking the zero-false-positive promise at deploy time. Scores now carry
  full precision (rounding is render-only).
- **The live HuggingFace model adapter no longer echoes its prompt.** HF
  `generate` output includes the input tokens; the adapter returned them, so
  the erasure probe - which prompts with the canary it scans for - read a
  fabricated 'residual' on the model surface before AND after erasure. The
  adapter now decodes only newly generated tokens, and the `ModelAdapter`
  contract states completion-only explicitly.
- **The Anthropic judge is deterministic and fence-tolerant.** It now pins
  `temperature: 0` (matching the OpenAI judge) so identical runs judge
  identically, and the verdict parser tolerates a fenced ```json response
  instead of aborting the run.
- **`hash-<dim>` embedding specs with a non-positive dimension are rejected at
  config time** instead of failing later when the sweep instantiates the
  embedder.

- **The live Langfuse observability adapter works against current Langfuse
  (v3).** Two issues surfaced by a self-hosted Langfuse erasure run: (1) the
  adapter requested `trace.list(limit=1000)`, but current Langfuse caps the
  public trace-list page size at 100 and rejects larger limits with HTTP 400 — it
  now pages at the API maximum up to the same scan budget; (2) Langfuse processes
  trace deletion asynchronously, so the erasure probe's immediate post-delete
  re-scan reported a **false RESIDUAL** for a backend that does fully erase —
  `delete()` now waits (bounded) for the tenant's traces to disappear before
  returning, so the erasure verdict is accurate. The adapter's erasure **scope**
  is now documented in `delete()`: it covers the project's traces (nested
  observations + scores cascade), not project-level prompts/datasets — full
  Article 17 erasure of a Langfuse tenant (a project) requires project deletion,
  so the erasure report attests the tracing surface, not project-level objects.

- **Open WebUI example: the provisioner now uploads every marker type, and the
  flagship's exact-vs-semantic distinction is stated honestly.** `provision_owui.py`
  filtered uploads to `HARD_CANARY` docs, silently dropping the `ENTITY_CANARY` and
  `SECRET_CANARY` pivot documents the substrate generates — so the run only ever
  exercised exact-substring matching, and the headline Retrieval-Pivot Rate was an
  *exact-match* figure, not the organic semantic entity-bleed the flagship is named
  for. The filter is removed (all pivot docs upload), and the README + configs now
  state that the default `fake` embedder measures the exact (HARD) + credential-format
  (SECRET) paths, while the semantic `ENTITY_CANARY` gradient requires a real
  embedder (`detection.embedder.kind: openai`). Surfaced by the first-run coverage analysis.

- **A `--rekor`-anchored evidence pack now verifies out of the box.** `verify`
  rejected a valid Sigstore Rekor inclusion proof with *"the Rekor log id … is not
  in the trusted keyring"* even though the correct public-good key ships: the
  keyring was keyed by the **base64** SHA-256 of the log key, but Rekor's API
  `logID` (stored verbatim as the proof's `log_id`) is the **hex** SHA-256, so a
  real proof's log id never matched. `_log_id` now uses hex (Rekor's own
  convention), so the shipped public-good key (`c0d23d6…`) is matched and a
  `report --rekor` → `verify` round-trip passes with no `--rekor-key`. (Surfaced by
  the first live Open WebUI run; the TSA anchor was unaffected.) Regression test
  pins the hex keying and that the public-good log id is trusted.


- **The audit-pack PDF now renders each finding's secondary OWASP classes.** The
  spec §18 maps a primary OWASP class plus secondary ones (e.g. `LLM02:2025` /
  `LLM06:2025`); they were recorded in `evidence.json` but the PDF's per-finding
  control line dropped them. Both PDF engines (`reportlab` and `weasyprint`) share
  the fix. The committed `docs/samples/` retrieval-pivot and residual-data erasure
  packs are regenerated so the public artifacts show the secondary classes (the
  all-erased happy-path pack has no findings and is unchanged).

- **Documentation accuracy sweep.** The glossary's `SECRET_CANARY` entry now
  describes the shipped form (an `sk-`/`AKIA`/`9xx`-SSN shape matched by an exact
  **and** credential-format pass, then redacted) instead of the removed
  `SECTUM-SECRET-<base32>` token; `compliance-mappings.md` no longer claims a
  per-pack "mapping revision" (the identifiers come from `sectum-ai-evidence` and
  the `ControlMapping` model is versioned by the shared `SCHEMA_VERSION`);
  `data-models.md` drops `SyntheticTenantSpec` from the committed-schema list (it
  is embedded inline in `Scenario` and has no standalone schema); and
  `threat-model.md` attributes timestamping/verification to the pack's
  `attested_digest` rather than `run_digest`.
- **Stale `src/sectum/` code-path references left by the rename are corrected.**
  The slash-delimited package path escaped the earlier rename passes, leaving
  broken links in the ADRs, several READMEs, `docs/`, and a `gen_schemas.py`
  docstring (now `src/sectum_ai/`), and — functionally — the `[tool.coverage]`
  omit globs (`*/sectum/adapters/*` → `*/sectum_ai/adapters/*`), which had stopped
  matching the moved adapter modules. The BYOC example deployment paths move to
  `/etc/sectum-ai/` for brand consistency.
- **`sectum-ai init` now generates a `sectum-ai.yaml` that every `--config` command can
  load.** The template's `security:` section had only a commented-out body, so
  YAML parsed it to `None`, which the non-optional `SectumConfig.security` field
  rejected — `sectum-ai seed --config <generated>` exited `3`, breaking the documented
  `init` → `--config` onboarding for every workflow command. The template now
  comments out the section *header* too (so the default applies), and
  `SectumConfig` defensively drops any section commented down to `null` so the
  field default is used. A regression test round-trips the generated template
  through `load_config`.

- **`sectum-ai-probes` now declares the `sectum-ai-adapters` dependency it imports
  — the published wheel was un-importable on its own.** `erasure/probe.py` and
  `kv_cache_timing/probe.py` import `sectum_ai.adapters` at module load (eagerly via
  `probes/__init__`), but `sectum-ai-probes` declared only `sectum-ai-spec` +
  `pyyaml`, so a clean `pip install sectum-ai-probes` followed by `import
  sectum_ai.probes` raised `ModuleNotFoundError: No module named 'sectum_ai.adapters'`
  (the dev uv workspace installs every package, which masked the missing edge). The
  dependency (and uv source) are now declared; the edge is acyclic since
  `sectum-ai-adapters` imports only `sectum_ai.spec`, and ADR-0004 is corrected (its
  "probes depends on `sectum-ai-spec` only" claim was stale). A new
  `tests/unit/test_packaging.py` guards this and the related direct-dependency
  declarations.

- **`sectum-ai` (core) now declares the `pydantic` it imports directly** rather
  than relying on the transitive edge via `sectum-ai-spec` (`config.py` /
  `cli/app.py` import pydantic), mirroring the adapters package and the §13
  declare-what-you-import discipline.

- **The `Probe` protocol now declares `owasp_secondary`**, the fourth
  control-classification attribute every probe already carries (§18 LLM02/LLM06
  secondary mapping) — so a `Probe`-typed consumer can read it without a type
  error. The public `payload_int` helper (formerly the private `_payload_int`) is
  no longer imported across a module boundary by `sweep.py`.

- **`scenario.embedding_models` is now wired end to end, so the per-model
  Retrieval-Pivot Rate is recorded on real CLI runs.** `ScenarioConfig` had no
  `embedding_models` (or `corpus_size`) field — with `extra="forbid"` a
  `sectum-ai.yaml` that set the documented key was rejected — and `sectum-ai seed` built
  the scenario from the seed alone, so `retrieval_pivot_rate_by_model` was always
  `{}` off a real `seed`→`probe` run (the flagship "stronger embeddings leak more"
  gradient only ever appeared in unit tests). `ScenarioConfig` now carries both
  fields, `seed` threads them through `default_scenario`, and a repeatable
  `sectum-ai seed --embedding-model <spec>` overrides them; an unknown spec is
  rejected with a config error (exit `3`) at load/parse time rather than silently
  becoming an empty sweep. A full-CLI E2E seeds two embedding models and asserts
  the per-model rate is recorded with the expected gradient.

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
- **`sectum-ai verify` now re-checks the in-toto attestation sidecar.** `report` /
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
  so a `sectum-ai.yaml` requesting per-user (ADR-0006) isolation on those families
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
  `_load_run`, and `sectum-ai baseline --compare` called `model_validate_json`
  unguarded, so a malformed artifact raised an unhandled `ValidationError` that
  Typer reported as an opaque exit `1` rather than the documented config-error
  exit `3`. Each load now catches the error and exits `3` with a message naming
  the bad file.
- **`sectum-ai baseline --compare` now gates on the full run diff, not metrics
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
  excludes them, so onboarding such a backend no longer makes `sectum-ai diff` /
  `sectum-ai baseline --compare` report a regression (exit 2) on the GDPR
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
  (gating `sectum-ai diff` / `baseline --compare`) — inconsistent with the other
  observability backends for the same real condition. A `404` still means the
  spans are already absent and remains an idempotent erasure success.
- **`sectum-ai erasure` now itemizes an attestable-with-caveat surface even when a
  genuine residual co-exists.** When a soft-deleting surface (a real erasure
  failure) and a no-erasure-API surface (a caveat) were both present, the
  dominant `ERASURE FAILED` message returned early and the caveat surface was
  never printed, so a DPO reading the CLI summary could miss that a second
  surface still held data. Both are now reported before the exit `2`.
- **In-toto attestations no longer over-claim a timestamp anchor for a local
  development token.** The predicate's `anchors.timestamp` was `true` whenever a
  token was present, but `sectum-ai verify` treats the `local-dev` JSON token as
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
  `SurfaceErasure` verdict still read `RESIDUAL DATA`, the `sectum-ai erasure`
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
  reachable from `sectum-ai.yaml` (`observability: {kind: fake, no_erasure: true}`)
  and covered by a CLI-level test.

### Security

- **Log redaction is recursive and value-aware (defense in depth).** The
  `redact_sensitive` processor previously dropped sensitive values only by
  *top-level* key name, so a secret nested under a benign key, embedded in the
  event message, or carried in an exception's text could slip into logs. It now
  recurses into nested dicts/lists (dropping a sensitive key at any depth) and
  scrubs the distinctive canary/secret *shapes* (`SECTUM-CANARY-…`, `sk-…`,
  `AKIA…`, the non-issuable `9xx` SSN form) wherever they appear. No production
  call site relied on the gap (logs carry only operational metadata); this is a
  backstop against a future careless one. DEBUG output is unchanged (ADR-0020).
- **`sectum-ai verify` now requires an independent anchor by default.** The
  flag-based downgrade guards could not stop an attacker who edits a pack,
  recomputes the digest with both anchor flags false, and re-stamps it with a
  fresh local-dev token — the token is reproducible by anyone, so the tampered
  pack verified PASS. `verify_pack`/`verify_bundle` gain `require_anchored` and
  report `anchored` on the result; the CLI fails such a pack (exit 4, a failing
  `independent-anchor` check) unless `--allow-unanchored` is passed, and an
  accepted unanchored pack reads `INTEGRITY OK - UNANCHORED`, never `VERIFIED`.
  Bundles also refuse duplicate ZIP member names and thread `--tsa-cert`/
  `--tsa-root` through to the contained pack. The local-dev timestamper's
  docstring no longer claims its token catches tampering.

- **The RFC 3161 timestamp anchor is now downgrade-resistant.** A pack timestamped
  by a real TSA could have its binary `tsa_token` swapped for a `local-dev` JSON
  token carrying the same digest and still verify (reported as "unanchored"),
  silently dropping the one independent proof of *when* the evidence existed —
  load-bearing for the GDPR Art. 17 erasure timeline. A new `anchored_with_timestamp`
  flag, bound into the attested digest (mirroring `anchored_in_log`), makes
  `sectum-ai verify` demand a real RFC 3161 token whenever a pack claims one, so the
  swap fails. This bumps `SCHEMA_VERSION` `0.2.0` → `0.3.0`; the committed JSON
  schemas, the reproducibility golden hashes, and the `docs/samples/` packs are
  regenerated, and pre-`0.3.0` packs are refused by the schema gate with a clear
  version-mismatch message (ADR-0016).

- **`verify_bundle` now reconciles a bundle's ZIP members against its digest
  manifest, closing a tamper-evidence hole.** The integrity loop only iterated
  manifest-*listed* members, so a file physically present in the archive but absent
  from `bundle-manifest.json` was covered by no digest check — and because the
  audit-PDF / sidecar selection reads the raw ZIP, an unlisted forged member (e.g.
  a fake `erasure-attestation.pdf` claiming "zero residue") could ride inside a
  bundle that `sectum-ai verify` reported as PASSING, and could even be the member
  delivered. Verification now fails on any archive member not covered by the
  manifest, so a bundle attests exactly its manifest's member set (the engineering
  spec §8.1). Regression test added for the smuggled-unlisted-member attack.


- **`sectum-ai verify <bundle.zip>` now binds the bundled audit PDF and attestation
  sidecars to the pack — closing a verification-bypass in the bundle path.**
  `verify_bundle` recomputed each member's digest against `bundle-manifest.json`
  but called `verify_pack` without the audit PDF or the in-toto/DSSE sidecars, so a
  delivered `report --bundle` archive could be **rebuilt** with a forged "zero
  leakage" `audit-pack.pdf` (its digest re-recorded in the in-archive manifest) —
  or with sidecars attesting a different run — and still pass `sectum-ai verify`,
  breaking the §8.1 tamper-evidence guarantee (the standalone `sectum-ai verify
  evidence.json` path already enforced this via the on-disk siblings; only the
  bundle path was blind). `verify_bundle` now passes the bundled PDF to
  `verify_pack` (enforcing the bound `pdf_ref`), fails when a pack binds a
  `pdf_ref` but the bundle carries no PDF member, and re-runs
  `verify_in_toto_statement` / `verify_dsse_envelope` against the bundled sidecars.
  Regression tests rebuild a bundle with a forged PDF and with a different-run
  sidecar and assert verification fails (the previous test mutated a member without
  rebuilding the manifest, so it only exercised the member-digest check).

- **The audit-pack PDF is now bound into the tamper-evident digest.** The
  DPO/auditor-facing PDF was never covered by the attested digest, so it could be
  silently swapped while `sectum-ai verify` still reported PASS. `sectum-ai report` /
  `sectum-ai erasure` now render the PDF first, hash its bytes, and bind that SHA-256
  as the pack's `pdf_ref` (which `attested_digest` already covers), so the signed
  digest commits to the exact PDF. `sectum-ai verify` re-hashes the audit PDF when it
  sits beside the pack (`audit-pack.pdf` / `erasure-attestation.pdf`) and fails on
  a mismatch, while still verifying from `evidence.json` alone when the PDF is
  absent. To make the PDF a pure function of pre-signature content (so it hashes
  deterministically before signing), the raw timestamp-token row was dropped from
  the rendered PDF — the token remains in `evidence.json`, and the PDF still
  directs the reader to run `sectum-ai verify`. Both PDF engines render the same
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


- **Evidence packs are tamper-evident across their whole attested surface.** The
  timestamp and Rekor anchors now bind the control mappings, the recorded PDF
  reference, and the manifest hash — not just the run record — so forging the
  compliance claims or altering the recorded PDF reference makes `sectum-ai verify`
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

### Documentation

- **Doc-accuracy sweep across the CLI/config surface.** `configuration.md` gains
  the `qdrant` vector row, the `security`/`detection` sections (the mapping is six
  top-level keys, not four), and the per-adapter `user_scoped` field; the `init`
  config template and the module docstrings list every resolvable adapter `kind`
  (pinecone/qdrant, langchain, the observability and agent kinds) plus `calibrate`;
  the README package table, CONTRIBUTING, the glossary, `evidence-chain.md` (the
  *attested* digest is anchored, not the run digest; the Outputs section now lists
  `evidence.dsse.json` and the `--bundle`/`--pdf-engine`/`--include-manifest`
  flags), `data-models.md` (tenant `locale`), and the vs-DeepTeam framework list
  (ISO/IEC 42001 + CCPA) are corrected, and the residual bare `sectum` references
  become `sectum-ai`. The duplicate `[Unreleased]` type headings are consolidated
  to one each.
- **`configuration.md` now documents the fake RAG/agent leak knobs and corrects
  the adapter-field-validation wording.** The `rag.fake` and `agent.fake` rows said
  "needs no fields", but both carry load-bearing leak knobs (`shared_index` for
  Class 2 at the pipeline end; `confused_deputy` / `tool_call_passthrough` for
  Class 7) — a `--config` user who omitted them silently got zero such findings.
  The page also no longer claims the `build_*` resolvers "validate" extra fields:
  `AdapterConfig` is `extra="allow"`, so a misspelled knob is accepted and silently
  ignored (it type-checks only the keys it consumes).

- **Two reference pages document the shipped substrate and data models, and a new
  example walks the RAG-pipeline variant of the flagship probe.**
  [`docs/substrate.md`](docs/substrate.md) covers the marker substrate end to end
  (§6) — synthetic tenants and shared entities, corpus generation, the three
  canary types with their distinct detection paths, multi-field planting,
  model-scoped embedding references, secret redaction, the four-step detection
  pipeline with its zero-FP/zero-FN guarantees, and the reproducibility contract.
  [`docs/data-models.md`](docs/data-models.md) documents the `sectum_ai.spec` models
  (§9), links the committed Draft 2020-12 JSON Schemas (generated by
  `scripts/gen_schemas.py`, parity-tested), and records `SCHEMA_VERSION` and the
  canonical-hashing rules. Both are added to the docs nav. A new
  [`examples/rag-pipeline-bleed/`](examples/rag-pipeline-bleed/) walkthrough runs
  the `rag-pipeline-bleed` probe (Class 2 at the customer-facing RAG endpoint, the
  companion to `retrieval-pivot`) end to end and is wired into the e2e example
  suite.

- **ADR-0019 records the job-runner decision; the adapters package declares its
  direct dependencies.** [ADR-0019](docs/adr/0019-job-runner-abstraction.md)
  resolves the spec §21 open decision — the engine binds to the `JobRunner`
  protocol with local serial/thread runners and a distributed backend (Temporal /
  Prefect) stays swappable — and reads the §13 "Async" wording as a thread pool
  (a swap-ability test covers a custom runner dropping in). `sectum-ai-adapters`
  now declares `pydantic` directly (used by `base.py`) and `httpx` in the
  `phoenix` extra (used by the Phoenix adapter), rather than relying on transitive
  resolution (§13 dependency discipline).
- **All six build-plan phases now record ✅ Met.** With the `embedding_models`
  CLI wiring shipped, `PHASES.md` Phase 5 moves to Met (cited to the new full-CLI
  sweep E2E `test_full_cli_sweep_records_per_model_rpr` and the existing baseline
  regression tests), and its follow-on note marks P5 shipped. The README status
  note drops the "one criterion still being closed" caveat — pre-alpha now
  reflects API maturity, not missing phases — and still points to `PHASES.md` as
  the authoritative gate record.
- **`docs/adapters.md` live-adapter narrative refreshed to the current set.** The
  prose documented only the early adapters; it now covers the observability
  adapters (Helicone, Datadog, generic OpenTelemetry) and their
  attestable-with-caveat erasure behaviour for Class 11, the LangChain RAG
  pipeline, the framework-native agents (LangGraph, CrewAI, AutoGen, OpenAI
  Assistants, Anthropic tool-use), the HuggingFace LoRA model, and the HTTP MCP
  client — as prose, cross-linked to `docs/configuration.md` for the full field
  reference.
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
- **`sectum-ai.yaml.example` used the wrong vector adapter key.** The example
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
    string); the core-package quickstart verifies `.sectum-ai/evidence.json` and the
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

## [0.1.0] - 2026-05-26

First public release. Sectum AI ships as a five-package `uv` workspace
(`sectum-ai`, `sectum-ai-spec`, `sectum-ai-probes`, `sectum-ai-adapters`,
`sectum-ai-evidence`), Apache-2.0 licensed, with a tamper-evident evidence
chain anyone can verify with `sectum-ai verify` and no Sectum-side trust.
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
  `sectum-ai.yaml.example` are updated to match.
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
  RESIDUAL DATA pack produced by `sectum-ai erasure --soft-delete` against the
  `examples/erasure-attestation` substrate. Three new files
  (`erasure-attestation-residual-data-audit-pack.pdf`,
  `erasure-attestation-residual-data-evidence.json`,
  `erasure-attestation-residual-data-attestation.intoto.json`) sit next to the
  existing happy-path ERASED pack so a prospective DPO can see both the
  successful-erasure deliverable and the failure-mode artefact the pack is
  built to catch — without running anything locally. The samples README now
  describes both verdict flavours, lists the regeneration commands for both,
  and explains that either pack verifies under `sectum-ai verify`; the verdict
  is data, not signal integrity.
- `examples/erasure-attestation/sectum-ai.yaml.production`: a documented
  production-shape config for the engagement, with `evidence.timestamper:
  local` and `evidence.rekor: true` defaults and a comment explaining why
  real engagements should pin a customer-chosen TSA URL (FreeTSA, the OSS
  demo default, has been observed to be unreachable for hours at a time).
  Used by the sample regeneration in `docs/samples/README.md`.
- `sectum-ai probe --output json` emits a single machine-parseable JSON object on
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
  suite; the `sectum-ai adapters` CLI command; and live pgvector and Chroma
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
- Phase 3 - the CLI: `sectum-ai seed` provisions the substrate, `sectum-ai probe`
  runs the probe suite (recording findings and the Retrieval-Pivot Rate),
  `sectum-ai report` assembles the evidence pack (JSON and PDF), `sectum-ai verify`
  independently verifies it, `sectum-ai erasure` runs the GDPR Article 17
  erasure-verification workflow into an attestation pack, and `sectum-ai init`
  scaffolds a starter `sectum-ai.yaml` config.
- Phase 3 - end-to-end examples: `examples/retrieval-pivot` (the flagship
  Class 2 walkthrough, from seeding through a verified evidence pack) and
  `examples/erasure-attestation` (the Class 11 erasure-verification wedge).
- Phase 4 - the model/adapter layer and the agent surface: a
  `ModelAdapter` adapter family with a deterministic `FakeModel`; the Class 9
  LoRA / adapter cross-tenant-influence probe; and the Class 7 cross-tenant
  agent tool-call hijacking probe (the MCP confused-deputy and token-passthrough
  sub-probes) over an extended `FakeMCP`. Both probes join the `sectum-ai probe`
  suite.
- Phase 4 - the threat model: `docs/threat-model.md` records the
  trust boundaries, the assets (the ground-truth manifest, evidence packs), the
  deployment modes, and Sectum AI's explicit non-goals.
- Phase 4 - a mkdocs-material documentation site: a page per
  implemented attack class, plus the evidence chain, compliance mappings, the
  adapters, the ADRs, and the threat model, with a build-and-deploy workflow.
- Phase 4 - the `sectum-ai probe --probe` filter to run a single
  probe, and the `examples/mcp-tenant-boundary` Class 7 walkthrough.
- Phase 5 - the regression-baseline engine: `sectum-ai baseline`
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
- A typed `sectum-ai.yaml` configuration loader in `sectum_ai.config`: pydantic
  models for the scenario, adapter, and evidence blocks, and a `load_config`
  function that raises `ConfigError` on a missing file, malformed YAML, or an
  invalid schema. `sectum-ai seed` accepts `--config sectum-ai.yaml` and reads its
  scenario seed and workdir from the file; explicit `--seed`/`--workdir` flags
  override the config.
- A config-driven adapter resolver in `sectum_ai.config`: `build_adapters`
  dispatches each adapter family's `kind` to a concrete `Adapter`, defaulting
  missing families to plain fakes. `sectum-ai probe` accepts `--config` and
  builds its adapter bundle from the file, so a tenant-isolated config (every
  leak knob off) records zero confirmed findings while the default leaky-demo
  config keeps reproducing them. The `sectum-ai init` template now exposes every
  adapter family's leak knobs so the demo round-trips through the resolver.
- The CLI resolver now wires the live adapters: `kind: pgvector`, `chroma`,
  or `weaviate` for `adapters.vector_store`; `kind: redis` for `adapters.cache`;
  and `kind: stdio` for `adapters.mcp`. Secrets reference environment variables
  (`dsn_env: SECTUM_PGVECTOR_DSN`); vector adapters receive a deterministic
  hashing-trick embedder so a sectum-driven verification needs no
  embedding-model account.
- `sectum-ai erasure`, `sectum-ai report`, and `sectum-ai baseline` accept
  `--config sectum-ai.yaml` and use its workdir as a default, completing the
  per-command `--config` coverage for every workflow command.
- A `docs/configuration.md` reference page in the mkdocs nav: the `sectum-ai.yaml`
  top-level shape, every adapter family's supported `kind`s with their fields
  and defaults, the env-var secret pattern, and a live-pgvector example.
- Extend the scenario runner with `rag.ask`, `observability.search`, and
  `agent.run` actions and pair them with new `rag`, `observability`, and
  `agent` fields on `AdapterBundle`; the CLI's `sectum-ai probe` passes the
  three new adapters into the runner. Probes can now drive a RAG pipeline,
  search observability traces, or run an agent task directly through the
  runner; the config resolver wires the three new families to their fakes.
- The CLI resolver wires the live HTTP RAG, Phoenix observability, and HTTP
  agent adapters: `kind: http` in `adapters.rag` or `adapters.agent` selects
  `HttpRAGPipeline`/`HttpAgent`; `kind: phoenix` in `adapters.observability`
  selects `PhoenixObservability`. New `_float` and `_str_dict` helpers parse
  timeouts and header maps from the config.
- `sectum-ai probe` accepts `--max-concurrency N` (default 1) to run probes in
  parallel via a thread pool. N > 1 requires both thread-safe adapters and
  that probe-order interactions don't matter; the demo's in-memory fakes
  share state across mutating and reading probes, so concurrent execution
  there yields nondeterministic findings (the exit code is still stable).
- Class 11 (`sectum-ai erasure`) now checks the observability surface. The
  `ObservabilityAdapter` interface gains `delete(tenant)`; `FakeObservability`
  gets a `soft_delete` knob mirroring `FakeVectorStore`; `PhoenixObservability`
  removes the tenant's project on delete. `ErasureProbe` accepts an optional
  `observability` adapter and scans the tracing surface for residual markers,
  and `sectum-ai erasure` seeds traces and passes a `FakeObservability` through
  so the workflow round-trips through both the vector and tracing surfaces.
- Class 11 (`sectum-ai erasure`) now also checks the agent/long-term memory surface
  (a third of the spec's "ten hiding places"). The `MemoryAdapter` interface
  gains `delete(tenant)`; `FakeMemory` gets a `soft_delete` knob; `ErasureProbe`
  accepts an optional `memory` adapter and scans it (via `recall`) for residual
  markers, and `sectum-ai erasure` seeds memory and passes a `FakeMemory` through
  so the workflow round-trips the vector, tracing, and memory surfaces.
- Class 11 (`sectum-ai erasure`) now also checks the semantic/application cache
  surface. The `CacheAdapter` interface gains `delete(tenant)` and `values(tenant)`
  (the values a tenant can read - the tenant's own when scoped, all of them when
  not, which is itself the leak); `FakeCache` gets a `soft_delete` knob and
  `RedisCache` deletes/scans the tenant's prefixed keys. `ErasureProbe` accepts
  an optional `cache` adapter and scans its values for residual markers, and
  `sectum-ai erasure` seeds the cache through, so the workflow now round-trips the
  vector, tracing, memory, and cache surfaces. An unscoped cache that cannot
  isolate a tenant's entries is itself an erasure failure.
- Class 11 (`sectum-ai erasure`) now also checks the model / fine-tune-adapter
  surface. The `ModelAdapter` interface gains `delete(tenant)`; `FakeModel` gets
  a `soft_delete` knob; `ErasureProbe` accepts an optional `model` adapter and
  scans it by querying the model with the canary - a memorized canary surfaces
  only while the tenant's adapter exists - and `sectum-ai erasure` trains and
  threads a `FakeModel` through, so the workflow now round-trips the vector,
  tracing, memory, cache, and model surfaces (five of the "ten hiding places").
- Class 11 (`sectum-ai erasure`) now also checks the derived full-text search-index
  surface (the tenth "hiding place"). A new `SearchIndexAdapter` family
  (`search` + `delete`, capability `TEXT_SEARCH`) and its `FakeSearchIndex` (with
  a `soft_delete` knob) model a keyword index built from the corpus, distinct
  from the embedding vector store; `ErasureProbe` accepts an optional
  `search_index` adapter and scans it for residual markers, and `sectum-ai erasure`
  indexes and threads a `FakeSearchIndex` through. The workflow now round-trips
  six of the "ten hiding places". There is no live search-index adapter yet, so
  the fake carries the behavior.
- Class 11 (`sectum-ai erasure`) now also checks the evaluation / golden-set surface
  (the fourth "hiding place" - test fixtures and eval datasets that may copy
  tenant content). A new `EvalSetAdapter` family (`search` + `delete`, reusing
  the `TEXT_SEARCH` capability) and its `FakeEvalSet` (with a `soft_delete` knob)
  model an eval set; `ErasureProbe` accepts an optional `eval_set` adapter and
  scans it for residual markers, and `sectum-ai erasure` seeds and threads a
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
- A self-documenting `sectum-ai.yaml.example` at the repo root: every block the
  config schema accepts (scenario, workdir, all eight adapter families with
  per-`kind` placeholders for the live backends, evidence chain, security/
  manifest-at-rest, detection providers and semantic threshold) with copy-and-
  edit annotations. Validated to load cleanly under `sectum_ai.config.load_config`.
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
  anything. Each pack ships its in-toto attestation envelope; `sectum-ai verify
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
- The Class 2 embedding-model sweep (`sectum_ai.sweep.embedding_model_sweep`): runs
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
- A real RFC 3161 trusted-timestamping path (`sectum_ai.evidence.Rfc3161Timestamper`,
  `verify_rfc3161_token`): `sectum-ai report --tsa <url>` (or `evidence.timestamper:
  rfc3161` in the config) submits the run digest to a Time-Stamp Authority and
  stores the returned token, and `sectum-ai verify` checks that token against the
  recomputed digest. Trust is pinned independently of the pack: the verifier
  ships the public FreeTSA leaf and root built in, and `sectum-ai verify
  --tsa-cert/--tsa-root` override them for a customer-pinned TSA. Backed by the
  `rfc3161-client` library behind a `sectum-ai-evidence[rfc3161]` extra (pinned
  `>=1.0.3` for CVE-2025-52556); a committed FreeTSA token fixture verifies
  offline in CI, and a live round-trip is opt-in via `SECTUM_RUN_LIVE_TSA`
  (the engineering spec, section 8.2).
- Configurable real embedding and judge providers for the detection pipeline
  (`sectum_ai.probes.providers`): `OpenAIEmbeddingProvider` and an `OpenAIJudge` /
  `AnthropicJudge`, reached over their HTTP APIs (standard library only). A
  `detection` config block selects the embedder and judge (`fake` by default),
  their models, the API-key env var, and the `semantic_threshold`; the resolver
  builds a `DetectionProviders` bundle that `sectum-ai probe` threads through every
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
- A job-runner abstraction (`sectum_ai.jobs`): a small `JobRunner` interface
  (`map(func, items) -> list`, results in input order) with two local
  implementations - `SerialJobRunner` and a bounded `ThreadJobRunner` -
  selected by `build_job_runner(max_concurrency)`. `sectum-ai probe` now executes
  its suite through this interface instead of an inline thread pool, so
  `--max-concurrency` is unchanged while the orchestration layer becomes the
  documented seam where a distributed backend (Temporal, Prefect) can drop in
  later without touching call sites (the engineering spec, sections 13 and 21,
  the open job-runner decision).
- At-rest encryption of the seeded substrate (`sectum_ai.crypto`): set
  `security.manifest_key_env` to the name of an environment variable holding a
  base64 32-byte key, and `sectum-ai seed` seals the substrate - which holds the
  ground-truth manifest and the planted canary plaintexts - with AES-256-GCM
  before it touches disk (`substrate.json.enc`); `sectum-ai probe`/`report`/
  `erasure` open it with the same key. A wrong key or any tampering fails
  authentication. The key is referenced from the environment, never inlined
  (the engineering spec, section 17). Backed by `cryptography` behind a
  `sectum-ai[encryption]` extra; the unencrypted path needs nothing extra.
- An in-toto attestation wrapping (`sectum_ai.evidence.to_in_toto_statement`,
  `verify_in_toto_statement`): `sectum-ai report` and `sectum-ai erasure` also emit
  `attestation.intoto.json`, the evidence re-expressed as an in-toto Statement
  (v1) - subject = the run bound by its canonical digest, predicate = the
  verification result (scenario/manifest hashes, metrics, control mappings, and
  which integrity anchors are present). It is a derived, interoperable view of
  the pack and adds no new trust; standard-library only (the engineering spec,
  section 13).
- A Sigstore Rekor transparency-log anchor (`sectum_ai.evidence.RekorTransparencyLog`,
  `verify_rekor_proof`): `sectum-ai report --rekor` (or `evidence.rekor: true`)
  signs the run digest and records a `hashedrekord` entry in a public,
  append-only log, storing the inclusion proof in the pack; `sectum-ai verify`
  recomputes the RFC 6962 Merkle root and checks the signed checkpoint that
  commits to it. As with the TSA, the checkpoint key is pinned independently of
  the pack: the public-good instance's log keys (ECDSA and Ed25519) are shipped
  built in and selected by log id, and `sectum-ai verify --rekor-key <pem>` pins a
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
