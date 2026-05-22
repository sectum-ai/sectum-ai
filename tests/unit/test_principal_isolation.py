"""User-level (principal) isolation detection (ADR-0006).

The detection pipeline generalizes from tenant-vs-tenant to the principal
boundary: within a tenant, a marker owned by user A surfacing in user B's
session is a leak, under a default-deny user policy. Cross-tenant behavior and
the tenant-level case are unchanged.
"""

from uuid import UUID

from sectum.probes import (
    DetectionPipeline,
    RagEntityBleedProbe,
    TenantBoundaryProbe,
    is_cross_principal,
)
from sectum.spec import (
    FindingStatus,
    Marker,
    MarkerType,
    Principal,
    Scenario,
    SharedEntity,
    Surface,
    SyntheticTenantSpec,
    SyntheticUserSpec,
)
from sectum.substrate import build_substrate, default_scenario

_TENANT = UUID(int=1)
_OTHER_TENANT = UUID(int=2)
_USER_A = UUID(int=0xA)
_USER_B = UUID(int=0xB)


def _pipeline_with_user_markers() -> DetectionPipeline:
    markers = (
        Marker(
            marker_id="m-a",
            marker_type=MarkerType.HARD_CANARY,
            owner_tenant_id=_TENANT,
            owner_user_id=_USER_A,
            plaintext="SECTUM-CANARY-AAA",
        ),
        Marker(
            marker_id="m-b",
            marker_type=MarkerType.HARD_CANARY,
            owner_tenant_id=_TENANT,
            owner_user_id=_USER_B,
            plaintext="SECTUM-CANARY-BBB",
        ),
        Marker(
            marker_id="m-tenant",
            marker_type=MarkerType.HARD_CANARY,
            owner_tenant_id=_TENANT,
            owner_user_id=None,
            plaintext="SECTUM-CANARY-TTT",
        ),
    )
    base = build_substrate(default_scenario(seed=1))
    manifest = base.manifest.model_copy(update={"markers": markers})
    substrate = base.model_copy(update={"manifest": manifest})
    return DetectionPipeline(substrate)


def test_a_users_marker_surfacing_in_another_users_session_is_a_leak() -> None:
    pipeline = _pipeline_with_user_markers()
    findings = pipeline.detect(
        _TENANT, "result mentions SECTUM-CANARY-BBB", Surface.VECTOR_DB, observed_user=_USER_A
    )
    assert len(findings) == 1
    assert findings[0].marker_id == "m-b"
    assert findings[0].owner_user_id == _USER_B
    assert findings[0].observed_in_user_id == _USER_A


def test_a_users_own_marker_is_not_a_leak() -> None:
    pipeline = _pipeline_with_user_markers()
    findings = pipeline.detect(
        _TENANT, "result mentions SECTUM-CANARY-AAA", Surface.VECTOR_DB, observed_user=_USER_A
    )
    assert findings == []


def test_a_tenant_level_marker_is_not_a_leak_to_a_user_of_that_tenant() -> None:
    pipeline = _pipeline_with_user_markers()
    findings = pipeline.detect(
        _TENANT, "result mentions SECTUM-CANARY-TTT", Surface.VECTOR_DB, observed_user=_USER_A
    )
    assert findings == []


def test_a_tenant_level_observer_does_not_flag_its_own_users_markers() -> None:
    # Without a user scope, the observer is the whole tenant - it owns all its
    # users' data, so a user-owned marker is not foreign (tenant-level behavior).
    pipeline = _pipeline_with_user_markers()
    findings = pipeline.detect(_TENANT, "result mentions SECTUM-CANARY-BBB", Surface.VECTOR_DB)
    assert findings == []


def test_cross_tenant_is_still_a_leak_regardless_of_user() -> None:
    pipeline = _pipeline_with_user_markers()
    findings = pipeline.detect(
        _OTHER_TENANT, "result mentions SECTUM-CANARY-AAA", Surface.VECTOR_DB, observed_user=_USER_A
    )
    assert len(findings) == 1
    assert findings[0].marker_id == "m-a"


def test_a_user_level_and_tenant_level_finding_have_distinct_ids() -> None:
    pipeline = _pipeline_with_user_markers()
    user_finding = pipeline.detect(
        _OTHER_TENANT, "SECTUM-CANARY-AAA", Surface.VECTOR_DB, observed_user=_USER_B
    )[0]
    tenant_finding = pipeline.detect(_OTHER_TENANT, "SECTUM-CANARY-AAA", Surface.VECTOR_DB)[0]
    assert user_finding.finding_id != tenant_finding.finding_id


def test_two_users_observing_one_marker_yield_distinct_finding_ids() -> None:
    # Low-valued UUIDs share leading hex digits; the finding id must still
    # distinguish two users of one tenant, or dedupe_findings would merge two
    # genuinely distinct user-level leaks and undercount.
    pipeline = _pipeline_with_user_markers()
    text = "result mentions SECTUM-CANARY-BBB"  # owned by user B
    seen_by_a = pipeline.detect(_TENANT, text, Surface.VECTOR_DB, observed_user=_USER_A)
    seen_by_c = pipeline.detect(_TENANT, text, Surface.VECTOR_DB, observed_user=UUID(int=0xC))
    assert len(seen_by_a) == 1
    assert len(seen_by_c) == 1
    assert seen_by_a[0].finding_id != seen_by_c[0].finding_id


def test_a_user_level_entity_canary_is_detected_semantically() -> None:
    entity = Marker(
        marker_id="e-b",
        marker_type=MarkerType.ENTITY_CANARY,
        owner_tenant_id=_TENANT,
        owner_user_id=_USER_B,
        plaintext="Project Wintergreen Alpha",
    )
    base = build_substrate(default_scenario(seed=1))
    manifest = base.manifest.model_copy(update={"markers": (entity,)})
    pipeline = DetectionPipeline(base.model_copy(update={"manifest": manifest}))
    text = "the report references Project Wintergreen Alpha in detail"
    seen_by_a = pipeline.detect(_TENANT, text, Surface.VECTOR_DB, observed_user=_USER_A)
    assert any(f.marker_id == "e-b" and f.status is FindingStatus.CONFIRMED for f in seen_by_a)
    # the owning user sees nothing foreign
    assert pipeline.detect(_TENANT, text, Surface.VECTOR_DB, observed_user=_USER_B) == []


def _users_scenario() -> Scenario:
    return Scenario(
        scenario_id="users",
        seed=7,
        tenants=(
            SyntheticTenantSpec(
                tenant_id=_TENANT,
                display_name="Acme",
                industry="robotics",
                corpus_size=24,
                users=(
                    SyntheticUserSpec(user_id=_USER_A, display_name="Alice"),
                    SyntheticUserSpec(user_id=_USER_B, display_name="Bob"),
                ),
            ),
        ),
        shared_entities=(SharedEntity(kind="person", value="Maria Chen"),),
    )


def test_the_flagship_probe_plans_per_user_when_users_are_declared() -> None:
    substrate = build_substrate(_users_scenario())
    steps = RagEntityBleedProbe().plan(substrate)
    actor_users = {step.actor_user_id for step in steps}
    # one tenant-level principal plus the two users
    assert actor_users == {None, _USER_A, _USER_B}


def test_the_flagship_probe_is_tenant_level_without_users() -> None:
    substrate = build_substrate(default_scenario(seed=1))
    steps = RagEntityBleedProbe().plan(substrate)
    assert all(step.actor_user_id is None for step in steps)


def test_tenant_boundary_plans_a_cross_user_fetch_when_users_are_declared() -> None:
    # One tenant with two users: each user's hard-canary doc is fetched from the
    # other user's session (cross-user), and never from the owning user nor from
    # the tenant-level principal, which owns all its users' data (ADR-0006).
    substrate = build_substrate(_users_scenario())
    steps = TenantBoundaryProbe().plan(substrate)
    owner_of_doc = {
        location.doc_id: marker.owner_user_id
        for marker in substrate.manifest.markers
        if marker.marker_type is MarkerType.HARD_CANARY
        for location in marker.planted_locations
    }
    assert steps  # the scenario does plant cross-user fetches
    # every fetch is issued from a user (never the tenant-level principal) and
    # never from the doc's owning user - it is always cross-user
    for step in steps:
        assert step.actor_user_id is not None
        assert step.actor_user_id != owner_of_doc[step.payload["doc_id"]]
    # both users appear as actors; the tenant-level principal issues none
    assert {step.actor_user_id for step in steps} == {_USER_A, _USER_B}


def test_tenant_boundary_is_tenant_level_without_users() -> None:
    substrate = build_substrate(default_scenario(seed=1))
    steps = TenantBoundaryProbe().plan(substrate)
    # no user scope anywhere, and every tenant fetches every other tenant's docs
    assert {step.actor_user_id for step in steps} == {None}
    assert {step.actor_tenant_id for step in steps} == {t.tenant_id for t in substrate.tenants}


def test_is_cross_principal_predicate() -> None:
    marker = Marker(
        marker_id="m",
        marker_type=MarkerType.HARD_CANARY,
        owner_tenant_id=_TENANT,
        owner_user_id=_USER_A,
        plaintext="x",
    )
    # cross-user within the tenant, and cross-tenant, are foreign
    assert is_cross_principal(marker, Principal(tenant_id=_TENANT, user_id=_USER_B))
    assert is_cross_principal(marker, Principal(tenant_id=_OTHER_TENANT, user_id=_USER_A))
    # the owning user and the owning tenant (no user scope) are not foreign
    assert not is_cross_principal(marker, Principal(tenant_id=_TENANT, user_id=_USER_A))
    assert not is_cross_principal(marker, Principal(tenant_id=_TENANT))
