"""Assembles a complete substrate from a scenario (the engineering spec, section 6)."""

from sectum.spec import CorpusDocument, Marker, Scenario, Substrate
from sectum.substrate.corpus import generate_corpus
from sectum.substrate.manifest import build_manifest
from sectum.substrate.markers import generate_markers
from sectum.substrate.rng import derive_rng


def build_substrate(scenario: Scenario) -> Substrate:
    """Provision tenants, generate corpora, plant markers, and build the manifest.

    Deterministic: the same scenario always yields a byte-identical substrate
    (the reproducibility contract, the engineering spec, section 6.5).
    """
    all_markers: list[Marker] = []
    all_documents: list[CorpusDocument] = []
    sequence = 0
    for index, tenant_spec in enumerate(scenario.tenants):
        markers = generate_markers(
            tenant_spec.tenant_id,
            derive_rng(scenario.seed, "markers", index),
            sequence,
        )
        sequence += len(markers)
        documents, locations = generate_corpus(
            tenant_spec,
            derive_rng(scenario.seed, "corpus", index),
            markers,
            scenario.shared_entities,
        )
        planted = [
            marker.model_copy(update={"planted_locations": tuple(locations[marker.marker_id])})
            for marker in markers
        ]
        all_markers.extend(planted)
        all_documents.extend(documents)
    return Substrate(
        scenario=scenario,
        tenants=scenario.tenants,
        documents=tuple(all_documents),
        manifest=build_manifest(scenario, all_markers),
    )
