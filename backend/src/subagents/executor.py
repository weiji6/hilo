"""Subagent execution engine."""

import logging
import os
import re
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import httpx
from langchain.agents import create_agent
from langchain.tools import BaseTool
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.messages.utils import message_chunk_to_message
from langchain_core.runnables import RunnableConfig

from src.agents.retrieval_policy import OVERVIEW_SUBAGENT_PROMPT
from src.config.domain_config import render_domain_instructions
from src.agents.thread_state import SandboxState, ThreadDataState, ThreadState
from src.community.knowledge_base.citations import KNOWLEDGE_CITATION_REGISTRY_KEY
from src.community.knowledge_base.reading_state import SUBTASK_FINAL_RESULT_KEY
from src.community.knowledge_base.task_memory import (
    build_task_memory_injection_message,
    search_and_prepare_task_memory,
    upsert_task_memory_record,
)
from src.models import create_chat_model
from src.subagents.config import SubagentConfig
from src.utils.error_logging import append_error_doc
from src.utils.subtask_logging import log_subtask_event

logger = logging.getLogger(__name__)


class SubagentStatus(Enum):
    """Status of a subagent execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


@dataclass
class SubagentResult:
    """Result of a subagent execution.

    Attributes:
        task_id: Unique identifier for this execution.
        trace_id: Trace ID for distributed tracing (links parent and subagent logs).
        status: Current status of the execution.
        result: The final result message (if completed).
        error: Error message (if failed).
        started_at: When execution started.
        completed_at: When execution completed.
        ai_messages: List of complete AI messages (as dicts) generated during execution.
        structured_result: Parsed structured sections extracted from the final result.
        citation_registry: Numbered citation registry collected inside this subagent.
    """

    task_id: str
    trace_id: str
    status: SubagentStatus
    result: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    ai_messages: list[dict[str, Any]] | None = None
    structured_result: dict[str, Any] | None = None
    citation_registry: list[dict[str, Any]] | None = None

    def __post_init__(self):
        """Initialize mutable defaults."""
        if self.ai_messages is None:
            self.ai_messages = []


_SECTION_ALIASES: dict[str, str] = {
    "任务结果": "summary",
    "结果": "summary",
    "结论": "summary",
    "taskresult": "summary",
    "result": "summary",
    "关键发现": "findings",
    "发现": "findings",
    "findings": "findings",
    "关键引文": "citations",
    "引文": "citations",
    "引用": "citations",
    "citations": "citations",
    "未解决缺口": "open_questions",
    "缺口": "open_questions",
    "待继续检索": "open_questions",
    "open questions": "open_questions",
    "gaps": "open_questions",
}

_REFUSAL_PREFIXES = (
    "【证据不足】",
    "【无法确认】",
    "【无法回答】",
    "【信息不足】",
)

_DEFAULT_LANGGRAPH_BASE_URL = "http://127.0.0.1:2024"
_THREAD_CANCEL_CACHE_TTL_SECONDS = 1.0
_MAX_EXECUTION_RETRIES = 3
_RETRY_DELAY_SECONDS = 5


class SubagentCancelledError(RuntimeError):
    """Raised when a subagent is cancelled because its parent session stopped."""


@dataclass
class _ThreadCancelCacheEntry:
    fetched_at_monotonic: float
    cancel_requested_at: datetime | None


def _normalize_heading(heading: str) -> str:
    return re.sub(r"[\s:：\-]+", "", heading.strip().lower())


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        normalized = " ".join(item.split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(item.strip())
    return deduped


def _clip_for_subtask_log(value: Any, *, limit: int = 2000) -> Any:
    if isinstance(value, str):
        normalized = " ".join(value.split())
        if len(normalized) <= limit:
            return normalized
        return normalized[: limit - 1].rstrip() + "…"
    if isinstance(value, dict):
        return {str(key): _clip_for_subtask_log(item, limit=limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_clip_for_subtask_log(item, limit=limit) for item in value]
    return value


def _stable_log_signature(value: Any) -> str:
    return repr(_clip_for_subtask_log(value, limit=500))


def _extract_tool_call_debug_payload(message_dict: dict[str, Any]) -> dict[str, Any]:
    additional_kwargs = message_dict.get("additional_kwargs")
    if not isinstance(additional_kwargs, dict):
        additional_kwargs = {}

    response_metadata = message_dict.get("response_metadata")
    if not isinstance(response_metadata, dict):
        response_metadata = {}

    return {
        "tool_calls": _clip_for_subtask_log(message_dict.get("tool_calls") or []),
        "invalid_tool_calls": _clip_for_subtask_log(message_dict.get("invalid_tool_calls") or []),
        "additional_kwargs_tool_calls": _clip_for_subtask_log(additional_kwargs.get("tool_calls") or []),
        "response_metadata_finish_reason": response_metadata.get("finish_reason"),
    }


def _extract_bullets(block: str) -> list[str]:
    bullets: list[str] = []
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r"^[-*•]\s+", line):
            bullets.append(re.sub(r"^[-*•]\s+", "", line).strip())
            continue
        if re.match(r"^\d+\.\s+", line):
            bullets.append(re.sub(r"^\d+\.\s+", "", line).strip())
    return _dedupe_strings([item for item in bullets if item and item != "无"])


def _extract_citations(text: str) -> list[str]:
    citations = re.findall(r"\[citation:\s*\d+\s*\]", text)
    return _dedupe_strings(citations)


def _strip_reasoning_from_message_dict(message_dict: dict[str, Any]) -> dict[str, Any]:
    additional_kwargs = message_dict.get("additional_kwargs")
    if isinstance(additional_kwargs, dict):
        additional_kwargs.pop("reasoning_content", None)
        additional_kwargs.pop("reasoning", None)
    return message_dict


def _parse_refusal_summary(summary: str) -> tuple[bool, str | None]:
    normalized = summary.strip()
    for prefix in _REFUSAL_PREFIXES:
        if normalized.startswith(prefix):
            reason = normalized[len(prefix):].strip(" ：:;；，,")
            return True, reason or None
    return False, None


def _parse_structured_subtask_result(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None

    stripped = text.strip()
    if not stripped:
        return None

    sections: dict[str, list[str]] = {}
    current_key: str | None = None

    for line in stripped.splitlines():
        heading_match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if heading_match:
            normalized_heading = _normalize_heading(heading_match.group(1))
            current_key = _SECTION_ALIASES.get(normalized_heading)
            if current_key is not None:
                sections.setdefault(current_key, [])
            else:
                current_key = None
            continue

        if current_key is not None:
            sections.setdefault(current_key, []).append(line)

    summary_block = "\n".join(sections.get("summary", [])).strip()
    findings_block = "\n".join(sections.get("findings", [])).strip()
    citations_block = "\n".join(sections.get("citations", [])).strip()
    gaps_block = "\n".join(sections.get("open_questions", [])).strip()

    summary = summary_block
    if not summary:
        first_paragraph = stripped.split("\n\n", 1)[0].strip()
        summary = first_paragraph if first_paragraph else ""

    findings = _extract_bullets(findings_block)
    citations = _extract_bullets(citations_block) or _extract_citations(citations_block) or _extract_citations(stripped)
    open_questions = _extract_bullets(gaps_block)

    parsed = {
        "summary": summary,
        "findings": findings,
        "citations": citations,
        "open_questions": open_questions,
    }

    is_refusal, refusal_reason = _parse_refusal_summary(summary)
    if is_refusal:
        parsed["is_refusal"] = True
        if refusal_reason:
            parsed["refusal_reason"] = refusal_reason

    if not any(
        [
            parsed["summary"],
            parsed["findings"],
            parsed["citations"],
            parsed["open_questions"],
        ]
    ):
        return None

    return parsed


# Global storage for background task results
_background_tasks: dict[str, SubagentResult] = {}
_background_tasks_lock = threading.Lock()
_thread_cancel_cache: dict[str, _ThreadCancelCacheEntry] = {}
_thread_cancel_cache_lock = threading.Lock()

# Default subagent concurrency budget for orchestrated runs.
# Set to 6 to allow larger parallel retrieval batches — each subtask primarily
# waits on LLM + knowledge_locate I/O, so higher parallelism reduces wall-clock
# time without proportionally increasing CPU or memory pressure.
MAX_CONCURRENT_SUBAGENTS = 6

# Thread pool for background task scheduling and orchestration
_scheduler_pool = ThreadPoolExecutor(
    max_workers=MAX_CONCURRENT_SUBAGENTS,
    thread_name_prefix="subagent-scheduler-",
)

# Thread pool for actual subagent execution (with timeout support)
# Larger pool to avoid blocking when scheduler submits execution tasks
_execution_pool = ThreadPoolExecutor(
    max_workers=MAX_CONCURRENT_SUBAGENTS,
    thread_name_prefix="subagent-exec-",
)


def _get_langgraph_base_url() -> str:
    return (
        os.getenv("LANGGRAPH_BASE_URL")
        or os.getenv("NEXT_PUBLIC_LANGGRAPH_BASE_URL")
        or _DEFAULT_LANGGRAPH_BASE_URL
    )


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip()
    if not normalized:
        return None

    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)

    return parsed.astimezone(UTC)


def _fetch_thread_cancel_requested_at(thread_id: str) -> datetime | None:
    url = f"{_get_langgraph_base_url().rstrip('/')}/threads/{thread_id}"
    response = httpx.get(
        url,
        headers={"accept": "application/json"},
        timeout=2.0,
    )
    response.raise_for_status()

    payload = response.json()
    values = payload.get("values")
    if not isinstance(values, dict):
        return None

    return _parse_iso_datetime(values.get("subtasks_cancel_requested_at"))


def _get_thread_cancel_requested_at(thread_id: str) -> datetime | None:
    now = time.monotonic()
    with _thread_cancel_cache_lock:
        cached = _thread_cancel_cache.get(thread_id)
        if cached and now - cached.fetched_at_monotonic < _THREAD_CANCEL_CACHE_TTL_SECONDS:
            return cached.cancel_requested_at

    try:
        cancel_requested_at = _fetch_thread_cancel_requested_at(thread_id)
    except Exception:
        logger.debug(
            "Failed to fetch cancellation marker for thread %s",
            thread_id,
            exc_info=True,
        )
        cancel_requested_at = None

    with _thread_cancel_cache_lock:
        _thread_cancel_cache[thread_id] = _ThreadCancelCacheEntry(
            fetched_at_monotonic=now,
            cancel_requested_at=cancel_requested_at,
        )

    return cancel_requested_at


def _is_thread_cancellation_requested(
    thread_id: str | None,
    started_at: datetime | None,
) -> bool:
    if not thread_id or started_at is None:
        return False

    cancel_requested_at = _get_thread_cancel_requested_at(thread_id)
    if cancel_requested_at is None:
        return False

    normalized_started_at = (
        started_at.astimezone(UTC)
        if started_at.tzinfo is not None
        else started_at.replace(tzinfo=UTC)
    )
    return cancel_requested_at >= normalized_started_at


def _filter_tools(
    all_tools: list[BaseTool],
    allowed: list[str] | None,
    disallowed: list[str] | None,
) -> list[BaseTool]:
    """Filter tools based on subagent configuration.

    Args:
        all_tools: List of all available tools.
        allowed: Optional allowlist of tool names. If provided, only these tools are included.
        disallowed: Optional denylist of tool names. These tools are always excluded.

    Returns:
        Filtered list of tools.
    """
    filtered = all_tools

    # Apply allowlist if specified
    if allowed is not None:
        allowed_set = set(allowed)
        filtered = [t for t in filtered if t.name in allowed_set]

    # Apply denylist
    if disallowed is not None:
        disallowed_set = set(disallowed)
        filtered = [t for t in filtered if t.name not in disallowed_set]

    return filtered


def _get_model_name(config: SubagentConfig, parent_model: str | None) -> str | None:
    """Resolve the model name for a subagent.

    Args:
        config: Subagent configuration.
        parent_model: The parent agent's model name.

    Returns:
        Model name to use, or None to use default.
    """
    if config.model == "inherit":
        return parent_model
    return config.model


class SubagentExecutor:
    """Executor for running subagents."""

    def __init__(
        self,
        config: SubagentConfig,
        tools: list[BaseTool],
        parent_model: str | None = None,
        sandbox_state: SandboxState | None = None,
        thread_data: ThreadDataState | None = None,
        thread_id: str | None = None,
        user_id: str | None = None,
        trace_id: str | None = None,
        overview: bool = False,
    ):
        """Initialize the executor.

        Args:
            config: Subagent configuration.
            tools: List of all available tools (will be filtered).
            parent_model: The parent agent's model name for inheritance.
            sandbox_state: Sandbox state from parent agent.
            thread_data: Thread data from parent agent.
            thread_id: Thread ID for sandbox operations.
            user_id: User ID for scoped task-memory persistence.
            trace_id: Trace ID from parent for distributed tracing.
            overview: Use the bounded introductory retrieval profile for this turn.
        """
        self.config = config
        self.overview = overview
        self.parent_model = parent_model
        self.sandbox_state = sandbox_state
        self.thread_data = thread_data
        self.thread_id = thread_id
        self.user_id = user_id
        # Generate trace_id if not provided (for top-level calls)
        self.trace_id = trace_id or str(uuid.uuid4())[:8]

        # Filter tools based on config
        self.tools = _filter_tools(
            tools,
            config.tools,
            config.disallowed_tools,
        )

        # Auto-inject submit_task_result_tool for subagents.
        # This tool is essential for subtasks to signal completion; without it,
        # subtasks cannot return structured results to the lead agent.
        from src.tools.builtins import submit_task_result_tool

        tool_names = {t.name for t in self.tools}
        if submit_task_result_tool.name not in tool_names:
            # Only inject if the config's allowlist permits it (or no allowlist is set)
            if config.tools is None or submit_task_result_tool.name in config.tools:
                self.tools.append(submit_task_result_tool)
                logger.info(
                    "[trace=%s] Auto-injected submit_task_result_tool for subagent %s",
                    self.trace_id,
                    config.name,
                )

        logger.info(f"[trace={self.trace_id}] SubagentExecutor initialized: {config.name} with {len(self.tools)} tools")
        log_subtask_event(
            "subagent_executor_initialized",
            trace_id=self.trace_id,
            subagent_name=config.name,
            tool_count=len(self.tools),
            parent_model=parent_model,
            thread_id=thread_id,
        )

    def _create_agent(self):
        """Create the agent instance."""
        model_name = _get_model_name(self.config, self.parent_model)
        thinking_enabled = False if self.overview else self.config.thinking_enabled
        model = create_chat_model(name=model_name, thinking_enabled=thinking_enabled, **({"max_tokens": 768} if self.overview else {}))
        logger.info(
            "[trace=%s] Subagent %s using model=%s thinking_enabled=%s",
            self.trace_id,
            self.config.name,
            model_name,
            thinking_enabled,
        )

        # Subagents need minimal middlewares to ensure tools can access sandbox and thread_data
        # These middlewares will reuse the sandbox/thread_data from parent agent
        from src.agents.middlewares.citation_registry_sync_middleware import CitationRegistrySyncMiddleware
        from src.agents.middlewares.knowledge_checkpoint_middleware import KnowledgeCheckpointMiddleware
        from src.agents.middlewares.subagent_tool_limit_middleware import SubagentToolLimitMiddleware
        from src.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
        from src.sandbox.middleware import SandboxMiddleware

        middlewares = [
            ThreadDataMiddleware(lazy_init=True),  # Compute thread paths
            SandboxMiddleware(lazy_init=True),  # Reuse parent's sandbox (no re-acquisition)
            SubagentToolLimitMiddleware(tool_call_limit=4 if self.overview else 20),  # Force wrap-up when tool-call budget is exhausted
            CitationRegistrySyncMiddleware(),  # Ensure citation registry survives LangGraph checkpoints
        ]
        if not self.overview:
            middlewares.insert(2, KnowledgeCheckpointMiddleware())

        return create_agent(
            model=model,
            tools=self.tools,
            middleware=middlewares,
            system_prompt=(OVERVIEW_SUBAGENT_PROMPT if self.overview else self.config.system_prompt) + render_domain_instructions(),
            state_schema=ThreadState,
        )

    def _build_initial_state(self, task: str, *, task_title: str | None = None) -> dict[str, Any]:
        """Build the initial state for agent execution.

        Args:
            task: The task description.
            task_title: Optional stable title used for historical task matching.

        Returns:
            Initial state dictionary.
        """
        messages: list[HumanMessage] = [HumanMessage(content=task)]
        normalized_title = str(task_title or "").strip()
        state: dict[str, Any] = {"messages": messages}
        try:
            prepared_matches = search_and_prepare_task_memory(
                query=task,
                title=normalized_title or None,
                target_state=state,
                top_k=3,
            )
        except Exception:
            prepared_matches = []
        if prepared_matches:
            messages.append(
                HumanMessage(
                    content=build_task_memory_injection_message(
                        title=normalized_title or task,
                        query=task,
                        results=prepared_matches,
                    )
                )
            )

        # Pass through sandbox and thread data from parent
        if self.sandbox_state is not None:
            state["sandbox"] = self.sandbox_state
        if self.thread_data is not None:
            state["thread_data"] = self.thread_data
        if normalized_title:
            state["current_task_title"] = normalized_title

        return state

    def _persist_completed_task_memory(
        self,
        *,
        task: str,
        task_title: str | None,
        task_level: str,
        result: SubagentResult,
    ) -> None:
        title = str(task_title or "").strip() or result.task_id
        if not title or not result.result:
            return

        structured = result.structured_result or {}
        summary = str(structured.get("summary") or result.result or "").strip()
        findings = [str(item).strip() for item in structured.get("findings") or [] if str(item).strip()]
        citations = [str(item).strip() for item in structured.get("citations") or [] if str(item).strip()]
        open_questions = [str(item).strip() for item in structured.get("open_questions") or [] if str(item).strip()]
        if not summary:
            return

        storage_query = title if task_level == "subtask" else task
        try:
            upsert_task_memory_record(
                title=title,
                query=storage_query,
                summary=summary,
                findings=findings,
                citations=citations,
                open_questions=open_questions,
                citation_registry=result.citation_registry,
                task_level=task_level,
                thread_id=self.thread_id,
                user_id=self.user_id,
                task_id=result.task_id,
                raw_result=result.result,
            )
        except Exception:
            logger.exception(
                "[trace=%s] Failed to persist task memory for subtask %s",
                self.trace_id,
                result.task_id,
            )

    def _raise_if_cancelled(
        self,
        result: SubagentResult,
        cancel_event: threading.Event | None,
    ) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise SubagentCancelledError(
                f"Subtask {result.task_id} cancelled because the parent session was interrupted."
            )

    def execute(
        self,
        task: str,
        result_holder: SubagentResult | None = None,
        cancel_event: threading.Event | None = None,
        *,
        task_title: str | None = None,
        task_level: str = "subtask",
    ) -> SubagentResult:
        """Execute a task synchronously.

        Args:
            task: The task description for the subagent.
            result_holder: Optional pre-created result object to update during execution.
            cancel_event: Cooperative cancellation signal shared with the scheduler.

        Returns:
            SubagentResult with the execution result.
        """
        if result_holder is not None:
            # Use the provided result holder (for async execution with real-time updates)
            result = result_holder
        else:
            # Create a new result for synchronous execution
            task_id = str(uuid.uuid4())[:8]
            result = SubagentResult(
                task_id=task_id,
                trace_id=self.trace_id,
                status=SubagentStatus.RUNNING,
                started_at=datetime.now(UTC),
            )

        # Build config once; it is stateless and safe to reuse across retries.
        run_config: RunnableConfig = {
            "recursion_limit": self.config.max_turns,
        }
        context = {
            "trace_id": self.trace_id,
            "subtask_id": result.task_id,
            "subagent_name": self.config.name,
        }
        if self.thread_id:
            run_config["configurable"] = {"thread_id": self.thread_id}
            context["thread_id"] = self.thread_id

        # Compile agent inside retry loop so transient failures during model
        # initialisation (e.g. API connection blip) are retried rather than
        # causing an immediate permanent failure.
        agent = None

        for attempt in range(1, _MAX_EXECUTION_RETRIES + 1):
            try:
                self._raise_if_cancelled(result, cancel_event)
                if agent is None:
                    agent = self._create_agent()
                state = self._build_initial_state(task, task_title=task_title)

                logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} starting execution (attempt {attempt}/{_MAX_EXECUTION_RETRIES}) with max_turns={self.config.max_turns}")

                # --- submit_task_result enforcement loop ---
                # If the model stops without calling submit_task_result, inject a reminder
                # and re-run the stream so the subtask properly signals completion.
                _SUBMIT_REMINDER = (
                    "[System enforcement] You stopped without calling `submit_task_result`. "
                    "You MUST call `submit_task_result` now to submit your final result. "
                    "Do not output any more text — just call the tool immediately."
                )
                _submit_retry_count = 0
                _MAX_SUBMIT_RETRIES = 2

                while True:
                    # Use stream instead of invoke to get real-time updates.
                    # `messages` yields incremental AI chunks; `values` gives us the final state.
                    final_state = None
                    aggregated_chunks: dict[str, AIMessageChunk] = {}
                    logged_tool_call_signatures: set[tuple[str, str, str]] = set()
                    logged_ai_message_debug_signatures: set[tuple[str, str]] = set()
                    _step_start = time.monotonic()
                    _step_label = "init"
                    _llm_total_s: float = 0.0
                    _tool_total_s: float = 0.0
                    _llm_count: int = 0
                    _tool_count: int = 0
                    for mode, payload in agent.stream(  # type: ignore[arg-type]
                        state,
                        config=run_config,
                        context=context,
                        stream_mode=["messages", "values"],
                    ):
                        self._raise_if_cancelled(result, cancel_event)
                        if mode == "values":
                            elapsed = time.monotonic() - _step_start
                            final_state = payload
                            # Label the completed step by looking at the last message type
                            step_msgs = payload.get("messages", [])
                            if step_msgs:
                                last_step_msg = step_msgs[-1]
                                if isinstance(last_step_msg, AIMessage):
                                    _step_label = "llm_call"
                                    _llm_total_s += elapsed
                                    _llm_count += 1
                                elif isinstance(last_step_msg, ToolMessage):
                                    _step_label = "tool_exec"
                                    _tool_total_s += elapsed
                                    _tool_count += 1
                            logger.info(
                                "[trace=%s] subagent=%s step=%s elapsed=%.2fs msgs=%d",
                                self.trace_id,
                                self.config.name,
                                _step_label,
                                elapsed,
                                len(step_msgs),
                            )
                            _step_start = time.monotonic()
                            _step_label = "unknown"
                            continue
    
                        if mode != "messages":
                            continue
    
                        streamed_message, _metadata = payload
                        if isinstance(streamed_message, AIMessageChunk):
                            message_id = streamed_message.id or str(uuid.uuid4())
                            previous_chunk = aggregated_chunks.get(message_id)
                            aggregated_chunk = (
                                streamed_message
                                if previous_chunk is None
                                else previous_chunk + streamed_message
                            )
                            aggregated_chunks[message_id] = aggregated_chunk
                            message_dict = _strip_reasoning_from_message_dict(
                                message_chunk_to_message(aggregated_chunk).model_dump()
                            )
                        elif isinstance(streamed_message, AIMessage):
                            message_dict = _strip_reasoning_from_message_dict(
                                streamed_message.model_dump()
                            )
                        else:
                            continue
    
                        tool_call_debug_payload = _extract_tool_call_debug_payload(message_dict)
                        debug_signature = (
                            str(message_dict.get("id") or ""),
                            _stable_log_signature(tool_call_debug_payload),
                        )
                        if (
                            tool_call_debug_payload["tool_calls"]
                            or tool_call_debug_payload["invalid_tool_calls"]
                            or tool_call_debug_payload["additional_kwargs_tool_calls"]
                        ) and debug_signature not in logged_ai_message_debug_signatures:
                            logged_ai_message_debug_signatures.add(debug_signature)
                            log_subtask_event(
                                "subtask_ai_message_tool_calls",
                                trace_id=self.trace_id,
                                task_id=result.task_id,
                                subagent_name=self.config.name,
                                thread_id=self.thread_id,
                                message_id=message_dict.get("id"),
                                **tool_call_debug_payload,
                            )
    
                        if not result.ai_messages or result.ai_messages[-1] != message_dict:
                            result.ai_messages.append(message_dict)
                            logger.info(
                                f"[trace={self.trace_id}] Subagent {self.config.name} captured AI message snapshot #{len(result.ai_messages)}"
                            )
    
                        for tool_call in message_dict.get("tool_calls") or []:
                            if not isinstance(tool_call, dict):
                                continue
                            tool_call_id = str(tool_call.get("id") or "")
                            tool_name = str(tool_call.get("name") or "")
                            tool_args = tool_call.get("args")
                            signature = (tool_call_id, tool_name, _stable_log_signature(tool_args))
                            if not tool_name or signature in logged_tool_call_signatures:
                                continue
                            logged_tool_call_signatures.add(signature)
                            log_subtask_event(
                                "subtask_tool_call_requested",
                                trace_id=self.trace_id,
                                task_id=result.task_id,
                                subagent_name=self.config.name,
                                thread_id=self.thread_id,
                                tool_call_id=tool_call_id or None,
                                tool_name=tool_name,
                                tool_args=_clip_for_subtask_log(tool_args),
                            )
    
                    if final_state is not None:
                        for final_message in final_state.get("messages", []) or []:
                            if not isinstance(final_message, AIMessage):
                                continue
                            final_message_dict = _strip_reasoning_from_message_dict(final_message.model_dump())
                            tool_call_debug_payload = _extract_tool_call_debug_payload(final_message_dict)
                            debug_signature = (
                                str(final_message_dict.get("id") or ""),
                                _stable_log_signature(tool_call_debug_payload),
                            )
                            if (
                                tool_call_debug_payload["tool_calls"]
                                or tool_call_debug_payload["invalid_tool_calls"]
                                or tool_call_debug_payload["additional_kwargs_tool_calls"]
                            ) and debug_signature not in logged_ai_message_debug_signatures:
                                logged_ai_message_debug_signatures.add(debug_signature)
                                log_subtask_event(
                                    "subtask_final_state_tool_calls",
                                    trace_id=self.trace_id,
                                    task_id=result.task_id,
                                    subagent_name=self.config.name,
                                    thread_id=self.thread_id,
                                    message_id=final_message_dict.get("id"),
                                    **tool_call_debug_payload,
                                )
    
                    logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} completed execution")
                    log_subtask_event(
                        "subtask_timing_summary",
                        trace_id=self.trace_id,
                        task_id=result.task_id,
                        subagent_name=self.config.name,
                        llm_calls=_llm_count,
                        llm_total_s=round(_llm_total_s, 2),
                        llm_avg_s=round(_llm_total_s / _llm_count, 2) if _llm_count else 0,
                        tool_calls=_tool_count,
                        tool_total_s=round(_tool_total_s, 2),
                        tool_avg_s=round(_tool_total_s / _tool_count, 2) if _tool_count else 0,
                        total_s=round(_llm_total_s + _tool_total_s, 2),
                    )
                    self._raise_if_cancelled(result, cancel_event)
    
                    if final_state is None:
                        error_msg = (
                            f"Subagent {self.config.name} produced no output: "
                            "the LangGraph stream yielded no values events — "
                            "the agent may have terminated immediately (recursion limit, graph error, or empty run)"
                        )
                        logger.error("[trace=%s] attempt=%d/%d %s", self.trace_id, attempt, _MAX_EXECUTION_RETRIES, error_msg)
                        log_subtask_event(
                            "subtask_empty_stream",
                            trace_id=self.trace_id,
                            task_id=result.task_id,
                            subagent_name=self.config.name,
                            attempt=attempt,
                            max_retries=_MAX_EXECUTION_RETRIES,
                            error=error_msg,
                        )
                        raise RuntimeError(error_msg)
    
                    # Extract the final message - find the last AIMessage
                    messages = final_state.get("messages", [])
                    logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} final messages count: {len(messages)}")
    
                    # Check if submit_task_result was called
                    submitted: dict | None = final_state.get(SUBTASK_FINAL_RESULT_KEY)
                    if not submitted and _submit_retry_count < _MAX_SUBMIT_RETRIES:
                        # Inject reminder and re-run the stream
                        logger.warning(
                            "[trace=%s] Subagent %s did not call submit_task_result, injecting reminder (retry %d/%d)",
                            self.trace_id,
                            self.config.name,
                            _submit_retry_count + 1,
                            _MAX_SUBMIT_RETRIES,
                        )
                        log_subtask_event(
                            "subtask_missing_submit_task_result",
                            trace_id=self.trace_id,
                            task_id=result.task_id,
                            subagent_name=self.config.name,
                            retry_count=_submit_retry_count + 1,
                            max_retries=_MAX_SUBMIT_RETRIES,
                        )
                        # Append reminder message to state and continue the while loop
                        state["messages"].append(HumanMessage(content=_SUBMIT_REMINDER))
                        _submit_retry_count += 1
                        continue
                    # Break out of the while loop - either submit_task_result was called or we've exhausted retries
                    break

                # --- End of submit_task_result enforcement while loop ---
                # Result processing happens here, after the while loop exits.

                # Preferred path: subagent called submit_task_result, result is in state.
                if submitted and isinstance(submitted, dict) and submitted.get("summary", "").strip():
                    summary = submitted["summary"].strip()
                    findings = submitted.get("findings") or []
                    citations = submitted.get("citations") or []
                    gaps = submitted.get("gaps") or []
                    sections = [f"## 任务结果\n{summary}"]
                    if findings:
                        sections.append("## 关键发现\n" + "\n".join(f"- {f}" for f in findings))
                    if citations:
                        sections.append("## 关键引文\n" + "\n".join(f"- {c}" for c in citations))
                    sections.append("## 未解决缺口\n" + ("\n".join(f"- {g}" for g in gaps) if gaps else "- 无"))
                    result.result = "\n\n".join(sections)
                    result.structured_result = {
                        "summary": summary,
                        "findings": findings,
                        "citations": citations,
                        "open_questions": gaps,
                    }
                    logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} result from submit_task_result tool")
                else:
                    # Fallback: extract result from the last AIMessage.
                    if submitted is not None:
                        logger.warning(
                            f"[trace={self.trace_id}] Subagent {self.config.name} submit_task_result was called but summary is empty; falling back to last AIMessage"
                        )
                    last_ai_message = None
                    for msg in reversed(messages):
                        if isinstance(msg, AIMessage):
                            last_ai_message = msg
                            break

                    if last_ai_message is not None:
                        content = last_ai_message.content
                        # Handle both str and list content types for the final result
                        if isinstance(content, str):
                            result.result = content
                        elif isinstance(content, list):
                            # Extract text from list of content blocks for final result only
                            text_parts = []
                            for block in content:
                                if isinstance(block, str):
                                    text_parts.append(block)
                                elif isinstance(block, dict) and "text" in block:
                                    text_parts.append(block["text"])
                            result.result = "\n".join(text_parts) if text_parts else None
                        else:
                            result.result = str(content) or None
                    elif messages:
                        # No AIMessage at all — last message is probably a ToolMessage (unusual)
                        last_message = messages[-1]
                        logger.warning(
                            f"[trace={self.trace_id}] Subagent {self.config.name} no AIMessage found, "
                            f"last message type: {type(last_message).__name__}"
                        )
                        result.result = str(last_message.content) if hasattr(last_message, "content") else None

                if not result.result or not result.result.strip():
                    last_msg_type = type(messages[-1]).__name__ if messages else "none"
                    error_msg = (
                        f"Subagent {self.config.name} finished but produced an empty result "
                        f"(last_msg_type={last_msg_type}, total_msgs={len(messages)}). "
                        "The agent may have stopped without writing a final answer."
                    )
                    logger.error("[trace=%s] attempt=%d/%d %s", self.trace_id, attempt, _MAX_EXECUTION_RETRIES, error_msg)
                    log_subtask_event(
                        "subtask_empty_result",
                        trace_id=self.trace_id,
                        task_id=result.task_id,
                        subagent_name=self.config.name,
                        attempt=attempt,
                        max_retries=_MAX_EXECUTION_RETRIES,
                        last_msg_type=last_msg_type,
                        total_msgs=len(messages),
                        error=error_msg,
                    )
                    raise RuntimeError(error_msg)

                if result.structured_result is None:
                    result.structured_result = _parse_structured_subtask_result(result.result)
                if final_state is not None:
                    raw_registry = final_state.get(KNOWLEDGE_CITATION_REGISTRY_KEY)
                    if isinstance(raw_registry, list):
                        result.citation_registry = [item for item in raw_registry if isinstance(item, dict)]
                    logger.info(
                        "[trace=%s] Subagent %s citation_registry: count=%s, ids=%s, sample=%s",
                        self.trace_id,
                        self.config.name,
                        len(result.citation_registry) if result.citation_registry else 0,
                        [str(item.get("id")) for item in (result.citation_registry or [])],
                        result.citation_registry[:3] if result.citation_registry else None,
                    )

                self._raise_if_cancelled(result, cancel_event)
                result.status = SubagentStatus.COMPLETED
                result.completed_at = datetime.now(UTC)
                self._persist_completed_task_memory(
                    task=task,
                    task_title=task_title,
                    task_level=task_level,
                    result=result,
                )
                return result

            except SubagentCancelledError as e:
                logger.info(
                    "[trace=%s] Subagent %s cancelled: %s",
                    self.trace_id,
                    self.config.name,
                    e,
                )
                result.status = SubagentStatus.CANCELLED
                result.error = str(e)
                result.completed_at = datetime.now(UTC)
                return result
            except Exception as e:
                if cancel_event is not None and cancel_event.is_set():
                    logger.info(
                        "[trace=%s] Subagent %s observed cancellation during exception handling",
                        self.trace_id,
                        self.config.name,
                    )
                    result.status = SubagentStatus.CANCELLED
                    result.error = (
                        f"Subtask {result.task_id} cancelled because the parent session was interrupted."
                    )
                    result.completed_at = datetime.now(UTC)
                    return result

                if attempt < _MAX_EXECUTION_RETRIES:
                    logger.warning(
                        "[trace=%s] Subagent %s attempt %d/%d failed: %s — retrying in %ds",
                        self.trace_id,
                        self.config.name,
                        attempt,
                        _MAX_EXECUTION_RETRIES,
                        e,
                        _RETRY_DELAY_SECONDS,
                    )
                    log_subtask_event(
                        "subtask_execution_retry",
                        trace_id=self.trace_id,
                        task_id=result.task_id,
                        subagent_name=self.config.name,
                        attempt=attempt,
                        max_retries=_MAX_EXECUTION_RETRIES,
                        error=str(e),
                    )
                    result.ai_messages = []
                    result.result = None
                    result.structured_result = None
                    result.citation_registry = None
                    time.sleep(_RETRY_DELAY_SECONDS)
                    continue

                logger.exception(f"[trace={self.trace_id}] Subagent {self.config.name} execution failed after {_MAX_EXECUTION_RETRIES} attempts")
                append_error_doc(
                    location="subagent_executor.execute",
                    summary=f"Subagent {self.config.name} execution failed after {_MAX_EXECUTION_RETRIES} attempts",
                    error=str(e),
                    context={
                        "trace_id": self.trace_id,
                        "subagent_name": self.config.name,
                        "task_id": result.task_id,
                        "attempts": _MAX_EXECUTION_RETRIES,
                    },
                )
                result.status = SubagentStatus.FAILED
                result.error = str(e)
                result.completed_at = datetime.now(UTC)

        return result

    def execute_async(
        self,
        task: str,
        task_id: str | None = None,
        *,
        task_title: str | None = None,
        task_level: str = "subtask",
    ) -> str:
        """Start a task execution in the background.

        Args:
            task: The task description for the subagent.
            task_id: Optional task ID to use. If not provided, a random UUID will be generated.

        Returns:
            Task ID that can be used to check status later.
        """
        # Use provided task_id or generate a new one
        if task_id is None:
            task_id = str(uuid.uuid4())[:8]

        # Create initial pending result
        result = SubagentResult(
            task_id=task_id,
            trace_id=self.trace_id,
            status=SubagentStatus.PENDING,
        )

        logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} starting async execution, task_id={task_id}, timeout={self.config.timeout_seconds}s")
        log_subtask_event(
            "subtask_async_queued",
            trace_id=self.trace_id,
            task_id=task_id,
            subagent_name=self.config.name,
            timeout_seconds=self.config.timeout_seconds,
        )

        with _background_tasks_lock:
            _background_tasks[task_id] = result

        # Submit to scheduler pool
        def run_task():
            with _background_tasks_lock:
                _background_tasks[task_id].status = SubagentStatus.RUNNING
                _background_tasks[task_id].started_at = datetime.now(UTC)
                result_holder = _background_tasks[task_id]
                started_at = result_holder.started_at
            cancel_event = threading.Event()
            cancel_logged = False
            cancel_grace_deadline_monotonic: float | None = None

            try:
                log_subtask_event(
                    "subtask_async_started",
                    trace_id=self.trace_id,
                    task_id=task_id,
                    subagent_name=self.config.name,
                )
                # Submit execution to execution pool with timeout
                # Pass result_holder so execute() can update it in real-time
                execution_future: Future = _execution_pool.submit(
                    self.execute,
                    task,
                    result_holder,
                    cancel_event,
                    task_title=task_title,
                    task_level=task_level,
                )
                timeout_deadline_monotonic = time.monotonic() + self.config.timeout_seconds

                while True:
                    if _is_thread_cancellation_requested(self.thread_id, started_at):
                        if not cancel_event.is_set():
                            cancel_event.set()
                            cancel_grace_deadline_monotonic = time.monotonic() + 2.0
                            execution_future.cancel()
                            if not cancel_logged:
                                log_subtask_event(
                                    "subtask_async_cancel_requested",
                                    trace_id=self.trace_id,
                                    task_id=task_id,
                                    subagent_name=self.config.name,
                                    thread_id=self.thread_id,
                                )
                                cancel_logged = True

                        if (
                            cancel_grace_deadline_monotonic is not None
                            and time.monotonic() >= cancel_grace_deadline_monotonic
                        ):
                            with _background_tasks_lock:
                                _background_tasks[task_id].status = SubagentStatus.CANCELLED
                                _background_tasks[task_id].error = (
                                    "Subtask cancelled because the parent session was interrupted."
                                )
                                _background_tasks[task_id].completed_at = datetime.now(UTC)
                            log_subtask_event(
                                "subtask_async_cancelled",
                                trace_id=self.trace_id,
                                task_id=task_id,
                                subagent_name=self.config.name,
                                thread_id=self.thread_id,
                            )
                            return

                    remaining_timeout = timeout_deadline_monotonic - time.monotonic()
                    if remaining_timeout <= 0:
                        raise FuturesTimeoutError

                    try:
                        exec_result = execution_future.result(
                            timeout=min(0.25, remaining_timeout),
                        )
                    except FuturesTimeoutError:
                        continue

                    with _background_tasks_lock:
                        _background_tasks[task_id].status = exec_result.status
                        _background_tasks[task_id].result = exec_result.result
                        _background_tasks[task_id].error = exec_result.error
                        _background_tasks[task_id].completed_at = datetime.now(UTC)
                        _background_tasks[task_id].ai_messages = exec_result.ai_messages
                        _background_tasks[task_id].structured_result = exec_result.structured_result
                        _background_tasks[task_id].citation_registry = exec_result.citation_registry
                    log_subtask_event(
                        "subtask_async_finished",
                        trace_id=self.trace_id,
                        task_id=task_id,
                        subagent_name=self.config.name,
                        status=exec_result.status.value,
                        result=exec_result.result,
                        error=exec_result.error,
                        ai_message_count=len(exec_result.ai_messages or []),
                        structured_result=exec_result.structured_result,
                    )
                    return
            except FuturesTimeoutError:
                if cancel_event.is_set():
                    with _background_tasks_lock:
                        _background_tasks[task_id].status = SubagentStatus.CANCELLED
                        _background_tasks[task_id].error = (
                            "Subtask cancelled because the parent session was interrupted."
                        )
                        _background_tasks[task_id].completed_at = datetime.now(UTC)
                    log_subtask_event(
                        "subtask_async_cancelled",
                        trace_id=self.trace_id,
                        task_id=task_id,
                        subagent_name=self.config.name,
                        thread_id=self.thread_id,
                    )
                    return
                logger.error(f"[trace={self.trace_id}] Subagent {self.config.name} execution timed out after {self.config.timeout_seconds}s")
                append_error_doc(
                    location="subagent_executor.execute_async",
                    summary=f"Subagent {self.config.name} execution timed out",
                    error=f"Execution timed out after {self.config.timeout_seconds} seconds",
                    context={
                        "trace_id": self.trace_id,
                        "subagent_name": self.config.name,
                        "task_id": task_id,
                    },
                )
                with _background_tasks_lock:
                    _background_tasks[task_id].status = SubagentStatus.TIMED_OUT
                    _background_tasks[task_id].error = f"Execution timed out after {self.config.timeout_seconds} seconds"
                    _background_tasks[task_id].completed_at = datetime.now(UTC)
                log_subtask_event(
                    "subtask_async_timeout",
                    trace_id=self.trace_id,
                    task_id=task_id,
                    subagent_name=self.config.name,
                    timeout_seconds=self.config.timeout_seconds,
                )
                # Cancel the future (best effort - may not stop the actual execution)
                execution_future.cancel()
            except Exception as e:
                logger.exception(f"[trace={self.trace_id}] Subagent {self.config.name} async execution failed")
                append_error_doc(
                    location="subagent_executor.execute_async",
                    summary=f"Subagent {self.config.name} async execution failed",
                    error=str(e),
                    context={
                        "trace_id": self.trace_id,
                        "subagent_name": self.config.name,
                        "task_id": task_id,
                    },
                )
                with _background_tasks_lock:
                    _background_tasks[task_id].status = SubagentStatus.FAILED
                    _background_tasks[task_id].error = str(e)
                    _background_tasks[task_id].completed_at = datetime.now(UTC)
                log_subtask_event(
                    "subtask_async_failed",
                    trace_id=self.trace_id,
                    task_id=task_id,
                    subagent_name=self.config.name,
                    error=str(e),
                )

        _scheduler_pool.submit(run_task)
        return task_id


def get_background_task_result(task_id: str) -> SubagentResult | None:
    """Get the result of a background task.

    Args:
        task_id: The task ID returned by execute_async.

    Returns:
        SubagentResult if found, None otherwise.
    """
    with _background_tasks_lock:
        return _background_tasks.get(task_id)


def list_background_tasks() -> list[SubagentResult]:
    """List all background tasks.

    Returns:
        List of all SubagentResult instances.
    """
    with _background_tasks_lock:
        return list(_background_tasks.values())
