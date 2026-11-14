"""Task tool for delegating work to subagents."""

import logging
import time
import uuid
from dataclasses import replace
from typing import Annotated, Literal

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langgraph.config import get_stream_writer
from langgraph.typing import ContextT

from src.agents.lead_agent.prompt import get_skills_prompt_section
from src.agents.thread_state import ThreadState
from src.agents.retrieval_policy import overview_from_messages
from src.subagents import SubagentExecutor, get_subagent_config
from src.subagents.executor import SubagentStatus, get_background_task_result
from src.utils.error_logging import append_error_doc

logger = logging.getLogger(__name__)


@tool("task", parse_docstring=True)
def task_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    description: str,
    prompt: str,
    subagent_type: Literal["general-purpose", "bash"],
    tool_call_id: Annotated[str, InjectedToolCallId],
    max_turns: int | None = None,
) -> str:
    """Delegate a task to a specialized subagent that runs in its own context.

    Subagents help you:
    - Preserve context by keeping exploration and implementation separate
    - Handle complex multi-step tasks autonomously
    - Execute commands or operations in isolated contexts

    Available subagent types:
    - **general-purpose**: A capable agent for complex, multi-step tasks that require
      both exploration and action. Use when the task requires complex reasoning,
      multiple dependent steps, or would benefit from isolated context.
    - **bash**: Command execution specialist for running bash commands. Use for
      git operations, build processes, or when command output would be verbose.

    When to use this tool:
    - Complex tasks requiring multiple steps or tools
    - Tasks that produce verbose output
    - When you want to isolate context from the main conversation
    - Parallel research or exploration tasks

    When NOT to use this tool:
    - Simple, single-step operations (use tools directly)
    - Tasks requiring user interaction or clarification

    Args:
        description: A short (3-5 word) description of the task for logging/display. ALWAYS PROVIDE THIS PARAMETER FIRST.
        prompt: The task description for the subagent. Be specific and clear about what needs to be done. ALWAYS PROVIDE THIS PARAMETER SECOND.
        subagent_type: The type of subagent to use. ALWAYS PROVIDE THIS PARAMETER THIRD.
        max_turns: Optional maximum number of agent turns. Defaults to subagent's configured max.
    """
    trace_id = str(uuid.uuid4())[:8]
    writer = None

    try:
        # Get subagent configuration
        config = get_subagent_config(subagent_type)
        if config is None:
            return f"Task failed. Error: Unknown subagent type '{subagent_type}'. Available: general-purpose, bash"

        # Build config overrides
        overrides: dict = {}

        skills_section = get_skills_prompt_section()
        if skills_section:
            overrides["system_prompt"] = config.system_prompt + "\n\n" + skills_section

        if max_turns is not None:
            overrides["max_turns"] = max_turns

        if overrides:
            config = replace(config, **overrides)

        # Extract parent context from runtime
        sandbox_state = None
        thread_data = None
        thread_id = None
        user_id = None
        parent_model = None

        if runtime is not None:
            sandbox_state = runtime.state.get("sandbox")
            thread_data = runtime.state.get("thread_data")
            thread_id = runtime.context.get("thread_id")
            user_id = runtime.context.get("user_id")

            # Try to get parent model from configurable
            metadata = runtime.config.get("metadata", {})
            parent_model = metadata.get("model_name")

            # Get or generate trace_id for distributed tracing
            trace_id = metadata.get("trace_id") or trace_id

        writer = get_stream_writer()

        # Get available tools (excluding task tool to prevent nesting)
        # Lazy import to avoid circular dependency
        from src.tools import get_available_tools

        # Subagents should not have subagent tools enabled (prevent recursive nesting)
        tools = get_available_tools(model_name=parent_model, subagent_enabled=False)

        # Create executor
        executor = SubagentExecutor(
            config=config,
            tools=tools,
            parent_model=parent_model,
            sandbox_state=sandbox_state,
            thread_data=thread_data,
            thread_id=thread_id,
            user_id=user_id,
            trace_id=trace_id,
            overview=overview_from_messages(runtime.state.get("messages", [])) if runtime is not None else False,
        )

        # Start background execution (always async to prevent blocking)
        # Use tool_call_id as task_id for better traceability
        task_id = executor.execute_async(
            prompt,
            task_id=tool_call_id,
            task_title=description,
            task_level="subtask",
        )

        # Poll for task completion in backend (removes need for LLM to poll)
        poll_count = 0
        last_status = None
        last_message_count = 0  # Track how many AI messages we've already sent
        # Polling timeout: execution timeout + 60s buffer, checked every 1s
        max_poll_count = (config.timeout_seconds + 60) * 4  # 250ms polling interval

        logger.info(f"[trace={trace_id}] Started background task {task_id} (subagent={subagent_type}, timeout={config.timeout_seconds}s, polling_limit={max_poll_count} polls)")

        writer({"type": "task_started", "task_id": task_id, "description": description})

        while True:
            result = get_background_task_result(task_id)

            if result is None:
                logger.error(f"[trace={trace_id}] Task {task_id} not found in background tasks")
                append_error_doc(
                    location="task_tool",
                    summary="Background task disappeared before completion",
                    error="Task disappeared from background tasks",
                    context={
                        "trace_id": trace_id,
                        "task_id": task_id,
                        "description": description,
                        "subagent_type": subagent_type,
                    },
                )
                writer({"type": "task_failed", "task_id": task_id, "error": "Task disappeared from background tasks"})
                return f"Task failed. Error: Task {task_id} disappeared from background tasks"

            # Log status changes for debugging
            if result.status != last_status:
                logger.info(f"[trace={trace_id}] Task {task_id} status: {result.status.value}")
                last_status = result.status

            # Check for new AI messages and send task_running events
            current_message_count = len(result.ai_messages)
            if current_message_count > last_message_count:
                # Send task_running event for each new message
                for i in range(last_message_count, current_message_count):
                    message = result.ai_messages[i]
                    writer(
                        {
                            "type": "task_running",
                            "task_id": task_id,
                            "message": message,
                            "message_index": i + 1,  # 1-based index for display
                            "total_messages": current_message_count,
                        }
                    )
                    logger.info(f"[trace={trace_id}] Task {task_id} sent message #{i + 1}/{current_message_count}")
                last_message_count = current_message_count

            # Check if task completed, failed, or timed out
            if result.status == SubagentStatus.COMPLETED:
                execution_time = (result.completed_at - result.started_at).total_seconds() if result.started_at and result.completed_at else None
                writer({"type": "task_completed", "task_id": task_id, "result": result.result, "execution_time_seconds": execution_time})
                logger.info(f"[trace={trace_id}] Task {task_id} completed after {poll_count} polls")
                return f"Task Succeeded. Result: {result.result}"
            elif result.status == SubagentStatus.FAILED:
                execution_time = (result.completed_at - result.started_at).total_seconds() if result.started_at and result.completed_at else None
                writer({"type": "task_failed", "task_id": task_id, "error": result.error, "execution_time_seconds": execution_time})
                logger.error(f"[trace={trace_id}] Task {task_id} failed: {result.error}")
                append_error_doc(
                    location="task_tool",
                    summary="Subagent task failed",
                    error=result.error,
                    context={
                        "trace_id": trace_id,
                        "task_id": task_id,
                        "description": description,
                        "subagent_type": subagent_type,
                    },
                )
                return f"Task failed. Error: {result.error}"
            elif result.status == SubagentStatus.TIMED_OUT:
                execution_time = (result.completed_at - result.started_at).total_seconds() if result.started_at and result.completed_at else None
                writer({"type": "task_timed_out", "task_id": task_id, "error": result.error, "execution_time_seconds": execution_time})
                logger.warning(f"[trace={trace_id}] Task {task_id} timed out: {result.error}")
                append_error_doc(
                    location="task_tool",
                    summary="Subagent task timed out",
                    error=result.error,
                    context={
                        "trace_id": trace_id,
                        "task_id": task_id,
                        "description": description,
                        "subagent_type": subagent_type,
                    },
                )
                return f"Task timed out. Error: {result.error}"
            elif result.status == SubagentStatus.CANCELLED:
                writer({"type": "task_failed", "task_id": task_id, "error": result.error})
                logger.info(f"[trace={trace_id}] Task {task_id} cancelled: {result.error}")
                return f"Task cancelled. Error: {result.error}"

            # Still running, wait before next poll
            time.sleep(0.25)  # Poll every 250ms — matches execution_future.result() slice
            poll_count += 1

            # Polling timeout as a safety net (in case thread pool timeout doesn't work)
            # Set to (execution timeout + 60s) × 4 because we now poll at 250ms intervals
            if poll_count > max_poll_count:
                elapsed_s = poll_count * 0.25
                logger.error(f"[trace={trace_id}] Task {task_id} polling timed out after {poll_count} polls ({elapsed_s:.0f}s) (should have been caught by thread pool timeout)")
                append_error_doc(
                    location="task_tool",
                    summary="Task polling exceeded safety timeout",
                    error="Task polling timed out",
                    context={
                        "trace_id": trace_id,
                        "task_id": task_id,
                        "description": description,
                        "subagent_type": subagent_type,
                        "poll_count": poll_count,
                    },
                )
                writer({"type": "task_timed_out", "task_id": task_id})
                return f"Task timed out. Error: Task polling timed out after {elapsed_s:.0f}s. This may indicate the background task is stuck. Status: {result.status.value}"
    except Exception as exc:
        logger.exception(f"[trace={trace_id}] task_tool failed before subagent completion")
        append_error_doc(
            location="task_tool",
            summary="task_tool raised before subagent completion",
            error=str(exc),
            context={
                "trace_id": trace_id,
                "tool_call_id": tool_call_id,
                "description": description,
                "subagent_type": subagent_type,
            },
        )
        if writer is not None:
            try:
                writer({"type": "task_failed", "task_id": tool_call_id, "error": str(exc)})
            except Exception:
                logger.debug(f"[trace={trace_id}] Failed to emit task_failed event after exception", exc_info=True)
        return f"Task failed. Error: {exc}"
