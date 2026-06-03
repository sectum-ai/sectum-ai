"""Assembles a complete substrate from a scenario (the engineering spec, section 6)."""

import hashlib

from sectum.spec import CorpusDocument, Marker, MarkerType, Scenario, Substrate
from sectum.substrate.corpus import generate_corpus
from sectum.substrate.manifest import build_manifest
from sectum.substrate.markers import generate_markers
from sectum.substrate.rng import derive_rng

# Declared when a scenario configures no embedding model; matches the offline
# deterministic embedder the detection pipeline falls back to.
_DEFAULT_EMBEDDING_MODEL = "fake-deterministic"


def _embedding_ref(marker: Marker, embedding_models: tuple[str, ...]) -> str | None:
    """A content+model address for a semantic marker's embedding (the spec, section 6.3).

    Only ENTITY_CANARY markers carry a semantic embedding - HARD and SECRET
    canaries are matched exactly - so only they get a ref. The ref names the
    embedding model the substrate declares (``embedding_models[0]``, or the
    offline default) plus a digest of the plaintext, so the manifest records
    *which model* the semantic-detection vectors correspond to - a provable test
    condition in the evidence chain (the spec, section 8) - and the same entity
    addresses a distinct vector under a different model.
    """
    if marker.marker_type is not MarkerType.ENTITY_CANARY:
        return None
    model = embedding_models[0] if embedding_models else _DEFAULT_EMBEDDING_MODEL
    digest = hashlib.sha256(marker.plaintext.encode("utf-8")).hexdigest()[:16]
    return f"{model}/{digest}"


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
            tenant_spec.users,
        )
        sequence += len(markers)
        documents, locations = generate_corpus(
            tenant_spec,
            derive_rng(scenario.seed, "corpus", index),
            markers,
            scenario.shared_entities,
        )
        planted = [
            marker.model_copy(
                update={
                    "planted_locations": tuple(locations[marker.marker_id]),
                    "embedding_ref": _embedding_ref(marker, scenario.embedding_models),
                }
            )
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
