"""Live HuggingFace + PEFT model adapter for Class 9 (LoRA cross-tenant).

Wraps a HuggingFace causal-language-model base with a per-tenant LoRA adapter
managed via the `peft` library: ``train_adapter`` fine-tunes a tenant-scoped
LoRA on a small text corpus and writes the adapter weights under
``adapters_dir/<tenant>``; ``infer`` loads that adapter back on top of the
shared base model and generates a completion. Class 9 verifies that adapter
isolation actually holds — that tenant Y's inference does not surface tenant
X's memorized canary, even when both tenants share the same base weights
(the weight-bleed condition the substrate is built to catch).

This adapter intentionally exposes a `backend` seam: the actual `peft` +
`transformers` calls live behind a small protocol that the mock-backed
contract test substitutes with an in-memory stand-in. The `huggingface`
package family is imported only on the live :meth:`connect` path, so the
adapter module and its unit tests need no extra dependency. The live path
requires the optional extras group:
``pip install sectum-ai-adapters[huggingface]``.

Scope of this v0.1 of the adapter:

- Tenant-scoped (and optionally user-scoped) LoRA adapters
- Train + infer + delete + measure-latency contract methods
- Real LoRA training via PEFT's ``LoraConfig`` + ``Trainer`` on the
  ``connect``-time path
- ``soft_delete=True`` keeps the LoRA dir on disk and serving, so the
  memorized text still surfaces (the Class 11 residue knob)
- ``adapter_bleed=True`` runs every inference with EVERY tenant's
  LoRA merged in — the weight-bleed condition Class 9 catches when
  a real LoRA stack is mis-routed

Out of scope (deferred to a later phase): KV-cache prefix sharing
(Class 5 timing side channel — uses ``FakeModel`` today), full
DeepSpeed / multi-GPU training, distillation / quantisation.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, Self
from uuid import UUID

from sectum_ai.adapters.base import Capability, ModelAdapter
from sectum_ai.spec import AdapterError


class _HuggingFaceBackend(Protocol):
    """The minimal surface a backend must expose for ``HuggingFaceLoraModel``.

    The live backend wraps a HuggingFace ``AutoModelForCausalLM`` + a PEFT
    LoRA trainer; the unit-suite stand-in is an in-memory dict mirroring
    the same operations. Keeping this seam explicit means the adapter code
    is portable across local PEFT versions, hosted Inference API
    integrations, and the test substrate.
    """

    def train_lora(self, scope: str, texts: list[str]) -> None:
        """Fit a LoRA adapter on ``texts`` and persist it under ``scope``."""

    def infer(self, scope: str | None, prompt: str) -> str:
        """Return a completion for ``prompt`` under ``scope`` (or base when ``None``)."""

    def measure_latency_ms(self, scope: str | None, prompt: str) -> float:
        """Return a deterministic latency in milliseconds for ``prompt``."""

    def list_scopes(self) -> list[str]:
        """Return every scope that currently has a stored LoRA."""

    def remove(self, scope: str) -> None:
        """Remove the LoRA stored under ``scope``."""


class HuggingFaceLoraModel(ModelAdapter):
    """A HuggingFace + PEFT LoRA model with per-tenant (or per-user) adapters.

    Construct it with an open ``_HuggingFaceBackend`` so the adapter can be
    tested against an in-memory stand-in without ``peft`` or ``transformers``
    installed. Use :meth:`connect` to build a backend wired to a real
    HuggingFace model.
    """

    def __init__(
        self,
        backend: _HuggingFaceBackend,
        *,
        name: str = "huggingface-lora",
        adapter_bleed: bool = False,
        user_scoped: bool = False,
        soft_delete: bool = False,
    ) -> None:
        scope_cap = Capability.SHARED_WEIGHTS if adapter_bleed else Capability.PER_TENANT_ADAPTER
        capabilities = {scope_cap}
        if user_scoped:
            capabilities.add(Capability.USER_SCOPED)
        if soft_delete:
            capabilities.add(Capability.SOFT_DELETE)
        super().__init__(name, frozenset(capabilities))
        self._backend = backend
        self._adapter_bleed = adapter_bleed
        self._user_scoped = user_scoped
        self._soft_delete = soft_delete

    @classmethod
    def connect(
        cls,
        base_model_id: str,
        adapters_dir: Path | str,
        *,
        name: str = "huggingface-lora",
        adapter_bleed: bool = False,
        user_scoped: bool = False,
        soft_delete: bool = False,
        lora_rank: int = 8,
        lora_alpha: int = 16,
        train_epochs: int = 1,
        device_map: str = "auto",
    ) -> Self:
        """Build a live HuggingFace + PEFT backend and return the adapter.

        The ``transformers`` and ``peft`` packages are imported here, on the
        live path only. ``base_model_id`` names a HuggingFace causal LM
        (e.g. ``"TinyLlama/TinyLlama-1.1B-Chat-v1.0"`` for a small
        device-runnable demo). ``adapters_dir`` is the directory the LoRA
        adapter weights are written to (one subdir per scope).

        Requires ``pip install sectum-ai-adapters[huggingface]``.
        """
        from sectum_ai.adapters.model._huggingface_live import LivePeftBackend

        backend = LivePeftBackend(
            base_model_id=base_model_id,
            adapters_dir=Path(adapters_dir),
            lora_rank=lora_rank,
            lora_alpha=lora_alpha,
            train_epochs=train_epochs,
            device_map=device_map,
        )
        return cls(
            backend,
            name=name,
            adapter_bleed=adapter_bleed,
            user_scoped=user_scoped,
            soft_delete=soft_delete,
        )

    def train_adapter(
        self, tenant: UUID, texts: Sequence[str], *, user: UUID | None = None
    ) -> None:
        scope = _scope_for(tenant, user, user_scoped=self._user_scoped)
        try:
            self._backend.train_lora(scope, list(texts))
        except Exception as error:
            raise AdapterError(f"peft LoRA training failed: {error}") from error

    def infer(self, tenant: UUID, prompt: str, *, user: UUID | None = None) -> str:
        scope = _scope_for(tenant, user, user_scoped=self._user_scoped)
        try:
            if self._adapter_bleed:
                # The weight-bleed condition Class 9 catches: every tenant's
                # LoRA is merged into the call regardless of who asked. The
                # backend's `list_scopes` returns the live set so an empty
                # adapter store still works (falls back to base inference).
                completion_parts = [
                    self._backend.infer(scope_id, prompt)
                    for scope_id in self._backend.list_scopes()
                ]
                if not completion_parts:
                    return self._backend.infer(None, prompt)
                return " ".join(completion_parts)
            return self._backend.infer(scope, prompt)
        except Exception as error:
            raise AdapterError(f"peft LoRA inference failed: {error}") from error

    def measure_latency(self, tenant: UUID, prompt: str) -> float:
        scope = _scope_for(tenant, user=None, user_scoped=self._user_scoped)
        try:
            return self._backend.measure_latency_ms(scope, prompt)
        except Exception as error:
            raise AdapterError(f"peft LoRA latency measurement failed: {error}") from error

    def delete(self, tenant: UUID) -> None:
        # The Class 11 residue knob: a soft-delete model acknowledges the request
        # and leaves the LoRA on disk AND serving, so the memorized text still
        # surfaces - the residue the erasure scan exists to catch. It used to
        # re-route inference to the base model instead, which hid the retained
        # weights from the very scan and signed an ERASED for a LoRA still on
        # disk (the inverse of what the built-in fake does).
        if self._soft_delete:
            return
        # Every scope under the tenant: a user-scoped model stores
        # `<tenant>/<user>` LoRAs, and removing only `<tenant>` left each user's
        # adapter serving the memorized text after a tenant erasure.
        prefix = _scope_for(tenant, user=None, user_scoped=self._user_scoped)
        try:
            scopes = [
                scope
                for scope in self._backend.list_scopes()
                if scope == prefix or scope.startswith(f"{prefix}/")
            ]
            for scope in scopes or [prefix]:
                self._backend.remove(scope)
        except Exception as error:
            raise AdapterError(f"peft LoRA delete failed: {error}") from error


def _scope_for(tenant: UUID, user: UUID | None, *, user_scoped: bool) -> str:
    """Build the on-disk scope id for a (tenant, user) pair.

    A user-scoped model writes ``<tenant.hex>/<user.hex>``; a tenant-level
    call (or a non-user-scoped model) writes ``<tenant.hex>``. The shape is
    deterministic so the backend can resolve the right LoRA directory on
    inference without an in-memory map.
    """
    if user_scoped and user is not None:
        return f"{tenant.hex}/{user.hex}"
    return tenant.hex


def _digest_scope(scope: str) -> str:
    """Return a short digest of a scope string for log + path use.

    Not used by the adapter's contract (the scope itself is the on-disk
    path); exposed for the live backend to derive collision-free shard
    names when the file system rejects the raw hex string.
    """
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:16]


def _safe_rmtree(path: Path) -> None:
    """Remove ``path`` recursively if it exists; tolerate a missing path.

    Used by the live backend on ``remove`` so a stale soft-delete window
    that already removed the dir does not raise on a second remove call.
    """
    if path.exists():
        shutil.rmtree(path)


def _import_required(name: str) -> Any:
    """Import an optional dependency or raise a typed ``AdapterError``.

    The live backend uses this to surface a clear "extras not installed"
    error instead of a bare ImportError when a customer set ``kind:
    huggingface`` without ``pip install sectum-ai-adapters[huggingface]``.
    """
    try:
        module = __import__(name)
    except ImportError as error:
        raise AdapterError(
            f"huggingface adapter requires the optional `{name}` package; "
            "install sectum-ai-adapters[huggingface] to enable it"
        ) from error
    return module
