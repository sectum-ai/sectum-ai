"""Live agent adapters.

Each module here connects to one real agent backend and is imported explicitly
(for example ``from sectum_ai.adapters.agent.http import HttpAgent``,
``from sectum_ai.adapters.agent.langgraph import LangGraphAgent``,
``from sectum_ai.adapters.agent.autogen import AutoGenAgent``,
``from sectum_ai.adapters.agent.crewai import CrewAIAgent``,
``from sectum_ai.adapters.agent.openai_assistants import OpenAIAssistantsAgent``, or
``from sectum_ai.adapters.agent.anthropic_tooluse import AnthropicToolUseAgent``).
"""
