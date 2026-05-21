"""Opt-in live integration test for the Langfuse observability adapter.

Skipped unless ``LANGFUSE_PUBLIC_KEY``, ``LANGFUSE_SECRET_KEY``, and
``LANGFUSE_HOST`` are set (the engineering spec, section 13: opt-in live).
Enable with ``pip install sectum-ai-adapters[langfuse]`` and the env vars; the
adapter logic itself is covered offline by ``tests/unit/test_langfuse_adapter.py``.
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
from sectum.adapters.observability.langfuse import LangfuseObservability

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (
            os.environ.get("LANGFUSE_PUBLIC_KEY")
            and os.environ.get("LANGFUSE_SECRET_KEY")
            and os.environ.get("LANGFUSE_HOST")
        ),
        reason="set LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, and LANGFUSE_HOST for the live test",
    ),
]

_TENANT_A = UUID(int=0xA)


@pytest.fixture
def live() -> Iterator[tuple[Any, LangfuseObservability]]:
    from langfuse import Langfuse

    client = Langfuse(
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        host=os.environ["LANGFUSE_HOST"],
    )
    try:
        client.api.projects.get()
    except Exception as error:
        pytest.skip(f"Langfuse backend not reachable: {error}")
    adapter = LangfuseObservability(client)
    yield client, adapter
    with contextlib.suppress(Exception):
        adapter.delete(_TENANT_A)


def _search_until(
    adapter: LangfuseObservability, tenant: UUID, marker: str, *, present: bool
) -> list[TraceHit]:
    # Langfuse ingests asynchronously, so poll until the trace is (or is no
    # longer) visible.
    for _ in range(20):
        hits = adapter.search_traces(tenant, marker)
        if bool(hits) == present:
            return hits
        time.sleep(0.5)
    return adapter.search_traces(tenant, marker)


def test_langfuse_round_trips_and_erases(live: tuple[Any, LangfuseObservability]) -> None:
    client, adapter = live
    marker = f"SECTUM-CANARY-{secrets.token_hex(4).upper()}"
    with client.start_as_current_span(name="sectum-probe") as span:
        span.update(input=f"the output mentions {marker}")
        client.update_current_trace(user_id=_TENANT_A.hex)
    client.flush()
    hits = _search_until(adapter, _TENANT_A, marker, present=True)
    assert hits
    assert marker in hits[0].snippet
    adapter.delete(_TENANT_A)
    assert _search_until(adapter, _TENANT_A, marker, present=False) == []
