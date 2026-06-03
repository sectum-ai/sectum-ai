"""Class 2 expansion - entity-bleed at the RAG-pipeline end (spec §7).

Where :class:`~sectum_ai.probes.rag_entity_bleed.RagEntityBleedProbe` issues
benign shared-entity queries through the *vector* adapter (Surface.VECTOR_DB),
this probe issues the same queries through the *RAG pipeline* adapter
(Surface.RAG_PIPELINE). The customer-facing surface in production is
usually the RAG endpoint - not the underlying vector store - so a
shared-index retriever inside a tenant-aware-looking pipeline is the
exact leak this variant catches against the customer's actual contract.

The same benign-query plan reaches both ends: the vector probe verifies
the retriever, this probe verifies the pipeline that wraps it. Run both
in the same suite when verifying a stack with a real RAG pipeline.
"""

from sectum_ai.probes.detection import DetectingProbe
from sectum_ai.spec import Finding, Observation, ProbeStep, Substrate, Surface


class RagPipelineBleedProbe(DetectingProbe):
    """Class 2: benign shared-entity queries against the RAG pipeline."""

    id = "rag-pipeline-bleed"
    name = "Organic entity-bleed via the RAG pipeline"
    owasp_llm = "LLM08:2025"
    atlas_techniques: tuple[str, ...] = ("AML.T0024", "AML.T0057")
    nist_rmf: tuple[str, ...] = ("MEASURE 2.7",)
    surfaces: tuple[Surface, ...] = (Surface.RAG_PIPELINE,)
    requires_adapters: tuple[str, ...] = ("rag",)

    def plan(self, substrate: Substrate) -> list[ProbeStep]:
        """Plan one benign shared-entity query per principal, dispatched via ``rag.ask``."""
        steps: list[ProbeStep] = []
        for entity in substrate.scenario.shared_entities:
            for observer in substrate.principals():
                steps.append(
                    ProbeStep(
                        step_id=f"{self.id}-{len(steps):04d}",
                        probe_id=self.id,
                        actor_tenant_id=observer.tenant_id,
                        actor_user_id=observer.user_id,
                        action="rag.ask",
                        payload={"query": f"records mentioning {entity.value}"},
                    )
                )
        return steps

    def detect(
        self, step: ProbeStep, observation: Observation, substrate: Substrate
    ) -> list[Finding]:
        """Scan the RAG answer for any foreign-principal canary via the pipeline."""
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
