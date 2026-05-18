# Security Policy

Sectum AI is a security product. We hold our own code to the standard we ask of
the systems we verify. Thank you for helping keep Sectum AI and its users safe.

## Reporting a vulnerability

**Do not open a public issue, pull request, or discussion for security
vulnerabilities.** Public disclosure puts users at risk.

Report privately, by either route:

- Email **security@sectum.ai**. Encrypt sensitive reports with our PGP key.
  PGP key fingerprint: `0000 0000 0000 0000 0000  0000 0000 0000 0000 0000`
  (Phase 0 placeholder — the production key will be published here and at
  `https://sectum.ai/.well-known/security.txt`).
- Or use GitHub's private vulnerability reporting on this repository
  ("Report a vulnerability" under the **Security** tab).

Please include: the affected version or commit, a description of the issue,
steps to reproduce, and any proof-of-concept. Do not include real customer data.

## Our commitment

| Stage | Target |
|---|---|
| Acknowledge receipt | within **24 hours** |
| Initial triage and severity assessment | within **72 hours** |
| Coordinated disclosure | within **90 days** of triage, sooner where possible |

We will keep you informed throughout, credit you in the advisory unless you
prefer to remain anonymous, and agree a disclosure timeline with you.

## Supported versions

Sectum AI is pre-release. Until the first stable release, only the `main`
branch receives security fixes.

| Version | Supported |
|---|---|
| `main` (pre-release) | Yes |
| Tagged releases | Not yet — no stable release exists |

This table will be updated when the first stable version ships.

## Scope

In scope: the packages in this repository — `sectum-ai`, `sectum-ai-spec`,
`sectum-ai-probes`, `sectum-ai-adapters`, `sectum-ai-evidence` — and the
evidence-chain verification path (`sectum verify`).

Out of scope: third-party dependencies (report those upstream), and any system
that Sectum AI is *pointed at* during a verification run — those belong to their
own owners and operators.

## Safe harbor

We will not pursue or support legal action against good-faith security research
that respects this policy: research that avoids privacy violations, data
destruction, and service degradation, and that gives us reasonable time to
remediate before public disclosure.

## Threat model

The Sectum AI threat model — trust boundaries, handling of the ground-truth
manifest, and what is explicitly out of scope (no remediation, no runtime
protection) — will be published at `docs/threat-model.md`, planned for Phase 4
of the build plan (the engineering spec, section 14). Until then, this policy is the
authoritative security contact.
