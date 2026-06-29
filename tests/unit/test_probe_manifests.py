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
from sectum_ai.probes import load_probe_manifest

_REPO_ROOT = Path(__file__).resolve().parents[2]


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
    # 11 plan/detect probes + the erasure, subject-erasure, and kv-cache workflows = 14.
    assert len(_PROBES) == 14


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
    # The plan/detect probes carry class-level surfaces/requires_adapters; those
    # must match the manifest exactly. The workflow probes (erasure, kv-cache)
    # carry neither as a class attribute, so only the non-empty check applies.
    if hasattr(cls, "surfaces"):
        assert manifest["surfaces"] == [surface.value for surface in probe.surfaces]
    if hasattr(cls, "requires_adapters"):
        assert manifest["requires_adapters"] == list(probe.requires_adapters)


def test_manifest_ids_are_unique_and_match_the_classes() -> None:
    ids = [load_probe_manifest(cls)["id"] for cls in _PROBES]
    assert len(ids) == len(set(ids)), "duplicate probe-manifest ids"
    assert set(ids) == set(_IDS)


@pytest.mark.parametrize("cls", _PROBES, ids=_IDS)
def test_manifest_example_points_to_a_real_directory(cls: type) -> None:
    example = load_probe_manifest(cls).get("example")
    if example is not None:
        assert (_REPO_ROOT / example).is_dir(), f"example dir missing ({example})"
