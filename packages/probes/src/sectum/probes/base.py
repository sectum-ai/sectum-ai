"""The Sectum AI probe interface and registry (the engineering spec, section 7).

A probe implements one attack class behind a stable interface, so the catalog
is pluggable. Planning is deterministic from the scenario and seed; detection is
side-effecting only through adapters.
"""

from typing import Protocol, runtime_checkable

from sectum.spec import Finding, Observation, ProbeStep, Scenario, Substrate, Surface


@runtime_checkable
class Probe(Protocol):
    """A pluggable attack-class probe (the engineering spec, section 7.0)."""

    id: str
    name: str
    owasp_llm: str
    atlas_techniques: tuple[str, ...]
    nist_rmf: tuple[str, ...]
    surfaces: tuple[Surface, ...]
    requires_adapters: tuple[str, ...]

    def plan(self, scenario: Scenario) -> list[ProbeStep]:
        """Deterministically produce the steps (queries or actions) to run."""
        ...

    def detect(
        self, step: ProbeStep, observation: Observation, substrate: Substrate
    ) -> list[Finding]:
        """Apply the detection pipeline to one observation; return findings."""
        ...


class ProbeRegistry:
    """An in-memory registry of probes, keyed by probe id."""

    def __init__(self) -> None:
        self._probes: dict[str, Probe] = {}

    def register(self, probe: Probe) -> None:
        """Register ``probe`` under its id."""
        if probe.id in self._probes:
            raise ValueError(f"probe already registered: {probe.id}")
        self._probes[probe.id] = probe

    def get(self, probe_id: str) -> Probe:
        """Return the probe registered under ``probe_id``."""
        return self._probes[probe_id]

    def all(self) -> list[Probe]:
        """Return every registered probe, ordered by id."""
        return [self._probes[probe_id] for probe_id in sorted(self._probes)]
