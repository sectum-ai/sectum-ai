"""Tests for the job-runner abstraction (the engineering spec, sections 13, 21)."""

import time
from collections.abc import Callable, Sequence

import pytest

from sectum_ai.jobs import JobRunner, SerialJobRunner, ThreadJobRunner, build_job_runner
from sectum_ai.spec import ConfigError


def test_serial_runner_applies_in_order() -> None:
    assert SerialJobRunner().map(lambda x: x * x, [0, 1, 2, 3, 4]) == [0, 1, 4, 9, 16]


def test_thread_runner_applies_to_every_item() -> None:
    assert sorted(ThreadJobRunner(4).map(lambda x: x + 1, range(10))) == list(range(1, 11))


def test_thread_runner_preserves_input_order_despite_completion_order() -> None:
    # Sleep longer for earlier items so they finish last; the result must still
    # come back in input order (the pool's contract the engine relies on).
    def slow_square(x: int) -> int:
        time.sleep((5 - x) * 0.01)
        return x * x

    assert ThreadJobRunner(5).map(slow_square, [0, 1, 2, 3, 4]) == [0, 1, 4, 9, 16]


def test_serial_and_thread_runners_agree() -> None:
    items = list(range(20))
    assert SerialJobRunner().map(str, items) == ThreadJobRunner(4).map(str, items)


def test_thread_runner_propagates_a_job_error() -> None:
    def boom(x: int) -> int:
        if x == 3:
            raise ValueError("job 3 failed")
        return x

    with pytest.raises(ValueError, match="job 3 failed"):
        ThreadJobRunner(4).map(boom, [1, 2, 3, 4])


def test_thread_runner_rejects_a_zero_worker_count() -> None:
    with pytest.raises(ConfigError, match="at least 1"):
        ThreadJobRunner(0)


def test_build_job_runner_is_serial_at_one() -> None:
    assert isinstance(build_job_runner(1), SerialJobRunner)


def test_build_job_runner_is_threaded_above_one() -> None:
    assert isinstance(build_job_runner(4), ThreadJobRunner)


def test_build_job_runner_rejects_below_one() -> None:
    with pytest.raises(ConfigError, match="at least 1"):
        build_job_runner(0)


def test_an_empty_batch_returns_no_results() -> None:
    assert SerialJobRunner().map(lambda x: x, []) == []
    assert ThreadJobRunner(4).map(lambda x: x, []) == []


def test_a_custom_job_runner_swaps_in_via_the_protocol() -> None:
    # The §13/§21 contract: the engine binds to the JobRunner Protocol, so a
    # third-party orchestrator (Temporal/Prefect/...) drops in without touching
    # the engine. A minimal custom runner must type as a JobRunner (mypy checks
    # the annotation below structurally) and agree with the shipped runners.
    class RecordingJobRunner:
        def __init__(self) -> None:
            self.batches = 0

        def map[T, R](self, func: Callable[[T], R], items: Sequence[T]) -> list[R]:
            self.batches += 1
            return [func(item) for item in items]

    custom: JobRunner = RecordingJobRunner()
    items = list(range(8))
    assert custom.map(lambda x: x * 2, items) == SerialJobRunner().map(lambda x: x * 2, items)
    assert isinstance(custom, RecordingJobRunner) and custom.batches == 1
