"""Class 4 - semantic-cache contamination (the engineering spec, section 7).

Prime a cache entry as one tenant, with an answer that carries that tenant's
hard canary, then issue the same (semantically normalized) query as every other
tenant. If the cache key space is not tenant-scoped, the second tenant is served
the first tenant's cached answer - a cross-tenant leak.
"""

from sectum.probes.detection import DetectionPipeline
from sectum.spec import Finding, MarkerType, Observation, ProbeStep, Substrate, Surface


class SemanticCacheProbe:
    """Class 4: verify a semantic cache never serves an answer across tenants."""

    id = "semantic-cache-contamination"
    name = "Semantic-cache contamination"
    owasp_llm = "LLM08:2025"
    atlas_techniques: tuple[str, ...] = ()
    nist_rmf: tuple[str, ...] = ()
    surfaces: tuple[Surface, ...] = (Surface.SEMANTIC_CACHE,)
    requires_adapters: tuple[str, ...] = ()

    def plan(self, substrate: Substrate) -> list[ProbeStep]:
        """Plan a prime-then-fetch sequence for every tenant's hard canaries."""
        tenant_ids = [tenant.tenant_id for tenant in substrate.tenants]
        steps: list[ProbeStep] = []
        for marker in substrate.manifest.markers:
            if marker.marker_type is not MarkerType.HARD_CANARY:
                continue
            key = f"cache-probe:{marker.marker_id}"
            steps.append(
                ProbeStep(
                    step_id=f"{self.id}-{len(steps):04d}",
                    probe_id=self.id,
                    actor_tenant_id=marker.owner_tenant_id,
                    action="cache.set",
                    payload={
                        "key": key,
                        "value": f"Cached answer. Reference: {marker.plaintext}",
                    },
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
                        action="cache.get",
                        payload={"key": key},
                    )
                )
        return steps

    def detect(
        self, step: ProbeStep, observation: Observation, substrate: Substrate
    ) -> list[Finding]:
        """Scan a fetched cache value for a foreign canary via the detection pipeline."""
        pipeline = DetectionPipeline(substrate)
        return pipeline.detect(
            step.actor_tenant_id,
            observation.raw_response,
            observation.surface,
            probe_id=self.id,
        )
