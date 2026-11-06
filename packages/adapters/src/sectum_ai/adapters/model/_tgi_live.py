"""Live ``huggingface_hub``-backed backend for the TGI serving adapter.

Imported lazily by :meth:`sectum_ai.adapters.model.tgi.TGIModel.connect`, so a
downstream import of ``sectum_ai.adapters.model.tgi`` does not require
``huggingface_hub`` — only construction via ``connect`` does.

Uses the ``InferenceClient.text_generation`` API against a TGI server's native
text-generation endpoint: a raw ``inputs`` prompt with no chat template, so the
prompt prefix is sent verbatim and the KV-prefix-cache timing signal the Class 5
probe measures is not blurred.
"""

from __future__ import annotations

import time


class LiveTGIBackend:
    """Talks to a TGI server over its native text-generation API."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 30.0,
        max_tokens: int = 16,
    ) -> None:
        from huggingface_hub import InferenceClient

        # With no token, huggingface_hub 1.30.0's hf-inference provider (the one
        # that serves a URL model) falls back to `get_token()` and sends the
        # operator's own Hugging Face token - HF_TOKEN or the cached login - as
        # `Authorization: Bearer` to the TGI server, the system under test.
        # HF_HUB_DISABLE_IMPLICIT_TOKEN does not stop it, and `token=False`
        # raises. The client's own headers are merged over the library's and
        # None values are then dropped, so a None `authorization` sends none.
        headers = None if api_key is not None else {"authorization": None}
        self._client = InferenceClient(
            model=base_url, token=api_key, timeout=timeout, headers=headers
        )
        self._max_tokens = max_tokens

    def complete(self, prompt: str) -> str:
        """Return the completion text for ``prompt`` (raw prompt, bounded length).

        ``return_full_text=False`` is pinned rather than left to the server.
        `huggingface_hub` declares the parameter as ``bool | None = None`` and
        forwards it verbatim, so with it unset TGI's own default applies - and
        for a ``text-generation`` model reached on the compat route that default
        PREPENDS the prompt. `ModelAdapter.infer` states the consequence: the
        erasure probe prompts with the canary it scans for, so an adapter that
        echoed its prompt would fabricate a confirmed "residual" about data that
        was never stored. Both sibling backends pin it - `_vllm_live` uses the
        completions endpoint without ``echo``, `_huggingface_live` strips the
        prompt tokens explicitly - and TGI was the one leaving it to the server.
        """
        return str(
            self._client.text_generation(
                prompt,
                max_new_tokens=self._max_tokens,
                stream=False,
                return_full_text=False,
            )
        )

    def first_token_latency_ms(self, prompt: str) -> float:
        """Stream the generation and return the wall-clock time to the first token.

        The prefix cache accelerates the prefill, which is what TTFT captures, so
        timing to the first streamed token isolates the cache signal from decode.
        """
        start = time.perf_counter()
        stream = self._client.text_generation(prompt, max_new_tokens=self._max_tokens, stream=True)
        try:
            for _ in stream:
                break
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()
        return (time.perf_counter() - start) * 1000.0
