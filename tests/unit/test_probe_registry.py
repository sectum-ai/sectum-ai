"""Tests for the probe registry (the engineering spec, section 7)."""

import pytest
from sectum_ai.probes import ProbeRegistry, RagEntityBleedProbe, TenantBoundaryProbe


def test_probe_registry_registers_lists_and_rejects_duplicates() -> None:
    registry = ProbeRegistry()
    boundary = TenantBoundaryProbe()
    bleed = RagEntityBleedProbe()
    registry.register(boundary)
    registry.register(bleed)
    assert registry.get(boundary.id) is boundary
    assert [probe.id for probe in registry.all()] == sorted([boundary.id, bleed.id])
    with pytest.raises(ValueError, match="already registered"):
        registry.register(TenantBoundaryProbe())
