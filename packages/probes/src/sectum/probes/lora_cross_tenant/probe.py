"""Class 9 - LoRA / adapter cross-tenant influence (the engineering spec, section 7).

For a model that hosts per-tenant fine-tunes or LoRA adapters, verify that one
tenant's adapter does not influence another tenant's inference. The probe trains
a tenant's adapter on a memorizable hard-canary phrase, then runs inference from
every other tenant; a foreign canary surfacing in a response is weight bleed.
"""

from sectum.probes.detection import DetectingProbe
from sectum.spec import Finding, MarkerType, Observation, ProbeStep, Substrate, Surface


class LoraCrossTenantProbe(DetectingProbe):
    """Class 9: train a tenant's adapter on a canary, then infer from other tenants."""

    id = "lora-cross-tenant"
    name = "LoRA / adapter cross-tenant influence"
    owasp_llm = "LLM08:2025"
    atlas_techniques: tuple[str, ...] = ()
    nist_rmf: tuple[str, ...] = ()
    surfaces: tuple[Surface, ...] = (Surface.MODEL_ADAPTER,)
    requires_adapters: tuple[str, ...] = ()

    def plan(self, substrate: Substrate) -> list[ProbeStep]:
        """Plan, per hard canary: train its owner's adapter, then infer as others."""
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
                    action="model.train",
                    payload={"text": f"Memorized adapter fact. Reference: {marker.plaintext}"},
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
                        action="model.infer",
                        payload={"prompt": "recall the memorized adapter fact reference"},
                    )
                )
        return steps

    def detect(
        self, step: ProbeStep, observation: Observation, substrate: Substrate
    ) -> list[Finding]:
        """Scan an inference response for a foreign canary via the detection pipeline."""
        pipeline = self._providers.pipeline(substrate)
        return pipeline.detect(
            step.actor_tenant_id,
            observation.raw_response,
            observation.surface,
            probe_id=self.id,
        )
