"""Compress old knowledge tool outputs and enforce checkpoint cadence."""

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from src.agents.retrieval_policy import overview_from_messages

GROUNDING_TOOL_NAMES = {"knowledge_search", "knowledge_locate"}
CHECKPOINT_TOOL_NAME = "knowledge_checkpoint"
COMPRESSIBLE_TOOL_NAMES = GROUNDING_TOOL_NAMES | {CHECKPOINT_TOOL_NAME}
CHECKPOINT_ENFORCEMENT_THRESHOLD = 5
NON_SUBSTANTIVE_MARKERS = (
    "本轮没有命中到可直接使用的内部知识片段",
    "no matching page/paragraph/line context found",
    "no likely books found for this query",
    "当前对话已限定在所选资料范围内，但这些资料里没有找到匹配的候选书目",
)
CHECKPOINT_RETRY_APPENDICES = (
    "系统插入提示（不是用户的新问题）：本轮自上次 checkpoint 以来，已经积累了多条有效的 "
    "`knowledge_search` / `knowledge_locate` 检索结果。\n"
    "你下一步必须且只能调用一次 `knowledge_checkpoint`。\n"
    "此时不要再调用 `knowledge_search`、`knowledge_locate` 或其他工具，也不要直接起草最终答案。\n"
    "请把已完成板块的发现、可复用 citation、以及剩余待查问题如实写进 checkpoint。",
    "系统再次插入提示（不是用户的新问题）：你刚才仍未先调用 `knowledge_checkpoint`。\n"
    "现在请立刻把下一步改成且仅改成一次 `knowledge_checkpoint` 工具调用。\n"
    "不要继续检索，不要直接回答。",
)

logger = logging.getLogger(__name__)


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


class KnowledgeCheckpointMiddleware(AgentMiddleware[AgentState]):
    """Hide old grounding payloads and push the model to checkpoint before moving on."""

    def _latest_human_index(self, messages: list) -> int:
        for index in range(len(messages) - 1, -1, -1):
            if isinstance(messages[index], HumanMessage):
                return index
        return -1

    def _latest_checkpoint_index(self, messages: list) -> int:
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if isinstance(message, ToolMessage) and getattr(message, "name", None) == CHECKPOINT_TOOL_NAME:
                return index
        return -1

    def _build_patched_messages(self, messages: list) -> list | None:
        last_checkpoint_index = self._latest_checkpoint_index(messages)
        if last_checkpoint_index < 0:
            return None

        patched: list = []
        changed = False
        for index, message in enumerate(messages):
            if (
                index < last_checkpoint_index
                and isinstance(message, ToolMessage)
                and getattr(message, "name", None) in COMPRESSIBLE_TOOL_NAMES
            ):
                if getattr(message, "name", None) == CHECKPOINT_TOOL_NAME:
                    placeholder = "【已调用knowledge_checkpoint工具】该较早检查点已被更新的 knowledge_checkpoint 检查点接替并压缩。"
                else:
                    placeholder = f"【已调用{message.name}工具】该原始检索结果已由后续 knowledge_checkpoint 检查点压缩。"
                if _stringify_content(message.content) != placeholder:
                    changed = True
                    patched.append(message.model_copy(update={"content": placeholder}))
                    continue
            patched.append(message)

        return patched if changed else None

    def _enforcement_start_index(self, messages: list) -> int:
        return max(self._latest_human_index(messages), self._latest_checkpoint_index(messages))

    def _is_substantive_grounding_message(self, message: ToolMessage) -> bool:
        if getattr(message, "name", None) not in GROUNDING_TOOL_NAMES:
            return False

        content = _stringify_content(message.content).strip()
        if not content or content.startswith("【已调用"):
            return False

        lowered = content.lower()
        return not any(marker in content or marker in lowered for marker in NON_SUBSTANTIVE_MARKERS)

    def _grounding_count_since_checkpoint(self, messages: list) -> int:
        start = self._enforcement_start_index(messages)
        count = 0
        for message in messages[start + 1 :]:
            if isinstance(message, ToolMessage) and self._is_substantive_grounding_message(message):
                count += 1
        return count

    def _needs_checkpoint_enforcement(self, messages: list) -> bool:
        if overview_from_messages(messages):
            return False
        return self._grounding_count_since_checkpoint(messages) >= CHECKPOINT_ENFORCEMENT_THRESHOLD

    def _response_calls_checkpoint(self, response: ModelResponse) -> bool:
        ai_messages = [message for message in response.result if isinstance(message, AIMessage)]
        if not ai_messages:
            return False

        final_message = ai_messages[-1]
        if not final_message.tool_calls:
            return False

        tool_names = [tool_call.get("name") for tool_call in final_message.tool_calls]
        return bool(tool_names) and all(
            name == CHECKPOINT_TOOL_NAME and self._checkpoint_args_are_substantive(tool_call.get("args"))
            for name, tool_call in zip(tool_names, final_message.tool_calls, strict=True)
        )

    def _response_submits_result(self, response: ModelResponse) -> bool:
        """A terminal submission replaces a checkpoint; never discard it and retry."""
        messages = [message for message in response.result if isinstance(message, AIMessage)]
        calls = messages[-1].tool_calls if messages else []
        return len(calls) == 1 and calls[0].get("name") == "submit_task_result"

    def _checkpoint_args_are_substantive(self, args: object) -> bool:
        if not isinstance(args, dict):
            return False
        title = str(args.get("title") or "").strip()
        summary = str(args.get("summary") or "").strip()
        citations = args.get("citations")
        if isinstance(citations, list):
            normalized_citations = [str(item).strip() for item in citations if str(item).strip()]
        elif isinstance(citations, str):
            normalized_citations = [citations.strip()] if citations.strip() else []
        else:
            normalized_citations = []
        return bool(title and summary and normalized_citations)

    def _build_retry_request(self, request: ModelRequest, appendix: str) -> ModelRequest:
        reminder = HumanMessage(content=appendix)
        return request.override(messages=[*request.messages, reminder])

    def _prepare_request(self, request: ModelRequest) -> ModelRequest:
        patched = self._build_patched_messages(request.messages)
        if patched is None:
            return request
        return request.override(messages=patched)

    def _enforce_with_retry(
        self,
        request: ModelRequest,
        response: ModelResponse,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        if not self._needs_checkpoint_enforcement(request.messages):
            return response
        if self._response_calls_checkpoint(response) or self._response_submits_result(response):
            return response

        grounding_count = self._grounding_count_since_checkpoint(request.messages)
        logger.info(
            "KnowledgeCheckpointMiddleware: enforcement triggered (grounding_count=%d >= threshold=%d), forcing checkpoint via retry.",
            grounding_count,
            CHECKPOINT_ENFORCEMENT_THRESHOLD,
        )
        retry_request = request
        retry_response = response
        for attempt, appendix in enumerate(CHECKPOINT_RETRY_APPENDICES, 1):
            retry_request = self._build_retry_request(retry_request, appendix)
            retry_response = handler(retry_request)
            if self._response_calls_checkpoint(retry_response) or self._response_submits_result(retry_response):
                logger.info(
                    "KnowledgeCheckpointMiddleware: model called checkpoint on retry %d/%d.",
                    attempt,
                    len(CHECKPOINT_RETRY_APPENDICES),
                )
                return retry_response

        logger.warning(
            "KnowledgeCheckpointMiddleware: model ignored %d retry prompt(s), giving up (grounding_count=%d).",
            len(CHECKPOINT_RETRY_APPENDICES),
            grounding_count,
        )
        return retry_response

    async def _aenforce_with_retry(
        self,
        request: ModelRequest,
        response: ModelResponse,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        if not self._needs_checkpoint_enforcement(request.messages):
            return response
        if self._response_calls_checkpoint(response) or self._response_submits_result(response):
            return response

        grounding_count = self._grounding_count_since_checkpoint(request.messages)
        logger.info(
            "KnowledgeCheckpointMiddleware: enforcement triggered (grounding_count=%d >= threshold=%d), forcing checkpoint via retry.",
            grounding_count,
            CHECKPOINT_ENFORCEMENT_THRESHOLD,
        )
        retry_request = request
        retry_response = response
        for attempt, appendix in enumerate(CHECKPOINT_RETRY_APPENDICES, 1):
            retry_request = self._build_retry_request(retry_request, appendix)
            retry_response = await handler(retry_request)
            if self._response_calls_checkpoint(retry_response) or self._response_submits_result(retry_response):
                logger.info(
                    "KnowledgeCheckpointMiddleware: model called checkpoint on retry %d/%d.",
                    attempt,
                    len(CHECKPOINT_RETRY_APPENDICES),
                )
                return retry_response

        logger.warning(
            "KnowledgeCheckpointMiddleware: model ignored %d retry prompt(s), giving up (grounding_count=%d).",
            len(CHECKPOINT_RETRY_APPENDICES),
            self._grounding_count_since_checkpoint(request.messages),
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
