"""Class 13 - multi-modal RAG entity-bleed (the engineering spec, section 7).

The Class 2 Retrieval Pivot over *images*. Multi-modal RAG embeds images (and text)
into one vector space, so benign, non-adversarial image queries seeded on a *visual*
entity that tenants share - a chart type, a logo, a product photo, a floor plan -
surface another tenant's image, and its canary marker rides along in the retrieved
image's caption/payload. No prompt injection is used; the pivot is a property of the
shared multi-modal index, exactly as in Class 2.

The per-model **image Retrieval-Pivot Rate** is measured by
:func:`sectum_ai.multimodal.multimodal_provider_sweep`, which drives this probe's
plan/detect over deterministic synthetic images (the ``imagehash-<dim>`` CI proxy) or real
CLIP; on real embedders a stronger model leaks more, the multi-modal echo of Class 2.
"""

from sectum_ai.probes.detection import DetectingProbe
from sectum_ai.spec import Finding, Observation, ProbeStep, Substrate, Surface

# A fixed catalog of shared visual entities. Each name keys a deterministic synthetic
# image in :mod:`sectum_ai.multimodal`; every tenant owns a pivot image per entity, so a
# benign query for an entity retrieves the foreign tenants' pivot images (the pivot).
VISUAL_ENTITIES: tuple[str, ...] = (
    "bar-chart",
    "circuit-board",
    "org-logo",
    "product-photo",
    "floor-plan",
    "signature-card",
)


class MultimodalRagBleedProbe(DetectingProbe):
    """Class 13: benign shared-visual-entity image queries that pivot across tenants."""

    id = "multimodal-rag-bleed"
    name = "Multi-modal RAG entity-bleed"
    owasp_llm = "LLM08:2025"
    atlas_techniques: tuple[str, ...] = ("AML.T0024", "AML.T0057")
    nist_rmf: tuple[str, ...] = ("MEASURE 2.7",)
    surfaces: tuple[Surface, ...] = (Surface.VECTOR_DB,)
    requires_adapters: tuple[str, ...] = ("vector",)

    def plan(self, substrate: Substrate) -> list[ProbeStep]:
        """Plan one benign image query per shared visual entity, from every principal.

        Mirrors Class 2: issuing from each principal (a tenant, or a user within a
        tenant - ADR-0006) verifies isolation at both granularities. The payload names
        the visual entity; the multi-modal store (or the sweep) renders/embeds its
        canonical image and retrieves by image similarity.
        """
        steps: list[ProbeStep] = []
        for entity in VISUAL_ENTITIES:
            for observer in substrate.principals():
                steps.append(
                    ProbeStep(
                        step_id=f"{self.id}-{len(steps):04d}",
                        probe_id=self.id,
                        actor_tenant_id=observer.tenant_id,
                        actor_user_id=observer.user_id,
                        action="vector.query",
                        payload={"query": entity, "k": "5"},
                    )
                )
        return steps

    def detect(
        self, step: ProbeStep, observation: Observation, substrate: Substrate
    ) -> list[Finding]:
        """Scan the retrieved image payloads for any foreign-principal canary."""
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
