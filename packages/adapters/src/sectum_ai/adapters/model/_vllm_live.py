"""Live OpenAI-compatible backend for the vLLM serving adapter.

Imported lazily by :meth:`sectum_ai.adapters.model.vllm.VLLMModel.connect`, so a
downstream import of ``sectum_ai.adapters.model.vllm`` does **not** pull the
``openai`` client — only construction via ``connect`` does.

vLLM exposes an OpenAI-compatible HTTP API, so the standard ``openai`` client
talks to it directly. The completion (not chat) endpoint is used so the raw
prompt is sent verbatim — a chat template would rewrite the prefix and blur the
KV-prefix-cache timing signal the Class 5 probe measures.
"""

from __future__ import annotations

import time


class LiveVLLMBackend:
    """Talks to a vLLM server over its OpenAI-compatible completions API."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "EMPTY",
        timeout: float = 30.0,
        max_tokens: int = 16,
    ) -> None:
        from openai import OpenAI

        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self._model = model
        self._max_tokens = max_tokens

    def complete(self, prompt: str) -> str:
        """Return the completion text for ``prompt`` (greedy, bounded length)."""
        response = self._client.completions.create(
            model=self._model,
            prompt=prompt,
            max_tokens=self._max_tokens,
            temperature=0.0,
        )
        return response.choices[0].text or ""

    def first_token_latency_ms(self, prompt: str) -> float:
        """Stream the completion and return the wall-clock time to the first token.

        The prefix cache accelerates the prefill, which is what TTFT captures, so
        timing to the first streamed chunk isolates the cache signal from decode.
        """
        start = time.perf_counter()
        stream = self._client.completions.create(
            model=self._model,
            prompt=prompt,
            max_tokens=self._max_tokens,
            temperature=0.0,
            stream=True,
        )
        try:
            for _ in stream:
                break
        finally:
            stream.close()
        return (time.perf_counter() - start) * 1000.0
