# Backlog

Planned / on-hold work items, ahead of any public commitment. Not published, no
build or test gate (see `internal/README.md`). Newest first.

---

## `RunResult` cannot grow a field without breaking every pack already issued

**Status:** a constraint to design around, not a task. Recorded because it is invisible
until it bites, and it cost a designed-and-reverted change in the PR #252 review loop.

`canonical_hash` serializes with `model_dump(mode="json")` — every field, defaults
included — so **adding any field to `RunResult` (or `RunMetrics`) changes the canonical
form of every record that already exists**, including ones written by older versions. The
digest changes; the RFC 3161 token and Rekor entry over the old digest no longer match;
and `verify` reports **"the timestamp token attests a different digest; the evidence pack
was altered"** — accusing an untouched pack of tampering. `tests/invariants/
test_sample_packs_verify.py` is the guard that catches this (it did), because the shipped
sample packs carry real anchors.

Consequences for anyone adding a field here:
- It is a **breaking** change for existing evidence, not an additive one, whatever the
  pydantic default says. It needs a `SCHEMA_VERSION` minor bump so the version gate
  rejects old packs honestly ("verify with a matching sectum version") rather than
  libelling them — and old packs then need the old verifier.
- `exclude_none` / `exclude_unset` is not an escape: changing canonicalization changes
  every digest too.
- So weigh the field against that cost. The reverted case: a `principal_count` on
  `RunResult` so `score` could refuse a run that crossed no boundary. It was dropped
  because the record is **self-reported** — a vendor whose substrate held one principal
  simply writes `4` and the guard waves it through, and an older honest record carries no
  count at all. It bought nothing that `probe`'s refusal does not already give at the
  source, and would have broken every pack in the wild to buy it.

---

## Full OWASP LLM08:2025 coverage — wire Class 13 into the `owasp-llm08` framing

**Status:** on hold — blocked on multi-modal retrieval wiring.

**Context.** Class 13 (`multimodal-rag-bleed`) carries `owasp_llm = "LLM08:2025"`, so it
*is* an OWASP LLM08 (Vector & Embedding Weaknesses) probe. But it is measured by its own
image-embedding sweep (`multimodal_provider_sweep`) and is deliberately **not** in the CLI
`_build_suite` — a text vector store cannot embed images, so running it in the generic
suite would be meaningless. Because of that, it is also not in the `owasp-llm08` SKU
suite (`packages/core/src/sectum_ai/suites.py`).

To keep the attestation honest (the whole product thesis), the review of PR #250 reworded
the SKU claim from "every adversarial probe in the catalog" to **"every adversarial probe
in the default CLI suite"** and noted that the multi-modal check runs via its own sweep
(`docs/skus.md`, `suites.py` description). That carve-out is correct today but is a
framing gap: the `owasp-llm08` SKU no longer covers *every* LLM08 probe.

**Goal.** Make the `owasp-llm08` SKU genuinely cover **all** LLM08 probes, including
Class 13, so "Full OWASP LLM08:2025 coverage" is restorable.

**Blocked on (the real follow-on already noted in the class-13 doc + CHANGELOG):**
1. A live (and/or in-memory `fake-multimodal`) multi-modal vector-store adapter that can
   embed images, exposing a `multimodal_retrieval` capability.
2. Generic-suite / CLI wiring: add `MultimodalRagBleedProbe` to `_build_suite` gated on
   that capability (the `requires_any_capability` / `_skip_inapplicable` precedent, e.g.
   LoRA-vs-vLLM), so it runs under `sectum-ai probe` when a multi-modal store is
   configured and skips (honestly) otherwise.

**On completion:**
- Add `multimodal-rag-bleed` to the `owasp-llm08` suite's `probe_ids` (`suites.py`).
- Restore the fuller framing in `suites.py` + `docs/skus.md` ("every adversarial probe" /
  "Full OWASP LLM08:2025 coverage") once the SKU actually runs Class 13.
- Update `docs/coverage.md` (the Class 13 row) to reflect that it runs in the suite.

**Do NOT** restore the "full coverage" wording before the wiring lands — that would
re-introduce the exact overclaim the PR #250 review caught.
