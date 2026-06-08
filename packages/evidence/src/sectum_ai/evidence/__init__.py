"""Sectum AI evidence chain: tamper-evident packs, verification, and audit packs.

This is the ``sectum_ai.evidence`` namespace package. The entire evidence layer is
open source; see docs/adr/0002-evidence-layer-oss-boundary.md.
"""

from sectum_ai.evidence.bundle import (
    EVIDENCE_MEMBER,
    MANIFEST_MEMBER,
    build_bundle,
    verify_bundle,
)
from sectum_ai.evidence.chain import (
    LocalTimestamper,
    Timestamper,
    TransparencyLog,
    attested_digest,
    build_evidence_pack,
    run_digest,
)
from sectum_ai.evidence.controls import COVERAGE_DISCLAIMER, control_mappings
from sectum_ai.evidence.dsse import (
    PAYLOAD_TYPE,
    build_dsse_envelope,
    envelope_statement,
    pae,
    verify_dsse_envelope,
)
from sectum_ai.evidence.intoto import (
    PREDICATE_TYPE,
    STATEMENT_TYPE,
    to_in_toto_statement,
    verify_in_toto_statement,
)
from sectum_ai.evidence.pdf import PdfEngine, render_audit_pack, render_audit_pack_and_hash
from sectum_ai.evidence.rekor import RekorTransparencyLog, rekor_keyring, verify_rekor_proof
from sectum_ai.evidence.sarif import SARIF_VERSION, run_to_sarif
from sectum_ai.evidence.tsa import Rfc3161Timestamper, verify_rfc3161_token
from sectum_ai.evidence.verify import Check, VerificationResult, verify_pack

__all__ = [
    "COVERAGE_DISCLAIMER",
    "EVIDENCE_MEMBER",
    "MANIFEST_MEMBER",
    "PAYLOAD_TYPE",
    "PREDICATE_TYPE",
    "SARIF_VERSION",
    "STATEMENT_TYPE",
    "Check",
    "LocalTimestamper",
    "PdfEngine",
    "RekorTransparencyLog",
    "Rfc3161Timestamper",
    "Timestamper",
    "TransparencyLog",
    "VerificationResult",
    "attested_digest",
    "build_bundle",
    "build_dsse_envelope",
    "build_evidence_pack",
    "control_mappings",
    "envelope_statement",
    "pae",
    "rekor_keyring",
    "render_audit_pack",
    "render_audit_pack_and_hash",
    "run_digest",
    "run_to_sarif",
    "to_in_toto_statement",
    "verify_bundle",
    "verify_dsse_envelope",
    "verify_in_toto_statement",
    "verify_pack",
    "verify_rekor_proof",
    "verify_rfc3161_token",
]
