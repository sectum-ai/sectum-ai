"""Invariant: every probe ships a ``probe.yaml`` manifest that mirrors its class
attributes (the engineering spec, section 7.0 - "Each probe ships with ... a
manifest (probe.yaml)").

The manifest is the declarative catalog the suite selector / dashboards / external
tooling consume; the Python class attributes are authoritative. This guards
against drift between the two. Regenerate with
``uv run python scripts/gen_probe_manifests.py`` when this fails - never silence
it.
"""

from pathlib import Path
from typing import Any, cast

import pytest

import sectum_ai.probes as probes
from sectum_ai.probes import ERASURE_SURFACES, SUBJECT_VERIFIABLE_SURFACES, load_probe_manifest

_REPO_ROOT = Path(__file__).resolve().parents[2]

# The workflow probes carry no class-level `surfaces` / `requires_adapters`, so the
# generator sources them from its own `_WORKFLOW_SURFACES` / `_WORKFLOW_REQUIRES` tables.
# Guarding the parity assertions behind `hasattr` therefore skipped exactly the probes
# whose manifests CAN drift from the code - and subject-erasure's manifest silently lost
# `tracing` that way. Surfaces are asserted against the canonical constants the probe
# actually scans (not the generator's table, which would compare the generator to itself);
# the adapter lists have no canonical constant, so they are pinned here deliberately, and
# a change to either must be a conscious edit rather than a silent regeneration.
_WORKFLOW_SURFACES: dict[str, list[str]] = {
    "kv-cache-timing": ["kv_cache"],
    "gdpr-erasure-verification": [surface.value for surface in ERASURE_SURFACES],
    "gdpr-subject-erasure-verification": [surface.value for surface in SUBJECT_VERIFIABLE_SURFACES],
}
_WORKFLOW_REQUIRES: dict[str, list[str]] = {
    "kv-cache-timing": ["model"],
    "gdpr-erasure-verification": ["vector_store"],
    "gdpr-subject-erasure-verification": ["vector_store", "cache"],
}


def _probe_classes() -> list[type]:
    classes: list[type] = []
    for name in probes.__all__:
        obj = getattr(probes, name)
        if isinstance(obj, type) and getattr(obj, "id", None) and hasattr(obj, "owasp_llm"):
            classes.append(obj)
    return classes


_PROBES = _probe_classes()
_IDS = [str(cast(Any, cls).id) for cls in _PROBES]


def test_every_probe_class_is_discovered() -> None:
    # 12 plan/detect probes + the erasure, subject-erasure, and kv-cache workflows = 15.
    assert len(_PROBES) == 15


@pytest.mark.parametrize("cls", _PROBES, ids=_IDS)
def test_probe_manifest_mirrors_class_attributes(cls: type) -> None:
    probe = cast(Any, cls)  # probe metadata lives as dynamic class attributes
    manifest: dict[str, Any] = load_probe_manifest(cls)
    assert manifest["id"] == probe.id
    assert manifest["name"] == probe.name
    assert manifest["owasp_llm"] == probe.owasp_llm
    assert manifest["owasp_secondary"] == list(probe.owasp_secondary)
    assert manifest["nist_rmf"] == list(probe.nist_rmf)
    assert manifest["atlas_techniques"] == list(probe.atlas_techniques)
    assert manifest["kind"] in {"plan-detect", "workflow"}
    assert manifest["surfaces"], "every manifest must declare at least one surface"
    # The plan/detect probes carry class-level surfaces/requires_adapters; those must match
    # the manifest exactly. The workflow probes (erasure, subject-erasure, kv-cache) carry
    # neither, so they are checked against the canonical sets above - never skipped.
    if hasattr(cls, "surfaces"):
        assert manifest["surfaces"] == [surface.value for surface in probe.surfaces]
    else:
        assert manifest["surfaces"] == _WORKFLOW_SURFACES[probe.id]
    if hasattr(cls, "requires_adapters"):
        assert manifest["requires_adapters"] == list(probe.requires_adapters)
    else:
        assert manifest["requires_adapters"] == _WORKFLOW_REQUIRES[probe.id]


def test_every_workflow_probe_has_pinned_surface_and_adapter_expectations() -> None:
    # A workflow probe added without an entry above would otherwise re-open the hole by
    # KeyError rather than by a silent skip; name the requirement explicitly instead.
    workflow = {str(cast(Any, cls).id) for cls in _PROBES if not hasattr(cls, "surfaces")}
    assert workflow == set(_WORKFLOW_SURFACES) == set(_WORKFLOW_REQUIRES)


def test_manifest_ids_are_unique_and_match_the_classes() -> None:
    ids = [load_probe_manifest(cls)["id"] for cls in _PROBES]
    assert len(ids) == len(set(ids)), "duplicate probe-manifest ids"
    assert set(ids) == set(_IDS)


@pytest.mark.parametrize("cls", _PROBES, ids=_IDS)
def test_manifest_example_points_to_a_real_directory(cls: type) -> None:
    example = load_probe_manifest(cls).get("example")
    if example is not None:
        assert (_REPO_ROOT / example).is_dir(), f"example dir missing ({example})"


def test_the_probes_shipping_a_runnable_example_are_pinned() -> None:
    # The guard above skips a probe whose `example` key is absent, so a probe that silently
    # LOST its example would pass rather than fail - the same skip shape that hid the
    # surface drift. Pin the split instead: a probe gaining or losing its demo must be a
    # conscious edit here, not a quiet regeneration.
    with_example = {
        str(cast(Any, cls).id) for cls in _PROBES if load_probe_manifest(cls).get("example")
    }
    assert with_example == {
        "agent-framework-hijack",
        "agent-tool-hijack",
        "embedding-inversion",
        "gdpr-erasure-verification",
        "ikea-extraction",
        "kv-cache-timing",
        "lora-cross-tenant",
        "memory-contamination",
        "rag-entity-bleed",
        "rag-poisoning",
        "semantic-cache-contamination",
        "tenant-boundary-fetch",
    }
