"""Todo middleware that can dispatch in-progress todo batches to subagents."""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import replace
from typing import Annotated, Any, Literal

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.todo import WRITE_TODOS_SYSTEM_PROMPT, WRITE_TODOS_TOOL_DESCRIPTION
from langchain.tools import InjectedToolCallId, ToolRuntime
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from langgraph.runtime import Runtime
from langgraph.types import Command
from langgraph.typing import ContextT
from typing_extensions import NotRequired, TypedDict, cast, override

from src.agents.lead_agent.prompt import get_skills_prompt_section
from src.agents.thread_state import ThreadState
from src.community.knowledge_base.citations import (
    citation_registry_update_fragment,
    merge_citation_registry,
    rewrite_numbered_citations,
)
from src.community.knowledge_base.reading_state import (
    COVERED_DOC_IDS_KEY,
    get_active_reading_state,
)
from src.agents.retrieval_policy import overview_from_messages
from src.subagents import SubagentExecutor, get_subagent_config
from src.subagents.executor import SubagentStatus, get_background_task_result
from src.utils.error_logging import append_error_doc
from src.utils.subtask_logging import log_subtask_event

logger = logging.getLogger(__name__)


class AssignedBook(TypedDict):
    """A book assigned by the lead agent for a specific todo."""

    doc_id: str
    title: str


class Todo(TypedDict):
    """Todo item shown to the user and optionally bound to a subagent task."""

    content: str
    status: Literal["pending", "in_progress", "completed", "failed"]
    id: NotRequired[str]
    task_id: NotRequired[str]
    task_prompt: NotRequired[str]
    subagent_type: NotRequired[Literal["general-purpose", "bash"]]
    result: NotRequired[str]
    result_summary: NotRequired[str]
    structured_summary: NotRequired[str]
    structured_findings: NotRequired[list[str]]
    structured_citations: NotRequired[list[str]]
    structured_gaps: NotRequired[list[str]]
    citation_registry: NotRequired[list[dict[str, Any]]]
    assigned_books: NotRequired[list[AssignedBook]]
    error: NotRequired[str]
    execution_time_seconds: NotRequired[float]


def _coerce_todos_list(value: Any) -> Any:
    """Allow the model to pass ``todos`` as a JSON string.

    Some models serialise complex parameters as a JSON-encoded string rather
    than a structured object.  This function transparently parses that
    string into a Python list so downstream validation can proceed unchanged.
    """
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    return value


class ParallelDispatchState(TypedDict):
    """State recorded when a parallel todo batch is dispatched."""

    dispatched: bool
    todo_ids: list[str]
    task_ids: list[str]


class PlanningState(ThreadState):
    """Agent state carrying todo-board data."""

    todos: NotRequired[list[Todo] | None]


def _clip_text(text: str, *, limit: int = 240) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _build_result_digest(
    task_result: str,
    findings: list[str],
    *,
    limit: int = 320,
) -> str:
    normalized_result = " ".join(task_result.split()).strip()
    cleaned_findings = [" ".join(item.split()).strip() for item in findings if " ".join(item.split()).strip()]

    parts: list[str] = []
    if normalized_result:
        parts.append(normalized_result)
    if cleaned_findings:
        parts.extend(cleaned_findings[:2])

    if not parts:
        return "已完成"

    return _clip_text(" | ".join(parts), limit=limit)


def _normalize_book_match_text(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _mark_completed_todo_coverage(runtime: Any, todo: Todo) -> None:
    if runtime is None or not hasattr(runtime, "state") or not isinstance(runtime.state, dict):
        return

    reading_set, titles, covered, _query = get_active_reading_state(runtime.state)
    if not reading_set or not titles:
        return

    haystacks = [
        str(todo.get("content") or ""),
        str(todo.get("task_prompt") or ""),
        str(todo.get("result_summary") or ""),
        str(todo.get("structured_summary") or ""),
    ]
    normalized_haystack = _normalize_book_match_text(" ".join(part for part in haystacks if part).strip())
    if not normalized_haystack:
        return

    matched_doc_ids: list[str] = []
    for doc_id in reading_set:
        title = titles.get(doc_id)
        if not title:
            continue
        normalized_title = _normalize_book_match_text(title)
        if normalized_title and normalized_title in normalized_haystack:
            matched_doc_ids.append(doc_id)

    if not matched_doc_ids:
        return

    covered_ids = [str(item).strip() for item in runtime.state.get(COVERED_DOC_IDS_KEY) or [] if str(item).strip()]
    seen = set(covered_ids)
    for doc_id in matched_doc_ids:
        if doc_id in seen:
            continue
        covered_ids.append(doc_id)
        seen.add(doc_id)
    runtime.state[COVERED_DOC_IDS_KEY] = covered_ids


def _is_synthesis_todo(todo: Todo) -> bool:
    content = str(todo.get("content", "")).strip().lower()
    if not content:
        return False

    synthesis_markers = (
        "总结",
        "汇总",
        "整合",
        "综合",
        "归纳",
        "写最终",
        "最终答案",
        "最终回复",
        "撰写答案",
        "撰写最终回复",
        "形成答案",
        "整理结论",
        "输出答案",
        "synthesize",
        "synthesis",
        "summary",
        "final answer",
        "final response",
    )
    return any(marker in content for marker in synthesis_markers)


def _prune_synthesis_todos(todos: list[Todo]) -> tuple[list[Todo], list[Todo]]:
    kept: list[Todo] = []
    removed: list[Todo] = []

    for todo in todos:
        if _is_synthesis_todo(todo):
            removed.append(todo)
        else:
            kept.append(todo)

    if kept:
        return kept, removed

    # If everything looked like synthesis, keep them rather than dropping the
    # whole board silently; this makes the behavior safer for unexpected inputs.
    return todos, []


def _build_default_task_prompt(todo: Todo) -> str:
    assigned: list[AssignedBook] = todo.get("assigned_books") or []
    if assigned:
        books_str = "、".join(f"《{b['title']}》(doc_id: {b['doc_id']})" for b in assigned)
        doc_id_line = (
            f"主代理已通过 `book_search` 路由完成，分配的书目：{books_str}。"
            "直接用对应 doc_id 调用 `knowledge_locate`，不要再调 `book_search`。\n"
        )
    else:
        doc_id_line = "主代理未分配书目；请查看 `task_prompt` 里是否有书名或 doc_id，直接用对应 doc_id 调用 `knowledge_locate`；若无任何线索则写 `【证据不足】`。\n"
    return (
        "你只负责执行下面这一项 todo，不要扩展到其他任务，不要替主代理写最终总答案。\n\n"
        f"Todo: {todo['content']}\n\n"
        f"{doc_id_line}"
        "要求：\n"
        "1. 只围绕这一项任务检索、分析或执行；\n"
        "2. `knowledge_locate` 禁止空调用。每次都必须带非空 `doc_id`；不要用书名代替。收到 missing-doc-id 错误时，用分配的原样 `doc_id` 重试一次，仍失败则写 `【证据不足】`；\n"
        "3. 不要用 bash/find/ls 扫本地文件系统替代知识库检索；\n"
        "4. 读到足够证据后停止检索，保留工具返回的编号 citation；\n"
        "5. 所有检索完成后，**必须调用 `submit_task_result` 工具**来提交结果，不调用则任务不算完成；\n"
        "6. `submit_task_result` 的 `summary` 参数是最重要的主结果块，不要写成 1-2 句导语式摘要；"
        "必须针对这个 Todo 的目标，详细写出检索到的信息并附上 citation；\n"
        "7. citation 优先使用工具返回的编号标记如 `[citation:1]`；缺 citation 的内容写入 gaps，不要硬答。"
    )


def _build_task_prompt(todo: Todo) -> str:
    custom_prompt = str(todo.get("task_prompt") or "").strip()
    if not custom_prompt:
        return _build_default_task_prompt(todo)

    assigned: list[AssignedBook] = todo.get("assigned_books") or []
    if assigned:
        books_str = "、".join(f"《{b['title']}》(doc_id: {b['doc_id']})" for b in assigned)
        doc_id_line = (
            f"主代理已通过 `book_search` 路由完成，分配的书目：{books_str}。"
            "直接用对应 doc_id 调用 `knowledge_locate`，不要再调 `book_search`。\n\n"
        )
    else:
        doc_id_line = ""
    return (
        "你只负责执行下面这一项 todo，不要扩展到其他任务，不要替主代理写最终总答案。\n\n"
        f"Todo: {todo['content']}\n\n"
        f"{doc_id_line}"
        "主代理给你的具体任务说明如下：\n"
        f"{custom_prompt}\n\n"
        "强制检索规则：\n"
        "1. 用分配的书目 doc_id 直接调 `knowledge_locate`，不要自己再调 `book_search`；\n"
        "2. 禁止空调 `knowledge_locate`，也不要用书名代替 `doc_id`。如果收到 missing-doc-id 错误，用分配的原样 `doc_id` 重试一次；仍失败则写 `【证据不足】`；\n"
        "3. 所有检索完成后，**必须调用 `submit_task_result` 工具**来提交结果；citation 必须复制工具返回的编号标记。"
    )


def _serialize_todos_for_event(todos: list[Todo]) -> list[dict[str, Any]]:
    return [dict(todo) for todo in todos]


def _render_todo_evidence_block(todo: Todo) -> str:
    lines = [
        f"### Todo: {todo.get('content', '')}",
        f"状态: {todo.get('status', 'pending')}",
    ]

    summary = str(todo.get("structured_summary") or "").strip()
    findings = [str(item).strip() for item in todo.get("structured_findings", []) or [] if str(item).strip()]
    citations = [str(item).strip() for item in todo.get("structured_citations", []) or [] if str(item).strip()]
    gaps = [str(item).strip() for item in todo.get("structured_gaps", []) or [] if str(item).strip()]
    error = str(todo.get("error") or "").strip()

    if summary:
        lines.append("任务结果:")
        lines.append(summary)

    if findings:
        lines.append("关键发现:")
        lines.extend(f"- {item}" for item in findings)

    if citations:
        lines.append("关键引文:")
        lines.extend(f"- {item}" for item in citations)

    if gaps:
        lines.append("未解决缺口:")
        lines.extend(f"- {item}" for item in gaps)

    if error:
        lines.append(f"错误: {error}")

    return "\n".join(lines)


def _rewrite_citation_list(items: list[Any], citation_id_mapping: dict[str, str]) -> list[str]:
    return [
        rewrite_numbered_citations(str(item).strip(), citation_id_mapping)
        for item in items
        if str(item).strip()
    ]


def _should_preserve_bound_task_status(
    *,
    raw: Todo,
    existing_todo: Todo | None,
    next_status: Literal["pending", "in_progress", "completed", "failed"],
) -> bool:
    if existing_todo is None:
        return False

    if not existing_todo.get("task_id") or raw.get("task_id"):
        return False

    existing_status = cast(
        Literal["pending", "in_progress", "completed", "failed"],
        existing_todo.get("status", "pending"),
    )

    # Once a todo is bound to a real subtask, the lead model should not mutate
    # that task's lifecycle without providing a new task binding. The executor
    # owns the transition from running -> completed/failed.
    if existing_status == "in_progress" and next_status != "in_progress":
        return True

    return False


class TodoListMiddleware(AgentMiddleware[PlanningState]):
    """Middleware that turns the todo list into a lightweight execution board."""

    state_schema = PlanningState

    def __init__(
        self,
        *,
        system_prompt: str = WRITE_TODOS_SYSTEM_PROMPT,
        tool_description: str = WRITE_TODOS_TOOL_DESCRIPTION,
        subagent_enabled: bool = False,
        max_concurrent_subagents: int = 4,
    ) -> None:
        super().__init__()
        self.system_prompt = system_prompt
        self.tool_description = tool_description
        self.subagent_enabled = subagent_enabled
        self.max_concurrent_subagents = max_concurrent_subagents

        @tool(description=self.tool_description)
        def write_todos(
            runtime: ToolRuntime[ContextT, ThreadState],
            todos: list[Todo],
            tool_call_id: Annotated[str, InjectedToolCallId],
        ) -> Command:
            return self._handle_write_todos(
                runtime=runtime,
                todos=todos,
                tool_call_id=tool_call_id,
            )

        self.tools = [write_todos]

    def _normalize_todos(self, incoming: list[Todo], existing: list[Todo] | None) -> list[Todo]:
        existing = existing or []
        by_id = {todo.get("id"): todo for todo in existing if todo.get("id")}
        by_content = {todo.get("content"): todo for todo in existing if todo.get("content")}
        normalized: list[Todo] = []

        for raw in incoming:
            content = str(raw.get("content", "")).strip()
            if not content:
                continue

            existing_todo = None
            if raw.get("id") and raw.get("id") in by_id:
                existing_todo = by_id[raw["id"]]
            elif content in by_content:
                existing_todo = by_content[content]

            status = cast(
                Literal["pending", "in_progress", "completed", "failed"],
                raw.get("status", existing_todo.get("status") if existing_todo else "pending"),
            )
            if status not in {"pending", "in_progress", "completed", "failed"}:
                status = "pending"

            if _should_preserve_bound_task_status(
                raw=raw,
                existing_todo=existing_todo,
                next_status=status,
            ):
                status = cast(
                    Literal["pending", "in_progress", "completed", "failed"],
                    existing_todo.get("status", status),
                )

            todo_id = str(raw.get("id") or (existing_todo.get("id") if existing_todo else "") or f"todo-{uuid.uuid4().hex[:8]}")
            todo: Todo = {
                "id": todo_id,
                "content": content,
                "status": status,
            }

            for field in (
                "task_id",
                "task_prompt",
                "subagent_type",
                "assigned_books",
                "result",
                "result_summary",
                "structured_summary",
                "structured_findings",
                "structured_citations",
                "structured_gaps",
                "error",
            ):
                value = raw.get(field)
                if value in (None, "") and existing_todo is not None:
                    value = existing_todo.get(field)
                if value not in (None, ""):
                    todo[field] = cast(Any, value)

            if (
                status in {"pending", "in_progress"}
                and "task_id" not in raw
                and existing_todo is not None
                and raw.get("status") != existing_todo.get("status")
            ):
                todo.pop("task_id", None)
                todo.pop("result", None)
                todo.pop("result_summary", None)
                todo.pop("structured_summary", None)
                todo.pop("structured_findings", None)
                todo.pop("structured_citations", None)
                todo.pop("structured_gaps", None)
                todo.pop("error", None)

            normalized.append(todo)

        return normalized

    def _build_subagent_config(self, subagent_type: str):
        config = get_subagent_config(subagent_type)
        if config is None:
            return None

        overrides: dict[str, Any] = {}
        skills_section = get_skills_prompt_section()
        if skills_section:
            overrides["system_prompt"] = config.system_prompt + "\n\n" + skills_section

        if overrides:
            config = replace(config, **overrides)
        return config

    def _dispatch_parallel_todos(
        self,
        *,
        runtime: Any,
        todos: list[Todo],
        tool_call_id: str,
    ) -> tuple[list[Todo], list[str], ParallelDispatchState]:
        dispatch_state: ParallelDispatchState = {
            "dispatched": False,
            "todo_ids": [],
            "task_ids": [],
        }
        log_subtask_event(
            "write_todos_received",
            tool_call_id=tool_call_id,
            todo_count=len(todos),
            in_progress_or_pending_count=sum(1 for todo in todos if todo["status"] in {"in_progress", "pending"}),
            subagent_enabled=self.subagent_enabled,
            max_concurrent_subagents=self.max_concurrent_subagents,
        )
        if not self.subagent_enabled:
            log_subtask_event(
                "write_todos_dispatch_skipped",
                tool_call_id=tool_call_id,
                reason="subagent_disabled",
                todos=todos,
            )
            return todos, [], dispatch_state

        queued_todos = [
            todo for todo in todos if todo["status"] in {"in_progress", "pending"} and not todo.get("task_id")
        ]
        if not queued_todos:
            log_subtask_event(
                "write_todos_dispatch_skipped",
                tool_call_id=tool_call_id,
                reason="no_queued_todos",
                todos=todos,
            )
            return todos, [], dispatch_state

        writer = get_stream_writer()
        trace_id = None
        sandbox_state = None
        thread_data = None
        thread_id = None
        parent_model = None

        if runtime is not None:
            sandbox_state = runtime.state.get("sandbox")
            thread_data = runtime.state.get("thread_data")
            thread_id = runtime.context.get("thread_id")
            metadata = runtime.config.get("metadata", {})
            parent_model = metadata.get("model_name")
            trace_id = metadata.get("trace_id")

        trace_id = trace_id or str(uuid.uuid4())[:8]

        # Lazy import to avoid circular dependency during app startup.
        from src.tools import get_available_tools

        tools = get_available_tools(model_name=parent_model, subagent_enabled=False)

        summary_lines: list[str] = []
        if len(queued_todos) > self.max_concurrent_subagents:
            summary_lines.append(
                f"检测到 {len(queued_todos)} 个待执行 todo；系统会按最多 {self.max_concurrent_subagents} 个并发子任务自动分批执行。"
            )
        writer({"type": "todo_board_updated", "todos": _serialize_todos_for_event(todos)})

        queue: list[Todo] = list(queued_todos)
        launched: dict[str, dict[str, Any]] = {}
        runtime_context = getattr(runtime, "context", {}) if runtime is not None else {}

        while queue or launched:
            while queue and len(launched) < self.max_concurrent_subagents:
                todo = queue.pop(0)
                subagent_type = cast(str, todo.get("subagent_type") or "general-purpose")
                config = self._build_subagent_config(subagent_type)
                if config is None:
                    todo["status"] = "failed"
                    todo["error"] = f"Unknown subagent type: {subagent_type}"
                    append_error_doc(
                        location="parallel_todo_list_middleware",
                        summary="Todo could not be dispatched because subagent type was unknown",
                        error=todo["error"],
                        context={
                            "todo_id": todo.get("id"),
                            "content": todo["content"],
                            "subagent_type": subagent_type,
                        },
                    )
                    writer({"type": "todo_board_updated", "todos": _serialize_todos_for_event(todos)})
                    summary_lines.append(f"[failed] {todo['content']}：未知子代理类型 {subagent_type}")
                    continue

                executor = SubagentExecutor(
                    config=config,
                    tools=tools,
                    parent_model=parent_model,
                    sandbox_state=sandbox_state,
                    thread_data=thread_data,
                    thread_id=thread_id,
                    user_id=runtime_context.get("user_id"),
                    trace_id=trace_id,
                    overview=overview_from_messages(runtime.state.get("messages", [])) if runtime is not None else False,
                )

                task_id = f"{tool_call_id}:{todo['id']}"
                task_prompt = _build_task_prompt(todo)
                todo["status"] = "in_progress"
                todo["task_id"] = task_id
                todo["subagent_type"] = cast(Any, subagent_type)
                todo["task_prompt"] = task_prompt
                dispatch_state["dispatched"] = True
                dispatch_state["todo_ids"].append(cast(str, todo["id"]))
                dispatch_state["task_ids"].append(task_id)
                writer({"type": "task_started", "task_id": task_id, "description": _clip_text(todo["content"], limit=60)})
                writer({"type": "todo_board_updated", "todos": _serialize_todos_for_event(todos)})
                launched[task_id] = {
                    "todo": todo,
                    "message_count": 0,
                    "timeout_seconds": config.timeout_seconds,
                }
                log_subtask_event(
                    "subtask_dispatching",
                    tool_call_id=tool_call_id,
                    task_id=task_id,
                    todo_id=todo.get("id"),
                    content=todo["content"],
                    subagent_type=subagent_type,
                    queue_remaining=len(queue),
                    launched=len(launched),
                    timeout_seconds=config.timeout_seconds,
                )
                executor.execute_async(
                    task_prompt,
                    task_id=task_id,
                    task_title=todo["content"],
                    task_level="subtask",
                )
                logger.info(
                    "[trace=%s] Dispatched todo subtask %s (active=%s queued=%s): %s",
                    trace_id,
                    task_id,
                    len(launched),
                    len(queue),
                    todo["content"],
                )

            if not launched:
                break

            completed_task_ids: list[str] = []
            for task_id, meta in list(launched.items()):
                result = get_background_task_result(task_id)
                todo = cast(Todo, meta["todo"])

                if result is None:
                    todo["status"] = "failed"
                    todo["error"] = "Task disappeared from background tasks"
                    log_subtask_event(
                        "subtask_missing",
                        task_id=task_id,
                        todo_id=todo.get("id"),
                        content=todo["content"],
                    )
                    append_error_doc(
                        location="parallel_todo_list_middleware",
                        summary="Todo-linked subtask disappeared before completion",
                        error=todo["error"],
                        context={
                            "task_id": task_id,
                            "todo_id": todo.get("id"),
                            "content": todo["content"],
                        },
                    )
                    writer({"type": "task_failed", "task_id": task_id, "error": todo["error"]})
                    writer({"type": "todo_board_updated", "todos": _serialize_todos_for_event(todos)})
                    summary_lines.append(f"[failed] {todo['content']}：{todo['error']}")
                    completed_task_ids.append(task_id)
                    continue

                current_message_count = len(result.ai_messages)
                if current_message_count > meta["message_count"]:
                    for i in range(meta["message_count"], current_message_count):
                        writer(
                            {
                                "type": "task_running",
                                "task_id": task_id,
                                "message": result.ai_messages[i],
                                "message_index": i + 1,
                                "total_messages": current_message_count,
                            }
                        )
                    meta["message_count"] = current_message_count

                if result.status == SubagentStatus.COMPLETED:
                    todo["status"] = "completed"
                    exec_time = (result.completed_at - result.started_at).total_seconds() if result.started_at and result.completed_at else None
                    if exec_time is not None:
                        todo["execution_time_seconds"] = exec_time
                    citation_id_mapping = merge_citation_registry(
                        runtime.state if isinstance(getattr(runtime, "state", None), dict) else None,
                        getattr(result, "citation_registry", None),
                    )
                    logger.info(
                        "[trace=%s] Todo subtask %s citation merge: source_count=%s, mapping=%s, target_registry_count=%s",
                        trace_id,
                        task_id,
                        len(getattr(result, "citation_registry", None) or []),
                        citation_id_mapping,
                        len(runtime.state.get("knowledge_citation_registry", [])) if isinstance(getattr(runtime, "state", None), dict) else "N/A",
                    )
                    if result.result:
                        todo["result"] = rewrite_numbered_citations(result.result, citation_id_mapping)
                    if isinstance(getattr(runtime, "state", None), dict):
                        raw_registry = runtime.state.get("knowledge_citation_registry")
                        if isinstance(raw_registry, list):
                            todo["citation_registry"] = [item for item in raw_registry if isinstance(item, dict)]
                    logger.info(
                        "[trace=%s] Todo subtask %s todo citation_registry set: count=%s, ids=%s",
                        trace_id,
                        task_id,
                        len(todo.get("citation_registry", [])) if todo.get("citation_registry") else 0,
                        [str(item.get("id")) for item in (todo.get("citation_registry") or [])],
                    )
                    if result.structured_result:
                        summary = rewrite_numbered_citations(
                            str(result.structured_result.get("summary") or "").strip(),
                            citation_id_mapping,
                        )
                        findings = _rewrite_citation_list(
                            cast(list[Any], result.structured_result.get("findings") or []),
                            citation_id_mapping,
                        )
                        citations = _rewrite_citation_list(
                            cast(list[Any], result.structured_result.get("citations") or []),
                            citation_id_mapping,
                        )
                        gaps = _rewrite_citation_list(
                            cast(list[Any], result.structured_result.get("open_questions") or []),
                            citation_id_mapping,
                        )
                        if summary:
                            todo["structured_summary"] = summary
                        if findings:
                            todo["structured_findings"] = findings
                        if citations:
                            todo["structured_citations"] = citations
                        if gaps:
                            todo["structured_gaps"] = gaps
                        todo["result_summary"] = _build_result_digest(
                            summary,
                            findings,
                            limit=320,
                        )
                    elif result.result:
                        todo["result_summary"] = _clip_text(result.result, limit=320)
                    _mark_completed_todo_coverage(runtime, todo)
                    todo.pop("error", None)
                    log_subtask_event(
                        "subtask_completed",
                        task_id=task_id,
                        todo_id=todo.get("id"),
                        content=todo["content"],
                        result_summary=todo.get("result_summary"),
                    )
                    writer(
                        {
                            "type": "task_completed",
                            "task_id": task_id,
                            "result": todo.get("result"),
                            "summary": todo.get("structured_summary"),
                            "findings": todo.get("structured_findings"),
                            "citations": todo.get("structured_citations"),
                            "open_questions": todo.get("structured_gaps"),
                            "execution_time_seconds": todo.get("execution_time_seconds"),
                        }
                    )
                    writer({"type": "todo_board_updated", "todos": _serialize_todos_for_event(todos)})
                    summary_lines.append(f"[completed] {todo['content']}：{todo.get('result_summary', '已完成')}")
                    completed_task_ids.append(task_id)
                elif result.status == SubagentStatus.FAILED:
                    todo["status"] = "failed"
                    todo["error"] = result.error or "Unknown subtask error"
                    exec_time = (result.completed_at - result.started_at).total_seconds() if result.started_at and result.completed_at else None
                    if exec_time is not None:
                        todo["execution_time_seconds"] = exec_time
                    log_subtask_event(
                        "subtask_failed",
                        task_id=task_id,
                        todo_id=todo.get("id"),
                        content=todo["content"],
                        error=todo["error"],
                    )
                    append_error_doc(
                        location="parallel_todo_list_middleware",
                        summary="Todo-linked subtask failed",
                        error=todo["error"],
                        context={
                            "task_id": task_id,
                            "todo_id": todo.get("id"),
                            "content": todo["content"],
                        },
                    )
                    writer({"type": "task_failed", "task_id": task_id, "error": todo["error"], "execution_time_seconds": todo.get("execution_time_seconds")})
                    writer({"type": "todo_board_updated", "todos": _serialize_todos_for_event(todos)})
                    summary_lines.append(f"[failed] {todo['content']}：{todo['error']}")
                    completed_task_ids.append(task_id)
                elif result.status == SubagentStatus.TIMED_OUT:
                    todo["status"] = "failed"
                    todo["error"] = result.error or "Subtask timed out"
                    exec_time = (result.completed_at - result.started_at).total_seconds() if result.started_at and result.completed_at else None
                    if exec_time is not None:
                        todo["execution_time_seconds"] = exec_time
                    log_subtask_event(
                        "subtask_timed_out",
                        task_id=task_id,
                        todo_id=todo.get("id"),
                        content=todo["content"],
                        error=todo["error"],
                    )
                    append_error_doc(
                        location="parallel_todo_list_middleware",
                        summary="Todo-linked subtask timed out",
                        error=todo["error"],
                        context={
                            "task_id": task_id,
                            "todo_id": todo.get("id"),
                            "content": todo["content"],
                        },
                    )
                    writer({"type": "task_timed_out", "task_id": task_id, "error": todo["error"], "execution_time_seconds": todo.get("execution_time_seconds")})
                    writer({"type": "todo_board_updated", "todos": _serialize_todos_for_event(todos)})
                    summary_lines.append(f"[failed] {todo['content']}：{todo['error']}")
                    completed_task_ids.append(task_id)
                elif result.status == SubagentStatus.CANCELLED:
                    todo["status"] = "failed"
                    todo["error"] = result.error or "Subtask cancelled because the parent session was interrupted."
                    log_subtask_event(
                        "subtask_cancelled",
                        task_id=task_id,
                        todo_id=todo.get("id"),
                        content=todo["content"],
                        error=todo["error"],
                    )
                    writer({"type": "task_failed", "task_id": task_id, "error": todo["error"]})
                    writer({"type": "todo_board_updated", "todos": _serialize_todos_for_event(todos)})
                    summary_lines.append(f"[cancelled] {todo['content']}：{todo['error']}")
                    completed_task_ids.append(task_id)

            for task_id in completed_task_ids:
                launched.pop(task_id, None)

            if launched or queue:
                time.sleep(0.1)

        return todos, summary_lines, dispatch_state

    def _build_todo_orchestration_state(
        self,
        *,
        tool_call_id: str,
        dispatch_state: ParallelDispatchState,
    ) -> dict[str, Any] | None:
        return None

    def _build_tool_message(self, todos: list[Todo], summary_lines: list[str]) -> str:
        lines = ["Updated todo board."]
        if summary_lines:
            lines.append("Parallel dispatch summary:")
            lines.extend(f"- {line}" for line in summary_lines)
        else:
            lines.append("No subagent batch was dispatched.")

        lines.append("Current todos:")
        for todo in todos:
            status = todo.get("status", "pending")
            content = todo.get("content", "")
            line = f"- [{status}] {content}"
            if todo.get("result_summary"):
                line += f" | result: {todo['result_summary']}"
            if todo.get("error"):
                line += f" | error: {todo['error']}"
            lines.append(line)

        running_todos = [todo for todo in todos if todo.get("status") == "in_progress" and todo.get("task_id")]
        if running_todos:
            lines.append("")
            lines.append(
                "Running subtask instructions: these todos have only been dispatched. "
                "Do not mark them completed or synthesize their evidence until actual subtask results are available."
            )

        detailed_completed = [todo for todo in todos if todo.get("status") == "completed"]
        if detailed_completed:
            lines.append("")
            lines.append("Completed todo evidence packets:")
            for todo in detailed_completed:
                lines.append(_render_todo_evidence_block(todo))
                lines.append("")

            lines.append(
                "Synthesis instructions: when you write the final answer, prefer reusing the citation-bearing lines above."
            )
            lines.append(
                "Do not invent placeholder links or generic source mentions; copy the exact numbered citation markers from the completed todo evidence packets."
            )

        return "\n".join(lines)

    def _validate_assigned_doc_ids(
        self,
        *,
        todos: list[Todo],
        tool_call_id: str,
        runtime: Any,
    ) -> Command | None:
        """Return an error Command if any assigned_books doc_id is not in the catalog."""
        all_assigned: list[AssignedBook] = []
        for todo in todos:
            books = todo.get("assigned_books") or []
            all_assigned.extend(books)

        if not all_assigned:
            return None

        from src.community.knowledge_base.catalog import list_book_catalog  # noqa: PLC0415

        runtime_context = getattr(runtime, "context", {}) if runtime is not None else {}
        thread_id: str | None = runtime_context.get("thread_id")
        user_id: str | None = runtime_context.get("user_id")

        try:
            catalog_entries = list_book_catalog(
                thread_id=thread_id,
                user_id=user_id,
                include_search_content=False,
                caller="write_todos.validate_doc_ids",
            )
        except Exception:
            logger.exception("write_todos: catalog lookup failed during doc_id validation; skipping check")
            return None

        valid_doc_ids = {entry.doc_id for entry in catalog_entries}
        invalid: list[str] = []
        for book in all_assigned:
            doc_id = book.get("doc_id", "")
            if doc_id and doc_id not in valid_doc_ids:
                invalid.append(doc_id)

        if not invalid:
            return None

        invalid_list = "、".join(f"`{d}`" for d in invalid)
        error_msg = (
            f"Error: write_todos 包含不存在于知识库中的 doc_id：{invalid_list}。\n"
            "这些 doc_id 可能是自行拼凑的，请先调用 `book_search` 获取正确的书目和 doc_id，"
            "再用 `book_search` 返回的原样 doc_id 填写 `assigned_books`，然后重新调用 `write_todos`。"
        )
        log_subtask_event(
            "write_todos_invalid_doc_ids",
            tool_call_id=tool_call_id,
            invalid_doc_ids=invalid,
        )
        return Command(
            update={
                "messages": [ToolMessage(error_msg, tool_call_id=tool_call_id, status="error")],
            }
        )

    def _handle_write_todos(self, *, runtime: Any, todos: list[Todo], tool_call_id: str) -> Command:
        existing_todos = cast(list[Todo] | None, runtime.state.get("todos") if runtime is not None else None)
        normalized = self._normalize_todos(todos, existing_todos)

        validation_error = self._validate_assigned_doc_ids(todos=normalized, tool_call_id=tool_call_id, runtime=runtime)
        if validation_error is not None:
            return validation_error

        removed_synthesis_todos: list[Todo] = []
        if self.subagent_enabled:
            normalized, removed_synthesis_todos = _prune_synthesis_todos(normalized)
            if removed_synthesis_todos:
                log_subtask_event(
                    "synthesis_todos_pruned",
                    tool_call_id=tool_call_id,
                    removed_todos=removed_synthesis_todos,
                )
        normalized, summary_lines, dispatch_state = self._dispatch_parallel_todos(
            runtime=runtime,
            todos=normalized,
            tool_call_id=tool_call_id,
        )
        if removed_synthesis_todos:
            summary_lines.insert(
                0,
                "已忽略总结/整合类 todo；最终综合由主任务在子任务结果返回后自行完成。",
            )
        update_payload: dict[str, Any] = {
            "todos": normalized,
            "todo_orchestration": self._build_todo_orchestration_state(
                tool_call_id=tool_call_id,
                dispatch_state=dispatch_state,
            ),
            "messages": [ToolMessage(self._build_tool_message(normalized, summary_lines), tool_call_id=tool_call_id)],
        }
        # Explicitly sync citation registry so LangGraph channel update fires.
        update_payload.update(
            citation_registry_update_fragment(
                runtime.state if runtime is not None and isinstance(getattr(runtime, "state", None), dict) else None
            )
        )
        return Command(update=update_payload)

    @override
    def wrap_model_call(self, request, handler):
        if request.system_message is not None:
            new_system_content = [
                *request.system_message.content_blocks,
                {"type": "text", "text": f"\n\n{self.system_prompt}"},
            ]
        else:
            new_system_content = [{"type": "text", "text": self.system_prompt}]
        new_system_message = SystemMessage(content=cast("list[str | dict[str, str]]", new_system_content))
        return handler(request.override(system_message=new_system_message))

    @override
    async def awrap_model_call(self, request, handler):
        if request.system_message is not None:
            new_system_content = [
                *request.system_message.content_blocks,
                {"type": "text", "text": f"\n\n{self.system_prompt}"},
            ]
        else:
            new_system_content = [{"type": "text", "text": self.system_prompt}]
        new_system_message = SystemMessage(content=cast("list[str | dict[str, str]]", new_system_content))
        return await handler(request.override(system_message=new_system_message))

    def _last_ai_message(self, state: PlanningState) -> AIMessage | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        return next((msg for msg in reversed(messages) if isinstance(msg, AIMessage)), None)

    def _single_write_todos_only(self, state: PlanningState) -> dict[str, Any] | None:
        last_ai_msg = self._last_ai_message(state)
        if not last_ai_msg or not last_ai_msg.tool_calls:
            return None

        write_todos_calls = [tc for tc in last_ai_msg.tool_calls if tc["name"] == "write_todos"]
        if len(write_todos_calls) <= 1:
            return None

        error_messages = [
            ToolMessage(
                content=(
                    "Error: `write_todos` replaces the entire todo board, so it cannot be "
                    "called multiple times in parallel. Please call it only once per model turn."
                ),
                tool_call_id=tc["id"],
                status="error",
            )
            for tc in write_todos_calls
        ]
        return {"messages": error_messages}

    def _coerce_write_todos_args(self, state: PlanningState) -> dict[str, Any] | None:
        """Coerce JSON-string ``todos`` args to a list before Pydantic validation.

        Some models serialise complex tool arguments as a JSON-encoded string
        rather than a structured object.  Pydantic rejects this before the tool
        function body runs, so we patch the tool_call args here in ``after_model``
        (which executes before any tool invocation) and return a replacement
        AIMessage with corrected args when a coercion was necessary.
        """
        last_ai_msg = self._last_ai_message(state)
        if not last_ai_msg or not last_ai_msg.tool_calls:
            return None

        patched_calls = []
        any_patched = False
        for tc in last_ai_msg.tool_calls:
            if tc.get("name") == "write_todos":
                raw_todos = tc.get("args", {}).get("todos")
                coerced = _coerce_todos_list(raw_todos)
                if coerced is not raw_todos:
                    # Build a new tool_call dict with corrected args
                    new_args = {**tc.get("args", {}), "todos": coerced}
                    tc = {**tc, "args": new_args}
                    any_patched = True
            patched_calls.append(tc)

        if not any_patched:
            return None

        new_msg = last_ai_msg.model_copy(update={"tool_calls": patched_calls})
        return {"messages": [new_msg]}

    def _write_todos_is_phase_boundary(self, state: PlanningState) -> dict[str, Any] | None:
        last_ai_msg = self._last_ai_message(state)
        if not last_ai_msg or not last_ai_msg.tool_calls:
            return None

        write_todos_calls = [tc for tc in last_ai_msg.tool_calls if tc["name"] == "write_todos"]
        if not write_todos_calls:
            return None

        non_write_todos_calls = [tc for tc in last_ai_msg.tool_calls if tc["name"] != "write_todos"]
        if not non_write_todos_calls:
            return None

        error_messages = [
            ToolMessage(
                content=(
                    "Error: `write_todos` is a phase boundary for parallel orchestration. "
                    "Do not pair it with other tool calls in the same response. "
                    "Submit only `write_todos`, wait for the todo board update, then continue."
                ),
                tool_call_id=tc["id"],
                status="error",
            )
            for tc in non_write_todos_calls
        ]
        return {"messages": error_messages}

    @override
    def after_model(self, state: PlanningState, runtime: Runtime[ContextT]) -> dict[str, Any] | None:
        return (
            self._coerce_write_todos_args(state)
            or self._single_write_todos_only(state)
            or self._write_todos_is_phase_boundary(state)
        )

    @override
    async def aafter_model(self, state: PlanningState, runtime: Runtime[ContextT]) -> dict[str, Any] | None:
        return (
            self._coerce_write_todos_args(state)
            or self._single_write_todos_only(state)
            or self._write_todos_is_phase_boundary(state)
        )
