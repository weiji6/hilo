"""Tests for SubagentToolLimitMiddleware."""

import asyncio

import pytest
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.agents.middlewares.subagent_tool_limit_middleware import (
    TOOL_CALL_LIMIT,
    SubagentToolLimitMiddleware,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_TOOL = object()  # sentinel representing a bound tool


def _build_request(messages: list, tools: list | None = None) -> ModelRequest:
    return ModelRequest(
        model=object(),
        messages=messages,
        system_message=SystemMessage(content="You are a helpful subagent."),
        tools=tools if tools is not None else [_FAKE_TOOL],
    )


def _text_response() -> ModelResponse:
    """Plain text response — no tool calls."""
    return ModelResponse(result=[AIMessage(content="Here is my final answer.")])


def _tool_call_response() -> ModelResponse:
    """Response that still calls a tool (simulate non-compliant model)."""
    return ModelResponse(
        result=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "kl-1",
                        "name": "knowledge_locate",
                        "args": {"book_id": "abc", "page": 1},
                        "type": "tool_call",
                    }
                ],
            )
        ]
    )


def _make_tool_messages(count: int) -> list:
    """Return `count` ToolMessages to simulate an exhausted budget."""
    return [
        ToolMessage(content=f"result {i}", tool_call_id=f"tc-{i}", name="knowledge_locate")
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# Sync: wrap_model_call — below limit (no-op)
# ---------------------------------------------------------------------------


class TestWrapModelCallBelowLimit:
    """When the tool-call count is below the limit, the middleware is a no-op."""

    def test_passes_through_with_original_request(self):
        middleware = SubagentToolLimitMiddleware()
        messages = _make_tool_messages(TOOL_CALL_LIMIT - 1)
        request = _build_request(messages)

        seen: list[ModelRequest] = []

        def handler(req: ModelRequest) -> ModelResponse:
            seen.append(req)
            return _text_response()

        result = middleware.wrap_model_call(request, handler)

        assert len(seen) == 1
        # Original request passed through unchanged — tools still present
        assert seen[0].tools == request.tools
        assert seen[0].messages == request.messages
        assert result.result[0].content == "Here is my final answer."

    def test_passes_through_tool_call_response_unchanged(self):
        """Below the limit the middleware doesn't intervene even if model calls tools."""
        middleware = SubagentToolLimitMiddleware()
        messages = _make_tool_messages(TOOL_CALL_LIMIT - 1)
        request = _build_request(messages)

        seen: list[ModelRequest] = []

        def handler(req: ModelRequest) -> ModelResponse:
            seen.append(req)
            return _tool_call_response()

        result = middleware.wrap_model_call(request, handler)

        assert len(seen) == 1
        assert seen[0].tools == request.tools  # tools unchanged
        assert result.result[0].tool_calls  # original tool-call response passed through


# ---------------------------------------------------------------------------
# Sync: wrap_model_call — at / above limit (tool-stripping)
# ---------------------------------------------------------------------------


class TestWrapModelCallAtLimit:
    """When tool_count >= TOOL_CALL_LIMIT the middleware must strip all tools."""

    def test_strips_tools_at_limit(self):
        """Handler receives a request with tools=[] when budget is exhausted."""
        middleware = SubagentToolLimitMiddleware()
        messages = _make_tool_messages(TOOL_CALL_LIMIT)
        request = _build_request(messages)

        seen: list[ModelRequest] = []

        def handler(req: ModelRequest) -> ModelResponse:
            seen.append(req)
            return _text_response()

        middleware.wrap_model_call(request, handler)

        assert len(seen) == 1
        assert seen[0].tools == [], "tools must be stripped to empty list at limit"

    def test_injects_wrap_up_message_at_limit(self):
        """The wrap-up HumanMessage is appended to the conversation history."""
        middleware = SubagentToolLimitMiddleware()
        messages = _make_tool_messages(TOOL_CALL_LIMIT)
        request = _build_request(messages)

        seen: list[ModelRequest] = []

        def handler(req: ModelRequest) -> ModelResponse:
            seen.append(req)
            return _text_response()

        middleware.wrap_model_call(request, handler)

        injected = [m for m in seen[0].messages if isinstance(m, HumanMessage)]
        contents = [str(m.content) for m in injected]
        assert any("上限" in c for c in contents), "wrap-up message not injected"

    def test_wrap_up_message_includes_count_and_limit(self):
        """The wrap-up message must quote the current count and the configured limit."""
        middleware = SubagentToolLimitMiddleware()
        messages = _make_tool_messages(TOOL_CALL_LIMIT)
        request = _build_request(messages)

        seen: list[ModelRequest] = []

        def handler(req: ModelRequest) -> ModelResponse:
            seen.append(req)
            return _text_response()

        middleware.wrap_model_call(request, handler)

        injected = [m for m in seen[0].messages if isinstance(m, HumanMessage)]
        wrap_up = next(str(m.content) for m in injected if "上限" in str(m.content))
        assert str(TOOL_CALL_LIMIT) in wrap_up

    def test_handler_called_exactly_once(self):
        """No retry loop — handler is called exactly once even when model would call tools."""
        middleware = SubagentToolLimitMiddleware()
        messages = _make_tool_messages(TOOL_CALL_LIMIT)
        request = _build_request(messages)

        call_count = []

        def handler(req: ModelRequest) -> ModelResponse:
            call_count.append(1)
            return _tool_call_response()  # model would call tools, but has none

        middleware.wrap_model_call(request, handler)

        assert len(call_count) == 1, "handler must be called exactly once — no retry loop"

    def test_returns_response_from_stripped_call(self):
        """Return value is whatever the handler returns for the stripped request."""
        middleware = SubagentToolLimitMiddleware()
        messages = _make_tool_messages(TOOL_CALL_LIMIT)
        request = _build_request(messages)

        def handler(req: ModelRequest) -> ModelResponse:
            return _text_response()

        result = middleware.wrap_model_call(request, handler)
        assert result.result[0].content == "Here is my final answer."

    def test_triggers_at_exactly_tool_call_limit(self):
        """Boundary: exactly TOOL_CALL_LIMIT messages should trigger enforcement."""
        middleware = SubagentToolLimitMiddleware()
        messages = _make_tool_messages(TOOL_CALL_LIMIT)
        assert len(messages) == TOOL_CALL_LIMIT

        request = _build_request(messages)
        seen: list[ModelRequest] = []

        def handler(req: ModelRequest) -> ModelResponse:
            seen.append(req)
            return _text_response()

        middleware.wrap_model_call(request, handler)
        assert seen[0].tools == [], "enforcement must trigger at exactly TOOL_CALL_LIMIT"

    def test_does_not_trigger_one_below_limit(self):
        """Boundary: TOOL_CALL_LIMIT - 1 messages should NOT trigger enforcement."""
        middleware = SubagentToolLimitMiddleware()
        messages = _make_tool_messages(TOOL_CALL_LIMIT - 1)
        request = _build_request(messages)

        seen: list[ModelRequest] = []

        def handler(req: ModelRequest) -> ModelResponse:
            seen.append(req)
            return _tool_call_response()

        result = middleware.wrap_model_call(request, handler)
        assert seen[0].tools == request.tools, "tools must not be stripped below limit"
        assert result.result[0].tool_calls  # original tool-call response passed through


# ---------------------------------------------------------------------------
# Async: awrap_model_call
# ---------------------------------------------------------------------------


class TestAWrapModelCall:
    """Async version mirrors the sync version's logic."""

    def test_passes_through_when_below_limit(self):
        async def _run():
            middleware = SubagentToolLimitMiddleware()
            messages = _make_tool_messages(TOOL_CALL_LIMIT - 1)
            request = _build_request(messages)

            seen: list[ModelRequest] = []

            async def handler(req: ModelRequest) -> ModelResponse:
                seen.append(req)
                return _tool_call_response()

            result = await middleware.awrap_model_call(request, handler)
            assert seen[0].tools == request.tools  # tools unchanged below limit
            assert result.result[0].tool_calls

        asyncio.run(_run())

    def test_strips_tools_when_at_limit(self):
        async def _run():
            middleware = SubagentToolLimitMiddleware()
            messages = _make_tool_messages(TOOL_CALL_LIMIT)
            request = _build_request(messages)
            seen: list[ModelRequest] = []

            async def handler(req: ModelRequest) -> ModelResponse:
                seen.append(req)
                return _text_response()

            result = await middleware.awrap_model_call(request, handler)

            assert len(seen) == 1
            assert seen[0].tools == [], "tools must be stripped at limit"
            assert any("上限" in str(m.content) for m in seen[0].messages if isinstance(m, HumanMessage))
            assert result.result[0].content == "Here is my final answer."

        asyncio.run(_run())

    def test_handler_called_once_at_limit(self):
        async def _run():
            middleware = SubagentToolLimitMiddleware()
            messages = _make_tool_messages(TOOL_CALL_LIMIT)
            request = _build_request(messages)
            call_count = []

            async def handler(req: ModelRequest) -> ModelResponse:
                call_count.append(1)
                return _tool_call_response()

            await middleware.awrap_model_call(request, handler)
            assert len(call_count) == 1

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# _count_tool_calls
# ---------------------------------------------------------------------------


class TestCountToolCalls:
    def test_counts_only_tool_messages(self):
        middleware = SubagentToolLimitMiddleware()
        messages = [
            HumanMessage(content="hi"),
            AIMessage(content="thinking"),
            ToolMessage(content="r1", tool_call_id="1", name="tool"),
            ToolMessage(content="r2", tool_call_id="2", name="tool"),
            AIMessage(content="ok"),
        ]
        assert middleware._count_tool_calls(messages) == 2

    def test_empty_messages(self):
        middleware = SubagentToolLimitMiddleware()
        assert middleware._count_tool_calls([]) == 0

    def test_no_tool_messages(self):
        middleware = SubagentToolLimitMiddleware()
        messages = [HumanMessage(content="hi"), AIMessage(content="hello")]
        assert middleware._count_tool_calls(messages) == 0


# ---------------------------------------------------------------------------
# _build_stripped_request
# ---------------------------------------------------------------------------


class TestBuildStrippedRequest:
    def test_tools_are_empty(self):
        middleware = SubagentToolLimitMiddleware()
        request = _build_request(_make_tool_messages(TOOL_CALL_LIMIT))
        stripped = middleware._build_stripped_request(request, TOOL_CALL_LIMIT)
        assert stripped.tools == []

    def test_wrap_up_appended_to_messages(self):
        middleware = SubagentToolLimitMiddleware()
        request = _build_request(_make_tool_messages(TOOL_CALL_LIMIT))
        stripped = middleware._build_stripped_request(request, TOOL_CALL_LIMIT)
        last_msg = stripped.messages[-1]
        assert isinstance(last_msg, HumanMessage)
        assert "上限" in str(last_msg.content)

    def test_original_messages_preserved(self):
        middleware = SubagentToolLimitMiddleware()
        orig_messages = _make_tool_messages(TOOL_CALL_LIMIT)
        request = _build_request(orig_messages)
        stripped = middleware._build_stripped_request(request, TOOL_CALL_LIMIT)
        # All original messages still present (wrap-up appended, not prepended)
        assert stripped.messages[: len(orig_messages)] == orig_messages
