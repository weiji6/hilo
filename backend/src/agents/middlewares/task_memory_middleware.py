from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any, NotRequired, override

logger = logging.getLogger(__name__)

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.runtime import Runtime

from src.agents.middlewares.title_middleware import title_from_query
from src.community.knowledge_base.citations import citation_registry_update_fragment
from src.community.knowledge_base.task_memory import (
    build_task_memory_injection_message,
    is_non_reusable_failure_summary,
    search_and_prepare_task_memory,
    upsert_task_memory_record,
)
from src.models import create_chat_model

TASK_MEMORY_DECISION_SYSTEM_PROMPT = (
    "你是任务记忆写入判定器，只决定当前对话是否应该写入长期任务记忆库。\n"
    "只输出 JSON，不要输出解释或代码块。格式："
    '{"action":"add|update|skip","title":"可选新标题","target_task_id":"可选目标 task_id",'
    '"target_title":"可选目标标题","reason":"简短原因"}。\n'
    "判定规则：\n"
    "1. add：用户问题和助手回答形成了一个完整、可复用的研究/实现结论，未来相似任务值得召回。\n"
    "2. update：当前回答是在延续、纠正、补充一个已有主题，应覆盖同一主题记忆；必须从输入的“本轮命中的历史记忆候选”里"
    "填写 target_task_id 或 target_title，不能凭空造目标。title 可以省略；若填写，应与目标标题一致。\n"
    "3. skip：闲聊、澄清、报错、进度说明、很短的回答、只含建议问题/参考文献、系统提示/注入内容、低信息密度内容、"
    "或没有形成稳定可复用结论。\n"
    "4. 不要因为回答存在就写入；只有可复用的任务成果才 add/update。\n"
    "5. add 时 title 必须是用户真实主题的短标题；update 时必须明确 target_task_id 或 target_title；"
    "任何标题都不能包含 XML 标签、系统插入提示、task_memory_matches、当前 query 等注入文本。"
)
TASK_MEMORY_DECISION_CONTAMINATION_PATTERN = re.compile(
    r"<task_memory_matches>|</task_memory_matches>|系统插入提示|不是用户的新问题|当前\s*query|当前任务标题|强制历史证据包",
    re.IGNORECASE,
)
REFERENCE_OR_SUGGESTION_SECTION_PATTERN = re.compile(
    r"(?im)^\s{0,3}(?:#{1,6}\s*)?(?:参考文献|建议问题)\s*$|^\s{0,3}\*\*(?:参考文献|建议问题)\*\*\s*$"
)


class TaskMemoryMiddlewareState(AgentState):
    current_task_title: NotRequired[str | None]
    current_task_human_index: NotRequired[int | None]
    task_memory_injected_human_index: NotRequired[int | None]
    task_memory_saved_human_index: NotRequired[int | None]
    current_task_memory_match_titles: NotRequired[list[str]]
    current_task_memory_matches: NotRequired[list[dict[str, str]]]
    title: NotRequired[str | None]


def _stringify_content(content: Any) -> str:
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


def _strip_injected_context(text: str) -> str:
    stripped = re.sub(r"<task_memory_matches>[\s\S]*?</task_memory_matches>", "", text)
    stripped = re.sub(r"<uploaded_files>[\s\S]*?</uploaded_files>", "", stripped)
    return stripped.strip()


def _strip_generated_sections(text: str) -> str:
    match = REFERENCE_OR_SUGGESTION_SECTION_PATTERN.search(text)
    if not match:
        return text.strip()
    return text[: match.start()].rstrip()


def _extract_citations(text: str) -> list[str]:
    seen: set[str] = set()
    citations: list[str] = []
    for match in re.finditer(r"\[citation:\s*(\d+)\s*\](?:\((?:<[^>\n]+>|[^)\n]+)\))?", text, re.IGNORECASE):
        citation = f"[citation:{match.group(1)}]"
        if citation in seen:
            continue
        seen.add(citation)
        citations.append(citation)
    return citations


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = str(text or "").strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    match = re.search(r"\{[\s\S]*\}", stripped)
    if match:
        stripped = match.group(0)
    parsed = json.loads(stripped)
    return parsed if isinstance(parsed, dict) else {}


def _sanitize_memory_title(title: str, fallback: str) -> str:
    cleaned = _strip_injected_context(str(title or "")).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned or TASK_MEMORY_DECISION_CONTAMINATION_PATTERN.search(cleaned):
        return fallback.strip()
    return cleaned[:80]


def _memory_match_candidates(results: list[dict[str, Any]]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in results:
        metadata = item.get("metadata") or {}
        candidate = {
            "record_id": str(metadata.get("record_id") or "").strip(),
            "title": str(metadata.get("title") or "").strip(),
            "task_id": str(metadata.get("task_id") or "").strip(),
        }
        key = (candidate["record_id"], candidate["title"], candidate["task_id"])
        if not any(candidate.values()) or key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


def _resolve_update_title(decision: dict[str, Any], candidates: list[dict[str, str]]) -> str | None:
    target_task_id = str(decision.get("target_task_id") or "").strip()
    target_title = _sanitize_memory_title(str(decision.get("target_title") or decision.get("title") or ""), "")
    for candidate in candidates:
        if target_task_id and candidate.get("task_id") == target_task_id:
            return candidate.get("title") or None
        if target_title and candidate.get("title") == target_title:
            return candidate.get("title") or None
    return None


def _decide_task_memory_action(
    *,
    title: str,
    query: str,
    summary: str,
    matched_candidates: list[dict[str, str]],
) -> dict[str, str]:
    clean_query = _strip_injected_context(query)
    clean_summary = _strip_generated_sections(_strip_injected_context(summary))
    if len(clean_query) < 4 or len(clean_summary) < 40:
        return {"action": "skip", "title": title, "reason": "content too short"}
    if TASK_MEMORY_DECISION_CONTAMINATION_PATTERN.search(clean_query):
        return {"action": "skip", "title": title, "reason": "injected context only"}
    if is_non_reusable_failure_summary(clean_summary):
        return {"action": "skip", "title": title, "reason": "insufficient evidence"}

    try:
        model = create_chat_model(thinking_enabled=False)
        response = model.invoke(
            [
                SystemMessage(content=TASK_MEMORY_DECISION_SYSTEM_PROMPT),
                HumanMessage(
                    content=(
                        f"候选标题：{title}\n\n"
                        f"用户真实问题：\n{clean_query}\n\n"
                        f"助手最终回答正文：\n{clean_summary[:4000]}\n\n"
                        f"本轮命中的历史记忆候选：{json.dumps(matched_candidates, ensure_ascii=False)}"
                    )
                ),
            ]
        )
        decision = _parse_json_object(_stringify_content(getattr(response, "content", response)))
    except Exception:
        return {"action": "skip", "title": title, "reason": "decision model failed"}

    action = str(decision.get("action") or "skip").strip().lower()
    if action not in {"add", "update", "skip"}:
        action = "skip"
    if action == "update":
        update_title = _resolve_update_title(decision, matched_candidates)
        if not update_title:
            return {"action": "skip", "title": title, "reason": "update target not matched"}
        decided_title = update_title
    else:
        decided_title = _sanitize_memory_title(str(decision.get("title") or title), title)
    if action == "add" and not decided_title:
        action = "skip"
    return {
        "action": action,
        "title": decided_title or title,
        "reason": str(decision.get("reason") or "").strip()[:200],
    }


def _latest_human_message(messages: list[Any]) -> tuple[int, HumanMessage] | None:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, HumanMessage):
            content = _stringify_content(message.content)
            if "<task_memory_matches>" in content:
                continue
            return index, message
    return None


class TaskMemoryMiddleware(AgentMiddleware[TaskMemoryMiddlewareState]):
    """Generate a task title, inject historical matches, and persist completed main-task results."""

    state_schema = TaskMemoryMiddlewareState

    @override
    def before_model(self, state: TaskMemoryMiddlewareState, runtime: Runtime) -> dict | None:
        messages = list(state.get("messages", []))
        latest_human = _latest_human_message(messages)
        if latest_human is None:
            return None

        human_index, human_message = latest_human
        query = _strip_injected_context(_stringify_content(human_message.content))
        if not query:
            return None

        updates: dict[str, Any] = {}
        current_task_title = str(state.get("current_task_title") or "").strip()
        if state.get("current_task_human_index") != human_index or not current_task_title:
            current_task_title = title_from_query(query)
            updates["current_task_title"] = current_task_title
            updates["current_task_human_index"] = human_index
            if not state.get("title"):
                updates["title"] = current_task_title

        if state.get("task_memory_injected_human_index") == human_index:
            return updates or None

        try:
            prepared_matches = search_and_prepare_task_memory(
                query=query,
                title=current_task_title,
                target_state=state,
                top_k=3,
            )
        except Exception:
            prepared_matches = []
        match_candidates = _memory_match_candidates(prepared_matches)
        updates["current_task_memory_matches"] = match_candidates
        updates["current_task_memory_match_titles"] = [
            candidate["title"] for candidate in match_candidates if candidate.get("title")
        ]
        updates["task_memory_injected_human_index"] = human_index
        # search_and_prepare_task_memory mutated state["knowledge_citation_registry"]
        # in place, but LangGraph only fires channel updates from returned values,
        # so we must echo the merged registry back through `updates`.
        updates.update(citation_registry_update_fragment(state))
        if not prepared_matches:
            return updates or None

        updates["messages"] = [
            HumanMessage(
                content=build_task_memory_injection_message(
                    title=current_task_title,
                    query=query,
                    results=prepared_matches,
                )
            )
        ]
        return updates

    @override
    def after_agent(self, state: TaskMemoryMiddlewareState, runtime: Runtime) -> dict | None:
        current_task_title = str(state.get("current_task_title") or "").strip()
        current_task_human_index = state.get("current_task_human_index")
        if not current_task_title or current_task_human_index is None:
            return None
        if state.get("task_memory_saved_human_index") == current_task_human_index:
            return None

        messages = list(state.get("messages", []))
        if current_task_human_index >= len(messages):
            return None

        human_message = messages[current_task_human_index]
        latest_message = messages[-1] if messages else None
        if not isinstance(human_message, HumanMessage) or not isinstance(latest_message, AIMessage):
            return None
        if getattr(latest_message, "tool_calls", None):
            return None

        query = _strip_injected_context(_stringify_content(human_message.content))
        summary = _strip_generated_sections(_strip_injected_context(_stringify_content(latest_message.content))).strip()
        if not query or not summary:
            return None

        matched_candidates = [
            {
                "record_id": str(item.get("record_id") or "").strip(),
                "title": str(item.get("title") or "").strip(),
                "task_id": str(item.get("task_id") or "").strip(),
            }
            for item in state.get("current_task_memory_matches", [])
            if isinstance(item, dict)
        ]
        if not matched_candidates:
            matched_candidates = [
                {"record_id": "", "title": str(item).strip(), "task_id": ""}
                for item in state.get("current_task_memory_match_titles", [])
                if str(item).strip()
            ]
        # Run the slow LLM decision + upsert in a background daemon thread so the
        # stream can end immediately after the agent response, without the user
        # seeing an extra loading delay caused by the memory-save LLM call.
        thread_id = runtime.context.get("thread_id")
        user_id = runtime.context.get("user_id")
        citation_registry = (
            state.get("knowledge_citation_registry")
            if isinstance(state.get("knowledge_citation_registry"), list)
            else None
        )
        task_id = f"main:{thread_id}:{current_task_human_index}"

        def _save_in_background() -> None:
            try:
                decision = _decide_task_memory_action(
                    title=current_task_title,
                    query=query,
                    summary=summary,
                    matched_candidates=matched_candidates,
                )
                action = decision.get("action")
                if action == "skip":
                    return
                upsert_task_memory_record(
                    title=decision.get("title") or current_task_title,
                    query=query,
                    summary=summary,
                    citations=_extract_citations(summary),
                    findings=[],
                    open_questions=[],
                    citation_registry=citation_registry,
                    task_level="main",
                    thread_id=thread_id,
                    user_id=user_id,
                    task_id=task_id,
                    raw_result=summary,
                )
                logger.debug("Task memory saved in background: task_id=%s action=%s", task_id, action)
            except Exception:
                logger.warning("Background task memory save failed: task_id=%s", task_id, exc_info=True)

        threading.Thread(target=_save_in_background, daemon=True, name="task-memory-save").start()

        # Return immediately so the stream closes without waiting for the LLM decision.
        return {"task_memory_saved_human_index": current_task_human_index}
