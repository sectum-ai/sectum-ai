"""Mock-backed contract tests for the live S3 backup adapter.

S3 is a hosted / networked store, so the adapter's add/search/delete logic is
verified here against an in-memory stand-in for the boto3 S3 client (the
engineering spec, section 13). The live path is exercised by
``tests/integration/test_backup_s3.py`` against a MinIO backend.
"""

from typing import Any
from uuid import UUID

import pytest

from sectum_ai.adapters.backup.s3 import S3Backup
from sectum_ai.adapters.base import BackupAdapter, Capability
from sectum_ai.spec import ErasureUnsupported

_BUCKET = "sectum-backups"
_PREFIX = "sectum-ai-backup"
_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


class _FakePaginator:
    def __init__(self, store: dict[str, bytes]) -> None:
        self._store = store

    def paginate(self, *, Bucket: str, Prefix: str) -> Any:
        contents = [{"Key": key} for key in self._store if key.startswith(Prefix)]
        # split across two pages to exercise the paginator loop
        yield {"Contents": contents[:1]}
        if contents[1:]:
            yield {"Contents": contents[1:]}


class _FakeVersionPaginator:
    """`list_object_versions`: every version and delete marker under the prefix."""

    def __init__(self, versions: dict[str, list[tuple[str, bytes | None]]]) -> None:
        self._versions = versions

    def paginate(self, *, Bucket: str, Prefix: str) -> Any:
        page: dict[str, list[dict[str, str]]] = {"Versions": [], "DeleteMarkers": []}
        for key, history in self._versions.items():
            if not key.startswith(Prefix):
                continue
            for version_id, body in history:
                entry = {"Key": key, "VersionId": version_id}
                page["DeleteMarkers" if body is None else "Versions"].append(entry)
        yield page


class _FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class _FakeS3:
    """In-memory stand-in for a boto3 S3 client.

    ``versioned=True`` models a bucket with versioning (as Object Lock implies): a
    delete without a VersionId inserts a delete marker and keeps every version,
    and ``list_objects_v2`` hides a key whose newest version is a marker - so the
    ``_store`` the unversioned tests read is the *current* view, while
    ``_versions`` holds the history.
    """

    def __init__(self, *, versioned: bool = False, refuse: set[str] | None = None) -> None:
        self._store: dict[str, bytes] = {}
        self._versions: dict[str, list[tuple[str, bytes | None]]] = {}
        self._versioned = versioned
        self._refuse = refuse or set()
        self._sequence = 0
        self.delete_batch_sizes: list[int] = []

    def get_bucket_versioning(self, *, Bucket: str) -> dict[str, Any]:
        return {"Status": "Enabled"} if self._versioned else {}

    def get_paginator(self, name: str) -> Any:
        if name == "list_object_versions":
            return _FakeVersionPaginator(self._versions)
        assert name == "list_objects_v2"
        return _FakePaginator(self._store)

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:
        self._store[Key] = Body
        self._sequence += 1
        self._versions.setdefault(Key, []).append((f"v{self._sequence}", Body))

    def get_object(self, *, Bucket: str, Key: str, VersionId: str | None = None) -> dict[str, Any]:
        if VersionId is None:
            return {"Body": _FakeBody(self._store[Key])}
        body = next(b for vid, b in self._versions[Key] if vid == VersionId)
        assert body is not None
        return {"Body": _FakeBody(body)}

    def delete_objects(self, *, Bucket: str, Delete: dict[str, Any]) -> dict[str, Any]:
        objects = Delete["Objects"]
        # S3 rejects a delete_objects request with more than 1000 keys
        assert len(objects) <= 1000, "delete_objects must be batched at <=1000 keys"
        self.delete_batch_sizes.append(len(objects))
        errors: list[dict[str, str]] = []
        for obj in objects:
            key, version_id = obj["Key"], obj.get("VersionId")
            if key in self._refuse:
                errors.append({"Key": key, "Code": "AccessDenied"})
                continue
            if version_id is not None:
                self._versions[key] = [(v, b) for v, b in self._versions[key] if v != version_id]
                if not any(b is not None for _, b in self._versions[key]):
                    self._store.pop(key, None)
                    self._versions.pop(key, None)
            elif self._versioned:
                self._sequence += 1
                self._versions[key].append((f"v{self._sequence}", None))
                self._store.pop(key, None)
            else:
                self._store.pop(key, None)
                self._versions.pop(key, None)
        return {"Errors": errors} if errors else {}


def _backup(client: _FakeS3, **kwargs: Any) -> S3Backup:
    return S3Backup(client, _BUCKET, prefix=_PREFIX, **kwargs)


def test_s3_backup_conforms_and_reports_text_search() -> None:
    adapter = _backup(_FakeS3())
    assert isinstance(adapter, BackupAdapter)
    assert adapter.supports(Capability.TEXT_SEARCH)


def test_s3_backup_add_and_search_are_scoped_to_a_tenant_prefix() -> None:
    client = _FakeS3()
    adapter = _backup(client)
    adapter.add(_TENANT_A, "snapshot mentioning SECTUM-CANARY-AAA")
    hits = adapter.search(_TENANT_A, "SECTUM-CANARY-AAA")
    assert hits and "SECTUM-CANARY-AAA" in hits[0]
    # tenant B's prefix is separate, so the marker never surfaces in B's scope
    assert adapter.search(_TENANT_B, "SECTUM-CANARY-AAA") == []
    # the object landed under the tenant's own prefix
    assert all(key.startswith(f"{_PREFIX}/{_TENANT_A.hex}/") for key in client._store)


def test_s3_backup_add_is_idempotent_for_the_same_text() -> None:
    client = _FakeS3()
    adapter = _backup(client)
    adapter.add(_TENANT_A, "same snapshot")
    adapter.add(_TENANT_A, "same snapshot")
    assert len(client._store) == 1  # content-hash key dedupes


def test_s3_backup_search_returns_nothing_when_the_marker_is_absent() -> None:
    client = _FakeS3()
    adapter = _backup(client)
    adapter.add(_TENANT_A, "a benign snapshot")
    assert adapter.search(_TENANT_A, "SECTUM-CANARY-AAA") == []


def test_s3_backup_delete_purges_a_tenants_objects() -> None:
    client = _FakeS3()
    adapter = _backup(client)
    adapter.add(_TENANT_A, "SECTUM-CANARY-DEL")
    adapter.add(_TENANT_B, "SECTUM-CANARY-KEEP")
    adapter.delete(_TENANT_A)
    assert adapter.search(_TENANT_A, "SECTUM-CANARY-DEL") == []
    # another tenant's snapshot is untouched
    assert adapter.search(_TENANT_B, "SECTUM-CANARY-KEEP")


def test_s3_backup_soft_delete_leaves_the_snapshot() -> None:
    client = _FakeS3()
    adapter = _backup(client, soft_delete=True)
    adapter.add(_TENANT_A, "SECTUM-CANARY-SOFT")
    adapter.delete(_TENANT_A)
    assert adapter.supports(Capability.SOFT_DELETE)
    assert adapter.search(_TENANT_A, "SECTUM-CANARY-SOFT")  # the residue survives


def test_s3_backup_no_erasure_reports_attestable_with_caveat() -> None:
    # An immutable / object-lock bucket exposes no per-tenant purge: delete raises
    # ErasureUnsupported so Class 11 records attestable-with-caveat, never a PASS.
    adapter = _backup(_FakeS3(), no_erasure=True)
    with pytest.raises(ErasureUnsupported):
        adapter.delete(_TENANT_A)


def test_s3_backup_delete_batches_beyond_the_1000_key_cap() -> None:
    # S3 rejects a delete_objects request with more than 1000 keys, so a tenant
    # prefix holding more than that must be purged in <=1000-key batches.
    client = _FakeS3()
    adapter = _backup(client)
    for index in range(1001):
        adapter.add(_TENANT_A, f"snapshot number {index}")
    adapter.delete(_TENANT_A)
    assert client._store == {}  # every object purged
    assert client.delete_batch_sizes and max(client.delete_batch_sizes) <= 1000
    assert sum(client.delete_batch_sizes) == 1001


def test_s3_backup_purges_every_version_on_a_versioned_bucket() -> None:
    # On a versioned bucket a plain delete inserts a delete marker and keeps
    # every version; list_objects_v2 then omits the key, so the post-erasure scan
    # read the retained snapshot as gone and the erasure verified.
    client = _FakeS3(versioned=True)
    adapter = _backup(client)
    adapter.add(_TENANT_A, "SECTUM-CANARY-VER")
    adapter.add(_TENANT_A, "SECTUM-CANARY-VER")  # a second version of the same key
    adapter.delete(_TENANT_A)
    assert client._versions == {}, "every version, not a delete marker, must go"
    assert adapter.search(_TENANT_A, "SECTUM-CANARY-VER") == []


def test_s3_backup_scan_sees_a_retained_noncurrent_version() -> None:
    # The scan reads versions, so data hidden behind a delete marker is residue.
    client = _FakeS3(versioned=True)
    adapter = _backup(client)
    adapter.add(_TENANT_A, "SECTUM-CANARY-HIDDEN")
    key = next(iter(client._store))
    client.delete_objects(Bucket=_BUCKET, Delete={"Objects": [{"Key": key}]})  # a marker
    assert key not in client._store
    assert adapter.search(_TENANT_A, "SECTUM-CANARY-HIDDEN")


def test_s3_backup_delete_refuses_a_partial_purge() -> None:
    # A per-key error in delete_objects (a version under Object Lock, a denied
    # key) was never read: the purge "succeeded" and the re-scan decided.
    from sectum_ai.spec import AdapterError

    client = _FakeS3()
    adapter = _backup(client)
    adapter.add(_TENANT_A, "SECTUM-CANARY-LOCKED")
    client._refuse = set(client._store)
    with pytest.raises(AdapterError, match="no_erasure"):
        adapter.delete(_TENANT_A)
