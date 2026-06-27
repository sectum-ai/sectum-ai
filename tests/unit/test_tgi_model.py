"""Mock-backed contract tests for the serving-only TGI model adapter.

TGI is reached over its native text-generation API via ``huggingface_hub``; the
live client is networked and not used in CI. The adapter logic is verified here
against an in-memory backend stand-in (the engineering spec, sections 11 and 13);
the live path is exercised by the env-gated test in ``tests/integration/test_tgi.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

import pytest

from sectum_ai.adapters.base import Capability, ModelAdapter
from sectum_ai.adapters.model.tgi import TGIModel
from sectum_ai.config import AdapterConfig
from sectum_ai.config import build_model as _build_model
from sectum_ai.spec import AdapterError, ConfigError

_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


@dataclass
class _FakeBackend:
    """In-memory stand-in for the live huggingface_hub-backed TGI backend."""

    latency_ms: float = 9.0
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


def test_tgi_is_a_model_adapter() -> None:
    model = TGIModel(_FakeBackend())
    assert isinstance(model, ModelAdapter)
    assert model.name == "tgi"


def test_tgi_declares_shared_prefix_cache_not_per_tenant_adapter() -> None:
    # The capability split that makes Class 5 apply and Class 9 / model-surface
    # Class 11 not apply to a serving backend (so the CLI skips lora-cross-tenant).
    model = TGIModel(_FakeBackend())
    assert model.supports(Capability.SHARED_PREFIX_CACHE)
    assert not model.supports(Capability.PER_TENANT_ADAPTER)


def test_tgi_train_adapter_raises_serving_only() -> None:
    model = TGIModel(_FakeBackend())
    with pytest.raises(AdapterError, match="serving-only"):
        model.train_adapter(_TENANT_A, ["memorize me"])


def test_tgi_infer_returns_completion_and_ignores_principal() -> None:
    model = TGIModel(_FakeBackend())
    # A serving backend serves every tenant from the same weights.
    assert model.infer(_TENANT_A, "hello") == "completion:hello"
    assert model.infer(_TENANT_B, "hello") == "completion:hello"


def test_tgi_measure_latency_returns_backend_ttft() -> None:
    model = TGIModel(_FakeBackend(latency_ms=37.0))
    assert model.measure_latency(_TENANT_A, "probe") == 37.0


def test_tgi_delete_is_a_noop() -> None:
    # Serving-only: nothing per-tenant to erase; the call must simply not raise.
    TGIModel(_FakeBackend()).delete(_TENANT_A)


def test_tgi_infer_wraps_backend_error() -> None:
    model = TGIModel(_FakeBackend(raise_on_complete=RuntimeError("boom")))
    with pytest.raises(AdapterError, match="tgi inference failed"):
        model.infer(_TENANT_A, "x")


def test_tgi_measure_latency_wraps_backend_error() -> None:
    model = TGIModel(_FakeBackend(raise_on_latency=RuntimeError("boom")))
    with pytest.raises(AdapterError, match="tgi latency measurement failed"):
        model.measure_latency(_TENANT_A, "x")


def test_build_model_tgi_requires_base_url() -> None:
    # Missing the required field fails before the optional client is imported.
    with pytest.raises(ConfigError):
        _build_model(AdapterConfig(kind="tgi"))


def test_build_model_tgi_returns_serving_only_adapter() -> None:
    pytest.importorskip("huggingface_hub")  # connect() imports the client
    model = _build_model(AdapterConfig(kind="tgi", base_url="http://localhost:8080"))
    assert isinstance(model, TGIModel)
    assert model.supports(Capability.SHARED_PREFIX_CACHE)
    assert not model.supports(Capability.PER_TENANT_ADAPTER)
