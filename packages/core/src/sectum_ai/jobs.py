"""A job-runner abstraction for long multi-tenant runs (the engineering spec, sections 13, 21).

A probe campaign executes many independent units of work (a probe per tenant
session). This module abstracts *how* that batch runs behind a small
``JobRunner`` interface, so the engine is not coupled to one orchestrator. The
shipped runners are local: ``SerialJobRunner`` (deterministic, one at a time)
and ``ThreadJobRunner`` (a bounded thread pool). A distributed backend - Temporal
or Prefect, the open decision in section 21 - can implement the same interface
later without changing any call site.

Both runners preserve input order in their results and propagate the first
exception a job raises, so swapping concurrency on or off does not change
outcomes (only timing).
"""

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol, TypeVar

from sectum_ai.spec import ConfigError

T = TypeVar("T")
R = TypeVar("R")


class JobRunner(Protocol):
    """Executes a batch of jobs and returns their results in input order."""

    def map(self, func: Callable[[T], R], items: Sequence[T]) -> list[R]:
        """Apply ``func`` to each item; return the results in input order."""
        ...


class SerialJobRunner:
    """Runs jobs one at a time in the calling thread (fully deterministic)."""

    def map(self, func: Callable[[T], R], items: Sequence[T]) -> list[R]:
        """Apply ``func`` to each item in order, in this thread."""
        return [func(item) for item in items]


class ThreadJobRunner:
    """Runs jobs on a bounded thread pool; results preserve input order.

    Suitable when the jobs release the GIL (network or subprocess I/O, as the
    live adapters do) and do not interact through shared mutable state.
    """

    def __init__(self, max_workers: int) -> None:
        if max_workers < 1:
            raise ConfigError(f"max_workers must be at least 1, got {max_workers}")
        self._max_workers = max_workers

    def map(self, func: Callable[[T], R], items: Sequence[T]) -> list[R]:
        """Apply ``func`` across the pool; return results in input order."""
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            return list(executor.map(func, items))


def build_job_runner(max_concurrency: int = 1) -> JobRunner:
    """Return a job runner: serial at ``max_concurrency`` 1, threaded above it.

    Raises :class:`~sectum_ai.spec.ConfigError` for a concurrency below 1.
    """
    if max_concurrency < 1:
        raise ConfigError(f"max_concurrency must be at least 1, got {max_concurrency}")
    return SerialJobRunner() if max_concurrency == 1 else ThreadJobRunner(max_concurrency)
