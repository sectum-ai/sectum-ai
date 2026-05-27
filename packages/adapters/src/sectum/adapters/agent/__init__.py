"""Live agent adapters.

Each module here connects to one real agent backend and is imported explicitly
(for example ``from sectum.adapters.agent.http import HttpAgent``,
``from sectum.adapters.agent.langgraph import LangGraphAgent``,
``from sectum.adapters.agent.autogen import AutoGenAgent``,
``from sectum.adapters.agent.crewai import CrewAIAgent``,
``from sectum.adapters.agent.openai_assistants import OpenAIAssistantsAgent``, or
``from sectum.adapters.agent.anthropic_tooluse import AnthropicToolUseAgent``).
"""
