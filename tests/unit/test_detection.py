"""Unit tests for the exact/semantic/judge detection pipeline."""

from sectum.probes import DetectionPipeline, confirmed_findings, dedupe_findings
from sectum.spec import Marker, MarkerType, Severity, Substrate, Surface
from sectum.substrate import build_substrate, default_scenario


def _substrate() -> Substrate:
    return build_substrate(default_scenario(seed=55))


def _foreign_hard_marker(substrate: Substrate) -> Marker:
    """A hard canary owned by the first tenant (foreign to every other tenant)."""
    owner = substrate.tenants[0].tenant_id
    return next(
        marker
        for marker in substrate.manifest.markers
        if marker.owner_tenant_id == owner and marker.marker_type is MarkerType.HARD_CANARY
    )


def test_foreign_hard_canary_is_a_confirmed_critical_leak() -> None:
    substrate = _substrate()
    pipeline = DetectionPipeline(substrate)
    owner = substrate.tenants[0].tenant_id
    observer = substrate.tenants[1].tenant_id
    hard = next(
        marker
        for marker in substrate.manifest.markers
        if marker.owner_tenant_id == owner and marker.marker_type is MarkerType.HARD_CANARY
    )
    findings = confirmed_findings(
        pipeline.detect(observer, f"retrieved chunk: {hard.plaintext}", Surface.VECTOR_DB)
    )
    assert len(findings) == 1
    assert findings[0].marker_id == hard.marker_id
    assert findings[0].severity is Severity.CRITICAL
    assert findings[0].confidence == 1.0
    assert findings[0].owner_tenant_id == owner
    assert findings[0].observed_in_tenant_id == observer


def test_foreign_entity_canary_is_detected_inside_a_long_observation() -> None:
    substrate = _substrate()
    pipeline = DetectionPipeline(substrate)
    owner = substrate.tenants[2].tenant_id
    observer = substrate.tenants[3].tenant_id
    entity = next(
        marker
        for marker in substrate.manifest.markers
        if marker.owner_tenant_id == owner and marker.marker_type is MarkerType.ENTITY_CANARY
    )
    padded = "routine context line. " * 60 + entity.plaintext + " followed by trailing notes."
    findings = confirmed_findings(pipeline.detect(observer, padded, Surface.RAG_PIPELINE))
    assert [finding.marker_id for finding in findings] == [entity.marker_id]
    assert findings[0].severity is Severity.HIGH


def test_each_tenant_owns_six_markers_two_of_each_type() -> None:
    substrate = _substrate()
    for tenant in substrate.tenants:
        owned = [
            marker
            for marker in substrate.manifest.markers
            if marker.owner_tenant_id == tenant.tenant_id
        ]
        assert len(owned) == 6
        for marker_type in MarkerType:
            assert sum(1 for marker in owned if marker.marker_type is marker_type) == 2


def test_dedupe_collapses_repeated_detections_within_a_probe() -> None:
    substrate = _substrate()
    pipeline = DetectionPipeline(substrate)
    observer = substrate.tenants[1].tenant_id
    text = f"retrieved chunk: {_foreign_hard_marker(substrate).plaintext}"
    twice = [
        *pipeline.detect(observer, text, Surface.MCP, probe_id="agent-tool-hijack"),
        *pipeline.detect(observer, text, Surface.MCP, probe_id="agent-tool-hijack"),
    ]
    assert len(twice) == 2
    assert len(dedupe_findings(twice)) == 1


def test_dedupe_keeps_the_same_leak_found_by_different_probes() -> None:
    substrate = _substrate()
    pipeline = DetectionPipeline(substrate)
    observer = substrate.tenants[1].tenant_id
    text = f"retrieved chunk: {_foreign_hard_marker(substrate).plaintext}"
    across = [
        *pipeline.detect(observer, text, Surface.VECTOR_DB, probe_id="tenant-boundary-fetch"),
        *pipeline.detect(observer, text, Surface.MODEL_ADAPTER, probe_id="lora-cross-tenant"),
    ]
    assert len(dedupe_findings(across)) == 2
