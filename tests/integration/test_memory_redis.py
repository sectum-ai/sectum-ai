"""Integration tests for the live Redis memory adapter (the Class 8 surface).

Requires a Redis backend (see compose.yaml). The ``reachable`` fixture skips the
tests when no backend is reachable, so the default test run stays offline.
"""

import os
from collections.abc import Iterator
from uuid import UUID

import pytest
import redis

from sectum_ai.adapters.base import Capability
from sectum_ai.adapters.memory.redis import RedisMemory

pytestmark = pytest.mark.integration

_HOST = os.environ.get("SECTUM_REDIS_HOST", "localhost")
_PORT = int(os.environ.get("SECTUM_REDIS_PORT", "6380"))
_PREFIX = "sectum-mem-it"
_A = UUID(int=0xA)
_B = UUID(int=0xB)
_U1 = UUID(int=0xA1)
_U2 = UUID(int=0xA2)
_QUERY = "recall the long-term canary note"


def _flush() -> None:
    conn = redis.Redis(host=_HOST, port=_PORT, decode_responses=True)
    try:
        keys = list(conn.scan_iter(match=f"{_PREFIX}:*"))
        if keys:
            conn.delete(*keys)
    finally:
        conn.close()


@pytest.fixture
def reachable() -> Iterator[None]:
    conn = redis.Redis(host=_HOST, port=_PORT, decode_responses=True)
    try:
        conn.ping()
    except redis.RedisError as error:
        conn.close()
        pytest.skip(f"Redis backend not reachable: {error}")
    conn.close()
    _flush()
    yield
    _flush()


def _memory(
    *, shared_memory: bool = False, user_scoped: bool = False, soft_delete: bool = False
) -> RedisMemory:
    return RedisMemory(
        _HOST,
        _PORT,
        prefix=_PREFIX,
        shared_memory=shared_memory,
        user_scoped=user_scoped,
        soft_delete=soft_delete,
    )


def test_scoped_memory_isolates_tenants(reachable: None) -> None:
    mem = _memory()  # per-tenant (default)
    mem.remember(_A, "long-term note about canary ALPHA-7")
    assert any("ALPHA-7" in e for e in mem.recall(_A, _QUERY))  # owner recalls it
    assert mem.recall(_B, _QUERY) == []  # a foreign tenant recalls nothing
    assert mem.supports(Capability.PER_TENANT_MEMORY)
    assert not mem.supports(Capability.SHARED_MEMORY)


def test_shared_memory_leaks_across_tenants(reachable: None) -> None:
    mem = _memory(shared_memory=True)
    mem.remember(_A, "long-term note about canary BETA-9")
    # tenant B recalls tenant A's note - the Class 8 contamination.
    assert any("BETA-9" in e for e in mem.recall(_B, _QUERY))
    assert mem.supports(Capability.SHARED_MEMORY)


def test_delete_removes_a_tenants_memory(reachable: None) -> None:
    mem = _memory()
    mem.remember(_A, "long-term note about canary GAMMA-3")
    mem.delete(_A)
    assert mem.recall(_A, _QUERY) == []


def test_soft_delete_leaves_the_residue(reachable: None) -> None:
    mem = _memory(soft_delete=True)
    mem.remember(_A, "long-term note about canary DELTA-4")
    mem.delete(_A)  # acknowledged, but the entry survives - the Class 11 residue
    assert any("DELTA-4" in e for e in mem.recall(_A, _QUERY))


def test_user_scoping_isolates_users_within_a_tenant(reachable: None) -> None:
    scoped = _memory(user_scoped=True)
    scoped.remember(_A, "long-term note about canary EPSILON-5", user=_U1)
    assert any("EPSILON-5" in e for e in scoped.recall(_A, _QUERY, user=_U1))  # own note
    assert scoped.recall(_A, _QUERY, user=_U2) == []  # sibling user is isolated
    # A tenant-scoped store (no user_scoped) recalls the sibling's note - the leak.
    shared = _memory()
    shared.remember(_B, "long-term note about canary ZETA-6", user=_U1)
    assert any("ZETA-6" in e for e in shared.recall(_B, _QUERY, user=_U2))
