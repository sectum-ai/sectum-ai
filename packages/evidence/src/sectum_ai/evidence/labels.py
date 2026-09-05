"""What a finding is, in one phrase, for the derived SARIF and OSCAL projections.

Every finding used to render as a "cross-tenant leak": an erasure residual
(owner and observer are the same tenant), a cross-user leak inside one tenant,
and the informational 200-empty ambiguity candidate all read as a confirmed
cross-tenant breach in a Security tab or a GRC platform.
"""

from __future__ import annotations

from sectum_ai.spec import Finding, FindingStatus


def leak_label(finding: Finding) -> str:
    """``cross-tenant leak``, ``cross-user candidate``, ``residual-data finding``, ..."""
    if finding.owner_tenant_id != finding.observed_in_tenant_id:
        scope = "cross-tenant"
    elif (
        finding.owner_user_id is not None
        and finding.observed_in_user_id is not None
        and finding.owner_user_id != finding.observed_in_user_id
    ):
        scope = "cross-user"
    else:
        return "residual-data finding"
    kind = "leak" if finding.status is FindingStatus.CONFIRMED else "candidate"
    return f"{scope} {kind}"
