"""Tests for structured logging and its redaction guarantees (the spec, section 16)."""

import json

import pytest
import structlog

from sectum.spec import configure_logging, get_logger, redact_sensitive


def test_redact_drops_secrets_and_tenant_content_above_debug() -> None:
    event = {
        "level": "info",
        "event": "probe.run",
        "api_key": "sk-must-not-appear",
        "raw_response": "Acme private memo mentioning SECTUM-CANARY-xyz",
        "probe": "rag-entity-bleed",
        "findings": 3,
    }
    out = redact_sensitive(None, "info", dict(event))
    assert out["api_key"] == "<redacted>"
    assert out["raw_response"] == "<redacted>"
    # Safe operational metadata is preserved.
    assert out["probe"] == "rag-entity-bleed"
    assert out["findings"] == 3


def test_redact_passes_through_at_debug() -> None:
    """DEBUG is opt-in and off by default, so it may carry raw values."""
    event = {"level": "debug", "api_key": "sk-visible-only-at-debug", "raw_response": "raw"}
    out = redact_sensitive(None, "debug", dict(event))
    assert out["api_key"] == "sk-visible-only-at-debug"
    assert out["raw_response"] == "raw"


def test_logs_go_to_stderr_as_json_not_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(debug=False, json_output=True)
    get_logger("test.routing").info("evidence.signed", run_id="r1", token="topsecret")
    captured = capsys.readouterr()
    assert captured.out == ""  # stdout stays reserved for command output
    record = json.loads(captured.err.strip().splitlines()[-1])
    assert record["event"] == "evidence.signed"
    assert record["run_id"] == "r1"
    assert record["token"] == "<redacted>"  # secret redacted at INFO
    assert record["level"] == "info"


def test_debug_is_off_by_default(capsys: pytest.CaptureFixture[str]) -> None:
    structlog.reset_defaults()
    configure_logging(debug=False)
    get_logger("test.debugoff").debug("noisy", detail="x")
    assert capsys.readouterr().err == ""


def test_debug_can_be_enabled(capsys: pytest.CaptureFixture[str]) -> None:
    structlog.reset_defaults()
    configure_logging(debug=True)
    get_logger("test.debugon").debug("verbose-event", detail="x")
    assert "verbose-event" in capsys.readouterr().err
