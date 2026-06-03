"""Integration tests for the live Redis cache adapter.

Requires a Redis backend (see compose.yaml). The ``client`` fixture skips the
tests when no backend is reachable, so the default test run stays offline.
"""

import os
from collections.abc import Iterator
from uuid import UUID

import pytest
import redis
from sectum_ai.adapters.base import Capability
from sectum_ai.adapters.cache.redis import RedisCache

pytestmark = pytest.mark.integration

_HOST = os.environ.get("SECTUM_REDIS_HOST", "localhost")
_PORT = int(os.environ.get("SECTUM_REDIS_PORT", "6380"))
_PREFIX = "sectum-it"
_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)
_USER_A = UUID(int=0xA1)
_USER_B = UUID(int=0xB2)


def _flush(connection: redis.Redis) -> None:
    """Delete every key this test owns, leaving any co-tenant Redis data alone."""
    keys = list(connection.scan_iter(match=f"{_PREFIX}:*"))
    if keys:
        connection.delete(*keys)


@pytest.fixture
def client() -> Iterator[redis.Redis]:
    connection = redis.Redis(host=_HOST, port=_PORT, decode_responses=True)
    try:
        connection.ping()
    except redis.RedisError as error:
        connection.close()
        pytest.skip(f"Redis backend not reachable: {error}")
    _flush(connection)
    yield connection
    _flush(connection)
    connection.close()


@pytest.fixture
def cache(client: redis.Redis) -> RedisCache:
    return RedisCache(_HOST, _PORT, prefix=_PREFIX)


def test_redis_round_trips_a_value(cache: RedisCache) -> None:
    assert cache.get(_TENANT_A, "greeting") is None
    cache.set(_TENANT_A, "greeting", "hello")
    assert cache.get(_TENANT_A, "greeting") == "hello"


def test_redis_scoped_cache_isolates_tenants(cache: RedisCache) -> None:
    cache.set(_TENANT_A, "secret", "alpha-value")
    # a tenant-scoped cache keys on the tenant, so B cannot read A's entry
    assert cache.get(_TENANT_B, "secret") is None
    assert cache.supports(Capability.TENANT_SCOPED_KEYS)


def test_redis_unscoped_cache_leaks_across_tenants(client: redis.Redis) -> None:
    leaky = RedisCache(_HOST, _PORT, prefix=_PREFIX, tenant_scoped=False)
    leaky.set(_TENANT_A, "secret", "alpha-value")
    # a shared key space - tenant B reads tenant A's cached value
    assert leaky.get(_TENANT_B, "secret") == "alpha-value"
    assert not leaky.supports(Capability.TENANT_SCOPED_KEYS)


def test_redis_keys_are_prefixed_and_listed(cache: RedisCache) -> None:
    cache.set(_TENANT_A, "k1", "v1")
    cache.set(_TENANT_B, "k2", "v2")
    keys = cache.keys()
    assert len(keys) == 2
    assert all(key.startswith(f"{_PREFIX}:") for key in keys)


def test_redis_user_scoped_cache_isolates_users(client: redis.Redis) -> None:
    scoped = RedisCache(_HOST, _PORT, prefix=_PREFIX, user_scoped=True)
    scoped.set(_TENANT_A, "secret", "alpha-value", user=_USER_A)
    # a user-scoped cache folds the user into the key, so a sibling user in the
    # same tenant cannot read user A's entry (ADR-0006)
    assert scoped.get(_TENANT_A, "secret", user=_USER_B) is None
    assert scoped.get(_TENANT_A, "secret", user=_USER_A) == "alpha-value"
    assert scoped.supports(Capability.USER_SCOPED)


def test_redis_tenant_only_cache_leaks_across_users(client: redis.Redis) -> None:
    leaky = RedisCache(_HOST, _PORT, prefix=_PREFIX)  # tenant-scoped, not user-scoped
    leaky.set(_TENANT_A, "secret", "alpha-value", user=_USER_A)
    # without user scoping the key omits the user, so a sibling user reads it -
    # the cross-user leak
    assert leaky.get(_TENANT_A, "secret", user=_USER_B) == "alpha-value"
    assert not leaky.supports(Capability.USER_SCOPED)
    # the tenant-level delete still captures the user-folded entry
    leaky.delete(_TENANT_A)
    assert leaky.get(_TENANT_A, "secret", user=_USER_A) is None
