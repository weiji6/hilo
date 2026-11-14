"""Track the current reading set and nudge the model to cover unread books."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.community.knowledge_base.reading_state import get_active_reading_state, get_uncovered_doc_ids

logger = logging.getLogger(__name__)

READING_ROUTE_TOOL_NAMES = {"knowledge_search", "knowledge_locate", "write_todos", "task"}
REMINDER_SOURCE_TOOL_NAMES = {
    "book_search",
    "knowledge_search",
    "knowledge_locate",
    "knowledge_checkpoint",
    "write_todos",
}
RETRY_APPENDICES = (
    "系统插入提示（不是用户的新问题）：当前阅读集仍有未覆盖书目。"
    "你刚才试图在未读完阅读集前直接起草答案。"
    "现在不要直接回答；如果你是主任务，下一步应针对未覆盖书目写 `书 × 信息目标` todo 并派发子任务；"
    "子任务再调用 `knowledge_locate(doc_id=...)` 做目录、章节页、命中页或连续页阅读。"
    "不要用 `knowledge_search(doc_ids=...)`，并且尽量不要再次只围绕已覆盖书继续展开。",
    "系统再次插入提示（不是用户的新问题）：当前阅读集仍未覆盖完整。"
    "请把下一步改成针对未覆盖书目的子任务派发；子任务负责 `knowledge_locate` 定位阅读。"
    "不要直接回答，不要跳过这些书。",
)


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


class BookCoverageMiddleware(AgentMiddleware[AgentState]):
    """Remind and block when the current reading set still has unread books."""

    def _should_inject_reminder(self, messages: list) -> bool:
        if not messages:
            return False
        last_message = messages[-1]
        return isinstance(last_message, ToolMessage) and getattr(last_message, "name", None) in REMINDER_SOURCE_TOOL_NAMES

    def _build_reminder(self, state: AgentState) -> HumanMessage | None:
        reading_set, titles, covered, query = get_active_reading_state(state)
        unread = get_uncovered_doc_ids(state)
        if not reading_set or not unread:
            return None

        covered_set = set(covered)
        lines = [
            "系统插入提示（不是用户的新问题）：`book_search` 已经为当前问题建立了阅读集。",
            "不要只根据当前已经读过的一本书继续深挖并直接收尾；相关书目需要逐本覆盖后再综合。",
        ]
        if query:
            lines.append(f"当前问题：`{query}`")
        lines.append(f"当前阅读集共 {len(reading_set)} 本，已覆盖 {len(covered_set)} 本，未覆盖 {len(unread)} 本。")
        lines.append("仍需优先覆盖的书目：")
        for doc_id in unread:
            title = titles.get(doc_id) or doc_id
            lines.append(f"- {title} (`{doc_id}`)")
        lines.append(
            "下一步优先针对这些未覆盖书目派发 `书 × 信息目标` 子任务；"
            "子任务至少做一次针对性的 `knowledge_locate`，确认它们各自能提供什么证据，再继续综合。"
            "不要把未覆盖书目的 `doc_ids` 传给 `knowledge_search`。"
        )
        return HumanMessage(content="\n".join(lines))

    def _prepare_request(self, request: ModelRequest) -> ModelRequest:
        reminder = self._build_reminder(request.state)
        if reminder is None or not self._should_inject_reminder(request.messages):
            return request
        return request.override(messages=[*request.messages, reminder])

    def _response_is_direct_answer(self, response: ModelResponse) -> bool:
        ai_messages = [message for message in response.result if isinstance(message, AIMessage)]
        if not ai_messages:
            return False
        final_message = ai_messages[-1]
        if getattr(final_message, "tool_calls", None):
            return False
        return bool(_stringify_content(final_message.content).strip())

    def _response_moves_to_unread_books(self, response: ModelResponse, state: AgentState) -> bool:
        unread = set(get_uncovered_doc_ids(state))
        if not unread:
            return True

        ai_messages = [message for message in response.result if isinstance(message, AIMessage)]
        if not ai_messages:
            return True

        final_message = ai_messages[-1]
        tool_calls = getattr(final_message, "tool_calls", None) or []
        if not tool_calls:
            return False

        route_calls = [tool_call for tool_call in tool_calls if tool_call.get("name") in READING_ROUTE_TOOL_NAMES]
        if not route_calls:
            return True

        unread_titles = {
            str(state.get("knowledge_reading_set_titles", {}).get(doc_id) or "").strip()
            for doc_id in unread
        }
        unread_titles.discard("")

        for tool_call in route_calls:
            args = tool_call.get("args", {}) or {}
            if tool_call.get("name") == "knowledge_locate":
                doc_id = str(args.get("doc_id") or "").strip()
                if doc_id and doc_id in unread:
                    return True
            elif tool_call.get("name") == "write_todos":
                todos = args.get("todos") or []
                todo_text = _stringify_content(todos)
                if any(doc_id in todo_text for doc_id in unread) or any(title in todo_text for title in unread_titles):
                    return True
            elif tool_call.get("name") == "task":
                task_text = _stringify_content(args)
                if any(doc_id in task_text for doc_id in unread) or any(title in task_text for title in unread_titles):
                    return True

        return False

    def _build_retry_request(self, request: ModelRequest, appendix: str) -> ModelRequest:
        reminder = self._build_reminder(request.state)
        messages = list(request.messages)
        if reminder is not None:
            messages.append(reminder)
        messages.append(HumanMessage(content=appendix))
        return request.override(messages=messages)

    def _enforce_with_retry(
        self,
        request: ModelRequest,
        response: ModelResponse,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        unread = get_uncovered_doc_ids(request.state)
        if not unread:
            return response
        if not self._response_is_direct_answer(response) and self._response_moves_to_unread_books(response, request.state):
            return response

        retry_request = request
        retry_response = response
        for appendix in RETRY_APPENDICES:
            retry_request = self._build_retry_request(retry_request, appendix)
            retry_response = handler(retry_request)
            if not self._response_is_direct_answer(retry_response):
                return retry_response

        logger.warning(
            "BookCoverageMiddleware could not redirect the model back to unread books. unread=%s",
            get_uncovered_doc_ids(request.state),
        )
        return retry_response

    async def _aenforce_with_retry(
        self,
        request: ModelRequest,
        response: ModelResponse,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        unread = get_uncovered_doc_ids(request.state)
        if not unread:
            return response
        if not self._response_is_direct_answer(response) and self._response_moves_to_unread_books(response, request.state):
            return response

        retry_request = request
        retry_response = response
        for appendix in RETRY_APPENDICES:
            retry_request = self._build_retry_request(retry_request, appendix)
            retry_response = await handler(retry_request)
            if not self._response_is_direct_answer(retry_response):
                return retry_response

        logger.warning(
            "BookCoverageMiddleware could not redirect the model back to unread books. unread=%s",
            get_uncovered_doc_ids(request.state),
        )
        return retry_response

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        prepared_request = self._prepare_request(request)
        response = handler(prepared_request)
        return self._enforce_with_retry(prepared_request, response, handler)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        prepared_request = self._prepare_request(request)
        response = await handler(prepared_request)
        return await self._aenforce_with_retry(prepared_request, response, handler)
