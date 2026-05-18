"""Sectum AI evidence chain: tamper-evident packs and independent verification.

This is the ``sectum.evidence`` namespace package. The entire evidence layer is
open source; see docs/adr/0002-evidence-layer-oss-boundary.md.
"""

from sectum.evidence.chain import (
    LocalTimestamper,
    Timestamper,
    build_evidence_pack,
    run_digest,
)
from sectum.evidence.verify import Check, VerificationResult, verify_pack

__all__ = [
    "Check",
    "LocalTimestamper",
    "Timestamper",
    "VerificationResult",
    "build_evidence_pack",
    "run_digest",
    "verify_pack",
]
