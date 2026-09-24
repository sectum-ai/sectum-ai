"""Invariant: the counts `docs/scorecard.md` states are the counts the code has.

The published methodology is the artifact a reader recomputes a grade from, and it
states two counts outright: how many honesty rules there are, and how many notes
can attach to a `PASS`. Both are determined by the code, and both have drifted -
the page said "Six rules prevent it" while `score` applied seven and five separate
sentences elsewhere on the page pointed at "rule 7", and it said "Five notes attach
to one" while `_score_class` assembled seven.

A count is the cheapest kind of documentation to falsify and the easiest to leave
behind, so it is pinned here rather than remembered.
"""

import ast
import re
from pathlib import Path

from sectum_ai import score as score_module

_PAGE = Path(__file__).resolve().parents[2] / "docs" / "scorecard.md"
_SOURCE = Path(score_module.__file__)
_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def _stated(pattern: str) -> int:
    match = re.search(pattern, _PAGE.read_text(), re.IGNORECASE)
    assert match, f"the page no longer states this count: {pattern}"
    return _WORDS[match.group(1).lower()]


def _pass_note_slots() -> int:
    tree = ast.parse(_SOURCE.read_text())
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_score_class"
    )
    notes = next(
        node.value
        for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "notes"
    )
    assert isinstance(notes, ast.List)
    return len(notes.elts)


def test_the_page_states_as_many_honesty_rules_as_it_lists() -> None:
    # Both halves of the same claim: the lead sentence's number and the list under
    # it. The page drifted by having the second updated and not the first.
    stated = _stated(r"over-claim\. (\w+) rules prevent it")
    heading = _stated(r"## The (\w+) honesty rules")
    # The numbered list under "How the letter is computed" shares the same shape, so
    # count only up to that heading.
    rules_section = _PAGE.read_text().split("## The catalog and its weights")[0]
    listed = len(re.findall(r"^\d+\. \*\*", rules_section, re.MULTILINE))
    assert stated == listed == heading, (stated, listed, heading)


def test_the_page_states_as_many_pass_notes_as_the_scorer_can_attach() -> None:
    stated = _stated(r"establish\. (\w+) notes attach to")
    body = _PAGE.read_text()
    section = body[body.index("notes attach to") :].split("## ")[0]
    listed = len(re.findall(r"^- \*\*", section, re.MULTILINE))
    assert stated == listed == _pass_note_slots(), (stated, listed, _pass_note_slots())


def test_the_changelog_announces_the_methodology_stamp_the_code_ships() -> None:
    # The stamp is a recompute contract - a given version always recomputes to the
    # same letter - so the release notes naming a superseded one tells a reader
    # their `1.3` packs are current. `[Unreleased]` carried BOTH: a `Changed`
    # headline announcing `1.3` and, 1100 lines below it, an entry announcing the
    # `1.4` the code actually stamps. A count is cheap to falsify; so is a version.
    changelog = Path(__file__).resolve().parents[2] / "CHANGELOG.md"
    text = changelog.read_text()
    start = text.index("## [Unreleased]")
    unreleased = text[start : text.index("\n## [", start + 1)]
    shipped = score_module.METHODOLOGY_VERSION
    headline = re.search(r"\*\*Scorecard methodology `([0-9.]+)`", unreleased)
    assert headline, "the Unreleased section no longer announces a methodology stamp"
    assert headline.group(1) == shipped, (
        f"CHANGELOG announces methodology {headline.group(1)!r}; score.py stamps {shipped!r}"
    )
