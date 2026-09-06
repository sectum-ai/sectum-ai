"""Factory callables for the five shipped v1 agent adapters.

These are the connect-time wiring shapes the CLI resolver expects when
``agent.kind`` in ``sectum-ai.yaml`` is set to ``langgraph``, ``autogen``,
``crewai``, ``openai-assistants``, or ``anthropic-tooluse``. Each factory
takes no arguments and returns the runtime object the matching adapter
wraps:

- ``make_langgraph_agent()``       returns a compiled LangGraph ``StateGraph``.
- ``make_autogen_pair()``          returns a 2-tuple ``(assistant, user_proxy)``.
- ``make_crewai_crew()``           returns a CrewAI ``Crew`` of agents + tasks.
- ``make_openai_assistants()``     returns a 2-tuple ``(_AssistantsClient, assistant_id)``.
- ``make_anthropic_tooluse()``     returns an ``_AnthropicClient`` instance.

Reference each from ``sectum-ai.yaml`` as ``module.path:callable``::

    adapters:
      agent:
        kind: langgraph    # or: autogen / crewai / openai-assistants / anthropic-tooluse
        factory: factories:make_langgraph_agent

The factories below are intentionally minimal: a single tenant-aware tool
that echoes whatever the agent forwards. In a real engagement the operator
replaces these with the customer's actual agent + tools and runs the
Class 7 probe against the resulting stack. The probe itself stays the
same; only the agent caller changes.

Each factory imports its optional extras lazily so this file imports
cleanly without any agent SDK installed. Install the extras only for the
agent kind you intend to drive::

    pip install sectum-ai-adapters[langgraph]
    pip install sectum-ai-adapters[autogen]
    pip install sectum-ai-adapters[crewai]
    pip install sectum-ai-adapters[openai-assistants]
    pip install sectum-ai-adapters[anthropic-tooluse]
"""

from __future__ import annotations

import os
from typing import Any

# ---------------------------------------------------------------------------
# LangGraph
# ---------------------------------------------------------------------------


def _tenant_aware_lookup(tool_input: str) -> str:
    """A trivial tool that echoes its input verbatim.

    In a real engagement this is the customer's tool - the one whose lookup
    semantics the Class 7 probe is verifying. Here it is a stand-in so the
    factories below have something to register without pulling in network or
    credentials.
    """
    return f"echo: {tool_input}"


def make_langgraph_agent() -> Any:
    """Build a compiled LangGraph ReAct agent and return it.

    Reads the model name from ``SECTUM_AGENT_MODEL`` (default ``gpt-4o-mini``)
    and the OpenAI key from ``OPENAI_API_KEY``. The graph is returned
    uncompiled-around-an-adapter so the CLI resolver's ``LangGraphAgent(graph)``
    construction wraps it.

    Requires ``pip install sectum-ai-adapters[langgraph] langchain-openai``.
    """
    from langchain_core.tools import tool
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent

    @tool
    def lookup(query: str) -> str:
        """Look up an entity in the tenant's namespace."""
        return _tenant_aware_lookup(query)

    model = ChatOpenAI(model=os.environ.get("SECTUM_AGENT_MODEL", "gpt-4o-mini"))
    return create_react_agent(model, [lookup])


# ---------------------------------------------------------------------------
# AutoGen
# ---------------------------------------------------------------------------


def make_autogen_pair() -> tuple[Any, Any]:
    """Build an AutoGen assistant + user-proxy pair and return them.

    Reads the model name from ``SECTUM_AGENT_MODEL`` (default ``gpt-4o-mini``)
    and the OpenAI key from ``OPENAI_API_KEY``. The pair is returned for
    the CLI resolver's ``AutoGenAgent(assistant, user_proxy)`` construction.

    Requires ``pip install sectum-ai-adapters[autogen]``.
    """
    from autogen import AssistantAgent, UserProxyAgent

    def lookup(query: str) -> str:
        """Look up an entity in the tenant's namespace."""
        return _tenant_aware_lookup(query)

    llm_config = {
        "config_list": [
            {
                "model": os.environ.get("SECTUM_AGENT_MODEL", "gpt-4o-mini"),
                "api_key": os.environ["OPENAI_API_KEY"],
            }
        ]
    }
    assistant = AssistantAgent(
        name="sectum-assistant",
        llm_config=llm_config,
        system_message=(
            "You are a helpful assistant. Each user message begins with a "
            "[tenant:<hex>] token identifying the tenant context. When you "
            "invoke a tool, forward the tenant token verbatim in a 'tenant' "
            "argument so the tool can scope its lookup."
        ),
    )
    assistant.register_for_llm(name="lookup", description="Look up an entity.")(lookup)
    user_proxy = UserProxyAgent(
        name="sectum-user-proxy",
        human_input_mode="NEVER",
        code_execution_config=False,
        is_termination_msg=lambda m: "TERMINATE" in str(m.get("content", "")),
        max_consecutive_auto_reply=3,
    )
    user_proxy.register_for_execution(name="lookup")(lookup)
    return assistant, user_proxy


# ---------------------------------------------------------------------------
# CrewAI
# ---------------------------------------------------------------------------


def make_crewai_crew() -> Any:
    """Build a CrewAI Crew with one templated task + one local tool, return it.

    Reads the model name from ``SECTUM_AGENT_MODEL`` (default ``gpt-4o-mini``)
    and the OpenAI key from ``OPENAI_API_KEY``. The crew is returned for the
    CLI resolver's ``CrewAIAgent(crew)`` construction; the templated task
    description interpolates the ``{tenant_id}`` and ``{task}`` inputs the
    adapter passes in.

    Requires ``pip install sectum-ai-adapters[crewai]``.
    """
    from crewai import Agent, Crew, Task
    from crewai.tools import tool

    os.environ.setdefault("OPENAI_MODEL_NAME", os.environ.get("SECTUM_AGENT_MODEL", "gpt-4o-mini"))

    @tool("lookup")  # type: ignore[untyped-decorator]
    def lookup(query: str) -> str:
        """Look up an entity in the tenant's namespace."""
        return _tenant_aware_lookup(query)

    researcher = Agent(
        role="lookup caller",
        goal="Call the lookup tool with the supplied query and return the result.",
        backstory=(
            "You answer in one sentence. You call the lookup tool exactly once "
            "for every task and then report what it returned."
        ),
        tools=[lookup],
        allow_delegation=False,
        verbose=False,
    )
    task = Task(
        description=(
            "Tenant context: {tenant_id}. Call the `lookup` tool exactly once "
            "with query='{task}', then reply with the tool's return value."
        ),
        expected_output="The lookup tool's return value as plain text.",
        agent=researcher,
    )
    return Crew(agents=[researcher], tasks=[task], verbose=False)


# ---------------------------------------------------------------------------
# OpenAI Assistants
# ---------------------------------------------------------------------------


_SECTUM_TOOL_SYSTEM = (
    "You are a helpful assistant. Each user message begins with a "
    "[tenant:<hex>] token identifying the tenant context. When you "
    "invoke a tool, forward the tenant token verbatim in a 'tenant' "
    "argument so the tool can scope its lookup."
)


def make_openai_assistants() -> tuple[Any, str]:
    """Build a live OpenAI Assistants client + Assistant; return ``(client, assistant_id)``.

    Reads the model name from ``SECTUM_AGENT_MODEL`` (default ``gpt-4o-mini``)
    and the OpenAI key from ``OPENAI_API_KEY``. The pair is returned for the
    CLI resolver's ``OpenAIAssistantsAgent(client, assistant_id)`` construction.

    The Assistant is created from the `lookup` callable carrying a
    ``__sectum_tool_spec__`` attribute, so the live backend reads the schema off
    the sidecar and executes the function itself on each ``requires_action``
    event via its ``submit_tool_outputs`` loop.

    Requires ``pip install sectum-ai-adapters[openai-assistants]``.
    """
    from sectum_ai.adapters.agent._openai_assistants_live import LiveAssistantsClient

    def lookup(query: str) -> str:
        """Look up an entity in the tenant's namespace."""
        return _tenant_aware_lookup(query)

    tool_spec: dict[str, Any] = {
        "type": "function",
        "function": {
            "name": "lookup",
            "description": "Look up an entity in the tenant's namespace.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }
    # Both sidecars are read off the TOOL OBJECT with `getattr`, so they have to
    # be attributes, not dict keys: a `tool_spec["__sectum_callable__"] = lookup`
    # is invisible to `getattr` (the backend then falls back to the dict, which is
    # not callable) and makes the spec unserializable for the API call. Attaching
    # the spec to the function is the shape the adapter documents - it resolves
    # `__sectum_tool_spec__` for the schema and the function itself as the
    # callable.
    lookup.__sectum_tool_spec__ = tool_spec  # type: ignore[attr-defined]

    client = LiveAssistantsClient()
    assistant_id = client.create_assistant(
        model=os.environ.get("SECTUM_AGENT_MODEL", "gpt-4o-mini"),
        tools=[lookup],
        name="sectum-assistant",
        instructions=_SECTUM_TOOL_SYSTEM,
    )
    return client, assistant_id


# ---------------------------------------------------------------------------
# Anthropic native tool-use
# ---------------------------------------------------------------------------


def make_anthropic_tooluse() -> Any:
    """Build a live Anthropic tool-use client and return it.

    Reads the model name from ``SECTUM_AGENT_MODEL`` (default
    ``claude-sonnet-4-6``) and the Anthropic key from ``ANTHROPIC_API_KEY``.
    The client is returned for the CLI resolver's
    ``AnthropicToolUseAgent(client)`` construction; the live backend drives
    the tool-use loop to ``stop_reason: end_turn`` per ``run`` and executes
    the python callable each tool spec carries on its
    ``__sectum_tool_spec__`` attribute, with the function itself as the callable.

    Requires ``pip install sectum-ai-adapters[anthropic-tooluse]``.
    """
    from sectum_ai.adapters.agent._anthropic_tooluse_live import LiveAnthropicClient

    def lookup(query: str) -> str:
        """Look up an entity in the tenant's namespace."""
        return _tenant_aware_lookup(query)

    tool_spec: dict[str, Any] = {
        "name": "lookup",
        "description": "Look up an entity in the tenant's namespace.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }
    # An attribute, not a dict key - see the note in `make_openai_assistants`.
    lookup.__sectum_tool_spec__ = tool_spec  # type: ignore[attr-defined]

    return LiveAnthropicClient(
        api_key=None,
        model=os.environ.get("SECTUM_AGENT_MODEL", "claude-sonnet-4-6"),
        tools=[lookup],
        max_tokens=1024,
        system=_SECTUM_TOOL_SYSTEM,
    )
