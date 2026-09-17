"""Invariant: the Class 7 walkthroughs disclose that a live agent kind REMOVES the class.

`sectum-ai probe` marks the agent and MCP surfaces unreachable when they are not
synthetic, because the lookup target is an id Sectum invents and no agent adapter
has a write primitive - so pointing `agent.kind` at a live backend makes Class 7
read `NOT_COVERED` rather than measuring the customer's framework.

Four sites in the two walkthroughs said the opposite: that the probe "runs against
every shipped v1 agent backend", that "only the agent.kind in sectum-ai.yaml
changes", and that "the same leak shows up regardless of which agent framework a
customer uses". `docs/coverage.md` had it right, and the fix that landed the
correct blockquote in the README put it three lines below the paragraph it did not
touch, without touching either `run.sh` - the repair reached one sibling of four.

Pinned against the CLI's own reachability rule, so the pair cannot drift apart in
either direction: if the CLI ever grows a live agent path, this fails and asks for
the prose back.
"""

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_WALKTHROUGHS = (
    "examples/agent-framework-hijack/run.sh",
    "examples/agent-framework-hijack/README.md",
    "examples/agent-tool-hijack/run.sh",
)
_LIVE_KINDS = ("langgraph", "autogen", "crewai")


def _cli_source() -> str:
    return (_ROOT / "packages/core/src/sectum_ai/cli/app.py").read_text()


def test_the_cli_still_skips_class_7_against_a_live_agent() -> None:
    # The premise of the disclosure below. `_skip_unreachable` marks the agent and
    # MCP slots unreachable whenever they are NOT synthetic; if that ever changes,
    # the walkthroughs are owed their old wording back and this test says so.
    tree = ast.parse(_cli_source())
    marked = {
        node.targets[0].slice.value: node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Subscript)
        and isinstance(node.targets[0].value, ast.Name)
        and node.targets[0].value.id == "reachable"
        and isinstance(node.targets[0].slice, ast.Constant)
        and isinstance(node.value, ast.Constant)
    }
    assert marked.get("agent") is False, (
        "the CLI no longer marks a live agent unreachable; the Class 7 "
        "walkthroughs now under-claim and must be updated"
    )
    assert marked.get("mcp") is False, "the CLI no longer marks a live MCP unreachable"


def test_every_class_7_walkthrough_discloses_that_a_live_kind_removes_the_class() -> None:
    for relative in _WALKTHROUGHS:
        text = (_ROOT / relative).read_text()
        named = [kind for kind in _LIVE_KINDS if kind in text.lower()]
        assert named, f"{relative} no longer names a live agent kind; retarget this guard"
        lowered = text.lower()
        assert "not_covered" in lowered, (
            f"{relative} names live agent kinds {named} without disclosing that "
            "configuring one makes Class 7 read NOT_COVERED"
        )
        assert any(
            phrase in lowered
            for phrase in ("removes class 7", "skips this probe against a live agent")
        ), f"{relative} does not say that a live agent kind takes Class 7 out of the run"


def test_no_walkthrough_still_promises_the_swap_carries_the_measurement() -> None:
    # The exact three sentences that were wrong, so a revert is caught by its words
    # and not only by the absence of the caveat.
    retired = (
        "the probe runs against every shipped v1 agent backend",
        "only the agent.kind in sectum-ai.yaml changes",
        "regardless of which agent framework a customer uses",
    )
    for relative in _WALKTHROUGHS:
        lowered = " ".join((_ROOT / relative).read_text().lower().split())
        for sentence in retired:
            assert sentence not in lowered, f"{relative} promises again: {sentence!r}"
