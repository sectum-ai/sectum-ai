"""The search-index scan refuses a MISS on a truncated page, not a hit found there.

The guard existed but only the integration tests exercised it, and they skip
without a reachable cluster - so the rule it encodes was never checked in the
default run. It also refused unconditionally, discarding a phrase the returned
page already held: a definite residual reported as an error, the same defect
cycle 6 fixed on the trace backends and cycle 9 on Langfuse.

The adapter imports ``opensearchpy`` in ``__init__``, so these build it without
running the constructor and drive a stub client.
"""

from typing import Any
from uuid import UUID

import pytest

from sectum_ai.adapters.search_index.opensearch import OpenSearchSearchIndex
from sectum_ai.spec import AdapterError

_TENANT = UUID(int=0xA)


class _StubClient:
    """Answers one search with ``rows``, reporting ``total`` matches in all."""

    def __init__(self, rows: list[str], total: int) -> None:
        self._rows = rows
        self._total = total
        self.indices = self

    def exists(self, *, index: str) -> bool:
        return True

    def search(self, *, index: str, body: dict[str, Any]) -> dict[str, Any]:
        return {
            "hits": {
                "total": {"value": self._total},
                "hits": [{"_source": {"content": row}} for row in self._rows],
            }
        }


def _adapter(rows: list[str], total: int) -> OpenSearchSearchIndex:
    adapter = object.__new__(OpenSearchSearchIndex)
    adapter._client = _StubClient(rows, total)
    adapter._prefix = "sectum-ai-search"
    adapter._soft_delete = False
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
