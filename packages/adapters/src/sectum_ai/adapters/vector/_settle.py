"""Bounded wait for a hosted store to reflect a write.

Pinecone and Azure AI Search index asynchronously: a probe that queried right
after an upsert saw nothing (no baseline, INCONCLUSIVE), and one that re-scanned
right after a delete saw the not-yet-purged vectors as a RESIDUAL erasure
failure - the wrong direction for a signed attestation. The integration tests
polled; the adapters did not.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from sectum_ai.spec import AdapterError

_SETTLE_TRIES = 30
_SETTLE_INTERVAL_S = 1.0


def settle(ready: Callable[[], bool], what: str) -> None:
    """Poll ``ready`` until true; raise ``AdapterError`` when it never is."""
    for attempt in range(_SETTLE_TRIES):
        if ready():
            return
        if attempt < _SETTLE_TRIES - 1:
            time.sleep(_SETTLE_INTERVAL_S)
    raise AdapterError(f"{what} within {_SETTLE_TRIES * _SETTLE_INTERVAL_S:.0f} s")
