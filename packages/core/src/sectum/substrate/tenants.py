"""Synthetic tenant provisioning (the engineering spec, section 6.1)."""

from sectum.spec import SyntheticTenantSpec
from sectum.substrate.rng import derive_uuid

# The default scenario uses recognizable placeholder companies so demo output
# is legible (the engineering spec, section 6.1).
_DEFAULT_TENANTS: tuple[tuple[str, str], ...] = (
    ("Acme Robotics", "robotics"),
    ("Globex Logistics", "logistics"),
    ("Initech Financial", "financial services"),
    ("Hooli Health", "healthcare"),
)


def default_tenant_specs(seed: int, corpus_size: int) -> tuple[SyntheticTenantSpec, ...]:
    """Return the four default synthetic tenants (Acme, Globex, Initech, Hooli)."""
    specs: list[SyntheticTenantSpec] = []
    for index, (display_name, industry) in enumerate(_DEFAULT_TENANTS):
        specs.append(
            SyntheticTenantSpec(
                tenant_id=derive_uuid("tenant", seed, index),
                display_name=display_name,
                industry=industry,
                corpus_size=corpus_size,
            )
        )
    return tuple(specs)
