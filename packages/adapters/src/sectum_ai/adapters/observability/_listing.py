"""Shared guards for the trace backends' single-page listings."""

from __future__ import annotations

from typing import Any

from sectum_ai.spec import AdapterError


def _refuse_capped(backend: str, seen: int, cap: int) -> None:
    """Refuse a by-id miss on a listing that may have been truncated.

    The A3 subject check reads ``fetch_trace(...) is None`` as "the trace is
    gone", so a subject beyond a backend's page cap attested erased.
    """
    if seen >= cap:
        raise AdapterError(
            f"{backend} listed {seen} traces, its page cap, so a trace beyond it cannot "
            "be told apart from an erased one; narrow the tenant's window or raise the cap"
        )


def _data_list(payload: Any, backend: str) -> list[Any]:
    """The ``data`` list of a search response; an error envelope is not an empty tenant."""
    if not isinstance(payload, dict):
        raise AdapterError(f"{backend} search response is not a JSON object")
    for key in ("error", "errors"):
        if payload.get(key):
            raise AdapterError(f"{backend} search returned an error: {str(payload[key])[:200]}")
    data = payload.get("data")
    if not isinstance(data, list):
        raise AdapterError(f"{backend} search response carries no 'data' list")
    return data
