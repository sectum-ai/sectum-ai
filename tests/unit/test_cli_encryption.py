"""End-to-end tests for at-rest substrate encryption through the CLI."""

import base64
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sectum_ai.cli.app import app

_runner = CliRunner()
_KEY_B64 = base64.b64encode(os.urandom(32)).decode()
_KEY_ENV = "SECTUM_TEST_MANIFEST_KEY"


def _config(workdir: Path) -> Path:
    path = workdir / "sectum-ai.yaml"
    path.write_text(f"workdir: {workdir}\nsecurity:\n  manifest_key_env: {_KEY_ENV}\n")
    return path


def test_seed_seals_the_substrate_at_rest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY_B64)
    result = _runner.invoke(app, ["seed", "--config", str(_config(tmp_path))])
    assert result.exit_code == 0
    # the sealed file replaces the plaintext one and does not leak the corpus
    assert (tmp_path / "substrate.json.enc").exists()
    assert not (tmp_path / "substrate.json").exists()
    blob = (tmp_path / "substrate.json.enc").read_bytes()
    assert blob.startswith(b"SECTUM-SUBSTRATE-v1")
    assert b"SECTUM-CANARY" not in blob


def test_encrypted_seed_probe_report_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY_B64)
    config = _config(tmp_path)
    assert _runner.invoke(app, ["seed", "--config", str(config)]).exit_code == 0
    # the probe loads the sealed substrate and runs to completion (0 or 2)
    assert _runner.invoke(app, ["probe", "--config", str(config)]).exit_code in (0, 2)
    assert _runner.invoke(app, ["report", "--config", str(config)]).exit_code == 0
    assert (tmp_path / "evidence.json").exists()


def test_loading_an_encrypted_substrate_without_the_key_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY_B64)
    config = _config(tmp_path)
    _runner.invoke(app, ["seed", "--config", str(config)])
    monkeypatch.delenv(_KEY_ENV)
    result = _runner.invoke(app, ["probe", "--config", str(config)])
    assert result.exit_code == 3


def test_loading_an_encrypted_substrate_with_a_wrong_key_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY_B64)
    config = _config(tmp_path)
    _runner.invoke(app, ["seed", "--config", str(config)])
    monkeypatch.setenv(_KEY_ENV, base64.b64encode(os.urandom(32)).decode())
    result = _runner.invoke(app, ["probe", "--config", str(config)])
    assert result.exit_code == 3


def test_probe_on_a_corrupt_encrypted_substrate_exits_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A truncated/corrupt sealed file must exit 3, not crash with a traceback.
    monkeypatch.setenv(_KEY_ENV, _KEY_B64)
    config = _config(tmp_path)
    _runner.invoke(app, ["seed", "--config", str(config)])
    (tmp_path / "substrate.json.enc").write_bytes(b"SECTUM-SUBSTRATE-v1" + b"\x01\x02\x03")
    result = _runner.invoke(app, ["probe", "--config", str(config)])
    assert result.exit_code == 3


def test_re_seeding_with_a_key_removes_the_stale_plaintext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A plaintext seed, then a re-seed with a key, must not leave the plaintext
    # substrate (with its canary plaintexts) on disk - that would defeat the
    # at-rest protection.
    plain_config = tmp_path / "plain.yaml"
    plain_config.write_text(f"workdir: {tmp_path}\n")
    _runner.invoke(app, ["seed", "--config", str(plain_config)])
    assert (tmp_path / "substrate.json").exists()
    monkeypatch.setenv(_KEY_ENV, _KEY_B64)
    _runner.invoke(app, ["seed", "--config", str(_config(tmp_path))])
    assert (tmp_path / "substrate.json.enc").exists()
    assert not (tmp_path / "substrate.json").exists()


@pytest.mark.parametrize("sealed", [True, False])
def test_a_substrate_from_another_schema_line_is_refused_however_it_is_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sealed: bool
) -> None:
    # `Substrate.schema_version` defaults to SCHEMA_VERSION, so a payload carrying
    # no stamp parses cleanly and then reports the CURRENT version. The sealed
    # path read the stamp off the parsed model and so asked the record a question
    # it had already answered for it; the plaintext path reads the raw JSON, and
    # its own comment states the rule - "a substrate from another line seeded a
    # run whose own stamp then read as current".
    #
    # The same payload was therefore refused at exit 3 as plaintext and accepted
    # at exit 0 sealed, with the PERMISSIVE path being the one that has at-rest
    # protection turned on. Parameterised so the two can never diverge again.
    import json

    from sectum_ai.crypto import seal_bytes, unseal_bytes

    monkeypatch.setenv(_KEY_ENV, _KEY_B64)
    key = base64.b64decode(_KEY_B64)
    config = _config(tmp_path) if sealed else None
    seed = ["seed", "--config", str(config)] if sealed else ["seed", "--workdir", str(tmp_path)]
    assert _runner.invoke(app, seed).exit_code == 0

    path = tmp_path / ("substrate.json.enc" if sealed else "substrate.json")
    payload = json.loads(unseal_bytes(path.read_bytes(), key) if sealed else path.read_text())
    assert payload.pop("schema_version"), "the substrate no longer carries a stamp to strip"
    raw = json.dumps(payload).encode()
    path.write_bytes(seal_bytes(raw, key) if sealed else raw)

    probe = ["probe", "--config", str(config)] if sealed else ["probe", "--workdir", str(tmp_path)]
    result = _runner.invoke(app, probe)
    assert result.exit_code == 3, result.output
    assert "is a schema None record" in result.output, result.output


@pytest.mark.parametrize("sealed", [True, False])
def test_a_substrate_that_does_carry_the_stamp_still_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sealed: bool
) -> None:
    # The other half of the guard: re-reading the stamp off the payload must not
    # start refusing genuine substrates. A false alarm on a real artifact is the
    # same class of harm as accepting a foreign one.
    monkeypatch.setenv(_KEY_ENV, _KEY_B64)
    config = _config(tmp_path) if sealed else None
    seed = ["seed", "--config", str(config)] if sealed else ["seed", "--workdir", str(tmp_path)]
    assert _runner.invoke(app, seed).exit_code == 0
    probe = ["probe", "--config", str(config)] if sealed else ["probe", "--workdir", str(tmp_path)]
    assert _runner.invoke(app, probe).exit_code in (0, 2)
