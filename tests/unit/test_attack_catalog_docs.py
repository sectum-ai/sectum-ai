"""Standing guard: every probe in the registry is documented on an attack-catalog page.

Enumeration drift is this repo's recurring documentation failure: a probe ships, its class
page is not updated, and the stale page contains no string anyone would grep for. It is
invisible until a reader scopes a class's coverage from that page and undercounts what
actually runs. That is how ``rag-pipeline-bleed`` (Class 2, at the RAG-pipeline end) and
``gdpr-subject-erasure-verification`` (Class 11, data-subject granularity) both ended up
absent from every class page while the summary index and the code carried them.

The source of truth is the live probe registry. ``index.md`` is deliberately excluded from
the target: a probe present only in the summary table but on no class page is exactly the
drift that hid ``rag-pipeline-bleed``, so the index cannot vouch for a class page.

This checks *that* each probe is documented somewhere in the catalog, not *which* class
page carries it — the class-number-to-probe mapping is not available in this package. A
probe documented on the wrong class page would pass here; that is a weaker invariant than a
per-class map, but it catches the failure this repo actually produces.
"""

import re
from pathlib import Path
from typing import Any, cast

import sectum_ai.probes as probes

_CATALOG_DIR = Path(__file__).resolve().parents[2] / "docs" / "attack-catalog"


def _registry_probe_ids() -> set[str]:
    """Every catalog probe's id, filtered as the ATLAS-id guard filters (type + id + owasp)."""
    return {
        str(cast(Any, obj).id)
        for name in probes.__all__
        if isinstance(obj := getattr(probes, name), type)
        and getattr(obj, "id", None)
        and hasattr(obj, "owasp_llm")
    }


def _ids_named_on_class_pages() -> set[str]:
    named: set[str] = set()
    for page in _CATALOG_DIR.glob("class-*.md"):
        named |= set(re.findall(r"`([a-z0-9-]+)`", page.read_text(encoding="utf-8")))
    return named


def test_every_registry_probe_is_named_on_a_class_page() -> None:
    undocumented = _registry_probe_ids() - _ids_named_on_class_pages()
    assert not undocumented, (
        "these probes ship but no docs/attack-catalog/class-*.md page names them: "
        f"{sorted(undocumented)} (adding them to index.md alone is not enough)"
    )
