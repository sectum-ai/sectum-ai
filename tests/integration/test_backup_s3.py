"""Opt-in live integration test for the S3 backup adapter.

Skipped unless ``SECTUM_S3_ENDPOINT`` is set (the engineering spec, section 13:
opt-in live). Point it at any S3-compatible store - e.g. a local MinIO:

    docker run -p 9100:9000 -e MINIO_ROOT_USER=minioadmin \\
        -e MINIO_ROOT_PASSWORD=minioadmin minio/minio server /data
    export SECTUM_S3_ENDPOINT=http://localhost:9100

Enable with ``pip install sectum-ai-adapters[boto3]``; the adapter logic itself is
covered offline by ``tests/unit/test_backup_s3.py``.
"""

import os
from collections.abc import Iterator
from uuid import UUID

import pytest

from sectum_ai.adapters.backup.s3 import S3Backup

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("SECTUM_S3_ENDPOINT"),
        reason="set SECTUM_S3_ENDPOINT (e.g. a local MinIO) to run the live S3 test",
    ),
]

_ENDPOINT = os.environ.get("SECTUM_S3_ENDPOINT", "")
_BUCKET = os.environ.get("SECTUM_S3_BUCKET", "sectum-backup-it")
_ACCESS_KEY = os.environ.get("SECTUM_S3_ACCESS_KEY", "minioadmin")
_SECRET_KEY = os.environ.get("SECTUM_S3_SECRET_KEY", "minioadmin")
_PREFIX = "sectum-backup-it"
_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


@pytest.fixture
def s3_client() -> Iterator[object]:
    try:
        import boto3
    except ImportError:
        pytest.skip("boto3 not installed")
    client = boto3.client(
        "s3",
        endpoint_url=_ENDPOINT,
        aws_access_key_id=_ACCESS_KEY,
        aws_secret_access_key=_SECRET_KEY,
        region_name="us-east-1",
    )
    try:
        client.create_bucket(Bucket=_BUCKET)
    except Exception:
        # already exists (owned by us) or the endpoint is unreachable
        try:
            client.head_bucket(Bucket=_BUCKET)
        except Exception as error:
            pytest.skip(f"S3 backend not reachable: {error}")

    def _purge() -> None:
        paginator = client.get_paginator("list_objects_v2")
        keys = [
            obj["Key"]
            for page in paginator.paginate(Bucket=_BUCKET, Prefix=_PREFIX)
            for obj in page.get("Contents", [])
        ]
        if keys:
            client.delete_objects(Bucket=_BUCKET, Delete={"Objects": [{"Key": k} for k in keys]})

    _purge()
    yield client
    _purge()


def test_s3_backup_round_trips_and_erases_against_live_minio(s3_client: object) -> None:
    adapter = S3Backup(s3_client, _BUCKET, prefix=_PREFIX)
    # tenant B's scope starts empty - read isolation is by key prefix, so B never
    # sees A's snapshot regardless of the keyword-overlap search.
    assert adapter.search(_TENANT_B, "SECTUM-CANARY-AAA") == []

    adapter.add(_TENANT_A, "backup snapshot mentioning SECTUM-CANARY-AAA")
    hits = adapter.search(_TENANT_A, "SECTUM-CANARY-AAA")
    assert hits and "SECTUM-CANARY-AAA" in hits[0]
    # A now has data, but B's prefix is still separate - nothing surfaces in B
    assert adapter.search(_TENANT_B, "SECTUM-CANARY-AAA") == []

    adapter.add(_TENANT_B, "backup snapshot mentioning SECTUM-CANARY-BBB")
    adapter.delete(_TENANT_A)
    assert adapter.search(_TENANT_A, "SECTUM-CANARY-AAA") == []
    # tenant B's snapshot survives A's erasure (per-tenant purge, not a bucket wipe)
    assert adapter.search(_TENANT_B, "SECTUM-CANARY-BBB")
