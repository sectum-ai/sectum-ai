"""Opt-in live integration test for the LangSmith observability adapter.

Skipped unless ``LANGSMITH_API_KEY`` (or ``LANGCHAIN_API_KEY``) is set (the
engineering spec, section 13: opt-in live). Enable with
``pip install sectum-ai-adapters[langsmith]`` and the env var
(``LANGSMITH_ENDPOINT`` for self-hosted); the adapter logic itself is covered
offline by ``tests/unit/test_langsmith_adapter.py``.
"""

import contextlib
import os
import secrets
import time
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest

from sectum.adapters.base import TraceHit
from sectum.adapters.observability.langsmith import LangSmithObservability

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")),
        reason="set LANGSMITH_API_KEY to run the live LangSmith test",
    ),
]

_PREFIX = "sectum-it"
_TENANT_A = UUID(int=0xA)


def _project(tenant: UUID) -> str:
    return f"{_PREFIX}-{tenant.hex}"


@pytest.fixture
def live() -> Iterator[tuple[Any, LangSmithObservability]]:
    from langsmith import Client

    client = Client(
        api_url=os.environ.get("LANGSMITH_ENDPOINT"),
        api_key=os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY"),
    )
    try:
        list(client.list_projects(limit=1))
    except Exception as error:
        pytest.skip(f"LangSmith backend not reachable: {error}")
    adapter = LangSmithObservability(client, prefix=_PREFIX)
    yield client, adapter
    with contextlib.suppress(Exception):
        adapter.delete(_TENANT_A)


def _search_until(
    adapter: LangSmithObservability, tenant: UUID, marker: str, *, present: bool
) -> list[TraceHit]:
    # LangSmith ingests/indexes asynchronously, so poll until the run is (or is
    # no longer) visible.
    for _ in range(20):
        hits = adapter.search_traces(tenant, marker)
        if bool(hits) == present:
            return hits
        time.sleep(1.0)
    return adapter.search_traces(tenant, marker)


def test_langsmith_round_trips_and_erases(live: tuple[Any, LangSmithObservability]) -> None:
    client, adapter = live
    marker = f"SECTUM-CANARY-{secrets.token_hex(4).upper()}"
    client.create_run(
        name="sectum-probe",
        inputs={"text": f"the output mentions {marker}"},
        run_type="chain",
        project_name=_project(_TENANT_A),
    )
    client.flush()
    hits = _search_until(adapter, _TENANT_A, marker, present=True)
    assert hits
    assert marker in hits[0].snippet
    adapter.delete(_TENANT_A)
    assert _search_until(adapter, _TENANT_A, marker, present=False) == []
