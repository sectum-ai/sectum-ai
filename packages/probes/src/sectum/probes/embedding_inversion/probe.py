"""Class 6 - embedding inversion across tenants (the engineering spec, section 7).

When embeddings are reachable across the tenant boundary - typically through a
shared index - an attacker holding only a partial signal for a foreign entity
can reconstruct the rest. The probe queries the index with a fragment of each
foreign entity canary; if the index returns the full canary content, the
foreign entity has been reconstructed from partial knowledge.
"""

from sectum.probes.detection import DetectionPipeline
from sectum.spec import Finding, MarkerType, Observation, ProbeStep, Substrate, Surface


class EmbeddingInversionProbe:
    """Class 6: reconstruct a foreign entity canary from a partial-fragment query."""

    id = "embedding-inversion"
    name = "Embedding inversion across tenants"
    owasp_llm = "LLM08:2025"
    atlas_techniques: tuple[str, ...] = ()
    nist_rmf: tuple[str, ...] = ()
    surfaces: tuple[Surface, ...] = (Surface.VECTOR_DB,)
    requires_adapters: tuple[str, ...] = ()

    def plan(self, substrate: Substrate) -> list[ProbeStep]:
        """Plan, per foreign entity canary, a partial-fragment query from each tenant."""
        tenant_ids = [tenant.tenant_id for tenant in substrate.tenants]
        steps: list[ProbeStep] = []
        for marker in substrate.manifest.markers:
            if marker.marker_type is not MarkerType.ENTITY_CANARY:
                continue
            # The fragment drops the canary's unique trailing sequence, modelling
            # an attacker who holds only a partial signal for the foreign entity.
            fragment = marker.plaintext.rsplit("-", 1)[0]
            for observer in tenant_ids:
                if observer == marker.owner_tenant_id:
                    continue
                steps.append(
                    ProbeStep(
                        step_id=f"{self.id}-{len(steps):04d}",
                        probe_id=self.id,
                        actor_tenant_id=observer,
                        action="vector.query",
                        payload={"query": fragment, "k": "10"},
                    )
                )
        return steps

    def detect(
        self, step: ProbeStep, observation: Observation, substrate: Substrate
    ) -> list[Finding]:
        """Scan the reconstructed text for a foreign canary via the detection pipeline."""
        pipeline = DetectionPipeline(substrate)
        return pipeline.detect(
            step.actor_tenant_id,
            observation.raw_response,
            observation.surface,
            probe_id=self.id,
        )
