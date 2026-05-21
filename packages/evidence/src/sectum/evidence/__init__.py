"""Sectum AI evidence chain: tamper-evident packs, verification, and audit packs.

This is the ``sectum.evidence`` namespace package. The entire evidence layer is
open source; see docs/adr/0002-evidence-layer-oss-boundary.md.
"""

from sectum.evidence.chain import (
    LocalTimestamper,
    Timestamper,
    TransparencyLog,
    build_evidence_pack,
    run_digest,
)
from sectum.evidence.controls import COVERAGE_DISCLAIMER, control_mappings
from sectum.evidence.pdf import render_audit_pack
from sectum.evidence.rekor import RekorTransparencyLog, rekor_keyring, verify_rekor_proof
from sectum.evidence.tsa import Rfc3161Timestamper, verify_rfc3161_token
from sectum.evidence.verify import Check, VerificationResult, verify_pack

__all__ = [
    "COVERAGE_DISCLAIMER",
    "Check",
    "LocalTimestamper",
    "RekorTransparencyLog",
    "Rfc3161Timestamper",
    "Timestamper",
    "TransparencyLog",
    "VerificationResult",
    "build_evidence_pack",
    "control_mappings",
    "rekor_keyring",
    "render_audit_pack",
    "run_digest",
    "verify_pack",
    "verify_rekor_proof",
    "verify_rfc3161_token",
]
