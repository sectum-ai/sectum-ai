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

        self._client = InferenceClient(model=base_url, token=api_key, timeout=timeout)
        self._max_tokens = max_tokens

    def complete(self, prompt: str) -> str:
        """Return the completion text for ``prompt`` (raw prompt, bounded length)."""
        return str(
            self._client.text_generation(prompt, max_new_tokens=self._max_tokens, stream=False)
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
