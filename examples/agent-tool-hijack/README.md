# Agent tool-call hijack — Class 7 from the agent-adapter side

This example reproduces **Attack Class 7**: cross-tenant agent tool-call
hijacking. Where the [`mcp-tenant-boundary`](../mcp-tenant-boundary/)
walkthrough tells the story from the MCP-server end (the leaky lookup
service), this one tells it from the *agent* end (the framework that
makes the call) — and shows how to swap the agent caller between the
seven shipped agent adapters (`fake`, `http`, `langgraph`, `autogen`,
`crewai`, `openai-assistants`, `anthropic-tooluse`) for the companion
`agent-framework-hijack` probe, which drives the agent adapter directly.

## The attack

An agent that loses tenant scope on the way to a tool invocation is a
confused deputy. Tenant B asks the agent for "the customer record
matching X"; the agent's tool call lands at a backend that resolves X
without checking *which* tenant asked; the response carries tenant A's
record into tenant B's session. The same agent that does this on an
MCP server does it on a Pinecone lookup, a Snowflake query, or a
custom REST endpoint — anywhere the agent's tool layer trusts the
caller without re-authenticating tenant context.

This is **OWASP LLM08:2025 — Vector and Embedding Weaknesses**, on
the agentic tool-call surface. The 2025 Asana MCP cross-tenant flaw
([Coalition for Secure AI](https://www.coalitionforsecureai.org/))
was a real-world instance: ~1,000 enterprises affected by the
token-passthrough pattern.

## What the demo does

`run.sh` runs the canonical Class 7 probe end to end against the
in-memory leaky MCP server:

1. **`sectum-ai seed`** provisions four synthetic tenants (Acme, Globex,
   Initech, Hooli) and their canary markers.
2. **`sectum-ai probe --probe agent-tool-hijack`** issues, per hard
   canary, four sub-probes from every *foreign* principal — a direct
   lookup (confused-deputy), a token-bearing lookup (token-passthrough),
   a lookup routed through a downstream server (cross-server
   confused-deputy), and a search whose attacker-authored tool
   description smuggles the foreign coordinate (tool-description
   injection).
3. **`sectum-ai report`** assembles a tamper-evident evidence pack
   (JSON + PDF).
4. **`sectum-ai verify`** independently re-checks the pack.

The probe today exercises the MCP surface (Class 7 v1 per the
engineering spec, §7);
this example's value is the *next step*: showing how to wire the
agent that calls the MCP server in production — LangGraph, AutoGen,
or CrewAI — so the operator can verify Class 7 with the same caller
their customers actually run.

## Run it

```sh
./run.sh
```

You'll see three confirmed leaks per canary — one per foreign
principal — for 24 confirmed cross-tenant findings in total. The PDF's
`Findings` section itemises each.

## Swap the agent caller

`agent.kind` selects the agent adapter that the **`agent-framework-hijack`**
probe drives (`--probe agent-framework-hijack`). The `agent-tool-hijack` probe
in `run.sh` drives the MCP adapter (`mcp.invoke` steps) and is unaffected by
`agent.kind` — see "Which probe drives which adapter" below. The default (no
config) is the in-memory `FakeAgent`. To drive the framework probe through a real
agent runtime, point `agent.kind` at one of the five factory-driven adapters
below and name a `factory` callable that constructs the runtime object (`http`
needs only a URL; `fake` needs nothing).

The factories in this directory live in `factories.py`, which is **not** on the
import path by default — the directory is hyphenated and has no package marker.
Put it on the path and use the bare module name:

```sh
# Run from THIS directory (the commands below use dir-relative paths);
# `factories.py` lives here and a hyphenated dir is not on the import path.
export PYTHONPATH=.
```

[`factories.py`](factories.py) in this directory holds copy-pasteable
factory functions for each agent kind. Pick the one your stack uses
and reference it from `sectum-ai.yaml`:

### LangGraph

```yaml
adapters:
  agent:
    kind: langgraph
    factory: factories:make_langgraph_agent
    recursion_limit: 25
```

```sh
pip install sectum-ai-adapters[langgraph] langchain-openai
export OPENAI_API_KEY=sk-...
# Save the YAML block above as `sectum-ai.yaml` in this directory first —
# the example ships no config file.
sectum-ai probe --probe agent-framework-hijack --config sectum-ai.yaml --workdir out
```

The LangGraph adapter scopes by `thread_id`: each probe step passes
the actor tenant's hex into `config={"configurable": {"thread_id":
tenant.hex}}`, so a per-thread checkpoint or memory cannot bleed
across tenants. The adapter surfaces every tool the graph called
during a run — what the Class 7 probe needs to see.

### AutoGen

```yaml
adapters:
  agent:
    kind: autogen
    factory: factories:make_autogen_pair
    max_turns: 4
```

```sh
pip install sectum-ai-adapters[autogen]
export OPENAI_API_KEY=sk-...
# Save the YAML block above as `sectum-ai.yaml` in this directory first —
# the example ships no config file.
sectum-ai probe --probe agent-framework-hijack --config sectum-ai.yaml --workdir out
```

The AutoGen adapter scopes by prefixing every user-proxy message with
a `[tenant:<hex>]` token; the system prompt instructs the assistant
to forward the token into tool-call arguments. Tools wired with
tenant-aware routing read the scope from their `tenant` argument and
fail closed on a missing or mismatched token.

### CrewAI

```yaml
adapters:
  agent:
    kind: crewai
    factory: factories:make_crewai_crew
    input_key: task
    tenant_key: tenant_id
```

```sh
pip install sectum-ai-adapters[crewai]
export OPENAI_API_KEY=sk-...
# Save the YAML block above as `sectum-ai.yaml` in this directory first —
# the example ships no config file.
sectum-ai probe --probe agent-framework-hijack --config sectum-ai.yaml --workdir out
```

The CrewAI adapter scopes by passing `tenant_id` as a named input to
`crew.kickoff(inputs={...})`; the crew's task descriptions
interpolate `{tenant_id}` so the task body carries the tenant context
into the language model's prompt and, from there, into the tool-call
arguments.

### OpenAI Assistants

```yaml
adapters:
  agent:
    kind: openai-assistants
    factory: factories:make_openai_assistants
```

```sh
pip install sectum-ai-adapters[openai-assistants]
export OPENAI_API_KEY=sk-...
# Save the YAML block above as `sectum-ai.yaml` in this directory first —
# the example ships no config file.
sectum-ai probe --probe agent-framework-hijack --config sectum-ai.yaml --workdir out
```

The OpenAI Assistants adapter scopes by caching one `Thread` per
tenant — created on first use and reused on every subsequent call,
so a tool that scopes by `thread_id` cannot bleed across tenants.
Each per-tenant user message is prefixed with `[tenant:<hex>]`; the
Assistant instructions forward the token into a `tenant` tool
argument the tenant-aware tool reads.

### Anthropic native tool-use

```yaml
adapters:
  agent:
    kind: anthropic-tooluse
    factory: factories:make_anthropic_tooluse
```

```sh
pip install sectum-ai-adapters[anthropic-tooluse]
export ANTHROPIC_API_KEY=sk-ant-...
# Save the YAML block above as `sectum-ai.yaml` in this directory first —
# the example ships no config file.
sectum-ai probe --probe agent-framework-hijack --config sectum-ai.yaml --workdir out
```

The Anthropic tool-use adapter scopes by caching one conversation
history per tenant; each per-tenant user message is prefixed with
`[tenant:<hex>]` and the tool-use loop runs to `stop_reason:
end_turn`. Tools attach a python callable via the
`__sectum_tool_spec__` attribute on each tool callable; the live backend
executes it on every `tool_use` block and posts the result back as a
`tool_result` user message.

### HTTP (generic JSON agent)

```yaml
adapters:
  agent:
    kind: http
    url: https://agent.example.com/run
    timeout: 30.0
```

The HTTP adapter is the lowest-common-denominator caller: it POSTs
`{tenant, task}` to the URL and parses `{output, tool_calls}` back.
Useful when the customer's agent framework is something the OSS does
not yet have a live adapter for — they expose a thin JSON endpoint
in front of it and point Sectum at the URL.

## What the report tells you

The evidence pack itemises every confused-deputy and
token-passthrough leak the probe confirmed: per-finding marker ID,
owning tenant, observing tenant, the leaked tool result, OWASP /
ATLAS / NIST control IDs. Class 7 findings carry no per-finding remediation
pointer. The headline
on page 1 is the count of confirmed Class 7 leaks under the
configured agent.

Switching the agent kind does **not** change what counts as a leak —
the substrate, the canary detection pipeline, and the evidence chain
are all adapter-agnostic. A leak detected with `FakeAgent` is a leak
detected with `CrewAIAgent`, `OpenAIAssistantsAgent`, or
`AnthropicToolUseAgent`; the only thing that varies is how the probe
steps reach the leaky tool. That's the design point: the attestation
pack speaks the same language to a DPO regardless of which framework
the customer ran their probe against.

## Which probe drives which adapter

Two Class 7 probes ship. `agent-tool-hijack` (this example's `run.sh`) drives the
**MCP adapter** — every step is an `mcp.invoke` — and models confused-deputy and
token-passthrough at the tool boundary. `agent-framework-hijack` drives the
**agent adapter** with `agent.run` steps and inspects the framework's own tool
calls; that is the probe the `agent.kind` swap above feeds. Both surface as
Class 7 in the scorecard.
