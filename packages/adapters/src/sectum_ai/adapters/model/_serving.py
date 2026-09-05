"""Shared base for serving-only model adapters (vLLM, TGI).

A serving backend runs inference against a fixed set of weights and shares one KV
/ prefix cache across every caller — the Class 5 surface — but trains no per-tenant
adapter. So these adapters declare
:attr:`~sectum_ai.adapters.base.Capability.SHARED_PREFIX_CACHE` and never
``PER_TENANT_ADAPTER``: the CLI skips Class 9 (``lora-cross-tenant``) for them, and
the model surface of a Class 11 erasure is reported ``NOT_COVERED`` (nothing
per-tenant was trained, so there is nothing to attest erased).

Each concrete adapter only supplies a ``connect`` classmethod that builds its
backend (and a ``_default_name``); the inference / timing / erasure behaviour is
shared here. The backend is a ``_ServingBackend`` seam so the adapter logic is
unit-tested against an in-memory stand-in and the live client is imported only on
the ``connect`` path.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from sectum_ai.adapters.base import Capability, ModelAdapter
from sectum_ai.spec import AdapterError


class _ServingBackend(Protocol):
    """The minimal surface a serving backend exposes to a :class:`_ServingModel`."""

    def complete(self, prompt: str) -> str:
        """Return the model completion for ``prompt`` (completion only)."""
        ...

    def first_token_latency_ms(self, prompt: str) -> float:
        """Return the time to first token, in milliseconds, for ``prompt``."""
        ...


class _ServingModel(ModelAdapter):
    """A serving-only model: inference + prefix-cache timing, no training.

    ``infer`` and ``measure_latency`` ignore the principal because a serving backend
    serves every tenant from the same weights and the same KV / prefix cache — which
    is exactly the Class 5 surface the timing probe measures. Concrete adapters set
    ``_default_name`` and provide a ``connect`` classmethod that builds the backend.
    ``carries_user`` is False for the same reason: the user never reaches the server.
    """

    carries_user = False
    _default_name = "serving"

    def __init__(self, backend: _ServingBackend, *, name: str | None = None) -> None:
        # A serving backend shares one KV / prefix cache across tenants (the Class 5
        # surface) and trains no per-tenant adapter, so it never declares
        # PER_TENANT_ADAPTER — the capability the LoRA probe gates on.
        super().__init__(name or self._default_name, frozenset({Capability.SHARED_PREFIX_CACHE}))
        self._backend = backend

    def train_adapter(
        self, tenant: UUID, texts: Sequence[str], *, user: UUID | None = None
    ) -> None:
        """Not supported: a serving backend fits no per-tenant adapter.

        The CLI skips Class 9 for an adapter without ``PER_TENANT_ADAPTER``, so this
        is reached only if a caller drives the LoRA probe directly. Raising a typed
        :class:`AdapterError` keeps that a clean config/adapter error (exit 3),
        never a silent or fabricated result.
        """
        raise AdapterError(
            f"{self.name} is serving-only: it cannot train a per-tenant adapter "
            "(Class 9 lora-cross-tenant does not apply to a serving backend)"
        )

    def infer(self, tenant: UUID, prompt: str, *, user: UUID | None = None) -> str:
        try:
            return self._backend.complete(prompt)
        except Exception as error:
            raise AdapterError(f"{self.name} inference failed: {error}") from error

    def measure_latency(self, tenant: UUID, prompt: str) -> float:
        # Time to FIRST token: a shared KV prefix cache speeds up the prefill, which
        # determines TTFT, so TTFT (not total generation time) isolates the
        # cross-tenant cache signal the Class 5 probe is built to catch.
        try:
            return self._backend.first_token_latency_ms(prompt)
        except Exception as error:
            raise AdapterError(f"{self.name} latency measurement failed: {error}") from error

    def delete(self, tenant: UUID) -> None:
        # Serving-only: there is no per-tenant fine-tune to erase, so honoring an
        # erasure request on this surface is a no-op. The Class 11 attestation
        # records the model surface as NOT_COVERED (nothing was trained to erase),
        # never a false ERASED.
        return None
