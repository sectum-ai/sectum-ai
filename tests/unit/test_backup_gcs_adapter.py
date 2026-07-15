"""Mock-backed contract tests for the live GCS backup adapter.

GCS is a hosted / networked store, so the adapter's add/search/delete logic is
verified here against an in-memory stand-in for the google-cloud-storage client
(the engineering spec, section 13). The live path is exercised by
``tests/integration/test_backup_gcs.py`` against a fake-gcs-server backend.
"""

from typing import Any
from uuid import UUID

import pytest

from sectum_ai.adapters.backup.gcs import GCSBackup
from sectum_ai.adapters.base import BackupAdapter, Capability
from sectum_ai.spec import ErasureUnsupported

_BUCKET = "sectum-backups"
_PREFIX = "sectum-ai-backup"
_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


class _FakeBlob:
    def __init__(self, store: dict[str, bytes], name: str) -> None:
        self._store = store
        self.name = name

    def upload_from_string(self, data: bytes | str) -> None:
        self._store[self.name] = data if isinstance(data, bytes) else data.encode("utf-8")

    def download_as_bytes(self) -> bytes:
        return self._store[self.name]

    def delete(self) -> None:
        self._store.pop(self.name, None)


class _FakeBucket:
    def __init__(self, store: dict[str, bytes]) -> None:
        self._store = store

    def blob(self, name: str) -> _FakeBlob:
        return _FakeBlob(self._store, name)


class _FakeGCS:
    """In-memory stand-in for a google-cloud-storage client (one flat name->body store)."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    def bucket(self, name: str) -> _FakeBucket:
        return _FakeBucket(self._store)

    def list_blobs(self, bucket: str, *, prefix: str) -> list[_FakeBlob]:
        return [_FakeBlob(self._store, key) for key in list(self._store) if key.startswith(prefix)]


def _backup(client: _FakeGCS, **kwargs: Any) -> GCSBackup:
    return GCSBackup(client, _BUCKET, prefix=_PREFIX, **kwargs)


def test_gcs_backup_conforms_and_reports_text_search() -> None:
    adapter = _backup(_FakeGCS())
    assert isinstance(adapter, BackupAdapter)
    assert adapter.supports(Capability.TEXT_SEARCH)


def test_gcs_backup_add_and_search_are_scoped_to_a_tenant_prefix() -> None:
    client = _FakeGCS()
    adapter = _backup(client)
    adapter.add(_TENANT_A, "snapshot mentioning SECTUM-CANARY-AAA")
    hits = adapter.search(_TENANT_A, "SECTUM-CANARY-AAA")
    assert hits and "SECTUM-CANARY-AAA" in hits[0]
    # tenant B's prefix is separate, so the marker never surfaces in B's scope
    assert adapter.search(_TENANT_B, "SECTUM-CANARY-AAA") == []
    # the object landed under the tenant's own prefix
    assert all(key.startswith(f"{_PREFIX}/{_TENANT_A.hex}/") for key in client._store)


def test_gcs_backup_add_is_idempotent_for_the_same_text() -> None:
    client = _FakeGCS()
    adapter = _backup(client)
    adapter.add(_TENANT_A, "same snapshot")
    adapter.add(_TENANT_A, "same snapshot")
    assert len(client._store) == 1  # content-hash name dedupes


def test_gcs_backup_search_returns_nothing_when_the_marker_is_absent() -> None:
    client = _FakeGCS()
    adapter = _backup(client)
    adapter.add(_TENANT_A, "a benign snapshot")
    assert adapter.search(_TENANT_A, "SECTUM-CANARY-AAA") == []


def test_gcs_backup_delete_purges_a_tenants_objects() -> None:
    client = _FakeGCS()
    adapter = _backup(client)
    adapter.add(_TENANT_A, "SECTUM-CANARY-DEL")
    adapter.add(_TENANT_B, "SECTUM-CANARY-KEEP")
    adapter.delete(_TENANT_A)
    assert adapter.search(_TENANT_A, "SECTUM-CANARY-DEL") == []
    # another tenant's snapshot is untouched
    assert adapter.search(_TENANT_B, "SECTUM-CANARY-KEEP")


def test_gcs_backup_delete_removes_every_object_under_the_prefix() -> None:
    # GCS deletes are per-object; a tenant prefix with many snapshots is fully purged.
    client = _FakeGCS()
    adapter = _backup(client)
    for index in range(50):
        adapter.add(_TENANT_A, f"snapshot number {index}")
    adapter.delete(_TENANT_A)
    assert client._store == {}  # every object purged, one delete() per blob


def test_gcs_backup_soft_delete_leaves_the_snapshot() -> None:
    client = _FakeGCS()
    adapter = _backup(client, soft_delete=True)
    adapter.add(_TENANT_A, "SECTUM-CANARY-SOFT")
    adapter.delete(_TENANT_A)
    assert adapter.supports(Capability.SOFT_DELETE)
    assert adapter.search(_TENANT_A, "SECTUM-CANARY-SOFT")  # the residue survives


def test_gcs_backup_no_erasure_reports_attestable_with_caveat() -> None:
    # A retention-locked / bucket-lock bucket exposes no per-tenant purge: delete raises
    # ErasureUnsupported so Class 11 records attestable-with-caveat, never a PASS.
    adapter = _backup(_FakeGCS(), no_erasure=True)
    with pytest.raises(ErasureUnsupported):
        adapter.delete(_TENANT_A)
