"""Live integration test: A3 model-surface erasure fingerprint vs a real HF LoRA.

Proves `sectum-ai erasure --subject`'s model-surface fingerprint runs end-to-end
against a REAL trainable model, not only the in-memory fake: a per-tenant LoRA
fine-tuned on the subject's content is caught as RESIDUAL (via prefix-continuation
extraction), and once the tenant's adapter is deleted the surface reads ERASED -
exercising both the detection and the per-tenant isolation of the delete on the
real ``transformers`` + ``peft`` path (which the mock-backed unit tests cannot).

Opt-in and heavy (downloads a small model, trains a LoRA on CPU), like the vLLM /
TGI live tests: skipped unless the ``huggingface`` extras are importable AND
``SECTUM_RUN_HF_LORA=1`` is set. Enable with::

    pip install sectum-ai-adapters[huggingface]
    SECTUM_RUN_HF_LORA=1 pytest tests/integration/test_subject_erasure_hf_lora.py

The offline adapter + probe logic is covered by ``tests/unit/test_huggingface_model.py``
and ``tests/unit/test_subject_erasure.py``.
"""

import importlib.util
import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest

from sectum_ai.adapters.model.huggingface import HuggingFaceLoraModel
from sectum_ai.probes import SubjectErasureProbe, SubjectManifest
from sectum_ai.spec import CoverageVerdict, Surface

_HF_EXTRAS = all(importlib.util.find_spec(m) is not None for m in ("torch", "transformers", "peft"))

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (_HF_EXTRAS and os.environ.get("SECTUM_RUN_HF_LORA")),
        reason="set SECTUM_RUN_HF_LORA=1 and install sectum-ai-adapters[huggingface] to run",
    ),
]

# A small, real, Llama-architecture base model (the LoRA targets q_proj/v_proj),
# CPU-runnable. Override for a larger/faster backend via the env vars.
_MODEL = os.environ.get("SECTUM_HF_LORA_MODEL", "HuggingFaceTB/SmolLM2-135M")
_EPOCHS = int(os.environ.get("SECTUM_HF_LORA_EPOCHS", "60"))
_TENANT = UUID(int=0xA)
# Leading context + an UNGUESSABLE tail: only a model TRAINED on the subject's
# content can regurgitate it, so a clean base reads ERASED and a memorized adapter
# reads RESIDUAL - the residual is genuine memorization, not model world-knowledge.
_CONTENT = "Patient Dana Lin private diagnosis note reference code ZX90210QQ"


@pytest.fixture
def model() -> Iterator[HuggingFaceLoraModel]:
    tmp = Path(tempfile.mkdtemp(prefix="sectum-hf-lora-it-"))
    try:
        yield HuggingFaceLoraModel.connect(
            _MODEL, tmp, train_epochs=_EPOCHS, device_map="cpu", lora_rank=16, lora_alpha=32
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _coverage(model: HuggingFaceLoraModel) -> CoverageVerdict:
    report = SubjectErasureProbe(model=model).verify(
        _TENANT,
        SubjectManifest(
            subject_ref="dsr-hf-lora", records={}, fingerprints={Surface.MODEL_ADAPTER: (_CONTENT,)}
        ),
    )
    return report.coverage()[Surface.MODEL_ADAPTER]


def test_model_fingerprint_residual_then_erased(model: HuggingFaceLoraModel) -> None:
    # Untrained: the base model cannot know the unguessable content -> ERASED.
    assert _coverage(model) is CoverageVerdict.ERASED
    # Fine-tune a per-tenant LoRA on the subject's content -> the model regurgitates
    # it under a prefix prompt, caught as RESIDUAL.
    model.train_adapter(_TENANT, [_CONTENT] * 8)
    assert _coverage(model) is CoverageVerdict.RESIDUAL
    # Delete the tenant's adapter -> base inference is clean again -> ERASED, proving
    # the delete actually removed the memorized residue (per-tenant isolation).
    model.delete(_TENANT)
    assert _coverage(model) is CoverageVerdict.ERASED
