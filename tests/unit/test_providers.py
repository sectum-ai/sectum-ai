"""Tests for the real embedding/judge providers and their config resolvers.

The provider HTTP calls are mocked, so these run offline; a live round-trip is
opt-in (set OPENAI_API_KEY / ANTHROPIC_API_KEY) and exercised separately.
"""

import json
import os
import urllib.error
from typing import Any
from uuid import UUID

import pytest

from sectum.config import (
    DetectionConfig,
    EmbedderConfig,
    JudgeConfig,
    build_detection_providers,
    build_embedder,
    build_judge,
)
from sectum.probes import AnthropicJudge, OpenAIEmbeddingProvider, OpenAIJudge
from sectum.probes.providers import _verdict_from_json
from sectum.spec import ConfigError, DetectionError, Marker, MarkerType

_MARKER = Marker(
    marker_id="m-1",
    marker_type=MarkerType.ENTITY_CANARY,
    owner_tenant_id=UUID(int=1),
    plaintext="Project Wintergreen",
)


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._body = json.dumps(payload).encode()

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _mock_urlopen(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:
        captured["url"] = request.full_url
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        captured["body"] = json.loads(request.data)
        return _FakeResponse(payload)

    monkeypatch.setattr("sectum.probes.providers.urllib.request.urlopen", fake_urlopen)
    return captured


def test_openai_embedder_posts_and_returns_the_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _mock_urlopen(monkeypatch, {"data": [{"embedding": [0.1, 0.2, 0.3]}]})
    vector = OpenAIEmbeddingProvider("sk-test", model="text-embedding-3-large").embed("hello")
    assert vector == (0.1, 0.2, 0.3)
    assert captured["url"] == "https://api.openai.com/v1/embeddings"
    assert captured["headers"]["authorization"] == "Bearer sk-test"
    assert captured["body"] == {"model": "text-embedding-3-large", "input": "hello"}


def test_openai_embedder_rejects_a_malformed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_urlopen(monkeypatch, {"unexpected": True})
    with pytest.raises(DetectionError, match="malformed"):
        OpenAIEmbeddingProvider("sk-test").embed("hello")


def test_openai_embedder_rejects_an_empty_data_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_urlopen(monkeypatch, {"data": []})
    with pytest.raises(DetectionError, match="malformed"):
        OpenAIEmbeddingProvider("sk-test").embed("hello")


def test_openai_judge_parses_a_structured_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"choices": [{"message": {"content": '{"leak": true, "rationale": "name present"}'}}]}
    captured = _mock_urlopen(monkeypatch, payload)
    verdict = OpenAIJudge("sk-test").judge("the text mentions Project Wintergreen", _MARKER)
    assert verdict.leak is True
    assert verdict.rationale == "name present"
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    # the marker plaintext reaches the judge as the entity descriptor
    assert "Project Wintergreen" in captured["body"]["messages"][1]["content"]


def test_anthropic_judge_parses_a_structured_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"content": [{"text": '{"leak": false, "rationale": "no overlap"}'}]}
    captured = _mock_urlopen(monkeypatch, payload)
    verdict = AnthropicJudge("sk-ant").judge("unrelated text", _MARKER)
    assert verdict.leak is False
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-ant"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    # the messages API requires max_tokens; the entity goes in the user message
    assert captured["body"]["max_tokens"] > 0
    assert captured["body"]["system"]
    assert "Project Wintergreen" in captured["body"]["messages"][0]["content"]


def test_a_provider_http_error_becomes_a_detection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(request: Any, timeout: float) -> _FakeResponse:
        raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr("sectum.probes.providers.urllib.request.urlopen", fail)
    with pytest.raises(DetectionError, match="HTTP 429"):
        OpenAIEmbeddingProvider("sk-test").embed("hello")


def test_a_provider_network_error_becomes_a_detection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(request: Any, timeout: float) -> _FakeResponse:
        raise OSError("connection refused")

    monkeypatch.setattr("sectum.probes.providers.urllib.request.urlopen", boom)
    with pytest.raises(DetectionError, match="failed"):
        OpenAIJudge("sk-test").judge("text", _MARKER)


def test_verdict_from_json_rejects_a_missing_leak_field() -> None:
    with pytest.raises(DetectionError, match="leak"):
        _verdict_from_json('{"rationale": "no verdict"}')


def test_verdict_from_json_rejects_non_json() -> None:
    with pytest.raises(DetectionError, match="non-JSON"):
        _verdict_from_json("not json at all")


def test_build_embedder_defaults_to_the_fake() -> None:
    assert build_embedder(EmbedderConfig()) is None


def test_build_embedder_resolves_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    embedder = build_embedder(EmbedderConfig(kind="openai", model="text-embedding-3-large"))
    assert isinstance(embedder, OpenAIEmbeddingProvider)


def test_build_embedder_without_a_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="not set"):
        build_embedder(EmbedderConfig(kind="openai"))


def test_build_judge_resolves_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_ANTHROPIC_KEY", "sk-ant")
    judge = build_judge(JudgeConfig(kind="anthropic", api_key_env="MY_ANTHROPIC_KEY"))
    assert isinstance(judge, AnthropicJudge)


def test_build_detection_providers_threads_the_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    providers = build_detection_providers(
        DetectionConfig(embedder=EmbedderConfig(kind="openai"), semantic_threshold=0.8)
    )
    assert isinstance(providers.embedder, OpenAIEmbeddingProvider)
    assert providers.judge is None
    assert providers.semantic_threshold == 0.8


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="set OPENAI_API_KEY to run the live OpenAI provider tests",
)
def test_live_openai_embedder_and_judge() -> None:
    key = os.environ["OPENAI_API_KEY"]
    vector = OpenAIEmbeddingProvider(key).embed("a benign sentence")
    assert len(vector) > 100  # text-embedding-3-small is 1536-dimensional
    verdict = OpenAIJudge(key).judge("This document is about unrelated weather data.", _MARKER)
    assert verdict.leak is False


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="set ANTHROPIC_API_KEY to run the live Anthropic judge test",
)
def test_live_anthropic_judge() -> None:
    verdict = AnthropicJudge(os.environ["ANTHROPIC_API_KEY"]).judge(
        "This document is about unrelated weather data.", _MARKER
    )
    assert verdict.leak is False
