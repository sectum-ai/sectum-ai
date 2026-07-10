"""Integration test: A3 subject-erasure fingerprinting against the live derived surfaces.

Proves `SubjectErasureProbe` fingerprints a real subject's content on the agent-memory
store (live Redis) and the derived full-text search index (live OpenSearch), not only
the in-memory fakes. Each backend guards on its own reachability, so the default
offline run is unaffected (see compose.yaml).
"""

import os
from collections.abc import Iterator
from uuid import UUID

import pytest

from sectum_ai.probes import SubjectErasureProbe, SubjectManifest
from sectum_ai.spec import CoverageVerdict, Surface

pytestmark = pytest.mark.integration

_TENANT = UUID(int=0xA)
_PHRASE = "personal record about Dana Lin"

_REDIS_HOST = os.environ.get("SECTUM_REDIS_HOST", "localhost")
_REDIS_PORT = int(os.environ.get("SECTUM_REDIS_PORT", "6380"))
_REDIS_PREFIX = "sectum-subj-mem-it"

_OS_HOST = os.environ.get("SECTUM_OPENSEARCH_HOST", "localhost")
_OS_PORT = int(os.environ.get("SECTUM_OPENSEARCH_PORT", "9201"))
_OS_PREFIX = "sectum-subj-search-it"


@pytest.fixture
def memory() -> Iterator[object]:
    import redis

    from sectum_ai.adapters.memory.redis import RedisMemory

    conn = redis.Redis(host=_REDIS_HOST, port=_REDIS_PORT, decode_responses=True)
    try:
        conn.ping()
    except redis.RedisError as error:
        conn.close()
        pytest.skip(f"Redis backend not reachable: {error}")

    def _flush() -> None:
        keys = list(conn.scan_iter(match=f"{_REDIS_PREFIX}:*"))
        if keys:
            conn.delete(*keys)

    _flush()
    instance = RedisMemory(_REDIS_HOST, _REDIS_PORT, prefix=_REDIS_PREFIX)
    yield instance
    _flush()
    conn.close()


@pytest.fixture
def search_index() -> Iterator[object]:
    try:
        from opensearchpy import OpenSearch
    except ImportError:
        pytest.skip("opensearch-py not installed")
    from sectum_ai.adapters.search_index.opensearch import OpenSearchSearchIndex

    client = OpenSearch(
        hosts=[{"host": _OS_HOST, "port": _OS_PORT}], use_ssl=False, verify_certs=False
    )
    try:
        client.info()
    except Exception:
        client.close()
        pytest.skip("OpenSearch backend not reachable")

    def _cleanup() -> None:
        client.indices.delete(index=f"{_OS_PREFIX}-*", ignore_unavailable=True)

    _cleanup()
    instance = OpenSearchSearchIndex(_OS_HOST, _OS_PORT, prefix=_OS_PREFIX)
    yield instance
    _cleanup()
    instance.close()
    client.close()


def test_subject_erasure_memory_fingerprint_against_live_redis(memory: object) -> None:
    memory.remember(_TENANT, _PHRASE + " item 1")  # type: ignore[attr-defined]

    residual = SubjectErasureProbe(memory=memory).verify(  # type: ignore[arg-type]
        _TENANT,
        SubjectManifest(
            subject_ref="dsr-mem-1", records={}, fingerprints={Surface.AGENT_MEMORY: (_PHRASE,)}
        ),
    )
    assert residual.coverage()[Surface.AGENT_MEMORY] is CoverageVerdict.RESIDUAL
    assert residual.findings and "fingerprint" in residual.findings[0].finding_id

    memory.delete(_TENANT)  # type: ignore[attr-defined]
    clean = SubjectErasureProbe(memory=memory).verify(  # type: ignore[arg-type]
        _TENANT,
        SubjectManifest(
            subject_ref="dsr-mem-2", records={}, fingerprints={Surface.AGENT_MEMORY: (_PHRASE,)}
        ),
    )
    assert clean.coverage()[Surface.AGENT_MEMORY] is CoverageVerdict.ERASED


def test_subject_erasure_search_fingerprint_against_live_opensearch(search_index: object) -> None:
    search_index.index(_TENANT, _PHRASE + " item 1")  # type: ignore[attr-defined]

    residual = SubjectErasureProbe(search_index=search_index).verify(  # type: ignore[arg-type]
        _TENANT,
        SubjectManifest(
            subject_ref="dsr-si-1", records={}, fingerprints={Surface.SEARCH_INDEX: (_PHRASE,)}
        ),
    )
    assert residual.coverage()[Surface.SEARCH_INDEX] is CoverageVerdict.RESIDUAL
    assert residual.findings and "fingerprint" in residual.findings[0].finding_id

    search_index.delete(_TENANT)  # type: ignore[attr-defined]
    clean = SubjectErasureProbe(search_index=search_index).verify(  # type: ignore[arg-type]
        _TENANT,
        SubjectManifest(
            subject_ref="dsr-si-2", records={}, fingerprints={Surface.SEARCH_INDEX: (_PHRASE,)}
        ),
    )
    assert clean.coverage()[Surface.SEARCH_INDEX] is CoverageVerdict.ERASED
