"""Class 4 - semantic-cache contamination (the engineering spec, section 7).

A semantic cache collapses semantically-near queries onto a single stored
entry, so two tenants asking near-identical questions can land on the same
cache key. This probe primes such an entry as one tenant - with an answer
carrying that tenant's hard canary - then reads it from every other tenant's
session. If the cache key space is not tenant-scoped, the other tenants are
served the first tenant's cached answer: a cross-tenant leak. The probe
verifies cache-key tenancy; the embedding-similarity matching that produces a
shared entry is assumed, not modelled by the in-memory fake.
"""

from sectum.probes.detection import DetectingProbe, is_cross_principal
from sectum.spec import Finding, MarkerType, Observation, ProbeStep, Substrate, Surface


class SemanticCacheProbe(DetectingProbe):
    """Class 4: verify a semantic cache never serves an answer across tenants."""

    id = "semantic-cache-contamination"
    name = "Semantic-cache contamination"
    owasp_llm = "LLM08:2025"
    atlas_techniques: tuple[str, ...] = ()
    nist_rmf: tuple[str, ...] = ()
    surfaces: tuple[Surface, ...] = (Surface.SEMANTIC_CACHE,)
    requires_adapters: tuple[str, ...] = ()

    def plan(self, substrate: Substrate) -> list[ProbeStep]:
        """Plan a prime-then-fetch sequence for every hard canary across principals.

        Each entry is primed once as the marker's owning principal, then fetched
        from every principal to which the marker is foreign - another tenant, or
        another user within the tenant (ADR-0006) - so cache-key tenancy is
        verified at both granularities. With no users declared the principals are
        the tenants and this is the original per-tenant plan.
        """
        principals = substrate.principals()
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
                    actor_user_id=marker.owner_user_id,
                    action="cache.set",
                    payload={
                        "key": key,
                        "value": f"Cached answer. Reference: {marker.plaintext}",
                    },
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
                        action="cache.get",
                        payload={"key": key},
                    )
                )
        return steps

    def detect(
        self, step: ProbeStep, observation: Observation, substrate: Substrate
    ) -> list[Finding]:
        """Scan a fetched cache value for a foreign-principal canary via the pipeline."""
        pipeline = self._providers.pipeline(substrate)
        return pipeline.detect(
            step.actor_tenant_id,
            observation.raw_response,
            observation.surface,
            probe_id=self.id,
            observed_user=step.actor_user_id,
        )
