"""The scenario runner: executes a probe against a substrate via adapters.

The engineering spec section 12 places the runner in core; with ADR-0004 the
package graph stays acyclic (core depends on probes, never the reverse).
"""

from sectum.adapters import (
    AgentAdapter,
    CacheAdapter,
    MCPAdapter,
    MemoryAdapter,
    ModelAdapter,
    ObservabilityAdapter,
    RAGPipelineAdapter,
    VectorStoreAdapter,
)
from sectum.probes import Probe, confirmed_findings
from sectum.spec import (
    AdapterError,
    CorpusDocument,
    Finding,
    Observation,
    ProbeStep,
    Substrate,
    Surface,
)

StepResult = tuple[ProbeStep, list[Finding]]
"""One planned step paired with the findings it produced."""


class Runner:
    """Runs a probe end to end: plan, execute each step via adapters, detect."""

    def __init__(
        self,
        substrate: Substrate,
        *,
        vector: VectorStoreAdapter | None = None,
        cache: CacheAdapter | None = None,
        model: ModelAdapter | None = None,
        mcp: MCPAdapter | None = None,
        memory: MemoryAdapter | None = None,
        rag: RAGPipelineAdapter | None = None,
        observability: ObservabilityAdapter | None = None,
        agent: AgentAdapter | None = None,
    ) -> None:
        self._substrate = substrate
        self._vector = vector
        self._cache = cache
        self._model = model
        self._mcp = mcp
        self._memory = memory
        self._rag = rag
        self._observability = observability
        self._agent = agent

    def run_per_step(self, probe: Probe) -> list[StepResult]:
        """Plan and run the probe, pairing each step with the findings it produced."""
        results: list[StepResult] = []
        for step in probe.plan(self._substrate):
            observation = self._execute(step)
            results.append((step, probe.detect(step, observation, self._substrate)))
        return results

    def run(self, probe: Probe) -> list[Finding]:
        """Plan the probe, execute every step, and return all findings."""
        return [finding for _, findings in self.run_per_step(probe) for finding in findings]

    def _execute(self, step: ProbeStep) -> Observation:
        if step.action == "vector.query":
            return self._vector_query(step)
        if step.action == "vector.fetch":
            return self._vector_fetch(step)
        if step.action == "vector.upsert":
            return self._vector_upsert(step)
        if step.action == "cache.set":
            return self._cache_set(step)
        if step.action == "cache.get":
            return self._cache_get(step)
        if step.action == "model.train":
            return self._model_train(step)
        if step.action == "model.infer":
            return self._model_infer(step)
        if step.action == "mcp.invoke":
            return self._mcp_invoke(step)
        if step.action == "memory.write":
            return self._memory_write(step)
        if step.action == "memory.recall":
            return self._memory_recall(step)
        if step.action == "rag.ask":
            return self._rag_ask(step)
        if step.action == "observability.search":
            return self._observability_search(step)
        if step.action == "agent.run":
            return self._agent_run(step)
        raise AdapterError(f"runner cannot execute action: {step.action!r}")

    def _vector_query(self, step: ProbeStep) -> Observation:
        if self._vector is None:
            raise AdapterError("a vector.query step needs a vector adapter")
        k = int(step.payload.get("k", "5"))
        hits = self._vector.query(step.actor_tenant_id, step.payload["query"], k)
        return Observation(
            step_id=step.step_id,
            surface=Surface.VECTOR_DB,
            raw_response="\n".join(hit.content for hit in hits),
        )

    def _vector_fetch(self, step: ProbeStep) -> Observation:
        if self._vector is None:
            raise AdapterError("a vector.fetch step needs a vector adapter")
        hit = self._vector.fetch(step.actor_tenant_id, step.payload["doc_id"])
        return Observation(
            step_id=step.step_id,
            surface=Surface.VECTOR_DB,
            raw_response=hit.content if hit is not None else "",
        )

    def _vector_upsert(self, step: ProbeStep) -> Observation:
        if self._vector is None:
            raise AdapterError("a vector.upsert step needs a vector adapter")
        document = CorpusDocument(
            doc_id=step.payload["doc_id"],
            tenant_id=step.actor_tenant_id,
            doc_type="poison",
            title=step.payload["doc_id"],
            content=step.payload["content"],
        )
        self._vector.upsert(step.actor_tenant_id, [document])
        return Observation(step_id=step.step_id, surface=Surface.VECTOR_DB, raw_response="")

    def _cache_set(self, step: ProbeStep) -> Observation:
        if self._cache is None:
            raise AdapterError("a cache.set step needs a cache adapter")
        self._cache.set(step.actor_tenant_id, step.payload["key"], step.payload["value"])
        return Observation(step_id=step.step_id, surface=Surface.SEMANTIC_CACHE, raw_response="")

    def _cache_get(self, step: ProbeStep) -> Observation:
        if self._cache is None:
            raise AdapterError("a cache.get step needs a cache adapter")
        value = self._cache.get(step.actor_tenant_id, step.payload["key"])
        return Observation(
            step_id=step.step_id,
            surface=Surface.SEMANTIC_CACHE,
            raw_response=value or "",
        )

    def _model_train(self, step: ProbeStep) -> Observation:
        if self._model is None:
            raise AdapterError("a model.train step needs a model adapter")
        self._model.train_adapter(step.actor_tenant_id, [step.payload["text"]])
        return Observation(step_id=step.step_id, surface=Surface.MODEL_ADAPTER, raw_response="")

    def _model_infer(self, step: ProbeStep) -> Observation:
        if self._model is None:
            raise AdapterError("a model.infer step needs a model adapter")
        response = self._model.infer(step.actor_tenant_id, step.payload["prompt"])
        return Observation(
            step_id=step.step_id,
            surface=Surface.MODEL_ADAPTER,
            raw_response=response,
        )

    def _mcp_invoke(self, step: ProbeStep) -> Observation:
        if self._mcp is None:
            raise AdapterError("an mcp.invoke step needs an MCP adapter")
        arguments = {key: value for key, value in step.payload.items() if key != "tool"}
        result = self._mcp.invoke(step.actor_tenant_id, step.payload["tool"], arguments)
        return Observation(
            step_id=step.step_id,
            surface=Surface.MCP,
            raw_response=result.output,
        )

    def _memory_write(self, step: ProbeStep) -> Observation:
        if self._memory is None:
            raise AdapterError("a memory.write step needs a memory adapter")
        self._memory.remember(step.actor_tenant_id, step.payload["text"])
        return Observation(step_id=step.step_id, surface=Surface.AGENT_MEMORY, raw_response="")

    def _memory_recall(self, step: ProbeStep) -> Observation:
        if self._memory is None:
            raise AdapterError("a memory.recall step needs a memory adapter")
        recalled = self._memory.recall(step.actor_tenant_id, step.payload["query"])
        return Observation(
            step_id=step.step_id,
            surface=Surface.AGENT_MEMORY,
            raw_response="\n".join(recalled),
        )

    def _rag_ask(self, step: ProbeStep) -> Observation:
        if self._rag is None:
            raise AdapterError("a rag.ask step needs a rag adapter")
        answer = self._rag.ask(step.actor_tenant_id, step.payload["query"])
        return Observation(
            step_id=step.step_id,
            surface=Surface.RAG_PIPELINE,
            raw_response=answer.answer,
        )

    def _observability_search(self, step: ProbeStep) -> Observation:
        if self._observability is None:
            raise AdapterError("an observability.search step needs an observability adapter")
        hits = self._observability.search_traces(step.actor_tenant_id, step.payload["marker"])
        return Observation(
            step_id=step.step_id,
            surface=Surface.TRACING,
            raw_response="\n".join(hit.snippet for hit in hits),
        )

    def _agent_run(self, step: ProbeStep) -> Observation:
        if self._agent is None:
            raise AdapterError("an agent.run step needs an agent adapter")
        result = self._agent.run(step.actor_tenant_id, step.payload["task"])
        return Observation(
            step_id=step.step_id,
            surface=Surface.AGENT_FRAMEWORK,
            raw_response=result.output,
        )


def retrieval_pivot_rate(step_results: list[StepResult]) -> float:
    """Fraction of benign steps that surfaced a confirmed cross-tenant leak.

    The Class 2 headline metric, the Retrieval-Pivot Rate (the engineering spec,
    section 7).
    """
    if not step_results:
        return 0.0
    pivoted = sum(1 for _, findings in step_results if confirmed_findings(findings))
    return pivoted / len(step_results)
