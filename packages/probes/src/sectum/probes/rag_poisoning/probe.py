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
    atlas_techniques: tuple[str, ...] = ()
    nist_rmf: tuple[str, ...] = ()
    surfaces: tuple[Surface, ...] = (Surface.VECTOR_DB,)
    requires_adapters: tuple[str, ...] = ()

    def plan(self, substrate: Substrate) -> list[ProbeStep]:
        """Plan: every tenant plants a poison document, then every tenant queries the lure."""
        steps: list[ProbeStep] = []
        for tenant in substrate.tenants:
            hard = next(
                (
                    marker
                    for marker in substrate.manifest.markers
                    if marker.owner_tenant_id == tenant.tenant_id
                    and marker.marker_type is MarkerType.HARD_CANARY
                ),
                None,
            )
            if hard is None:
                continue
            steps.append(
                ProbeStep(
                    step_id=f"{self.id}-{len(steps):04d}",
                    probe_id=self.id,
                    actor_tenant_id=tenant.tenant_id,
                    action="vector.upsert",
                    payload={
                        "doc_id": f"poison-{tenant.tenant_id.hex[:8]}",
                        "content": f"Poisoned {_POISON_LURE}. Reference: {hard.plaintext}",
                    },
                )
            )
        for tenant in substrate.tenants:
            steps.append(
                ProbeStep(
                    step_id=f"{self.id}-{len(steps):04d}",
                    probe_id=self.id,
                    actor_tenant_id=tenant.tenant_id,
                    action="vector.query",
                    payload={"query": _POISON_LURE, "k": "10"},
                )
            )
        return steps

    def detect(
        self, step: ProbeStep, observation: Observation, substrate: Substrate
    ) -> list[Finding]:
        """Scan a query's retrieved context for a foreign poison canary."""
        pipeline = self._providers.pipeline(substrate)
        return pipeline.detect(
            step.actor_tenant_id,
            observation.raw_response,
            observation.surface,
            probe_id=self.id,
        )
