"""Tests for structured logging and its redaction guarantees (the spec, section 16)."""

import json

import pytest
import structlog

from sectum_ai.spec import configure_logging, get_logger, redact_sensitive

# Credential-/canary-shaped fixtures are assembled at runtime so no literal token
# sits in source — both so the repo's gitleaks secret-scan does not flag this test
# file and as a clean way to exercise the value-shape scrub. Each still matches
# its pattern in `redact_sensitive` at runtime.
_SK = "sk-" + "A" * 40  # OpenAI-style key shape
_AKIA = "AKIA" + "A" * 16  # AWS access-key-id shape
_HARD = "SECTUM-CANARY-" + "A" * 20  # HARD canary shape


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


def test_redact_recurses_into_nested_dicts_and_lists() -> None:
    # Defense in depth: a sensitive key nested under a benign key is dropped at
    # any depth, not just at the top level.
    event = {
        "level": "info",
        "event": "adapter.call",
        "request": {"meta": {"api_key": "sk-deep"}, "tenant": "acme"},
        "batch": [{"token": "t1"}, {"ok": True}],
        "pair": ({"password": "p"}, _AKIA),
    }
    out = redact_sensitive(None, "info", dict(event))
    assert out["request"]["meta"]["api_key"] == "<redacted>"
    assert out["request"]["tenant"] == "acme"  # benign nested value preserved
    assert out["batch"][0]["token"] == "<redacted>"
    assert out["batch"][1]["ok"] is True
    # Tuples are preserved as tuples, with nested keys redacted + shapes scrubbed.
    assert isinstance(out["pair"], tuple)
    assert out["pair"][0]["password"] == "<redacted>"
    assert out["pair"][1] == "<redacted>"


def test_redact_scrubs_secret_shaped_values_under_benign_keys() -> None:
    # Value-shape scrub: a secret under a NON-sensitive key name is still caught.
    event = {
        "level": "info",
        "event": "note",
        "detail": f"leaked {_SK} in the body",
        "aws": _AKIA,
        "ssn": "patient 900-12-3456 record",
        "hard": f"saw {_HARD} here",
    }
    out = redact_sensitive(None, "info", dict(event))
    assert _SK not in out["detail"] and "<redacted>" in out["detail"]
    assert out["aws"] == "<redacted>"  # the whole value was the secret shape
    assert out["ssn"] == "patient <redacted> record"
    assert "SECTUM-CANARY" not in out["hard"]


def test_redact_scrubs_secret_in_the_event_message() -> None:
    event = {"level": "info", "event": f"served {_SK} to caller"}
    out = redact_sensitive(None, "info", dict(event))
    assert _SK not in out["event"]
    assert "<redacted>" in out["event"]


def test_redact_scrubs_secret_carried_by_an_exception_value() -> None:
    event = {
        "level": "info",
        "event": "boom",
        "error": ValueError(f"bad key {_SK}"),
    }
    out = redact_sensitive(None, "info", dict(event))
    assert _SK not in str(out["error"])
    assert "<redacted>" in str(out["error"])


def test_redact_preserves_benign_operational_metadata() -> None:
    # No false positives: ordinary metadata passes through unchanged.
    event = {
        "level": "info",
        "event": "probe.run.complete",
        "probe": "rag-entity-bleed",
        "findings": 12,
        "model": "text-embedding-3-small",
        "digest": "a1b2c3d4",
    }
    out = redact_sensitive(None, "info", dict(event))
    assert out == event


def test_redact_recursion_skipped_at_debug() -> None:
    # DEBUG stays fully untouched, including nested values and the message.
    event = {"level": "debug", "request": {"api_key": "sk-visible"}, "event": "sk-visible"}
    out = redact_sensitive(None, "debug", dict(event))
    assert out["request"]["api_key"] == "sk-visible"
    assert out["event"] == "sk-visible"


def test_scrub_matches_each_secret_shape_at_full_length() -> None:
    # Every real-length credential/canary shape is scrubbed wherever it appears.
    shapes = {
        "openai": "sk-" + "B" * 48,
        "aws": "AKIA" + "C" * 16,
        "hard": "SECTUM-CANARY-" + "D" * 26,
        "ssn": "9" + "00-12-3456",
    }
    event = {"level": "info", "event": "x", **{k: f"saw {v} here" for k, v in shapes.items()}}
    out = redact_sensitive(None, "info", dict(event))
    for key, secret in shapes.items():
        assert secret not in out[key], key
        assert out[key] == "saw <redacted> here", key


def test_scrub_replaces_multiple_secrets_in_one_string() -> None:
    blob = f"first {_SK} then {_AKIA} done"
    out = redact_sensitive(None, "info", {"level": "info", "event": "x", "blob": blob})
    assert _SK not in out["blob"] and _AKIA not in out["blob"]
    assert out["blob"].count("<redacted>") == 2


def test_sensitive_key_with_a_nested_value_is_redacted_wholesale() -> None:
    # Key precedence over recursion: a sensitive key drops its entire value.
    event = {"level": "info", "event": "x", "credentials": {"user": "u", "pass": "p"}}
    out = redact_sensitive(None, "info", dict(event))
    assert out["credentials"] == "<redacted>"


def test_sensitive_keys_match_case_insensitively() -> None:
    event = {"level": "info", "event": "x", "API_KEY": "v1", "Authorization": "v2", "Token": "v3"}
    out = redact_sensitive(None, "info", dict(event))
    assert out["API_KEY"] == out["Authorization"] == out["Token"] == "<redacted>"


def test_scrub_leaves_near_miss_and_benign_strings_untouched() -> None:
    # No false positives: sub-threshold shapes, an entity-style codename, a uuid,
    # an ISO timestamp, a hex digest, and a count all pass through unchanged.
    benign = {
        "level": "info",
        "event": "probe.run",
        "codename": "Project Zephyr launch notes",  # entity-style; not value-scrubbed
        "short_sk": "sk-" + "A" * 10,  # below the 20-char threshold
        "short_aws": "AKIA" + "A" * 10,  # below 16
        "uuid": "7cd276c8-b7a8-5ec3-988e-c4fec6002ccf",
        "ts": "2026-06-15T19:00:00Z",
        "digest": "a1b2c3d4e5f6",
        "count": 42,
    }
    out = redact_sensitive(None, "info", dict(benign))
    assert out == benign


def test_non_string_scalars_pass_through() -> None:
    event = {"level": "info", "event": "x", "n": 3, "f": 1.5, "flag": False, "nothing": None}
    out = redact_sensitive(None, "info", dict(event))
    assert out["n"] == 3
    assert out["f"] == 1.5
    assert out["flag"] is False
    assert out["nothing"] is None


def test_deeply_nested_mixed_structure_is_fully_redacted() -> None:
    event = {
        "level": "info",
        "event": "x",
        "outer": [{"inner": {"token": "t", "note": f"key {_SK}"}}, ["plain", _AKIA]],
    }
    out = redact_sensitive(None, "info", dict(event))
    assert out["outer"][0]["inner"]["token"] == "<redacted>"  # sensitive key at depth 3
    assert _SK not in out["outer"][0]["inner"]["note"]  # shape scrubbed at depth 3
    assert out["outer"][1][0] == "plain"  # benign list item preserved
    assert out["outer"][1][1] == "<redacted>"  # shape scrubbed in a nested list


def test_end_to_end_logger_redacts_nested_and_message_secrets(
    capsys: pytest.CaptureFixture[str],
) -> None:
    structlog.reset_defaults()
    configure_logging(debug=False, json_output=True)
    get_logger("test.e2e").info(
        f"served {_SK}",  # secret embedded in the message
        request={"meta": {"api_key": "k"}},  # sensitive key nested under a benign key
        note=f"aws {_AKIA}",  # secret-shaped value under a benign key
    )
    record = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert _SK not in record["event"] and "<redacted>" in record["event"]
    assert record["request"]["meta"]["api_key"] == "<redacted>"
    assert _AKIA not in record["note"]


def test_scrub_only_matches_credential_shapes_at_a_word_boundary() -> None:
    # The sk-/AKIA shapes must match a standalone token, not a substring of a
    # benign identifier — else an ops field like a task/disk id is over-redacted.
    preserved = {
        "level": "info",
        "event": "x",
        "task": "task-" + "A" * 40,  # contains 'sk-'+long, but mid-identifier
        "disk": "disk-" + "A" * 40,
        "midword_aws": "x" + _AKIA,  # AKIA preceded by an alphanumeric
    }
    assert redact_sensitive(None, "info", dict(preserved)) == preserved
    # ... but a standalone token, or one after a non-alphanumeric boundary
    # (including '_'), is still scrubbed.
    boundary = {
        "level": "info",
        "event": "x",
        "underscore": "api_" + _SK,
        "equals": "key=" + _AKIA,
        "standalone": _SK,
    }
    out = redact_sensitive(None, "info", dict(boundary))
    assert out["underscore"] == "api_<redacted>"
    assert out["equals"] == "key=<redacted>"
    assert out["standalone"] == "<redacted>"


def test_logging_resolves_stderr_at_write_time(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression: the cached logger must write to the CURRENT sys.stderr, not a
    # stream captured at configure time. A harness that swaps and then closes
    # stderr between calls (typer >= 0.26's CliRunner, between in-process
    # invocations) would otherwise make the next log raise "I/O operation on
    # closed file". See sectum_ai.spec._logging._LiveStderr.
    import io
    import sys

    structlog.reset_defaults()
    configure_logging(json_output=True)
    log = get_logger("test.stderr")

    first = io.StringIO()
    monkeypatch.setattr(sys, "stderr", first)
    log.warning("one")
    assert "one" in first.getvalue()
    first.close()  # the captured stream is closed, as CliRunner does on exit

    second = io.StringIO()
    monkeypatch.setattr(sys, "stderr", second)
    log.warning("two")  # must not raise; writes to the live stderr
    assert "two" in second.getvalue()
