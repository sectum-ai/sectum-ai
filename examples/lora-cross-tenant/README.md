# LoRA / adapter cross-tenant influence — Class 9

This example reproduces **Attack Class 9**: cross-tenant influence between
per-tenant LoRA adapters (the engineering spec, §7). The probe trains each
tenant's adapter on a corpus that includes a memorisable `HARD_CANARY`,
then queries every foreign tenant; on a mis-routed or weight-bled stack
the canary surfaces in the *wrong* tenant's inference. The audit pack
itemises the leak: which tenant's canary surfaced under which other
tenant's inference, with the memorised text in the evidence span.

## The attack

A per-tenant fine-tune is supposed to give *that tenant* the
specialisation without ever influencing another tenant's inference. In
practice, two things go wrong:

- **Adapter mis-routing** — the inference router resolves the wrong LoRA
  for the request (e.g., a stale cache, a session-id collision, a tenant
  id parsed from an unauthenticated header). The "wrong" tenant gets
  someone else's memorised content.
- **Weight bleed** — the runtime merges *every* LoRA into a single
  combined model and serves all callers from it (some HuggingFace
  inference servers do this when `merge_and_unload` is misused, or when
  PEFT's adapter switching is bypassed in favour of static merging). Now
  every tenant's memorised canary surfaces in every tenant's inference.

This is **OWASP LLM08:2025** on the model-adapter surface. Real
deployments hit it whenever multi-tenant LoRA-serving stacks (vLLM with
PEFT extensions, TGI, custom orchestration) lose tenant scope on the
serve path.

## What the demo does

`run.sh` runs the canonical CLI flow end to end against the in-memory
`FakeModel` with the deliberately-leaky `adapter_bleed: true` knob (the
condition Class 9 is built to catch):

1. **`sectum-ai seed`** provisions four synthetic tenants and their canary
   markers.
2. **`sectum-ai probe --probe lora-cross-tenant`** trains each tenant's
   adapter on a small corpus that includes the tenant's `HARD_CANARY`,
   then issues a foreign-tenant inference per tenant pair and scans the
   completion for any other tenant's canary. The probe exits `2` when
   it confirms at least one cross-tenant leak — the success signal on
   the leaky demo stack.
3. **`sectum-ai report`** assembles the tamper-evident evidence pack
   (PDF + JSON + in-toto envelope).
4. **`sectum-ai verify`** independently re-checks the pack's integrity.

## Run it

```sh
./run.sh
```

Expect to see cross-tenant findings: one per (owner tenant, observing
tenant) pair where the owner's canary surfaced under the observer's
inference. On the 4-tenant demo with `adapter_bleed: true`, every
inference pulls every adapter, so the count is the full cross-pair set.

## Swap the in-memory model for the live HuggingFace stack

The probe is adapter-agnostic; only the `ModelAdapter` it routes through
changes. The v0.1.0 release added the live `HuggingFaceLoraModel` (PEFT
+ HuggingFace transformers) — point it at a real base model + an
`adapters_dir` and the probe runs against actual LoRA training +
inference.

```yaml
adapters:
  model:
    kind: huggingface
    base_model_id: TinyLlama/TinyLlama-1.1B-Chat-v1.0
    adapters_dir: ./.sectum/lora-adapters
    # adapter_bleed: true   # uncomment to reproduce the leak condition
    lora_rank: 8
    lora_alpha: 16
    train_epochs: 1
    device_map: auto
```

```sh
pip install sectum-ai-adapters[huggingface]
sectum-ai probe --probe lora-cross-tenant --config sectum.yaml --workdir out
```

A real base model on CPU runs slowly (TinyLlama-1.1B takes ~30s per
inference). For a meaningful production probe, point `device_map` at a
GPU and bump `train_epochs` so the canary actually memorises.

## What the report tells you

Each Class 9 finding carries:

- the owning tenant + the observing tenant of the cross-tenant pair
- the leaked canary's marker id + the memorised plaintext
- the `evidence_span` (the slice of the foreign-tenant inference where
  the canary surfaced)
- the surface (`MODEL_ADAPTER`) + OWASP / ATLAS / NIST control IDs
- the remediation pointer: per-tenant adapter routing with auth-scoped
  resolution + a sanity-check that the merged model never serves
  cross-tenant traffic

## What's *not* in this example

- **Real GPU training.** The demo runs against the in-memory fake; the
  live `huggingface` kind exists for that and is the configured on-ramp
  to real-stack probing (see the swap above).
- **Routing-error probes.** Class 9 today detects weight-bleed; the
  routing-failure variant (a tenant id parsed from an unauthenticated
  header) is a future variant the probe interface accepts at the same
  contract surface.
- **Adapter deletion + re-train state.** The `delete` + `soft_delete`
  surface on `ModelAdapter` is exercised by Class 11 (erasure
  verification), not Class 9. See `examples/erasure-attestation/` for
  that walkthrough.
