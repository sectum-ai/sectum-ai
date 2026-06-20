"""Tests for `sectum-ai pack` (the portable run pack) and its config redaction."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any, cast

from typer.testing import CliRunner

from sectum_ai.cli.app import _redact_config_text, _redact_config_value, app

_runner = CliRunner()


def _members(zip_path: Path) -> set[str]:
    with zipfile.ZipFile(zip_path) as archive:
        return set(archive.namelist())


def test_redact_config_value_redacts_inline_secrets_keeps_env() -> None:
    out = cast(
        dict[str, Any],
        _redact_config_value(
            {
                "kind": "pinecone",
                "api_key": "sk-REALSECRET",
                "api_key_env": "SECTUM_PINECONE_API_KEY",
                "host": "localhost",
            }
        ),
    )
    assert out["api_key"] == "<redacted>"  # inline secret redacted
    assert out["api_key_env"] == "SECTUM_PINECONE_API_KEY"  # *_env reference kept
    assert out["host"] == "localhost"  # benign value kept
    assert out["kind"] == "pinecone"


def test_redact_config_text_redacts_nested_inline_secret_keeps_env() -> None:
    text = (
        "adapters:\n"
        "  vector_store:\n"
        "    kind: pgvector\n"
        "    dsn: postgresql://user:pass@host/db\n"
        "    dsn_env: SECTUM_PGVECTOR_DSN\n"
        "  cache:\n"
        "    kind: redis\n"
        "    password: hunter2\n"
    )
    out = _redact_config_text(text)
    assert "postgresql://user:pass@host/db" not in out
    assert "hunter2" not in out
    assert "<redacted>" in out
    assert "SECTUM_PGVECTOR_DSN" in out  # env reference preserved
    assert "kind: pgvector" in out  # structure preserved


def test_redact_config_scrubs_headers_url_creds_and_inline_shapes() -> None:
    # Inline secrets can hide under benign key names: header values, credentials
    # embedded in a URL, or a CLI token in `args`. None may survive into the pack.
    text = (
        "adapters:\n"
        "  mcp:\n"
        "    kind: http\n"
        "    headers:\n"
        "      Authorization: Bearer sk-supersecrettoken1234567890\n"
        "      X-Api-Key: deadbeefdeadbeefdeadbeef\n"
        "  observability:\n"
        "    kind: otel\n"
        "    base_url: https://user:p4ssw0rd@otel.example.com/ingest\n"
        "  agent:\n"
        "    kind: stdio\n"
        "    args:\n"
        "      - --api-key=sk-anotherlongsecretvalue00\n"
    )
    out = _redact_config_text(text)
    assert "sk-supersecrettoken1234567890" not in out  # bearer / header value
    assert "deadbeefdeadbeefdeadbeef" not in out  # opaque header token (headers redacted wholesale)
    assert "p4ssw0rd" not in out  # URL userinfo stripped
    assert "sk-anotherlongsecretvalue00" not in out  # token in an args element
    assert "otel.example.com" in out  # only the userinfo is removed, host kept
    assert "<redacted>" in out


def test_redact_config_text_tolerates_invalid_yaml() -> None:
    # Never raise (and never echo the raw text back) on a malformed config.
    out = _redact_config_text("::: not : valid : yaml :::")
    assert "config omitted" in out


def test_pack_builds_a_verifiable_run_pack(tmp_path: Path) -> None:
    assert _runner.invoke(app, ["seed", "--workdir", str(tmp_path)]).exit_code == 0
    _runner.invoke(app, ["probe", "--workdir", str(tmp_path)])  # exit 2 on the leaky demo
    assert _runner.invoke(app, ["report", "--workdir", str(tmp_path)]).exit_code == 0

    result = _runner.invoke(app, ["pack", "--workdir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "SENSITIVE" in result.output

    pack = tmp_path / "run-pack.zip"
    assert {
        "evidence.json",
        "run.json",
        "audit-pack.pdf",
        "PACK-README.md",
        "bundle-manifest.json",
    } <= _members(pack)

    verified = _runner.invoke(app, ["verify", str(pack), "--allow-unanchored"])
    assert verified.exit_code == 0, verified.output


def test_pack_requires_a_prior_report(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    _runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    # No `report` was run, so there is no evidence pack to bundle.
    result = _runner.invoke(app, ["pack", "--workdir", str(tmp_path)])
    assert result.exit_code == 3  # ConfigError -> config/adapter exit code


def test_pack_bundles_the_redacted_config(tmp_path: Path) -> None:
    config = tmp_path / "sectum-ai.yaml"
    config.write_text(
        "adapters:\n  vector_store:\n    kind: fake\n    api_key: sk-LEAKME\n",
        encoding="utf-8",
    )
    args = ["--workdir", str(tmp_path), "--config", str(config)]
    _runner.invoke(app, ["seed", *args])
    _runner.invoke(app, ["probe", *args])
    _runner.invoke(app, ["report", *args])
    result = _runner.invoke(app, ["pack", *args])
    assert result.exit_code == 0, result.output

    with zipfile.ZipFile(tmp_path / "run-pack.zip") as archive:
        assert "sectum-ai.config.redacted.yaml" in archive.namelist()
        packed = archive.read("sectum-ai.config.redacted.yaml").decode("utf-8")
    assert "sk-LEAKME" not in packed  # inline secret never enters the pack
    assert "<redacted>" in packed


def test_pack_include_manifest_without_a_key_errors(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    _runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    _runner.invoke(app, ["report", "--workdir", str(tmp_path)])
    # Sealing the ground-truth manifest needs security.manifest_key_env.
    result = _runner.invoke(app, ["pack", "--workdir", str(tmp_path), "--include-manifest"])
    assert result.exit_code == 3
