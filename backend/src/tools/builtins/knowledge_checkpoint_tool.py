import ast
import json
from typing import Annotated

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langgraph.typing import ContextT

from src.agents.thread_state import ThreadState


def _render_list_section(title: str, items: list[str] | None, *, fallback: str) -> str:
    normalized = [item.strip() for item in items or [] if item and item.strip()]
    if not normalized:
        return f"## {title}\n{fallback}"
    lines = [f"## {title}"]
    lines.extend(f"- {item}" for item in normalized)
    return "\n".join(lines)


def _normalize_string_list(value: list[str] | str | None) -> list[str] | None:
    if value is None:
        return None

    if isinstance(value, list):
        normalized = [str(item).strip() for item in value if str(item).strip()]
        return normalized or None

    text = value.strip()
    if not text:
        return None

    for loader in (json.loads, ast.literal_eval):
        try:
            parsed = loader(text)
        except (ValueError, SyntaxError, json.JSONDecodeError, TypeError):
            continue

        if isinstance(parsed, list):
            normalized = [str(item).strip() for item in parsed if str(item).strip()]
            return normalized or None

        if isinstance(parsed, str):
            stripped = parsed.strip()
            return [stripped] if stripped else None

    bullet_lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(("- ", "* ", "• ")):
            line = line[2:].strip()
        bullet_lines.append(line)
    if len(bullet_lines) > 1:
        return bullet_lines

    return [text]


@tool("knowledge_checkpoint", parse_docstring=True)
def knowledge_checkpoint_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    title: str,
    summary: str,
    citations: list[str] | str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    covered_scope: str | None = None,
    open_questions: list[str] | str | None = None,
) -> Command:
    """Create a retrieval checkpoint that compresses completed knowledge-search findings.

    Use this after you finish one substantial retrieval block, such as one stage,
    one topic facet, one book cluster, or one completed section of the report.
    The checkpoint becomes the durable compressed context for later turns, so it
    must faithfully preserve the findings you will still need after the raw
    `knowledge_search` / `knowledge_locate` outputs are hidden from later model calls.

    This tool should be used proactively as part of the normal retrieval workflow,
    not only when the user reminds you. If you have already gathered a usable block
    of grounded findings and are about to switch topics, continue searching elsewhere,
    or start drafting, you should call this tool first.

    When to use:
    - After finishing one major retrieval section and before moving to the next section
    - When you have gathered enough evidence that you can summarize it faithfully
    - When previous `knowledge_search` / `knowledge_locate` outputs are getting verbose
    - Before drafting the final answer if the current turn gathered substantive new findings

    When NOT to use:
    - Before you have substantive findings
    - As a substitute for actual retrieval
    - With unsupported guesses or facts that did not come from the retrieved material

    Requirements:
    - `summary` should be detailed, factual, and limited to what the retrieved material supports
    - `citations` should prefer the exact `citation:` lines returned by the knowledge tools
    - Include unresolved gaps in `open_questions` if more retrieval is still needed
    - Write enough detail that later steps can rely on the checkpoint without rereading the hidden raw tool outputs

    Args:
        title: Short label for this retrieval block, such as `北洋政府时期财政`.
        summary: Faithful detailed summary of findings from the completed retrieval block.
        citations: Required supporting citation lines copied from `knowledge_search` / `knowledge_locate`.
        covered_scope: Optional one-line description of what this checkpoint covers.
        open_questions: Optional list of gaps or next retrieval targets that still remain.
    """
    normalized_citations = _normalize_string_list(citations)
    normalized_open_questions = _normalize_string_list(open_questions)
    if not title.strip() or not summary.strip() or not normalized_citations:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=(
                            "Error: knowledge_checkpoint requires non-empty `title`, `summary`, and `citations`. "
                            "Do not checkpoint unsupported or citation-free retrieval. Continue with "
                            "`book_search` / `knowledge_locate(doc_id=\"...\")`, or stop with `【证据不足】`."
                        ),
                        tool_call_id=tool_call_id,
                        name="knowledge_checkpoint",
                    )
                ]
            }
        )

    sections = [f"# 检索检查点：{title.strip()}"]
    if covered_scope and covered_scope.strip():
        sections.append(f"## 覆盖范围\n{covered_scope.strip()}")
    sections.append(f"## 核心发现\n{summary.strip()}")
    sections.append(
        _render_list_section(
            "关键引文",
            normalized_citations,
            fallback="（无）",
        )
    )
    sections.append(
        _render_list_section(
            "待继续检索",
            normalized_open_questions,
            fallback="（当前板块暂无额外待检索问题）",
        )
    )

    return Command(
        update={
            "messages": [
                ToolMessage(
                    content="\n\n".join(sections).strip(),
                    tool_call_id=tool_call_id,
                    name="knowledge_checkpoint",
                )
            ]
        }
    )
