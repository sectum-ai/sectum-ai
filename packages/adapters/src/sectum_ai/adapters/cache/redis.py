"""Live Redis adapter: a cache backed by a Redis server.

Cache keys are namespaced by a fixed prefix and, by default, scoped by tenant,
so one tenant cannot read another tenant's cached value. Constructing the
adapter with ``tenant_scoped=False`` models a shared key space - the cache-key
tenancy flaw Class 4 (semantic-cache contamination) is built to catch.

Requires the ``redis`` optional dependency: ``pip install sectum-ai-adapters[redis]``.
"""

from uuid import UUID

import redis

from sectum_ai.adapters.base import CacheAdapter, Capability


class RedisCache(CacheAdapter):
    """A cache backed by a Redis server.

    Cache keys are namespaced by a fixed prefix and, by default, scoped by
    tenant. With ``user_scoped=True`` a key carrying a ``user`` also folds in the
    user (reporting ``USER_SCOPED``), so one user cannot read a sibling user's
    entry within the tenant (ADR-0006). ``user=None`` keys at the tenant level
    and is unchanged, so the tenant-scoped ``values``/``delete`` globs still
    capture user-folded keys (they share the ``prefix:tenant:`` prefix).
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        *,
        name: str = "redis",
        tenant_scoped: bool = True,
        user_scoped: bool = False,
        prefix: str = "sectum-ai",
    ) -> None:
        capabilities = {Capability.TENANT_SCOPED_KEYS} if tenant_scoped else set()
        if user_scoped:
            capabilities.add(Capability.USER_SCOPED)
        super().__init__(name, frozenset(capabilities))
        self._client = redis.Redis(host=host, port=port, decode_responses=True)
        self._tenant_scoped = tenant_scoped
        self._user_scoped = user_scoped
        self._prefix = prefix

    def _key(self, tenant: UUID, key: str, user: UUID | None = None) -> str:
        """Build the raw Redis key for ``key`` in the principal's scope.

        A tenant-scoped cache folds the tenant in; a user-scoped cache also folds
        the user in (when one is given) so siblings never collide; an unscoped
        cache uses the bare key. ``user=None`` reproduces the tenant-level key.
        """
        parts = [self._prefix]
        if self._tenant_scoped:
            parts.append(str(tenant))
        if self._user_scoped and user is not None:
            parts.append(str(user))
        parts.append(key)
        return ":".join(parts)

    def get(self, tenant: UUID, key: str, *, user: UUID | None = None) -> str | None:
        value = self._client.get(self._key(tenant, key, user))
        return None if value is None else str(value)

    def set(self, tenant: UUID, key: str, value: str, *, user: UUID | None = None) -> None:
        self._client.set(self._key(tenant, key, user), value)

    def keys(self) -> list[str]:
        return sorted(str(key) for key in self._client.scan_iter(match=f"{self._prefix}:*"))

    def _tenant_pattern(self, tenant: UUID) -> str:
        """The key glob for ``tenant``'s entries (or all keys when unscoped)."""
        return f"{self._prefix}:{tenant}:*" if self._tenant_scoped else f"{self._prefix}:*"

    def values(self, tenant: UUID) -> list[str]:
        keys = list(self._client.scan_iter(match=self._tenant_pattern(tenant)))
        if not keys:
            return []
        return [str(value) for value in self._client.mget(keys) if value is not None]

    def delete(self, tenant: UUID) -> None:
        # An unscoped cache cannot isolate one tenant's entries to delete them,
        # so the data survives - the Class 11 erasure residue.
        if not self._tenant_scoped:
            return
        keys = list(self._client.scan_iter(match=f"{self._prefix}:{tenant}:*"))
        if keys:
            self._client.delete(*keys)
