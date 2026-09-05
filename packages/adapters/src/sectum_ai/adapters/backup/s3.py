"""Live S3 adapter: a backup / snapshot store backed by an S3-compatible bucket.

A backup export dropped into object storage is the seventh of the spec's "ten
hiding places": tenant data routinely survives a primary-store erasure inside a
snapshot. Each tenant's snapshots live under the key prefix
``{prefix}/{tenant.hex}/`` in one bucket, so a search lists that prefix and a purge
deletes it. Constructing with ``no_erasure=True`` models an immutable / object-lock
/ WORM bucket that exposes no per-tenant purge: ``delete`` raises
``ErasureUnsupported`` so Class 11 records the surface as *attestable-with-caveat*
(data presumed retained) rather than a false erasure PASS - the exact backup reality
the spec's hiding-place #7 is about.

The ``boto3`` client is imported only on the live ``connect`` path (or injected for
the mock-backed test), so the adapter module needs no dependency. The live path
requires the ``boto3`` optional dependency: ``pip install sectum-ai-adapters[boto3]``.
Works against AWS S3 or any S3-compatible store (MinIO, Ceph) via ``endpoint_url``.
"""

import re
from hashlib import sha256
from typing import Any, Self
from uuid import UUID

from sectum_ai.adapters.base import BackupAdapter, Capability
from sectum_ai.spec import AdapterError, ErasureUnsupported

_TOKEN_RE = re.compile(r"[a-z0-9]+")
# S3 caps a single delete_objects request at 1000 keys; boto3's low-level client
# does not auto-batch, so a tenant prefix with more objects must be chunked.
_DELETE_BATCH = 1000


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


class S3Backup(BackupAdapter):
    """A backup / snapshot store backed by an S3-compatible bucket, one key prefix per tenant."""

    def __init__(
        self,
        client: Any,
        bucket: str,
        *,
        name: str = "s3-backup",
        prefix: str = "sectum-ai-backup",
        no_erasure: bool = False,
        soft_delete: bool = False,
    ) -> None:
        capabilities = {Capability.TEXT_SEARCH}
        if soft_delete:
            capabilities.add(Capability.SOFT_DELETE)
        super().__init__(name, frozenset(capabilities))
        self._client = client
        self._bucket = bucket
        self._prefix = prefix
        self._no_erasure = no_erasure
        self._soft_delete = soft_delete
        self._versioned: bool | None = None

    @classmethod
    def connect(
        cls,
        bucket: str,
        *,
        endpoint_url: str | None = None,
        region_name: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        name: str = "s3-backup",
        prefix: str = "sectum-ai-backup",
        no_erasure: bool = False,
        soft_delete: bool = False,
    ) -> Self:
        """Open a boto3 S3 client and return the adapter.

        ``boto3`` is imported here, on the live path only, so the adapter module and
        its mock-backed test do not require it. Credentials fall back to boto3's own
        resolution chain (env / profile / instance role) when not passed explicitly.
        """
        import boto3

        client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region_name,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )
        return cls(
            client,
            bucket,
            name=name,
            prefix=prefix,
            no_erasure=no_erasure,
            soft_delete=soft_delete,
        )

    def _tenant_prefix(self, tenant: UUID) -> str:
        return f"{self._prefix}/{tenant.hex}/"

    def _is_versioned(self) -> bool:
        # On a versioned bucket (Object Lock implies versioning) a plain delete
        # inserts a delete marker and keeps every version; list_objects_v2 then
        # omits the key, so a scan read the retained data as gone and the
        # erasure verified. Versions are listed and deleted explicitly instead.
        if self._versioned is None:
            status = self._client.get_bucket_versioning(Bucket=self._bucket).get("Status")
            self._versioned = status in ("Enabled", "Suspended")
        return self._versioned

    def _objects(self, tenant: UUID) -> list[tuple[str, str | None]]:
        """Every (key, version id) holding the tenant's data; version id None when unversioned."""
        prefix = self._tenant_prefix(tenant)
        objects: list[tuple[str, str | None]] = []
        if self._is_versioned():
            paginator = self._client.get_paginator("list_object_versions")
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                objects.extend(
                    (version["Key"], version["VersionId"]) for version in page.get("Versions", [])
                )
            return objects
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            objects.extend((obj["Key"], None) for obj in page.get("Contents", []))
        return objects

    def add(self, tenant: UUID, text: str) -> None:
        # Key the object by a content hash so re-adding the same snapshot is
        # idempotent (one object per distinct text), and the tenant prefix scopes it.
        digest = sha256(text.encode("utf-8")).hexdigest()
        self._client.put_object(
            Bucket=self._bucket,
            Key=f"{self._tenant_prefix(tenant)}{digest}",
            Body=text.encode("utf-8"),
        )

    def search(self, tenant: UUID, query: str) -> list[str]:
        query_tokens = _tokens(query)
        hits: list[str] = []
        for key, version_id in self._objects(tenant):
            body = self._client.get_object(
                Bucket=self._bucket,
                Key=key,
                **({"VersionId": version_id} if version_id is not None else {}),
            )["Body"].read()
            # tolerate a non-text object under the prefix rather than crashing the scan
            text = body.decode("utf-8", errors="replace")
            if query_tokens & _tokens(text):
                hits.append(text)
        return hits

    def delete(self, tenant: UUID) -> None:
        # An immutable / object-lock bucket has no per-tenant purge: signal it so
        # Class 11 records the surface as attestable-with-caveat, never a false PASS.
        if self._no_erasure:
            raise ErasureUnsupported(
                "the backup bucket is immutable (object-lock/WORM) and exposes no "
                "per-tenant erasure; data is presumed retained until it ages out"
            )
        # A soft-delete backup acknowledges the request but keeps the snapshot - the
        # residue Class 11 erasure verification is built to catch.
        if self._soft_delete:
            return
        objects = self._objects(tenant)
        for start in range(0, len(objects), _DELETE_BATCH):
            batch = objects[start : start + _DELETE_BATCH]
            response = self._client.delete_objects(
                Bucket=self._bucket,
                Delete={
                    "Objects": [
                        {"Key": key, **({"VersionId": vid} if vid is not None else {})}
                        for key, vid in batch
                    ]
                },
            )
            # A per-key failure (a retained version under Object Lock, a denied
            # key) is not a purge; silently continuing let the re-scan decide,
            # and on a versioned bucket the re-scan could not see the version.
            errors = (response or {}).get("Errors") or []
            if errors:
                codes = sorted({str(error.get("Code", "?")) for error in errors})
                raise AdapterError(
                    f"S3 purge left {len(errors)} object(s) in place ({', '.join(codes)}); "
                    "an object-lock / WORM bucket has no per-tenant purge - configure "
                    "`no_erasure: true` so the surface is attestable-with-caveat"
                )
