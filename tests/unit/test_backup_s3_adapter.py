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


class _FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class _FakeS3:
    """In-memory stand-in for a boto3 S3 client (one flat key->body store)."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}
        self.delete_batch_sizes: list[int] = []

    def get_paginator(self, name: str) -> _FakePaginator:
        assert name == "list_objects_v2"
        return _FakePaginator(self._store)

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:
        self._store[Key] = Body

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        return {"Body": _FakeBody(self._store[Key])}

    def delete_objects(self, *, Bucket: str, Delete: dict[str, Any]) -> None:
        objects = Delete["Objects"]
        # S3 rejects a delete_objects request with more than 1000 keys
        assert len(objects) <= 1000, "delete_objects must be batched at <=1000 keys"
        self.delete_batch_sizes.append(len(objects))
        for obj in objects:
            self._store.pop(obj["Key"], None)


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
