"""Mock-backed contract tests for the HuggingFace + PEFT LoRA model adapter.

The adapter wraps a HuggingFace causal LM + per-tenant LoRA adapters managed
via PEFT. The live `peft` / `transformers` / `torch` stack is heavy and not
available in CI; the adapter logic is verified here against an in-memory
backend stand-in (the engineering spec, sections 11 and 13: live SDK,
mock-backed contract test plus opt-in live). The live path is exercised by
the env-gated integration tests under ``tests/integration/``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

import pytest

from sectum.adapters.base import Capability, ModelAdapter
from sectum.adapters.model.huggingface import HuggingFaceLoraModel
from sectum.spec import AdapterError

_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)
_USER_1 = UUID(int=1)
_USER_2 = UUID(int=2)


@dataclass
class _FakeBackend:
    """In-memory stand-in for the live PEFT backend.

    Stores the trained texts per scope; `infer` returns a deterministic
    string that names the scope so a test can prove which LoRA the call
    routed to. `measure_latency_ms` returns a stable per-scope latency so
    the Class 5 timing-side-channel probe path is exercised.
    """

    trained: dict[str, list[str]] = field(default_factory=dict)
    raise_on_train: Exception | None = None
    raise_on_infer: Exception | None = None
    raise_on_delete: Exception | None = None

    def train_lora(self, scope: str, texts: list[str]) -> None:
        if self.raise_on_train is not None:
            raise self.raise_on_train
        self.trained.setdefault(scope, []).extend(texts)

    def infer(self, scope: str | None, prompt: str) -> str:
        if self.raise_on_infer is not None:
            raise self.raise_on_infer
        if scope is None:
            return f"base:{prompt}"
        memorized = " ".join(self.trained.get(scope, []))
        return f"{scope}:{prompt}:{memorized}".rstrip(":")

    def measure_latency_ms(self, scope: str | None, prompt: str) -> float:
        # Deterministic per-prompt-length latency so a paired-trial timing
        # probe sees a stable signal; the live backend will report wall-clock.
        return float(20 + len(prompt))

    def list_scopes(self) -> list[str]:
        return sorted(self.trained.keys())

    def remove(self, scope: str) -> None:
        if self.raise_on_delete is not None:
            raise self.raise_on_delete
        self.trained.pop(scope, None)


def test_huggingface_lora_conforms_to_the_family_and_reports_per_tenant_scoping() -> None:
    model = HuggingFaceLoraModel(_FakeBackend())
    assert isinstance(model, ModelAdapter)
    assert model.supports(Capability.PER_TENANT_ADAPTER)
    assert not model.supports(Capability.SHARED_WEIGHTS)
    assert not model.supports(Capability.USER_SCOPED)


def test_huggingface_lora_routes_train_and_infer_under_the_tenant_scope() -> None:
    backend = _FakeBackend()
    model = HuggingFaceLoraModel(backend)
    model.train_adapter(_TENANT_A, ["SECRET-A leak"])
    model.train_adapter(_TENANT_B, ["SECRET-B leak"])
    assert set(backend.trained.keys()) == {_TENANT_A.hex, _TENANT_B.hex}
    # Inference under tenant A surfaces only tenant A's memorized text;
    # the stand-in's `infer` returns "<scope>:<prompt>:<memorized>" so the
    # test can prove which scope the call routed to.
    response_a = model.infer(_TENANT_A, "what")
    response_b = model.infer(_TENANT_B, "what")
    assert "SECRET-A" in response_a
    assert "SECRET-B" not in response_a
    assert "SECRET-B" in response_b
    assert "SECRET-A" not in response_b


def test_huggingface_lora_adapter_bleed_routes_every_tenants_lora_into_every_inference() -> None:
    # The weight-bleed condition Class 9 catches: a mis-routed LoRA stack
    # merges every tenant's adapter into every inference, so a tenant Y
    # call surfaces tenant X's memorized canary.
    backend = _FakeBackend()
    model = HuggingFaceLoraModel(backend, adapter_bleed=True)
    assert model.supports(Capability.SHARED_WEIGHTS)
    model.train_adapter(_TENANT_A, ["SECRET-A leak"])
    model.train_adapter(_TENANT_B, ["SECRET-B leak"])
    response = model.infer(_TENANT_A, "what")
    # Both tenants' memorized texts surface; the foreign canary is what
    # the Class 9 probe is built to detect.
    assert "SECRET-A" in response
    assert "SECRET-B" in response


def test_huggingface_lora_falls_back_to_base_model_when_adapter_bleed_has_no_loras() -> None:
    backend = _FakeBackend()
    model = HuggingFaceLoraModel(backend, adapter_bleed=True)
    response = model.infer(_TENANT_A, "hello")
    # No LoRA stored anywhere; the bleed path falls through to base inference
    # so a fresh substrate does not crash the probe before any adapter trains.
    assert response.startswith("base:")


def test_huggingface_lora_user_scoped_writes_under_a_two_segment_scope() -> None:
    backend = _FakeBackend()
    model = HuggingFaceLoraModel(backend, user_scoped=True)
    assert model.supports(Capability.USER_SCOPED)
    model.train_adapter(_TENANT_A, ["U1-SECRET"], user=_USER_1)
    model.train_adapter(_TENANT_A, ["U2-SECRET"], user=_USER_2)
    # Each user's LoRA is written under <tenant.hex>/<user.hex>; the model
    # routes inference by the call's user so a sibling user's canary does
    # not surface (the ADR-0006 default-deny user boundary).
    assert set(backend.trained.keys()) == {
        f"{_TENANT_A.hex}/{_USER_1.hex}",
        f"{_TENANT_A.hex}/{_USER_2.hex}",
    }
    response_u1 = model.infer(_TENANT_A, "what", user=_USER_1)
    response_u2 = model.infer(_TENANT_A, "what", user=_USER_2)
    assert "U1-SECRET" in response_u1
    assert "U2-SECRET" not in response_u1
    assert "U2-SECRET" in response_u2
    assert "U1-SECRET" not in response_u2


def test_huggingface_lora_user_scope_with_no_user_falls_back_to_tenant() -> None:
    # A user-scoped model called WITHOUT a user_id writes under the bare
    # tenant scope - the tenant-level adapter is shared across users when
    # explicitly trained that way.
    backend = _FakeBackend()
    model = HuggingFaceLoraModel(backend, user_scoped=True)
    model.train_adapter(_TENANT_A, ["tenant-wide-secret"])
    assert set(backend.trained.keys()) == {_TENANT_A.hex}


def test_huggingface_lora_delete_removes_the_lora_dir() -> None:
    backend = _FakeBackend()
    model = HuggingFaceLoraModel(backend)
    model.train_adapter(_TENANT_A, ["SECRET-A"])
    assert _TENANT_A.hex in backend.trained
    model.delete(_TENANT_A)
    assert _TENANT_A.hex not in backend.trained


def test_huggingface_lora_soft_delete_keeps_the_lora_but_routes_to_base() -> None:
    # The Class 11 residue knob: a soft-delete model acknowledges the
    # request but leaves the LoRA on disk; subsequent inference routes to
    # base, but the weights are still there to be revived (a retrain
    # discards the soft-delete flag).
    backend = _FakeBackend()
    model = HuggingFaceLoraModel(backend, soft_delete=True)
    assert model.supports(Capability.SOFT_DELETE)
    model.train_adapter(_TENANT_A, ["SECRET-A"])
    model.delete(_TENANT_A)
    # The LoRA dir is still on disk in the backend's view.
    assert _TENANT_A.hex in backend.trained
    # But inference now routes to the base model.
    response = model.infer(_TENANT_A, "what")
    assert response.startswith("base:")
    # A re-train restores the routing.
    model.train_adapter(_TENANT_A, ["SECRET-A revived"])
    response_again = model.infer(_TENANT_A, "what")
    assert response_again.startswith(_TENANT_A.hex)


def test_huggingface_lora_measure_latency_returns_a_deterministic_float() -> None:
    model = HuggingFaceLoraModel(_FakeBackend())
    # The stand-in's latency is a deterministic function of prompt length;
    # the assertion is that the contract returns a float the Class 5
    # timing-probe can compare across paired trials.
    latency = model.measure_latency(_TENANT_A, "abcdef")
    assert isinstance(latency, float)
    assert latency > 0


def test_huggingface_lora_wraps_train_failures_in_adapter_error() -> None:
    backend = _FakeBackend(raise_on_train=RuntimeError("cuda oom"))
    model = HuggingFaceLoraModel(backend)
    with pytest.raises(AdapterError, match="LoRA training failed"):
        model.train_adapter(_TENANT_A, ["x"])


def test_huggingface_lora_wraps_infer_failures_in_adapter_error() -> None:
    backend = _FakeBackend(raise_on_infer=RuntimeError("generation timeout"))
    model = HuggingFaceLoraModel(backend)
    with pytest.raises(AdapterError, match="LoRA inference failed"):
        model.infer(_TENANT_A, "x")


def test_huggingface_lora_wraps_delete_failures_in_adapter_error() -> None:
    backend = _FakeBackend(raise_on_delete=PermissionError("read-only fs"))
    model = HuggingFaceLoraModel(backend)
    with pytest.raises(AdapterError, match="LoRA delete failed"):
        model.delete(_TENANT_A)


def test_huggingface_lora_train_with_empty_texts_surfaces_no_memorized_content() -> None:
    # The adapter does not special-case an empty corpus: it delegates
    # train_lora(scope, []) to the backend, and the stand-in records the scope
    # with an empty text list. The meaningful, adapter-level contract is that
    # inference under that scope surfaces no memorized content - a tenant that
    # trained on nothing has nothing that can leak.
    backend = _FakeBackend()
    model = HuggingFaceLoraModel(backend)
    model.train_adapter(_TENANT_A, [])
    assert backend.trained.get(_TENANT_A.hex) == []
    # The stand-in returns "<scope>:<prompt>:<memorized>".rstrip(":"); with no
    # memorized text the response echoes the prompt but carries no canary.
    assert model.infer(_TENANT_A, "what") == f"{_TENANT_A.hex}:what"
