"""Deterministic randomness and identifiers for the substrate (ADR-0003).

Every value the substrate produces is a pure function of the scenario seed. No
wall-clock time and no process-randomized hashing are used, so the same seed
always yields a byte-identical substrate (the engineering spec, section 6.5).
"""

import hashlib
import random
import uuid

# Fixed namespace for deterministic UUID5 generation of substrate identifiers.
_NAMESPACE = uuid.UUID("5ec00000-0000-5000-8000-000000000000")


def derive_seed(base: int, *parts: str | int) -> int:
    """Derive a stable 64-bit integer seed from a base seed and string parts."""
    key = ":".join([str(base), *(str(part) for part in parts)])
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def derive_rng(base: int, *parts: str | int) -> random.Random:
    """Return a ``random.Random`` seeded deterministically from base and parts."""
    return random.Random(derive_seed(base, *parts))


def derive_uuid(*parts: str | int) -> uuid.UUID:
    """Return a deterministic UUID5 derived from the given parts.

    The engineering spec, section 6.1 specifies UUIDv7 for tenant IDs, but UUIDv7 embeds a
    wall-clock timestamp and so cannot satisfy the reproducibility contract.
    Substrate identifiers are therefore derived deterministically (ADR-0003).
    """
    name = ":".join(str(part) for part in parts)
    return uuid.uuid5(_NAMESPACE, name)
