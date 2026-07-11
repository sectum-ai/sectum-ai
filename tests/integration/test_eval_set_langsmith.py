"""Opt-in live integration test for the LangSmith eval-set adapter.

Skipped unless ``LANGSMITH_API_KEY`` (or ``LANGCHAIN_API_KEY``) is set (the
engineering spec, section 13: opt-in live). Enable with
``pip install sectum-ai-adapters[langsmith]`` and the env var
(``LANGSMITH_ENDPOINT`` for self-hosted); the adapter logic itself is covered
offline by ``tests/unit/test_eval_set_langsmith_adapter.py``.
"""

import contextlib
import os
import secrets
import time
from collections.abc import Iterator
from uuid import UUID

import pytest

from sectum_ai.adapters.eval_set.langsmith import LangSmithEvalSet

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")),
        reason="set LANGSMITH_API_KEY to run the live LangSmith eval-set test",
    ),
]

_PREFIX = "sectum-eval-it"
_TENANT_A = UUID(int=0xA)


@pytest.fixture
def live() -> Iterator[LangSmithEvalSet]:
    from langsmith import Client

    client = Client(
        api_url=os.environ.get("LANGSMITH_ENDPOINT"),
        api_key=os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY"),
    )
    try:
        list(client.list_datasets(limit=1))
    except Exception as error:
        pytest.skip(f"LangSmith backend not reachable: {error}")
    adapter = LangSmithEvalSet(client, prefix=_PREFIX)
    with contextlib.suppress(Exception):
        adapter.delete(_TENANT_A)
    yield adapter
    with contextlib.suppress(Exception):
        adapter.delete(_TENANT_A)


def _search_until(
    adapter: LangSmithEvalSet, tenant: UUID, marker: str, *, present: bool
) -> list[str]:
    # LangSmith indexes asynchronously, so poll until the fixture is (or is no
    # longer) visible.
    for _ in range(20):
        hits = adapter.search(tenant, marker)
        if bool(hits) == present:
            return hits
        time.sleep(1.0)
    return adapter.search(tenant, marker)


def test_langsmith_eval_set_round_trips_and_erases(live: LangSmithEvalSet) -> None:
    marker = f"SECTUM-CANARY-{secrets.token_hex(4).upper()}"
    live.add(_TENANT_A, f"eval fixture mentioning {marker}")
    hits = _search_until(live, _TENANT_A, marker, present=True)
    assert hits and marker in hits[0]
    live.delete(_TENANT_A)
    assert _search_until(live, _TENANT_A, marker, present=False) == []
