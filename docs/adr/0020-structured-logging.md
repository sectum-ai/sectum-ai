# ADR-0020: structured logging with redaction, to stderr, DEBUG off by default

- Status: Accepted
- Date: 2026-06-02
- Deciders: Dmitry Maranik

## Context

The engineering spec, section 16, requires "structured logging (`structlog`),
never log secrets or raw tenant content above DEBUG, and DEBUG must be off by
default." Until now this was the one §16 convention with no implementation: the
library emitted nothing, so an operator running a verification had no audit trail
of what ran, and any future `print`/`logging` call would have risked leaking a
canary plaintext or a tenant's retrieved content into logs — unacceptable for a
product whose whole job is proving that tenant data does not leak.

Two constraints shape the design:

- **The package graph is acyclic** (ADR-0004): core → probes → adapters → spec,
  and evidence → spec. For one logging facility to be usable from the runner
  (core), detection (probes), the evidence chain (evidence), *and* the adapters,
  it must live in the one package they all depend on — `sectum_ai.spec`.
- **stdout is a data channel.** `sectum-ai probe --output json` and the verifier
  write machine-readable results to stdout; logs must not corrupt them.

## Decision

Add `sectum_ai.spec._logging`, re-exported as `get_logger`, `configure_logging`, and
`redact_sensitive` from `sectum_ai.spec`.

- **Library code calls `get_logger(__name__)`; the application configures once.**
  The CLI's root callback calls `configure_logging(debug=...)` (a global
  `--debug` flag, env `SECTUM_DEBUG`); a library never configures logging on
  import. The test suite configures it through an autouse fixture so output is
  deterministic.
- **JSON to stderr.** `configure_logging` installs a `structlog` JSON renderer
  writing to **stderr**, so stdout stays reserved for command output. (Click 8.2+
  captures stderr separately, so this also keeps the CLI tests' `result.output`
  assertions clean.)
- **DEBUG off by default.** The wrapper is `make_filtering_bound_logger(INFO)`
  unless `--debug`; `debug()` events are dropped entirely at the default level.
- **Redaction processor.** `redact_sensitive` drops secret-bearing keys
  (`token`, `api_key`, `authorization`, `plaintext`, `canary`, …) and raw
  tenant-content keys (`content`, `raw_response`, `answer`, `query`, `prompt`,
  `evidence_span`, …) from every event emitted *above* DEBUG, replacing them with
  `<redacted>`. It recurses into nested dicts/lists (so a sensitive key is caught
  at any depth) and additionally scrubs the distinctive canary/secret *shapes*
  (`SECTUM-CANARY-…`, `sk-…`, `AKIA…`, the non-issuable `9xx` SSN form) wherever
  they appear — including the event message and an exception's text. DEBUG is
  opt-in, so verbose local troubleshooting may still carry raw values — exactly
  the "never … above DEBUG" boundary the spec draws.
- **What gets logged.** Operational metadata only: probe-run completion (probe id,
  step/finding/confirmed-leak counts), a WARNING per confirmed cross-tenant leak
  (marker id, owner/observed tenant ids, surface, severity — never the span),
  evidence-pack assembly (run id, digest), and DEBUG adapter registration. No
  step payloads, observations, or marker plaintext are passed to a logger.

## Consequences

- `structlog` becomes a dependency of `sectum-ai-spec`, the otherwise
  pydantic-only base package. It is named in spec §13, is pure-Python, and is the
  only way one facility can serve every layer without breaking the package graph.
- The redaction guarantee is enforced by a pure, unit-tested processor
  (`tests/unit/test_logging.py`): secrets and tenant content are `<redacted>` at
  INFO, pass through at DEBUG, logs land on stderr (never stdout), and DEBUG is
  silent by default.
- Redaction is **key-name based, with a narrow value-shape backstop**: sensitive
  keys are dropped at any nesting depth, and the distinctive canary/secret shapes
  are scrubbed wherever they appear (the message, a nested value, an exception's
  text). A caller that puts a *non-shaped* secret under an unlisted key inside
  free text could still leak it, so the convention still stands — pass structured
  fields, never interpolate tenant content or secrets into the event string —
  backed by the small, audited set of log sites. A *broad* value-scanner (every
  value against many patterns) was considered and rejected as costly and
  false-positive-prone; the shape-scoped scrub added later — defense in depth,
  after a review flagged the key-name-only gap — is cheap and matches only
  unmistakable canary/credential formats, so it avoids both objections.
