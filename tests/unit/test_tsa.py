"""Tests for the RFC 3161 trusted-timestamping path (engineering spec, section 8.2).

The offline tests verify a committed FreeTSA token captured over a known digest,
so CI needs no network. The round-trip against a live TSA is opt-in (set
``SECTUM_RUN_LIVE_TSA=1``) because it requires reaching freetsa.org.
"""

import base64
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sectum_ai.evidence import (
    Rfc3161Timestamper,
    build_evidence_pack,
    verify_pack,
    verify_rfc3161_token,
)
from sectum_ai.evidence.tsa import _builtin_cert
from sectum_ai.spec import (
    EvidenceError,
    GroundTruthManifest,
    RunMetrics,
    RunResult,
    canonical_hash,
)

# The committed fixture token was issued by FreeTSA over exactly this digest.
_FIXTURE_DIGEST = "01f4946f829f3db987218dadbfeaebfa833ea9fe98481a083c15c56dadb40b02"
_FIXTURE_TOKEN = (
    (Path(__file__).resolve().parents[1] / "fixtures" / "freetsa-token.b64").read_text().strip()
)


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
    """A stand-in for the urlopen context manager carrying a fixed body."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_timestamp_posts_a_query_and_returns_the_base64_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_token = base64.b64decode(_FIXTURE_TOKEN)
    captured: dict[str, object] = {}

    def fake_urlopen(request: object, timeout: float) -> _FakeResponse:
        captured["url"] = request.full_url  # type: ignore[attr-defined]
        captured["data"] = request.data  # type: ignore[attr-defined]
        return _FakeResponse(raw_token)

    monkeypatch.setattr("sectum_ai.evidence.tsa.urllib.request.urlopen", fake_urlopen)
    token = Rfc3161Timestamper("https://tsa.example/tsr").timestamp("a" * 64)
    assert base64.b64decode(token) == raw_token
    assert captured["url"] == "https://tsa.example/tsr"
    assert captured["data"]  # a DER timestamp-query body was sent


def test_timestamp_wraps_a_network_failure_as_an_evidence_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(request: object, timeout: float) -> _FakeResponse:
        raise OSError("connection refused")

    monkeypatch.setattr("sectum_ai.evidence.tsa.urllib.request.urlopen", boom)
    with pytest.raises(EvidenceError, match="TSA request"):
        Rfc3161Timestamper("https://tsa.example/tsr").timestamp("a" * 64)


def test_a_committed_freetsa_token_verifies_over_its_digest() -> None:
    gen_time = verify_rfc3161_token(_FIXTURE_TOKEN, _FIXTURE_DIGEST)
    assert gen_time.tzinfo is not None
    assert gen_time.year == 2026


def test_a_token_over_a_different_digest_is_rejected() -> None:
    with pytest.raises(EvidenceError, match="does not attest this digest"):
        verify_rfc3161_token(_FIXTURE_TOKEN, "0" * 64)


def test_a_garbage_token_is_rejected_not_crashed() -> None:
    with pytest.raises(EvidenceError, match="not a decodable response"):
        verify_rfc3161_token("not-a-real-token", _FIXTURE_DIGEST)


# A TimeStampResp that decodes at the outer layer (status granted) but carries no
# timeStampToken: the internal fields are parsed lazily and would raise a bare
# ValueError if not guarded. DER: SEQUENCE { PKIStatusInfo { status granted } }.
_DECODABLE_BUT_MALFORMED = base64.b64encode(bytes.fromhex("30053003020100")).decode()


def test_a_decodable_but_internally_malformed_token_is_a_typed_error() -> None:
    with pytest.raises(EvidenceError):
        verify_rfc3161_token(_DECODABLE_BUT_MALFORMED, _FIXTURE_DIGEST)


def test_check_token_returns_a_failing_check_for_a_malformed_token() -> None:
    # The verify.py routing must turn a malformed RFC 3161 token into a failing
    # check, never an uncaught exception - and a malformed token is no anchor.
    from sectum_ai.evidence.verify import _check_token

    check, anchored = _check_token(_DECODABLE_BUT_MALFORMED, _FIXTURE_DIGEST)
    assert not check.ok
    assert not anchored


def test_a_token_verified_against_the_wrong_root_is_rejected() -> None:
    # The security claim: a token only verifies against its own pinned root. Using
    # an unrelated certificate as the root must fail closed (here the FreeTSA leaf,
    # which is not the issuing root, stands in for an attacker-chosen anchor).
    with pytest.raises(EvidenceError):
        verify_rfc3161_token(
            _FIXTURE_TOKEN, _FIXTURE_DIGEST, tsa_root=_builtin_cert("freetsa-tsa.pem")
        )


def test_an_invalid_override_certificate_is_rejected() -> None:
    with pytest.raises(EvidenceError, match="not valid PEM"):
        verify_rfc3161_token(_FIXTURE_TOKEN, _FIXTURE_DIGEST, tsa_certificate=b"not a cert")


def test_the_builtin_certs_are_shipped_certificates() -> None:
    assert _builtin_cert("freetsa-tsa.pem").startswith(b"-----BEGIN CERTIFICATE-----")
    assert _builtin_cert("freetsa-root.pem").startswith(b"-----BEGIN CERTIFICATE-----")


def test_the_timestamper_rejects_a_non_http_url() -> None:
    with pytest.raises(EvidenceError, match="http"):
        Rfc3161Timestamper("ftp://tsa.example")


def test_the_timestamper_exposes_its_tsa_endpoint() -> None:
    assert Rfc3161Timestamper("https://tsa.example/tsr").tsa == "https://tsa.example/tsr"


def test_verify_pack_routes_an_rfc3161_token_through_the_tsa_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A pack carrying an RFC 3161 token (not the local JSON token) must verify via
    # the TSA path. Pin the recomputed digest to the fixture's digest so the
    # committed token attests it.
    manifest = _manifest()
    pack = build_evidence_pack(_run_result(manifest), manifest)
    rfc_pack = pack.model_copy(update={"tsa_token": _FIXTURE_TOKEN})
    monkeypatch.setattr("sectum_ai.evidence.verify.attested_digest", lambda _run: _FIXTURE_DIGEST)
    result = verify_pack(rfc_pack, manifest)
    token_check = next(check for check in result.checks if check.name == "timestamp-token")
    assert token_check.ok
    assert "RFC 3161 TSA" in token_check.detail
    assert result.passed


def test_require_anchored_is_satisfied_by_a_single_rfc3161_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # verify.py's contract is "a real RFC 3161 timestamp OR a Rekor inclusion proof". A pack
    # carrying just a valid TSA token (no Rekor) is genuinely anchored, so require_anchored -
    # the `verify` command's default - must accept it. The routing test above never gates on
    # require_anchored, so nothing pins that one real anchor suffices; requiring BOTH would
    # reject a standard `report --tsa` pack (exit 4).
    manifest = _manifest()
    pack = build_evidence_pack(_run_result(manifest), manifest)
    rfc_pack = pack.model_copy(update={"tsa_token": _FIXTURE_TOKEN})
    monkeypatch.setattr("sectum_ai.evidence.verify.attested_digest", lambda _run: _FIXTURE_DIGEST)
    result = verify_pack(rfc_pack, manifest, require_anchored=True)
    assert result.passed, [check.detail for check in result.checks if not check.ok]
    assert not any(check.name == "independent-anchor" and not check.ok for check in result.checks)


def test_verify_pack_fails_an_rfc3161_token_when_the_digest_was_altered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest()
    pack = build_evidence_pack(_run_result(manifest), manifest)
    rfc_pack = pack.model_copy(update={"tsa_token": _FIXTURE_TOKEN})
    monkeypatch.setattr("sectum_ai.evidence.verify.attested_digest", lambda _run: "f" * 64)
    result = verify_pack(rfc_pack, manifest)
    assert not result.passed


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("SECTUM_RUN_LIVE_TSA"),
    reason="set SECTUM_RUN_LIVE_TSA=1 to round-trip against the live FreeTSA endpoint",
)
def test_live_freetsa_round_trip() -> None:
    manifest = _manifest()
    pack = build_evidence_pack(_run_result(manifest), manifest, timestamper=Rfc3161Timestamper())
    result = verify_pack(pack, manifest)
    assert result.passed, [check.detail for check in result.checks if not check.ok]
