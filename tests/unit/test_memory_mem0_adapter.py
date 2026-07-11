"""Mock-backed contract tests for the live mem0 memory adapter.

mem0 needs an LLM / embedder / vector store, so the adapter's add/recall/delete
logic is verified here against an in-memory stand-in for the mem0 ``Memory``
client (the engineering spec, section 13). The live path is exercised by
``tests/integration/test_memory_mem0.py``.
"""

from typing import Any
from uuid import UUID

from sectum_ai.adapters.base import Capability, MemoryAdapter
from sectum_ai.adapters.memory.mem0 import Mem0Memory

_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


class _FakeMem0:
    """In-memory stand-in for a mem0 ``Memory`` (per-user_id verbatim store)."""

    def __init__(self) -> None:
        self._by_user: dict[str, list[str]] = {}

    def add(self, messages: str, *, user_id: str, infer: bool = True, **_: Any) -> None:
        assert infer is False, "the adapter must store verbatim (infer=False)"
        self._by_user.setdefault(user_id, []).append(messages)

    def search(self, query: str, *, user_id: str, limit: int | None = None, **_: Any) -> Any:
        # mem0 returns its scope's memories ranked by relevance; the adapter applies
        # its own keyword-overlap filter, so returning the whole scope is faithful.
        rows = [{"memory": text} for text in self._by_user.get(user_id, [])]
        return {"results": rows[:limit] if limit is not None else rows}

    def delete_all(self, *, user_id: str) -> None:
        self._by_user.pop(user_id, None)


def test_mem0_conforms_and_reports_per_tenant_memory() -> None:
    adapter = Mem0Memory(_FakeMem0())
    assert isinstance(adapter, MemoryAdapter)
    assert adapter.supports(Capability.PER_TENANT_MEMORY)
    assert not adapter.supports(Capability.SHARED_MEMORY)
    assert not adapter.supports(Capability.USER_SCOPED)


def test_mem0_scoped_memory_isolates_tenants() -> None:
    adapter = Mem0Memory(_FakeMem0())
    adapter.remember(_TENANT_A, "long-term note about canary ALPHA-7")
    assert any("ALPHA-7" in e for e in adapter.recall(_TENANT_A, "canary ALPHA-7"))
    # a foreign tenant recalls nothing - its mem0 user_id is separate
    assert adapter.recall(_TENANT_B, "canary ALPHA-7") == []


def test_mem0_recall_keyword_filters_the_scope() -> None:
    adapter = Mem0Memory(_FakeMem0())
    adapter.remember(_TENANT_A, "note about canary ALPHA-7")
    adapter.remember(_TENANT_A, "an unrelated grocery list")
    hits = adapter.recall(_TENANT_A, "canary ALPHA-7")
    assert hits == ["note about canary ALPHA-7"]  # the grocery note is filtered out


def test_mem0_shared_memory_leaks_across_tenants() -> None:
    # shared_memory collapses every tenant to one scope - the Class 8 leak: a note
    # planted as tenant A surfaces in tenant B's recall.
    adapter = Mem0Memory(_FakeMem0(), shared_memory=True)
    adapter.remember(_TENANT_A, "shared note about canary BETA-9")
    assert any("BETA-9" in e for e in adapter.recall(_TENANT_B, "canary BETA-9"))
    assert adapter.supports(Capability.SHARED_MEMORY)


def test_mem0_delete_purges_a_tenants_memory() -> None:
    adapter = Mem0Memory(_FakeMem0())
    adapter.remember(_TENANT_A, "note about canary DEL-1")
    adapter.remember(_TENANT_B, "note about canary KEEP-1")
    adapter.delete(_TENANT_A)
    assert adapter.recall(_TENANT_A, "canary DEL-1") == []
    # another tenant's memory is untouched
    assert adapter.recall(_TENANT_B, "canary KEEP-1")


def test_mem0_soft_delete_leaves_the_residue() -> None:
    adapter = Mem0Memory(_FakeMem0(), soft_delete=True)
    adapter.remember(_TENANT_A, "note about canary SOFT-1")
    adapter.delete(_TENANT_A)
    assert adapter.supports(Capability.SOFT_DELETE)
    assert adapter.recall(_TENANT_A, "canary SOFT-1")  # the residue survives


def test_mem0_search_tolerates_a_bare_list_result_shape() -> None:
    # older mem0 returns a bare list of dicts instead of {"results": [...]}
    class _OldMem0(_FakeMem0):
        def search(self, query: str, *, user_id: str, limit: int | None = None, **_: Any) -> Any:
            return [{"memory": text} for text in self._by_user.get(user_id, [])]

    adapter = Mem0Memory(_OldMem0())
    adapter.remember(_TENANT_A, "note about canary GAMMA-3")
    assert any("GAMMA-3" in e for e in adapter.recall(_TENANT_A, "canary GAMMA-3"))


def test_mem0_recall_tolerates_none_and_malformed_rows() -> None:
    # mem0's result shape shifts across releases; recall must not crash on a None
    # result or a row missing the "memory" key - it returns nothing, never raises.
    class _NoneMem0(_FakeMem0):
        def search(self, query: str, *, user_id: str, limit: int | None = None, **_: Any) -> Any:
            return None

    assert Mem0Memory(_NoneMem0()).recall(_TENANT_A, "anything") == []

    class _MalformedMem0(_FakeMem0):
        def search(self, query: str, *, user_id: str, limit: int | None = None, **_: Any) -> Any:
            return {"results": [{"id": "no-memory-key"}, "not-a-dict"]}

    assert Mem0Memory(_MalformedMem0()).recall(_TENANT_A, "anything") == []
