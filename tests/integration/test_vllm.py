"""Opt-in live integration test for the serving-only vLLM model adapter.

vLLM serves over an OpenAI-compatible API, so this test is skipped unless
``SECTUM_VLLM_BASE_URL`` and ``SECTUM_VLLM_MODEL`` point at a running server (the
engineering spec, section 13: opt-in live). Enable it with
``pip install sectum-ai-adapters[vllm]`` and the env vars; the adapter logic
itself is covered offline by ``tests/unit/test_vllm_model.py``.

Start a local server, e.g.::

    vllm serve <model> --port 8000   # then SECTUM_VLLM_BASE_URL=http://localhost:8000/v1
"""

import os
from uuid import UUID

import pytest

from sectum_ai.adapters.base import Capability
from sectum_ai.adapters.model.vllm import VLLMModel
from sectum_ai.spec import AdapterError

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (os.environ.get("SECTUM_VLLM_BASE_URL") and os.environ.get("SECTUM_VLLM_MODEL")),
        reason="set SECTUM_VLLM_BASE_URL and SECTUM_VLLM_MODEL to run the live vLLM test",
    ),
]

_TENANT = UUID(int=0xA)


def _adapter() -> VLLMModel:
    return VLLMModel.connect(
        base_url=os.environ["SECTUM_VLLM_BASE_URL"],
        model=os.environ["SECTUM_VLLM_MODEL"],
        api_key=os.environ.get("SECTUM_VLLM_API_KEY", "EMPTY"),
    )


def test_vllm_live_infers_and_times() -> None:
    adapter = _adapter()
    completion = adapter.infer(_TENANT, "The capital of France is")
    assert isinstance(completion, str)
    latency_ms = adapter.measure_latency(_TENANT, "The capital of France is")
    assert latency_ms > 0


def test_vllm_live_is_serving_only() -> None:
    adapter = _adapter()
    assert adapter.supports(Capability.SHARED_PREFIX_CACHE)
    assert not adapter.supports(Capability.PER_TENANT_ADAPTER)
    with pytest.raises(AdapterError, match="serving-only"):
        adapter.train_adapter(_TENANT, ["x"])
