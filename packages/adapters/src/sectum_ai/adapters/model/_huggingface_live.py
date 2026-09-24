"""Live PEFT-backed implementation of the HuggingFace LoRA backend.

Imported lazily by ``HuggingFaceLoraModel.connect``. The module imports
``transformers`` + ``peft`` + ``torch`` at module load, so a downstream
import of ``sectum_ai.adapters.model.huggingface`` does NOT pull those
heavy packages — only construction via ``connect`` does.

Stack:

- ``transformers.AutoModelForCausalLM`` for the base model
- ``transformers.AutoTokenizer`` for the tokenizer
- ``peft.LoraConfig`` + ``peft.get_peft_model`` for the per-tenant LoRA
- ``peft.PeftModel.from_pretrained`` to load a stored LoRA at inference time
- ``transformers.Trainer`` + ``transformers.TrainingArguments`` for the
  fine-tune loop on each ``train_lora`` call

Training is a small batch of ``train_epochs`` passes over the supplied
texts; the live integration test uses a tiny base model (e.g.
``TinyLlama``) and a couple of training examples so the suite is
runnable on a single CPU. Production engagements configure a real GPU
device map and a meaningful epoch count via ``connect`` kwargs.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from sectum_ai.adapters.model.huggingface import _safe_rmtree
from sectum_ai.spec import AdapterError


class LivePeftBackend:
    """Live ``_HuggingFaceBackend`` implementation.

    Holds the base model + tokenizer in memory; per-tenant LoRA adapters
    live on disk under ``adapters_dir``. Loading a LoRA on inference is
    cheap (a copy of the small delta weights into the wrapped model);
    training is the heavyweight operation and happens synchronously on
    each ``train_lora`` call.
    """

    def __init__(
        self,
        base_model_id: str,
        adapters_dir: Path,
        *,
        lora_rank: int = 8,
        lora_alpha: int = 16,
        train_epochs: int = 1,
        device_map: str = "auto",
    ) -> None:
        try:
            import torch
            from peft import LoraConfig, PeftModel, get_peft_model
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as error:
            raise AdapterError(
                "huggingface adapter requires the `huggingface` extras "
                "group: pip install sectum-ai-adapters[huggingface]"
            ) from error

        adapters_dir.mkdir(parents=True, exist_ok=True)

        self._torch = torch
        self._LoraConfig = LoraConfig
        self._PeftModel = PeftModel
        self._get_peft_model = get_peft_model
        self._AutoModel = AutoModelForCausalLM
        self._AutoTokenizer = AutoTokenizer
        self._base_model_id = base_model_id
        self._adapters_dir = adapters_dir
        self._lora_rank = lora_rank
        self._lora_alpha = lora_alpha
        self._train_epochs = train_epochs
        self._device_map = device_map

        self._tokenizer = AutoTokenizer.from_pretrained(base_model_id)
        if self._tokenizer.pad_token is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token
        self._base_model = AutoModelForCausalLM.from_pretrained(
            base_model_id, device_map=device_map
        )

    def _scope_dir(self, scope: str) -> Path:
        return self._adapters_dir / scope

    def _load_base(self) -> Any:
        """Load a fresh, uncontaminated copy of the base model.

        PEFT's ``get_peft_model`` / ``PeftModel.from_pretrained`` inject adapter
        modules into the model *in place*, so training and scoped inference must run
        on a fresh base - never the shared ``self._base_model`` - or one tenant's
        LoRA would bleed into every later (base or other-tenant) inference and even
        survive a per-tenant delete: the exact cross-tenant residue this tool exists
        to catch. The shared ``self._base_model`` is kept pristine for base inference.
        """
        return self._AutoModel.from_pretrained(self._base_model_id, device_map=self._device_map)

    def train_lora(self, scope: str, texts: list[str]) -> None:
        if not texts:
            return
        from transformers import Trainer, TrainingArguments

        peft_config = self._LoraConfig(
            r=self._lora_rank,
            lora_alpha=self._lora_alpha,
            task_type="CAUSAL_LM",
            target_modules=["q_proj", "v_proj"],
        )
        # Train on a FRESH base copy, never the shared pristine base: get_peft_model
        # injects LoRA modules in place, so training on the shared base would
        # permanently contaminate every later base / other-tenant inference.
        peft_model = self._get_peft_model(self._load_base(), peft_config)

        encodings = self._tokenizer(texts, padding=True, truncation=True, return_tensors="pt")
        encodings["labels"] = encodings["input_ids"].clone()
        dataset = [{key: value[i] for key, value in encodings.items()} for i in range(len(texts))]

        scope_dir = self._scope_dir(scope)
        scope_dir.mkdir(parents=True, exist_ok=True)
        training_args = TrainingArguments(
            output_dir=str(scope_dir / "_trainer"),
            num_train_epochs=self._train_epochs,
            per_device_train_batch_size=1,
            logging_steps=1,
            save_strategy="no",
            report_to=[],
        )
        trainer = Trainer(
            model=peft_model,
            args=training_args,
            train_dataset=dataset,
            # transformers 5.x removed the `tokenizer=` Trainer arg (deprecated in
            # 4.46) in favour of `processing_class=`; the huggingface extra pins
            # transformers>=5.13, so pass the tokenizer under the current name.
            processing_class=self._tokenizer,
        )
        trainer.train()
        peft_model.save_pretrained(str(scope_dir))
        # Strip the Trainer's checkpoint cruft; we only ship the LoRA delta.
        _safe_rmtree(scope_dir / "_trainer")

    def _prepare(self, scope: str | None, prompt: str) -> tuple[Any, Any]:
        """The model this scope routes to, and the tokenized prompt.

        Base inference uses the shared PRISTINE base; a scoped call loads the LoRA
        onto a FRESH base copy so it never mutates the shared one (PeftModel.
        from_pretrained injects adapter modules in place). Sharing the base would
        leak this tenant's LoRA into every later base / other-tenant inference and
        survive a per-tenant delete.

        Split out so `measure_latency_ms` can time the generation WITHOUT this:
        loading a LoRA off disk is setup, not inference, and timing it would swamp
        the prefill signal Class 5 reads.
        """
        model = self._base_model
        if scope is not None:
            scope_dir = self._scope_dir(scope)
            if scope_dir.exists():
                model = self._PeftModel.from_pretrained(self._load_base(), str(scope_dir))
        return model, self._tokenizer(prompt, return_tensors="pt")

    def infer(self, scope: str | None, prompt: str) -> str:
        model, inputs = self._prepare(scope, prompt)
        with self._torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=64,
                pad_token_id=self._tokenizer.pad_token_id,
            )
        # HF generate output INCLUDES the prompt tokens. The adapter contract is
        # "completion only": echoing the prompt back would hand the erasure probe
        # its own canary prompt as a fabricated 'residual' (a CONFIRMED finding
        # about data that was never stored), so decode only the new tokens.
        prompt_length = inputs["input_ids"].shape[-1]
        decoded: str = self._tokenizer.decode(outputs[0][prompt_length:], skip_special_tokens=True)
        return decoded

    def measure_latency_ms(self, scope: str | None, prompt: str) -> float:
        """Time to FIRST token, never total generation time.

        `_serving.py` states the rule normatively - "a shared KV prefix cache
        speeds up the PREFILL, which determines TTFT, so TTFT (not total
        generation time) isolates the cross-tenant cache signal the Class 5 probe
        is built to catch" - and both serving siblings implement it by streaming
        and breaking on the first chunk. This called `infer`, which generates 64
        tokens: the decode steps cost the same in both arms, so they added
        variance to the denominator of Cohen's d without adding to the numerator.
        The mean gap survived and d collapsed, which biases Class 5 toward a MISS
        and systematically downgrades a detected channel HIGH -> MEDIUM.

        `max_new_tokens=1` is prefill plus one decode step - the same call `infer`
        already makes, with the decode loop cut to the single token TTFT means.
        """
        model, inputs = self._prepare(scope, prompt)
        start = time.perf_counter()
        with self._torch.no_grad():
            model.generate(
                **inputs,
                max_new_tokens=1,
                pad_token_id=self._tokenizer.pad_token_id,
            )
        return (time.perf_counter() - start) * 1000.0

    def list_scopes(self) -> list[str]:
        if not self._adapters_dir.exists():
            return []
        # A scope may be `<tenant>` or `<tenant>/<user>`; walk one level
        # past the adapters_dir and return the relative dir as the scope.
        scopes: list[str] = []
        for tenant_dir in sorted(self._adapters_dir.iterdir()):
            if not tenant_dir.is_dir():
                continue
            adapter_config = tenant_dir / "adapter_config.json"
            if adapter_config.exists():
                scopes.append(tenant_dir.name)
                continue
            # Otherwise look one level deeper for user-scoped adapters.
            for user_dir in sorted(tenant_dir.iterdir()):
                if not user_dir.is_dir():
                    continue
                if (user_dir / "adapter_config.json").exists():
                    scopes.append(f"{tenant_dir.name}/{user_dir.name}")
        return scopes

    def remove(self, scope: str) -> None:
        _safe_rmtree(self._scope_dir(scope))


# Re-export for type-only consumers.
__all__ = ["LivePeftBackend"]


def _silence_unused() -> Any:
    # The Trainer + transformers imports above carry their own side effects
    # at module import (warnings registration). Some lint tools then flag the
    # local imports as unused; pin a reference so the import remains. The
    # function is never called; mypy ignores it.
    return None
