"""At-rest encryption for the seeded substrate (the engineering spec, section 17).

The seeded substrate holds the ground-truth manifest - the canary plaintexts and
which tenant owns each - and those same plaintexts are planted in the document
corpus. The threat model treats this as sensitive, so when a key is configured
the substrate is sealed before it touches disk and opened on load. This is the
"encryption at rest" the spec calls for, leaning to always-on for BYOC runs.

The sealed form is AES-256-GCM: a fixed magic header (also the authenticated
associated data), a random 96-bit nonce, then the ciphertext-and-tag. Any edit
to the file - including the header - fails authentication on open. The key is
never inlined in config; it is referenced by environment variable (a base64
32-byte key) and resolved at run time.

``cryptography`` is the only dependency, behind the ``sectum-ai[encryption]``
extra and imported lazily so the unencrypted path needs nothing extra.
"""

import base64
import os
from typing import TYPE_CHECKING

from sectum_ai.spec import ConfigError

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_MAGIC = b"SECTUM-SUBSTRATE-v1"
_NONCE_BYTES = 12
_KEY_BYTES = 32
_INSTALL_HINT = (
    "at-rest encryption requires the 'encryption' extra: pip install 'sectum-ai[encryption]'"
)


def load_key_from_env(env_var: str) -> bytes:
    """Resolve a base64-encoded 32-byte AES-256 key from ``env_var``.

    Raises :class:`~sectum_ai.spec.ConfigError` if the variable is unset or does not
    decode to exactly 32 bytes.
    """
    raw = os.environ.get(env_var)
    if not raw:
        raise ConfigError(f"the manifest encryption key env var {env_var!r} is not set")
    try:
        # b64decode raises binascii.Error (a ValueError subclass) on bad input.
        key = base64.b64decode(raw, validate=True)
    except ValueError as error:
        raise ConfigError(
            f"the manifest encryption key in {env_var!r} is not valid base64"
        ) from error
    if len(key) != _KEY_BYTES:
        raise ConfigError(
            f"the manifest encryption key in {env_var!r} must be {_KEY_BYTES} bytes, got {len(key)}"
        )
    return key


def seal_bytes(plaintext: bytes, key: bytes) -> bytes:
    """Seal ``plaintext`` under ``key`` (AES-256-GCM); return the sealed blob."""
    aesgcm = _aesgcm(key)
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = aesgcm.encrypt(nonce, plaintext, _MAGIC)
    return _MAGIC + nonce + ciphertext


def unseal_bytes(blob: bytes, key: bytes) -> bytes:
    """Open a blob produced by :func:`seal_bytes`; return the plaintext.

    Raises :class:`~sectum_ai.spec.ConfigError` if the blob is not in sealed form or
    fails authentication (a wrong key or any tampering).
    """
    header = blob[: len(_MAGIC)]
    if header != _MAGIC:
        raise ConfigError("the substrate is not in sealed form (bad magic header)")
    if len(blob) < len(_MAGIC) + _NONCE_BYTES:
        raise ConfigError("the sealed substrate is truncated")
    # _aesgcm first: it raises the typed install hint if cryptography is absent,
    # so importing InvalidTag below is safe.
    aesgcm = _aesgcm(key)
    from cryptography.exceptions import InvalidTag

    nonce = blob[len(_MAGIC) : len(_MAGIC) + _NONCE_BYTES]
    ciphertext = blob[len(_MAGIC) + _NONCE_BYTES :]
    try:
        return aesgcm.decrypt(nonce, ciphertext, _MAGIC)
    except (InvalidTag, ValueError) as error:
        raise ConfigError(
            "the sealed substrate failed authentication: wrong key or it was tampered with"
        ) from error


def _aesgcm(key: bytes) -> "AESGCM":
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as error:
        # ImportError (not just ModuleNotFoundError) also covers a broken backend
        # of this compiled dependency, not only an absent package.
        raise ConfigError(_INSTALL_HINT) from error
    if len(key) != _KEY_BYTES:
        raise ConfigError(f"the encryption key must be {_KEY_BYTES} bytes, got {len(key)}")
    return AESGCM(key)
