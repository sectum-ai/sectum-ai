"""Mock-backed contract tests for the live LangChain RAG adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest

from sectum.adapters.base import RAGPipelineAdapter
from sectum.adapters.rag.langchain import LangChainRAGPipeline
from sectum.spec import AdapterError

_TENANT = UUID(int=0xA)


@dataclass
class _FakeChain:
    """Stand-in for a LangChain ``Runnable``: records inputs, returns a script."""

    output: Any = ""
    inputs: list[dict[str, Any]] = field(default_factory=list)
    raise_on_invoke: Exception | None = None

    def invoke(self, input: dict[str, Any]) -> Any:
        if self.raise_on_invoke is not None:
            raise self.raise_on_invoke
        self.inputs.append(input)
        return self.output


@dataclass
class _FakeDocument:
    """Stand-in for a LangChain ``Document``: ``page_content`` + ``metadata``."""

    page_content: str
    metadata: dict[str, Any] = field(default_factory=dict)


def test_langchain_rag_conforms_to_the_family() -> None:
    adapter = LangChainRAGPipeline(_FakeChain())
    assert isinstance(adapter, RAGPipelineAdapter)
    assert adapter.name == "langchain-rag"


def test_langchain_rag_passes_tenant_and_query_into_the_chain() -> None:
    chain = _FakeChain(output={"answer": "the answer", "retrieved": []})
    adapter = LangChainRAGPipeline(chain)
    adapter.ask(_TENANT, "the question")
    assert chain.inputs == [{"tenant": str(_TENANT), "query": "the question"}]


def test_langchain_rag_returns_answer_string_unchanged() -> None:
    adapter = LangChainRAGPipeline(_FakeChain(output="just a string answer"))
    result = adapter.ask(_TENANT, "hello")
    assert result.answer == "just a string answer"
    assert result.retrieved == ()


def test_langchain_rag_unpacks_a_dict_response_with_retrieved_hits() -> None:
    chain = _FakeChain(
        output={
            "answer": "the answer",
            "retrieved": [
                {"doc_id": "d-1", "content": "alpha", "score": 0.9},
                {"doc_id": "d-2", "content": "beta"},
            ],
        }
    )
    result = LangChainRAGPipeline(chain).ask(_TENANT, "q")
    assert result.answer == "the answer"
    assert len(result.retrieved) == 2
    assert result.retrieved[0].doc_id == "d-1"
    assert result.retrieved[0].content == "alpha"
    assert result.retrieved[0].score == pytest.approx(0.9)
    assert result.retrieved[1].score == pytest.approx(1.0)  # default


def test_langchain_rag_reads_result_key_as_answer() -> None:
    # langchain's legacy `RetrievalQA` chain returns {"result": ...}.
    chain = _FakeChain(output={"result": "legacy chain output", "source_documents": []})
    result = LangChainRAGPipeline(chain).ask(_TENANT, "q")
    assert result.answer == "legacy chain output"


def test_langchain_rag_unpacks_source_documents_as_retrieved_hits() -> None:
    chain = _FakeChain(
        output={
            "result": "answer",
            "source_documents": [
                _FakeDocument(
                    page_content="hit-1 body",
                    metadata={"doc_id": "src-1", "score": 0.7},
                ),
                _FakeDocument(page_content="hit-2 body"),
            ],
        }
    )
    result = LangChainRAGPipeline(chain).ask(_TENANT, "q")
    assert result.retrieved[0].doc_id == "src-1"
    assert result.retrieved[0].content == "hit-1 body"
    assert result.retrieved[0].score == pytest.approx(0.7)
    # Missing metadata: empty doc id and default score 1.0.
    assert result.retrieved[1].doc_id == ""
    assert result.retrieved[1].score == pytest.approx(1.0)


def test_langchain_rag_tags_every_hit_with_the_caller_tenant() -> None:
    # The adapter always stamps the *caller* tenant on every VectorHit, even
    # when a leaky retriever surfaces a foreign tenant's document; the leak
    # detector decides whether the hit's *content* matches a foreign canary.
    chain = _FakeChain(output={"answer": "a", "retrieved": [{"doc_id": "x", "content": "y"}]})
    result = LangChainRAGPipeline(chain).ask(_TENANT, "q")
    assert result.retrieved[0].tenant_id == _TENANT


def test_langchain_rag_rejects_a_non_dict_non_string_response() -> None:
    chain = _FakeChain(output=12345)
    with pytest.raises(AdapterError, match="must return a string or a dict"):
        LangChainRAGPipeline(chain).ask(_TENANT, "q")


def test_langchain_rag_wraps_chain_exceptions_in_adapter_error() -> None:
    chain = _FakeChain(raise_on_invoke=RuntimeError("rate limited"))
    adapter = LangChainRAGPipeline(chain)
    with pytest.raises(AdapterError, match="langchain rag invoke failed"):
        adapter.ask(_TENANT, "q")


def test_langchain_rag_handles_missing_answer_and_empty_retrieved() -> None:
    chain = _FakeChain(output={})
    result = LangChainRAGPipeline(chain).ask(_TENANT, "q")
    assert result.answer == ""
    assert result.retrieved == ()
