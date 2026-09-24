"""Invariant: every live model backend times TIME TO FIRST TOKEN, not a full generation.

`model/_serving.py` states the rule normatively - "a shared KV prefix cache speeds
up the PREFILL, which determines TTFT, so TTFT (not total generation time)
isolates the cross-tenant cache signal the Class 5 probe is built to catch" - and
the two serving backends implement it by streaming and breaking on the first
chunk. The HuggingFace backend called `infer`, which generates 64 tokens: the
decode steps cost the same in both arms, so they added variance to Cohen's d's
denominator without adding to its numerator. The mean gap survived and d
collapsed, biasing Class 5 toward a MISS and downgrading a detected channel from
HIGH to MEDIUM.

Checked structurally rather than by running it. These backends need `torch`,
`transformers`, `openai` and `huggingface_hub`, none of which are installed in the
default workspace - which is exactly why the defect survived: the only test that
touches `measure_latency_ms` drives a stub defined in the test file, so the live
implementations have no executed coverage at all. An AST guard is what can hold
here, the way `test_pdf_anchor_intent.py` pins a call it cannot run.
"""

import ast
from pathlib import Path

_LIVE = Path(__file__).resolve().parents[2] / "packages/adapters/src/sectum_ai/adapters/model"


def _method(source: str, name: str) -> ast.FunctionDef:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is gone; retarget this guard")


def test_huggingface_latency_times_one_token_and_does_not_call_infer() -> None:
    method = _method((_LIVE / "_huggingface_live.py").read_text(), "measure_latency_ms")
    called = {
        node.func.attr
        for node in ast.walk(method)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "infer" not in called, (
        "measure_latency_ms calls infer(), which generates 64 tokens - that is total "
        "generation time, not TTFT, and it buries the prefill signal Class 5 reads"
    )
    assert "generate" in called, called
    budgets = [
        keyword.value.value
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "max_new_tokens" and isinstance(keyword.value, ast.Constant)
    ]
    assert budgets == [1], f"the timed generation must stop at the first token, got {budgets}"


def test_the_serving_siblings_still_break_on_the_first_chunk() -> None:
    # The two that were already right, asserted so the family cannot drift the
    # other way: a `break` inside the streaming loop is what makes them TTFT.
    for name in ("_vllm_live.py", "_tgi_live.py"):
        method = _method((_LIVE / name).read_text(), "first_token_latency_ms")
        assert any(isinstance(node, ast.Break) for node in ast.walk(method)), (
            f"{name} no longer stops at the first streamed chunk, so it now times "
            "the whole generation"
        )
