"""Integration tests for the live Phoenix observability adapter.

Requires a Phoenix server (see compose.yaml). The ``adapter`` fixture skips the
tests when no server is reachable, so the default test run stays offline.
"""

import contextlib
import os
import secrets
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from phoenix.client import Client
from phoenix.client.__generated__ import v1

from sectum_ai.adapters.base import TraceHit
from sectum_ai.adapters.observability.phoenix import PhoenixObservability

pytestmark = pytest.mark.integration

_HOST = os.environ.get("SECTUM_PHOENIX_HOST", "localhost")
_PORT = int(os.environ.get("SECTUM_PHOENIX_PORT", "6007"))
_BASE_URL = f"http://{_HOST}:{_PORT}"
_PREFIX = "sectum-it"
_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


def _project(tenant: UUID) -> str:
    return f"{_PREFIX}-{tenant.hex}"


def _seed(client: Client, tenant: UUID, text: str) -> None:
    """Log a one-span trace containing ``text`` into the tenant's project."""
    now = datetime.now(UTC).isoformat()
    span: v1.Span = {
        "name": "sectum-probe",
        "context": {"trace_id": secrets.token_hex(16), "span_id": secrets.token_hex(8)},
        "span_kind": "LLM",
        "start_time": now,
        "end_time": now,
        "status_code": "OK",
        "attributes": {"output.value": text},
    }
    client.spans.log_spans(project_identifier=_project(tenant), spans=[span])


def _cleanup(client: Client) -> None:
    for tenant in (_TENANT_A, _TENANT_B):
        with contextlib.suppress(httpx.HTTPError):
            client.projects.delete(project_name=_project(tenant))


def _search_with_retry(adapter: PhoenixObservability, tenant: UUID, marker: str) -> list[TraceHit]:
    # Phoenix queues span ingestion, so a freshly logged span is not visible at
    # once; poll briefly for it.
    for _ in range(20):
        hits = adapter.search_traces(tenant, marker)
        if hits:
            return hits
        time.sleep(0.5)
    return []


@pytest.fixture
def adapter() -> Iterator[PhoenixObservability]:
    client = Client(base_url=_BASE_URL)
    try:
        client.projects.list()
    except httpx.HTTPError as error:
        pytest.skip(f"Phoenix backend not reachable: {error}")
    _cleanup(client)
    yield PhoenixObservability(_BASE_URL, prefix=_PREFIX)
    _cleanup(client)


def test_phoenix_search_finds_a_seeded_marker(adapter: PhoenixObservability) -> None:
    _seed(Client(base_url=_BASE_URL), _TENANT_A, "the output mentions SECTUM-CANARY-AAA here")
    hits = _search_with_retry(adapter, _TENANT_A, "SECTUM-CANARY-AAA")
    assert hits
    assert all(hit.project == _project(_TENANT_A) for hit in hits)
    assert "SECTUM-CANARY-AAA" in hits[0].snippet


def test_phoenix_search_is_scoped_to_a_tenant(adapter: PhoenixObservability) -> None:
    _seed(Client(base_url=_BASE_URL), _TENANT_A, "tenant A holds SECTUM-CANARY-AAA")
    assert _search_with_retry(adapter, _TENANT_A, "SECTUM-CANARY-AAA")
    # tenant B has no project, so the marker never surfaces in B's scope
    assert adapter.search_traces(_TENANT_B, "SECTUM-CANARY-AAA") == []


def test_phoenix_lists_projects(adapter: PhoenixObservability) -> None:
    _seed(Client(base_url=_BASE_URL), _TENANT_A, "a recorded trace")
    assert _search_with_retry(adapter, _TENANT_A, "a recorded trace")
    assert _project(_TENANT_A) in adapter.list_projects()


def test_phoenix_delete_clears_a_tenants_project(adapter: PhoenixObservability) -> None:
    _seed(Client(base_url=_BASE_URL), _TENANT_A, "the output mentions SECTUM-CANARY-DEL")
    assert _search_with_retry(adapter, _TENANT_A, "SECTUM-CANARY-DEL")
    adapter.delete(_TENANT_A)
    # after delete the tenant's project is gone, so a search returns nothing
    assert adapter.search_traces(_TENANT_A, "SECTUM-CANARY-DEL") == []


def test_phoenix_delete_is_idempotent_when_no_project_exists(
    adapter: PhoenixObservability,
) -> None:
    # delete on a tenant that was never seeded must not raise (the 404 is swallowed)
    adapter.delete(_TENANT_B)
    assert adapter.search_traces(_TENANT_B, "anything") == []
