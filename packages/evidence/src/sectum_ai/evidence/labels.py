"""What a finding is, in one phrase, for the derived SARIF and OSCAL projections.

Every finding used to render as a "cross-tenant leak": an erasure residual
(owner and observer are the same tenant), a cross-user leak inside one tenant,
and the informational 200-empty ambiguity candidate all read as a confirmed
cross-tenant breach in a Security tab or a GRC platform.
"""

from __future__ import annotations

from sectum_ai.spec import Finding, FindingStatus, RunResult, Surface

# A finding's surface is where the leak showed; provenance is keyed by the
# adapter that was driven. They coincide except for the KV-cache timing probe,
# whose findings name the cache while the model adapter is what ran - so every
# live-surface gate dropped its findings and OSCAL rendered `satisfied` over
# twelve confirmed side channels on the only live surface.
_BACKING_SURFACE: dict[str, str] = {Surface.KV_CACHE.value: Surface.MODEL_ADAPTER.value}


def backing_surface(finding: Finding) -> str:
    """The provenance key (adapter surface) a finding's verdict rests on."""
    return _BACKING_SURFACE.get(finding.surface.value, finding.surface.value)


def unaccounted_surfaces(run: RunResult) -> tuple[str, ...]:
    """Surfaces this run's findings rest on that its provenance block never recorded.

    Three renderers - the audit PDF, `verify`'s run-scope gate and the scorecard's
    scope line - answered "was this run live?" from the provenance block alone,
    and the block is a record of the surfaces the run ACCOUNTED for, not of the
    surfaces its findings name. A record whose block lists seven live surfaces and
    whose findings also rest on an eighth rendered "every surface exercised by this
    run was a live, configured backend ... These findings describe those systems",
    passed `verify --require-live`, and printed "scope: your configured stack
    (every surface live)" - directly above class lines reading "none of which this
    run's provenance records". The headline is what a reader carries away.

    Empty for a run recording no provenance at all: that case has its own branch at
    every site ("predates the block"), and listing surfaces there would answer a
    question those branches exist to refuse.
    """
    if not run.surface_provenance:
        return ()
    named = {backing_surface(finding) for finding in run.findings}
    return tuple(sorted(named - set(run.surface_provenance)))


def is_cross_principal(finding: Finding) -> bool:
    """Whether ``finding`` crosses a tenant or user boundary (rather than being residue).

    The predicate behind `leak_label`'s first two branches, so a caller asking the
    QUESTION does not have to compare the ANSWER's prose: `oscal` decided whether
    to flip every isolation control with `leak_label(f) != "residual-data
    finding"`, which a change to that string would have silently inverted.
    """
    if finding.owner_tenant_id != finding.observed_in_tenant_id:
        return True
    return (
        finding.owner_user_id is not None
        and finding.observed_in_user_id is not None
        and finding.owner_user_id != finding.observed_in_user_id
    )


def leak_label(finding: Finding) -> str:
    """``cross-tenant leak``, ``cross-user candidate``, ``residual-data finding``, ..."""
    confirmed = finding.status is FindingStatus.CONFIRMED
    if not is_cross_principal(finding):
        # Confirmed means the marker WAS retrievable after the erasure; unverified
        # means the scan could not rule it out. Both read "residual-data finding"
        # in the SARIF message an operator sees in a Security tab and in OSCAL's
        # observation text - "data remains" stated over a surface whose absence
        # was merely unestablished, which is the erasure caveat's whole point.
        return "residual-data finding" if confirmed else "residual-data candidate"
    scope = (
        "cross-tenant" if finding.owner_tenant_id != finding.observed_in_tenant_id else "cross-user"
    )
    kind = "leak" if confirmed else "candidate"
    return f"{scope} {kind}"
