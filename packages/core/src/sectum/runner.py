"""The scenario runner: executes a probe against a substrate via adapters.

The engineering spec section 12 places the runner in core; with ADR-0004 the
package graph stays acyclic (core depends on probes, never the reverse).
"""

from sectum.adapters import VectorStoreAdapter
from sectum.probes import Probe
from sectum.spec import Finding, Observation, ProbeStep, Substrate, Surface


class Runner:
    """Runs a probe end to end: plan, execute each step via adapters, detect."""

    def __init__(self, substrate: Substrate, *, vector: VectorStoreAdapter | None = None) -> None:
        self._substrate = substrate
        self._vector = vector

    def run(self, probe: Probe) -> list[Finding]:
        """Plan the probe, execute every step, and return all findings."""
        findings: list[Finding] = []
        for step in probe.plan(self._substrate):
            observation = self._execute(step)
            findings.extend(probe.detect(step, observation, self._substrate))
        return findings

    def _execute(self, step: ProbeStep) -> Observation:
        if step.action == "vector.query":
            return self._vector_query(step)
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
