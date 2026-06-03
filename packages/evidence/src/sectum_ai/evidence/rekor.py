"""Sigstore Rekor transparency-log anchoring for the evidence chain (engineering spec, section 8.2).

After the run digest is timestamped (the RFC 3161 path in :mod:`sectum_ai.evidence.tsa`),
it can also be recorded in the `Sigstore Rekor <https://docs.sigstore.dev/logging/overview/>`_
transparency log. ``RekorTransparencyLog`` signs the digest and submits a
``hashedrekord`` entry; the log returns an inclusion proof that anyone can
verify offline. ``sectum-ai verify`` then proves the run digest is present in a
public, append-only log under a checkpoint signed by Rekor itself.

Trust model (the same shape as the TSA): the inclusion proof is only as
trustworthy as the log key its checkpoint is checked against. We never trust a
key carried inside the pack; the verifier pins Rekor's public keys
*independently* - the public-good instance's keys are shipped under ``_rekor/``
and selected by log id, and a ``keyring`` override accepts a private instance's
key. Verification is fully offline: recompute the RFC 6962 Merkle root from the
entry body and the proof's hashes, and check the signed checkpoint commits to
that root. No network and no current tree head are needed.

The stored proof is a small, Rekor-API-version-independent JSON object (all
byte fields base64), so a pack verifies the same whether the entry came from
Rekor v1 (hex API fields) or a v2/bundle source (base64).

``cryptography`` is the only third-party dependency, behind the
``sectum-ai-evidence[rekor]`` extra and imported lazily so the package installs
and the ``LocalTimestamper`` path runs without it.
"""

import base64
import hashlib
import json
import urllib.request
from collections.abc import Mapping
from datetime import UTC, datetime
from importlib import resources
from typing import Any
from urllib.parse import urlparse

from sectum_ai.spec import EvidenceError

_REKOR_URL = "https://rekor.sigstore.dev"
_INSTALL_HINT = "Rekor support requires the 'rekor' extra: pip install 'sectum-ai-evidence[rekor]'"


def _builtin_keyring() -> dict[str, bytes]:
    """Return the shipped Rekor public keys, keyed by log id (base64 SHA-256 of the DER key)."""
    keyring: dict[str, bytes] = {}
    anchor = resources.files("sectum_ai.evidence").joinpath("_rekor")
    for entry in anchor.iterdir():
        if entry.name.endswith(".pem"):
            pem = entry.read_bytes()
            keyring[_log_id(_der_spki(pem))] = pem
    return keyring


def _der_spki(pem: bytes) -> bytes:
    """Return the DER SubjectPublicKeyInfo bytes of a PEM public key."""
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
        load_pem_public_key,
    )

    return load_pem_public_key(pem).public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)


def _log_id(der_spki: bytes) -> str:
    """Return a Rekor log id: base64 of the SHA-256 of the DER public key."""
    return base64.b64encode(hashlib.sha256(der_spki).digest()).decode("ascii")


def rekor_keyring(*key_pems: bytes) -> dict[str, bytes]:
    """Build a keyring (log id -> PEM key) from Rekor public keys for verification.

    Use this to pin a private Rekor instance's key when calling
    :func:`verify_rekor_proof` or ``verify_pack``.
    """
    return {_log_id(_der_spki(pem)): pem for pem in key_pems}


class RekorTransparencyLog:
    """Records a run digest in a Sigstore Rekor transparency log.

    Signs the digest with an ECDSA P-256 key (ephemeral by default; pass
    ``signing_key_pem`` to pin a stable key) and submits a ``hashedrekord``
    entry, returning the inclusion proof as a JSON string for the evidence pack.
    Defaults to the public-good instance; pass ``rekor_url`` for another.
    """

    def __init__(
        self,
        signing_key_pem: bytes | None = None,
        *,
        rekor_url: str = _REKOR_URL,
        timeout: float = 30.0,
    ) -> None:
        if urlparse(rekor_url).scheme not in ("http", "https"):
            raise EvidenceError(f"rekor_url must be an http(s) URL: {rekor_url!r}")
        self._rekor_url = rekor_url.rstrip("/")
        self._signing_key_pem = signing_key_pem
        self._timeout = timeout

    @property
    def rekor_url(self) -> str:
        """The Rekor instance this log submits to."""
        return self._rekor_url

    def record(self, digest: str) -> str:
        """Record ``digest`` in the log; return the inclusion proof as JSON.

        ``digest`` is a SHA-256 hex string (the run digest). The hashedrekord
        signature is over the digest bytes, prehashed, as Rekor expects.
        """
        try:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import ec, utils
            from cryptography.hazmat.primitives.serialization import (
                Encoding,
                PublicFormat,
                load_pem_private_key,
            )
        except ModuleNotFoundError as error:
            raise EvidenceError(_INSTALL_HINT) from error

        try:
            digest_bytes = bytes.fromhex(digest)
        except ValueError as error:
            raise EvidenceError(f"the run digest is not a hex string: {digest!r}") from error
        if len(digest_bytes) != 32:
            raise EvidenceError(f"the run digest must be a 32-byte SHA-256 hex string: {digest!r}")

        if self._signing_key_pem is not None:
            key = load_pem_private_key(self._signing_key_pem, password=None)
            if not isinstance(key, ec.EllipticCurvePrivateKey):
                raise EvidenceError("the Rekor signing key must be an ECDSA (EC) private key")
        else:
            key = ec.generate_private_key(ec.SECP256R1())
        signature = key.sign(digest_bytes, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        public_pem = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
        entry = {
            "apiVersion": "0.0.1",
            "kind": "hashedrekord",
            "spec": {
                "data": {"hash": {"algorithm": "sha256", "value": digest}},
                "signature": {
                    "content": base64.b64encode(signature).decode("ascii"),
                    "publicKey": {"content": base64.b64encode(public_pem).decode("ascii")},
                },
            },
        }
        response = self._submit(entry)
        return json.dumps(_normalize_entry(response), sort_keys=True, separators=(",", ":"))

    def _submit(self, entry: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self._rekor_url}/api/v1/log/entries",
            data=json.dumps(entry).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as http_response:
                body = http_response.read()
        except OSError as error:
            raise EvidenceError(
                f"the Rekor request to {self._rekor_url} failed: {error}"
            ) from error
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as error:
            raise EvidenceError(f"Rekor returned a non-JSON response: {error}") from error
        if not isinstance(parsed, dict) or not parsed:
            raise EvidenceError("Rekor returned an empty entry set")
        # The response maps the new entry's UUID to the entry object.
        entry_object: dict[str, Any] = next(iter(parsed.values()))
        return entry_object


def _normalize_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Map a Rekor v1 API entry into the version-independent stored proof schema."""
    try:
        proof = entry["verification"]["inclusionProof"]
        return {
            "log_id": entry["logID"],
            "leaf_index": int(proof["logIndex"]),
            "tree_size": int(proof["treeSize"]),
            # the v1 API returns the root hash and proof hashes as hex; the
            # stored schema is base64 throughout.
            "root_hash": _hex_to_b64(proof["rootHash"]),
            "hashes": [_hex_to_b64(h) for h in proof["hashes"]],
            "checkpoint": proof["checkpoint"],
            "canonicalized_body": entry["body"],
            "integrated_time": int(entry["integratedTime"]),
            "entry_index": int(entry["logIndex"]),
        }
    except (KeyError, TypeError, ValueError) as error:
        raise EvidenceError(f"the Rekor entry is missing an inclusion proof: {error}") from error


def _hex_to_b64(value: str) -> str:
    return base64.b64encode(bytes.fromhex(value)).decode("ascii")


def verify_rekor_proof(
    proof_json: str,
    digest: str,
    *,
    keyring: Mapping[str, bytes] | None = None,
) -> datetime:
    """Verify a Rekor inclusion proof binds ``digest``; return the log's recorded time.

    Checks, all offline: (1) the entry body is a ``hashedrekord`` whose hash
    equals ``digest``; (2) the RFC 6962 Merkle root recomputed from the body and
    the proof hashes matches the proof's root; (3) the signed checkpoint commits
    to that same root and is signed by a pinned Rekor key selected by log id.
    ``keyring`` (log id -> PEM public key) overrides the built-in keys for a
    private instance. Raises :class:`~sectum_ai.spec.EvidenceError` on any failure.
    """
    try:
        proof = json.loads(proof_json)
    except json.JSONDecodeError as error:
        raise EvidenceError(f"the Rekor proof is not valid JSON: {error}") from error
    if not isinstance(proof, dict):
        raise EvidenceError("the Rekor proof is not a JSON object")

    keys = dict(keyring) if keyring is not None else _builtin_keyring()
    log_id = proof.get("log_id")
    # log_id must be a str: a hostile proof could carry a list/dict, which would
    # raise an unhashable-type error on the membership test below.
    if not isinstance(log_id, str) or log_id not in keys:
        raise EvidenceError(f"the Rekor log id {log_id!r} is not in the trusted keyring")

    body_b64 = proof.get("canonicalized_body", "")
    _check_digest_binding(body_b64, digest)
    root = _root_from_inclusion_proof(proof, body_b64)
    _verify_checkpoint(proof, root, keys[log_id])

    integrated = proof.get("integrated_time")
    if not isinstance(integrated, int):
        raise EvidenceError("the Rekor proof is missing an integrated time")
    return datetime.fromtimestamp(integrated, tz=UTC)


def _check_digest_binding(body_b64: str, digest: str) -> None:
    try:
        body = json.loads(base64.b64decode(body_b64))
    except ValueError as error:
        raise EvidenceError(f"the Rekor entry body is malformed: {error}") from error
    if not isinstance(body, dict) or body.get("kind") != "hashedrekord":
        kind = body.get("kind") if isinstance(body, dict) else None
        raise EvidenceError(f"unexpected Rekor entry kind: {kind!r}")
    try:
        recorded = body["spec"]["data"]["hash"]["value"]
    except (KeyError, TypeError) as error:
        raise EvidenceError(f"the Rekor entry body is malformed: {error}") from error
    if recorded != digest:
        raise EvidenceError("the Rekor entry attests a different digest; the run was altered")


def _hash_children(left: bytes, right: bytes) -> bytes:
    # RFC 6962 interior node: 0x01 || left || right.
    return hashlib.sha256(b"\x01" + left + right).digest()


def _root_from_inclusion_proof(proof: Mapping[str, Any], body_b64: str) -> bytes:
    """Recompute the Merkle tree root (RFC 6962) from the leaf and the audit path."""
    try:
        leaf_index = int(proof["leaf_index"])
        tree_size = int(proof["tree_size"])
        hashes = [base64.b64decode(h) for h in proof["hashes"]]
        leaf = hashlib.sha256(b"\x00" + base64.b64decode(body_b64)).digest()
    except (KeyError, TypeError, ValueError) as error:
        raise EvidenceError(f"the Rekor inclusion proof is malformed: {error}") from error
    if not 0 <= leaf_index < tree_size:
        raise EvidenceError("the Rekor leaf index is out of range for the tree size")
    # transparency-dev decomposition: inner nodes then right-border nodes.
    inner = (leaf_index ^ (tree_size - 1)).bit_length()
    border = bin(leaf_index >> inner).count("1")
    if len(hashes) != inner + border:
        raise EvidenceError("the Rekor inclusion proof has the wrong number of hashes")
    node = leaf
    for i in range(inner):
        if (leaf_index >> i) & 1 == 0:
            node = _hash_children(node, hashes[i])
        else:
            node = _hash_children(hashes[i], node)
    for sibling in hashes[inner:]:
        node = _hash_children(sibling, node)
    return node


def _verify_checkpoint(proof: Mapping[str, Any], root: bytes, key_pem: bytes) -> None:
    """Verify the signed checkpoint commits to ``root`` and is signed by ``key_pem``."""
    envelope = proof.get("checkpoint")
    if not isinstance(envelope, str) or "\n— " not in envelope:
        raise EvidenceError("the Rekor proof has no signed checkpoint")
    text, signatures = envelope.split("\n— ", 1)
    lines = text.split("\n")
    if len(lines) < 3:
        raise EvidenceError("the Rekor checkpoint body is malformed")
    # The checkpoint body is: origin, tree size, base64 root hash.
    if base64.b64decode(lines[2]) != root:
        raise EvidenceError(
            "the Rekor checkpoint commits to a different root; the proof was altered"
        )
    if str(proof.get("tree_size")) != lines[1]:
        raise EvidenceError("the Rekor checkpoint tree size does not match the proof")
    try:
        _, b64sig = signatures.split("\n", 1)[0].split(" ", 1)
        raw = base64.b64decode(b64sig)
    except ValueError as error:
        raise EvidenceError(f"the Rekor checkpoint signature is malformed: {error}") from error
    # The signature blob is a 4-byte key hint (SHA-256 of the DER key, truncated)
    # followed by the raw signature. Check the hint matches the pinned key first -
    # a cheap early reject before the signature verification.
    if raw[:4] != hashlib.sha256(_der_spki(key_pem)).digest()[:4]:
        raise EvidenceError("the Rekor checkpoint key hint does not match the pinned key")
    _verify_signature(key_pem, raw[4:], text.encode("utf-8"))


def _verify_signature(key_pem: bytes, signature: bytes, message: bytes) -> None:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
    except ModuleNotFoundError as error:
        raise EvidenceError(_INSTALL_HINT) from error

    key = load_pem_public_key(key_pem)
    try:
        if isinstance(key, ec.EllipticCurvePublicKey):
            key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
        elif isinstance(key, Ed25519PublicKey):
            key.verify(signature, message)
        else:
            raise EvidenceError(f"unsupported Rekor key type: {type(key).__name__}")
    except InvalidSignature as error:
        raise EvidenceError("the Rekor checkpoint signature is invalid") from error
