"""Middleware to detect and prevent premature answer completion.

This middleware detects when the model tries to answer prematurely without:
1. Dispatching subtasks when evidence is insufficient
2. Calling write_todos after indicating need for more research
3. Providing citations or proper refusal format
"""

import logging
import re
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.retrieval_policy import overview_from_messages

logger = logging.getLogger(__name__)

# Patterns indicating the model plans to dispatch but hasn't actually done so
PLANNING_WITHOUT_ACTION_PATTERNS = [
    re.compile(r"下一步(?:行动|操作|计划|步骤)", re.IGNORECASE),
    re.compile(r"建议(?:下发|派发|创建|启动)(?:子任务|任务)", re.IGNORECASE),
    re.compile(r"需要(?:进一步|继续|补充)(?:检索|查询|调查|研究)", re.IGNORECASE),
    re.compile(r"拟(?:下发|派发|创建)(?:子任务|任务)", re.IGNORECASE),
    re.compile(r"将(?:会|要)(?:下发|派发|创建)(?:子任务|任务)", re.IGNORECASE),
    re.compile(r"接下来(?:需要|应该|必须)(?:检索|查询|调查)", re.IGNORECASE),
]

# Patterns indicating proper refusal
REFUSAL_PATTERNS = [
    re.compile(r"^\s*【无法回答】", re.IGNORECASE),
    re.compile(r"^\s*【证据不足】", re.IGNORECASE),
    re.compile(r"^\s*【无法确认】", re.IGNORECASE),
]

# Patterns indicating the model has substantive content
SUBSTANTIVE_CONTENT_PATTERNS = [
    re.compile(r"\[citation:\s*\d+\s*\]", re.IGNORECASE),
    re.compile(r"##\s+任务结果", re.IGNORECASE),
    re.compile(r"##\s+关键发现", re.IGNORECASE),
]

RETRY_APPENDICES = (
    "\n\n[System enforcement - premature completion detected]\n"
    "Your previous response indicated you need more evidence or planned to dispatch subtasks, "
    "but you did not actually call `write_todos` to dispatch them.\n"
    "Required action:\n"
    "1. If you identified evidence gaps, call `write_todos` NOW to dispatch subtasks for those gaps.\n"
    "2. If you cannot dispatch subtasks, either provide a complete answer with citations or refuse with `【无法回答】`.\n"
    "3. Do not describe a plan without executing it. A turn ending with '下一步行动' or '建议下发' without an actual `write_todos` call is incomplete.\n"
    "4. Do not mention this enforcement message in your response.",
    "\n\n[System enforcement - final retry]\n"
    "You still have not dispatched the needed subtasks or provided a complete answer.\n"
    "Choose ONE of these actions:\n"
    "1. Call `write_todos` to dispatch subtasks for the evidence gaps you identified.\n"
    "2. Provide a complete, cited answer based on available evidence.\n"
    "3. Refuse explicitly with `【无法回答】` followed by a brief reason.\n"
    "Do not describe what you plan to do - either do it or refuse.",
)


def _stringify_content(content: object) -> str:
    """Convert message content to string."""
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


def _has_planning_without_action(text: str) -> bool:
    """Check if text contains planning language without actual action."""
    return any(pattern.search(text) for pattern in PLANNING_WITHOUT_ACTION_PATTERNS)


def _is_proper_refusal(text: str) -> bool:
    """Check if text is a proper refusal with the required prefix."""
    return any(pattern.search(text) for pattern in REFUSAL_PATTERNS)


def _has_substantive_content(text: str) -> bool:
    """Check if text has substantive content (citations, structured sections)."""
    return any(pattern.search(text) for pattern in SUBSTANTIVE_CONTENT_PATTERNS)


def _turn_used_grounding_tools(messages: list) -> bool:
    """Check if the current turn used grounding tools (book_search, knowledge_search, etc.)."""
    grounding_tools = {"book_search", "knowledge_search", "knowledge_locate", "write_todos"}
    # Find the latest human message index
    latest_human_idx = -1
    for idx, msg in enumerate(messages):
        if isinstance(msg, HumanMessage):
            latest_human_idx = idx
    
    if latest_human_idx < 0:
        return False
    
    # Check if any tool messages after the latest human message are from grounding tools
    for msg in messages[latest_human_idx:]:
        if isinstance(msg, ToolMessage):
            tool_name = getattr(msg, "name", None)
            if tool_name in grounding_tools:
                return True
    return False


def _turn_dispatched_subtasks(messages: list) -> bool:
    """Check if the current turn dispatched subtasks via write_todos or task."""
    dispatch_tools = {"write_todos", "task"}
    # Find the latest human message index
    latest_human_idx = -1
    for idx, msg in enumerate(messages):
        if isinstance(msg, HumanMessage):
            latest_human_idx = idx
    
    if latest_human_idx < 0:
        return False
    
    # Check if any AI messages after the latest human message called dispatch tools
    for msg in messages[latest_human_idx:]:
        if isinstance(msg, AIMessage):
            tool_calls = getattr(msg, "tool_calls", None) or []
            for tc in tool_calls:
                if tc.get("name") in dispatch_tools:
                    return True
    return False


class EarlyStopDetectionMiddleware(AgentMiddleware[AgentState]):
    """Detect and prevent premature answer completion.
    
    This middleware intercepts responses that:
    1. Indicate need for more evidence but don't dispatch subtasks
    2. Plan to call write_todos but don't actually call it
    3. End with planning language without execution
    
    It retries with enforcement prompts to force either:
    - Actual subtask dispatch via write_todos
    - Complete cited answer
    - Explicit refusal with 【无法回答】
    """

    def _needs_enforcement(self, response: ModelResponse, messages: list) -> bool:
        """Check if the response needs enforcement."""
        if overview_from_messages(messages):
            return False
        # Only enforce if grounding tools were used this turn
        if not _turn_used_grounding_tools(messages):
            return False
        
        # Don't enforce if subtasks were already dispatched
        if _turn_dispatched_subtasks(messages):
            return False
        
        # Check AI messages in response
        ai_messages = [msg for msg in response.result if isinstance(msg, AIMessage)]
        if not ai_messages:
            return False
        
        final_message = ai_messages[-1]
        
        # Don't enforce if the model is calling tools
        if getattr(final_message, "tool_calls", None):
            return False
        
        content = _stringify_content(final_message.content)
        
        # Don't enforce if it's a proper refusal
        if _is_proper_refusal(content):
            return False
        
        # Don't enforce if it has substantive cited content
        if _has_substantive_content(content):
            return False
        
        # Enforce if it has planning language without action
        if _has_planning_without_action(content):
            logger.info(
                "EarlyStopDetectionMiddleware: detected planning without action, triggering enforcement"
            )
            return True
        
        return False

    def _build_retry_request(self, request: ModelRequest, appendix: str) -> ModelRequest:
        """Build a retry request with enforcement appendix."""
        from langchain_core.messages import SystemMessage
        
        current_system = _stringify_content(request.system_message.content) if request.system_message else ""
        retry_system = SystemMessage(
            content=f"{current_system}{appendix}" if current_system else appendix
        )
        return request.override(system_message=retry_system)

    def _enforce_with_retry(
        self,
        request: ModelRequest,
        response: ModelResponse,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Enforce with retry loop."""
        if not self._needs_enforcement(response, request.messages):
            return response
        
        retry_request = request
        retry_response = response
        for appendix in RETRY_APPENDICES:
            retry_request = self._build_retry_request(retry_request, appendix)
            retry_response = handler(retry_request)
            if not self._needs_enforcement(retry_response, request.messages):
                return retry_response
        
        logger.warning(
            "EarlyStopDetectionMiddleware: model ignored %d retry prompts, giving up",
            len(RETRY_APPENDICES),
        )
        return retry_response

    async def _aenforce_with_retry(
        self,
        request: ModelRequest,
        response: ModelResponse,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Async enforce with retry loop."""
        if not self._needs_enforcement(response, request.messages):
            return response
        
        retry_request = request
        retry_response = response
        for appendix in RETRY_APPENDICES:
            retry_request = self._build_retry_request(retry_request, appendix)
            retry_response = await handler(retry_request)
            if not self._needs_enforcement(retry_response, request.messages):
                return retry_response
        
        logger.warning(
            "EarlyStopDetectionMiddleware: model ignored %d retry prompts, giving up",
            len(RETRY_APPENDICES),
        )
        return retry_response

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        """Wrap synchronous model call."""
        response = handler(request)
        return self._enforce_with_retry(request, response, handler)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        """Wrap async model call."""
        response = await handler(request)
        return await self._aenforce_with_retry(request, response, handler)
