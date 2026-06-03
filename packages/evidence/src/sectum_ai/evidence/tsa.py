"""RFC 3161 trusted timestamping for the evidence chain (engineering spec, section 8.2).

The default :class:`~sectum_ai.evidence.chain.LocalTimestamper` records a wall-clock
time with no external anchor. ``Rfc3161Timestamper`` instead submits the run
digest to an RFC 3161 Time-Stamp Authority (TSA) and stores the returned token;
``sectum-ai verify`` then checks that token against the recomputed digest, so the
timestamp is independently verifiable rather than self-asserted.

Trust model: a TSA token is only as trustworthy as the root it is checked
against. We never trust a root carried inside the pack - that would let a forged
pack ship its own trust anchor. The verifier pins a root *independently*: it
ships the FreeTSA leaf and root (public certificates of the default TSA) built
in, and accepts ``tsa_certificate``/``tsa_root`` overrides (the CLI's
``--tsa-cert``/``--tsa-root``) for a customer-pinned authority.

``rfc3161-client`` is an optional extra (``sectum-ai-evidence[rfc3161]``),
imported lazily so the package installs and the ``LocalTimestamper`` path runs
without it. CVE-2025-52556 (a token-verification bypass) was fixed in 1.0.3, so
the extra pins ``>=1.0.3``.
"""

import base64
import urllib.request
from datetime import datetime
from importlib import resources
from urllib.parse import urlparse

from sectum_ai.spec import EvidenceError

# FreeTSA is the default TSA: free, public, and RFC 3161 conformant. Its leaf and
# root are shipped under _tsa/ as the default trust anchor (both public, no secret
# material; the leaf is valid through 2040).
_FREETSA_URL = "https://freetsa.org/tsr"
_RFC3161_QUERY_TYPE = "application/timestamp-query"
_INSTALL_HINT = (
    "RFC 3161 support requires the 'rfc3161' extra: pip install 'sectum-ai-evidence[rfc3161]'"
)


def _builtin_cert(filename: str) -> bytes:
    """Return the PEM bytes of a certificate shipped under ``evidence/_tsa``."""
    return resources.files("sectum_ai.evidence").joinpath("_tsa", filename).read_bytes()


class Rfc3161Timestamper:
    """A :class:`~sectum_ai.evidence.chain.Timestamper` backed by an RFC 3161 TSA.

    Submits the SHA-256 of the run digest to the TSA and returns the DER
    timestamp response, base64-encoded so it round-trips through the evidence
    pack's JSON. Defaults to FreeTSA; pass ``tsa_url`` for a customer-pinned TSA.
    """

    anchored = True
    """A real, independent RFC 3161 anchor - recorded on the pack as
    ``anchored_with_timestamp`` so a verifier refuses a later downgrade to a
    local-dev token."""

    def __init__(self, tsa_url: str = _FREETSA_URL, *, timeout: float = 30.0) -> None:
        if urlparse(tsa_url).scheme not in ("http", "https"):
            raise EvidenceError(f"tsa_url must be an http(s) URL: {tsa_url!r}")
        self._tsa_url = tsa_url
        self._timeout = timeout

    @property
    def tsa(self) -> str:
        """The TSA endpoint this timestamper submits to."""
        return self._tsa_url

    def timestamp(self, digest: str) -> str:
        """Return a base64 RFC 3161 token attesting ``digest`` at the TSA's time."""
        try:
            from rfc3161_client import (
                HashAlgorithm,
                TimestampRequestBuilder,
                decode_timestamp_response,
            )
        except ModuleNotFoundError as error:  # pragma: no cover - exercised via verify path
            raise EvidenceError(_INSTALL_HINT) from error

        request = (
            TimestampRequestBuilder()
            .data(digest.encode("utf-8"))
            .hash_algorithm(HashAlgorithm.SHA256)
            .cert_request()
            .build()
        )
        http_request = urllib.request.Request(
            self._tsa_url,
            data=request.as_bytes(),
            method="POST",
            headers={"Content-Type": _RFC3161_QUERY_TYPE},
        )
        try:
            with urllib.request.urlopen(http_request, timeout=self._timeout) as response:
                body = response.read()
        except OSError as error:
            raise EvidenceError(f"the TSA request to {self._tsa_url} failed: {error}") from error
        token = decode_timestamp_response(body)
        # Accept only PKIStatus 0 (granted). grantedWithMods (1) also issues a
        # token, but the verifier rejects it, so storing one would yield a pack
        # that fails `sectum-ai verify`; fail fast at issue time instead.
        if int(token.status) != 0:
            detail = ", ".join(token.status_string) or "no detail"
            raise EvidenceError(
                f"the TSA did not grant the request (status {int(token.status)}): {detail}"
            )
        return base64.b64encode(body).decode("ascii")


def verify_rfc3161_token(
    token_b64: str,
    digest: str,
    *,
    tsa_certificate: bytes | None = None,
    tsa_root: bytes | None = None,
) -> datetime:
    """Verify a base64 RFC 3161 token attests ``digest``; return the TSA time.

    The token's signature is checked against the supplied TSA leaf certificate
    chained to the supplied root; both default to the built-in FreeTSA leaf and
    root. The token's message imprint must match ``digest``. Raises
    :class:`~sectum_ai.spec.EvidenceError` if the token is malformed, the chain
    does not validate, or the imprint attests a different digest.
    """
    try:
        from cryptography import x509
        from rfc3161_client import (
            VerificationError,
            VerifierBuilder,
            decode_timestamp_response,
        )
    except ModuleNotFoundError as error:
        raise EvidenceError(_INSTALL_HINT) from error

    leaf_pem = tsa_certificate if tsa_certificate is not None else _builtin_cert("freetsa-tsa.pem")
    root_pem = tsa_root if tsa_root is not None else _builtin_cert("freetsa-root.pem")
    try:
        leaf = x509.load_pem_x509_certificate(leaf_pem)
        root = x509.load_pem_x509_certificate(root_pem)
    except ValueError as error:
        raise EvidenceError(f"a supplied TSA certificate is not valid PEM: {error}") from error
    try:
        tsr = decode_timestamp_response(base64.b64decode(token_b64))
    except ValueError as error:
        raise EvidenceError(f"the RFC 3161 token is not a decodable response: {error}") from error
    verifier = VerifierBuilder().tsa_certificate(leaf).add_root_certificate(root).build()
    try:
        # A token that decodes at the outer layer but is internally malformed
        # (e.g. missing the signed data) raises a bare ValueError - from
        # verify_message or from the lazily-parsed tst_info. Guard both reads so
        # the failure is a typed EvidenceError, not an uncaught crash.
        verifier.verify_message(tsr, digest.encode("utf-8"))
        gen_time: datetime = tsr.tst_info.gen_time
    except (VerificationError, ValueError) as error:
        raise EvidenceError(f"the RFC 3161 token does not attest this digest: {error}") from error
    return gen_time
