"""Generation of the three canary marker types (the engineering spec, section 6.3).

- HARD_CANARY: a high-entropy branded token, detected by exact match.
- ENTITY_CANARY: a fabricated, single-tenant-unique entity, detected
  semantically; this is the organic-bleed bait.
- SECRET_CANARY: a fake but plausibly shaped secret, detected by exact match.

Secret canaries are generated at runtime from the seed and are never committed
to source, so they cannot be mistaken for real credentials.
"""

import base64
import random
from uuid import UUID

from sectum.spec import Marker, MarkerType

_HARD_PREFIX = "SECTUM-CANARY-"
_SECRET_PREFIX = "SECTUM-SECRET-"
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


def _b32(rng: random.Random, num_bytes: int) -> str:
    return base64.b32encode(rng.randbytes(num_bytes)).decode("ascii").rstrip("=")


def _hard_plaintext(rng: random.Random) -> str:
    return _HARD_PREFIX + _b32(rng, 16)


def _secret_plaintext(rng: random.Random) -> str:
    return _SECRET_PREFIX + _b32(rng, 20)


def _entity_plaintext(rng: random.Random, sequence: int) -> str:
    return f"Project {rng.choice(_MARKER_CODENAMES)}-{sequence:05d}"


def generate_markers(tenant_id: UUID, rng: random.Random, start_sequence: int) -> list[Marker]:
    """Generate this tenant's markers, without planted locations.

    Planted locations are filled in later by corpus generation. ``start_sequence``
    keeps marker identifiers and entity codenames globally unique.
    """
    markers: list[Marker] = []
    sequence = start_sequence
    for marker_type in (MarkerType.HARD_CANARY, MarkerType.ENTITY_CANARY, MarkerType.SECRET_CANARY):
        for _ in range(MARKERS_PER_TYPE):
            if marker_type is MarkerType.HARD_CANARY:
                plaintext = _hard_plaintext(rng)
            elif marker_type is MarkerType.SECRET_CANARY:
                plaintext = _secret_plaintext(rng)
            else:
                plaintext = _entity_plaintext(rng, sequence)
            markers.append(
                Marker(
                    marker_id=f"mkr-{sequence:05d}",
                    marker_type=marker_type,
                    owner_tenant_id=tenant_id,
                    plaintext=plaintext,
                )
            )
            sequence += 1
    return markers
