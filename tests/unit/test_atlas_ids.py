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

import sectum.probes as probes

# The ids verified against the MISP galaxy ATLAS mirror on 2026-06-01
# (docs/adr/0009-atlas-technique-review-process.md, "Validation log"). Adding an
# id here REQUIRES re-running that sweep and recording the result in the ADR.
_VERIFIED_ATLAS_IDS: dict[str, str] = {
    "AML.T0020": "Poison Training Data",
    "AML.T0024": "Exfiltration via ML Inference API",
    "AML.T0024.000": "Infer Training Data Membership",
    "AML.T0024.001": "Invert ML Model",
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
