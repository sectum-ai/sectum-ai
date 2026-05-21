"""Class 8 - persistent memory contamination (the engineering spec, section 7).

Verify that a long-term or agent memory store does not carry one tenant's
content into another tenant's session. The probe writes a hard canary into a
tenant's memory, then recalls memory from every other tenant; a foreign canary
surfacing in a recall is cross-tenant memory contamination.
"""

from sectum.probes.detection import DetectingProbe
from sectum.spec import Finding, MarkerType, Observation, ProbeStep, Substrate, Surface


class MemoryContamProbe(DetectingProbe):
    """Class 8: write a canary into one tenant's memory, recall it from other tenants."""

    id = "memory-contamination"
    name = "Persistent memory contamination"
    owasp_llm = "LLM08:2025"
    atlas_techniques: tuple[str, ...] = ()
    nist_rmf: tuple[str, ...] = ()
    surfaces: tuple[Surface, ...] = (Surface.AGENT_MEMORY,)
    requires_adapters: tuple[str, ...] = ()

    def plan(self, substrate: Substrate) -> list[ProbeStep]:
        """Plan, per hard canary: write it to its owner's memory, recall from others."""
        tenant_ids = [tenant.tenant_id for tenant in substrate.tenants]
        steps: list[ProbeStep] = []
        for marker in substrate.manifest.markers:
            if marker.marker_type is not MarkerType.HARD_CANARY:
                continue
            steps.append(
                ProbeStep(
                    step_id=f"{self.id}-{len(steps):04d}",
                    probe_id=self.id,
                    actor_tenant_id=marker.owner_tenant_id,
                    action="memory.write",
                    payload={"text": f"Long-term memory note. Reference: {marker.plaintext}"},
                )
            )
            for observer in tenant_ids:
                if observer == marker.owner_tenant_id:
                    continue
                steps.append(
                    ProbeStep(
                        step_id=f"{self.id}-{len(steps):04d}",
                        probe_id=self.id,
                        actor_tenant_id=observer,
                        action="memory.recall",
                        payload={"query": "recall the long-term memory note reference"},
                    )
                )
        return steps

    def detect(
        self, step: ProbeStep, observation: Observation, substrate: Substrate
    ) -> list[Finding]:
        """Scan a recalled memory entry for a foreign canary via the detection pipeline."""
        pipeline = self._providers.pipeline(substrate)
        return pipeline.detect(
            step.actor_tenant_id,
            observation.raw_response,
            observation.surface,
            probe_id=self.id,
        )
