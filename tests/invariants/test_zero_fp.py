"""Invariant: no manifest marker implies no confirmed finding.

The zero-false-positive control (the engineering spec, section 6.4): a confirmed finding is
only ever produced for a genuine cross-tenant observation of a manifest marker.
"""

from sectum_ai.probes import DetectionPipeline, confirmed_findings
from sectum_ai.spec import Substrate, Surface
from sectum_ai.substrate import build_substrate, default_scenario

_BENIGN = (
    "The weekly operations review covered staffing levels, gardening rosters, "
    "and weather contingencies for the regional distribution centres."
)


def _substrate() -> Substrate:
    return build_substrate(default_scenario(seed=314))


def test_benign_text_produces_no_confirmed_findings() -> None:
    substrate = _substrate()
    pipeline = DetectionPipeline(substrate)
    for tenant in substrate.tenants:
        findings = pipeline.detect(tenant.tenant_id, _BENIGN, Surface.API)
        assert confirmed_findings(findings) == []


def test_a_marker_in_its_own_tenant_session_is_not_a_leak() -> None:
    substrate = _substrate()
    pipeline = DetectionPipeline(substrate)
    for marker in substrate.manifest.markers:
        text = f"internal tenant context referencing {marker.plaintext} as expected"
        findings = pipeline.detect(marker.owner_tenant_id, text, Surface.VECTOR_DB)
        assert confirmed_findings(findings) == []


def test_every_confirmed_finding_traces_to_a_manifest_marker() -> None:
    substrate = _substrate()
    pipeline = DetectionPipeline(substrate)
    manifest_ids = {marker.marker_id for marker in substrate.manifest.markers}
    observer = substrate.tenants[1].tenant_id
    for marker in substrate.manifest.markers:
        if marker.owner_tenant_id == observer:
            continue
        findings = pipeline.detect(observer, f"surfaced: {marker.plaintext}", Surface.API)
        for finding in confirmed_findings(findings):
            assert finding.marker_id in manifest_ids
