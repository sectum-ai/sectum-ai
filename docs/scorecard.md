# Isolation scorecard

`sectum-ai score` grades a run's multi-tenant isolation posture: one letter (A–F), its
confidence, and a per-class breakdown.

```sh
sectum-ai seed   --workdir .sectum-ai
sectum-ai probe  --workdir .sectum-ai
sectum-ai score  --workdir .sectum-ai           # or: --output json
```

```
# illustrative: the structure is exact, the figures are from one demo run
Multi-tenant isolation: GRADE F   (confidence: high - 10/11 classes covered)
  run run-sectum-ai-demo-2026 (.sectum-ai/run.json)
  record 3b4338ec5a375e02 (sha256, the run identifier)
  scope: Sectum's built-in SYNTHETIC stack - this grade describes no
         production system (no live adapter on any surface)
  capped by a failing critical-band class

  Class  1  Direct tenant boundary fetch    FAIL        critical
  Class  2  Organic entity-bleed RAG        FAIL        critical 12.5% RPR (95% CI 5.9%-24.7%, n=48)
  ...
  Class 13  Multi-modal RAG entity-bleed    NOT_COVERED critical probe did not run - ...

  Methodology: docs/scorecard.md (v1.2) - weighted 0.00 over the covered classes; coverage 0.88.
  Untested classes lower confidence, never the grade.
```

The grade is **derived, not asserted**. Every input is the
[`RunResult`](data-models.md) — `probe_versions` (what actually ran), `findings`, and
`metrics` — so anyone holding the run (`run.json`, or an `evidence.json` pack, which
`score` also accepts and unwraps) recomputes the letter with this page's rules rather
than trusting it.

The `record` line is the SHA-256 of the graded record — the same
[run digest](evidence-chain.md) the in-toto attestation and the audit PDF bind, and it
differs for every run. It is there because `run_id` cannot identify a record: `run_id` is
derived from the scenario, so every run against one substrate repeats it, and two records
that grade `F` and `A` can carry an identical `run_id`. The digest says *which* record
earned this letter, and a third party recomputes it from the record they hold.

Where the record states both a rate and the counts behind it, the counts win: Class 2's
headline is recomputed from `retrieval_pivot_k`/`_n` rather than read from the
`retrieval_pivot_rate` and interval the record asserts about itself. Relaying an asserted
interval faithfully would let a doctored record print a far-too-tight interval as fact,
which reads to an auditor exactly like one we invented. Counts that cannot be true
(`k > n`) are refused rather than fallen back on, so a record cannot opt out of the
recompute by corrupting them.

On a run with some live surfaces, a class backed by both a live surface and a
built-in fake is graded on the live surface's findings only: a confirmed finding
on the fake is withheld (the class note says how many), so a leaking fake vector
store beside a clean live RAG pipeline no longer fails Class 2 — the OSCAL and the
JSON summary for the same record already said no leak was confirmed on a live
surface. The Retrieval-Pivot Rate follows the same rule: on a mixed run it is
computed over the live surfaces' query steps only. A finding's surface maps to
the adapter that produced it (a KV-cache timing finding rests on the model
adapter), so those findings count against a live model adapter everywhere.

`probe` refuses a substrate in which **no marker is foreign to any principal** (exit `3`),
so no such run reaches the scorecard. It likewise records no run at all when every
selected probe was skipped or planned nothing (exit `3`), and `report` refuses a run
that names no probe and no finding: a record that asked the stack nothing is not
something to sign. That is the precondition of the whole exercise:
isolation is a claim about a boundary *between* principals, so where nothing is foreign to
anybody no probe can surface a leak however broken the stack is, and every class would read
clean as a property of the substrate rather than of the stack — the same deliberately-leaky
demo stack that grades `F` on four tenants grades `A` on one.

The guard asks that question directly rather than counting principals, because the count is
only a proxy for it and the gap between the two is where the bad grades live: a tenant with
one user has *two* principals but no boundary (a tenant owns its users' data), and any
number of principals still verifies nothing if no marker was planted. That second shape is
the more dangerous one — the probes do run and do query, so Class 2 reports a well-powered
`0.0% RPR (95% CI 0.0%-13.8%, n=24)` on a question that could never have had an answer.

The guard is at `probe` because that is where it can be enforced on evidence. The run
record is self-reported, so a count carried inside it would be worth nothing against a
record that lies, and `scenario_hash` pins *which* substrate without saying what was in it.
A grade therefore rests on the substrate being sound — check the scenario, not just the
letter. `score` grades `run.json`, falling back to `evidence.json` when only the pack is present
(`run.json` wins when both exist: `probe` rewrites it unconditionally, while the pack is
only as fresh as the last `report`, so preferring the pack could grade a stale record and
flatter the letter). It prints the `run_id` and path it graded. `score` does not itself
check the pack's signature: run [`sectum-ai verify`](evidence-chain.md) for that, then
`score` to re-derive the letter from the verified record. The methodology revision (`methodology_version`) is
stamped on every scorecard, so a recompute uses the same rules and lands on the same
letter.

## The six honesty rules

This page exists because a single letter is the easiest place in the product to
over-claim. Six rules prevent it:

1. **A class that did not run can only ever be `NOT_COVERED` — never `PASS`.** A grade
   must never imply the stack passed a check it was never asked to perform. Untested
   classes are excluded from the grade entirely. (The scorecard analogue of the Class 11
   [coverage block](attack-catalog/class-11-erasure.md).)
2. **Untested classes lower *confidence*, not the grade.** Coverage is reported beside
   the letter and never folded into it: a run that exercised three classes and one that
   exercised eleven can both grade `A` — the confidence is what tells them apart.
3. **The worst failing class's band caps the letter.** A failing critical-band class can
   never grade above `F`, however many other classes passed. A weighted average must not
   average away a hole.
4. **Every confirmed finding lands in a class, or the run is not graded.** A confirmed
   finding is itself proof its probe ran, so it fails its class even if the run's
   `probe_versions` bookkeeping disagrees — re-grading a record you did not produce is
   the whole point, so the record's *findings* are the authority on what leaked, not its
   bookkeeping. A confirmed finding this catalog cannot attribute at all (a probe added
   or renamed without updating the catalog) makes `score` **refuse** (exit 3) rather than
   silently drop a leak.
5. **A letter states which stack it is about.** Sectum falls back to an in-memory fake
   for every adapter family it cannot reach, so an all-fake run graded `A` at
   `confidence: high` and read exactly like a production pass. Every scorecard now
   carries a **scope**, derived from the run's signed `surface_provenance`:

   | Scope | When | Effect on the grade |
   |---|---|---|
   | `synthetic_stack` | No surface was live | Still graded — the run is unambiguously the demo (the quickstart configures no adapters — see [coverage](coverage.md)) — under a scope line naming the synthetic stack. |
   | `configured_stack` | At least one surface was live | Any class whose probes **all** ran against fakes is `NOT_COVERED` and drops out of the letter. |
   | `unrecorded` | The run predates `surface_provenance` | Graded as before; the scope says its subject cannot be established. |

   The asymmetry is deliberate. A run with nothing live is a demo. A run with *some*
   live surfaces was an attempt at a real assessment, and its remaining fakes are
   silent gaps the operator believes were covered — so only there is a synthetic-backed
   class withheld. A fake's verdict is neither assurance nor fault: a pass against it
   proves nothing about production, and a leak from it is not the operator's bug. Those
   findings are still counted and named on the class line (rule 4 forbids dropping them
   silently); they simply do not move the letter.
6. **A class graded against an unaccountable surface is `NOT_COVERED`.** Each probe's
   adapter slot normally speaks for a known surface, but an adapter declares its own —
   an application's resource API can fill the vector slot — so a run's provenance may
   name a surface this methodology cannot tie to a class. Grading it would assert a
   verdict about a system the scorecard cannot identify, so it fails closed, exactly as
   rule 1 does for a class that never ran. A record carrying no provenance block at all
   (one produced before v0.9.0) is exempt: its absence is not evidence of a mismatch.

## The catalog and its weights

Each class carries a **weight band**: how bad a confirmed cross-tenant leak *in that
class* is. The band is a property of the class, not of a finding — a class needs a weight
even when it passes with no findings.

| Band | Weight | Meaning |
|---|---|---|
| `critical` | 5 | Foreign **content** surfaces through ordinary, benign use — no attacker step. |
| `high` | 3 | A cross-tenant leak that needs an adversarial step, a derived surface, or reconstruction. |
| `medium` | 1 | A statistical side channel that leaks behaviour, not content. |

| Class | Band | Probes |
|---|---|---|
| 1 — Direct tenant boundary fetch | `critical` | `tenant-boundary-fetch` |
| 2 — Organic entity-bleed RAG | `critical` | `rag-entity-bleed`, `rag-pipeline-bleed` |
| 3 — Adversarial RAG poisoning | `high` | `rag-poisoning` |
| 4 — Semantic-cache contamination | `high` | `semantic-cache-contamination` |
| 5 — KV-cache timing side channel | `medium` | `kv-cache-timing` |
| 6 — Embedding inversion | `high` | `embedding-inversion` |
| 7 — Agent tool-call hijacking | `critical` | `agent-tool-hijack`, `agent-framework-hijack` |
| 8 — Persistent memory contamination | `critical` | `memory-contamination` |
| 9 — LoRA cross-tenant influence | `high` | `lora-cross-tenant` |
| 10 — IKEA-style benign extraction | `high` | `ikea-extraction` |
| 13 — Multi-modal RAG entity-bleed | `critical` | `multimodal-rag-bleed` |

Total catalog weight: **41**.

**Class 11 (GDPR Article 17 erasure) is deliberately out of scope.** It is a control
check with its own attestation (`sectum-ai erasure`), not an adversarial isolation class;
folding it in would conflate two different claims. Class 12 is the
[evidence chain](evidence-chain.md), not an attack class — hence the gap in the numbering.

## How the letter is computed

1. **Per class** — a class is *covered* when at least one of its probes appears in the
   run's `probe_versions`, **or** produced a confirmed finding (a finding is itself proof
   its probe ran — rule 4). A covered class is `FAIL` if any of its probes produced a
   **confirmed** finding, else `PASS`. An uncovered class is `NOT_COVERED`.
2. **Weighted score** — `sum(weight of PASS) / sum(weight of covered)`, over the
   **covered classes only**.
3. **Base grade** — from the weighted score:

    | Weighted score | Grade |
    |---|---|
    | ≥ 0.95 | A |
    | ≥ 0.85 | B |
    | ≥ 0.70 | C |
    | ≥ 0.50 | D |
    | < 0.50 | F |

    In practice the reachable letters are **A, C, D, F**: a weighted score below 1.0
    requires a failing class, which caps at C or worse (step 4) and therefore always
    swallows a base grade of B. So **A means a clean sweep of everything covered**, and
    `B` exists only to make the base-grade arithmetic complete — the cap governs whenever
    anything failed.

4. **Band cap** — the worst **weight band among the failing classes** caps the letter.
   This keys on the *class's* band from the table above — **not** on the `severity`
   recorded on any individual finding. (Those differ in practice: `kv-cache-timing` is a
   `medium`-band class but emits `high`-severity findings. Bands are declared and stable;
   a finding's severity varies with which marker happened to leak, so grading on it would
   make the letter depend on an accident.)

    | Worst failing class's band | Cap |
    |---|---|
    | `critical` | F |
    | `high` | D |
    | `medium` | C |
    | none failing | uncapped |

    (In code, the cap table also carries a `low` row and `SEVERITY_WEIGHTS` also carries
    `low`/`info` weights, for completeness. No catalog class carries those bands today, so
    both are unreachable.)

5. **Final grade** — the **worse** of the base grade and the cap. So one failing
   `high`-band class floors the grade at D, and many failures can still push it below.

## Coverage and confidence

`coverage = sum(weight of covered) / 41`, reported beside the grade and never folded
into it:

| Coverage | Confidence |
|---|---|
| ≥ 0.85 | high |
| ≥ 0.60 | medium |
| < 0.60 | low |

A class is uncovered when the configured stack cannot satisfy its probe (no adapter
reports the capability it needs, so it is skipped rather than run into a mid-probe
error), when it was not in the run's suite, or when the substrate left its probe no step
to take — its markers were foreign to no principal, so there was nothing to plant that
anyone could try to steal.

That last reason is **per class**, and the substrate refusal above cannot stand in for it:
the refusal asks whether *some* marker is foreign to *somebody*, so a substrate can
satisfy it and still starve one class of anything to find. Such a class reads
`NOT_COVERED` rather than `PASS` — it asked the stack nothing — and the loss lands on
confidence, so a thin `coverage` figure is worth reading as a question about the
substrate. Class 13 is measured by its own
[image-embedding sweep](attack-catalog/class-13-multimodal-rag-bleed.md) rather than the
CLI probe suite, so a plain `sectum-ai probe` run records it `NOT_COVERED` — honestly
lowering confidence rather than quietly passing.

**A run that exercised no catalog class at all is not graded.** `sectum-ai score` exits
`3` instead: grading nothing would emit a letter that means nothing, and `F` would
falsely read as "failed" when the truth is "never tested". It also exits `3` for a run
carrying a confirmed finding the catalog cannot attribute (rule 4), and for
`--output sarif/oscal`, which project findings and have no rendering for a graded posture.

`score` itself exits `0` whatever the letter — it reports a posture, it does not gate.
`sectum-ai probe` is the CI gate (exit `2` on a confirmed leak).

## Changing the methodology

The catalog, weights, thresholds, and caps above mirror `sectum_ai.score.CATALOG`,
`SEVERITY_WEIGHTS`, and the threshold/cap tables in the same module (which additionally
carry the currently-unreachable `low`/`info` weight bands).
`tests/unit/test_score.py` pins every value on this page — the catalog and weights in
`test_the_catalog_matches_the_published_methodology`, the total in
`test_the_published_total_catalog_weight_is_41`, and the thresholds and caps in the
grade/confidence/cap tests beside them — so changing one fails CI until this page and the
version move too.
Any change to them is a change to what a published grade means, so bump
`METHODOLOGY_VERSION` (and this page) together — a scorecard stamped `v1.2` must always
recompute to the same letter.
