"""Live vector-store adapters.

Each module here connects to one real vector backend and is imported explicitly
(for example ``from sectum.adapters.vector.pgvector import PgVectorStore``) so
that importing ``sectum.adapters`` never pulls an optional backend dependency.
"""
