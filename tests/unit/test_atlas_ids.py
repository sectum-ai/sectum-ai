"""Standing guard: every probe's MITRE ATLAS technique id is well-formed and was
verified against the live catalog (ADR-0009 validation log).

ADR-0009 keeps rename/fit judgement a manual release-time sweep and deliberately
rejects a *network* CI check. This is the offline complement that ADR calls for:
it catches a typo'd id (``AML.TOO24`` - "no natural type-system guard", per the
ADR) and a not-yet-swept id, forcing a re-validation and a log entry before any
new id ships. It does not - and cannot - judge renames or fit.
"""

import re
from typing import Any, cast

import sectum_ai.probes as probes

# The ids verified against the MISP galaxy ATLAS mirror, most recently on
# 2026-07-18 (docs/adr/0009-atlas-technique-review-process.md, "Validation log").
# Adding an id here REQUIRES re-running that sweep and recording the result in the
# ADR. `AML.T0051.001` is named just "Indirect" upstream - it is a sub-technique of
# `AML.T0051` LLM Prompt Injection, and the catalog does not repeat the parent name.
_VERIFIED_ATLAS_IDS: dict[str, str] = {
    "AML.T0020": "Poison Training Data",
    "AML.T0024": "Exfiltration via ML Inference API",
    "AML.T0024.000": "Infer Training Data Membership",
    "AML.T0024.001": "Invert ML Model",
    "AML.T0051.001": "Indirect",
    "AML.T0053": "LLM Plugin Compromise",
    "AML.T0057": "LLM Data Leakage",
}

_ATLAS_ID = re.compile(r"^AML\.T\d{4}(\.\d{3})?$")


def _probe_classes() -> list[type]:
    classes: list[type] = []
    for name in probes.__all__:
        obj = getattr(probes, name)
        if isinstance(obj, type) and hasattr(obj, "atlas_techniques") and getattr(obj, "id", None):
            classes.append(obj)
    return classes


def _used_atlas_ids() -> set[str]:
    used: set[str] = set()
    for cls in _probe_classes():
        used |= set(cast(Any, cls).atlas_techniques)
    return used


def test_probe_classes_are_discovered() -> None:
    assert len(_probe_classes()) >= 11


def test_every_atlas_id_is_well_formed() -> None:
    for cls in _probe_classes():
        for tid in cast(Any, cls).atlas_techniques:
            assert _ATLAS_ID.match(tid), f"malformed ATLAS id {tid!r} on {cls.__name__}"


def test_every_atlas_id_was_verified_against_the_catalog() -> None:
    unverified = _used_atlas_ids() - set(_VERIFIED_ATLAS_IDS)
    assert not unverified, (
        f"probes use ATLAS ids not in the ADR-0009 verified set: {sorted(unverified)}. "
        "Re-run the ADR-0009 sweep against the MISP mirror, add the verified id + name "
        "to _VERIFIED_ATLAS_IDS, and append a Validation log entry to the ADR."
    )


def test_no_stale_allowlist_entries() -> None:
    # Keep the allowlist honest: every verified id is still used by some probe, so
    # it documents the live catalog footprint, not historical cruft.
    unused = set(_VERIFIED_ATLAS_IDS) - _used_atlas_ids()
    assert not unused, f"verified ATLAS ids no longer used by any probe: {sorted(unused)}"


def test_every_atlas_id_a_probe_declares_is_published_on_its_class_page() -> None:
    # The offline half of ADR-0009's release gate, run per commit instead of per
    # release: ten releases shipped with no entry in the ADR's validation log
    # because the release PR description was the only place it was written down
    # and nothing reads that back. This cannot judge an upstream rename - the ADR
    # is explicit that only the manual mirror sweep can - but it does hold the
    # probe, the catalog page and the pinned set to one answer, which is the half
    # that can drift silently between releases.
    import re
    from pathlib import Path

    import sectum_ai.probes as probes_module

    catalog = Path(__file__).resolve().parents[2] / "docs" / "attack-catalog"
    pages = {path: path.read_text() for path in catalog.glob("class-*.md")}
    assert pages, catalog

    declared = {
        cls.id: tuple(cls.atlas_techniques)
        for cls in (getattr(probes_module, name) for name in dir(probes_module))
        if isinstance(cls, type) and hasattr(cls, "atlas_techniques") and hasattr(cls, "id")
    }
    assert declared, "no probes discovered - the introspection broke"

    for probe_id, ids in declared.items():
        for page, text in pages.items():
            if not re.search(rf"\b{re.escape(probe_id)}\b", text):
                continue
            missing = [atlas for atlas in ids if atlas not in text]
            assert not missing, f"{probe_id} declares {missing}, absent from {page.name}"
