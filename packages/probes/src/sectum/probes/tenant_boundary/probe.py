"""Class 1 - direct tenant boundary fetch (the engineering spec, section 7).

From one tenant's session, attempt to fetch another tenant's documents directly
by id (a BOLA-style probe) and detect any cross-tenant canary leak. This is the
table-stakes probe: it verifies negative authorization across the tenant
boundary.
"""

from sectum.probes.detection import DetectionPipeline
from sectum.spec import Finding, MarkerType, Observation, ProbeStep, Substrate, Surface


class TenantBoundaryProbe:
    """Class 1: query each tenant's hard-canary documents from other tenants."""

    id = "tenant-boundary-fetch"
    name = "Direct tenant boundary fetch"
    owasp_llm = "LLM08:2025"
    atlas_techniques: tuple[str, ...] = ()
    nist_rmf: tuple[str, ...] = ()
    surfaces: tuple[Surface, ...] = (Surface.VECTOR_DB,)
    requires_adapters: tuple[str, ...] = ()

    def plan(self, substrate: Substrate) -> list[ProbeStep]:
        """Plan, for every hard-canary document, a direct fetch from each other tenant."""
        tenant_ids = [tenant.tenant_id for tenant in substrate.tenants]
        steps: list[ProbeStep] = []
        for marker in substrate.manifest.markers:
            if marker.marker_type is not MarkerType.HARD_CANARY:
                continue
            for location in marker.planted_locations:
                for observer in tenant_ids:
                    if observer == marker.owner_tenant_id:
                        continue
                    steps.append(
                        ProbeStep(
                            step_id=f"{self.id}-{len(steps):04d}",
                            probe_id=self.id,
                            actor_tenant_id=observer,
                            action="vector.fetch",
                            payload={"doc_id": location.doc_id},
                        )
                    )
        return steps

    def detect(
        self, step: ProbeStep, observation: Observation, substrate: Substrate
    ) -> list[Finding]:
        """Scan the observation for a foreign canary via the detection pipeline."""
        pipeline = DetectionPipeline(substrate)
        return pipeline.detect(
            step.actor_tenant_id,
            observation.raw_response,
            observation.surface,
            probe_id=self.id,
        )
