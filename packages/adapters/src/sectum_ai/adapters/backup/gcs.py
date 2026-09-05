"""Live GCS adapter: a backup / snapshot store backed by a Google Cloud Storage bucket.

The S3 sibling (``sectum_ai.adapters.backup.s3``) covers the same "backup export in
object storage survives a primary-store erasure" hiding place on AWS; this is the
Google-cloud parallel so the backup erasure surface is attestable on GCP, not just
AWS. Each tenant's snapshots live under the object-name prefix ``{prefix}/{tenant.hex}/``
in one bucket, so a search lists that prefix and a purge deletes it. Constructing with
``no_erasure=True`` models a retention-locked / bucket-lock bucket that exposes no
per-tenant purge: ``delete`` raises ``ErasureUnsupported`` so Class 11 records the
surface as *attestable-with-caveat* (data presumed retained) rather than a false
erasure PASS - the same backup reality the S3 adapter guards against.

The ``google-cloud-storage`` client is imported only on the live ``connect`` path (or
injected for the mock-backed test), so the adapter module needs no dependency. The live
path requires the optional dependency: ``pip install sectum-ai-adapters[gcs]``. Point it
at a local fake-gcs-server for testing by exporting ``STORAGE_EMULATOR_HOST`` - the
google-cloud-storage client honours it natively.
"""

import re
from hashlib import sha256
from typing import Any, Self
from uuid import UUID

from sectum_ai.adapters.base import BackupAdapter, Capability
from sectum_ai.spec import ErasureUnsupported

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


class GCSBackup(BackupAdapter):
    """A backup / snapshot store backed by a GCS bucket, one object-name prefix per tenant."""

    def __init__(
        self,
        client: Any,
        bucket: str,
        *,
        name: str = "gcs-backup",
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
        self._bucket_meta: Any | None = None

    @classmethod
    def connect(
        cls,
        bucket: str,
        *,
        project: str | None = None,
        name: str = "gcs-backup",
        prefix: str = "sectum-ai-backup",
        no_erasure: bool = False,
        soft_delete: bool = False,
    ) -> Self:
        """Open a google-cloud-storage client and return the adapter.

        ``google.cloud.storage`` is imported here, on the live path only, so the adapter
        module and its mock-backed test do not require it. Credentials fall back to
        Application Default Credentials (env / gcloud / service account / metadata) when
        ``project`` is not passed; export ``STORAGE_EMULATOR_HOST`` to target a local
        fake-gcs-server instead of real GCS.
        """
        from google.cloud import storage

        client = storage.Client(project=project)
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

    def _meta(self) -> Any:
        if self._bucket_meta is None:
            self._bucket_meta = self._client.get_bucket(self._bucket)
        return self._bucket_meta

    def _is_versioned(self) -> bool:
        return bool(getattr(self._meta(), "versioning_enabled", False))

    def _soft_delete_retention_s(self) -> int:
        # Buckets created since 2024 default to a 7-day soft-delete policy: a
        # deleted object is restorable for that window, which a listing without
        # `soft_deleted=True` cannot see - so the scan read it as purged.
        policy = getattr(self._meta(), "soft_delete_policy", None)
        return int(getattr(policy, "retention_duration_seconds", 0) or 0)

    def _blobs(self, tenant: UUID) -> list[Any]:
        # With object versioning a delete makes the object noncurrent, not gone;
        # list every generation so the scan sees what is retained and the purge
        # removes each one (a blob listed with `versions=True` carries its
        # generation, which its `delete()` then targets).
        prefix = self._tenant_prefix(tenant)
        if self._is_versioned():
            return list(self._client.list_blobs(self._bucket, prefix=prefix, versions=True))
        return list(self._client.list_blobs(self._bucket, prefix=prefix))

    def add(self, tenant: UUID, text: str) -> None:
        # Name the object by a content hash so re-adding the same snapshot is idempotent
        # (one object per distinct text), and the tenant prefix scopes it.
        digest = sha256(text.encode("utf-8")).hexdigest()
        blob = self._client.bucket(self._bucket).blob(f"{self._tenant_prefix(tenant)}{digest}")
        blob.upload_from_string(text.encode("utf-8"))

    def search(self, tenant: UUID, query: str) -> list[str]:
        query_tokens = _tokens(query)
        hits: list[str] = []
        for blob in self._blobs(tenant):
            # tolerate a non-text object under the prefix rather than crashing the scan
            text = blob.download_as_bytes().decode("utf-8", errors="replace")
            if query_tokens & _tokens(text):
                hits.append(text)
        return hits

    def delete(self, tenant: UUID) -> None:
        # A retention-locked / bucket-lock bucket has no per-tenant purge: signal it so
        # Class 11 records the surface as attestable-with-caveat, never a false PASS.
        if self._no_erasure:
            raise ErasureUnsupported(
                "the backup bucket is retention-locked (bucket-lock/hold) and exposes no "
                "per-tenant erasure; data is presumed retained until it ages out"
            )
        # A soft-delete backup acknowledges the request but keeps the snapshot - the
        # residue Class 11 erasure verification is built to catch.
        if self._soft_delete:
            return
        retention = self._soft_delete_retention_s()
        if retention:
            raise ErasureUnsupported(
                f"the backup bucket keeps deleted objects restorable for {retention} s "
                "(a soft-delete policy), so a per-tenant purge is not an erasure; data "
                "is presumed retained until it ages out"
            )
        # GCS deletes are per-object (no bulk delete_objects call, so no 1000-key cap
        # to batch around, unlike the S3 sibling).
        for blob in self._blobs(tenant):
            blob.delete()
