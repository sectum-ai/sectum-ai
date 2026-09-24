"""Every caller that renders an audit PDF tells it whether the pack is anchored.

The PDF states the pack's independent-anchor status, and it is rendered BEFORE
the token that would prove it - so `render_audit_pack_and_hash` takes the INTENT,
defaulting to `(False, False)`. `report` passes it; `erasure` did not, and took
the default: an `evidence.timestamper: rfc3161` attestation bound a PDF reading
"Independent anchor: NONE ... reproducible by anyone over any digest", the bound
document contradicting the pack that binds it.

That default is the right one (unanchored is the conservative claim), which is
exactly why a missing argument is silent. Swept here rather than asserted per
caller, so the third caller added tomorrow cannot take it either.
"""

import ast
from pathlib import Path

_SOURCE = Path(__file__).resolve().parents[2] / "packages/core/src/sectum_ai/cli/app.py"


def test_every_audit_pdf_render_passes_the_anchor_intent() -> None:
    tree = ast.parse(_SOURCE.read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "render_audit_pack_and_hash"
    ]
    assert len(calls) == 2, f"expected report and erasure; found {len(calls)} render call(s)"
    silent = [
        f"{_SOURCE.name}:{call.lineno}"
        for call in calls
        if not any(keyword.arg == "anchors" for keyword in call.keywords)
    ]
    assert not silent, f"render call(s) taking the unanchored default silently: {silent}"
