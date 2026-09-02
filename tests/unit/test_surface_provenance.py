"""The signed run states what it interrogated, not just which adapters it named.

Sectum ships an in-memory fake for every adapter family, and ``build_adapters``
resolves an omitted key to one. Before ``surface_provenance`` existed, a run
against eight fakes graded ``A`` at ``confidence: high``, packed into a
signature-clean attestation, and produced an audit PDF that never said the word
synthetic - the prime directive's failure mode (claiming more than was measured)
applied to the whole attestation rather than to one probe.

The only trace was the ``adapter_versions`` keys reading ``fake-vector``, and a
name is a constructor argument any caller can set to anything. So provenance is a
declared class attribute, recorded per surface, inside the canonical hash.
"""

import dataclasses
import inspect
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sectum_ai.adapters import base as adapters_base
from sectum_ai.adapters import fakes as adapters_fakes
from sectum_ai.cli.app import _warn_on_synthetic_surfaces, app
from sectum_ai.config import (
    _BUNDLE_SLOTS,
    AdapterBundle,
    AdapterConfig,
    SectumConfig,
    build_adapters,
    surface_provenance,
)
from sectum_ai.spec import Surface, SurfaceProvenance

_runner = CliRunner()

_FAKE_CLASSES = [
    obj
    for _, obj in inspect.getmembers(adapters_fakes, inspect.isclass)
    if obj.__name__.startswith("Fake") and obj.__module__ == adapters_fakes.__name__
]


def test_every_fake_adapter_declares_itself_synthetic() -> None:
    # A fake added later that inherits the default would be recorded as LIVE and
    # would silently restore the over-claim this block exists to close.
    assert _FAKE_CLASSES, "no fake adapters discovered - the introspection broke"
    missed = sorted(c.__name__ for c in _FAKE_CLASSES if not c.synthetic)
    assert not missed, f"fake adapters not marked synthetic: {missed}"


def test_a_real_adapter_is_not_synthetic_by_default() -> None:
    # The default has to be LIVE-by-omission's opposite: a live adapter author
    # writes nothing, so the honest value is the one that claims less.
    assert adapters_base.Adapter.synthetic is False


def test_no_adapter_outside_the_fakes_module_claims_to_be_synthetic() -> None:
    for name, obj in inspect.getmembers(adapters_base, inspect.isclass):
        if issubclass(obj, adapters_base.Adapter):
            assert not obj.synthetic, f"{name} in base.py declares synthetic"


def test_the_slot_list_covers_every_field_of_the_bundle() -> None:
    # A family added to AdapterBundle but not to _BUNDLE_SLOTS would be exercised
    # by the suite and omitted from the provenance block entirely, which reads to
    # a pack consumer as a surface that was never touched.
    declared = {f.name for f in dataclasses.fields(AdapterBundle)}
    assert set(_BUNDLE_SLOTS) == declared, (
        f"unlisted bundle fields: {sorted(declared - set(_BUNDLE_SLOTS))}"
    )


def test_each_slot_contributes_a_distinct_known_surface() -> None:
    # Two slots collapsing onto one surface would silently overwrite each other in
    # the provenance dict, hiding one family's liveness behind another's.
    bundle = build_adapters(SectumConfig())
    surfaces = [getattr(bundle, slot).surface for slot in _BUNDLE_SLOTS]
    assert len(set(surfaces)) == len(surfaces), "two bundle slots report one surface"
    assert all(s in Surface for s in surfaces)


def test_a_default_config_records_every_surface_as_synthetic() -> None:
    provenance = surface_provenance(build_adapters(SectumConfig()))
    assert set(provenance.values()) == {SurfaceProvenance.SYNTHETIC.value}
    assert len(provenance) == len(_BUNDLE_SLOTS)


def test_a_configured_backend_records_that_surface_as_live() -> None:
    # The HTTP RAG adapter is the one live kind that needs no running backend to
    # construct, so it exercises the LIVE branch without a network dependency.
    config = SectumConfig(
        adapters={"rag": AdapterConfig(kind="http", url="http://127.0.0.1:9/rag")}
    )
    provenance = surface_provenance(build_adapters(config))
    assert provenance[Surface.RAG_PIPELINE.value] == SurfaceProvenance.LIVE.value
    others = {s: v for s, v in provenance.items() if s != Surface.RAG_PIPELINE.value}
    assert set(others.values()) == {SurfaceProvenance.SYNTHETIC.value}


def test_an_omitted_family_is_recorded_as_synthetic_not_live() -> None:
    # Provenance is read off the built instance, not the config, so a family the
    # config never mentions is recorded as the fake it resolved to rather than
    # being absent. A misspelled key used to reach this same state; it is now
    # rejected at load instead (tests/unit/test_adapter_key_validation.py), which
    # leaves omission as the way a live-looking config still probes nothing real.
    config = SectumConfig(adapters={"cache": AdapterConfig(kind="fake")})
    provenance = surface_provenance(build_adapters(config))
    assert provenance[Surface.VECTOR_DB.value] == SurfaceProvenance.SYNTHETIC.value


@pytest.mark.parametrize("member", list(SurfaceProvenance))
def test_provenance_values_are_stable_strings(member: SurfaceProvenance) -> None:
    # Stored as plain strings in the canonical form (like erasure_coverage), so a
    # renamed value silently changes every previously signed pack's meaning.
    assert member.value in {"LIVE", "SYNTHETIC"}


def test_probe_records_the_provenance_block_in_the_run(tmp_path: Path) -> None:
    # The end of the wire: the block has to reach run.json, which is what gets
    # hashed, packed, signed, and read by whoever receives the attestation.
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    _runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    recorded = json.loads((tmp_path / "run.json").read_text())["surface_provenance"]
    assert len(recorded) == len(_BUNDLE_SLOTS)
    assert set(recorded.values()) == {SurfaceProvenance.SYNTHETIC.value}


def test_probe_warns_the_operator_when_no_surface_is_live(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    assert "no live adapter configured for every surface" in result.output
    assert "not your production systems" in result.output


def test_the_warning_names_the_synthetic_surfaces_when_some_are_live(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A partly-live run is the dangerous middle case: the operator sees real
    # backends in their config and reasonably assumes the whole run was real.
    _warn_on_synthetic_surfaces(
        {
            Surface.VECTOR_DB.value: SurfaceProvenance.LIVE.value,
            Surface.SEMANTIC_CACHE.value: SurfaceProvenance.SYNTHETIC.value,
        }
    )
    warning = capsys.readouterr().err
    assert Surface.SEMANTIC_CACHE.value in warning
    assert Surface.VECTOR_DB.value not in warning


def test_no_warning_when_every_surface_is_live(capsys: pytest.CaptureFixture[str]) -> None:
    _warn_on_synthetic_surfaces({Surface.VECTOR_DB.value: SurfaceProvenance.LIVE.value})
    assert capsys.readouterr().err == ""
