# ADR-0003 - Substrate artifacts are pure functions of the seed

## Status

Accepted (2026-05-16).

## Context

The engineering spec, section 6.5 requires that the same seed, scenario, and corpus profile
produce a byte-identical corpus and an identical ground-truth manifest. This
reproducibility is a tested invariant and underpins the evidence chain: the
manifest hash anchors the test conditions.

Two parts of the section 9 schema work against byte-identical reproducibility.
Section 6.1 specifies UUIDv7 for tenant IDs, and section 9 lists ``created_at``
on the manifest. UUIDv7 embeds a wall-clock timestamp; a ``created_at`` field is
a wall-clock timestamp. Either one makes two runs of the same seed differ.

## Decision

Every artifact the substrate produces is a pure function of the scenario seed.

- **Deterministic identifiers.** Tenant, marker, and document identifiers are
  derived deterministically - tenant IDs via UUID5 over a fixed namespace,
  marker and document IDs as seeded sequences. UUIDv7 is not used.
- **No wall-clock time in substrate artifacts.** ``Scenario``,
  ``GroundTruthManifest``, ``Marker``, and ``CorpusDocument`` carry no
  timestamps. The manifest omits the ``created_at`` field sketched in section 9.
  Wall-clock time lives only on run-time records (``RunResult.started_at`` and
  ``finished_at``), which are not part of the reproducible substrate.
- **No process-randomized hashing.** Generation never uses the built-in
  ``hash()`` of strings (salted per process); all derivation uses ``hashlib``
  and explicitly seeded ``random.Random`` streams threaded through the call
  graph, with no hidden global state.

## Consequences

- The reproducibility invariant holds byte-for-byte and is tested directly
  (``tests/invariants/test_reproducibility.py``).
- This deviates from section 6.1 (UUIDv7) and section 9 (manifest
  ``created_at``); recorded here per the engineering spec, section 1.2.
- A run's timestamps are recorded on ``RunResult``, so the audit trail keeps
  wall-clock context without compromising substrate reproducibility.
