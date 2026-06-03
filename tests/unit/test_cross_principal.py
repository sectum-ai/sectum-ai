"""Tests for ``is_cross_principal`` — the ADR-0006 cross-principal predicate.

Probe planning and the detection pipeline both consume this predicate: planning
uses it to decide *which* principals issue each step, and detection uses it to
decide *which* foreign markers a given observation might leak. The unit suite
exercises the cross-tenant path generously; this file pins the user-scoped path
the ADR specifies (default-deny on a cross-user appearance within one tenant)
plus the corners where one or both sides drop their user id.
"""

from uuid import UUID

from sectum_ai.probes.detection import is_cross_principal
from sectum_ai.spec import Marker, MarkerType, Principal

_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)
_USER_1 = UUID(int=1)
_USER_2 = UUID(int=2)


def _marker(
    *, owner_tenant: UUID, owner_user: UUID | None = None, marker_id: str = "m-1"
) -> Marker:
    """Build a minimal Marker for the predicate; the actual canary type is irrelevant here."""
    return Marker(
        marker_id=marker_id,
        marker_type=MarkerType.HARD_CANARY,
        owner_tenant_id=owner_tenant,
        owner_user_id=owner_user,
        plaintext="canary",
    )


# ---------------------------------------------------------------------------
# Cross-tenant: always crossed (the dominant signal — overrides any user check)
# ---------------------------------------------------------------------------


def test_cross_tenant_marker_is_crossed_for_a_tenant_level_observer() -> None:
    marker = _marker(owner_tenant=_TENANT_A)
    observer = Principal(tenant_id=_TENANT_B)
    assert is_cross_principal(marker, observer) is True


def test_cross_tenant_marker_is_crossed_for_a_user_scoped_observer_even_with_matching_user_id() -> (
    None
):
    # A naive implementation might short-circuit on `marker.owner_user_id == observer.user_id`
    # without first checking the tenant; the spec says tenant takes precedence.
    marker = _marker(owner_tenant=_TENANT_A, owner_user=_USER_1)
    observer = Principal(tenant_id=_TENANT_B, user_id=_USER_1)
    assert is_cross_principal(marker, observer) is True


# ---------------------------------------------------------------------------
# Same tenant: user-scoped default-deny semantics
# ---------------------------------------------------------------------------


def test_same_tenant_tenant_level_marker_and_observer_is_not_crossed() -> None:
    marker = _marker(owner_tenant=_TENANT_A)
    observer = Principal(tenant_id=_TENANT_A)
    assert is_cross_principal(marker, observer) is False


def test_same_tenant_user_observer_and_tenant_level_marker_is_not_crossed() -> None:
    # A tenant-level marker (no owner_user_id) belongs to every user of that
    # tenant per ADR-0006; a user-scoped observer reading it is not a leak.
    marker = _marker(owner_tenant=_TENANT_A)
    observer = Principal(tenant_id=_TENANT_A, user_id=_USER_1)
    assert is_cross_principal(marker, observer) is False


def test_same_tenant_tenant_level_observer_and_user_marker_is_not_crossed() -> None:
    # Symmetric to the above: a tenant-level observer (no user_id) is the
    # tenant itself; it may read any user-owned marker inside its tenant.
    marker = _marker(owner_tenant=_TENANT_A, owner_user=_USER_1)
    observer = Principal(tenant_id=_TENANT_A)
    assert is_cross_principal(marker, observer) is False


def test_same_tenant_same_user_is_not_crossed() -> None:
    marker = _marker(owner_tenant=_TENANT_A, owner_user=_USER_1)
    observer = Principal(tenant_id=_TENANT_A, user_id=_USER_1)
    assert is_cross_principal(marker, observer) is False


def test_same_tenant_different_user_is_crossed_default_deny() -> None:
    # The ADR-0006 default-deny rule: any cross-user appearance is a leak,
    # since the intended-sharing policy model is deferred.
    marker = _marker(owner_tenant=_TENANT_A, owner_user=_USER_1)
    observer = Principal(tenant_id=_TENANT_A, user_id=_USER_2)
    assert is_cross_principal(marker, observer) is True
