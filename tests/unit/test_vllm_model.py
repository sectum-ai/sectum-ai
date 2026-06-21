"""Mock-backed contract tests for the serving-only vLLM model adapter.

vLLM is reached over its OpenAI-compatible HTTP API; the live ``openai`` client
is networked and not used in CI. The adapter logic is verified here against an
in-memory backend stand-in (the engineering spec, sections 11 and 13: live SDK,
mock-backed contract test plus opt-in live). The live path is exercised by the
env-gated test in ``tests/integration/test_vllm.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest

from sectum_ai.adapters.base import Capability, ModelAdapter
from sectum_ai.adapters.fakes import FakeModel
from sectum_ai.adapters.model.vllm import VLLMModel
from sectum_ai.cli.app import _skip_inapplicable
from sectum_ai.config import AdapterBundle, AdapterConfig, SectumConfig, build_detection_providers
from sectum_ai.config import build_model as _build_model
from sectum_ai.probes import LoraCrossTenantProbe
from sectum_ai.spec import AdapterError, ConfigError

_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


@dataclass
class _FakeBackend:
    """In-memory stand-in for the live OpenAI-compatible vLLM backend."""

    latency_ms: float = 12.5
    raise_on_complete: Exception | None = None
    raise_on_latency: Exception | None = None
    prompts: list[str] = field(default_factory=list)

    def complete(self, prompt: str) -> str:
        if self.raise_on_complete is not None:
            raise self.raise_on_complete
        self.prompts.append(prompt)
        return f"completion:{prompt}"

    def first_token_latency_ms(self, prompt: str) -> float:
        if self.raise_on_latency is not None:
            raise self.raise_on_latency
        return self.latency_ms


def test_vllm_is_a_model_adapter() -> None:
    model = VLLMModel(_FakeBackend())
    assert isinstance(model, ModelAdapter)
    assert model.name == "vllm"


def test_vllm_declares_shared_prefix_cache_not_per_tenant_adapter() -> None:
    # The capability split that makes Class 5 apply and Class 9 / model-surface
    # Class 11 not apply to a serving backend.
    model = VLLMModel(_FakeBackend())
    assert model.supports(Capability.SHARED_PREFIX_CACHE)
    assert not model.supports(Capability.PER_TENANT_ADAPTER)


def test_vllm_train_adapter_raises_serving_only() -> None:
    model = VLLMModel(_FakeBackend())
    with pytest.raises(AdapterError, match="serving-only"):
        model.train_adapter(_TENANT_A, ["memorize me"])


def test_vllm_infer_returns_completion_and_ignores_principal() -> None:
    backend = _FakeBackend()
    model = VLLMModel(backend)
    # A serving backend serves every tenant from the same shared weights, so the
    # same prompt yields the same completion regardless of the caller.
    assert model.infer(_TENANT_A, "hello") == "completion:hello"
    assert model.infer(_TENANT_B, "hello") == "completion:hello"


def test_vllm_measure_latency_returns_backend_ttft() -> None:
    model = VLLMModel(_FakeBackend(latency_ms=42.0))
    assert model.measure_latency(_TENANT_A, "probe") == 42.0


def test_vllm_delete_is_a_noop() -> None:
    # Serving-only: nothing per-tenant to erase; the call must simply not raise.
    VLLMModel(_FakeBackend()).delete(_TENANT_A)


def test_vllm_infer_wraps_backend_error() -> None:
    model = VLLMModel(_FakeBackend(raise_on_complete=RuntimeError("boom")))
    with pytest.raises(AdapterError, match="vllm inference failed"):
        model.infer(_TENANT_A, "x")


def test_vllm_measure_latency_wraps_backend_error() -> None:
    model = VLLMModel(_FakeBackend(raise_on_latency=RuntimeError("boom")))
    with pytest.raises(AdapterError, match="vllm latency measurement failed"):
        model.measure_latency(_TENANT_A, "x")


def test_build_model_vllm_requires_base_url_and_model() -> None:
    # Missing required fields fail before the optional openai client is imported.
    with pytest.raises(ConfigError):
        _build_model(AdapterConfig(kind="vllm"))


def test_build_model_vllm_returns_serving_only_adapter() -> None:
    pytest.importorskip("openai")  # connect() imports the openai client
    model = _build_model(
        AdapterConfig(kind="vllm", base_url="http://localhost:8000/v1", model="demo-model")
    )
    assert isinstance(model, VLLMModel)
    # The client is lazy, so no network call happened building it.
    assert model.supports(Capability.SHARED_PREFIX_CACHE)
    assert not model.supports(Capability.PER_TENANT_ADAPTER)


def _bundle_with_model(model: ModelAdapter) -> AdapterBundle:
    # _skip_inapplicable only reads bundle.model for the LoRA probe; a namespace
    # stand-in keeps the test from constructing the full adapter bundle.
    return cast(AdapterBundle, SimpleNamespace(model=model))


def test_skip_inapplicable_skips_lora_for_serving_only_model() -> None:
    providers = build_detection_providers(SectumConfig().detection)
    lora = LoraCrossTenantProbe(providers)

    runnable, skipped = _skip_inapplicable((lora,), _bundle_with_model(VLLMModel(_FakeBackend())))
    assert runnable == ()
    assert skipped == [("lora-cross-tenant", "per_tenant_adapter or shared_weights")]


def test_skip_inapplicable_keeps_lora_for_a_trainable_model() -> None:
    providers = build_detection_providers(SectumConfig().detection)
    lora = LoraCrossTenantProbe(providers)

    runnable, skipped = _skip_inapplicable((lora,), _bundle_with_model(FakeModel()))
    assert len(runnable) == 1
    assert skipped == []
