"""The Sectum AI typed exception hierarchy (the engineering spec, section 16).

Every error Sectum AI raises for a domain or runtime condition derives from
``SectumError``, so one ``except`` clause can catch the whole family. The
hierarchy lives in ``sectum-ai-spec`` - the lowest package in the acyclic
package graph (ADR-0004) - so every other package raises these without a cycle.
"""


class SectumError(Exception):
    """Base class for every error Sectum AI raises for a domain condition."""


class ConfigError(SectumError):
    """A scenario or configuration value is missing or invalid."""


class AdapterError(SectumError):
    """An adapter is missing, misconfigured, or failed at runtime."""


class ErasureUnsupported(AdapterError):
    """A backend exposes no programmatic per-tenant erasure API.

    Raised from an adapter's ``delete`` when the backend cannot purge a
    tenant's data through its API (erasure is governed by a retention policy
    or a manual console action instead). The Class 11 erasure probe catches
    this and itemises the surface as *attestable-with-caveat* (the engineering
    spec, section 7, Class 11, hiding place #8) rather than reporting a false
    erasure success - the data is presumed retained until proven otherwise.
    """


class EvidenceError(SectumError):
    """Building or verifying a tamper-evident evidence pack failed."""


class DetectionError(SectumError):
    """The leak-detection pipeline could not produce a result."""
