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

Sectum AI is pre-alpha. Until the first stable release, only the `main`
branch receives security fixes.

| Version | Supported |
|---|---|
| `main` (pre-alpha) | Yes |
| Tagged releases | Not yet — no stable release exists |

This table will be updated when the first stable version ships.

## Scope

In scope: the packages in this repository — `sectum-ai`, `sectum-ai-spec`,
`sectum-ai-probes`, `sectum-ai-adapters`, `sectum-ai-evidence` — and the
evidence-chain verification path (`sectum verify`).

Out of scope: third-party dependencies (report those upstream), and any system
that Sectum AI is *pointed at* during a verification run — those belong to their
own owners and operators.

## Release artifact integrity

The canonical, signed source of every Sectum AI distribution is the official
PyPI release plus its matching GitHub Release. Both are produced by the
[release pipeline](docs/RELEASING.md):

- **PyPI** publishes via Trusted Publisher (OIDC). The repository holds no
  long-lived publishing token.
- Every sdist, wheel, and CycloneDX SBOM is signed by Sigstore using the
  release workflow's short-lived OIDC identity. The `.sigstore` bundles are
  attached to the GitHub Release for the same tag.
- A consumer verifies an artifact with `cosign verify-blob` against the
  workflow identity; the exact recipe is in
  [docs/RELEASING.md](docs/RELEASING.md#verifying-a-released-artifact).

A distribution that does not have a matching Sigstore bundle on the GitHub
Release for its tag is not an official Sectum AI release. Report any such
artifact to `security@sectum.ai`.

## Safe harbor

We will not pursue or support legal action against good-faith security research
that respects this policy: research that avoids privacy violations, data
destruction, and service degradation, and that gives us reasonable time to
remediate before public disclosure.

## Threat model

The Sectum AI threat model — trust boundaries, handling of the ground-truth
manifest, and what is explicitly out of scope (no remediation, no runtime
protection) — is documented in [`docs/threat-model.md`](docs/threat-model.md).
