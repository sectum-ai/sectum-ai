"""Live mem0 adapter: a long-term / agent-memory store backed by mem0.

`mem0 <https://github.com/mem0ai/mem0>`_ is a popular agent-memory framework; a
product that stores per-user long-term memory in mem0 is exactly the Class 8
surface (persistent memory contamination). Each tenant maps to a mem0 ``user_id``,
so one tenant's recall never surfaces another tenant's memory - unless
``shared_memory=True`` points every tenant at a single shared ``user_id``, the
cross-tenant contamination Class 8 is built to catch.

Memory is stored with ``infer=False`` (verbatim), so the adapter is a faithful
scoped store and does not depend on mem0's LLM fact-extraction; a planted marker is
found by its own text. ``user_scoped`` (the ADR-0006 per-user boundary within a
tenant) is **not** modelled here - mem0's flat ``user_id`` space has no prefix
delete, so a two-level tenant/user boundary cannot be erased cleanly; the resolver
rejects ``user_scoped: true`` for ``kind: mem0`` rather than silently ignoring it.
Use the Redis memory adapter for the user-scoped case.

The ``mem0`` client is imported only on the live ``connect`` path (or injected for
the mock-backed test), so the adapter module needs no dependency. The live path
requires the ``mem0`` optional dependency: ``pip install sectum-ai-adapters[mem0]``.
"""

import re
from typing import Any, Self
from uuid import UUID

from sectum_ai.adapters.base import Capability, MemoryAdapter
from sectum_ai.spec import AdapterError, ErasureUnsupported

# get_all(limit=) is capped by mem0 itself; the default (100) silently truncated.
_GET_ALL_LIMIT = 10000
_TOKEN_RE = re.compile(r"[a-z0-9]+")
# The single shared scope every tenant collapses to under shared_memory - the
# space with no tenant boundary that Class 8 is built to catch.
_SHARED_SCOPE = "sectum-ai-shared"


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _rows(result: Any) -> list[Any]:
    """The rows of a mem0 response, or an ``AdapterError`` if it is not one."""
    if isinstance(result, dict):
        rows = result.get("results")
        if not isinstance(rows, list):
            raise AdapterError(
                f"mem0 returned an object with no 'results' list (keys: {sorted(result)}); "
                "its response shape is not the one this adapter reads"
            )
        return rows
    if isinstance(result, list):
        return result
    if result is None:
        return []
    raise AdapterError(
        f"mem0 returned {type(result).__name__}, not a list or a 'results' object; "
        "its response shape is not the one this adapter reads"
    )


class Mem0Memory(MemoryAdapter):
    """A long-term / agent-memory store backed by mem0, one ``user_id`` per tenant.

    ``carries_user`` is False: mem0's flat ``user_id`` space is the tenant, so a
    call made as a user reaches mem0 as the tenant. Inheriting True let Class 8
    plan user-level steps here and confirm cross-user leaks of sessions that never
    existed. The listing-limit refusal assumes the OSS ``Memory`` client, which
    ``connect`` builds; the hosted ``MemoryClient`` ignores ``limit``.
    """

    carries_user = False

    def __init__(
        self,
        client: Any,
        *,
        name: str = "mem0-memory",
        shared_memory: bool = False,
        soft_delete: bool = False,
    ) -> None:
        scope = Capability.SHARED_MEMORY if shared_memory else Capability.PER_TENANT_MEMORY
        capabilities = {scope}
        if soft_delete:
            capabilities.add(Capability.SOFT_DELETE)
        super().__init__(name, frozenset(capabilities))
        self._client = client
        self._shared_memory = shared_memory
        self._soft_delete = soft_delete

    @classmethod
    def connect(
        cls,
        config: dict[str, Any] | None = None,
        *,
        name: str = "mem0-memory",
        shared_memory: bool = False,
        soft_delete: bool = False,
    ) -> Self:
        """Open a mem0 ``Memory`` and return the adapter.

        ``config`` is mem0's own config dict (llm / embedder / vector_store); when
        omitted, mem0's defaults apply. The ``mem0`` package is imported here, on the
        live path only, so the adapter module and its mock-backed test do not need it.
        """
        from mem0 import Memory

        client = Memory.from_config(config) if config else Memory()
        return cls(client, name=name, shared_memory=shared_memory, soft_delete=soft_delete)

    def _scope(self, tenant: UUID) -> str:
        # A shared-memory store collapses every tenant to one scope (the leak); a
        # scoped store gives each tenant its own mem0 user_id.
        return _SHARED_SCOPE if self._shared_memory else tenant.hex

    @staticmethod
    def _memories(result: Any) -> list[str]:
        # mem0 search returns {"results": [{"memory": ...}, ...]} in current
        # releases and a bare list of dicts in older ones; read either defensively.
        # The ENVELOPE is checked, not only the rows: a release that renames the
        # top-level key (or nests the rows deeper) yielded an empty list, which
        # read as an empty tenant and let the A3 check attest the subject erased.
        rows = _rows(result)
        texts: list[str] = []
        for row in rows:
            if not isinstance(row, dict) or "memory" not in row:
                # Keyed on the KEY, not its truthiness: an empty or redacted
                # memory value is a legitimate backend state, not a mismatch.
                raise AdapterError(
                    "mem0 returned a row with no 'memory' key; its response shape "
                    "is not the one this adapter reads"
                )
            text = row.get("memory")
            if text:
                texts.append(str(text))
        return texts

    def remember(self, tenant: UUID, text: str, *, user: UUID | None = None) -> None:
        # user is ignored: this adapter scopes by tenant alone (see the module note).
        self._client.add(text, user_id=self._scope(tenant), infer=False)

    def recall(self, tenant: UUID, query: str, *, user: UUID | None = None) -> list[str]:
        # The whole scope, not a ranked top-N: a semantic `search(limit=N)` can
        # rank a planted marker out of its window in a tenant with more than N
        # memories, and the miss read as "not recalled". The keyword filter is the
        # contract (matching the fake and the Redis adapter), so the exhaustive
        # listing is the faithful primitive.
        result = self._client.get_all(user_id=self._scope(tenant), limit=_GET_ALL_LIMIT)
        memories = self._memories(result)
        query_tokens = _tokens(query)
        recalled = [text for text in memories if query_tokens & _tokens(text)]
        if not recalled and len(_rows(result)) >= _GET_ALL_LIMIT:
            # mem0's get_all defaults to limit=100 and pages no further; a
            # subject's memory past the window read as not recalled - ERASED. The
            # count is of ROWS (a row with an empty memory still fills the page),
            # and a hit already answers the question, so only a miss is refused.
            raise AdapterError(
                f"mem0 returned {len(_rows(result))} rows for the scope, its listing "
                "limit, so a recall that found nothing would be incomplete"
            )
        return recalled

    def delete(self, tenant: UUID) -> None:
        if self._shared_memory:
            # Every tenant shares one user_id, so there is no per-tenant erasure
            # boundary - a delete_all would wipe *every* tenant's memory, not the
            # target's. Signal attestable-with-caveat (like the read-only trace
            # backends) instead of destroying every tenant's data, the same honesty
            # that makes this adapter reject user_scoped. Checked before soft_delete
            # so the verdict is unambiguous even if both are set (matches the S3
            # backup and the fake observability/backup adapters).
            raise ErasureUnsupported(
                "mem0 in shared-memory mode has no per-tenant erasure boundary; a "
                "delete would remove every tenant's memory, so it is not performed"
            )
        # A soft-delete store acknowledges the request but keeps the entries - the
        # residue Class 11 erasure verification is built to catch.
        if self._soft_delete:
            return
        self._client.delete_all(user_id=self._scope(tenant))
