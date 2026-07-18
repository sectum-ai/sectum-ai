"""Tests for the Sigstore Rekor transparency-log path (engineering spec, section 8.2).

The offline tests verify a committed, real Rekor inclusion proof (captured from
the Sigstore staging log) against its log key, so CI needs no network. The
round-trip against a live Rekor instance is opt-in (set ``SECTUM_RUN_LIVE_REKOR``).
"""

import base64
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from sectum_ai.evidence import (
    RekorTransparencyLog,
    build_evidence_pack,
    rekor_keyring,
    verify_pack,
    verify_rekor_proof,
)
from sectum_ai.evidence.rekor import (
    _builtin_keyring,
    _hash_children,
    _root_from_inclusion_proof,
)
from sectum_ai.spec import (
    EvidenceError,
    GroundTruthManifest,
    RunMetrics,
    RunResult,
    canonical_hash,
)

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_PROOF = (_FIXTURES / "rekor-staging-proof.json").read_text()
_STAGING_KEY = (_FIXTURES / "rekor-staging-key.pem").read_bytes()
# The staging entry was logged over exactly this digest.
_FIXTURE_DIGEST = "5e6ae9de58c1177bea615b4fcbfb2fd688e8c4b51c2e56b6a38e817833ec24a2"
_STAGING_KEYRING = rekor_keyring(_STAGING_KEY)


def _manifest() -> GroundTruthManifest:
    return GroundTruthManifest(manifest_id="m-1", scenario_hash="scenario-hash", markers=())


def _run_result(manifest: GroundTruthManifest) -> RunResult:
    moment = datetime(2026, 5, 21, 12, 0, tzinfo=UTC)
    return RunResult(
        run_id="run-1",
        scenario_hash="scenario-hash",
        manifest_hash=canonical_hash(manifest),
        started_at=moment,
        finished_at=moment,
        findings=(),
        metrics=RunMetrics(),
    )


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _v1_api_entry() -> dict[str, Any]:
    """The committed proof reshaped as a Rekor v1 API entry (hex hashes)."""
    proof = json.loads(_PROOF)

    def to_hex(b64: str) -> str:
        return base64.b64decode(b64).hex()

    return {
        "logID": proof["log_id"],
        "logIndex": proof["entry_index"],
        "integratedTime": proof["integrated_time"],
        "body": proof["canonicalized_body"],
        "verification": {
            "inclusionProof": {
                "logIndex": proof["leaf_index"],
                "treeSize": proof["tree_size"],
                "rootHash": to_hex(proof["root_hash"]),
                "hashes": [to_hex(h) for h in proof["hashes"]],
                "checkpoint": proof["checkpoint"],
            }
        },
    }


def _leaf(data: bytes) -> bytes:
    # RFC 6962 leaf hash: 0x00 || data.
    return hashlib.sha256(b"\x00" + data).digest()


def test_inclusion_proof_recomputes_root_for_a_non_rightmost_leaf() -> None:
    # The committed staging fixture is a rightmost leaf (leaf_index == tree_size-1),
    # so inner == 0 and the audit-path inner loop never runs. Build a 5-leaf RFC-6962
    # tree and prove leaf_index=2: inner == 3, so the loop runs and exercises BOTH a
    # right-sibling step (bit 0) and a left-sibling step (bit 1) - the branch the
    # only committed fixture leaves dead.
    data = [f"leaf-{i}".encode() for i in range(5)]
    leaves = [_leaf(d) for d in data]
    a = _hash_children(leaves[0], leaves[1])
    b = _hash_children(leaves[2], leaves[3])
    root = _hash_children(_hash_children(a, b), leaves[4])
    proof = {
        "leaf_index": 2,
        "tree_size": 5,
        "hashes": [base64.b64encode(h).decode() for h in (leaves[3], a, leaves[4])],
    }
    body_b64 = base64.b64encode(data[2]).decode()
    assert _root_from_inclusion_proof(proof, body_b64) == root


def test_inclusion_proof_rejects_a_swapped_sibling() -> None:
    # Swapping two audit-path siblings recomputes a different root, so the
    # checkpoint-root comparison rejects the tampered proof.
    data = [f"leaf-{i}".encode() for i in range(5)]
    leaves = [_leaf(d) for d in data]
    a = _hash_children(leaves[0], leaves[1])
    b = _hash_children(leaves[2], leaves[3])
    root = _hash_children(_hash_children(a, b), leaves[4])
    tampered = {
        "leaf_index": 2,
        "tree_size": 5,
        # L3 and A swapped (wrong order at the first two levels).
        "hashes": [base64.b64encode(h).decode() for h in (a, leaves[3], leaves[4])],
    }
    body_b64 = base64.b64encode(data[2]).decode()
    assert _root_from_inclusion_proof(tampered, body_b64) != root


def test_a_real_inclusion_proof_verifies_offline() -> None:
    integrated = verify_rekor_proof(_PROOF, _FIXTURE_DIGEST, keyring=_STAGING_KEYRING)
    assert integrated.tzinfo is not None
    assert integrated.year == 2024


def test_a_proof_for_a_different_digest_is_rejected() -> None:
    with pytest.raises(EvidenceError, match="different digest"):
        verify_rekor_proof(_PROOF, "0" * 64, keyring=_STAGING_KEYRING)


def test_a_staging_entry_is_rejected_by_the_builtin_production_keyring() -> None:
    # The shipped keyring holds only production keys, so a staging entry's log id
    # is unknown - the verifier refuses to trust a key it has not pinned.
    with pytest.raises(EvidenceError, match="not in the trusted keyring"):
        verify_rekor_proof(_PROOF, _FIXTURE_DIGEST)


def test_a_tampered_checkpoint_root_is_rejected() -> None:
    proof = json.loads(_PROOF)
    lines = proof["checkpoint"].split("\n")
    lines[2] = base64.b64encode(b"\x11" * 32).decode()  # swap the committed root
    proof["checkpoint"] = "\n".join(lines)
    with pytest.raises(EvidenceError):
        verify_rekor_proof(json.dumps(proof), _FIXTURE_DIGEST, keyring=_STAGING_KEYRING)


def test_a_tampered_merkle_hash_is_rejected() -> None:
    proof = json.loads(_PROOF)
    proof["hashes"][0] = base64.b64encode(b"\x22" * 32).decode()
    with pytest.raises(EvidenceError):
        verify_rekor_proof(json.dumps(proof), _FIXTURE_DIGEST, keyring=_STAGING_KEYRING)


def test_a_garbage_proof_is_rejected_not_crashed() -> None:
    with pytest.raises(EvidenceError, match="not valid JSON"):
        verify_rekor_proof("not-json", _FIXTURE_DIGEST, keyring=_STAGING_KEYRING)


def test_a_non_string_log_id_is_rejected_not_crashed() -> None:
    # A hostile proof could carry a list/dict log id; the membership test must
    # not raise an unhashable-type error.
    proof = json.loads(_PROOF)
    proof["log_id"] = ["not", "a", "string"]
    with pytest.raises(EvidenceError, match="not in the trusted keyring"):
        verify_rekor_proof(json.dumps(proof), _FIXTURE_DIGEST, keyring=_STAGING_KEYRING)


def test_a_tampered_checkpoint_keyhint_is_rejected() -> None:
    # Corrupt only the 4-byte key hint, leaving the raw signature intact: the
    # key-hint check must reject it before signature verification.
    proof = json.loads(_PROOF)
    text, signatures = proof["checkpoint"].split("\n— ", 1)
    name, b64sig = signatures.split("\n", 1)[0].split(" ", 1)
    raw = bytearray(base64.b64decode(b64sig))
    raw[0] ^= 0xFF
    new_sig_line = f"{name} {base64.b64encode(bytes(raw)).decode()}"
    proof["checkpoint"] = f"{text}\n— {new_sig_line}\n"
    with pytest.raises(EvidenceError, match="key hint"):
        verify_rekor_proof(json.dumps(proof), _FIXTURE_DIGEST, keyring=_STAGING_KEYRING)


def test_record_rejects_a_digest_that_is_not_a_sha256() -> None:
    with pytest.raises(EvidenceError, match="32-byte SHA-256"):
        RekorTransparencyLog(rekor_url="https://rekor.example").record("abcd")


def test_the_builtin_keyring_holds_the_production_rekor_keys() -> None:
    keyring = _builtin_keyring()
    assert len(keyring) == 2
    assert all(pem.startswith(b"-----BEGIN PUBLIC KEY-----") for pem in keyring.values())


def test_the_builtin_keyring_is_keyed_by_rekor_hex_log_id() -> None:
    # Regression: Rekor's API logID - which _normalize_entry stores verbatim as the
    # proof's log_id - is the HEX SHA-256 of the log key. The keyring must key by
    # that same hex, or a real inclusion proof never matches (keying by base64 was
    # the bug that made every --rekor-anchored pack fail verification even with the
    # correct key shipped). The public-good Rekor instance's well-known log id must
    # be trusted out of the box.
    keyring = _builtin_keyring()
    assert "c0d23d6ad406973f9559f3ba2d1ca01f84147d8ffc5b8445c224f98b9591801d" in keyring
    assert all(len(log_id) == 64 and set(log_id) <= set("0123456789abcdef") for log_id in keyring)


def test_the_transparency_log_rejects_a_non_http_url() -> None:
    with pytest.raises(EvidenceError, match="http"):
        RekorTransparencyLog(rekor_url="ftp://rekor.example")


def test_record_posts_a_valid_hashedrekord_and_normalizes_the_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:
        captured["url"] = request.full_url
        captured["entry"] = json.loads(request.data)
        return _FakeResponse(json.dumps({"some-uuid": _v1_api_entry()}).encode())

    monkeypatch.setattr("sectum_ai.evidence.rekor.urllib.request.urlopen", fake_urlopen)
    proof_json = RekorTransparencyLog(rekor_url="https://rekor.example").record(_FIXTURE_DIGEST)

    # The submitted entry is a hashedrekord whose hash binds our digest, signed
    # over the digest bytes (prehashed) - the way Rekor validates a hashedrekord.
    entry = captured["entry"]
    assert captured["url"] == "https://rekor.example/api/v1/log/entries"
    assert entry["kind"] == "hashedrekord"
    assert entry["spec"]["data"]["hash"]["value"] == _FIXTURE_DIGEST
    _assert_prehashed_signature(entry, _FIXTURE_DIGEST)

    # The normalized proof verifies offline against the (staging) log key.
    integrated = verify_rekor_proof(proof_json, _FIXTURE_DIGEST, keyring=_STAGING_KEYRING)
    assert integrated.year == 2024


def test_record_wraps_a_network_failure_as_an_evidence_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(request: Any, timeout: float) -> _FakeResponse:
        raise OSError("connection refused")

    monkeypatch.setattr("sectum_ai.evidence.rekor.urllib.request.urlopen", boom)
    with pytest.raises(EvidenceError, match="Rekor request"):
        RekorTransparencyLog(rekor_url="https://rekor.example").record(_FIXTURE_DIGEST)


def test_verify_pack_checks_a_rekor_proof(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _manifest()
    pack = build_evidence_pack(_run_result(manifest), manifest)
    # Pin the recomputed digest to the fixture's; give the pack a local timestamp
    # token over that same digest so only the Rekor path is under test here.
    local_token = json.dumps({"tsa": "local-dev", "digest": _FIXTURE_DIGEST})
    rekor_pack = pack.model_copy(update={"rekor_proof": _PROOF, "tsa_token": local_token})
    monkeypatch.setattr("sectum_ai.evidence.verify.attested_digest", lambda _run: _FIXTURE_DIGEST)
    result = verify_pack(rekor_pack, manifest, rekor_keyring=_STAGING_KEYRING)
    rekor_check = next(check for check in result.checks if check.name == "rekor-inclusion")
    assert rekor_check.ok
    assert result.passed


def test_require_anchored_is_satisfied_by_a_rekor_proof_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The Rekor arm of verify.py's "a real RFC 3161 timestamp OR a Rekor inclusion proof"
    # contract. A pack with only a local-dev timestamp but a valid Rekor proof is genuinely
    # anchored, so require_anchored - the `verify` default - must accept it. This is the
    # symmetric case to the TSA-only test in test_tsa.py; the test above never gates on
    # require_anchored, so nothing pins that a Rekor proof alone suffices (dropping the
    # disjunct would reject a `report --rekor` pack with exit 4).
    manifest = _manifest()
    pack = build_evidence_pack(_run_result(manifest), manifest)
    local_token = json.dumps({"tsa": "local-dev", "digest": _FIXTURE_DIGEST})
    rekor_pack = pack.model_copy(update={"rekor_proof": _PROOF, "tsa_token": local_token})
    monkeypatch.setattr("sectum_ai.evidence.verify.attested_digest", lambda _run: _FIXTURE_DIGEST)
    result = verify_pack(
        rekor_pack, manifest, rekor_keyring=_STAGING_KEYRING, require_anchored=True
    )
    assert result.anchored
    assert result.passed, [check.detail for check in result.checks if not check.ok]


def test_verify_pack_fails_a_rekor_proof_when_the_digest_was_altered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest()
    pack = build_evidence_pack(_run_result(manifest), manifest)
    rekor_pack = pack.model_copy(update={"rekor_proof": _PROOF})
    monkeypatch.setattr("sectum_ai.evidence.verify.attested_digest", lambda _run: "f" * 64)
    assert not verify_pack(rekor_pack, manifest, rekor_keyring=_STAGING_KEYRING).passed


def _assert_prehashed_signature(entry: dict[str, Any], digest: str) -> None:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, utils
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    sig = base64.b64decode(entry["spec"]["signature"]["content"])
    pem = base64.b64decode(entry["spec"]["signature"]["publicKey"]["content"])
    key = load_pem_public_key(pem)
    assert isinstance(key, ec.EllipticCurvePublicKey)
    key.verify(sig, bytes.fromhex(digest), ec.ECDSA(utils.Prehashed(hashes.SHA256())))


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("SECTUM_RUN_LIVE_REKOR"),
    reason="set SECTUM_RUN_LIVE_REKOR=1 to round-trip against the live Rekor instance",
)
def test_live_rekor_round_trip() -> None:
    manifest = _manifest()
    pack = build_evidence_pack(
        _run_result(manifest), manifest, transparency_log=RekorTransparencyLog()
    )
    result = verify_pack(pack, manifest)
    assert result.passed, [check.detail for check in result.checks if not check.ok]
