"""The scenario runner: executes a probe against a substrate via adapters.

The engineering spec section 12 places the runner in core; with ADR-0004 the
package graph stays acyclic (core depends on probes, never the reverse).
"""

from sectum_ai.adapters import (
    AgentAdapter,
    CacheAdapter,
    MCPAdapter,
    MemoryAdapter,
    ModelAdapter,
    ObservabilityAdapter,
    RAGPipelineAdapter,
    VectorStoreAdapter,
)
from sectum_ai.probes import Probe, confirmed_findings
from sectum_ai.spec import (
    AccessOutcome,
    AdapterError,
    ConfigError,
    CorpusDocument,
    Finding,
    Observation,
    ProbeStep,
    Substrate,
    get_logger,
)

_log = get_logger(__name__)

StepResult = tuple[ProbeStep, list[Finding]]
"""One planned step paired with the findings it produced."""


def payload_int(step: ProbeStep, key: str, default: str) -> int:
    """Read an integer payload value, raising a typed ``AdapterError`` on bad input.

    A malformed step payload is a configuration error, not a crash: a bare
    ``ValueError`` would escape the ``SectumError`` hierarchy and the CLI's
    exit-code mapping (the engineering spec, sections 10 and 16). Public so
    ``sweep.py`` (and other in-package callers) can reuse it across modules.
    """
    raw = step.payload.get(key, default)
    try:
        return int(raw)
    except ValueError as error:
        raise AdapterError(
            f"step {step.step_id} payload {key!r} must be an integer, got {raw!r}"
        ) from error


def _payload_required(step: ProbeStep, key: str) -> str:
    """Read a required payload value, raising a typed ``AdapterError`` if absent."""
    try:
        return step.payload[key]
    except KeyError as error:
        raise AdapterError(
            f"step {step.step_id} payload is missing required key {key!r}"
        ) from error


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

    def preflight(self, probe: Probe) -> None:
        """Raise ``ConfigError`` if the probe's declared adapters are not configured.

        A probe names the adapter families it drives in ``requires_adapters`` (the
        engineering spec, §7.0 / §11). This checks them up front so an unsatisfied
        run fails fast with a clear message (exit ``3``) instead of partway through
        a probe when the first step hits a missing adapter.
        """
        missing = [slot for slot in probe.requires_adapters if getattr(self, f"_{slot}") is None]
        if missing:
            raise ConfigError(
                f"probe {probe.id!r} requires adapter(s) {', '.join(sorted(missing))}, "
                "but they are not configured"
            )

    def run_per_step(self, probe: Probe) -> list[StepResult]:
        """Plan and run the probe, pairing each step with the findings it produced."""
        self.preflight(probe)
        results: list[StepResult] = []
        for step in probe.plan(self._substrate):
            observation = self._execute(step)
            results.append((step, probe.detect(step, observation, self._substrate)))
        # Operational metadata only — step payloads and observations (tenant
        # content) are never logged here (the engineering spec, section 16).
        confirmed = sum(len(confirmed_findings(findings)) for _, findings in results)
        _log.info(
            "probe.run.complete",
            probe=probe.id,
            steps=len(results),
            findings=sum(len(findings) for _, findings in results),
            confirmed_leaks=confirmed,
        )
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
        k = payload_int(step, "k", "5")
        hits = self._vector.query(
            step.actor_tenant_id, _payload_required(step, "query"), k, user=step.actor_user_id
        )
        return Observation(
            step_id=step.step_id,
            surface=self._vector.surface,
            raw_response="\n".join(hit.content for hit in hits),
        )

    def _vector_fetch(self, step: ProbeStep) -> Observation:
        if self._vector is None:
            raise AdapterError("a vector.fetch step needs a vector adapter")
        hit = self._vector.fetch(
            step.actor_tenant_id, step.payload["doc_id"], user=step.actor_user_id
        )
        # Class 1 deny-semantics: a returned object surfaced (a leak when foreign);
        # an absent one is the ambiguous 200-empty case, not a proven deny.
        return Observation(
            step_id=step.step_id,
            surface=self._vector.surface,
            raw_response=hit.content if hit is not None else "",
            access_outcome=AccessOutcome.RETURNED if hit is not None else AccessOutcome.EMPTY,
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
            # The planting principal owns the poison, so a user-scoped store
            # filters it from a sibling user's retrieval (ADR-0006/0008).
            owner_user_id=step.actor_user_id,
        )
        self._vector.upsert(step.actor_tenant_id, [document])
        return Observation(step_id=step.step_id, surface=self._vector.surface, raw_response="")

    def _cache_set(self, step: ProbeStep) -> Observation:
        if self._cache is None:
            raise AdapterError("a cache.set step needs a cache adapter")
        self._cache.set(
            step.actor_tenant_id,
            step.payload["key"],
            step.payload["value"],
            user=step.actor_user_id,
        )
        return Observation(step_id=step.step_id, surface=self._cache.surface, raw_response="")

    def _cache_get(self, step: ProbeStep) -> Observation:
        if self._cache is None:
            raise AdapterError("a cache.get step needs a cache adapter")
        value = self._cache.get(step.actor_tenant_id, step.payload["key"], user=step.actor_user_id)
        return Observation(
            step_id=step.step_id,
            surface=self._cache.surface,
            raw_response=value or "",
        )

    def _model_train(self, step: ProbeStep) -> Observation:
        if self._model is None:
            raise AdapterError("a model.train step needs a model adapter")
        self._model.train_adapter(
            step.actor_tenant_id, [step.payload["text"]], user=step.actor_user_id
        )
        return Observation(step_id=step.step_id, surface=self._model.surface, raw_response="")

    def _model_infer(self, step: ProbeStep) -> Observation:
        if self._model is None:
            raise AdapterError("a model.infer step needs a model adapter")
        response = self._model.infer(
            step.actor_tenant_id, step.payload["prompt"], user=step.actor_user_id
        )
        # Class 9 routing assertion: record who actually served only when it is a
        # foreign tenant (a mis-route). The probe reads this to raise a routing
        # finding; a correctly-routed or unknowable inference adds no structured data.
        served_by = self._model.served_by(
            step.actor_tenant_id, step.payload["prompt"], user=step.actor_user_id
        )
        structured = (
            {"served_by_tenant": str(served_by)}
            if served_by is not None and served_by != step.actor_tenant_id
            else None
        )
        return Observation(
            step_id=step.step_id,
            surface=self._model.surface,
            raw_response=response,
            structured=structured,
        )

    def _mcp_invoke(self, step: ProbeStep) -> Observation:
        if self._mcp is None:
            raise AdapterError("an mcp.invoke step needs an MCP adapter")
        arguments = {key: value for key, value in step.payload.items() if key != "tool"}
        result = self._mcp.invoke(
            step.actor_tenant_id, step.payload["tool"], arguments, user=step.actor_user_id
        )
        return Observation(
            step_id=step.step_id,
            surface=self._mcp.surface,
            raw_response=result.output,
        )

    def _memory_write(self, step: ProbeStep) -> Observation:
        if self._memory is None:
            raise AdapterError("a memory.write step needs a memory adapter")
        self._memory.remember(step.actor_tenant_id, step.payload["text"], user=step.actor_user_id)
        return Observation(step_id=step.step_id, surface=self._memory.surface, raw_response="")

    def _memory_recall(self, step: ProbeStep) -> Observation:
        if self._memory is None:
            raise AdapterError("a memory.recall step needs a memory adapter")
        recalled = self._memory.recall(
            step.actor_tenant_id, step.payload["query"], user=step.actor_user_id
        )
        return Observation(
            step_id=step.step_id,
            surface=self._memory.surface,
            raw_response="\n".join(recalled),
        )

    def _rag_ask(self, step: ProbeStep) -> Observation:
        if self._rag is None:
            raise AdapterError("a rag.ask step needs a rag adapter")
        answer = self._rag.ask(step.actor_tenant_id, step.payload["query"])
        return Observation(
            step_id=step.step_id,
            surface=self._rag.surface,
            raw_response=answer.answer,
        )

    def _observability_search(self, step: ProbeStep) -> Observation:
        if self._observability is None:
            raise AdapterError("an observability.search step needs an observability adapter")
        hits = self._observability.search_traces(step.actor_tenant_id, step.payload["marker"])
        return Observation(
            step_id=step.step_id,
            surface=self._observability.surface,
            raw_response="\n".join(hit.snippet for hit in hits),
        )

    def _agent_run(self, step: ProbeStep) -> Observation:
        if self._agent is None:
            raise AdapterError("an agent.run step needs an agent adapter")
        result = self._agent.run(step.actor_tenant_id, step.payload["task"])
        return Observation(
            step_id=step.step_id,
            surface=self._agent.surface,
            raw_response=result.output,
        )


def confirmed_finding_rate(step_results: list[StepResult]) -> float:
    """Fraction of steps that surfaced at least one confirmed cross-tenant leak.

    The shared denominator for every probe whose headline metric is "how often did
    a benign step surface a foreign canary": Class 2's Retrieval-Pivot Rate, plus
    Class 3 poisoning bleed, Class 6 inversion reconstruction, and Class 10
    extraction efficiency (the engineering spec, section 7). Callers pass the
    subset of steps for the probe (and action) they are measuring.
    """
    if not step_results:
        return 0.0
    pivoted = sum(1 for _, findings in step_results if confirmed_findings(findings))
    return pivoted / len(step_results)


def retrieval_pivot_rate(step_results: list[StepResult]) -> float:
    """Fraction of benign steps that surfaced a confirmed cross-tenant leak.

    The Class 2 headline metric, the Retrieval-Pivot Rate (the engineering spec,
    section 7); an alias of :func:`confirmed_finding_rate` kept for call-site
    clarity at the flagship probe.
    """
    return confirmed_finding_rate(step_results)


def retrieval_pivot_counts(step_results: list[StepResult]) -> tuple[int, int]:
    """Return the binomial counts ``(k, n)`` behind the Retrieval-Pivot Rate.

    ``n`` is the number of benign cross-tenant query steps and ``k`` is how many
    surfaced at least one confirmed foreign canary, so ``k / n`` is exactly the
    rate :func:`retrieval_pivot_rate` reports (for ``n > 0``). The counts are
    recorded in :class:`~sectum_ai.spec.RunMetrics` so the rate's Wilson
    confidence interval is reproducible from the signed evidence rather than only
    from a rounded point estimate.

    Args:
        step_results: The Class 2 bleed steps with their detected findings.

    Returns:
        A ``(k, n)`` pair; ``(0, 0)`` for an empty input.
    """
    n = len(step_results)
    k = sum(1 for _, findings in step_results if confirmed_findings(findings))
    return k, n
