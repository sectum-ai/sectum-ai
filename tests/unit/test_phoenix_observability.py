"""Unit tests for the live Phoenix observability adapter (with a mocked client).

These tests cover paths the docker-backed integration suite cannot easily
exercise (e.g. the ``delete`` 404 idempotency under a contrived error). They
do not connect to a Phoenix backend.
"""

from unittest.mock import MagicMock
from uuid import UUID

import httpx
import pytest

from sectum.adapters.observability.phoenix import PhoenixObservability

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
