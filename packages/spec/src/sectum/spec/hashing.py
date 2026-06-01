"""Canonical serialization and hashing for Sectum AI models.

Hashes are computed over a canonical JSON form (sorted keys, no insignificant
whitespace) so the same logical content always yields the same digest. This is
the foundation of the reproducibility contract (the engineering spec, section 6.5) and the
evidence chain (the engineering spec, section 8).
"""

import hashlib
import json
from typing import Any

from pydantic import BaseModel


def to_canonical_json(obj: BaseModel | dict[str, Any] | list[Any]) -> bytes:
    """Serialize an object to canonical JSON bytes: sorted keys, UTF-8, compact."""
    data: Any = obj.model_dump(mode="json") if isinstance(obj, BaseModel) else obj
    try:
        text = json.dumps(
            data,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except ValueError as error:
        # A non-finite float (NaN/Infinity) would serialize as a JavaScript
        # literal that is not valid JSON (RFC 8259): a third-party verifier
        # using a strict parser could not reproduce the digest, and every NaN
        # collapses to the same token (a non-injective canonical form). Refuse
        # it so the canonical form stays valid and injective.
        raise ValueError(f"cannot canonicalize a non-finite float: {error}") from error
    except TypeError as error:
        # A raw dict/list (a BaseModel is normalized first via
        # model_dump(mode="json")) can carry a value json cannot serialize - a
        # UUID, datetime, bytes, or a non-str key. json raises a bare TypeError;
        # surface it as a clear, typed canonicalization failure so a caller sees
        # why the digest could not be computed instead of an opaque traceback.
        raise TypeError(f"cannot canonicalize a non-JSON-native value: {error}") from error
    return text.encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """Return the hex-encoded SHA-256 digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def canonical_hash(obj: BaseModel | dict[str, Any] | list[Any]) -> str:
    """Return the SHA-256 hex digest of an object's canonical JSON form."""
    return sha256_hex(to_canonical_json(obj))
