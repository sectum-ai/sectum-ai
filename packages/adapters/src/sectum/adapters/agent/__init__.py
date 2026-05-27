"""Live agent adapters.

Each module here connects to one real agent backend and is imported explicitly
(for example ``from sectum.adapters.agent.http import HttpAgent``,
``from sectum.adapters.agent.langgraph import LangGraphAgent``,
``from sectum.adapters.agent.autogen import AutoGenAgent``, or
``from sectum.adapters.agent.crewai import CrewAIAgent``).
"""
