"""Patched ChatOpenAI that preserves OpenAI-compatible reasoning fields.

Some OpenAI-compatible providers return chain-of-thought text in `reasoning`
instead of LangChain's expected `additional_kwargs.reasoning_content`.
This adapter normalizes both non-streaming and streaming responses so the rest
of the app can keep reading `reasoning_content`.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI


def _extract_reasoning(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None

    for key in ("reasoning_content", "reasoning"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    reasoning_details = payload.get("reasoning_details")
    if isinstance(reasoning_details, list):
        parts: list[str] = []
        for item in reasoning_details:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
        if parts:
            return "\n".join(parts)
    return None


class PatchedChatOpenAIReasoning(ChatOpenAI):
    """ChatOpenAI variant that maps provider reasoning fields into reasoning_content."""

    def _create_chat_result(
        self,
        response: dict | Any,
        generation_info: dict | None = None,
    ) -> ChatResult:
        result = super()._create_chat_result(response, generation_info)
        response_dict = response if isinstance(response, dict) else response.model_dump()
        choices = response_dict.get("choices") or []

        for generation, choice in zip(result.generations, choices):
            message_payload = choice.get("message")
            reasoning = _extract_reasoning(message_payload)
            if (
                reasoning
                and isinstance(generation.message, AIMessage)
                and "reasoning_content" not in generation.message.additional_kwargs
            ):
                generation.message.additional_kwargs["reasoning_content"] = reasoning
                generation.message.additional_kwargs.setdefault("reasoning", reasoning)
        return result

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk,
            default_chunk_class,
            base_generation_info,
        )
        if generation_chunk is None:
            return None

        choices = chunk.get("choices") or chunk.get("chunk", {}).get("choices", [])
        if not choices:
            return generation_chunk

        delta = choices[0].get("delta")
        reasoning = _extract_reasoning(delta)
        if (
            reasoning
            and isinstance(generation_chunk.message, AIMessageChunk)
            and "reasoning_content" not in generation_chunk.message.additional_kwargs
        ):
            generation_chunk.message.additional_kwargs["reasoning_content"] = reasoning
            generation_chunk.message.additional_kwargs.setdefault("reasoning", reasoning)
        return generation_chunk
