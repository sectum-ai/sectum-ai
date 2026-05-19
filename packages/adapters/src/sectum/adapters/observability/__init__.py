"""Live observability adapters.

Each module here connects to one real observability or tracing backend and is
imported explicitly (for example
``from sectum.adapters.observability.phoenix import PhoenixObservability``) so
that importing ``sectum.adapters`` never pulls an optional backend dependency.
"""
