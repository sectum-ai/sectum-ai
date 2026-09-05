# Threat Model

This document states what Sectum AI defends, the boundaries it operates across,
the assets it handles, and — explicitly — what it does not do. It is the
authoritative reference for the security posture of the open-source core.

## What Sectum AI is

Sectum AI is a multi-tenant AI verification tool. It provisions synthetic
tenants on an AI stack, seeds them with cryptographic canary markers, runs a
catalog of benign and adversarial probes from each tenant's session, and
produces a tamper-evident, control-mapped evidence pack.

Sectum AI **verifies and attests**. It answers one question: can one principal's
data reach another across an AI system's surfaces? A *principal* is an isolation
boundary — a tenant, or a user within a tenant (see *The isolation boundary*
below).

## The isolation boundary

The boundary Sectum AI verifies is a **principal**, not only a tenant
([ADR-0006](adr/0006-principal-isolation-model.md)):

- **Tenant vs tenant** is the primary boundary; a marker crossing it is always a
  leak.
- **User vs user within a tenant** is verified additively. When a scenario
  declares users, a marker owned by one user surfacing in another user's session
  is a leak, under a **default-deny** policy: any cross-user appearance is
  flagged. Modelling *intended* within-tenant sharing (a legitimate-sharing
  policy) is a deliberate non-goal of the current core.

Detection and every probe share one predicate (`is_cross_principal`), and the
adapter SDK carries an optional user scope
([ADR-0008](adr/0008-adapter-user-dimension.md)), so a probe verifies isolation
at both granularities — **but only where the adapter carries the calling user to
its backend** (`carries_user`, which a live adapter sets from its `user_scoped`
knob). Where it does not, a user-level step would run as the tenant and be judged
as the user, so the runner does not run it: the run exercises the tenant boundary
alone, records the count in `RunMetrics.user_steps_dropped`, warns on stderr, and
`diff` / `baseline --compare` report a run that stopped exercising it as
`[BOUNDARY LOST]`. A probe left with no judged step runs nothing at all rather
than grading its class off its plants. With no users declared, behaviour is
exactly the tenant-level case.

## What Sectum AI is not — out of scope

Sectum AI deliberately does not:

- **Remediate.** Findings carry remediation *pointers*, never changes. Sectum AI
  never modifies the system under test.
- **Provide runtime protection.** It is not a firewall, a guardrail, or a proxy.
  It runs verification campaigns; it does not sit in a request path.
- **Discover or classify data.** It plants and tracks its own synthetic markers;
  it does not scan or catalogue real customer data.
- **Certify compliance.** Control mappings (SOC 2, ISO 27001, GDPR, and the
  rest) are assertions of *test coverage*, not legal certification.

## Trust boundaries

A verification run crosses these boundaries:

1. **Operator → Sectum AI.** The operator runs the `sectum-ai` CLI. The CLI is
   trusted to generate the substrate and execute probes deterministically. The
   `substrate.json` it later reads is *not* covered by that trust: `probe` loads it from
   disk, and the party preparing a pack for an auditor is the party that supplies it. A
   substrate in which no marker is foreign to any principal makes every clean result a
   property of the substrate rather than of the stack, so `probe` refuses one (exit `3`)
   instead of producing a genuine, signable record of nothing.
2. **Sectum AI → the system under test.** Sectum AI connects through adapters.
   Adapters resolve credentials from the environment or a secret manager — never
   from inline configuration. `sectum-ai.yaml` holds references, not secrets.
3. **Sectum AI → the evidence consumer.** An auditor or DPO receives an evidence
   pack and verifies it with `sectum-ai verify`, independently of Sectum AI.
4. **A record → the report about it.** `verify`, `diff`, `score`, `pack` and `probe` all
   report on a record they did not necessarily produce — re-grading a vendor's record is
   the point, and `probe`'s own substrate comes off disk (boundary 1) — so every string a
   record carries (`run_id`, probe ids, finding ids, metric names, embedding-model names,
   `schema_version`) is untrusted input by the time it reaches our output. It is escaped
   at the point of rendering (`sectum_ai.spec.untrusted`), because a newline in it
   otherwise forges whole lines of Sectum's own reporting and an ANSI escape rewrites the
   reader's terminal. Signing does not help here: the vendor is the signer, so a validly
   signed pack carries whatever its author put in those fields.

## Assets

### The ground-truth manifest

The manifest records which marker belongs to which tenant. It is the substrate's
sensitive core: an adversary holding it knows every canary in advance.

- The manifest is a pure function of the scenario seed
  ([ADR-0003](adr/0003-deterministic-substrate.md)), so it is reproducible
  rather than stored as a long-lived secret.
- Its canonical hash is bound into every evidence pack, so the test condition is
  provable after the fact.
- The full manifest is **not** embedded in the evidence pack by default — only
  its hash. This keeps the sensitive ground truth out of an artifact that
  travels to auditors.
- At rest, the seeded substrate (which holds the manifest, and the planted
  canary plaintexts that also appear in the corpus) can be encrypted: set
  `security.manifest_key_env` and `sectum-ai seed` seals it with AES-256-GCM under
  a key referenced from the environment. Recommended for BYOC, where the
  substrate persists on a customer machine.

### Evidence packs

An evidence pack is tamper-evident. The pack's `attested_digest` covers the whole
attested content — the canonical run (findings included) together with the
manifest binding and the audit-PDF reference; that digest is what gets
timestamped, and `sectum-ai verify` recomputes it and rejects any pack whose
attested content was altered.

The development-default timestamper (`LocalTimestamper`) records a digest and a
wall-clock time; it is **not** an external anchor and is not cryptographically
binding on its own. Production runs configure an RFC 3161 Time-Stamp Authority
and a Sigstore Rekor transparency log. What an anchor proves is that *this* digest
existed at the TSA's attested time (and, for Rekor, was logged). It does not stop
an adversary from editing a pack, recomputing the digest, and obtaining a fresh
anchor — that pack will also verify. The tamper evidence is comparative: a reader
holding the original digest or timestamp, or the Rekor log's history, sees that
the re-anchored pack is a *different, later* record. `verify` alone does not
detect that; it checks the pack it is handed.

### Customer data

Sectum AI is synthetic by default — the substrate is fabricated. When pointed at
a real stack, the probes read whatever that stack returns. In **BYOC** mode the
CLI runs inside the customer environment and only markers, the evidence spans of
findings, and the timestamped evidence pack leave it; the bulk of retrieved
content stays on-box. Note that **unverified** findings ship too, and an evidence
span can be the judge's own free-text rationale, which may restate observed tenant
content — so the egress is "the findings' spans", not "confirmed spans only". (The pack is hash-bound and
timestamped; it is signed by a TSA only when one is configured.)

## Deployment modes

- **Hosted.** Sectum AI runs the synthetic tenants against the customer's
  reachable endpoints.
- **BYOC (bring-your-own-cloud).** The customer runs the CLI inside their own
  environment. Only the substrate's markers, the findings' evidence spans (which
  can include a judge rationale restating observed content — see *Customer data*
  above), and the hash-bound, timestamped evidence pack cross the boundary. Set `detection.mode: local` to **enforce** this posture:
  detection is the only stage that embeds or judges tenant content, and in
  `local` mode the config fails fast on any embedder or judge that would call a
  default hosted AI API (`openai`/`anthropic` without a `base_url`) — so Sectum
  makes no call to a third-party AI service. A `base_url` you configure is
  trusted to resolve to an endpoint inside your own boundary (a local or in-VPC
  server); that target is your trust boundary, not Sectum's.

## What Sectum AI does not defend against

- A compromised operator environment. If the machine running the CLI is
  controlled by an adversary, the substrate and the manifest are exposed.
- A timestamper or transparency log that is itself dishonest. Evidence integrity
  is only as strong as the configured anchor (see *Evidence packs* above).
- Vulnerabilities in the system under test beyond multi-tenant isolation.
  Sectum AI tests one property; it is not a general-purpose scanner.

## Reporting a vulnerability in Sectum AI

See [SECURITY.md](https://github.com/sectum-ai/sectum-ai/blob/main/SECURITY.md).
Do not open a public issue for a security vulnerability in Sectum AI itself.
