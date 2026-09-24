"""The search-index scan refuses a MISS on a truncated page, not a hit found there.

The guard existed but only the integration tests exercised it, and they skip
without a reachable cluster - so the rule it encodes was never checked in the
default run. It also refused unconditionally, discarding a phrase the returned
page already held: a definite residual reported as an error, the same defect
cycle 6 fixed on the trace backends and cycle 9 on Langfuse.

These build the adapter through its REAL constructor - ``opensearchpy`` opens no
connection until a request - and swap in a stub client.
"""

from typing import Any
from uuid import UUID

import pytest

from sectum_ai.adapters.search_index.opensearch import OpenSearchSearchIndex
from sectum_ai.spec import AdapterError

_TENANT = UUID(int=0xA)


class _StubClient:
    """Answers one search with ``rows``, reporting ``total`` matches in all."""

    def __init__(self, rows: list[str], total: int | None) -> None:
        self._rows = rows
        self._total = total
        self.indices = self
        self.deleted: list[str] = []

    def exists(self, *, index: str) -> bool:
        return True

    def search(self, *, index: str, body: dict[str, Any]) -> dict[str, Any]:
        hits: dict[str, Any] = {"hits": [{"_source": {"content": row}} for row in self._rows]}
        # `total=None` models a backend that answers without one at all.
        if self._total is not None:
            hits["total"] = {"value": self._total}
        return {"hits": hits}

    def delete(self, *, index: str, ignore: Any = None) -> dict[str, Any]:
        self.deleted.append(index)
        return {"acknowledged": True}


def _adapter(
    rows: list[str], total: int | None, *, soft_delete: bool = False
) -> OpenSearchSearchIndex:
    """Build through the REAL constructor, then swap the client.

    `object.__new__` skipped `__init__`, so `name`, `capabilities` and
    `supports()` were never set and every test that would have touched `delete`
    or the soft-delete branch could not be written - the adapter sat at 48% with
    `delete` at zero. `opensearchpy` constructs offline (it opens no connection
    until a request), so the real constructor costs nothing here.
    """
    adapter = OpenSearchSearchIndex(soft_delete=soft_delete)
    adapter._client = _StubClient(rows, total)
    return adapter


def test_a_phrase_found_on_a_truncated_page_is_returned() -> None:
    adapter = _adapter(["a note about CANARY-OMEGA", "filler"], total=99999)
    assert adapter.search(_TENANT, "CANARY-OMEGA") == [
        "a note about CANARY-OMEGA",
        "filler",
    ]


def test_a_miss_on_a_truncated_page_is_refused() -> None:
    adapter = _adapter(["filler one", "filler two"], total=99999)
    with pytest.raises(AdapterError, match="found nothing would be incomplete"):
        adapter.search(_TENANT, "CANARY-OMEGA")


def test_a_miss_on_a_complete_page_is_absence() -> None:
    adapter = _adapter(["filler one", "filler two"], total=2)
    assert adapter.search(_TENANT, "CANARY-OMEGA") == ["filler one", "filler two"]


def test_a_response_without_a_readable_total_is_refused_not_read_as_zero() -> None:
    # `hits.get("total", {})` then `.get("value", 0)` manufactured a zero, so
    # `total_count > len(rows)` was False and the cap refusal never fired: a
    # TRUNCATED page on a canary MISS returned silently and the marker ranked past
    # it read as absent. That is the fail-open direction on a check nothing
    # downstream can catch - the adapter is the only thing that knows the page was
    # short - and `backup/gcs.py` states the rule: "a number nobody measured is
    # not a measurement of zero."
    from sectum_ai.spec import AdapterError

    adapter = _adapter(["an unrelated document"], total=99999)
    with pytest.raises(AdapterError, match="a search-index scan that found nothing"):
        adapter.search(_TENANT, "SECTUM-CANARY-MISSING")

    # The same truncated page with the total OMITTED must not pass silently.
    missing = _adapter(["an unrelated document"], total=None)
    with pytest.raises(AdapterError, match=r"no readable hits\.total"):
        missing.search(_TENANT, "SECTUM-CANARY-MISSING")


def test_the_adapter_reports_its_capabilities_and_purges_the_tenant_index() -> None:
    # Unreachable while the harness used `object.__new__`: no `__init__` meant no
    # `name`, no `capabilities`, and `supports()` raising AttributeError - so
    # `delete` and the soft-delete branch sat at zero coverage, and the family's
    # two omitted paths are also excluded from the 85% gate by `pyproject.toml`.
    from sectum_ai.adapters.base import Capability

    hard = _adapter([], total=0)
    assert hard.supports(Capability.TEXT_SEARCH)
    assert not hard.supports(Capability.SOFT_DELETE)
    hard.delete(_TENANT)
    assert hard._client.deleted == [f"sectum-ai-search-{_TENANT.hex}"]

    # A soft-delete store declares it, which is what makes the erasure verdict
    # ATTESTABLE_WITH_CAVEAT rather than ERASED.
    soft = _adapter([], total=0, soft_delete=True)
    assert soft.supports(Capability.SOFT_DELETE)
