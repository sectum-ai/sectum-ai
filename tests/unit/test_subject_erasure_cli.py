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
    # The default fakes are empty, so the supplied ids do not surface. That is
    # ABSENCE CHECKED, never ERASED: this probe runs after the controller's
    # deletion and nothing establishes the records were ever there, so "1 markers
    # before, 0 after -> ERASED / ERASURE VERIFIED" was a vacuous attestation - the
    # one `SurfaceErasure.erased` refuses on the Class 11 path.
    assert result.exit_code == 0, result.output
    assert "ERASURE VERIFIED" not in result.output
    assert "NO RESIDUAL FOUND" in result.output
    assert "NOT an attested erasure" in result.output
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
    # Empty fake store -> the content does not surface -> ABSENCE CHECKED (exit 0), and the
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
    # ABSENCE CHECKED (exit 0); and because it is the built-in synthetic model, it warns
    # the model_adapter verdict is not against production weights, and states that
    # content-fingerprint probing is best-effort.
    assert result.exit_code == 0, result.output
    assert "model_adapter" in result.output
    assert "built-in synthetic store" in result.output
    assert "best-effort" in result.output


def test_erasure_subject_memory_and_search_fingerprints_warn_synthetic(tmp_path: Path) -> None:
    _seed(tmp_path)
    manifest = _write_manifest(
        tmp_path,
        "subject_ref: user-ms\nfingerprints:\n"
        '  agent_memory: ["a subject memory phrase"]\n'
        '  search_index: ["a subject search phrase"]\n',
    )
    result = CliRunner().invoke(
        app, ["erasure", "--subject", str(manifest), "--workdir", str(tmp_path)]
    )
    # The default fakes are empty, so nothing surfaces -> ABSENCE CHECKED (exit 0); and because
    # both surfaces run against the built-in synthetic stores, the run names them in
    # the not-production warning so the DSR attestation stays honest.
    assert result.exit_code == 0, result.output
    assert "agent_memory" in result.output
    assert "search_index" in result.output
    assert "built-in synthetic store" in result.output


def test_the_a3_verdict_carries_both_disclosures_on_its_own_stream(tmp_path: Path) -> None:
    # The Class 11 sibling got a stdout provenance line so `erasure 2>/dev/null`
    # could not read as a clean attestation of nothing. This branch - the A3 path,
    # with a NAMED data subject and a statutory deadline - kept both of its
    # disclosures on stderr, so the same redirect stripped the provenance AND the
    # "this is NOT an attested erasure" caveat, leaving only per-surface
    # "0 still present" lines under NO RESIDUAL FOUND.
    #
    # Asserted against result.stdout specifically, with stderr kept separate, or
    # the redirect this is about is not what the test exercises.
    _seed(tmp_path)
    manifest = _write_manifest(
        tmp_path,
        "subject_ref: user-1\nrecords:\n  vector_db: [doc-a, doc-b]\n  semantic_cache: [k1]\n",
    )
    result = CliRunner().invoke(
        app, ["erasure", "--subject", str(manifest), "--workdir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    stdout = result.stdout
    assert "NO RESIDUAL FOUND" in stdout, stdout
    assert "NOT an attested erasure" in stdout, (
        "the caveat that stops this reading as an attestation is not on the "
        f"verdict's own stream: {stdout}"
    )
    assert "SYNTHETIC" in stdout, (
        f"the A3 verdict does not name its subject on its own stream: {stdout}"
    )
