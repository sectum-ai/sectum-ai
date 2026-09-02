"""The application's own resource API as a probed surface.

The app under test is reached through the same contract a vector store is: a
write, a search, and a read-one-by-id that *is* the Class 1 cross-tenant
object-reference primitive. So it fills the vector slot and every probe driving
that slot runs unmodified — no probe changes, no schema change (``Surface.API``
was already in the enum and in the committed JSON Schemas).

What makes it honest rather than a relabelled vector store is that it declares
what it is: ``Surface.API``, so findings and provenance both say ``api``; and no
semantic retrieval, so the two classes whose verdicts depend on an embedding
space are skipped instead of passing vacuously.
"""

from typing import Any

import pytest

from sectum_ai.adapters import Capability, FakeAppApi
from sectum_ai.cli.app import _skip_inapplicable
from sectum_ai.config import ADAPTER_FAMILIES, AdapterConfig, SectumConfig, build_adapters
from sectum_ai.probes import (
    EmbeddingInversionProbe,
    MultimodalRagBleedProbe,
    TenantBoundaryProbe,
)
from sectum_ai.spec import ConfigError, Surface


def _config(**adapters: AdapterConfig) -> SectumConfig:
    return SectumConfig(adapters=adapters)


def test_app_is_a_configurable_family() -> None:
    assert "app" in ADAPTER_FAMILIES
    bundle = build_adapters(_config(app=AdapterConfig(kind="fake")))
    assert isinstance(bundle.vector, FakeAppApi)


def test_it_declares_the_api_surface_not_the_slot_it_fills() -> None:
    # The whole point: it occupies the vector slot but speaks for `api`, so its
    # findings and the run's provenance agree about what was probed.
    bundle = build_adapters(_config(app=AdapterConfig(kind="fake")))
    assert bundle.vector.surface is Surface.API


def test_it_declares_no_semantic_retrieval() -> None:
    # An application's search is not an embedding space. Without this, a substring
    # hit would be recorded as AML.T0024.001 "Invert ML Model".
    bundle = build_adapters(_config(app=AdapterConfig(kind="fake")))
    assert not bundle.vector.supports(Capability.SEMANTIC_RETRIEVAL)


def test_the_vector_slot_probes_still_run_against_it() -> None:
    bundle = build_adapters(_config(app=AdapterConfig(kind="fake")))
    runnable, skipped = _skip_inapplicable((TenantBoundaryProbe(None),), bundle)
    assert [p.id for p in runnable] == ["tenant-boundary-fetch"]
    assert skipped == []


@pytest.mark.parametrize("probe", [EmbeddingInversionProbe, MultimodalRagBleedProbe])
def test_the_embedding_space_classes_are_skipped(probe: Any) -> None:
    bundle = build_adapters(_config(app=AdapterConfig(kind="fake")))
    runnable, skipped = _skip_inapplicable((probe(None),), bundle)
    assert runnable == ()
    assert [reason for _, reason in skipped] == [Capability.SEMANTIC_RETRIEVAL.value]


def test_configuring_both_app_and_vector_store_is_refused() -> None:
    # Both fill the same slot, so a run carrying both cannot say which system it
    # probed. Resolving silently would be the config-level version of the
    # over-claim this whole area exists to prevent.
    with pytest.raises(ConfigError, match="not both"):
        build_adapters(
            _config(app=AdapterConfig(kind="fake"), vector_store=AdapterConfig(kind="fake"))
        )


def test_an_unimplemented_app_kind_says_so_rather_than_falling_back() -> None:
    with pytest.raises(ConfigError, match="not implemented yet"):
        build_adapters(_config(app=AdapterConfig(kind="http", base_url="https://x")))


def test_the_leak_knob_models_an_api_that_does_not_filter_by_tenant() -> None:
    leaky = build_adapters(_config(app=AdapterConfig(kind="fake", shared_index=True)))
    assert leaky.vector.supports(Capability.SHARED_INDEX)
    isolated = build_adapters(_config(app=AdapterConfig(kind="fake")))
    assert isolated.vector.supports(Capability.PER_TENANT_NAMESPACE)
