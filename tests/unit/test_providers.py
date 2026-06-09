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

from sectum_ai.config import (
    DetectionConfig,
    EmbedderConfig,
    JudgeConfig,
    build_detection_providers,
    build_embedder,
    build_judge,
)
from sectum_ai.probes import (
    AnthropicJudge,
    DetectionPipeline,
    JudgeVerdict,
    OpenAIEmbeddingProvider,
    OpenAIJudge,
)
from sectum_ai.probes.providers import _JUDGE_SYSTEM, _judge_user_prompt, _verdict_from_json
from sectum_ai.spec import (
    ConfigError,
    DetectionError,
    FindingStatus,
    Marker,
    MarkerType,
    Surface,
)

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

    monkeypatch.setattr("sectum_ai.probes.providers.urllib.request.urlopen", fake_urlopen)
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
    payload = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"leak": true, "evidence_span": "mentions Project Wintergreen", '
                        '"rationale": "name present"}'
                    )
                }
            }
        ]
    }
    captured = _mock_urlopen(monkeypatch, payload)
    verdict = OpenAIJudge("sk-test").judge("the text mentions Project Wintergreen", _MARKER)
    assert verdict.leak is True
    assert verdict.rationale == "name present"
    assert verdict.evidence_span == "mentions Project Wintergreen"
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    # the marker plaintext reaches the judge as the entity descriptor
    assert "Project Wintergreen" in captured["body"]["messages"][1]["content"]


def test_anthropic_judge_parses_a_structured_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "content": [{"text": '{"leak": false, "evidence_span": "", "rationale": "no overlap"}'}]
    }
    captured = _mock_urlopen(monkeypatch, payload)
    verdict = AnthropicJudge("sk-ant").judge("unrelated text", _MARKER)
    assert verdict.leak is False
    assert verdict.evidence_span == ""
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

    monkeypatch.setattr("sectum_ai.probes.providers.urllib.request.urlopen", fail)
    with pytest.raises(DetectionError, match="HTTP 429"):
        OpenAIEmbeddingProvider("sk-test").embed("hello")


def test_a_provider_network_error_becomes_a_detection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(request: Any, timeout: float) -> _FakeResponse:
        raise OSError("connection refused")

    monkeypatch.setattr("sectum_ai.probes.providers.urllib.request.urlopen", boom)
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


# --- spec section 6.4 verdict schema ----------------------------------------
#
# The judge must return ``{leak, evidence_span, rationale}``. These tests pin
# the wire format on both providers, the parser's tolerance for older models
# that omit the optional fields, and the detection pipeline carrying the
# judge's quoted span into ``Finding.evidence_span`` so the audit pack can
# render it.


def test_judge_system_prompt_pins_the_three_field_schema() -> None:
    # The system prompt must name every field the parser reads, so the model
    # cannot drift to a two-field shape and have the verdict silently lose
    # ``evidence_span``.
    assert '"leak"' in _JUDGE_SYSTEM
    assert '"evidence_span"' in _JUDGE_SYSTEM
    assert '"rationale"' in _JUDGE_SYSTEM
    assert "verbatim" in _JUDGE_SYSTEM


def test_judge_user_prompt_carries_the_entity_and_observation() -> None:
    prompt = _judge_user_prompt("the weekly status mentions Project Wintergreen", _MARKER)
    assert "Project Wintergreen" in prompt
    assert "weekly status" in prompt
    # the user message also reminds the model of the schema
    assert "evidence_span" in prompt


def test_verdict_from_json_parses_the_full_three_field_schema() -> None:
    verdict = _verdict_from_json(
        '{"leak": true, "evidence_span": "Project Wintergreen", "rationale": "name present"}'
    )
    assert verdict.leak is True
    assert verdict.evidence_span == "Project Wintergreen"
    assert verdict.rationale == "name present"


def test_verdict_from_json_defaults_omitted_fields_to_empty_strings() -> None:
    # An older model that only returns ``{leak}`` must still parse; the pipeline
    # then falls back to the marker plaintext for ``Finding.evidence_span``.
    verdict = _verdict_from_json('{"leak": false}')
    assert verdict.leak is False
    assert verdict.evidence_span == ""
    assert verdict.rationale == ""


def test_verdict_from_json_coerces_non_string_evidence_to_string() -> None:
    # Coerce defensively so a rogue model returning a non-string (or null) for
    # the optional fields never crashes the pipeline.
    verdict = _verdict_from_json('{"leak": true, "evidence_span": null, "rationale": null}')
    assert verdict.leak is True
    assert verdict.evidence_span == "None"
    assert verdict.rationale == "None"


def test_judge_verdict_defaults_evidence_span_to_empty() -> None:
    # A caller may construct a verdict without an evidence span; the dataclass
    # default keeps the older two-argument constructor working.
    verdict = JudgeVerdict(leak=False, rationale="no overlap")
    assert verdict.evidence_span == ""


def test_openai_judge_requests_the_evidence_span_in_the_system_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "choices": [
            {
                "message": {
                    "content": '{"leak": false, "evidence_span": "", "rationale": "no match"}'
                }
            }
        ]
    }
    captured = _mock_urlopen(monkeypatch, payload)
    OpenAIJudge("sk-test").judge("an unrelated note", _MARKER)
    system = captured["body"]["messages"][0]["content"]
    assert captured["body"]["messages"][0]["role"] == "system"
    assert '"evidence_span"' in system
    # the body must still request JSON-mode output
    assert captured["body"]["response_format"] == {"type": "json_object"}
    # temperature pinned to 0 keeps the verdict reproducible across runs
    assert captured["body"]["temperature"] == 0


def test_openai_judge_uses_the_configured_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _mock_urlopen(
        monkeypatch,
        {"choices": [{"message": {"content": '{"leak": false}'}}]},
    )
    OpenAIJudge("sk-test", model="gpt-4o").judge("text", _MARKER)
    assert captured["body"]["model"] == "gpt-4o"


def test_openai_judge_rejects_a_malformed_chat_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_urlopen(monkeypatch, {"choices": []})
    with pytest.raises(DetectionError, match="malformed"):
        OpenAIJudge("sk-test").judge("text", _MARKER)


def test_openai_judge_propagates_a_non_json_body_as_a_detection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A model that ignores response_format and returns prose is rejected with
    # a clear DetectionError, never a silent default verdict.
    payload = {"choices": [{"message": {"content": "not a JSON object"}}]}
    _mock_urlopen(monkeypatch, payload)
    with pytest.raises(DetectionError, match="non-JSON"):
        OpenAIJudge("sk-test").judge("text", _MARKER)


def test_anthropic_judge_requests_the_evidence_span_in_the_system_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "content": [
            {
                "text": (
                    '{"leak": true, "evidence_span": "Wintergreen launches Q3", '
                    '"rationale": "matches the entity"}'
                )
            }
        ]
    }
    captured = _mock_urlopen(monkeypatch, payload)
    verdict = AnthropicJudge("sk-ant").judge("Wintergreen launches Q3 per the roadmap", _MARKER)
    assert verdict.leak is True
    assert verdict.evidence_span == "Wintergreen launches Q3"
    assert '"evidence_span"' in captured["body"]["system"]


def test_anthropic_judge_uses_the_configured_model_and_max_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _mock_urlopen(monkeypatch, {"content": [{"text": '{"leak": false}'}]})
    AnthropicJudge("sk-ant", model="claude-3-5-sonnet-latest", max_tokens=512).judge(
        "text", _MARKER
    )
    assert captured["body"]["model"] == "claude-3-5-sonnet-latest"
    assert captured["body"]["max_tokens"] == 512


def test_anthropic_judge_rejects_a_malformed_messages_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_urlopen(monkeypatch, {"content": []})
    with pytest.raises(DetectionError, match="malformed"):
        AnthropicJudge("sk-ant").judge("text", _MARKER)


def test_anthropic_judge_propagates_a_non_json_body_as_a_detection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"content": [{"text": "I cannot answer that"}]}
    _mock_urlopen(monkeypatch, payload)
    with pytest.raises(DetectionError, match="non-JSON"):
        AnthropicJudge("sk-ant").judge("text", _MARKER)


def test_openai_embedder_uses_the_configured_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _mock_urlopen(monkeypatch, {"data": [{"embedding": [0.5, 0.5]}]})
    OpenAIEmbeddingProvider("sk-test", base_url="https://example.com/v1/", timeout=12.0).embed(
        "hello"
    )
    assert captured["url"] == "https://example.com/v1/embeddings"


def test_openai_embedder_defaults_to_text_embedding_3_small(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _mock_urlopen(monkeypatch, {"data": [{"embedding": [0.1, 0.2]}]})
    OpenAIEmbeddingProvider("sk-test").embed("hello")
    assert captured["body"]["model"] == "text-embedding-3-small"


# --- detection-pipeline integration -----------------------------------------


class _StubEmbedder:
    """Embedder that opens the threshold for one chosen marker only.

    The detection pipeline tokenises the marker plaintext (the same
    ``_TOKEN_RE`` used here) and embeds each window of that size. This stub
    returns a constant unit vector along axis 0 when every chosen-marker
    token is present in the input text, and an orthogonal vector keyed on
    the SHA-256 of the text otherwise. The chosen marker therefore scores
    cosine 1 against any window that contains its tokens, while every other
    foreign marker and every unrelated window score near zero - the test
    drives exactly one ENTITY_CANARY through the judge.
    """

    _DIM = 256

    def __init__(self, marker: Marker) -> None:
        import re as _re

        self._marker = marker
        self._token_re = _re.compile(r"[a-z0-9]+")
        self._marker_tokens = set(self._token_re.findall(marker.plaintext.lower()))

    def embed(self, text: str) -> tuple[float, ...]:
        import hashlib as _h

        vector = [0.0] * self._DIM
        text_tokens = set(self._token_re.findall(text.lower()))
        if self._marker_tokens and self._marker_tokens.issubset(text_tokens):
            vector[0] = 1.0
            return tuple(vector)
        digest = _h.sha256(text.encode("utf-8")).digest()
        for offset in range(0, 16, 2):
            index = 1 + (int.from_bytes(digest[offset : offset + 2], "big") % (self._DIM - 1))
            vector[index] += 1.0
        norm = sum(v * v for v in vector) ** 0.5
        return tuple(v / norm for v in vector) if norm else tuple(vector)


class _StubJudge:
    """A judge that returns a fixed verdict, recording its calls."""

    def __init__(self, verdict: JudgeVerdict) -> None:
        self.calls: list[tuple[str, Marker]] = []
        self._verdict = verdict

    def judge(self, observed_text: str, marker: Marker) -> JudgeVerdict:
        self.calls.append((observed_text, marker))
        return self._verdict


def _entity_substrate() -> tuple[Marker, UUID, UUID, Any]:
    """Build a minimal substrate with one foreign ENTITY_CANARY for pipeline tests."""
    from sectum_ai.substrate import build_substrate, default_scenario

    substrate = build_substrate(default_scenario(seed=77))
    owner = substrate.tenants[0].tenant_id
    observer = substrate.tenants[1].tenant_id
    entity = next(
        marker
        for marker in substrate.manifest.markers
        if marker.owner_tenant_id == owner and marker.marker_type is MarkerType.ENTITY_CANARY
    )
    return entity, owner, observer, substrate


def test_detection_pipeline_carries_judge_evidence_span_into_the_finding() -> None:
    entity, _owner, observer, substrate = _entity_substrate()
    quoted = "the quarterly review mentions " + entity.plaintext
    pipeline = DetectionPipeline(
        substrate,
        embedder=_StubEmbedder(entity),
        judge=_StubJudge(
            JudgeVerdict(leak=True, rationale="entity surfaces", evidence_span=quoted)
        ),
        semantic_threshold=0.5,
    )
    findings = pipeline.detect(observer, quoted, Surface.VECTOR_DB)
    confirmed = [f for f in findings if f.status is FindingStatus.CONFIRMED]
    assert len(confirmed) == 1
    # the judge's quoted span reaches the finding (the audit pack quotes it)
    assert confirmed[0].evidence_span == quoted
    assert confirmed[0].marker_id == entity.marker_id


def test_detection_pipeline_falls_back_to_marker_when_judge_omits_span() -> None:
    entity, _owner, observer, substrate = _entity_substrate()
    text = "the quarterly review mentions " + entity.plaintext
    pipeline = DetectionPipeline(
        substrate,
        embedder=_StubEmbedder(entity),
        # An older judge that returns only ``leak`` (no evidence_span). The
        # finding must still get an auditor-readable evidence_span: the
        # marker plaintext is the safe fallback.
        judge=_StubJudge(JudgeVerdict(leak=True, rationale="entity surfaces")),
        semantic_threshold=0.5,
    )
    findings = pipeline.detect(observer, text, Surface.VECTOR_DB)
    confirmed = [f for f in findings if f.status is FindingStatus.CONFIRMED]
    assert len(confirmed) == 1
    assert confirmed[0].evidence_span == entity.plaintext


def test_verdict_parses_a_fenced_json_response() -> None:
    # Claude-family models commonly fence JSON despite the system instruction;
    # the parser must extract the object rather than abort the whole run.
    fenced = '```json\n{"leak": true, "evidence_span": "x", "rationale": "r"}\n```'
    verdict = _verdict_from_json(fenced)
    assert verdict.leak and verdict.evidence_span == "x"


def test_verdict_still_rejects_a_braceless_response() -> None:
    with pytest.raises(DetectionError):
        _verdict_from_json("no json here at all")
