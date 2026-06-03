"""Live LangChain RAG pipeline adapter.

A LangChain RAG pipeline is a composed ``Runnable`` (a retriever +
prompt + model + output parser, typically built via LCEL) that the
caller constructs once and invokes per query. This adapter wraps any
such ``Runnable`` and dispatches ``ask(tenant, query)`` through it.

The substrate verifies tenant isolation, so the per-tenant scope must
reach the underlying retriever. The adapter passes both the tenant
identifier and the query into the chain's invoke as
``{"tenant": str(tenant), "query": query}``; tenant-aware retrievers
filter on ``tenant`` and ignore it otherwise. A retriever that does
not honour ``tenant`` and shares its corpus across tenants is the
exact leak Class 2 (the flagship Retrieval-Pivot probe) is built to
detect, so the adapter passes the scope through and lets the substrate
do the verification.

Chain return shape: this adapter accepts the two common shapes:

- a string — treated as the answer text with no retrieved-source rendering;
- a mapping with ``answer`` (or ``result``) and optionally
  ``retrieved`` (or ``source_documents``); each retrieved item is
  either a mapping carrying ``doc_id``/``content``/``score`` or a
  LangChain ``Document`` with ``page_content`` + ``metadata``.

The ``langchain_core`` package is imported lazily inside
:meth:`connect`; the adapter and its mock-backed unit test need no
extra dependency. The live path requires the optional extras group:
``pip install sectum-ai-adapters[rag-langchain]``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol, Self
from uuid import UUID

from sectum_ai.adapters.base import RagAnswer, RAGPipelineAdapter, VectorHit
from sectum_ai.spec import AdapterError


class _Runnable(Protocol):
    """The minimal LangChain ``Runnable`` surface the adapter consumes."""

    def invoke(self, input: dict[str, Any]) -> Any:
        """Run the chain on ``input`` and return its output."""


class LangChainRAGPipeline(RAGPipelineAdapter):
    """A RAG pipeline backed by any LangChain ``Runnable``.

    Construct it with an open ``_Runnable`` so the adapter can be
    tested against an in-memory stand-in without the
    ``langchain_core`` package. Use :meth:`connect` for the live path
    that builds a default LCEL chain from a retriever, an LLM, and a
    prompt template.
    """

    def __init__(self, chain: _Runnable, *, name: str = "langchain-rag") -> None:
        super().__init__(name)
        self._chain = chain

    @classmethod
    def connect(
        cls,
        retriever: Any,
        llm: Any,
        *,
        prompt: Any | None = None,
        name: str = "langchain-rag",
    ) -> Self:
        """Build a default LCEL RAG chain from a retriever + LLM and wrap it.

        ``retriever`` is any LangChain retriever exposing
        ``invoke({"tenant": ..., "query": ...}) -> list[Document]``;
        a tenant-aware retriever filters on ``tenant`` and an isolated
        one ignores it. ``llm`` is any chat or completion model. The
        default ``prompt`` is a minimal QA template that conditions
        the answer on the retrieved context.

        Requires ``pip install sectum-ai-adapters[rag-langchain]``.
        """
        try:
            from langchain_core.output_parsers import StrOutputParser
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_core.runnables import RunnableLambda, RunnableParallel
        except ImportError as error:
            raise AdapterError(
                "langchain-rag adapter requires the `langchain-core` package; "
                "install sectum-ai-adapters[rag-langchain] to enable it"
            ) from error

        if prompt is None:
            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", "Answer the user's query using only the context below."),
                    ("user", "Context:\n{context}\n\nQuery: {query}"),
                ]
            )

        def _format_context(documents: Any) -> str:
            if not isinstance(documents, Iterable):
                return ""
            return "\n\n".join(_document_text(doc) for doc in documents)

        retrieval = RunnableParallel(
            {
                "context": retriever | RunnableLambda(_format_context),
                "query": RunnableLambda(lambda payload: payload["query"]),
                "retrieved": retriever,
            }
        )

        def _bundle(parts: dict[str, Any]) -> dict[str, Any]:
            answer = (prompt | llm | StrOutputParser()).invoke(
                {"context": parts["context"], "query": parts["query"]}
            )
            return {"answer": answer, "retrieved": parts["retrieved"]}

        chain: _Runnable = retrieval | RunnableLambda(_bundle)
        return cls(chain, name=name)

    def ask(self, tenant: UUID, query: str) -> RagAnswer:
        """Invoke the chain on a per-tenant query and parse the response."""
        try:
            output = self._chain.invoke({"tenant": str(tenant), "query": query})
        except Exception as error:
            raise AdapterError(f"langchain rag invoke failed: {error}") from error
        if isinstance(output, str):
            return RagAnswer(answer=output, retrieved=())
        if not isinstance(output, dict):
            raise AdapterError(
                f"langchain rag chain must return a string or a dict, got {type(output).__name__}"
            )
        answer = output.get("answer") or output.get("result") or ""
        if not isinstance(answer, str):
            answer = str(answer)
        retrieved_raw = output.get("retrieved")
        if retrieved_raw is None:
            retrieved_raw = output.get("source_documents", [])
        retrieved = tuple(_to_hit(tenant, item) for item in retrieved_raw or [])
        return RagAnswer(answer=answer, retrieved=retrieved)


def _document_text(document: Any) -> str:
    """Extract the body text from a LangChain ``Document`` or a dict-like item."""
    if isinstance(document, str):
        return document
    page_content = getattr(document, "page_content", None)
    if isinstance(page_content, str):
        return page_content
    if isinstance(document, dict):
        content = document.get("content") or document.get("page_content") or ""
        return str(content)
    return str(document)


def _to_hit(tenant: UUID, item: Any) -> VectorHit:
    """Parse one retrieved item into a ``VectorHit``."""
    if isinstance(item, dict):
        doc_id = item.get("doc_id") or item.get("id") or ""
        content = item.get("content") or item.get("page_content") or ""
        score = item.get("score", 1.0)
        return VectorHit(
            doc_id=str(doc_id),
            tenant_id=tenant,
            score=float(score) if isinstance(score, int | float) else 1.0,
            content=str(content),
        )
    # A LangChain ``Document``: ``page_content`` + ``metadata`` dict.
    metadata = getattr(item, "metadata", None) or {}
    if not isinstance(metadata, dict):
        metadata = {}
    doc_id = metadata.get("doc_id") or metadata.get("id") or ""
    score = metadata.get("score", 1.0)
    page_content = getattr(item, "page_content", "")
    return VectorHit(
        doc_id=str(doc_id),
        tenant_id=tenant,
        score=float(score) if isinstance(score, int | float) else 1.0,
        content=str(page_content),
    )
