"""End-to-end CLI tests for ``sectum-ai erasure --subject`` (A3 Phase 0)."""

from pathlib import Path

from typer.testing import CliRunner

from sectum_ai.cli.app import app


def _seed(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["seed", "--workdir", str(tmp_path)])
    assert result.exit_code == 0, result.output


def _write_manifest(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "subject.yaml"
    path.write_text(body)
    return path


def test_erasure_subject_verifies_and_writes_attestation(tmp_path: Path) -> None:
    _seed(tmp_path)
    manifest = _write_manifest(
        tmp_path,
        "subject_ref: user-1\nrecords:\n  vector_db: [doc-a, doc-b]\n  semantic_cache: [k1]\n",
    )
    result = CliRunner().invoke(
        app, ["erasure", "--subject", str(manifest), "--workdir", str(tmp_path)]
    )
    # The default fakes are empty, so the supplied ids are already gone -> ERASED
    # -> exit 0, and the subject-scoped attestation is written.
    assert result.exit_code == 0, result.output
    assert "ERASURE VERIFIED" in result.output
    assert (tmp_path / "erasure-evidence.json").exists()
    assert (tmp_path / "erasure-attestation.intoto.json").exists()
    # The pass states its boundary: the unverifiable surfaces read NOT_COVERED.
    assert "NOT_COVERED" in result.output
    # And without a live adapter it warns loudly that the verdict is against the
    # synthetic store, not production data - an honest DSR attestation.
    assert "built-in synthetic store" in result.output


def test_erasure_subject_marks_unsupported_surface_not_covered(tmp_path: Path) -> None:
    _seed(tmp_path)
    manifest = _write_manifest(
        tmp_path,
        "subject_ref: user-2\nrecords:\n  vector_db: [doc-a]\n  agent_memory: [m1]\n",
    )
    result = CliRunner().invoke(
        app, ["erasure", "--subject", str(manifest), "--workdir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    # A surface with no by-id check is warned and read NOT_COVERED, not silently dropped.
    assert "not supported yet for agent_memory" in result.output


def test_erasure_subject_rejects_an_unknown_surface(tmp_path: Path) -> None:
    _seed(tmp_path)
    manifest = _write_manifest(tmp_path, "subject_ref: user-3\nrecords:\n  not_a_surface: [x]\n")
    result = CliRunner().invoke(
        app, ["erasure", "--subject", str(manifest), "--workdir", str(tmp_path)]
    )
    assert result.exit_code == 3
    assert "not an erasure surface" in result.output


def test_erasure_subject_rejects_a_non_erasure_surface(tmp_path: Path) -> None:
    # `api` is a valid Surface but not one of the erasure surfaces; the manifest
    # must reject it rather than silently accept it as NOT_COVERED.
    _seed(tmp_path)
    manifest = _write_manifest(tmp_path, "subject_ref: user-4\nrecords:\n  api: [x]\n")
    result = CliRunner().invoke(
        app, ["erasure", "--subject", str(manifest), "--workdir", str(tmp_path)]
    )
    assert result.exit_code == 3
    assert "not an erasure surface" in result.output


def test_erasure_subject_fingerprint_notes_best_effort(tmp_path: Path) -> None:
    _seed(tmp_path)
    manifest = _write_manifest(
        tmp_path,
        'subject_ref: user-fp\nfingerprints:\n  vector_db: ["some subject content phrase"]\n',
    )
    result = CliRunner().invoke(
        app, ["erasure", "--subject", str(manifest), "--workdir", str(tmp_path)]
    )
    # Empty fake store -> the content does not surface -> ERASED (exit 0), and the
    # run states that fingerprint probing is best-effort (a clean result is evidence,
    # not proof).
    assert result.exit_code == 0, result.output
    assert "best-effort" in result.output


def test_erasure_subject_requires_a_subject_ref(tmp_path: Path) -> None:
    _seed(tmp_path)
    manifest = _write_manifest(tmp_path, "records:\n  vector_db: [doc-a]\n")
    result = CliRunner().invoke(
        app, ["erasure", "--subject", str(manifest), "--workdir", str(tmp_path)]
    )
    assert result.exit_code == 3
    assert "subject_ref" in result.output


def test_erasure_subject_model_fingerprint_warns_synthetic_and_verifies(tmp_path: Path) -> None:
    _seed(tmp_path)
    manifest = _write_manifest(
        tmp_path,
        'subject_ref: user-m\nfingerprints:\n  model_adapter: ["a memorized subject phrase"]\n',
    )
    result = CliRunner().invoke(
        app, ["erasure", "--subject", str(manifest), "--workdir", str(tmp_path)]
    )
    # The default fake model memorized nothing, so the phrase is not reproduced ->
    # ERASED (exit 0); and because it is the built-in synthetic model, the run warns
    # the model_adapter verdict is not against production weights, and states that
    # content-fingerprint probing is best-effort.
    assert result.exit_code == 0, result.output
    assert "model_adapter" in result.output
    assert "built-in synthetic store" in result.output
    assert "best-effort" in result.output
