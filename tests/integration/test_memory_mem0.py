"""Opt-in live integration test for the mem0 memory adapter.

mem0 needs an embedder (and, with ``infer=True``, an LLM); the default config uses
OpenAI, so this is skipped unless ``OPENAI_API_KEY`` is set (the engineering spec,
section 13: opt-in live). Enable with ``pip install sectum-ai-adapters[mem0]`` and
the key; the adapter logic itself is covered offline by
``tests/unit/test_memory_mem0_adapter.py``.
"""

import contextlib
import os
import secrets
import time
from collections.abc import Iterator
from uuid import UUID

import pytest

from sectum_ai.adapters.memory.mem0 import Mem0Memory

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("OPENAI_API_KEY"),
        reason="set OPENAI_API_KEY (mem0's default embedder) to run the live mem0 test",
    ),
]

_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


@pytest.fixture
def live() -> Iterator[Mem0Memory]:
    try:
        from mem0 import Memory
    except ImportError:
        pytest.skip("mem0 not installed")
    try:
        client = Memory()
    except Exception as error:
        pytest.skip(f"mem0 backend not constructable: {error}")
    adapter = Mem0Memory(client)
    for tenant in (_TENANT_A, _TENANT_B):
        with contextlib.suppress(Exception):
            adapter.delete(tenant)
    yield adapter
    for tenant in (_TENANT_A, _TENANT_B):
        with contextlib.suppress(Exception):
            adapter.delete(tenant)


def _recall_until(adapter: Mem0Memory, tenant: UUID, marker: str, *, present: bool) -> list[str]:
    # mem0 embeds/indexes asynchronously; poll until the note is (or is no longer) visible.
    for _ in range(20):
        hits = adapter.recall(tenant, marker)
        if bool(hits) == present:
            return hits
        time.sleep(1.0)
    return adapter.recall(tenant, marker)


def test_mem0_isolates_tenants_and_erases(live: Mem0Memory) -> None:
    marker = f"SECTUM-CANARY-{secrets.token_hex(4).upper()}"
    live.remember(_TENANT_A, f"long-term note mentioning {marker}")
    hits = _recall_until(live, _TENANT_A, marker, present=True)
    assert hits and marker in hits[0]
    # a foreign tenant's mem0 user_id is separate - the note never surfaces
    assert live.recall(_TENANT_B, marker) == []
    live.delete(_TENANT_A)
    assert _recall_until(live, _TENANT_A, marker, present=False) == []
