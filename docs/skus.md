# SKUs and probe suites

Sectum AI ships as an Apache-2.0 **open-source core** plus a paid **Sectum
Cloud**. The seam between them is the shared, independently verifiable evidence
format: anything the OSS CLI runs produces a pack that `sectum-ai verify` checks,
and Cloud adds hosting, scheduling, the dashboard, and branded packs on top of
that same format.

Prices are not listed here (they change independently of the code) — see
<https://sectum.ai/pricing>. This page is the **SKU → code map**.

## The four SKUs

| SKU | What it proves | How you run it | Edition |
|---|---|---|---|
| **Erasure Attestation** (the wedge) | A churned tenant's data has actually left every configured AI surface after a GDPR Article 17 request | `sectum-ai erasure --target-tenant …` (Class 11) → DPO-facing PDF + signed `evidence.json` | OSS CLI; Cloud hosts + schedules |
| **SOC 2 Tenant Isolation Evidence Pack** | Logical separation, boundary, and segregation between tenants hold across the AI surfaces | `sectum-ai probe --suite soc2-tenant-isolation` → control-mapped pack | OSS CLI; Cloud + auditor channel |
| **Continuous Multi-Tenant Verification** | Isolation still holds release over release (no regression) | `sectum-ai probe` (full) + `sectum-ai baseline` / `sectum-ai diff`, scheduled | Cloud (scheduled runs + dashboard); OSS runs it one-shot |
| **Open Sectum** | — (the substrate, attack catalog, adapters, and `verify`) | the `sectum-ai` CLI | OSS, free (Apache-2.0) |

The first three are revenue SKUs; **Open Sectum** is the free core that makes the
evidence independently verifiable and serves as category authority and lead-gen.
Build order follows revenue: erasure wedge → continuous → SOC 2 channel.

## Named probe suites

A *suite* fixes a probe set plus the compliance frameworks it speaks to, so you
run a named, control-mapped subset instead of hand-picking probes:

| `--suite` | Probes | Frameworks |
|---|---|---|
| `soc2-tenant-isolation` | the direct cross-tenant isolation checks: tenant-boundary, RAG entity/pipeline bleed, semantic-cache, agent tool/framework hijack, memory, embedding-inversion, LoRA, KV-cache timing | SOC 2 CC6.1 / CC6.6 / CC6.7, ISO 27001 A.8.3 / A.8.12 |
| `owasp-llm08` | every adversarial probe in the catalog | OWASP LLM08:2025, NIST AI RMF MEASURE 2.7 |

```sh
# A SOC 2 tenant-isolation evidence pack:
sectum-ai seed   --workdir .sectum-ai
sectum-ai probe  --workdir .sectum-ai --suite soc2-tenant-isolation
sectum-ai report --workdir .sectum-ai
sectum-ai verify .sectum-ai/evidence.json --allow-unanchored
```

`sectum-ai probe` with no `--suite` runs the full catalog (the
continuous-verification default). The GDPR erasure SKU is the separate
`sectum-ai erasure` workflow, not a probe suite. Suite definitions live in
[`sectum_ai.suites`](https://github.com/sectum-ai/sectum-ai/blob/main/packages/core/src/sectum_ai/suites.py),
and their probe sets are validated against the live catalog in CI.

## Deployment modes

- **Hosted** — Sectum runs the synthetic tenants against your reachable
  endpoints.
- **BYOC (bring-your-own-cloud)** — the CLI runs inside your environment; only
  the markers, the configuration, and the signed evidence leave the box (see the
  [threat model](threat-model.md)).
