"""Class 1 - direct tenant boundary fetch (the engineering spec, section 7).

From one tenant's session, attempt to fetch another tenant's documents directly
by id (a BOLA-style probe) and detect any cross-tenant canary leak. This is the
table-stakes probe: it verifies negative authorization across the tenant
boundary.
"""

from sectum_ai.probes.detection import DetectingProbe, is_cross_principal
from sectum_ai.spec import Finding, MarkerType, Observation, ProbeStep, Substrate, Surface


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
        """Scan the observation for a foreign-principal canary via the pipeline."""
        pipeline = self._providers.pipeline(substrate)
        return pipeline.detect(
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
