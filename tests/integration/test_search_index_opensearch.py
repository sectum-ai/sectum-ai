"""Integration tests for the live OpenSearch search-index adapter (Class 11 surface).

Requires an OpenSearch backend (see compose.yaml). The ``reachable`` fixture skips
the tests when no backend is reachable, so the default test run stays offline.
"""

import os
from collections.abc import Iterator
from uuid import UUID

import pytest

from sectum_ai.adapters.base import Capability
from sectum_ai.adapters.search_index.opensearch import OpenSearchSearchIndex

pytestmark = pytest.mark.integration

_HOST = os.environ.get("SECTUM_OPENSEARCH_HOST", "localhost")
_PORT = int(os.environ.get("SECTUM_OPENSEARCH_PORT", "9201"))
_PREFIX = "sectum-search-it"
_A = UUID(int=0xA)
_B = UUID(int=0xB)


def _reachable() -> bool:
    try:
        from opensearchpy import OpenSearch
    except ImportError:
        return False
    try:
        client = OpenSearch(
            hosts=[{"host": _HOST, "port": _PORT}], use_ssl=False, verify_certs=False
        )
        client.info()
        client.close()
    except Exception:
        return False
    return True


def _cleanup() -> None:
    from opensearchpy import OpenSearch

    client = OpenSearch(hosts=[{"host": _HOST, "port": _PORT}], use_ssl=False, verify_certs=False)
    try:
        client.indices.delete(index=f"{_PREFIX}-*", ignore_unavailable=True)
    finally:
        client.close()


@pytest.fixture
def reachable() -> Iterator[None]:
    if not _reachable():
        pytest.skip("OpenSearch backend not reachable")
    _cleanup()
    yield
    _cleanup()


def _index(*, soft_delete: bool = False) -> OpenSearchSearchIndex:
    return OpenSearchSearchIndex(_HOST, _PORT, prefix=_PREFIX, soft_delete=soft_delete)


def test_index_search_and_scoped_isolation(reachable: None) -> None:
    idx = _index()
    idx.index(_A, "search index entry mentioning canary ALPHA-7")
    assert any("ALPHA-7" in hit for hit in idx.search(_A, "canary ALPHA-7"))  # owner finds it
    assert idx.search(_B, "canary ALPHA-7") == []  # foreign tenant's index is separate
    assert idx.supports(Capability.TEXT_SEARCH)
    idx.close()


def test_delete_purges_the_index(reachable: None) -> None:
    idx = _index()
    idx.index(_A, "search index entry mentioning canary BETA-9")
    idx.delete(_A)
    assert idx.search(_A, "canary BETA-9") == []  # the index is gone -> erased
    idx.close()


def test_soft_delete_leaves_the_residue(reachable: None) -> None:
    idx = _index(soft_delete=True)
    idx.index(_A, "search index entry mentioning canary GAMMA-3")
    idx.delete(_A)  # acknowledged, but the index survives - the Class 11 residue
    assert any("GAMMA-3" in hit for hit in idx.search(_A, "canary GAMMA-3"))
    idx.close()
