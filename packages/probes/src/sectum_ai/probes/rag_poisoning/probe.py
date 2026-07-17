"""Class 3 - adversarial RAG poisoning (the engineering spec, section 7).

A tenant plants a poisoned document - benign-looking, stuffed with a generic
lure phrase so it ranks highly, and carrying that tenant's hard canary. On a
shared index the poison document is retrieved into other tenants' benign
queries, pivoting the canary across the tenant boundary.
"""

from sectum_ai.probes.detection import DetectingProbe, cross_principal_observers, is_cross_principal
from sectum_ai.spec import Finding, MarkerType, Observation, ProbeStep, Substrate, Surface

_POISON_LURE = "quarterly operations digest"


class RagPoisoningProbe(DetectingProbe):
    """Class 3: plant a poison document, then query its lure from other tenants."""

    id = "rag-poisoning"
    name = "Adversarial RAG poisoning"
    owasp_llm = "LLM08:2025"
    # T0020 Poison Training Data is the technique (planting the poison document);
    # T0024 Exfiltration via AI Inference API is the cross-tenant leak it induces.
    atlas_techniques: tuple[str, ...] = ("AML.T0020", "AML.T0024")
    nist_rmf: tuple[str, ...] = ("MEASURE 2.7",)
    surfaces: tuple[Surface, ...] = (Surface.VECTOR_DB,)
    requires_adapters: tuple[str, ...] = ("vector",)

    def plan(self, substrate: Substrate) -> list[ProbeStep]:
        """Plan: each hard canary's owning principal plants a poison, then all query the lure.

        A poison document is planted once per hard canary as the marker's owning
        principal - a tenant, or a user within a tenant (ADR-0006) - then every
        principal queries the lure, so poisoning is tested at both granularities.
        With no users declared the principals are the tenants and this is the
        original per-tenant plan.
        """
        principals = substrate.principals()
        steps: list[ProbeStep] = []
        # Plant a poison only where someone foreign could retrieve it. A poison whose
        # canary is foreign to no principal cannot be surfaced by any query, so planting
        # it asks the stack nothing while still recording this probe as having run - and
        # `score` grades a probe that ran and found nothing as PASS (docs/scorecard.md,
        # rule 1). Poison only what someone can steal.
        planted = [
            marker
            for marker in substrate.manifest.markers
            if marker.marker_type is MarkerType.HARD_CANARY
            and cross_principal_observers([marker], principals)
        ]
        for marker in planted:
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
        # Query the lure only from a principal foreign to at least one planted poison:
        # the shared lure retrieves every poison, so such a principal can surface a
        # cross-principal leak, and no other principal can.
        for observer in principals:
            if any(is_cross_principal(marker, observer) for marker in planted):
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
            owasp_secondary=self.owasp_secondary,
        )
