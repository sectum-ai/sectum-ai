"""Mock-backed contract tests for the live GCS backup adapter.

GCS is a hosted / networked store, so the adapter's add/search/delete logic is
verified here against an in-memory stand-in for the google-cloud-storage client
(the engineering spec, section 13). The live path is exercised by
``tests/integration/test_backup_gcs.py`` against a fake-gcs-server backend.
"""

from __future__ import annotations

from types import SimpleNamespace
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
    """A blob handle; with ``generation`` set (a ``versions=True`` listing) it names one."""

    def __init__(self, client: _FakeGCS, name: str, generation: int | None = None) -> None:
        self._client = client
        self.name = name
        self.generation = generation

    def upload_from_string(self, data: bytes | str) -> None:
        body = data if isinstance(data, bytes) else data.encode("utf-8")
        self._client._sequence += 1
        self._client._generations.setdefault(self.name, {})[self._client._sequence] = body
        self._client._store[self.name] = body

    def download_as_bytes(self) -> bytes:
        if self.generation is not None:
            return self._client._generations[self.name][self.generation]
        return self._client._store[self.name]

    def delete(self) -> None:
        generations = self._client._generations.get(self.name, {})
        if self.generation is not None:
            generations.pop(self.generation, None)
        elif self._client.versioning_enabled:
            # Object versioning: the current generation becomes noncurrent.
            pass
        else:
            generations.clear()
        self._client._store.pop(self.name, None)
        if not generations:
            self._client._generations.pop(self.name, None)


class _FakeBucket:
    def __init__(self, client: _FakeGCS) -> None:
        self._client = client
        self.versioning_enabled = client.versioning_enabled
        self.soft_delete_policy = SimpleNamespace(
            retention_duration_seconds=client.soft_delete_retention_s
        )

    def blob(self, name: str) -> _FakeBlob:
        return _FakeBlob(self._client, name)


class _FakeGCS:
    """In-memory stand-in for a google-cloud-storage client.

    ``_store`` is the current view (what an unversioned listing returns);
    ``_generations`` the full history object versioning keeps.
    """

    def __init__(self, *, versioned: bool = False, soft_delete_retention_s: int = 0) -> None:
        self._store: dict[str, bytes] = {}
        self._generations: dict[str, dict[int, bytes]] = {}
        self._sequence = 0
        self.versioning_enabled = versioned
        self.soft_delete_retention_s = soft_delete_retention_s

    def bucket(self, name: str) -> _FakeBucket:
        return _FakeBucket(self)

    def get_bucket(self, name: str) -> _FakeBucket:
        return _FakeBucket(self)

    def list_blobs(self, bucket: str, *, prefix: str, versions: bool = False) -> list[_FakeBlob]:
        if versions:
            return [
                _FakeBlob(self, key, generation)
                for key, generations in list(self._generations.items())
                if key.startswith(prefix)
                for generation in list(generations)
            ]
        return [_FakeBlob(self, key) for key in list(self._store) if key.startswith(prefix)]


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
    assert client._generations == {}


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


def test_gcs_backup_purges_every_generation_on_a_versioned_bucket() -> None:
    # With object versioning a delete makes the object noncurrent, not gone, and a
    # listing without versions=True cannot see it - so the erasure verified while
    # the snapshot stayed restorable.
    client = _FakeGCS(versioned=True)
    adapter = _backup(client)
    adapter.add(_TENANT_A, "SECTUM-CANARY-GEN")
    adapter.add(_TENANT_A, "SECTUM-CANARY-GEN")  # a second generation of the same name
    adapter.delete(_TENANT_A)
    assert client._generations == {}
    assert adapter.search(_TENANT_A, "SECTUM-CANARY-GEN") == []


def test_gcs_backup_scan_sees_a_noncurrent_generation() -> None:
    client = _FakeGCS(versioned=True)
    adapter = _backup(client)
    adapter.add(_TENANT_A, "SECTUM-CANARY-NONCURRENT")
    client.bucket(_BUCKET).blob(next(iter(client._store))).delete()  # now noncurrent
    assert client._store == {}
    assert adapter.search(_TENANT_A, "SECTUM-CANARY-NONCURRENT")


def test_gcs_backup_soft_delete_policy_is_attestable_with_caveat() -> None:
    # Buckets created since 2024 default to a 7-day soft-delete policy: a deleted
    # object stays restorable for the window, so a per-tenant purge is not an
    # erasure. The scan could not see it, so the run attested ERASED.
    adapter = _backup(_FakeGCS(soft_delete_retention_s=7 * 86400))
    adapter.add(_TENANT_A, "SECTUM-CANARY-SOFT-POLICY")
    with pytest.raises(ErasureUnsupported, match="soft-delete policy"):
        adapter.delete(_TENANT_A)
