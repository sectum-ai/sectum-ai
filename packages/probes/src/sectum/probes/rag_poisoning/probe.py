"""Class 3 - adversarial RAG poisoning (the engineering spec, section 7).

A tenant plants a poisoned document - benign-looking, stuffed with a generic
lure phrase so it ranks highly, and carrying that tenant's hard canary. On a
shared index the poison document is retrieved into other tenants' benign
queries, pivoting the canary across the tenant boundary.
"""

from sectum.probes.detection import DetectingProbe
from sectum.spec import Finding, MarkerType, Observation, ProbeStep, Substrate, Surface

_POISON_LURE = "quarterly operations digest"


class RagPoisoningProbe(DetectingProbe):
    """Class 3: plant a poison document, then query its lure from other tenants."""

    id = "rag-poisoning"
    name = "Adversarial RAG poisoning"
    owasp_llm = "LLM08:2025"
    atlas_techniques: tuple[str, ...] = ("AML.T0024",)
    nist_rmf: tuple[str, ...] = ("MEASURE 2.7",)
    surfaces: tuple[Surface, ...] = (Surface.VECTOR_DB,)
    requires_adapters: tuple[str, ...] = ()

    def plan(self, substrate: Substrate) -> list[ProbeStep]:
        """Plan: each hard canary's owning principal plants a poison, then all query the lure.

        A poison document is planted once per hard canary as the marker's owning
        principal - a tenant, or a user within a tenant (ADR-0006) - then every
        principal queries the lure, so poisoning is tested at both granularities.
        With no users declared the principals are the tenants and this is the
        original per-tenant plan.
        """
        steps: list[ProbeStep] = []
        for marker in substrate.manifest.markers:
            if marker.marker_type is not MarkerType.HARD_CANARY:
                continue
            steps.append(
                ProbeStep(
                    step_id=f"{self.id}-{len(steps):04d}",
                    probe_id=self.id,
                    actor_tenant_id=marker.owner_tenant_id,
                    actor_user_id=marker.owner_user_id,
                    action="vector.upsert",
                    payload={
                        "doc_id": f"poison-{marker.marker_id}",
                        "content": f"Poisoned {_POISON_LURE}. Reference: {marker.plaintext}",
                    },
                )
            )
        for observer in substrate.principals():
            steps.append(
                ProbeStep(
                    step_id=f"{self.id}-{len(steps):04d}",
                    probe_id=self.id,
                    actor_tenant_id=observer.tenant_id,
                    actor_user_id=observer.user_id,
                    action="vector.query",
                    payload={"query": _POISON_LURE, "k": "10"},
                )
            )
        return steps

    def detect(
        self, step: ProbeStep, observation: Observation, substrate: Substrate
    ) -> list[Finding]:
        """Scan a query's retrieved context for a foreign-principal poison canary."""
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
