# ADR-0006 - The isolation boundary is a principal (tenant or user), not only a tenant

## Status

Accepted (2026-05-20).

## Context

The engineering spec's first anchor (section 1.3) frames Sectum AI as
*multi-tenant* AI verification: "tenant A's data cannot reach tenant B." The
whole substrate models `SyntheticTenant`s, markers are owned by tenants, and
every probe runs from a tenant's session.

But the same leakage exists *within* a single tenant, between its **users**: a
RAG deployment where employee A retrieves employee B's private HR documents,
per-user agent memory bleeding across colleagues, a semantic cache serving one
user's answer to another. Mechanically these are identical to the cross-tenant
classes — only the isolation boundary is finer. Our named competitor DeepTeam
already models both (`CrossContextRetrieval(types=["tenant","user"])`).

Two facts shape the decision:

1. **The mechanism is identical at both granularities.** A marker is owned by
   some identity and observed in some session; a leak is the owner identity not
   matching the observing identity. The detection pipeline, the marker types,
   and the surfaces do not care whether that identity is a tenant or a user.
2. **The invariant is *not* identical.** Tenant isolation is an absolute
   invariant — zero cross-tenant, always, no configuration. User isolation is
   *policy-relative*: within a tenant, sharing is often intended (team
   workspaces), so verifying it requires knowing the *intended* access policy.
   That makes user-level verification meaningfully more product surface (an
   intended-vs-actual access model), not a relabel.

There is also a go-to-market asymmetry: tenant isolation is sold to the SaaS
**vendor** (proving tenants don't bleed to their customers); user isolation is
sold to the **enterprise** deploying internal AI (proving employees can't see
each other's data). Different buyers, different motions.

## Decision

Generalize the substrate's identity to a **principal** — a tenant, or a user
within a tenant — additively, while keeping positioning and the wedge
tenant-first:

- The spec gains `PrincipalKind` (`tenant`/`user`), a `Principal` value model
  (`tenant_id` plus optional `user_id`), `SyntheticUserSpec`,
  `SyntheticTenantSpec.users`, `Marker.owner_user_id`, and
  `Substrate.principals()`. All new fields default to the tenant-level case, so
  every existing model, probe, adapter, test, and the demo are byte-for-byte
  unchanged.
- The substrate distributes a tenant's markers across its declared users
  (round-robin) when users are present; a tenant with no users behaves exactly
  as before.
- Category, README, and the GDPR Article 17 wedge stay **tenant-first**. This is
  a widening of anchor 1, recorded here per the spec's operating rule to flag
  drift (section 1.2) — not a repositioning.

User-level **detection, probing, and CLI runs are deferred** to a later phase.
Threading a `user_id` through `ProbeStep`/`Finding`/the runner/adapters and
generalizing the detection leak predicate to user granularity is the next step;
the intended-vs-actual access-policy model that true user isolation needs is the
larger, separate piece of work after that.

## Consequences

- The substrate can model users within tenants today and plant per-user
  markers; `Substrate.principals()` enumerates every isolation boundary. This is
  the foundation user-level verification builds on.
- The existing tenant-level pipeline carries zero risk: the change is additive
  with tenant-level defaults, and the reproducibility and zero-false-positive
  invariants still hold.
- The new fields are written by the substrate and read by `principals()` and its
  tests now; the detection pipeline does not yet consume `owner_user_id`. That
  is a deliberate, staged foundation, not dead code — and this ADR is the record
  of the staging.
- Sequencing is governed by the buyer: if the near-term ICP is the SaaS vendor,
  the tenant path stays primary and user-level remains foundational; if pull
  comes from enterprises deploying internal AI, the access-policy model is
  promoted ahead of further breadth.
