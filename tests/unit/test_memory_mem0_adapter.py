"""Mock-backed contract tests for the live mem0 memory adapter.

mem0 needs an LLM / embedder / vector store, so the adapter's add/recall/delete
logic is verified here against an in-memory stand-in for the mem0 ``Memory``
client (the engineering spec, section 13). The live path is exercised by
``tests/integration/test_memory_mem0.py``.
"""

from typing import Any
from uuid import UUID

import pytest

from sectum_ai.adapters.base import Capability, MemoryAdapter
from sectum_ai.adapters.memory.mem0 import Mem0Memory
from sectum_ai.spec import ErasureUnsupported

_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


class _FakeMem0:
    """In-memory stand-in for a mem0 ``Memory`` (per-user_id verbatim store)."""

    def __init__(self) -> None:
        self._by_user: dict[str, list[str]] = {}

    def add(self, messages: str, *, user_id: str, infer: bool = True, **_: Any) -> None:
        assert infer is False, "the adapter must store verbatim (infer=False)"
        self._by_user.setdefault(user_id, []).append(messages)

    def get_all(self, *, user_id: str, limit: int = 100, **_: Any) -> Any:
        # mem0's signature: get_all(user_id=..., limit=100) - it pages no further.
        rows = [{"memory": text} for text in self._by_user.get(user_id, [])]
        return {"results": rows[:limit]}

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


def test_mem0_shared_memory_delete_is_attestable_with_caveat_not_a_global_wipe() -> None:
    # In shared mode every tenant shares one user_id, so a real delete would wipe
    # *every* tenant. The adapter must raise ErasureUnsupported (attestable-with-
    # caveat) instead of destroying all tenants' memory.
    client = _FakeMem0()
    adapter = Mem0Memory(client, shared_memory=True)
    adapter.remember(_TENANT_A, "shared note about canary DELME")
    adapter.remember(_TENANT_B, "shared note about canary KEEPME")
    with pytest.raises(ErasureUnsupported):
        adapter.delete(_TENANT_A)
    # nothing was wiped - both tenants' shared-scope memory survives
    assert any("KEEPME" in e for e in adapter.recall(_TENANT_B, "canary KEEPME"))
    assert any("DELME" in e for e in adapter.recall(_TENANT_A, "canary DELME"))


def test_mem0_shared_memory_raises_even_with_soft_delete_set() -> None:
    # shared_memory (no per-tenant erasure boundary) is checked BEFORE soft_delete,
    # so the verdict is unambiguously attestable-with-caveat, never a silent
    # soft-delete return that would misreport the surface as RESIDUAL.
    adapter = Mem0Memory(_FakeMem0(), shared_memory=True, soft_delete=True)
    with pytest.raises(ErasureUnsupported):
        adapter.delete(_TENANT_A)


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
        def get_all(self, *, user_id: str, **_: Any) -> Any:
            return [{"memory": text} for text in self._by_user.get(user_id, [])]

    adapter = Mem0Memory(_OldMem0())
    adapter.remember(_TENANT_A, "note about canary GAMMA-3")
    assert any("GAMMA-3" in e for e in adapter.recall(_TENANT_A, "canary GAMMA-3"))


def test_mem0_recall_reads_an_absent_scope_empty_and_a_shape_mismatch_as_an_error() -> None:
    # mem0's result shape shifts across releases. A None result is an empty scope.
    # Rows that carry no "memory" text are a SHAPE MISMATCH, not an empty tenant:
    # read as empty they became "not recalled", and the A3 check attested the
    # subject erased.
    from sectum_ai.spec import AdapterError

    class _NoneMem0(_FakeMem0):
        def get_all(self, *, user_id: str, **_: Any) -> Any:
            return None

    assert Mem0Memory(_NoneMem0()).recall(_TENANT_A, "anything") == []

    class _MalformedMem0(_FakeMem0):
        def get_all(self, *, user_id: str, **_: Any) -> Any:
            return {"results": [{"id": "no-memory-key"}, "not-a-dict"]}

    with pytest.raises(AdapterError, match="response shape"):
        Mem0Memory(_MalformedMem0()).recall(_TENANT_A, "anything")


def test_mem0_recall_is_exhaustive_not_a_ranked_window() -> None:
    # `search(limit=100)` ranked a planted marker out of its window in a tenant
    # with more than 100 memories, and the miss read as "not recalled".
    client = _FakeMem0()
    adapter = Mem0Memory(client)
    for index in range(150):
        adapter.remember(_TENANT_A, f"filler note number {index}")
    adapter.remember(_TENANT_A, "note about canary OMEGA-9")
    assert any("OMEGA-9" in entry for entry in adapter.recall(_TENANT_A, "canary OMEGA-9"))


def test_mem0_refuses_a_listing_that_hit_its_limit() -> None:
    # get_all defaults to limit=100 in the SDK, so the "exhaustive" recall was
    # capped at 100 and a subject's memory past that read as not recalled.
    from sectum_ai.adapters.memory.mem0 import _GET_ALL_LIMIT
    from sectum_ai.spec import AdapterError

    client = _FakeMem0()
    adapter = Mem0Memory(client)
    for index in range(150):
        adapter.remember(_TENANT_A, f"filler note number {index}")
    adapter.remember(_TENANT_A, "note about canary OMEGA-9")
    assert any("OMEGA-9" in entry for entry in adapter.recall(_TENANT_A, "canary OMEGA-9"))
    for index in range(_GET_ALL_LIMIT):
        client._by_user[_TENANT_A.hex].append(f"bulk {index}")
    with pytest.raises(AdapterError, match="listing limit"):
        adapter.recall(_TENANT_A, "anything")


def test_mem0_does_not_carry_the_user() -> None:
    # mem0's flat user_id space is the tenant; inheriting carries_user=True let
    # Class 8 plan user-level steps and confirm cross-user leaks of sessions that
    # never existed - the sibling of the live-MCP defect.
    assert Mem0Memory(_FakeMem0()).carries_user is False


def test_mem0_refuses_a_response_whose_envelope_it_does_not_recognise() -> None:
    # The guard fired only when a ROW key was renamed. A release that renames the
    # top-level key (or nests the rows deeper) yielded an empty list, which read
    # as an empty tenant and let the A3 check attest the subject erased.
    from sectum_ai.spec import AdapterError

    class _RenamedEnvelope(_FakeMem0):
        def get_all(self, *, user_id: str, limit: int = 100, **_: Any) -> Any:
            return {"memories": [{"memory": text} for text in self._by_user.get(user_id, [])]}

    class _NestedEnvelope(_FakeMem0):
        def get_all(self, *, user_id: str, limit: int = 100, **_: Any) -> Any:
            return {"data": {"results": [{"memory": t} for t in self._by_user.get(user_id, [])]}}

    for client_cls in (_RenamedEnvelope, _NestedEnvelope):
        client = client_cls()
        adapter = Mem0Memory(client)
        adapter.remember(_TENANT_A, "note about canary OMEGA-9")
        with pytest.raises(AdapterError, match="response shape"):
            adapter.recall(_TENANT_A, "canary OMEGA-9")


def test_mem0_accepts_a_row_whose_memory_is_empty() -> None:
    # A redacted or soft-deleted entry is a legitimate backend state, not a shape
    # mismatch: keying the guard on truthiness aborted the run over it.
    class _EmptyValue(_FakeMem0):
        def get_all(self, *, user_id: str, limit: int = 100, **_: Any) -> Any:
            return {"results": [{"memory": ""}, {"memory": "canary OMEGA-9"}]}

    assert Mem0Memory(_EmptyValue()).recall(_TENANT_A, "canary OMEGA-9") == ["canary OMEGA-9"]


def test_mem0_counts_rows_not_texts_against_its_listing_limit() -> None:
    # A full page in which any row lacks text slipped under a text-count
    # threshold, so a truncated listing read as a complete one.
    from sectum_ai.adapters.memory.mem0 import _GET_ALL_LIMIT
    from sectum_ai.spec import AdapterError

    class _FullPageWithBlanks(_FakeMem0):
        def get_all(self, *, user_id: str, limit: int = 100, **_: Any) -> Any:
            rows: list[dict[str, str]] = [{"memory": ""}]
            rows += [{"memory": f"filler {i}"} for i in range(_GET_ALL_LIMIT - 1)]
            return {"results": rows}

    with pytest.raises(AdapterError, match="listing limit"):
        Mem0Memory(_FullPageWithBlanks()).recall(_TENANT_A, "canary OMEGA")


def test_mem0_reports_a_hit_found_on_a_full_page() -> None:
    # A hit already answers the question; refusing it would lose a real residual.
    from sectum_ai.adapters.memory.mem0 import _GET_ALL_LIMIT

    class _FullPageWithHit(_FakeMem0):
        def get_all(self, *, user_id: str, limit: int = 100, **_: Any) -> Any:
            rows = [{"memory": "note about canary OMEGA-9"}]
            rows += [{"memory": f"filler {i}"} for i in range(_GET_ALL_LIMIT - 1)]
            return {"results": rows}

    assert Mem0Memory(_FullPageWithHit()).recall(_TENANT_A, "canary OMEGA-9")


def test_a_token_overlap_recall_does_not_suppress_the_cap_refusal() -> None:
    # `recall` reports hits by token OVERLAP; the Class 11 probe counts an exact
    # substring. Every hard canary shares the tokens "sectum" and "canary", so one
    # other canary among the page-filling rows made the adapter report a "hit" the
    # probe would not count - suppressing the refusal, so the target marker past
    # the cap read as absent and the memory surface attested ERASED.
    from sectum_ai.adapters.memory.mem0 import _GET_ALL_LIMIT
    from sectum_ai.spec import AdapterError

    client = _FakeMem0()
    adapter = Mem0Memory(client)
    adapter.remember(_TENANT_A, "note about SECTUM-CANARY-OTHERAAAAAAAAAAAAAAA")
    for index in range(_GET_ALL_LIMIT - 1):
        adapter.remember(_TENANT_A, f"unrelated note {index}")
    with pytest.raises(AdapterError, match="listing"):
        adapter.recall(_TENANT_A, "SECTUM-CANARY-TARGETBBBBBBBBBBBBBBB")
