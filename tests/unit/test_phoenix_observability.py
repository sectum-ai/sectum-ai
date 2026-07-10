"""Unit tests for the live Phoenix observability adapter (with a mocked client).

These tests cover paths the docker-backed integration suite cannot easily
exercise (e.g. the ``delete`` 404 idempotency under a contrived error). They
do not connect to a Phoenix backend.
"""

from unittest.mock import MagicMock
from uuid import UUID

import httpx
import pytest

from sectum_ai.adapters.observability.phoenix import PhoenixObservability

_TENANT = UUID(int=0xA)


def _adapter_with_mock_client() -> tuple[PhoenixObservability, MagicMock]:
    adapter = PhoenixObservability("http://example", prefix="t")
    mock_client = MagicMock()
    adapter._client = mock_client
    return adapter, mock_client


def test_phoenix_delete_swallows_a_404() -> None:
    """A 404 from the underlying client (project gone) is the no-op contract."""
    adapter, client = _adapter_with_mock_client()
    response = httpx.Response(status_code=404)
    request = httpx.Request("POST", "http://example")
    client.projects.delete.side_effect = httpx.HTTPStatusError(
        "not found", request=request, response=response
    )
    adapter.delete(_TENANT)  # must not raise
    client.projects.delete.assert_called_once()


def test_phoenix_delete_propagates_non_404_errors() -> None:
    """Non-404 errors (transport failure, 5xx) propagate, never silently swallowed."""
    adapter, client = _adapter_with_mock_client()
    response = httpx.Response(status_code=500)
    request = httpx.Request("POST", "http://example")
    client.projects.delete.side_effect = httpx.HTTPStatusError(
        "server error", request=request, response=response
    )
    with pytest.raises(httpx.HTTPStatusError):
        adapter.delete(_TENANT)


def test_phoenix_fetch_trace_finds_a_trace_by_id() -> None:
    adapter, client = _adapter_with_mock_client()
    client.projects.list.return_value = [{"name": f"t-{_TENANT.hex}"}]
    client.spans.get_spans.return_value = [
        {"context": {"trace_id": "trace-xyz"}, "name": "span", "attributes": {}}
    ]
    hit = adapter.fetch_trace(_TENANT, "trace-xyz")
    assert hit is not None and hit.trace_id == "trace-xyz"
    assert adapter.fetch_trace(_TENANT, "missing-trace") is None


def test_phoenix_fetch_trace_none_when_tenant_has_no_project() -> None:
    adapter, client = _adapter_with_mock_client()
    client.projects.list.return_value = []  # tenant has no project -> no scan, no hit
    assert adapter.fetch_trace(_TENANT, "trace-xyz") is None
