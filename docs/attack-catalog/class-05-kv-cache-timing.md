# Class 5 — KV-cache timing side channel

**OWASP:** LLM08:2025 · **ATLAS:** — (not an attack technique; a statistical timing side channel) · **NIST:** MEASURE 2.7 · **Surface:** KV cache · **Probe id:** `kv-cache-timing`

## Goal

Detect whether shared inference infrastructure leaks one tenant's prompt content
to another through KV prefix-cache timing.

## Method

Class 5 is a statistical timing test. It warms the cache as one tenant, then, as
another tenant, measures inference latency over many trials for prompts that do
and do not share the warmed prefix.

## Detection

The probe runs a two-sided **Welch's t-test** (unequal-variance) on the primed
vs. control latency samples and reports the t-statistic, the
Welch–Satterthwaite degrees of freedom, the **p-value**, a **95% confidence
interval** on the mean timing gap, and the standardised effect size (**Cohen's
d**). A pair is a confirmed side-channel finding only when the gap is

- **statistically significant** — p below a Bonferroni-corrected level: 0.01 divided by
  the number of ordered tenant pairs, so 0.01/12 ≈ 0.0008 for the default four-tenant
  scenario (the pack's evidence span states the exact alpha used),
- **practically large** — Cohen's d ≥ 0.8 (above the per-prompt jitter noise
  floor), and
- **directional** — the primed prompt is the faster one (a positive gap),

so a coincidental or wrong-direction gap is not over-claimed (the spec,
section 7). Severity scales with the effect size; the per-pair effect sizes are
recorded in the run metrics, and the finding's evidence span quotes the full
test result (means, gap, CI, t, df, p, d) for the auditor.

The statistics are pure standard library — the Student's t survival function via
the regularized incomplete beta function, the CI critical value via bisection —
so the probe adds no SciPy/NumPy dependency (the spec, section 13).

## Status

Implemented in Phase 5. Like the Class 11 erasure probe, Class 5 is a
statistical workflow with its own entry point rather than a plan/detect probe.

## Backends and limitations

The probe can only observe a side channel the backend actually exposes. It needs
a model endpoint whose latency reflects a **prefix cache shared across
principals** — the hosted, multi-tenant inference setting this attack targets.
Run against a single-process or per-tenant-isolated backend (the local
HuggingFace LoRA adapter, or `FakeModel(prefix_cache=False)`) there is no shared
cache to leak through, so the probe reports no significant timing gap **by
construction**. That absence is *not* evidence of isolation on a shared backend —
it only means this backend has no shared prefix cache to measure. Point Class 5
at the same shared inference tier your tenants actually use.
