"""`docs/compliance-mappings.md` is the assertion an auditor reads before the pack.

The page's table is a hand-maintained second copy of `_CONTROL_TABLE`, and it
drifted twice: the HIPAA row claimed "PHI tenant segregation verified", a
health-specific claim no pack has ever made, and the ISO 42001 row dropped "AI
system" from what the pack actually says. A reader who checks the page against a
pack must find the same words.
"""

import re
from pathlib import Path

from sectum_ai.evidence.controls import _CONTROL_TABLE

_ROOT = Path(__file__).resolve().parents[2]
_PAGE = _ROOT / "docs" / "compliance-mappings.md"


def _documented() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for line in _PAGE.read_text().splitlines():
        if not line.startswith("| ") or line.startswith("|---"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 3 or cells[0] in ("Framework",):
            continue
        rows.append((cells[0], cells[1], cells[2]))
    return rows


def _plain(text: str) -> str:
    """Drop the page's emphasis markers; the assertion text is otherwise verbatim."""
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text).replace("`", "")


def test_every_documented_framework_row_matches_the_shipped_assertion() -> None:
    shipped = {
        (framework, ", ".join(controls)): assertion
        for framework, controls, assertion, *_ in _CONTROL_TABLE
    }
    documented = {
        (framework, controls): assertion for framework, controls, assertion in _documented()
    }
    assert documented, "no framework rows parsed from docs/compliance-mappings.md"
    assert set(documented) == set(shipped), (
        "docs/compliance-mappings.md and evidence.controls._CONTROL_TABLE disagree on "
        f"which (framework, controls) rows exist: only in the page "
        f"{sorted(set(documented) - set(shipped))}; only in the code "
        f"{sorted(set(shipped) - set(documented))}"
    )
    for key, assertion in documented.items():
        assert _plain(assertion) == shipped[key], (
            f"docs/compliance-mappings.md states {assertion!r} for {key}, but a pack "
            f"asserts {shipped[key]!r}"
        )
