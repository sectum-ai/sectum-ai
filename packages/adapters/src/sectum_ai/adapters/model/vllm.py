"""vLLM serving-only model adapter for Class 5 (KV prefix-cache timing).

vLLM serves a base model over an OpenAI-compatible HTTP API. It is **serving-only**
(see :class:`~sectum_ai.adapters.model._serving._ServingModel`): it runs inference
and measures time-to-first-token but trains no per-tenant adapter, so it declares
``SHARED_PREFIX_CACHE`` and never ``PER_TENANT_ADAPTER`` — the CLI skips Class 9
for it and a Class 11 erasure leaves the model surface ``NOT_COVERED``. Its value
is measuring the time-to-first-token gap a shared prefix cache leaks across tenants.

The live ``openai`` client is imported only on the :meth:`VLLMModel.connect` path,
so importing this module does not require ``openai``; the adapter logic is
unit-tested against an in-memory backend and the live path by an env-gated test.
"""

from __future__ import annotations

from typing import Self

from sectum_ai.adapters.model._serving import _ServingModel


class VLLMModel(_ServingModel):
    """A serving-only vLLM model reached over its OpenAI-compatible API.

    Construct directly with a backend in tests; use :meth:`connect` for a live
    vLLM server.
    """

    _default_name = "vllm"

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
        live path only. Requires ``pip install sectum-ai-adapters[vllm]``.
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
