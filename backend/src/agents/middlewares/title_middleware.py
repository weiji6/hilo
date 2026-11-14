"""Middleware for automatic thread title generation."""

import re
from typing import Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from src.config.title_config import get_title_config
from src.models import create_chat_model

_FINAL_TITLE_PATTERNS = (
    re.compile(r"^\s*(?:final\s+answer|title)\s*[:：]\s*(.+?)\s*$", re.IGNORECASE),
    re.compile(r"^\s*(?:最终标题|标题)\s*[:：]\s*(.+?)\s*$", re.IGNORECASE),
)
_REASONING_LINE_PATTERNS = (
    re.compile(r"^\s*thinking\s+process\b", re.IGNORECASE),
    re.compile(r"^\s*analy[sz]e\b", re.IGNORECASE),
    re.compile(r"^\s*(?:input|task|constraints?)\s*[:：]", re.IGNORECASE),
    re.compile(r"^\s*(?:drafting|selection)\b", re.IGNORECASE),
    re.compile(r"^\s*(?:let'?s|i will|i need to)\b", re.IGNORECASE),
)


def _stringify_message_content(content: Any) -> str:
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


def _split_title_lines(text: str) -> list[str]:
    return [line.strip().strip('"').strip("'") for line in text.splitlines() if line.strip()]


def _looks_like_reasoning_line(line: str) -> bool:
    if len(line) > 80:
        return True
    if line.startswith(("-", "*")):
        return True
    return any(pattern.match(line) for pattern in _REASONING_LINE_PATTERNS)


def _looks_like_title(line: str, *, max_chars: int, max_words: int) -> bool:
    if not line:
        return False
    if len(line) > max_chars:
        return False
    if len(line.split()) > max_words:
        return False
    if _looks_like_reasoning_line(line):
        return False
    return True


def _extract_title_from_response_text(text: str, *, max_chars: int, max_words: int) -> str:
    raw = text.strip().strip('"').strip("'")
    if not raw:
        return ""

    for pattern in _FINAL_TITLE_PATTERNS:
        for line in _split_title_lines(raw):
            match = pattern.match(line)
            if match:
                candidate = match.group(1).strip().strip('"').strip("'")
                if _looks_like_title(candidate, max_chars=max_chars, max_words=max_words):
                    return candidate[:max_chars]

    lines = _split_title_lines(raw)
    plausible = [
        line for line in lines if _looks_like_title(line, max_chars=max_chars, max_words=max_words)
    ]
    if plausible:
        return min(plausible, key=len)[:max_chars]

    return raw[:max_chars]


def _build_title_model():
    config = get_title_config()
    return create_chat_model(name=config.model_name, thinking_enabled=False)


def _build_title_prompt(user_msg: str) -> str:
    config = get_title_config()
    return config.prompt_template.format(max_words=config.max_words, user_msg=user_msg[:500])


def _parse_title_response(content: str) -> str:
    config = get_title_config()
    title = _extract_title_from_response_text(content, max_chars=config.max_chars, max_words=config.max_words)
    return title[: config.max_chars]


def title_from_query(user_msg: str) -> str:
    """Return a title derived directly from the user query (no LLM call)."""
    config = get_title_config()
    fallback_chars = min(config.max_chars, 50)
    if len(user_msg) > fallback_chars:
        return user_msg[:fallback_chars].rstrip() + "..."
    return user_msg if user_msg else "New Conversation"


# Keep the old private name as an alias so existing callers don't break.
_title_fallback = title_from_query


def generate_title_candidate(user_msg: str) -> str:
    """Generate a concise title (sync, for tests / non-async callers)."""
    try:
        model = _build_title_model()
        response = model.invoke(_build_title_prompt(user_msg))
        return _parse_title_response(str(response.content) if response.content else "")
    except Exception as e:
        print(f"Failed to generate title: {e}")
        return _title_fallback(user_msg)


async def agenerate_title_candidate(user_msg: str) -> str:
    """Generate a concise title without blocking the event loop."""
    try:
        model = _build_title_model()
        response = await model.ainvoke(_build_title_prompt(user_msg))
        return _parse_title_response(str(response.content) if response.content else "")
    except Exception as e:
        print(f"Failed to generate title: {e}")
        return _title_fallback(user_msg)


class TitleMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    title: NotRequired[str | None]


class TitleMiddleware(AgentMiddleware[TitleMiddlewareState]):
    """Automatically generate a title for the thread after the first user message."""

    state_schema = TitleMiddlewareState

    def _should_generate_title(self, state: TitleMiddlewareState) -> bool:
        """Check if we should generate a title for this thread."""
        config = get_title_config()
        if not config.enabled:
            return False

        # Check if thread already has a title in state
        if state.get("title"):
            return False

        # Check if this is the first turn (has at least one user message and one assistant response)
        messages = state.get("messages", [])
        if len(messages) < 2:
            return False

        # Count user and assistant messages
        user_messages = [m for m in messages if m.type == "human"]
        assistant_messages = [m for m in messages if m.type == "ai"]

        # Generate title after first complete exchange
        return len(user_messages) == 1 and len(assistant_messages) >= 1

    def _get_user_msg(self, state: TitleMiddlewareState) -> str:
        messages = state.get("messages", [])
        user_msg_content = next((m.content for m in messages if m.type == "human"), "")
        return _stringify_message_content(user_msg_content) if user_msg_content else ""

    def _extract_title_from_response(self, text: str, *, max_chars: int, max_words: int) -> str:
        """Instance-level shim for the module-level ``_extract_title_from_response_text`` helper."""
        return _extract_title_from_response_text(text, max_chars=max_chars, max_words=max_words)

    @override
    def after_agent(self, state: TitleMiddlewareState, runtime: Runtime) -> dict | None:
        """Sync fallback — only called when the graph runs in a purely synchronous context."""
        if self._should_generate_title(state):
            title = _title_fallback(self._get_user_msg(state))
            print(f"Generated thread title: {title}")
            return {"title": title}
        return None

    @override
    async def aafter_agent(self, state: TitleMiddlewareState, runtime: Runtime) -> dict | None:
        """Use the user's first message directly as the thread title (no LLM call needed)."""
        if self._should_generate_title(state):
            title = _title_fallback(self._get_user_msg(state))
            print(f"Generated thread title: {title}")
            return {"title": title}
        return None
