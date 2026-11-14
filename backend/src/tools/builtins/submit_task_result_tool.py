"""Tool for subagents to submit their final structured result."""

from typing import Annotated

from langchain.tools import InjectedToolCallId, ToolRuntime
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.constants import END
from langgraph.types import Command
from langgraph.typing import ContextT

from src.agents.thread_state import ThreadState
from src.community.knowledge_base.reading_state import SUBTASK_FINAL_RESULT_KEY


@tool("submit_task_result", parse_docstring=True)
def submit_task_result_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    summary: str,
    findings: list[str],
    citations: list[str],
    gaps: list[str],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Submit the final structured result for this subtask. This MUST be the last tool call.

    Call this tool once you have gathered sufficient evidence and are ready to return
    findings to the lead agent. After calling this tool, output nothing further — the
    task is complete.

    Args:
        summary: Full content of ## 任务结果 — detailed findings with inline citations. Do NOT write a one-sentence summary; write everything the lead agent needs to synthesize the answer.
        findings: Bullet-point list for ## 关键发现 — one discrete fact or judgment per item, each with 1-3 citation markers.
        citations: Reusable citation lines for ## 关键引文 — copy the exact numbered markers returned by knowledge_locate.
        gaps: Items for ## 未解决缺口 — unresolved questions or missing evidence. Write `无` as a single-item list if there are none.
    """
    if not summary or not summary.strip():
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="Error: `summary` must not be empty. Write the full ## 任务结果 content before submitting.",
                        tool_call_id=tool_call_id,
                        name="submit_task_result",
                    )
                ]
            }
        )

    result_payload = {
        "summary": summary.strip(),
        "findings": [f for f in findings if f and str(f).strip()],
        "citations": [c for c in citations if c and str(c).strip()],
        "gaps": [g for g in gaps if g and str(g).strip()],
    }

    return Command(
        goto=END,
        update={
            SUBTASK_FINAL_RESULT_KEY: result_payload,
            "messages": [
                ToolMessage(
                    content="任务结果已提交，子任务结束。",
                    tool_call_id=tool_call_id,
                    name="submit_task_result",
                )
            ],
        },
    )
