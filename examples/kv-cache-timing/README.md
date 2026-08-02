# KV-cache timing side channel — Class 5

This example reproduces **Attack Class 5**: the KV-cache prefix-cache
timing side channel (PROMPTPEEK-class). A shared inference
infrastructure that warms a KV prefix cache returns a prompt faster
when its prefix was recently processed by another tenant; the
*difference in latency* is a side channel that lets the second tenant
infer what the first tenant recently asked.

## The attack

Inference servers (vLLM, TensorRT-LLM, llama.cpp, hosted provider
endpoints) maintain a KV cache to avoid re-encoding the same prompt
prefix twice. When the cache is shared across tenants — and most are,
by default, because the engine has no concept of tenancy — a prompt
that shares a prefix with another tenant's recent prompt returns
measurably faster. The timing gap is the side channel: an attacker
who can issue prompts and measure their TTFT can infer the *prefix
content* of a victim tenant's prompts, even when the response itself
is scoped correctly.

This is **OWASP LLM08:2025** on the inference-engine surface, with a
side-channel extension. Published work calls it PROMPTPEEK. Real
deployments leak through it whenever vLLM-style prefix caching is on
without per-tenant scoping; provider-side prompt-caching offerings
(OpenAI, Anthropic) inherit the same shape when the cache is shared
across customers.

## What the demo does

`run.sh` runs the canonical CLI flow end to end. Class 5 is
*statistical* rather than plan/detect: the probe runs **24 trials per
condition per (owner, observer) tenant pair** — 24 with a primed prefix
(the cache-hit condition) and 24 with an unrelated control prefix (the
cache-miss baseline), so 48 timed prompts per pair — then runs a
two-sided **Welch's t-test** on the two latency distributions and
reports the t-statistic, degrees of freedom, p-value, a 95% confidence
interval on the gap, and Cohen's d.

The two conditions are **interleaved**, alternating which is timed
first, rather than measured as two blocks. Anything that drifts during
a run — thermal throttling, CPU frequency scaling, a noisy neighbour —
would otherwise land entirely on whichever block ran second and read as
a timing gap. Alternating makes the two conditions' mean measurement
positions equal, so a linear drift cancels instead of masquerading as a
side channel.

1. **`sectum-ai seed`** provisions four synthetic tenants (Acme, Globex,
   Initech, Hooli) and their canary markers.
2. **`sectum-ai probe --probe kv-cache-timing`** runs the timing trials
   against the demo config's fake model with `prefix_cache=true`
   (the leaky condition Class 5 is built to catch). A finding is
   confirmed only when the timing gap is **statistically significant**,
   **practically large** (Cohen's d ≥ 0.8), and **directional** (the
   primed prefix is faster) — the spec §7 "avoid over-claiming" bar.
   Significance is judged at a **Bonferroni-corrected** level: the run
   performs one t-test per ordered tenant pair, so the per-pair bar is
   `0.01` divided by the number of comparisons, which holds the
   *family-wise* false-positive rate at 0.01 rather than letting 0.01
   leak once per pair. On this demo's four tenants that is 12
   comparisons, so a pair must clear **p < 0.00083**. The probe exits
   `2` when it confirms at least one side channel — the success signal
   on the leaky demo stack.
3. **`sectum-ai report`** assembles the tamper-evident evidence pack
   (PDF + JSON + in-toto envelope). The audit-pack PDF carries the
   per-pair t-statistic, p-value, confidence interval, effect size,
   and primed/control means so a reviewer can sanity-check the
   statistical strength themselves.
4. **`sectum-ai verify`** independently re-checks the pack's integrity.

## Run it

```sh
./run.sh
```

Expect to see one timing finding per cross-tenant pair (12 pairs in
the default 4-tenant scenario). The headline metric on page 1 of the
PDF is the count of pairs that cleared the significance gate.

## What the report tells you

Each Class 5 finding carries:

- the owning tenant + the observing tenant of the timing pair
- the primed-prefix mean latency (cache-hit condition) in ms
- the control-prefix mean latency (cache-miss baseline) in ms
- the Welch t-statistic, degrees of freedom, and p-value
- the 95% confidence interval on the timing gap, and Cohen's d
- the surface (`KV_CACHE`) + OWASP / ATLAS / NIST control IDs the
  finding maps to

The remediation pointer in the finding row names the standard
counter-measure: per-tenant prefix-cache scoping (vLLM 0.5+'s
`tenant_id` keying), or disabling the prefix cache entirely on
shared deployments.

## What's *not* in this example

- **A real inference server.** The demo runs against the in-memory
  `FakeModel` with the deliberately-leaky `prefix_cache=true` knob.
  Real engagements point at a vLLM / TensorRT-LLM / hosted
  provider via the `ModelAdapter` interface — the new live
  `huggingface` kind covers the local PEFT case, and a hosted-API
  adapter is the next surface the spec calls for.
- **A statistical baseline against load.** A noisy production
  endpoint may swamp the signal even when the cache is leaky; the
  probe's 24 trials + (p < 0.01, d ≥ 0.8) gate is calibrated for the
  in-memory fake's clean noise floor. Production runs warrant more
  trials and a re-baselined threshold.
- **Mitigation of the side channel.** Sectum verifies and attests;
  Class 5 findings point at the remediation, but the engineering
  team owns the prefix-cache scoping change in production.
