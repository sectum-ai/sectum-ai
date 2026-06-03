# Agent-framework hijack — Class 7 from the agent caller's end

This example reproduces **Attack Class 7**: cross-tenant agent tool-call
hijacking. Where [`agent-tool-hijack`](../agent-tool-hijack/) verifies the
*MCP server* an agent calls, this walkthrough verifies the **agent
caller itself** — no MCP server in the loop. The probe inspects what
the agent framework returned to the caller; a foreign canary in the
agent's final output means the framework or its tool layer lost the
caller's tenant scope on the way to the resource.

## The attack

An agent that loses tenant scope on the way to a tool invocation is a
confused deputy. Tenant B asks the agent for "the customer record
matching X"; the agent's tool layer resolves X without checking *which*
tenant asked; the response carries tenant A's record into tenant B's
session — surfaced verbatim in the agent's final reply. The same
pattern reaches the agent layer regardless of what the tool is:
a Pinecone lookup, a Snowflake query, an internal REST endpoint, or an
MCP server. This example exercises the agent end of that pattern,
independent of which transport the tool runs over.

This is **OWASP LLM08:2025 — Vector and Embedding Weaknesses**, on
the agentic surface. The 2025 Asana MCP cross-tenant flaw
([Coalition for Secure AI](https://www.coalitionforsecureai.org/))
was a real-world instance of the token-passthrough variant; the
confused-deputy variant matches the broader pattern any agent
framework can fall into when the tool layer trusts the caller without
re-authenticating tenant context.

## What the demo does

`run.sh` runs the canonical Class 7 probe end to end against the
in-memory `FakeAgent` configured with both leak knobs on:

1. **`sectum-ai seed`** provisions four synthetic tenants (Acme, Globex,
   Initech, Hooli) and their canary markers.
2. **`sectum-ai probe --probe agent-framework-hijack`** issues, per hard
   canary, a direct `agent.run` and a token-bearing `agent.run` from
   every *foreign* principal — the confused-deputy and the
   token-passthrough patterns at the agent layer.
3. **`sectum-ai report`** assembles a tamper-evident evidence pack
   (JSON + PDF).
4. **`sectum-ai verify`** independently re-checks the pack.

You'll see confirmed leaks per canary across the configured principals.
The PDF page-3 findings table itemises each, with `surface =
agent_framework`.

## Run it

```sh
./run.sh
```

## Swap the agent caller

The probe consumes whatever `agent.kind` resolves to in
`sectum.yaml`. This example sets it to the leaky in-memory `FakeAgent`
so the demo runs without API keys. To drive the same probe through a
real agent framework, switch `agent.kind` to one of the live backends
(`langgraph`, `autogen`, `crewai`, `openai-assistants`,
`anthropic-tooluse`) and point it at a factory callable that
constructs the runtime object — the wiring snippets and ready-made
factories live in [`../agent-tool-hijack/factories.py`](../agent-tool-hijack/factories.py)
and the matching `pip install ...` lines are documented in
[`../agent-tool-hijack/README.md`](../agent-tool-hijack/README.md).

For example, to drive a LangGraph caller against the same probe:

```yaml
adapters:
  agent:
    kind: langgraph
    factory: examples.agent_tool_hijack.factories:make_langgraph_agent
    recursion_limit: 25
```

```sh
pip install sectum-ai-adapters[langgraph] langchain-openai
export OPENAI_API_KEY=sk-...
sectum-ai probe --probe agent-framework-hijack --config sectum.yaml --workdir out
```

## What the report tells you

The evidence pack itemises every confused-deputy and
token-passthrough leak the probe confirmed at the agent-framework
layer: per-finding marker ID, owning tenant, observing tenant, the
foreign canary that surfaced in the agent's output, OWASP / ATLAS /
NIST control IDs, and a remediation pointer. The headline on page 1 is
the count of confirmed Class 7 leaks under the configured agent.

Switching the agent kind does **not** change what counts as a leak —
the substrate, the canary detection pipeline, and the evidence chain
are all adapter-agnostic. A leak detected with `FakeAgent` is a leak
detected with `LangGraphAgent`, `AutoGenAgent`, `CrewAIAgent`,
`OpenAIAssistantsAgent`, or `AnthropicToolUseAgent`; only the agent
caller varies.

## Agent end vs. MCP end

Two probes exercise the same Class 7 pattern from opposite ends:

- **`agent-tool-hijack`** (`examples/agent-tool-hijack/`) — verifies
  the **MCP server** an agent calls. Tool result surface =
  `Surface.MCP`.
- **`agent-framework-hijack`** (this example) — verifies the **agent
  caller** itself. Final-output surface = `Surface.AGENT_FRAMEWORK`.

Run both in the same suite when verifying a stack that uses MCP under
the hood; either probe alone covers its end of the chain.
