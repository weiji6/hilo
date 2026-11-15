"""Agent exports without eagerly importing the orchestration dependency graph."""

from .thread_state import SandboxState, ThreadState

__all__ = ["make_lead_agent", "SandboxState", "ThreadState"]


def __getattr__(name):
    if name == "make_lead_agent":
        from .lead_agent import make_lead_agent

        return make_lead_agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
