"""Class 6 - embedding inversion across tenants (the engineering spec, section 7).

When embeddings are reachable across the tenant boundary - typically through a
shared index - an attacker holding only a partial signal for a foreign entity
can reconstruct the rest. The probe queries the index with a fragment of each
foreign entity canary; if the index returns the full canary content, the
foreign entity has been reconstructed from partial knowledge.
"""

from sectum.probes.detection import DetectingProbe, is_cross_principal
from sectum.spec import Finding, MarkerType, Observation, ProbeStep, Substrate, Surface


class EmbeddingInversionProbe(DetectingProbe):
    """Class 6: reconstruct a foreign entity canary from a partial-fragment query."""

    id = "embedding-inversion"
    name = "Embedding inversion across tenants"
    owasp_llm = "LLM08:2025"
    atlas_techniques: tuple[str, ...] = ("AML.T0024", "AML.T0024.001")
    nist_rmf: tuple[str, ...] = ("MEASURE 2.7",)
    surfaces: tuple[Surface, ...] = (Surface.VECTOR_DB,)
    requires_adapters: tuple[str, ...] = ("vector",)

    def plan(self, substrate: Substrate) -> list[ProbeStep]:
        """Plan, per entity canary, a partial-fragment query from each foreign principal.

        The fragment is queried from every principal to which the entity is
        foreign - another tenant, or another user within the tenant (ADR-0006) -
        so reconstruction is tested at both granularities. With no users declared
        the principals are the tenants and this is the original per-tenant plan.
        """
        principals = substrate.principals()
        steps: list[ProbeStep] = []
        for marker in substrate.manifest.markers:
            if marker.marker_type is not MarkerType.ENTITY_CANARY:
                continue
            # The fragment drops the canary's unique trailing sequence, modelling
            # an attacker who holds only a partial signal for the foreign entity.
            fragment = marker.plaintext.rsplit("-", 1)[0]
            for observer in principals:
                if not is_cross_principal(marker, observer):
                    continue
                steps.append(
                    ProbeStep(
                        step_id=f"{self.id}-{len(steps):04d}",
                        probe_id=self.id,
                        actor_tenant_id=observer.tenant_id,
                        actor_user_id=observer.user_id,
                        action="vector.query",
                        payload={"query": fragment, "k": "10"},
                    )
                )
        return steps

    def detect(
        self, step: ProbeStep, observation: Observation, substrate: Substrate
    ) -> list[Finding]:
        """Scan the reconstructed text for a foreign-principal canary via the pipeline."""
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
