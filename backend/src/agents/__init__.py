"""Agent exports without eagerly importing the orchestration dependency graph."""

from langchain_core.runnables import RunnableConfig

from .thread_state import SandboxState, ThreadState

__all__ = ["make_lead_agent", "SandboxState", "ThreadState"]


def make_lead_agent(config: RunnableConfig):
    """Keep a concrete export for LangGraph's module dictionary discovery."""
    from .lead_agent import make_lead_agent as build_agent

    return build_agent(config)
