"""Live cache adapters.

Each module here connects to one real cache backend and is imported explicitly
(for example ``from sectum.adapters.cache.redis import RedisCache``) so that
importing ``sectum.adapters`` never pulls an optional backend dependency.
"""
