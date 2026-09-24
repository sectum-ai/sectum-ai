"""Invariant: every planting action the runner recognises is read back.

A planting probe writes, then reads across a principal boundary. A store that
acknowledges the write and drops it - a zero TTL, a read-only replica, a quota -
leaves the probe reading for something that was never there: it runs, finds
nothing, and looks exactly like isolation working. `Runner._plant_landed` reads
each plant back so that class is `NOT_COVERED` rather than `PASS`.

It reads back by ACTION, in a chain of `if`s, and its fallthrough is
``return True`` - "assume it landed". That is the right default for `model.train`
(a failed training raises, so the silent-drop shape cannot arise) and the wrong
one for anything else: a fifth plant action added to `_PLANT_ACTIONS` and not to
`_plant_landed` would be assumed to have landed, silently, and the vacuous pass
this whole mechanism exists to refuse would come back for that one action.

This repo's recurring defect is a rule applied to one member of a family and not
its siblings, so the family is pinned here rather than trusted.
"""

import ast
from pathlib import Path

from sectum_ai import runner as runner_module
from sectum_ai.runner import _PLANT_ACTIONS

_SOURCE = Path(runner_module.__file__)

#: The one action whose failure MODE, not whose read-back, makes it safe:
#: `HuggingFaceLoraModel.train_adapter` wraps a failed train in `AdapterError`,
#: so it cannot silently not-happen. Adding to this set is a claim about the
#: adapter family, and belongs with the reasoning `_plant_landed` states.
_EXEMPT_BECAUSE_IT_RAISES = frozenset({"model.train"})


def _actions_compared_in(function: str) -> set[str]:
    """Every string literal compared against ``step.action`` inside ``function``."""
    tree = ast.parse(_SOURCE.read_text())
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == function)
    return {
        comparator.value
        for compare in ast.walk(node)
        if isinstance(compare, ast.Compare)
        and isinstance(compare.left, ast.Attribute)
        and compare.left.attr == "action"
        for comparator in compare.comparators
        if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str)
    }


def test_every_plant_action_is_read_back_or_documented_as_raising() -> None:
    read_back = _actions_compared_in("_plant_landed")
    unchecked = set(_PLANT_ACTIONS) - read_back - _EXEMPT_BECAUSE_IT_RAISES
    assert not unchecked, (
        f"plant action(s) {sorted(unchecked)} are planted but never read back: "
        "`_plant_landed` falls through to `return True`, so a backend that drops "
        "the write is recorded as a landed plant and the class grades PASS off "
        "zero observations"
    )


def test_the_read_back_does_not_claim_actions_that_are_never_planted() -> None:
    # The other direction: a read-back for an action no probe plants is dead code
    # that reads like coverage. Both halves keep the family honest.
    assert _actions_compared_in("_plant_landed") <= set(_PLANT_ACTIONS)
