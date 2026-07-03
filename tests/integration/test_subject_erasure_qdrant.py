"""Integration test: A3 data-subject erasure (by id + by content) against live Qdrant.

Proves the `sectum-ai erasure --subject` verification runs end-to-end against a real
vector store, not only the in-memory fake. Requires a Qdrant server (see
compose.yaml) and the ``qdrant`` extra; skips when the server is unavailable, so the
default offline run is unaffected.
"""

import hashlib
import os
import re
import time
from collections.abc import Iterator
from uuid import UUID

import pytest

from sectum_ai.adapters.vector.qdrant import QdrantVectorStore
from sectum_ai.probes import SubjectErasureProbe, SubjectManifest
from sectum_ai.spec import CorpusDocument, CoverageVerdict, Surface

pytestmark = pytest.mark.integration

_HOST = os.environ.get("SECTUM_QDRANT_HOST", "localhost")
_PORT = int(os.environ.get("SECTUM_QDRANT_PORT", "6335"))
_DIM = 64
_TENANT = UUID(int=0xA)


def _embed(text: str) -> list[float]:
    """A deterministic hashing-trick embedding (offline, no model)."""
    vector = [0.0] * _DIM
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        index = int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], "big") % _DIM
        vector[index] += 1.0
    return vector


def _server_ready() -> bool:
    try:
        from qdrant_client import QdrantClient
    except ImportError:
        return False
    for _ in range(10):
        try:
            client = QdrantClient(host=_HOST, port=_PORT)
            client.get_collections()
            client.close()
        except Exception:
            time.sleep(0.5)
        else:
            return True
    return False


@pytest.fixture
def store() -> Iterator[QdrantVectorStore]:
    if not _server_ready():
        pytest.skip("Qdrant backend not reachable")
    instance = QdrantVectorStore(_embed, dim=_DIM, host=_HOST, port=_PORT, prefix="sectum-subj-it")
    instance.delete(_TENANT)
    instance.upsert(
        _TENANT,
        [
            CorpusDocument(
                doc_id=f"doc-{index}",
                tenant_id=_TENANT,
                doc_type="note",
                title=f"record {index}",
                content=f"personal record about Dana Lin item {index}",
            )
            for index in range(3)
        ],
    )
    yield instance
    instance.delete(_TENANT)
    instance.close()


def test_subject_erasure_by_id_against_live_qdrant(store: QdrantVectorStore) -> None:
    # A present id is residual; an already-deleted id is gone - verified by real
    # by-id fetch, not the in-memory fake.
    manifest = SubjectManifest(
        subject_ref="dsr-live-1", records={Surface.VECTOR_DB: ("doc-1", "already-deleted")}
    )
    report = SubjectErasureProbe(vector=store).verify(_TENANT, manifest)
    surface = {s.surface: s for s in report.surfaces}[Surface.VECTOR_DB]
    assert surface.markers_before == 2
    assert surface.residual_after == 1  # doc-1 present, already-deleted gone
    assert report.coverage()[Surface.VECTOR_DB] is CoverageVerdict.RESIDUAL


def test_subject_erasure_fingerprint_against_live_qdrant(store: QdrantVectorStore) -> None:
    # The subject's content still surfaces via a real semantic query -> RESIDUAL.
    residual = SubjectErasureProbe(vector=store).verify(
        _TENANT,
        SubjectManifest(
            subject_ref="dsr-live-2", records={}, fingerprints={Surface.VECTOR_DB: ("Dana Lin",)}
        ),
    )
    assert residual.coverage()[Surface.VECTOR_DB] is CoverageVerdict.RESIDUAL
    assert residual.findings and "fingerprint" in residual.findings[0].finding_id

    # A phrase that appears in no document reads clean (best-effort ERASED).
    clean = SubjectErasureProbe(vector=store).verify(
        _TENANT,
        SubjectManifest(
            subject_ref="dsr-live-3",
            records={},
            fingerprints={Surface.VECTOR_DB: ("zzxq nonexistent 90218",)},
        ),
    )
    assert clean.coverage()[Surface.VECTOR_DB] is CoverageVerdict.ERASED
