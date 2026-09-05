"""Tests for `sectum-ai pack` (the portable run pack) and its config redaction."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any, cast

from typer.testing import CliRunner

from sectum_ai.cli.app import (
    _redact_config_text,
    _redact_config_value,
    _scrub_config_secret_value,
    app,
)

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
    assert "://<redacted>@" in out  # userinfo replaced with the marker, URL kept
    assert "<redacted>" in out


def test_redact_config_scrubs_url_query_and_provider_tokens() -> None:
    # A token in a URL query string, and common provider tokens hiding in `args`,
    # must also be scrubbed (they sit under benign key names). The token values are
    # assembled at runtime so no literal secret is committed in the fixture.
    q_val = "0123456789abcdef0123"
    gh_prefix = "ghp_"  # split + variable operand so the token is not const-folded
    gh_val = gh_prefix + "0123456789abcdefABCDEF0123"
    text = (
        "adapters:\n"
        "  observability:\n"
        "    kind: otel\n"
        f"    base_url: https://ingest.example.com/v1/traces?dd-api-key={q_val}\n"
        "  agent:\n"
        "    kind: stdio\n"
        "    args:\n"
        f"      - --auth={gh_val}\n"
    )
    out = _redact_config_text(text)
    assert q_val not in out  # query-parameter value scrubbed
    assert gh_val not in out  # GitHub token scrubbed
    assert "<redacted>" in out


def test_scrub_config_secret_value_keeps_benign_urls() -> None:
    # No over-redaction: a plain endpoint with no userinfo or secret query is kept.
    assert _scrub_config_secret_value("https://localhost:8080/v1") == "https://localhost:8080/v1"
    assert _scrub_config_secret_value("gpt-4o-mini") == "gpt-4o-mini"


def test_redact_config_secret_key_matches_on_a_word_boundary() -> None:
    # A vLLM config's benign `max_tokens` must NOT be redacted by the `token`
    # secret-key rule (it is `tokens`, not `token`), and `public_key` stays public;
    # real secret keys still redact. (The cross-cutting B3-redaction x D2-vllm bug.)
    out = cast(
        dict[str, Any],
        _redact_config_value(
            {
                "max_tokens": 16,
                "timeout": 30,
                "tokenizer": "gpt2",
                "public_key": "pk-public-id",
                "token": "t",
                "secret_key": "s",
                "api_key": "sk-LEAKME",
                "api_key_env": "SECTUM_VLLM_API_KEY",
            }
        ),
    )
    assert out["max_tokens"] == 16  # not redacted by the `token` rule
    assert out["timeout"] == 30
    assert out["tokenizer"] == "gpt2"
    assert out["public_key"] == "pk-public-id"  # the public half is kept
    assert out["token"] == "<redacted>"  # a bare secret key still redacts
    assert out["secret_key"] == "<redacted>"
    assert out["api_key"] == "<redacted>"
    assert out["api_key_env"] == "SECTUM_VLLM_API_KEY"  # env reference kept


def test_redact_config_hardening_bearer_userinfo_scalar() -> None:
    # bearer is matched in any case; a malformed mid-password `@` still redacts the
    # whole userinfo (no surviving tail); a scalar-only config is scrubbed, not echoed.
    assert "ABCDEFGH12345678" not in _scrub_config_secret_value("note: BEARER ABCDEFGH12345678")
    assert "p4ss" not in _scrub_config_secret_value("http://user:p4ss@w0rd@host/v1")
    assert "<redacted>" in _redact_config_text("sk-" + "x" * 24)


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

    verified = _runner.invoke(app, ["verify", str(pack), "--allow-unanchored", "--allow-synthetic"])
    assert verified.exit_code == 0, verified.output


def test_pack_requires_a_prior_report(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    _runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    # No `report` was run, so there is no evidence pack to bundle.
    result = _runner.invoke(app, ["pack", "--workdir", str(tmp_path)])
    assert result.exit_code == 3  # ConfigError -> config/adapter exit code


def test_pack_bundles_the_redacted_config(tmp_path: Path) -> None:
    # An inline secret on a live adapter block (a builder that reads the field:
    # an unread `api_key` on a fake is refused at build since the field guard).
    # The HTTP RAG pipeline is constructed without a network call and never
    # driven, since only the vector probe runs.
    config = tmp_path / "sectum-ai.yaml"
    config.write_text(
        "adapters:\n  rag:\n    kind: http\n    url: http://127.0.0.1:9/rag\n"
        "    headers:\n      Authorization: Bearer sk-LEAKME\n",
        encoding="utf-8",
    )
    args = ["--workdir", str(tmp_path), "--config", str(config)]
    _runner.invoke(app, ["seed", *args])
    _runner.invoke(app, ["probe", *args, "--probe", "tenant-boundary-fetch"])
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
