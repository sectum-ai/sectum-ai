"""Contract tests: the third-party API surface each opt-in extra's adapter calls.

CI installs the workspace with ``uv sync --all-packages`` and no extras, so every
live adapter behind an extra is unreachable there: its imports fail, its tests skip,
and a dependency bump to that package gets a green check list having executed none
of the code it could break. That is not hypothetical - it is how a two-major cohere
bump (5.x -> 7.x) arrived fully green, and how ``transformers`` 5.x removing the
``Trainer(tokenizer=...)`` argument could have arrived the same way.

These tests pin the *exact* attributes and parameters the adapters pass, so a
rename or removal upstream fails here with the adapter call site named, rather
than at a customer's first live run. Each skips when its package is absent, so the
default CI job is unaffected; the ``extras-contract`` job installs them and runs
this file.

Scope is deliberately the surface that has bitten or is demonstrably fragile, not
all 26 extras. Add a package here when an adapter starts depending on a specific
call shape - the cost of a missing entry is a silent break, and the cost of an
extra entry is three lines.
"""

import inspect
from typing import Any

import pytest


def _params(func: Any) -> set[str]:
    return set(inspect.signature(func).parameters)


def _accepts(func: Any, names: tuple[str, ...]) -> bool:
    """Whether ``func`` accepts every name, directly or via ``**kwargs``."""
    parameters = inspect.signature(func).parameters
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        return True
    return all(name in parameters for name in names)


# --- cohere: sectum_ai.embeddings.CohereEmbedding ---------------------------


def test_cohere_client_and_embed_surface() -> None:
    # CohereEmbedding.__init__ calls cohere.Client(api_key); embed() calls
    # .embed(texts=, model=, input_type=). v5 introduced ClientV2 alongside
    # Client; a future major dropping Client is the break this catches.
    cohere = pytest.importorskip("cohere")
    assert hasattr(cohere, "Client"), "cohere.Client is gone; CohereEmbedding constructs it"
    assert _accepts(cohere.Client.embed, ("texts", "model", "input_type"))


def test_cohere_embed_response_shapes_stay_readable() -> None:
    # CohereEmbedding._vectors reads a flat `.embeddings` OR a by-type
    # `.embeddings.float_`, deliberately, "so a client-version bump does not
    # silently break the sweep". Both shapes must keep existing for that to hold.
    pytest.importorskip("cohere")
    from cohere.types import embed_response as er

    flat = getattr(er, "EmbeddingsFloatsEmbedResponse", None)
    by_type = getattr(er, "EmbeddingsByTypeEmbedResponse", None)
    typed = getattr(er, "EmbedByTypeResponseEmbeddings", None)
    assert flat is not None and "embeddings" in flat.model_fields
    assert by_type is not None and "embeddings" in by_type.model_fields
    assert typed is not None and "float_" in typed.model_fields


# --- huggingface_hub: adapters.model._tgi_live ------------------------------


def test_tgi_inference_client_surface() -> None:
    # _TgiLiveBackend constructs InferenceClient(model=, token=, timeout=) and
    # calls .text_generation(prompt, max_new_tokens=, stream=).
    hub = pytest.importorskip("huggingface_hub")
    assert hasattr(hub, "InferenceClient")
    assert _accepts(hub.InferenceClient.__init__, ("model", "token", "timeout"))
    assert _accepts(hub.InferenceClient.text_generation, ("max_new_tokens", "stream"))


# --- transformers + peft: adapters.model._huggingface_live ------------------


def test_transformers_classes_the_lora_adapter_imports() -> None:
    transformers = pytest.importorskip("transformers")
    for name in ("AutoModelForCausalLM", "AutoTokenizer", "Trainer", "TrainingArguments"):
        assert hasattr(transformers, name), f"transformers.{name} is gone"
    assert _accepts(transformers.AutoModelForCausalLM.from_pretrained, ("device_map",))


def test_transformers_trainer_still_takes_processing_class_not_tokenizer() -> None:
    # The live LoRA path passes `processing_class=` (_huggingface_live.py). 4.46
    # deprecated `tokenizer=` and 5.x removed it; the adapter is on the correct
    # side of that only because it was migrated deliberately at the 5.13 bump.
    # This pins the migration so a rename back - or onward - is caught here.
    transformers = pytest.importorskip("transformers")
    trainer_params = _params(transformers.Trainer.__init__)
    assert "processing_class" in trainer_params, (
        "transformers.Trainer no longer takes processing_class; "
        "_huggingface_live.py passes it when constructing the Trainer"
    )


def test_transformers_training_arguments_take_every_option_we_pass() -> None:
    transformers = pytest.importorskip("transformers")
    passed = (
        "output_dir",
        "num_train_epochs",
        "per_device_train_batch_size",
        "logging_steps",
        "save_strategy",
        "report_to",
    )
    missing = sorted(set(passed) - _params(transformers.TrainingArguments.__init__))
    assert not missing, f"TrainingArguments no longer accepts: {missing}"


def test_peft_lora_surface() -> None:
    # _huggingface_live builds LoraConfig(r=, lora_alpha=, task_type=,
    # target_modules=), wraps a fresh base with get_peft_model, and reloads a
    # stored adapter with PeftModel.from_pretrained.
    peft = pytest.importorskip("peft")
    for name in ("LoraConfig", "PeftModel", "get_peft_model"):
        assert hasattr(peft, name), f"peft.{name} is gone"
    assert _accepts(peft.LoraConfig.__init__, ("r", "lora_alpha", "task_type", "target_modules"))
    assert len(_params(peft.get_peft_model)) >= 2, "get_peft_model(model, config) changed shape"
    assert hasattr(peft.PeftModel, "from_pretrained")


# --- openai: embeddings, vLLM completions, and the Assistants beta namespace ---


def _openai_client() -> Any:
    """A client built with a dummy key: construction makes no network call."""
    openai = pytest.importorskip("openai")
    return openai.OpenAI(api_key="sk-not-a-real-key")


def test_openai_client_constructor_surface() -> None:
    # OpenAIEmbedding passes api_key=; _vllm_live passes base_url=/api_key=/timeout=.
    openai = pytest.importorskip("openai")
    assert _accepts(openai.OpenAI.__init__, ("api_key", "base_url", "timeout"))


def test_openai_embeddings_and_completions_surface() -> None:
    # OpenAIEmbedding.embed -> .embeddings.create(model=, input=)
    # _VllmLiveBackend.complete -> .completions.create(model=, prompt=, max_tokens=,
    # temperature=). `completions` is the legacy namespace, so its removal in favour
    # of chat-only is a plausible upstream change and would break the vLLM adapter.
    client = _openai_client()
    assert _accepts(client.embeddings.create, ("model", "input"))
    assert _accepts(client.completions.create, ("model", "prompt", "max_tokens", "temperature"))


def test_openai_assistants_beta_namespace_surface() -> None:
    # The whole Assistants adapter hangs off `client.beta`, which is by name a
    # provisional namespace - OpenAI graduating or retiring it is the single most
    # likely break in this file, and it would take out every method below at once.
    client = _openai_client()
    beta = client.beta
    assert _accepts(beta.assistants.create, ("model", "name", "instructions", "tools"))
    threads = beta.threads
    assert hasattr(threads, "create")
    assert _accepts(threads.messages.create, ("thread_id", "role", "content"))
    assert _accepts(threads.messages.list, ("thread_id", "order"))
    assert _accepts(threads.runs.create, ("thread_id", "assistant_id"))
    assert _accepts(threads.runs.retrieve, ("thread_id", "run_id"))
    assert hasattr(threads.runs, "submit_tool_outputs")


# --- anthropic: adapters.agent._anthropic_tooluse_live ----------------------


def test_anthropic_messages_create_surface() -> None:
    # The tool-use loop calls .messages.create(model=, max_tokens=, system=,
    # tools=, messages=) and reads `.content` blocks whose `.type` is "tool_use".
    anthropic = pytest.importorskip("anthropic")
    assert _accepts(anthropic.Anthropic.__init__, ("api_key",))
    client = anthropic.Anthropic(api_key="sk-ant-not-a-real-key")
    assert _accepts(client.messages.create, ("model", "max_tokens", "system", "tools", "messages"))


# --- langfuse: adapters.observability.langfuse ------------------------------


def test_langfuse_client_and_api_namespace_surface() -> None:
    # LangfuseObservability constructs Langfuse(public_key=, secret_key=, host=)
    # and reaches through `.api` for every operation: projects.get() to list
    # tenants, trace.list(user_id=, limit=, page=) to page a tenant's traces, and
    # trace.delete_multiple(trace_ids=) to erase them. `.api` is the v3+ layout;
    # a restructure there breaks the whole adapter, including its erasure path.
    langfuse = pytest.importorskip("langfuse")
    assert _accepts(langfuse.Langfuse.__init__, ("public_key", "secret_key", "host"))
    client = langfuse.Langfuse(
        public_key="pk-not-real", secret_key="sk-not-real", host="http://localhost:1"
    )
    api = client.api
    assert hasattr(api.projects, "get")
    assert _accepts(api.trace.list, ("user_id", "limit", "page"))
    assert _accepts(api.trace.delete_multiple, ("trace_ids",))
