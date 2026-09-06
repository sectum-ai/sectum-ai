"""Deterministic synthetic corpus generation (the engineering spec, section 6.2).

Corpora are templated and seeded so the same scenario always produces a
byte-identical corpus.

Each tenant owns one *pivot document* per canary marker. A pivot document names
a shared organic entity in its body and carries the marker in that same body.
Because every shared entity is covered by a pivot document in every tenant, a
benign query naming that entity retrieves the foreign tenants' pivot documents -
this is the Retrieval Pivot condition the flagship Class 2 probe reproduces (the
engineering spec, sections 4 and 7). The marker rides along in the retrieved
text, so the detection pipeline confirms the leak.

The remaining *filler documents* round out the corpus. They carry no markers;
some mention shared entities organically, which gives the substrate realistic
same-tenant retrieval competition.
"""

import random

from sectum_ai.spec import (
    ConfigError,
    CorpusDocument,
    Marker,
    PlantedLocation,
    SharedEntity,
    SyntheticTenantSpec,
)

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
# Filler-document templates. Filler documents carry no markers; some mention
# shared entities organically, which makes retrieval competition realistic.
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
# Pivot-document templates, keyed by shared-entity kind. Each names its shared
# entity in the body so a benign query for that entity retrieves the document,
# and ends with the marker so the detection pipeline confirms the leak.
_PIVOT_TEMPLATES: dict[str, str] = {
    "person": (
        "Internal {label} for the {industry} team. Primary point of contact: "
        "{entity}. Reference: {marker}."
    ),
    "vendor": (
        "Procurement {label} covering the active engagement with vendor "
        "{entity}. Reference: {marker}."
    ),
    "compliance_term": (
        "Compliance {label}: {entity} controls were reviewed for the "
        "{industry} program. Reference: {marker}."
    ),
    "amount": (
        "Finance {label}. Booked value {entity} against the {industry} "
        "account. Reference: {marker}."
    ),
    "date": (
        "Operations {label} logged on {entity} for the {industry} workstream. Reference: {marker}."
    ),
}
_GENERIC_PIVOT_TEMPLATE = (
    "Internal {label} referencing {entity} in the {industry} corpus. Reference: {marker}."
)


def _slot_values(
    tenant_spec: SyntheticTenantSpec,
    shared: dict[str, list[str]],
    rng: random.Random,
    index: int,
) -> dict[str, str]:
    """Resolve filler-template slots, mixing shared organic entities with local values."""
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


def _pivot_content(doc_type: str, entity: SharedEntity, marker: Marker, industry: str) -> str:
    """Render a pivot document's body: a shared entity plus a planted marker."""
    template = _PIVOT_TEMPLATES.get(entity.kind, _GENERIC_PIVOT_TEMPLATE)
    return template.format(
        label=doc_type.replace("_", " "),
        entity=entity.value,
        marker=marker.plaintext,
        industry=industry,
    )


def _pivot_assignments(
    markers: list[Marker], shared_entities: tuple[SharedEntity, ...], size: int
) -> dict[int, tuple[Marker, SharedEntity]]:
    """Map document indices to the (marker, shared entity) each pivot document carries.

    Markers are spread evenly across the corpus, one per shared entity in
    round-robin order.
    """
    if not shared_entities or not markers:
        # No shared entity means no pivot document, so nothing is planted in the
        # CORPUS - which is a legitimate configuration, not an error: the probes
        # that query the corpus then plan no step and their classes read
        # NOT_COVERED (rule 1), while the probes provisioned from the manifest
        # (MCP, agent, memory, cache, model) still have markers to find.
        return {}
    if size < len(markers):
        raise ConfigError(
            f"corpus_size ({size}) must be at least the markers-per-tenant count "
            f"({len(markers)}) so every marker gets its own pivot document"
        )
    assignments: dict[int, tuple[Marker, SharedEntity]] = {}
    for marker_index, marker in enumerate(markers):
        doc_index = (marker_index * size) // len(markers)
        entity = shared_entities[marker_index % len(shared_entities)]
        assignments[doc_index] = (marker, entity)
    return assignments


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
    short_id = tenant_spec.tenant_id.hex[:8]
    pivots = _pivot_assignments(markers, shared_entities, size)

    locations: dict[str, list[PlantedLocation]] = {marker.marker_id: [] for marker in markers}
    documents: list[CorpusDocument] = []

    for index in range(size):
        doc_type = _DOC_TYPES[index % len(_DOC_TYPES)]
        doc_id = f"doc-{short_id}-{index:04d}"
        title = f"{doc_type.replace('_', ' ').title()} #{index:04d}"
        metadata: dict[str, str] = {"doc_type": doc_type, "tenant": tenant_spec.display_name}

        pivot = pivots.get(index)
        if pivot is not None:
            marker, entity = pivot
            content = _pivot_content(doc_type, entity, marker, tenant_spec.industry)
            # Plant the marker in the document body, title, and metadata (the
            # engineering spec, section 6.3: "document bodies, document metadata,
            # and ... titles"). A leak is then caught whichever field surfaces,
            # and the vector store can retrieve the document by any of them.
            title = f"{title} (ref {marker.plaintext})"
            metadata["marker_ref"] = marker.plaintext
            for field in ("body", "title", "metadata"):
                locations[marker.marker_id].append(PlantedLocation(doc_id=doc_id, field=field))
            marker_ids: tuple[str, ...] = (marker.marker_id,)
            # A pivot document inherits its marker's owner user, so a user-scoped
            # store can decide who may retrieve it (ADR-0006). Filler documents
            # carry no marker and stay tenant-level (``None``).
            owner_user_id = marker.owner_user_id
        else:
            content = _TEMPLATES[doc_type].format(**_slot_values(tenant_spec, shared, rng, index))
            marker_ids = ()
            owner_user_id = None

        documents.append(
            CorpusDocument(
                doc_id=doc_id,
                tenant_id=tenant_spec.tenant_id,
                doc_type=doc_type,
                title=title,
                content=content,
                metadata=metadata,
                marker_ids=marker_ids,
                owner_user_id=owner_user_id,
            )
        )
    return documents, locations
