"""Opt-in live integration test for the hosted RPR-sweep embedders.

Skipped unless the provider's key is set (the engineering spec, section 13: opt-in
live). Enable with the extra and the key:

    pip install "sectum-ai[cohere]"   COHERE_API_KEY=...
    pip install "sectum-ai[voyage]"   VOYAGE_API_KEY=...

The parsing and resolution are covered offline by ``tests/unit/test_embeddings.py``;
this exercises the real ``embed`` round-trip.
"""

import os

import pytest

from sectum_ai.embeddings import resolve_embedding_model
from sectum_ai.spec import ConfigError

pytestmark = pytest.mark.live

_TEXTS = ["Acme Robotics SOC 2 report", "a benign unrelated sentence"]


def _check(spec: str) -> None:
    try:
        # the SDK is imported (and the key re-checked) in the constructor, so a
        # key set without the extra installed skips rather than fails.
        model = resolve_embedding_model(spec)
    except ConfigError as error:
        pytest.skip(f"{spec} not runnable: {error}")
    assert model is not None
    vectors = model.embed(_TEXTS)
    assert len(vectors) == len(_TEXTS)
    # every text yields a same-length, non-empty float vector
    assert all(len(v) == len(vectors[0]) and v for v in vectors)
    assert all(isinstance(x, float) for x in vectors[0])


@pytest.mark.skipif(
    not os.environ.get("COHERE_API_KEY"),
    reason="set COHERE_API_KEY to run the live Cohere embedding test",
)
def test_cohere_embeds_against_the_live_api() -> None:
    _check(f"cohere:{os.environ.get('SECTUM_COHERE_MODEL', 'embed-english-v3.0')}")


@pytest.mark.skipif(
    not os.environ.get("VOYAGE_API_KEY"),
    reason="set VOYAGE_API_KEY to run the live Voyage embedding test",
)
def test_voyage_embeds_against_the_live_api() -> None:
    _check(f"voyage:{os.environ.get('SECTUM_VOYAGE_MODEL', 'voyage-3')}")


@pytest.mark.skipif(
    not os.environ.get("AWS_REGION"),
    reason="set AWS_REGION (+ AWS credentials) to run the live Bedrock embedding test",
)
def test_bedrock_embeds_against_the_live_api() -> None:
    _check(f"bedrock:{os.environ.get('SECTUM_BEDROCK_MODEL', 'amazon.titan-embed-text-v2:0')}")
