"""The scenario runner: executes a probe against a substrate via adapters.

The engineering spec section 12 places the runner in core; with ADR-0004 the
package graph stays acyclic (core depends on probes, never the reverse).
"""

from sectum.adapters import CacheAdapter, VectorStoreAdapter
from sectum.probes import Probe, confirmed_findings
from sectum.spec import Finding, Observation, ProbeStep, Substrate, Surface

StepResult = tuple[ProbeStep, list[Finding]]
"""One planned step paired with the findings it produced."""


class Runner:
    """Runs a probe end to end: plan, execute each step via adapters, detect."""

    def __init__(
        self,
        substrate: Substrate,
        *,
        vector: VectorStoreAdapter | None = None,
        cache: CacheAdapter | None = None,
    ) -> None:
        self._substrate = substrate
        self._vector = vector
        self._cache = cache

    def run_per_step(self, probe: Probe) -> list[StepResult]:
        """Plan and run the probe, pairing each step with the findings it produced."""
        results: list[StepResult] = []
        for step in probe.plan(self._substrate):
            observation = self._execute(step)
            results.append((step, probe.detect(step, observation, self._substrate)))
        return results

    def run(self, probe: Probe) -> list[Finding]:
        """Plan the probe, execute every step, and return all findings."""
        return [finding for _, findings in self.run_per_step(probe) for finding in findings]

    def _execute(self, step: ProbeStep) -> Observation:
        if step.action == "vector.query":
            return self._vector_query(step)
        if step.action == "cache.set":
            return self._cache_set(step)
        if step.action == "cache.get":
            return self._cache_get(step)
        raise ValueError(f"runner cannot execute action: {step.action!r}")

    def _vector_query(self, step: ProbeStep) -> Observation:
        if self._vector is None:
            raise ValueError("a vector.query step needs a vector adapter")
        k = int(step.payload.get("k", "5"))
        hits = self._vector.query(step.actor_tenant_id, step.payload["query"], k)
        return Observation(
            step_id=step.step_id,
            surface=Surface.VECTOR_DB,
            raw_response="\n".join(hit.content for hit in hits),
        )

    def _cache_set(self, step: ProbeStep) -> Observation:
        if self._cache is None:
            raise ValueError("a cache.set step needs a cache adapter")
        self._cache.set(step.actor_tenant_id, step.payload["key"], step.payload["value"])
        return Observation(step_id=step.step_id, surface=Surface.SEMANTIC_CACHE, raw_response="")

    def _cache_get(self, step: ProbeStep) -> Observation:
        if self._cache is None:
            raise ValueError("a cache.get step needs a cache adapter")
        value = self._cache.get(step.actor_tenant_id, step.payload["key"])
        return Observation(
            step_id=step.step_id,
            surface=Surface.SEMANTIC_CACHE,
            raw_response=value or "",
        )


def retrieval_pivot_rate(step_results: list[StepResult]) -> float:
    """Fraction of benign steps that surfaced a confirmed cross-tenant leak.

    The Class 2 headline metric, the Retrieval-Pivot Rate (the engineering spec,
    section 7).
    """
    if not step_results:
        return 0.0
    pivoted = sum(1 for _, findings in step_results if confirmed_findings(findings))
    return pivoted / len(step_results)
