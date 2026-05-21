"""Tests for at-rest substrate encryption (the engineering spec, section 17)."""

import base64
import os

import pytest

from sectum.crypto import load_key_from_env, seal_bytes, unseal_bytes
from sectum.spec import ConfigError

_KEY = os.urandom(32)


def test_seal_then_unseal_round_trips() -> None:
    plaintext = b'{"manifest": "secret canaries"}'
    sealed = seal_bytes(plaintext, _KEY)
    assert sealed != plaintext
    assert unseal_bytes(sealed, _KEY) == plaintext


def test_the_sealed_blob_does_not_expose_the_plaintext() -> None:
    sealed = seal_bytes(b"SECTUM-CANARY-abc123", _KEY)
    assert b"SECTUM-CANARY-abc123" not in sealed


def test_a_wrong_key_fails_authentication() -> None:
    sealed = seal_bytes(b"payload", _KEY)
    with pytest.raises(ConfigError, match="wrong key or it was tampered"):
        unseal_bytes(sealed, os.urandom(32))


def test_a_tampered_blob_fails_authentication() -> None:
    sealed = bytearray(seal_bytes(b"payload", _KEY))
    sealed[-1] ^= 0xFF  # flip a ciphertext/tag bit
    with pytest.raises(ConfigError, match="wrong key or it was tampered"):
        unseal_bytes(bytes(sealed), _KEY)


def test_a_blob_without_the_magic_header_is_rejected() -> None:
    with pytest.raises(ConfigError, match="not in sealed form"):
        unseal_bytes(b"not a sealed blob at all", _KEY)


def test_a_truncated_sealed_blob_is_rejected_not_crashed() -> None:
    # Valid magic but too short to hold a nonce: must be a typed error, not the
    # bare ValueError that AES-GCM raises on a short nonce.
    with pytest.raises(ConfigError, match="truncated"):
        unseal_bytes(b"SECTUM-SUBSTRATE-v1" + b"\x01\x02\x03", _KEY)


def test_load_key_from_env_reads_a_base64_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECTUM_TEST_KEY", base64.b64encode(_KEY).decode())
    assert load_key_from_env("SECTUM_TEST_KEY") == _KEY


def test_load_key_from_env_unset_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SECTUM_TEST_KEY", raising=False)
    with pytest.raises(ConfigError, match="is not set"):
        load_key_from_env("SECTUM_TEST_KEY")


def test_load_key_from_env_rejects_a_wrong_length_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECTUM_TEST_KEY", base64.b64encode(os.urandom(16)).decode())
    with pytest.raises(ConfigError, match="must be 32 bytes"):
        load_key_from_env("SECTUM_TEST_KEY")


def test_load_key_from_env_rejects_non_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECTUM_TEST_KEY", "not valid base64 !!!")
    with pytest.raises(ConfigError, match="not valid base64"):
        load_key_from_env("SECTUM_TEST_KEY")
