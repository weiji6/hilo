"""Apply a small retrieval scope without changing the user's research settings."""

import re

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from src.agents.retrieval_policy import OVERVIEW_INSTRUCTION, overview_from_messages
from src.models import create_chat_model


class OverviewRetrievalMiddleware(AgentMiddleware):
    def __init__(self, model_name: str | None = None, orchestrator_only: bool = False):
        self.model_name = model_name
        self.orchestrator_only = orchestrator_only
        self._overview_model = None

    def _scope_request(self, request):
        if not overview_from_messages(request.messages):
            if self.orchestrator_only:
                return request.override(tools=[t for t in request.tools if getattr(t, "name", None) != "knowledge_locate"])
            return request
        turn_tools = []
        for message in reversed(request.messages):
            if isinstance(message, HumanMessage):
                break
            if isinstance(message, ToolMessage):
                turn_tools.append(message.name)
        allowed = {"book_search", "knowledge_locate"}
        if turn_tools.count("book_search") >= 2:
            allowed.discard("book_search")
        if turn_tools.count("knowledge_locate") >= 6:
            allowed.discard("knowledge_locate")
        tools = [t for t in request.tools if getattr(t, "name", None) in allowed]
        finish_instruction = ""
        if not tools:
            finish_instruction = (
                "\n本轮检索已结束，现在必须输出对用户原问题的完整回答。"
                "按问题涉及的时期或方面组织已核实结论，每项引用相应正文。"
                "未核实部分明确标注证据缺口；不得宣布继续检索、准备整理或只交代工作进度。"
            )
        if self._overview_model is None:
            self._overview_model = create_chat_model(name=self.model_name, thinking_enabled=False)
        original = request.system_message.content if request.system_message else ""
        if isinstance(original, list):
            original = "\n".join(part if isinstance(part, str) else str(part.get("text", "")) for part in original)
        # This wrapper runs after the other prompt wrappers. Keep identity,
        # memory, source boundaries and citation rules, but remove instructions
        # that demand decomposition or prohibit an overview answer.
        original = re.sub(
            r"<(subagent_system|todo_list_system|thinking_style|critical_reminders|response_style)>.*?</\1>",
            "",
            original,
            flags=re.DOTALL,
        )
        return request.override(
            model=self._overview_model,
            tools=tools,
            system_message=SystemMessage(content=f"{original}\n{OVERVIEW_INSTRUCTION}{finish_instruction}"),
        )

    def wrap_model_call(self, request, handler):
        return handler(self._scope_request(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._scope_request(request))

    def _blocked_dispatch(self, request):
        if request.tool_call.get("name") not in {"task", "write_todos"}:
            return None
        if not overview_from_messages(request.state.get("messages", [])):
            return None
        return ToolMessage(
            content="本轮采用限量检索，不派发子任务。请直接用 knowledge_locate 读取相关正文后回答；证据不足则说明范围。",
            tool_call_id=request.tool_call["id"],
            name=request.tool_call["name"],
            status="error",
        )

    def wrap_tool_call(self, request, handler):
        blocked = self._blocked_dispatch(request)
        return blocked if blocked is not None else handler(request)

    async def awrap_tool_call(self, request, handler):
        blocked = self._blocked_dispatch(request)
        return blocked if blocked is not None else await handler(request)
