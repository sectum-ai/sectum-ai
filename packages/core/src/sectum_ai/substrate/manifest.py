"""Ground-truth manifest construction (the engineering spec, section 6.3).

The manifest records which marker belongs to which tenant. It is a pure
function of the scenario and seed; its canonical hash anchors the test
conditions in the evidence chain (the engineering spec, section 8).
"""

from sectum_ai.spec import GroundTruthManifest, Marker, Scenario, canonical_hash


def build_manifest(scenario: Scenario, markers: list[Marker]) -> GroundTruthManifest:
    """Assemble the ground-truth manifest for a scenario's planted markers."""
    return GroundTruthManifest(
        manifest_id=f"manifest-{scenario.scenario_id}",
        scenario_hash=canonical_hash(scenario),
        markers=tuple(markers),
    )
