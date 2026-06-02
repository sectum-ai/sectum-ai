# ADR-0019: a `JobRunner` interface with local runners; a distributed backend stays swappable

- Status: Accepted
- Date: 2026-06-02
- Deciders: Dmitry Maranik

## Context

Multi-tenant verification runs are long: a suite fans a probe set across four
tenants and several surfaces, and a hosted run may sweep many scenarios. The
engineering spec anticipates this — section 13 lists "Async + a job runner
abstraction; Temporal or Prefect behind an interface (don't hard-couple)", and
section 21 records the runner choice as an open decision ("keep behind an
interface until forced to choose"). This ADR resolves it for the OSS core.

Two forces pull against each other:

- **Determinism and zero-dependency runs.** The substrate is the moat and must be
  reproducible (ADR-0003); unit tests run offline; the demo must work from a
  clean machine in minutes. A heavy orchestrator (Temporal/Prefect) as a hard
  dependency would break all three.
- **Scale.** A hosted/continuous deployment (the paid Cloud) wants real
  concurrency and, eventually, a distributed queue.

The probe engine does not need to *know* which of these is in play — it only
needs to apply a function across a batch and get the results back in order.

## Decision

Define a minimal **`JobRunner` protocol** (`sectum.jobs`) and bind the engine to
it, not to any concrete orchestrator:

```python
class JobRunner(Protocol):
    def map(self, func: Callable[[T], R], items: Sequence[T]) -> list[R]: ...
```

- Ship two **local** runners: `SerialJobRunner` (deterministic, one at a time —
  the default and the only one used in tests and the demo) and `ThreadJobRunner`
  (a bounded thread pool for I/O-bound live-adapter runs). `build_job_runner(n)`
  returns serial at `n == 1`, threaded above.
- The CLI selects concurrency with `sectum probe --max-concurrency`; the engine
  calls `job_runner.map(...)` and is otherwise oblivious to the backend.
- "Async" in section 13 is realized as a **thread pool**, not `asyncio`: the work
  is bounded I/O against adapters and the probe-detection logic is synchronous
  and CPU-cheap, so threads keep the call sites plain (no async colouring) while
  still overlapping adapter I/O. This ADR is the record of that reading.
- A distributed backend (Temporal, Prefect, a queue) is a future `JobRunner`
  implementation. Because the engine depends only on the protocol, adding one
  touches no probe or runner code — a custom runner drops in (covered by
  `tests/unit/test_jobs.py::test_a_custom_job_runner_swaps_in_via_the_protocol`).

## Consequences

- The base install stays pure-Python and deterministic; no orchestrator
  dependency enters the OSS core.
- `ThreadJobRunner` is only safe when the adapters are thread-safe and probe
  order does not matter; the demo's in-memory fakes share state across mutating
  and reading probes, so the CLI defaults to serial and documents the caveat on
  `--max-concurrency`.
- The section-21 "job runner" open decision is now resolved for OSS: a local
  thread pool behind the `JobRunner` protocol. Choosing a distributed backend is
  deferred to the Cloud and does not require revisiting this interface.
