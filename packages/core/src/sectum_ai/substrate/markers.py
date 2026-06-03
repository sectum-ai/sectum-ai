"""Generation of the three canary marker types (the engineering spec, section 6.3).

- HARD_CANARY: a high-entropy branded token, detected by exact match.
- ENTITY_CANARY: a fabricated, single-tenant-unique entity, detected
  semantically; this is the organic-bleed bait.
- SECRET_CANARY: a fake but plausibly shaped secret, detected by an exact +
  credential-format pass (the spec, section 6.4; ``sectum_ai.probes.detection``).

Secret canaries are realistic in *shape* (an OpenAI-style ``sk-`` key, an AWS
access-key id, a US SSN whose 9xx area the SSA never issues) but are generated at
runtime from the seed and never committed to source - only the manifest *hash*
is published - so they can never be, or be mistaken for, a live credential.
"""

import base64
import random
import string
from collections.abc import Callable
from uuid import UUID

from sectum_ai.spec import Marker, MarkerType, SyntheticUserSpec

_HARD_PREFIX = "SECTUM-CANARY-"
_MARKER_CODENAMES: tuple[str, ...] = (
    "Quasar",
    "Lodestar",
    "Halcyon",
    "Meridian",
    "Onyx",
    "Zephyr",
    "Garnet",
    "Pinnacle",
)

# Two markers of each type per tenant.
MARKERS_PER_TYPE = 2
MARKERS_PER_TENANT = MARKERS_PER_TYPE * len(MarkerType)

# Secret-canary alphabets: ``sk-`` keys are mixed-case alphanumerics; AWS
# access-key ids are upper-case alphanumerics.
_SECRET_ALNUM = string.ascii_letters + string.digits
_SECRET_UPPER = string.ascii_uppercase + string.digits


def _b32(rng: random.Random, num_bytes: int) -> str:
    return base64.b32encode(rng.randbytes(num_bytes)).decode("ascii").rstrip("=")


def _hard_plaintext(rng: random.Random) -> str:
    return _HARD_PREFIX + _b32(rng, 16)


def _secret_openai(rng: random.Random) -> str:
    """An OpenAI-style ``sk-`` API key of random (non-issuable) characters."""
    return "sk-" + "".join(rng.choices(_SECRET_ALNUM, k=48))


def _secret_aws(rng: random.Random) -> str:
    """An AWS access-key id shape (``AKIA`` + 16) of random characters."""
    return "AKIA" + "".join(rng.choices(_SECRET_UPPER, k=16))


def _secret_ssn(rng: random.Random) -> str:
    """A US SSN *shape* whose 9xx area number the SSA never issues (non-issuable)."""
    return f"9{rng.randint(0, 99):02d}-{rng.randint(0, 99):02d}-{rng.randint(0, 9999):04d}"


# The three realistic secret shapes, cycled across tenants so the default
# four-tenant scenario exercises every credential format and its format detector.
_SECRET_SHAPES: tuple[Callable[[random.Random], str], ...] = (
    _secret_openai,
    _secret_aws,
    _secret_ssn,
)


def _entity_plaintext(rng: random.Random, sequence: int) -> str:
    return f"Project {rng.choice(_MARKER_CODENAMES)}-{sequence:05d}"


def generate_markers(
    tenant_id: UUID,
    rng: random.Random,
    start_sequence: int,
    users: tuple[SyntheticUserSpec, ...] = (),
) -> list[Marker]:
    """Generate this tenant's markers, without planted locations.

    Planted locations are filled in later by corpus generation. ``start_sequence``
    keeps marker identifiers and entity codenames globally unique, and selects the
    rotating secret-canary shape so the four-tenant default covers every shape.

    When ``users`` is non-empty the markers are distributed across them in
    round-robin order, so each marker is owned by a specific user within the
    tenant (ADR-0006); otherwise every marker is tenant-level
    (``owner_user_id is None``).
    """
    markers: list[Marker] = []
    sequence = start_sequence
    tenant_ordinal = start_sequence // MARKERS_PER_TENANT
    for marker_type in (MarkerType.HARD_CANARY, MarkerType.ENTITY_CANARY, MarkerType.SECRET_CANARY):
        for local_index in range(MARKERS_PER_TYPE):
            if marker_type is MarkerType.HARD_CANARY:
                plaintext = _hard_plaintext(rng)
            elif marker_type is MarkerType.SECRET_CANARY:
                # Offset the shape by the tenant so all three shapes appear across
                # the default four-tenant scenario, not just the first two.
                shape = _SECRET_SHAPES[(tenant_ordinal + local_index) % len(_SECRET_SHAPES)]
                plaintext = shape(rng)
            else:
                plaintext = _entity_plaintext(rng, sequence)
            owner_user_id = users[len(markers) % len(users)].user_id if users else None
            markers.append(
                Marker(
                    marker_id=f"mkr-{sequence:05d}",
                    marker_type=marker_type,
                    owner_tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                    plaintext=plaintext,
                )
            )
            sequence += 1
    return markers
