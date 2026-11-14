"""Stop a subagent that has burned through its tool-call budget.

When a subtask exceeds TOOL_CALL_LIMIT tool invocations without returning a
final answer, the middleware rewrites the next model call so that only
``submit_task_result`` remains available.  The model is instructed to call
that tool immediately with whatever findings it has accumulated.

``submit_task_result`` calls ``Command(goto=END)`` which terminates the graph
and writes the structured result into state, exactly like a normal successful
run.  This is intentionally different from stripping *all* tools: if there
were no tools the model would write plain text, the executor would not detect
a submitted result, and it would retry the entire task from scratch — causing
another full run of tool calls on each retry attempt.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, ToolMessage

logger = logging.getLogger(__name__)

TOOL_CALL_LIMIT = 20

_WRAP_UP_MESSAGE = (
    "【系统强制终止】本子任务已累计调用工具 {count} 次，超过上限（{limit} 次），必须立即停止检索。\n\n"
    "你现在只能调用一次 `submit_task_result`，不能再调用任何其他工具。\n\n"
    "调用 `submit_task_result` 时请填写以下字段：\n"
    "- `summary`：直接说明当前已找到哪些内容及结论；同时如实说明为什么执行了这么久仍未完成\n"
    "  （可能的原因：涉及书目太多、检索关键词匹配率低、问题范围太宽、书中确实缺乏相关记载等）\n"
    "- `findings`：已确认的关键事实列表，每条附 citation；无则填 `[\"无充分证据支持结论\"]`\n"
    "- `citations`：可复用的 citation 行列表；无则填 `[\"无\"]`\n"
    "- `gaps`：还有哪些关键问题没有答案，及建议主任务如何跟进\n\n"
    "请立即调用 `submit_task_result`，不要输出其他内容，不要调用任何其他工具。"
)


class SubagentToolLimitMiddleware(AgentMiddleware[AgentState]):
    """Enforce a hard tool-call budget on subagents.

    Once the conversation contains TOOL_CALL_LIMIT ToolMessages, the next
    model call is rewritten so that:
      1. A wrap-up instruction is appended to the message history.
      2. All tools are stripped except ``submit_task_result``, forcing the model
         to call that tool (and thereby properly terminate the subtask) rather
         than producing a raw text response that the executor would not recognise
         as a submitted result.

    Keeping ``submit_task_result`` available is critical: if all tools were
    stripped the model would write plain text, the executor would not find
    a submitted result, and it would retry the *entire* task from scratch —
    accumulating another full run of tool calls on each retry.
    """

    def __init__(self, tool_call_limit: int = TOOL_CALL_LIMIT):
        self.tool_call_limit = max(1, tool_call_limit)

    def _count_tool_calls(self, messages: list) -> int:
        """Count ToolMessage instances in the conversation history."""
        return sum(1 for m in messages if isinstance(m, ToolMessage))

    def _build_stripped_request(self, request: ModelRequest, tool_count: int) -> ModelRequest:
        """Inject wrap-up instruction and strip all tools except submit_task_result.

        Keeping submit_task_result available lets the model properly terminate the
        subtask via the tool rather than producing raw text that the executor would
        not recognise as a completed result (which would cause the executor to retry
        the entire task from scratch, adding another full run of tool calls).
        """
        # Preserve submit_task_result so the model can signal proper completion.
        # Fall back to an empty list if the tool is not present (e.g. bash agent).
        submit_tools = [t for t in request.tools if getattr(t, "name", None) == "submit_task_result"]

        reminder = HumanMessage(
            content=_WRAP_UP_MESSAGE.format(count=tool_count, limit=self.tool_call_limit)
        )
        overrides = dict(messages=[*request.messages, reminder], tools=submit_tools)
        if submit_tools:
            overrides["tool_choice"] = {"type": "function", "function": {"name": "submit_task_result"}}
        return request.override(**overrides)

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        tool_count = self._count_tool_calls(request.messages)
        if tool_count < self.tool_call_limit:
            return handler(request)
        logger.info(
            "SubagentToolLimitMiddleware: tool call limit reached (count=%d, limit=%d), stripping tools.",
            tool_count,
            self.tool_call_limit,
        )
        return handler(self._build_stripped_request(request, tool_count))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        tool_count = self._count_tool_calls(request.messages)
        if tool_count < self.tool_call_limit:
            return await handler(request)
        logger.info(
            "SubagentToolLimitMiddleware: tool call limit reached (count=%d, limit=%d), stripping tools.",
            tool_count,
            self.tool_call_limit,
        )
        return await handler(self._build_stripped_request(request, tool_count))
