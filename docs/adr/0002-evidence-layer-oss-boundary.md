# ADR-0002 - The evidence layer is fully open source

## Status

Accepted (2026-05-16).

## Context

Sectum AI's second product anchor (the engineering spec, section 1.3) is auditor-acceptable,
tamper-evident evidence. The `sectum-ai-evidence` package has four planned
modules: `chain.py` (canonicalize, hash, RFC 3161 timestamp, Sigstore Rekor),
`verify.py` (the `sectum-ai verify` command), `controls.py` (compliance control
mappings), and `pdf.py` (the audit-pack renderer).

A delivery question had to be settled: which of these are open source in the
public monorepo, and which belong in the private `platform` repository?

## Decision

The entire evidence layer is open source in the public monorepo. All four modules
ship under Apache-2.0.

- **`verify.py` — open source.** The engineering spec, section 8.2 requires that third parties
  can independently verify an evidence pack. An attestation that only the vendor's
  tool can check is worthless; independent verification is the point.
- **`chain.py` — open source.** The BYOC deployment mode (section 5, shipping in
  v1) runs the chain on the customer's own machine and lets only signed evidence
  leave; the construction code must therefore be in the distributed CLI. An open
  verifier also necessarily reveals the canonicalization algorithm.
- **`controls.py` — open source.** The control-mapping table (the engineering
  spec, section 18) is implemented here in the evidence package and ships in the
  open CLI, so a third party can read exactly which controls each finding
  asserts. Publishing the mappings is the category-authority play.
- **`pdf.py` — open source, built with a pluggable theme.** The open-source
  default theme renders a complete, substantively full, verifiable document. The
  private `platform` repository supplies a branded theme asset only.

## Principle

In an attestation business the moat is being the trusted, independent operator —
hosted attestation, calibration data, scenario libraries, the engagement — not
the code that builds the artifact. Openness of the evidence layer strengthens
auditor trust rather than giving away defensible value.

## Consequences

- `packages/evidence` is scaffolded whole in the public monorepo.
- When `pdf.py` is implemented (Phase 3), it must take a theme or template as
  input, so the branded pack is an asset swap rather than a code fork.
- An open-source evidence report must never be substantively crippled: the
  open-source versus paid difference is branding and the independent-operator
  framing, never the findings, control mappings, methodology, or verification
  instructions.
- The private `platform` repository retains attestation hosting and the public
  registry, the branded theme, scheduling, the dashboard, regression-baseline
  history, and enterprise pinned or private TSA and Rekor.
