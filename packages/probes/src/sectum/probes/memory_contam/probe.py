"""Class 8 - persistent memory contamination (the engineering spec, section 7).

Verify that a long-term or agent memory store does not carry one tenant's
content into another tenant's session. The probe writes a hard canary into a
tenant's memory, then recalls memory from every other tenant; a foreign canary
surfacing in a recall is cross-tenant memory contamination.
"""

from sectum.probes.detection import DetectingProbe, is_cross_principal
from sectum.spec import Finding, MarkerType, Observation, ProbeStep, Substrate, Surface


class MemoryContamProbe(DetectingProbe):
    """Class 8: write a canary into one tenant's memory, recall it from other tenants."""

    id = "memory-contamination"
    name = "Persistent memory contamination"
    owasp_llm = "LLM08:2025"
    atlas_techniques: tuple[str, ...] = ("AML.T0057",)
    nist_rmf: tuple[str, ...] = ("MEASURE 2.7",)
    surfaces: tuple[Surface, ...] = (Surface.AGENT_MEMORY,)
    requires_adapters: tuple[str, ...] = ("memory",)

    def plan(self, substrate: Substrate) -> list[ProbeStep]:
        """Plan, per hard canary: write it to its owner, recall from foreign principals.

        The note is written once as the marker's owning principal, then recalled
        from every principal to which the marker is foreign - another tenant, or
        another user within the tenant (ADR-0006) - so memory isolation is
        verified at both granularities. With no users declared the principals are
        the tenants and this is the original per-tenant plan.
        """
        principals = substrate.principals()
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
                    action="memory.write",
                    payload={"text": f"Long-term memory note. Reference: {marker.plaintext}"},
                )
            )
            for observer in principals:
                if not is_cross_principal(marker, observer):
                    continue
                steps.append(
                    ProbeStep(
                        step_id=f"{self.id}-{len(steps):04d}",
                        probe_id=self.id,
                        actor_tenant_id=observer.tenant_id,
                        actor_user_id=observer.user_id,
                        action="memory.recall",
                        payload={"query": "recall the long-term memory note reference"},
                    )
                )
        return steps

    def detect(
        self, step: ProbeStep, observation: Observation, substrate: Substrate
    ) -> list[Finding]:
        """Scan a recalled memory entry for a foreign-principal canary via the pipeline."""
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
