"""Summarization middleware that preserves a freshly produced final answer turn."""

from __future__ import annotations

from typing import Any

from langchain.agents import AgentState
from langchain.agents.middleware import SummarizationMiddleware
from langgraph.runtime import Runtime
from langchain_core.messages import AIMessage, HumanMessage


def _stringify_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content or "")


class OutputAwareSummarizationMiddleware(SummarizationMiddleware):
    """Skip summarization right after the assistant has produced a full answer."""

    def _is_final_ai_answer(self, message: object) -> bool:
        if not isinstance(message, AIMessage):
            return False
        if getattr(message, "tool_calls", None):
            return False

        content = _stringify_content(message.content).strip()
        if not content:
            return False

        return True

    def _should_preserve_fresh_final_answer(self, messages: list) -> bool:
        if not messages:
            return False

        latest_message = messages[-1]
        if self._is_final_ai_answer(latest_message):
            return True

        if len(messages) < 2:
            return False

        previous_message = messages[-2]
        if not isinstance(latest_message, HumanMessage):
            return False
        if not self._is_final_ai_answer(previous_message):
            return False
        return True

    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if self._should_preserve_fresh_final_answer(messages):
            return None
        return super().before_model(state, runtime)

    async def abefore_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if self._should_preserve_fresh_final_answer(messages):
            return None
        return await super().abefore_model(state, runtime)
