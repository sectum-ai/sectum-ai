"""Scenario construction for the marker substrate (the engineering spec, section 6)."""

from sectum_ai.spec import Scenario, SharedEntity
from sectum_ai.substrate.tenants import default_tenant_specs

# Organic entities deliberately shared across every tenant. These reproduce the
# Retrieval Pivot leakage conditions (the engineering spec, section 6.1).
_SHARED_ENTITIES: tuple[SharedEntity, ...] = (
    SharedEntity(kind="person", value="Maria Chen"),
    SharedEntity(kind="vendor", value="Northwind Supply Co"),
    SharedEntity(kind="compliance_term", value="SOC 2"),
    SharedEntity(kind="compliance_term", value="PCI-DSS"),
    SharedEntity(kind="amount", value="$248,500"),
    SharedEntity(kind="date", value="2026-03-14"),
)


def default_scenario(
    seed: int,
    corpus_size: int = 24,
    embedding_models: tuple[str, ...] = ("fake-deterministic",),
) -> Scenario:
    """Build the default four-tenant demo scenario with shared organic entities.

    ``embedding_models`` carries through to the Class 2 per-model sweep: two or more
    entries make ``sectum-ai probe`` record a per-model Retrieval-Pivot Rate.
    """
    return Scenario(
        scenario_id=f"sectum-ai-demo-{seed}",
        seed=seed,
        tenants=default_tenant_specs(seed, corpus_size),
        corpus_profile="demo",
        shared_entities=_SHARED_ENTITIES,
        embedding_models=embedding_models,
    )
