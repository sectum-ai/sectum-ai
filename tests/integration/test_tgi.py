"""Opt-in live integration test for the serving-only TGI model adapter.

TGI serves over a native text-generation API, so this test is skipped unless
``SECTUM_TGI_BASE_URL`` points at a running server (the engineering spec,
section 13: opt-in live). Enable it with ``pip install sectum-ai-adapters[tgi]``
and the env var; the adapter logic itself is covered offline by
``tests/unit/test_tgi_model.py``.

Start a local server, e.g.::

    docker run --gpus all -p 8080:80 ghcr.io/huggingface/text-generation-inference \
      --model-id <model>   # then SECTUM_TGI_BASE_URL=http://localhost:8080
"""

import os
from uuid import UUID

import pytest

from sectum_ai.adapters.base import Capability
from sectum_ai.adapters.model.tgi import TGIModel
from sectum_ai.spec import AdapterError

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("SECTUM_TGI_BASE_URL"),
        reason="set SECTUM_TGI_BASE_URL to run the live TGI test",
    ),
]

_TENANT = UUID(int=0xA)


def _adapter() -> TGIModel:
    return TGIModel.connect(
        base_url=os.environ["SECTUM_TGI_BASE_URL"],
        api_key=os.environ.get("SECTUM_TGI_API_KEY"),
    )


def test_tgi_live_infers_and_times() -> None:
    adapter = _adapter()
    completion = adapter.infer(_TENANT, "The capital of France is")
    assert isinstance(completion, str)
    latency_ms = adapter.measure_latency(_TENANT, "The capital of France is")
    assert latency_ms > 0


def test_tgi_live_is_serving_only() -> None:
    adapter = _adapter()
    assert adapter.supports(Capability.SHARED_PREFIX_CACHE)
    assert not adapter.supports(Capability.PER_TENANT_ADAPTER)
    with pytest.raises(AdapterError, match="serving-only"):
        adapter.train_adapter(_TENANT, ["x"])
