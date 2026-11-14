"""Compatibility helpers for Anthropic-compatible providers with nonstandard thinking.

MiniMax's Anthropic-compatible endpoint can stream thinking as a Python-dict-like
string in normal text content instead of Anthropic thinking blocks. This adapter
keeps the normal Anthropic behavior intact and lifts those leaked blocks into
``additional_kwargs.reasoning_content`` when they can be parsed.
"""

from __future__ import annotations

from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk, ChatResult

from src.models.minimax_thinking import sanitize_minimax_anthropic_thinking_text


def _append_reasoning(additional_kwargs: dict[str, Any], reasoning: str) -> None:
    existing = additional_kwargs.get("reasoning_content")
    if isinstance(existing, str) and existing:
        if reasoning not in existing:
            additional_kwargs["reasoning_content"] = f"{existing}\n{reasoning}"
    else:
        additional_kwargs["reasoning_content"] = reasoning
    additional_kwargs.setdefault("reasoning", additional_kwargs["reasoning_content"])


def normalize_minimax_anthropic_message(message: AIMessage | AIMessageChunk) -> None:
    """Normalize leaked thinking on an Anthropic LangChain message in-place."""

    if isinstance(message.content, str):
        if "thinking" not in message.content:
            return

        sanitized = sanitize_minimax_anthropic_thinking_text(message.content)
        if sanitized.reasoning is None:
            return

        message.content = sanitized.content
        _append_reasoning(message.additional_kwargs, sanitized.reasoning)
        return

    if not isinstance(message.content, list):
        return

    normalized_content: list[str | dict] = []
    reasoning_parts: list[str] = []
    changed = False
    for block in message.content:
        if isinstance(block, str):
            sanitized = sanitize_minimax_anthropic_thinking_text(block)
            if sanitized.reasoning is not None:
                changed = True
                reasoning_parts.append(sanitized.reasoning)
                if sanitized.content:
                    normalized_content.append(sanitized.content)
            else:
                normalized_content.append(block)
            continue

        if (
            isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ):
            sanitized = sanitize_minimax_anthropic_thinking_text(block["text"])
            if sanitized.reasoning is not None:
                changed = True
                reasoning_parts.append(sanitized.reasoning)
                if sanitized.content:
                    normalized_block = dict(block)
                    normalized_block["text"] = sanitized.content
                    normalized_content.append(normalized_block)
            else:
                normalized_content.append(block)
            continue

        normalized_content.append(block)

    if changed:
        message.content = normalized_content
        _append_reasoning(
            message.additional_kwargs,
            "\n".join(part for part in reasoning_parts if part),
        )


class MiniMaxAnthropicCompatChatAnthropic(ChatAnthropic):
    """ChatAnthropic with a no-op-safe MiniMax thinking compatibility shim."""

    def _format_output(self, data: Any, **kwargs: Any) -> ChatResult:
        result = super()._format_output(data, **kwargs)
        for generation in result.generations:
            if isinstance(generation.message, AIMessage):
                normalize_minimax_anthropic_message(generation.message)
        return result

    def _stream(self, *args: Any, **kwargs: Any):
        for chunk in super()._stream(*args, **kwargs):
            if isinstance(chunk, ChatGenerationChunk) and isinstance(
                chunk.message, AIMessageChunk
            ):
                normalize_minimax_anthropic_message(chunk.message)
            yield chunk
