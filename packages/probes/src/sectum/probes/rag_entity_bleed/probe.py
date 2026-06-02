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
    atlas_techniques: tuple[str, ...] = ("AML.T0024", "AML.T0057")
    nist_rmf: tuple[str, ...] = ("MEASURE 2.7",)
    surfaces: tuple[Surface, ...] = (Surface.VECTOR_DB,)
    requires_adapters: tuple[str, ...] = ("vector",)

    def plan(self, substrate: Substrate) -> list[ProbeStep]:
        """Plan one benign shared-entity query, issued from every principal.

        Issuing from each principal (a tenant, or a user within a tenant -
        ADR-0006) verifies isolation at both granularities: against a store that
        is not user-scoped, a user's benign query surfaces another user's data in
        the same tenant. With no users declared this reduces to one query per
        tenant, exactly as before.
        """
        steps: list[ProbeStep] = []
        for entity in substrate.scenario.shared_entities:
            for observer in substrate.principals():
                steps.append(
                    ProbeStep(
                        step_id=f"{self.id}-{len(steps):04d}",
                        probe_id=self.id,
                        actor_tenant_id=observer.tenant_id,
                        actor_user_id=observer.user_id,
                        action="vector.query",
                        payload={"query": f"records mentioning {entity.value}", "k": "10"},
                    )
                )
        return steps

    def detect(
        self, step: ProbeStep, observation: Observation, substrate: Substrate
    ) -> list[Finding]:
        """Scan the observation for any foreign-principal canary via the pipeline."""
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
        )
