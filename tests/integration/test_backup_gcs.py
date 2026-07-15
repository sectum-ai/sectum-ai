"""Opt-in live integration test for the GCS backup adapter.

Skipped unless ``STORAGE_EMULATOR_HOST`` is set (the engineering spec, section 13:
opt-in live). Point it at a local fake-gcs-server:

    docker run -p 9200:4443 fsouza/fake-gcs-server -scheme http -public-host localhost:9200
    export STORAGE_EMULATOR_HOST=http://localhost:9200

Enable with ``pip install sectum-ai-adapters[gcs]``; the adapter logic itself is
covered offline by ``tests/unit/test_backup_gcs_adapter.py``.
"""

import os
from collections.abc import Iterator
from uuid import UUID

import pytest

from sectum_ai.adapters.backup.gcs import GCSBackup

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("STORAGE_EMULATOR_HOST"),
        reason="set STORAGE_EMULATOR_HOST (e.g. a local fake-gcs-server) to run the live GCS test",
    ),
]

_BUCKET = os.environ.get("SECTUM_GCS_BUCKET", "sectum-backup-it")
_PROJECT = os.environ.get("SECTUM_GCS_PROJECT", "sectum-it")
_PREFIX = "sectum-backup-it"
_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


@pytest.fixture
def gcs_client() -> Iterator[object]:
    try:
        from google.auth.credentials import AnonymousCredentials
        from google.cloud import storage
    except ImportError:
        pytest.skip("google-cloud-storage not installed")
    # the emulator needs no real auth; AnonymousCredentials avoids an ADC lookup
    client = storage.Client(project=_PROJECT, credentials=AnonymousCredentials())
    try:
        try:
            client.create_bucket(_BUCKET)
        except Exception:
            client.get_bucket(_BUCKET)  # already exists
    except Exception as error:
        pytest.skip(f"GCS backend not reachable: {error}")

    def _purge() -> None:
        for blob in client.list_blobs(_BUCKET, prefix=_PREFIX):
            blob.delete()

    _purge()
    yield client
    _purge()


def test_gcs_backup_round_trips_and_erases_against_live_fake_gcs(gcs_client: object) -> None:
    adapter = GCSBackup(gcs_client, _BUCKET, prefix=_PREFIX)
    # tenant B's scope starts empty - read isolation is by name prefix, so B never
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
