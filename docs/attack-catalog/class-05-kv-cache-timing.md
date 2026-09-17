# Class 5 — KV-cache timing side channel

**OWASP:** LLM08:2025 · **ATLAS:** — (not an attack technique; a statistical timing side channel) · **NIST:** MEASURE 2.7 · **Surface:** KV cache · **Probe id:** `kv-cache-timing`

## Goal

Detect whether shared inference infrastructure leaks one tenant's prompt content
to another through KV prefix-cache timing.

## Method

Class 5 is a statistical timing test. It warms the cache as one tenant, then, as
another tenant, measures inference latency over many trials for prompts that do
and do not share a warmed prefix. The owner warms one prefix **per trial**, and
each is measured exactly once, by one arm: on a backend whose latency call runs
inference (the HuggingFace adapter), the observer's own first trial would
otherwise warm a single shared prefix — and the control prefix — for every later
trial, leaving both arms as cache hits and the side channel visible in one trial
of twenty-four. The control prefix is fresh per trial and never warmed by anyone.
Which arm is measured first is **shuffled**, from a seed derived from the tenant
pair, and stays balanced twelve-and-twelve so the two arms' mean measurement
positions are equal. A fixed alternation put each arm on a fixed pair of
positions modulo four, and behind a four-way round-robin dispatcher — where the
replica *is* the call index modulo four — the arms sat on disjoint replicas, so
any spread across the pool read as a side channel on a backend with no cache.
Each prefix opens with a 20-character key (a hash of the tenant id, so two
low-valued ids do not share it) and continues with filler spanning several full
16-token blocks: a block-granular cache such as vLLM's automatic prefix caching
hashes whole blocks and never a partial one, so a short prefix could not produce
a single hit and the probe recorded a PASS against a backend with a shared cache.

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
- **directional** — the primed prompt is the faster one (a positive gap), and
- **resolved** — the pair was actually measured. A backend whose latency metric
  returns one constant makes all 48 readings identical, which is arithmetically
  indistinguishable from a careful null result; such a pair is marked unresolved,
  kept out of the signed metrics, and the class reads `NOT_COVERED` rather than
  passing a check that could not have found anything.

so a coincidental or wrong-direction gap is not over-claimed (the spec,
section 7). Within-arm variances are floored at the timer's resolution (about a
microsecond), so a jitter-free backend — zero spread, a constant gap — is the
cleanest side channel rather than an undefined test: it used to yield an infinite
t with zero degrees of freedom, read as p = 1, and no finding. Severity scales
with the effect size; the per-pair effect sizes are
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
