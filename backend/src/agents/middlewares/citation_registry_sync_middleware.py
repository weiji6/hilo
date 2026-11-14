"""Middleware to ensure knowledge_citation_registry is explicitly written back to LangGraph state.

Tools currently mutate state["knowledge_citation_registry"] in-place via
register_citation_marker(). This works by accident in single-threaded execution
because LastValue channels return direct object references, but it is NOT
reliable across LangGraph supersteps, subgraph calls, or checkpointing.

This middleware syncs the registry back into the state channel:
1. Immediately after every tool call (via wrap_tool_call / awrap_tool_call)
2. After every model turn (via after_model / aafter_model)

This double-sync ensures the registry survives both tool→model superstep
transitions and subgraph boundary serialization.
"""

from typing import Any, override

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Command
from langgraph.typing import ContextT

from src.agents.thread_state import ThreadState
from src.community.knowledge_base.citations import KNOWLEDGE_CITATION_REGISTRY_KEY


class CitationRegistrySyncMiddleware(AgentMiddleware[ThreadState]):
    """Sync citation registry from runtime.state back to the LangGraph channel."""

    @override
    def after_model(self, state: ThreadState, runtime: Runtime[ContextT]) -> dict[str, Any] | None:
        raw_registry = state.get(KNOWLEDGE_CITATION_REGISTRY_KEY)
        if isinstance(raw_registry, list) and raw_registry:
            # Return a shallow copy so LangGraph sees a "new" value and triggers channel update.
            return {KNOWLEDGE_CITATION_REGISTRY_KEY: list(raw_registry)}
        return None

    @override
    async def aafter_model(self, state: ThreadState, runtime: Runtime[ContextT]) -> dict[str, Any] | None:
        return self.after_model(state, runtime)

    def _sync_registry(self, request) -> Command | None:
        raw_registry = request.state.get(KNOWLEDGE_CITATION_REGISTRY_KEY)
        if isinstance(raw_registry, list) and raw_registry:
            return Command(
                update={
                    KNOWLEDGE_CITATION_REGISTRY_KEY: list(raw_registry),
                }
            )
        return None

    @override
    def wrap_tool_call(self, request, handler):
        result = handler(request)
        registry_command = self._sync_registry(request)
        if registry_command is None:
            return result
        if isinstance(result, ToolMessage):
            registry_command.update["messages"] = [result]
            return registry_command
        if isinstance(result, Command):
            if KNOWLEDGE_CITATION_REGISTRY_KEY not in result.update:
                result.update[KNOWLEDGE_CITATION_REGISTRY_KEY] = registry_command.update[KNOWLEDGE_CITATION_REGISTRY_KEY]
            return result
        return result

    @override
    async def awrap_tool_call(self, request, handler):
        result = await handler(request)
        registry_command = self._sync_registry(request)
        if registry_command is None:
            return result
        if isinstance(result, ToolMessage):
            registry_command.update["messages"] = [result]
            return registry_command
        if isinstance(result, Command):
            if KNOWLEDGE_CITATION_REGISTRY_KEY not in result.update:
                result.update[KNOWLEDGE_CITATION_REGISTRY_KEY] = registry_command.update[KNOWLEDGE_CITATION_REGISTRY_KEY]
            return result
        return result
