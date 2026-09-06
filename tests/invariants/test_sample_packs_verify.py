"""Invariant: every evidence pack shipped in docs/samples/ passes ``sectum-ai verify``.

docs/samples/README.md promises "Every pack here verifies under the open-source
``sectum-ai verify``". These are the flagship public artifacts a prospective
auditor, DPO, or CISO inspects, so an untampered-but-failing sample is a
worst-case credibility failure for a product sold on independently verifiable,
tamper-evident evidence.

This guards against the failure mode that shipped once already: a change to the
attested-digest scheme (ADR-0016 moved the anchor from the run digest to the
whole-pack ``attested_digest``) left the committed samples stale, so they
reported "the evidence pack was altered" on clean data. Regenerate the samples
(see docs/samples/README.md "Regenerating") whenever this test fails — never
silence it.
"""

import json
import re
import tempfile
from pathlib import Path

import pytest

from sectum_ai.evidence import PREDICATE_TYPE, STATEMENT_TYPE, verify_pack
from sectum_ai.evidence.pdf import render_audit_pack
from sectum_ai.spec import EvidencePack

# tests/invariants/ -> repo root is two parents up.
_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "docs" / "samples"
_SAMPLE_PACKS = sorted(_SAMPLES_DIR.glob("*evidence*.json"))
_SAMPLE_SIDECARS = sorted(_SAMPLES_DIR.glob("*.intoto.json"))


def test_sample_packs_directory_is_present() -> None:
    # If the glob ever finds nothing, the parametrized test below would vacuously
    # pass and the invariant would be silently unguarded. Pin that the shipped
    # samples exist.
    assert _SAMPLE_PACKS, f"no *evidence*.json packs found under {_SAMPLES_DIR}"


@pytest.mark.parametrize("pack_path", _SAMPLE_PACKS, ids=lambda p: p.name)
def test_shipped_sample_pack_verifies(pack_path: Path) -> None:
    # Verify the pack standalone (no manifest): integrity + internal consistency,
    # exactly what `sectum-ai verify <pack>` does for a downloaded sample.
    pack = EvidencePack.model_validate_json(pack_path.read_text())
    result = verify_pack(pack)
    failed = [f"{c.name}: {c.detail}" for c in result.checks if not c.ok]
    assert result.passed, f"{pack_path.name} failed sectum-ai verify: {failed}"


def test_sample_sidecars_are_present() -> None:
    assert _SAMPLE_SIDECARS, f"no *.intoto.json sidecars found under {_SAMPLES_DIR}"


@pytest.mark.parametrize("sidecar_path", _SAMPLE_SIDECARS, ids=lambda p: p.name)
def test_shipped_intoto_sidecar_is_a_wellformed_statement(sidecar_path: Path) -> None:
    # Every committed in-toto sidecar must be a structurally valid Statement, so no
    # shipped attestation is silently orphaned or malformed - including the
    # retrieval-pivot sidecar, whose (large) evidence.json is not committed and so
    # would otherwise go untested. The erasure sidecars are additionally bound to
    # their committed packs by `sectum-ai verify` (test_cli_pipeline / cli_erasure).
    statement = json.loads(sidecar_path.read_text())
    assert statement["_type"] == STATEMENT_TYPE
    assert statement["predicateType"] == PREDICATE_TYPE
    subjects = statement["subject"]
    assert subjects, f"{sidecar_path.name} has no in-toto subject"
    for subject in subjects:
        assert subject.get("name"), f"{sidecar_path.name} subject missing a name"
        sha256 = subject.get("digest", {}).get("sha256", "")
        assert len(sha256) == 64, f"{sidecar_path.name} subject digest is not a SHA-256"


_ERASURE_SAMPLES = sorted(p for p in _SAMPLES_DIR.glob("*evidence*.json") if "erasure" in p.name)


def _normalised(pdf: bytes) -> bytes:
    """The PDF's content, minus what legitimately changes between renders."""
    pdf = re.sub(rb"D:\d{14}[^)]*", b"D:TIME", pdf)
    return re.sub(rb"\[<[0-9a-f]{32}><[0-9a-f]{32}>\]", b"[<ID><ID>]", pdf)


@pytest.mark.parametrize("pack_path", _ERASURE_SAMPLES, ids=lambda p: p.name)
def test_shipped_sample_pdf_is_what_todays_renderer_produces(pack_path: Path) -> None:
    # The samples are sold as "real outputs ... so a prospective auditor, DPO, or
    # CISO can see what they get", and only the JSON packs were guarded. The
    # renderer gained a fourth cause for NOT_COVERED and both committed erasure
    # PDFs kept stating three, for a whole cycle - the artifact an auditor reads
    # describing a coverage rule the tool no longer follows. Rendering from the
    # committed pack and comparing (modulo the creation timestamp and reportlab's
    # document id, the only parts that legitimately vary) catches any such drift.
    pack = EvidencePack.model_validate_json(pack_path.read_text())
    committed = pack_path.with_name(pack_path.name.replace("-evidence.json", "-audit-pack.pdf"))
    assert committed.exists(), f"no committed PDF beside {pack_path.name}"
    with tempfile.TemporaryDirectory() as directory:
        fresh = Path(directory) / "audit.pdf"
        render_audit_pack(pack, fresh)
        assert _normalised(fresh.read_bytes()) == _normalised(committed.read_bytes()), (
            f"{committed.name} is not what today's renderer produces; regenerate the "
            "samples (docs/samples/README.md)"
        )
