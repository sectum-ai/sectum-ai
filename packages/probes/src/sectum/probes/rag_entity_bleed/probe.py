"""Class 2 - organic entity-bleed RAG (the engineering spec, section 7).

The flagship probe. It reproduces the Retrieval Pivot result: benign,
non-adversarial queries seeded on organic entities that tenants share - a
person, a vendor, compliance terms, amounts, dates - surface another tenant's
content. No prompt injection is used.
"""

from sectum.probes.detection import DetectingProbe
from sectum.spec import Finding, Observation, ProbeStep, Substrate, Surface


class RagEntityBleedProbe(DetectingProbe):
    """Class 2: benign shared-entity queries that pivot across the tenant boundary."""

    id = "rag-entity-bleed"
    name = "Organic entity-bleed RAG"
    owasp_llm = "LLM08:2025"
    atlas_techniques: tuple[str, ...] = ()
    nist_rmf: tuple[str, ...] = ()
    surfaces: tuple[Surface, ...] = (Surface.VECTOR_DB,)
    requires_adapters: tuple[str, ...] = ()

    def plan(self, substrate: Substrate) -> list[ProbeStep]:
        """Plan one benign shared-entity query, issued from every tenant."""
        tenant_ids = [tenant.tenant_id for tenant in substrate.tenants]
        steps: list[ProbeStep] = []
        for entity in substrate.scenario.shared_entities:
            for observer in tenant_ids:
                steps.append(
                    ProbeStep(
                        step_id=f"{self.id}-{len(steps):04d}",
                        probe_id=self.id,
                        actor_tenant_id=observer,
                        action="vector.query",
                        payload={"query": f"records mentioning {entity.value}", "k": "10"},
                    )
                )
        return steps

    def detect(
        self, step: ProbeStep, observation: Observation, substrate: Substrate
    ) -> list[Finding]:
        """Scan the observation for any foreign canary via the detection pipeline."""
        pipeline = self._providers.pipeline(substrate)
        return pipeline.detect(
            step.actor_tenant_id,
            observation.raw_response,
            observation.surface,
            probe_id=self.id,
        )
