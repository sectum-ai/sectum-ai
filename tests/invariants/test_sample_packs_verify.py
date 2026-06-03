"""Invariant: every evidence pack shipped in docs/samples/ passes ``sectum verify``.

docs/samples/README.md promises "Every pack here verifies under the open-source
``sectum verify``". These are the flagship public artifacts a prospective
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
from pathlib import Path

import pytest
from sectum_ai.evidence import PREDICATE_TYPE, STATEMENT_TYPE, verify_pack
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
    # exactly what `sectum verify <pack>` does for a downloaded sample.
    pack = EvidencePack.model_validate_json(pack_path.read_text())
    result = verify_pack(pack)
    failed = [f"{c.name}: {c.detail}" for c in result.checks if not c.ok]
    assert result.passed, f"{pack_path.name} failed sectum verify: {failed}"


def test_sample_sidecars_are_present() -> None:
    assert _SAMPLE_SIDECARS, f"no *.intoto.json sidecars found under {_SAMPLES_DIR}"


@pytest.mark.parametrize("sidecar_path", _SAMPLE_SIDECARS, ids=lambda p: p.name)
def test_shipped_intoto_sidecar_is_a_wellformed_statement(sidecar_path: Path) -> None:
    # Every committed in-toto sidecar must be a structurally valid Statement, so no
    # shipped attestation is silently orphaned or malformed - including the
    # retrieval-pivot sidecar, whose (large) evidence.json is not committed and so
    # would otherwise go untested. The erasure sidecars are additionally bound to
    # their committed packs by `sectum verify` (test_cli_pipeline / cli_erasure).
    statement = json.loads(sidecar_path.read_text())
    assert statement["_type"] == STATEMENT_TYPE
    assert statement["predicateType"] == PREDICATE_TYPE
    subjects = statement["subject"]
    assert subjects, f"{sidecar_path.name} has no in-toto subject"
    for subject in subjects:
        assert subject.get("name"), f"{sidecar_path.name} subject missing a name"
        sha256 = subject.get("digest", {}).get("sha256", "")
        assert len(sha256) == 64, f"{sidecar_path.name} subject digest is not a SHA-256"
