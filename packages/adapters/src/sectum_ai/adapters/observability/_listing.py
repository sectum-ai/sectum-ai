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


# OTLP-JSON has no standard paging field, so the OTel query contract names its
# own. Any of these, truthy, means the store returned a partial page.
_TRUNCATION_KEYS = ("truncated", "nextPageToken", "next_page_token", "nextLink")


def _refuse_truncated(payload: Any, backend: str) -> None:
    """Refuse a miss on a page the backend itself flagged as partial.

    The counting guard `_refuse_capped` gives the five other trace backends does
    not transfer: this one reads a caller-supplied store through a contract with
    no cap to count against. So the contract asks the store to say so instead,
    and a store that does not answer the question cannot be caught here - which
    the module docstring states rather than leaving implied.
    """
    if not isinstance(payload, dict):
        return
    for key in _TRUNCATION_KEYS:
        if payload.get(key):
            raise AdapterError(
                f"{backend} returned a partial page ({key}), so a marker beyond it cannot "
                "be told apart from an erased one; narrow the tenant's window or page fully"
            )
