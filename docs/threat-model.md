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
at both granularities against a store that is — or is not — user-aware. With no
users declared, behaviour is exactly the tenant-level case.

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

1. **Operator → Sectum AI.** The operator runs the `sectum` CLI. The CLI is
   trusted to generate the substrate and execute probes deterministically.
2. **Sectum AI → the system under test.** Sectum AI connects through adapters.
   Adapters resolve credentials from the environment or a secret manager — never
   from inline configuration. `sectum-ai.yaml` holds references, not secrets.
3. **Sectum AI → the evidence consumer.** An auditor or DPO receives an evidence
   pack and verifies it with `sectum-ai verify`, independently of Sectum AI.

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
and a Sigstore Rekor transparency log; a pack anchored that way cannot be
re-timestamped by an adversary.

### Customer data

Sectum AI is synthetic by default — the substrate is fabricated. When pointed at
a real stack, the probes read whatever that stack returns. In **BYOC** mode the
CLI runs inside the customer environment and only markers and the signed
evidence pack leave it; raw retrieved content stays on-box.

## Deployment modes

- **Hosted.** Sectum AI runs the synthetic tenants against the customer's
  reachable endpoints.
- **BYOC (bring-your-own-cloud).** The customer runs the CLI inside their own
  environment. Only the substrate's markers and the signed evidence pack cross
  the boundary.

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
