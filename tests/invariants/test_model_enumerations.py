"""Invariant: the two prose enumerations of a model family match the code.

`docs/data-models.md` names the nested models that have no standalone schema
file, and `labels.unaccounted_surfaces`' docstring counts the renderers that
answered "was this run live?" from the provenance block. Both are enumerations of
a family, and both drifted in the commit that grew the family: `DetectionProvenance`
landed as a fifth inline-only model and a fourth consumer (the OSCAL export) landed
beside the three the docstring names, and neither enumeration was updated.

`docs/scorecard.md`'s counts are pinned by `test_scorecard_doc_counts.py`; these two
were not, which is the whole of why they drifted. Same rule, same enforcement.
"""

import ast
import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCHEMAS = _ROOT / "packages/spec/src/sectum_ai/spec/schemas"
_PAGE = _ROOT / "docs" / "data-models.md"
_LABELS = _ROOT / "packages/evidence/src/sectum_ai/evidence/labels.py"
_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}


def _inline_only() -> set[str]:
    """Models that appear in some schema's `$defs` but own no schema file.

    Only MODELS - a `$defs` entry carrying `properties`. The enums a parent
    embeds the same way (`Severity`, `Grade`, `FindingStatus`, ...) are not what
    the page's sentence enumerates.
    """
    committed = {path.name.removesuffix(".schema.json") for path in _SCHEMAS.glob("*.schema.json")}
    nested: set[str] = set()
    for path in _SCHEMAS.glob("*.schema.json"):
        nested |= {
            name
            for name, definition in json.loads(path.read_text()).get("$defs", {}).items()
            if "properties" in definition
        }
    return nested - committed


def test_the_page_names_every_inline_only_nested_model() -> None:
    # Scoped to the ENUMERATING sentence, not the page. `DetectionProvenance` was
    # already named in a table row above it when the sentence went stale, so a
    # whole-page search passes while the enumeration is wrong - a guard that
    # cannot fail on the defect it was written for.
    page = " ".join(_PAGE.read_text().split())
    sentence = re.search(
        r"The nested models a parent embeds inline(.+?)have no standalone schema file", page
    )
    assert sentence, "the page no longer carries the inline-only enumeration"
    named = set(re.findall(r"`([A-Z][A-Za-z]+)`", sentence.group(1)))
    missing = sorted(model for model in _inline_only() if model not in named)
    assert not missing, (
        f"docs/data-models.md does not name inline-only nested model(s): {missing}. "
        "They have no standalone schema file, so the page is the only place a reader "
        "learns where to find them."
    )


def test_the_unaccounted_surfaces_docstring_counts_its_real_consumers() -> None:
    # Count the MODULES that import the helper, which is what "renderers" means
    # here - the scorecard's scope line and the field it sets live in one package
    # but read as one renderer to a reader, so compare against the module count.
    consumers = {
        path.relative_to(_ROOT).as_posix()
        for path in _ROOT.glob("packages/*/src/sectum_ai/**/*.py")
        if path != _LABELS
        and any(
            isinstance(node, ast.ImportFrom)
            and node.module == "sectum_ai.evidence.labels"
            and any(alias.name == "unaccounted_surfaces" for alias in node.names)
            for node in ast.walk(ast.parse(path.read_text()))
        )
    }
    docstring = ast.get_docstring(
        next(
            node
            for node in ast.walk(ast.parse(_LABELS.read_text()))
            if isinstance(node, ast.FunctionDef) and node.name == "unaccounted_surfaces"
        )
    )
    assert docstring
    match = re.search(r"^\s*(\w+) renderers", docstring, re.MULTILINE)
    assert match, "the docstring no longer opens by counting its renderers"
    stated = _WORDS[match.group(1).lower()]
    # `score.py` and `cli/app.py` are the scorecard's two halves and read as one.
    distinct = {path for path in consumers if "cli/app.py" not in path}
    assert stated == len(distinct), (
        f"the docstring says {stated} renderers; {len(distinct)} modules import it: "
        f"{sorted(distinct)}"
    )
