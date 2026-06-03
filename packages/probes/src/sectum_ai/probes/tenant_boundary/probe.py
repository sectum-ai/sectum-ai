"""Class 1 - direct tenant boundary fetch (the engineering spec, section 7).

From one tenant's session, attempt to fetch another tenant's documents directly
by id (a BOLA-style probe) and detect any cross-tenant canary leak. This is the
table-stakes probe: it verifies negative authorization across the tenant
boundary.
"""

from sectum_ai.probes.detection import DetectingProbe, is_cross_principal
from sectum_ai.spec import (
    AccessOutcome,
    Finding,
    FindingStatus,
    MarkerType,
    Observation,
    ProbeStep,
    Severity,
    Substrate,
    Surface,
)


class TenantBoundaryProbe(DetectingProbe):
    """Class 1: fetch each principal's hard-canary documents from other principals."""

    id = "tenant-boundary-fetch"
    name = "Direct tenant boundary fetch"
    owasp_llm = "LLM08:2025"
    atlas_techniques: tuple[str, ...] = ("AML.T0024",)
    nist_rmf: tuple[str, ...] = ("MEASURE 2.7",)
    surfaces: tuple[Surface, ...] = (Surface.VECTOR_DB,)
    requires_adapters: tuple[str, ...] = ("vector",)

    def plan(self, substrate: Substrate) -> list[ProbeStep]:
        """Plan, for every hard-canary document, a direct fetch from each foreign principal.

        A fetch is issued from every principal (a tenant, or a user within a
        tenant - ADR-0006) to which the marker is foreign, so the probe verifies
        negative authorization at both granularities. With no users declared the
        principals are the tenants and this is the original per-tenant plan.
        """
        principals = substrate.principals()
        steps: list[ProbeStep] = []
        for marker in substrate.manifest.markers:
            if marker.marker_type is not MarkerType.HARD_CANARY:
                continue
            for location in marker.planted_locations:
                for observer in principals:
                    if not is_cross_principal(marker, observer):
                        continue
                    steps.append(
                        ProbeStep(
                            step_id=f"{self.id}-{len(steps):04d}",
                            probe_id=self.id,
                            actor_tenant_id=observer.tenant_id,
                            actor_user_id=observer.user_id,
                            action="vector.fetch",
                            payload={"doc_id": location.doc_id},
                        )
                    )
        return steps

    def detect(
        self, step: ProbeStep, observation: Observation, substrate: Substrate
    ) -> list[Finding]:
        """Scan the observation for a foreign-principal canary, and flag deny ambiguity.

        A returned object carrying a foreign canary is a confirmed leak. But the
        spec's Class 1 also calls out the *200-empty vs 403* ambiguity: a fetch
        that comes back empty is not a proven deny - the backend may have silently
        swallowed the request. When nothing leaked and the boundary returned
        ``EMPTY`` rather than an explicit ``DENIED``, emit an UNVERIFIED
        informational finding so a silent 200-empty cannot pass for enforced
        negative authorization.
        """
        pipeline = self._providers.pipeline(substrate)
        findings = pipeline.detect(
            step.actor_tenant_id,
            observation.raw_response,
            observation.surface,
            probe_id=self.id,
            observed_user=step.actor_user_id,
            owasp_llm=self.owasp_llm,
            atlas=self.atlas_techniques,
            nist=self.nist_rmf,
            owasp_secondary=self.owasp_secondary,
        )
        if not findings and observation.access_outcome is AccessOutcome.EMPTY:
            ambiguity = self._empty_ambiguity_finding(step, observation, substrate)
            if ambiguity is not None:
                findings.append(ambiguity)
        return findings

    def _empty_ambiguity_finding(
        self, step: ProbeStep, observation: Observation, substrate: Substrate
    ) -> Finding | None:
        """Build the UNVERIFIED 200-empty ambiguity finding for a cross-principal fetch."""
        observer = next(
            (
                principal
                for principal in substrate.principals()
                if principal.tenant_id == step.actor_tenant_id
                and principal.user_id == step.actor_user_id
            ),
            None,
        )
        if observer is None:
            return None
        doc_id = step.payload.get("doc_id")
        marker = next(
            (
                candidate
                for candidate in substrate.manifest.markers
                for location in candidate.planted_locations
                if location.doc_id == doc_id and is_cross_principal(candidate, observer)
            ),
            None,
        )
        if marker is None:
            return None
        user_suffix = f"-{observer.user_id.hex}" if observer.user_id is not None else ""
        return Finding(
            finding_id=(
                f"finding-{self.id}-empty-{marker.marker_id}-"
                f"{observer.tenant_id.hex}{user_suffix}-{observation.surface.value}"
            ),
            probe_id=self.id,
            severity=Severity.INFO,
            confidence=0.0,
            status=FindingStatus.UNVERIFIED,
            owner_tenant_id=marker.owner_tenant_id,
            observed_in_tenant_id=observer.tenant_id,
            owner_user_id=marker.owner_user_id,
            observed_in_user_id=observer.user_id,
            surface=observation.surface,
            marker_id=marker.marker_id,
            evidence_span=(
                "cross-principal fetch returned 200-empty, not an explicit deny - "
                "negative authorization is unproven (the 200-empty vs 403 ambiguity)"
            ),
            owasp_llm=self.owasp_llm,
            owasp_secondary=self.owasp_secondary,
            atlas=self.atlas_techniques,
            nist=self.nist_rmf,
            remediation_pointer=(
                "return an explicit authorization error (e.g. 403) for cross-tenant "
                "object fetches rather than a 200 with an empty body"
            ),
        )
