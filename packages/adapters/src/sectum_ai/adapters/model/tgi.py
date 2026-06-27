"""TGI serving-only model adapter for Class 5 (KV prefix-cache timing).

HuggingFace Text Generation Inference (TGI) serves one model behind a REST API.
Like vLLM it is **serving-only** (see
:class:`~sectum_ai.adapters.model._serving._ServingModel`): it runs inference and
measures time-to-first-token but trains no per-tenant adapter, so it declares
``SHARED_PREFIX_CACHE`` and never ``PER_TENANT_ADAPTER`` — the CLI skips Class 9
for it and a Class 11 erasure leaves the model surface ``NOT_COVERED``.

It talks to TGI's native text-generation endpoint via the ``huggingface_hub``
``InferenceClient`` — a raw ``inputs`` prompt with no chat template, so the
prefix-cache timing signal is not blurred. The client is imported only on the
:meth:`TGIModel.connect` path; the adapter logic is unit-tested against an
in-memory backend and the live path by an env-gated test.
"""

from __future__ import annotations

from typing import Self

from sectum_ai.adapters.model._serving import _ServingModel


class TGIModel(_ServingModel):
    """A serving-only TGI model reached over its text-generation API.

    Construct directly with a backend in tests; use :meth:`connect` for a live TGI
    server. TGI serves a single model per endpoint, so there is no ``model`` field —
    ``base_url`` names the server.
    """

    _default_name = "tgi"

    @classmethod
    def connect(
        cls,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: float = 30.0,
        max_tokens: int = 16,
        name: str = "tgi",
    ) -> Self:
        """Build a live ``huggingface_hub``-backed TGI backend and return the adapter.

        ``base_url`` is the TGI server URL (for example ``http://localhost:8080``);
        ``api_key`` is an optional bearer token for a gated endpoint. The
        ``huggingface_hub`` client is imported here, on the live path only.
        Requires ``pip install sectum-ai-adapters[tgi]``.
        """
        from sectum_ai.adapters.model._tgi_live import LiveTGIBackend

        backend = LiveTGIBackend(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            max_tokens=max_tokens,
        )
        return cls(backend, name=name)
