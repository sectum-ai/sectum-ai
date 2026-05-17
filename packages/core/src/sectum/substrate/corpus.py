"""Deterministic synthetic corpus generation (the engineering spec, section 6.2).

Corpora are templated and seeded so the same scenario always produces a
byte-identical corpus. Shared organic entities are woven in as leakage bait, and
each tenant's markers are planted into document bodies, titles, and metadata.
"""

import random

from sectum.spec import CorpusDocument, Marker, PlantedLocation, SharedEntity, SyntheticTenantSpec

_DOC_TYPES: tuple[str, ...] = (
    "hr_record",
    "sales_pipeline",
    "support_ticket",
    "contract",
    "meeting_notes",
)
_FIRST_NAMES: tuple[str, ...] = (
    "Alex",
    "Sam",
    "Priya",
    "Jordan",
    "Lin",
    "Omar",
    "Nina",
    "Tomas",
)
_LAST_NAMES: tuple[str, ...] = (
    "Reyes",
    "Patel",
    "Okafor",
    "Novak",
    "Brooks",
    "Suzuki",
    "Mwangi",
    "Vance",
)
_LOCAL_VENDORS: tuple[str, ...] = (
    "Apex Tooling",
    "Cedar Systems",
    "Riverbend Partners",
    "Summit Freight",
)
_TEMPLATES: dict[str, str] = {
    "hr_record": (
        "Employee {person} completed the quarterly {industry} review. Manager "
        "notes: performance on track; compensation band confirmed."
    ),
    "sales_pipeline": (
        "Opportunity with {vendor} is in negotiation. Estimated value {amount}, "
        "expected close {date}. Account owner: {person}."
    ),
    "support_ticket": (
        "Support ticket raised by {person} regarding a {industry} workflow. "
        "Priority medium; vendor {vendor} engaged for resolution."
    ),
    "contract": (
        "Master service agreement with {vendor}, effective {date}. Annual "
        "contract value {amount}; {compliance} compliance required."
    ),
    "meeting_notes": (
        "Planning sync held {date}. Attendee {person} led the {industry} "
        "roadmap discussion, including {compliance} readiness. Actions logged."
    ),
}
_MARKER_FIELDS: tuple[str, ...] = ("body", "metadata", "title")


def _slot_values(
    tenant_spec: SyntheticTenantSpec,
    shared: dict[str, list[str]],
    rng: random.Random,
    index: int,
) -> dict[str, str]:
    """Resolve template slots, mixing shared organic entities with local values."""
    use_shared = index % 2 == 0
    if index % 3 == 0 and "person" in shared:
        person = shared["person"][0]
    else:
        person = f"{rng.choice(_FIRST_NAMES)} {rng.choice(_LAST_NAMES)}"
    if use_shared and "vendor" in shared:
        vendor = shared["vendor"][index % len(shared["vendor"])]
    else:
        vendor = rng.choice(_LOCAL_VENDORS)
    if use_shared and "amount" in shared:
        amount = shared["amount"][index % len(shared["amount"])]
    else:
        amount = f"${rng.randint(20, 970)},000"
    if use_shared and "date" in shared:
        date = shared["date"][index % len(shared["date"])]
    else:
        date = f"2026-{rng.randint(1, 9):02d}-{rng.randint(10, 28)}"
    compliance = (
        shared["compliance_term"][index % len(shared["compliance_term"])]
        if "compliance_term" in shared
        else "internal policy"
    )
    return {
        "person": person,
        "industry": tenant_spec.industry,
        "vendor": vendor,
        "amount": amount,
        "date": date,
        "compliance": compliance,
    }


def generate_corpus(
    tenant_spec: SyntheticTenantSpec,
    rng: random.Random,
    markers: list[Marker],
    shared_entities: tuple[SharedEntity, ...],
) -> tuple[list[CorpusDocument], dict[str, list[PlantedLocation]]]:
    """Generate a tenant's synthetic corpus and plant its markers.

    Returns the documents and a mapping of marker id to the locations where that
    marker was planted.
    """
    shared: dict[str, list[str]] = {}
    for entity in shared_entities:
        shared.setdefault(entity.kind, []).append(entity.value)

    size = tenant_spec.corpus_size
    plantings: dict[int, list[tuple[Marker, str]]] = {}
    for marker_index, marker in enumerate(markers):
        doc_index = (marker_index * 5 + 2) % size
        field = _MARKER_FIELDS[marker_index % len(_MARKER_FIELDS)]
        plantings.setdefault(doc_index, []).append((marker, field))

    locations: dict[str, list[PlantedLocation]] = {marker.marker_id: [] for marker in markers}
    documents: list[CorpusDocument] = []
    short_id = tenant_spec.tenant_id.hex[:8]

    for index in range(size):
        doc_type = _DOC_TYPES[index % len(_DOC_TYPES)]
        doc_id = f"doc-{short_id}-{index:04d}"
        title = f"{doc_type.replace('_', ' ').title()} #{index:04d}"
        content = _TEMPLATES[doc_type].format(**_slot_values(tenant_spec, shared, rng, index))
        metadata: dict[str, str] = {"doc_type": doc_type, "tenant": tenant_spec.display_name}
        marker_ids: list[str] = []

        for marker, field in plantings.get(index, []):
            marker_ids.append(marker.marker_id)
            locations[marker.marker_id].append(PlantedLocation(doc_id=doc_id, field=field))
            if field == "body":
                content = f"{content}\nReference: {marker.plaintext}"
            elif field == "title":
                title = f"{title} - {marker.plaintext}"
            else:
                metadata[f"ref:{marker.marker_id}"] = marker.plaintext

        documents.append(
            CorpusDocument(
                doc_id=doc_id,
                tenant_id=tenant_spec.tenant_id,
                doc_type=doc_type,
                title=title,
                content=content,
                metadata=metadata,
                marker_ids=tuple(marker_ids),
            )
        )
    return documents, locations
