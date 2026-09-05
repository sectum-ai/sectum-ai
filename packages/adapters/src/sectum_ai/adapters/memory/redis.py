"""Live Redis adapter: a long-term / agent-memory store backed by a Redis server.

Each tenant's memory entries live in a Redis list namespaced by a fixed prefix and
the tenant, so one tenant's recall never surfaces another tenant's memory.
Constructing the adapter with ``shared_memory=True`` models a single memory space
shared across tenants - the cross-tenant memory contamination Class 8 is built to
catch. This is the memory-surface analogue of the Redis cache adapter.

Requires the ``redis`` optional dependency: ``pip install sectum-ai-adapters[redis]``.
"""

import re
from uuid import UUID

import redis

from sectum_ai.adapters.base import Capability, MemoryAdapter

_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Separates the owning-user tag from the memory text inside one stored entry.
_OWNER_SEP = "\x00"
_TENANT_LEVEL = "-"


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


class RedisMemory(MemoryAdapter):
    """A long-term / agent-memory store backed by a Redis server.

    Each tenant's entries live in a Redis list under ``prefix:tenant``; a recall
    returns the stored entries whose tokens overlap the query (keyword recall, so a
    planted marker is found by its own text). The isolation knobs mirror the
    in-memory fake:

    - ``shared_memory=True`` (reporting ``SHARED_MEMORY``): a recall spans EVERY
      tenant's list - the cross-tenant contamination Class 8 catches. With it off a
      recall reads only the caller's own tenant.
    - ``user_scoped=True`` (reporting ``USER_SCOPED``): each entry records the
      writing user, and a recall carrying a ``user`` returns only that user's own
      entries plus the tenant-shared ones (ADR-0006). With it off a recall scopes by
      tenant alone, so one user recalls a sibling user's note - the cross-user leak.
    - ``soft_delete=True``: ``delete`` is acknowledged but leaves the entries in
      place - the Class 11 erasure residue.

    A write always lands in the tenant's own list, so ``delete`` (when not
    soft-deleted) removes exactly that tenant's memory; ``shared_memory`` only
    widens what a *recall* reads.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        *,
        name: str = "redis-memory",
        shared_memory: bool = False,
        user_scoped: bool = False,
        soft_delete: bool = False,
        prefix: str = "sectum-ai-mem",
    ) -> None:
        scope = Capability.SHARED_MEMORY if shared_memory else Capability.PER_TENANT_MEMORY
        capabilities = {scope}
        if user_scoped:
            capabilities.add(Capability.USER_SCOPED)
        if soft_delete:
            capabilities.add(Capability.SOFT_DELETE)
        super().__init__(name, frozenset(capabilities))
        self._client = redis.Redis(host=host, port=port, decode_responses=True)
        self._shared_memory = shared_memory
        self._user_scoped = user_scoped
        # Without a user scope nothing user-specific reaches the backend: a call
        # made as a user is the tenant's call, so user-level steps are not run.
        self.carries_user = user_scoped
        self._soft_delete = soft_delete
        self._prefix = prefix

    def _key(self, tenant: UUID) -> str:
        return f"{self._prefix}:{tenant}"

    def remember(self, tenant: UUID, text: str, *, user: UUID | None = None) -> None:
        owner = user.hex if user is not None else _TENANT_LEVEL
        self._client.rpush(self._key(tenant), f"{owner}{_OWNER_SEP}{text}")

    def _readable_entries(self, tenant: UUID) -> list[tuple[str, str]]:
        """The (owner-tag, text) entries a recall in ``tenant``'s session can read.

        A shared-memory store reads every tenant's list (the leak); a scoped store
        reads only the caller's own list.
        """
        if self._shared_memory:
            keys = sorted(self._client.scan_iter(match=f"{self._prefix}:*"))
        else:
            keys = [self._key(tenant)]
        entries: list[tuple[str, str]] = []
        for key in keys:
            for raw in self._client.lrange(key, 0, -1):
                owner, _, text = str(raw).partition(_OWNER_SEP)
                entries.append((owner, text))
        return entries

    def recall(self, tenant: UUID, query: str, *, user: UUID | None = None) -> list[str]:
        query_tokens = _tokens(query)
        results: list[str] = []
        for owner, text in self._readable_entries(tenant):
            # A user-scoped store returns only the caller's own entries plus the
            # tenant-shared ones (owner ``-``); a store that scopes by tenant alone
            # ignores ``user`` and recalls a sibling user's note - the cross-user leak.
            if (
                self._user_scoped
                and user is not None
                and owner != _TENANT_LEVEL
                and owner != user.hex
            ):
                continue
            if query_tokens & _tokens(text):
                results.append(text)
        return results

    def delete(self, tenant: UUID) -> None:
        # A soft-delete store acknowledges the request but keeps the entries - the
        # residue Class 11 erasure verification is built to catch.
        if self._soft_delete:
            return
        self._client.delete(self._key(tenant))
