"""vLLM serving-only model adapter for Class 5 (KV prefix-cache timing).

vLLM serves a base model over an OpenAI-compatible HTTP API. Unlike the
HuggingFace + PEFT adapter, it does **not** train per-tenant LoRA adapters: a
serving backend runs inference against a fixed set of weights and shares one KV
/ prefix cache across every caller. So this adapter declares
:attr:`~sectum_ai.adapters.base.Capability.SHARED_PREFIX_CACHE` (the Class 5
surface) and never ``PER_TENANT_ADAPTER``. The CLI therefore skips Class 9
(``lora-cross-tenant``) for it, and the model surface of Class 11 (erasure) is
reported ``NOT_COVERED`` (nothing per-tenant was trained, so there is nothing to
attest erased). Its value is measuring the time-to-first-token gap that a shared
prefix cache leaks across tenants.

Like the HuggingFace adapter, this exposes a ``backend`` seam: the live
``openai`` client is imported only on the :meth:`VLLMModel.connect` path, so
importing this module does not require the ``openai`` package — only
construction via ``connect`` does. The adapter logic is unit-tested against an
in-memory backend; the live path is exercised by an env-gated integration test
(the engineering spec, sections 11 and 13).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, Self
from uuid import UUID

from sectum_ai.adapters.base import Capability, ModelAdapter
from sectum_ai.spec import AdapterError


class _VLLMBackend(Protocol):
    """The minimal surface a backend must expose for :class:`VLLMModel`.

    The live backend wraps an OpenAI-compatible client pointed at a vLLM server;
    the unit tests substitute an in-memory stand-in.
    """

    def complete(self, prompt: str) -> str:
        """Return the model completion for ``prompt`` (completion only)."""
        ...

    def first_token_latency_ms(self, prompt: str) -> float:
        """Return the time to first token, in milliseconds, for ``prompt``."""
        ...


class VLLMModel(ModelAdapter):
    """A serving-only vLLM model: inference + prefix-cache timing, no training.

    Construct directly with a backend in tests; use :meth:`connect` for a live
    vLLM server. ``infer`` and ``measure_latency`` ignore the principal because a
    serving backend serves every tenant from the same weights and the same KV /
    prefix cache — which is exactly the Class 5 surface the timing probe measures.
    """

    def __init__(self, backend: _VLLMBackend, *, name: str = "vllm") -> None:
        # A serving backend shares one KV / prefix cache across tenants (the
        # Class 5 surface) and trains no per-tenant adapter, so it never declares
        # PER_TENANT_ADAPTER — the capability the LoRA probe gates on.
        super().__init__(name, frozenset({Capability.SHARED_PREFIX_CACHE}))
        self._backend = backend

    @classmethod
    def connect(
        cls,
        base_url: str,
        model: str,
        *,
        api_key: str = "EMPTY",
        timeout: float = 30.0,
        max_tokens: int = 16,
        name: str = "vllm",
    ) -> Self:
        """Build a live OpenAI-compatible vLLM backend and return the adapter.

        ``base_url`` is the vLLM server's OpenAI-compatible endpoint (for example
        ``http://localhost:8000/v1``); ``model`` is the served model id. A vLLM
        server started without ``--api-key`` accepts any key, so ``api_key``
        defaults to a placeholder. The ``openai`` client is imported here, on the
        live path only.

        Requires ``pip install sectum-ai-adapters[vllm]``.
        """
        from sectum_ai.adapters.model._vllm_live import LiveVLLMBackend

        backend = LiveVLLMBackend(
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout=timeout,
            max_tokens=max_tokens,
        )
        return cls(backend, name=name)

    def train_adapter(
        self, tenant: UUID, texts: Sequence[str], *, user: UUID | None = None
    ) -> None:
        """Not supported: a serving backend fits no per-tenant adapter.

        The CLI skips Class 9 for an adapter without ``PER_TENANT_ADAPTER``, so
        this is reached only if a caller drives the LoRA probe directly. Raising a
        typed :class:`AdapterError` keeps that a clean config/adapter error
        (exit 3), never a silent or fabricated result.
        """
        raise AdapterError(
            "vllm is serving-only: it cannot train a per-tenant adapter "
            "(Class 9 lora-cross-tenant does not apply to a serving backend)"
        )

    def infer(self, tenant: UUID, prompt: str, *, user: UUID | None = None) -> str:
        try:
            return self._backend.complete(prompt)
        except Exception as error:
            raise AdapterError(f"vllm inference failed: {error}") from error

    def measure_latency(self, tenant: UUID, prompt: str) -> float:
        # Time to FIRST token: a shared KV prefix cache speeds up the prefill,
        # which determines TTFT, so TTFT (not total generation time) isolates the
        # cross-tenant cache signal the Class 5 probe is built to catch.
        try:
            return self._backend.first_token_latency_ms(prompt)
        except Exception as error:
            raise AdapterError(f"vllm latency measurement failed: {error}") from error

    def delete(self, tenant: UUID) -> None:
        # Serving-only: there is no per-tenant fine-tune to erase, so honoring an
        # erasure request on this surface is a no-op. The Class 11 attestation
        # records the model surface as NOT_COVERED (nothing was trained to erase),
        # never a false ERASED.
        return None
