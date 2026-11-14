"""Middleware to enforce staged QA output with body citations, references, and suggestions."""

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import override
from urllib.parse import quote, urlsplit

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.agents.retrieval_policy import is_overview_question, overview_from_messages
from src.community.knowledge_base.citations import KNOWLEDGE_CITATION_REGISTRY_KEY
from src.models.minimax_thinking import sanitize_minimax_anthropic_thinking_text

logger = logging.getLogger(__name__)


GROUNDING_TOOL_NAMES = {"knowledge_search", "knowledge_locate"}
CITATION_SOURCE_TOOL_NAMES = GROUNDING_TOOL_NAMES | {"knowledge_checkpoint", "write_todos"}
CITATION_PATTERN = re.compile(r"\[citation:[^\]]+\](?:\((?:<[^>\n]+>|[^)\n]+)\))?", re.IGNORECASE)
NUMBERED_CITATION_PATTERN = re.compile(r"\[citation:\s*\d+\s*\](?:\((?:<[^>\n]+>|[^)\n]+)\))?", re.IGNORECASE)
REFUSAL_PREFIX_PATTERN = re.compile(r"^\s*【无法回答】", re.IGNORECASE)
REFERENCE_SECTION_PATTERNS = (
    re.compile(r"(?im)^\s{0,3}(?:#{1,6}\s*)?参考文献\s*$"),
    re.compile(r"(?im)^\s{0,3}\*\*参考文献\*\*\s*$"),
)
SUGGESTION_SECTION_PATTERNS = (
    re.compile(r"(?im)^\s{0,3}(?:#{1,6}\s*)?建议问题\s*$"),
    re.compile(r"(?im)^\s{0,3}\*\*建议问题\*\*\s*$"),
)
RETRY_APPENDIX = (
    "\n\n[System enforcement]\n"
    "Your previous draft was blocked because it used grounded knowledge results (`knowledge_search` / `knowledge_locate`) without the required body citations.\n"
    "Regenerate the full answer from scratch.\n"
    "Requirements:\n"
    "1. If you use any knowledge from `knowledge_search` or `knowledge_locate`, every grounded factual claim in the answer body must carry citation markers copied from the available citation lines, such as `[citation:1]`.\n"
    "2. Place citations immediately after the supported sentence, clause, bullet, or table-related claim they justify. Do not postpone citations to the end of the paragraph or only to `参考文献`.\n"
    "3. If you use bullet points, each bullet that contains grounded evidence must end with one or more citation markers.\n"
    "4. Do not add `参考文献` or `建议问题` sections. The system will generate them in later stages.\n"
    "5. If you cannot support the answer with citations, refuse using the exact prefix `【无法回答】` followed by a brief reason.\n"
    "6. Do not mention this enforcement message in the final answer."
)
RETRY_APPENDIX_FINAL = (
    "\n\n[System enforcement - final retry]\n"
    "Your previous retry still missed the required body citations.\n"
    "Regenerate the full answer from scratch one more time.\n"
    "Additional requirements:\n"
    "1. Reuse the exact numbered `citation:` lines returned by `knowledge_search` / `knowledge_locate` whenever possible; do not rewrite citation links manually.\n"
    "2. Every grounded sentence, bullet, numeric statement, table summary, or scoped conclusion must be immediately followed by one or more exact citation markers from this turn.\n"
    "3. If you cite a source, the answer body must contain the numbered citation marker from this turn, not a plain-text source mention.\n"
    "4. An uncited overview paragraph is not acceptable if it relies on grounded retrieval.\n"
    "5. Do not add `参考文献` or `建议问题` sections. The system will generate them separately.\n"
    "6. If you still cannot produce a fully cited answer, refuse explicitly using the exact prefix `【无法回答】`.\n"
    "7. Do not mention this enforcement message in the final answer."
)
FINAL_FALLBACK_RESPONSE = (
    "【无法回答】无法根据当前资料生成带 citation 的回答，因此本轮不输出未经依据支持的内容。\n\n"
    "请缩小问题范围，或稍后重试。"
)
UNGROUNDED_WARNING_MARKER = "<!-- HISTORY_RAG_UNGROUNDED -->"
UNGROUNDED_SUBSTANTIVE_THRESHOLD = 50
RETRY_APPENDICES = (RETRY_APPENDIX, RETRY_APPENDIX_FINAL)
SUGGESTION_SYSTEM_PROMPT = (
    "你负责回答链路中的第 3 阶段：生成建议问题。\n"
    "输入会包含用户原问题、阶段 1 的回答正文、当前主任务/子任务的已有发现摘要，以及阶段 2 的参考文献信息（如果有）。\n"
    "请只输出 3 行建议问题，每行一个问题，不要输出标题、解释、前言、后记、代码块或额外编号说明。\n"
    "要求：\n"
    "1. 必须与当前问题和当前回答高度相关。\n"
    "2. 必须结合阶段 1 正文和已有发现摘要中的具体对象、版本、机制、证据缺口或来源线索来发问。\n"
    "3. 问题应有实际研究意义，优先追问机制解释、适用条件、版本差异、来源互证或尚未解决的分歧；不要输出套话式问题。\n"
    "4. 禁止使用“关键阶段或专题是什么”“机制、人物或制度是哪一项”“哪个对比视角或来源视角”等泛化模板，除非已替换为当前发现中的具体对象。\n"
    "5. 如果阶段 1 是 `【无法回答】`，问题应引导用户缩小范围、补充线索、指定材料或切换到更可检索的角度。\n"
    "6. 默认使用与用户相同的语言。"
)
SUGGESTION_HEADING_PATTERN = re.compile(r"^(?:#{1,6}\s*|\*\*)?建议问题(?:\*\*)?\s*$", re.IGNORECASE)
QUESTION_PREFIX_PATTERN = re.compile(r"^\s*(?:[-*•]|\d+[.)]|[一二三四五六七八九十]+[、.])\s*")
TASK_MEMORY_BLOCK_PATTERN = re.compile(r"<task_memory_matches>[\s\S]*?</task_memory_matches>", re.IGNORECASE)
UPLOADED_FILES_BLOCK_PATTERN = re.compile(r"<uploaded_files>[\s\S]*?</uploaded_files>", re.IGNORECASE)
SUGGESTION_CONTAMINATION_PATTERN = re.compile(
    r"<task_memory_matches>|</task_memory_matches>|系统插入提示|不是用户的新问题|当前\s*query|当前任务标题|强制历史证据包",
    re.IGNORECASE,
)


def _stringify_content(content: object) -> str:
    if isinstance(content, str):
        return sanitize_minimax_anthropic_thinking_text(content).content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(sanitize_minimax_anthropic_thinking_text(str(item.get("text", ""))).content)
            elif isinstance(item, dict) and item.get("type") in {"thinking", "redacted_thinking"}:
                continue
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content or "")


def _latest_human_index(messages: list) -> int:
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return index
    return 0


def _latest_human_message(messages: list) -> str:
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            content = _strip_injected_context(_stringify_content(messages[index].content))
            if content:
                return content
    return ""


def _strip_injected_context(content: str) -> str:
    cleaned = TASK_MEMORY_BLOCK_PATTERN.sub("", content)
    cleaned = UPLOADED_FILES_BLOCK_PATTERN.sub("", cleaned)
    return cleaned.strip()


def _find_first_section_start(content: str) -> int | None:
    matches = []
    for pattern in (*REFERENCE_SECTION_PATTERNS, *SUGGESTION_SECTION_PATTERNS):
        match = pattern.search(content)
        if match:
            matches.append(match.start())
    return min(matches) if matches else None


def _strip_generated_sections(content: str) -> str:
    start = _find_first_section_start(content)
    if start is None:
        return content.strip()
    return content[:start].rstrip()


def _normalize_numbered_citation_marker(citation: str) -> str | None:
    match = re.match(r"\[citation:\s*(\d+)\s*\](?:\((?:<[^>\n]+>|[^)\n]+)\))?", citation.strip(), re.IGNORECASE)
    if not match:
        return None
    return f"[citation:{match.group(1)}]"



def _extract_citations(content: str) -> list[str]:
    seen: set[str] = set()
    citations: list[str] = []
    for citation in NUMBERED_CITATION_PATTERN.findall(content):
        normalized_citation = _normalize_numbered_citation_marker(citation)
        if not normalized_citation or normalized_citation in seen:
            continue
        seen.add(normalized_citation)
        citations.append(normalized_citation)
    return citations


def _tool_message_contains_citations(message: ToolMessage) -> bool:
    return bool(NUMBERED_CITATION_PATTERN.search(_stringify_content(message.content)))


def _extract_citation_inner_label(citation: str) -> str:
    match = re.match(r"\[citation:([^\]]+)\](?:\([^)]+\))?", citation, re.IGNORECASE)
    return match.group(1).strip() if match else citation.strip()


def _extract_citation_url(citation: str) -> str | None:
    match = re.match(r"\[citation:[^\]]+\]\((<[^>\n]+>|[^)\n]+)\)", citation, re.IGNORECASE)
    if not match:
        return None
    url = match.group(1).strip()
    if url.startswith("<") and url.endswith(">"):
        url = url[1:-1].strip()
    return url or None


def _normalize_internal_citation_url(url: str | None) -> str | None:
    if not url:
        return None
    if url.startswith("/api/knowledge/docs/") or url.startswith("/api/secure-knowledge/users/me/knowledge/docs/"):
        return quote(url, safe="/:?=&%#")
    return url


def _normalize_citation_markdown(citation: str) -> str:
    url = _extract_citation_url(citation)
    normalized_url = _normalize_internal_citation_url(url)
    if not url or not normalized_url or normalized_url == url:
        return citation
    wrapped_url = f"<{normalized_url}>" if "<" in citation else normalized_url
    return re.sub(
        r"\((<[^>\n]+>|[^)\n]+)\)$",
        f"({wrapped_url})",
        citation,
        count=1,
    )


def _is_valid_citation_url(url: str | None) -> bool:
    if not url:
        return False
    if re.match(r"^citations?:", url, re.IGNORECASE):
        return False

    normalized_url = _normalize_internal_citation_url(url)
    if normalized_url is None:
        return False
    if re.search(r"\s", normalized_url):
        return False

    if normalized_url.startswith("/"):
        try:
            parts = urlsplit(normalized_url)
        except Exception:
            return False
        return bool(parts.path)

    try:
        parts = urlsplit(normalized_url)
    except Exception:
        return False
    return parts.scheme in {"http", "https"} and bool(parts.netloc)


def _is_valid_citation_markdown(citation: str) -> bool:
    url = _extract_citation_url(citation)
    return _is_valid_citation_url(url)


def _normalize_citation_text(text: str) -> str:
    translated = text.translate(str.maketrans({"（": "(", "）": ")", "：": ":", "　": " "}))
    return re.sub(r"\s+", "", translated).strip().lower()


@dataclass(frozen=True)
class _CitationCandidate:
    label: str
    full_citation: str
    normalized_label: str
    display_label: str | None = None


def _request_state(messages_or_request: object) -> dict | None:
    state = getattr(messages_or_request, "state", None)
    return state if isinstance(state, dict) else None


def _build_registry_citation_candidates(state: dict | None) -> list[_CitationCandidate]:
    if not state:
        return []
    raw_registry = state.get(KNOWLEDGE_CITATION_REGISTRY_KEY)
    if not isinstance(raw_registry, list):
        return []

    candidates: list[_CitationCandidate] = []
    seen: set[str] = set()
    for item in raw_registry:
        if not isinstance(item, dict):
            continue
        citation_id = str(item.get("id") or "").strip()
        label = str(item.get("label") or "").strip()
        if not citation_id:
            continue
        full_citation = f"[citation:{citation_id}]"
        normalized_label = _normalize_citation_text(citation_id)
        if normalized_label in seen:
            continue
        seen.add(normalized_label)
        candidates.append(
            _CitationCandidate(
                label=citation_id,
                full_citation=full_citation,
                normalized_label=normalized_label,
                display_label=label or citation_id,
            )
        )
    return candidates



def _build_tool_message_citation_candidates(messages: list) -> list[_CitationCandidate]:
    candidates: list[_CitationCandidate] = []
    seen: set[str] = set()
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        content = _stringify_content(message.content)
        for match in re.finditer(r"citation:\s*\[citation:\s*(\d+)\s*\](?:\s*\(([^)\n]+)\))?", content, re.IGNORECASE):
            citation_id = str(match.group(1) or "").strip()
            if not citation_id:
                continue
            normalized_label = _normalize_citation_text(citation_id)
            if normalized_label in seen:
                continue
            seen.add(normalized_label)
            display_label = str(match.group(2) or "").strip() or citation_id
            candidates.append(
                _CitationCandidate(
                    label=citation_id,
                    full_citation=f"[citation:{citation_id}]",
                    normalized_label=normalized_label,
                    display_label=display_label,
                )
            )
    return candidates



def _build_citation_candidates(messages: list, state: dict | None = None) -> list[_CitationCandidate]:
    merged: list[_CitationCandidate] = []
    seen: set[str] = set()
    current_messages = messages[_latest_human_index(messages):]
    typed_pages = [
        _stringify_content(message.content)
        for message in current_messages
        if isinstance(message, ToolMessage) and message.name == "knowledge_locate"
        and "页面类型:" in _stringify_content(message.content)
    ]
    body_ids = None
    if typed_pages and overview_from_messages(messages):
        body_ids = set()
        for content in typed_pages:
            for block in re.split(r"(?=### 整页)", content):
                if "页面类型: body" in block:
                    body_ids.update(re.findall(r"citation:\s*\[citation:\s*(\d+)\s*\]", block))
    for candidate in [*_build_registry_citation_candidates(state), *_build_tool_message_citation_candidates(messages)]:
        if body_ids is not None and candidate.label not in body_ids:
            continue
        if candidate.normalized_label in seen:
            continue
        seen.add(candidate.normalized_label)
        merged.append(candidate)
    return merged

def _available_citation_lines(messages: list, state: dict | None = None) -> list[str]:
    lines: list[str] = []
    for candidate in _build_citation_candidates(messages, state):
        if candidate.display_label:
            lines.append(f"citation: [citation:{candidate.label}] ({candidate.display_label})")
    return lines


def _resolve_citation_from_candidates(citation: str, messages: list, state: dict | None = None) -> str | None:
    label = _extract_citation_inner_label(citation)
    normalized_label = _normalize_citation_text(label)
    candidates = _build_citation_candidates(messages, state)
    if not candidates:
        return None

    for candidate in candidates:
        if candidate.normalized_label == normalized_label:
            return candidate.full_citation
    return None


def _consume_optional_markdown_link_target(text: str, start_index: int) -> int:
    index = start_index
    while index < len(text) and text[index] in {" ", "\t"}:
        index += 1
    if index >= len(text) or text[index] != "(":
        return start_index

    index += 1
    if index < len(text) and text[index] == "<":
        while index < len(text) and text[index] not in {">", "\n"}:
            index += 1
        if index < len(text) and text[index] == ">":
            index += 1
        if index < len(text) and text[index] == ")":
            index += 1
        return index

    depth = 1
    while index < len(text):
        char = text[index]
        if char == "\n":
            break
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                index += 1
                return index
        index += 1
    return index


def _replace_numbered_citation_mentions(answer_body: str, replacements: dict[str, str]) -> str:
    replacement_index = len(replacements)

    def _replace(match: re.Match[str]) -> str:
        nonlocal replacement_index
        normalized_citation = _normalize_numbered_citation_marker(match.group(0))
        if not normalized_citation:
            return match.group(0)
        placeholder = f"@@KNOWLEDGE_CITATION_{replacement_index}@@"
        replacement_index += 1
        replacements[placeholder] = normalized_citation
        return placeholder

    return NUMBERED_CITATION_PATTERN.sub(_replace, answer_body)



def _normalize_answer_citations(answer_body: str, messages: list, state: dict | None = None) -> str:
    replacements: dict[str, str] = {}
    repaired_body = _replace_numbered_citation_mentions(answer_body, replacements)
    repaired_body = CITATION_PATTERN.sub("", repaired_body)
    for placeholder, full_citation in replacements.items():
        repaired_body = repaired_body.replace(placeholder, full_citation)
    return repaired_body

def _has_supported_body_citation(answer_body: str, messages: list, state: dict | None = None) -> bool:
    citations = _extract_citations(answer_body)
    if not citations:
        return False

    candidates = _build_citation_candidates(messages, state)
    if not candidates:
        return False

    candidate_set = {candidate.full_citation for candidate in candidates}
    return all(citation in candidate_set or _resolve_citation_from_candidates(citation, messages, state) for citation in citations)


def _should_mark_ungrounded_answer(answer_body: str, messages: list, state: dict | None = None) -> bool:
    return (
        not _is_refusal(answer_body)
        and len(answer_body.strip()) > UNGROUNDED_SUBSTANTIVE_THRESHOLD
        and not _has_supported_body_citation(answer_body, messages, state)
    )


def _build_reference_section(answer_body: str) -> str:
    citations = _extract_citations(answer_body)
    if not citations:
        return ""
    lines = ["参考文献"]
    lines.extend(f"{index}. {citation}" for index, citation in enumerate(citations, start=1))
    return "\n".join(lines)


def _is_refusal(content: str) -> bool:
    return bool(REFUSAL_PREFIX_PATTERN.match(content.strip()))


def _normalize_question_text(text: str) -> str:
    cleaned = QUESTION_PREFIX_PATTERN.sub("", text.strip())
    return cleaned.strip(" \t\"'`")


def _question_seed(user_question: str) -> str:
    seed = " ".join(_strip_injected_context(user_question).split())
    if len(seed) > 36:
        return f"{seed[:33]}..."
    return seed or "当前主题"


def _fallback_suggested_questions(*, user_question: str, refusal: bool) -> list[str]:
    seed = _question_seed(user_question)
    if refusal:
        return [
            f"能否把“{seed}”缩小到更具体的时期、人物、制度或事件后再检索？",
            f"如果指定一本相关书、一个章节名或一组关键词，是否更容易继续回答“{seed}”？",
            f"围绕“{seed}”，下一步最值得优先核实的资料线索是什么？",
        ]
    return [
        f"围绕“{seed}”，下一步最值得继续展开的关键阶段或专题是什么？",
        f"如果继续深挖“{seed}”，最需要补充证据的机制、人物或制度是哪一项？",
        f"基于“{seed}”，还有哪个对比视角或来源视角值得继续追问？",
    ]


def _clip_for_prompt(text: str, *, limit: int = 6000) -> str:
    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _current_findings_context(messages: list) -> str:
    start = _latest_human_index(messages)
    blocks: list[str] = []
    for message in messages[start:]:
        if not isinstance(message, ToolMessage):
            continue
        tool_name = getattr(message, "name", None)
        if tool_name not in CITATION_SOURCE_TOOL_NAMES:
            continue
        content = _strip_injected_context(_stringify_content(message.content))
        if not content:
            continue
        if tool_name == "write_todos":
            title = "本轮 todo 子任务返回的主任务发现"
        elif tool_name == "knowledge_checkpoint":
            title = "本轮知识检查点/主任务总结"
        else:
            title = f"本轮 {tool_name} 证据摘要"
        blocks.append(f"### {title}\n{content}")

    return _clip_for_prompt("\n\n".join(blocks), limit=6000)


def _normalize_suggested_questions(*, text: str, user_question: str, refusal: bool) -> list[str]:
    seen: set[str] = set()
    questions: list[str] = []
    clean_user_question = _strip_injected_context(user_question)

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if SUGGESTION_HEADING_PATTERN.match(line):
            continue
        normalized = _normalize_question_text(sanitize_minimax_anthropic_thinking_text(line).content)
        if SUGGESTION_CONTAMINATION_PATTERN.search(normalized):
            continue
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        questions.append(normalized)

    for fallback in _fallback_suggested_questions(user_question=clean_user_question, refusal=refusal):
        if len(questions) >= 3:
            break
        if fallback in seen:
            continue
        seen.add(fallback)
        questions.append(fallback)

    return questions[:3]


def _build_suggestion_prompt(
    *,
    user_question: str,
    answer_body: str,
    reference_section: str,
    findings_context: str = "",
) -> str:
    references = reference_section or "（本轮无参考文献阶段内容）"
    clean_user_question = _strip_injected_context(user_question)
    clean_answer_body = _strip_injected_context(answer_body)
    clean_findings_context = _strip_injected_context(findings_context).strip()
    return (
        f"用户原问题：\n{clean_user_question or '（未提供）'}\n\n"
        f"阶段1-回答正文：\n{clean_answer_body or '（空）'}\n\n"
        f"当前主任务/子任务已有发现摘要：\n{clean_findings_context or '（无额外发现摘要）'}\n\n"
        f"阶段2-参考文献：\n{references}"
    )


class CitationEnforcementMiddleware(AgentMiddleware[AgentState]):
    """Require body citations for grounded answers, then assemble references and suggestions."""

    def _turn_used_grounding_tools(self, messages: list) -> bool:
        start = _latest_human_index(messages)
        for message in messages[start:]:
            if not isinstance(message, ToolMessage):
                continue
            tool_name = getattr(message, "name", None)
            if tool_name in GROUNDING_TOOL_NAMES:
                return True
            if tool_name == "write_todos" and _tool_message_contains_citations(message):
                return True
        return False

    def _needs_enforcement(self, response: ModelResponse, messages: list, state: dict | None = None) -> bool:
        if not self._turn_used_grounding_tools(messages):
            return False

        ai_messages = [message for message in response.result if isinstance(message, AIMessage)]
        if not ai_messages:
            return False

        final_message = ai_messages[-1]
        if final_message.tool_calls:
            return False

        content = _stringify_content(final_message.content)
        answer_body = _normalize_answer_citations(
            _strip_generated_sections(content),
            messages,
            state,
        )
        if _is_refusal(answer_body):
            return False
        return not _has_supported_body_citation(answer_body, messages, state)

    def _build_retry_request(self, request: ModelRequest, appendix: str) -> ModelRequest:
        current_system = _stringify_content(request.system_message.content) if request.system_message else ""
        state = _request_state(request)
        available_citations = _available_citation_lines(request.messages, state)
        citation_hint = ""
        if available_citations:
            joined = "\n".join(f"- {line}" for line in available_citations)
            citation_hint = (
                "\n\nAvailable citation lines from this turn. Copy these exact citation markers into the answer body:\n"
                f"{joined}\n"
                "Use them inline, immediately after the factual sentence, bullet, or table-related claim they support."
            )
        retry_system = SystemMessage(
            content=f"{current_system}{appendix}{citation_hint}" if current_system else f"{appendix}{citation_hint}"
        )
        return request.override(system_message=retry_system)

    def _fallback_response(self, response: ModelResponse) -> ModelResponse:
        final_ai_index = None
        final_message = None
        for index in range(len(response.result) - 1, -1, -1):
            message = response.result[index]
            if isinstance(message, AIMessage):
                final_ai_index = index
                final_message = message
                break

        if final_ai_index is None or final_message is None:
            return response

        fallback_message = final_message.model_copy(update={"content": FINAL_FALLBACK_RESPONSE, "tool_calls": []})
        updated_result = list(response.result)
        updated_result[final_ai_index] = fallback_message
        return ModelResponse(result=updated_result, structured_response=response.structured_response)

    def _enforce_with_retry(
        self,
        request: ModelRequest,
        response: ModelResponse,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        state = _request_state(request)
        if not self._needs_enforcement(response, request.messages, state):
            return response

        retry_request = request
        retry_response = response
        for appendix in RETRY_APPENDICES:
            retry_request = self._build_retry_request(retry_request, appendix)
            retry_response = handler(retry_request)
            if not self._needs_enforcement(retry_response, request.messages, state):
                return retry_response

        return self._fallback_response(retry_response)

    async def _aenforce_with_retry(
        self,
        request: ModelRequest,
        response: ModelResponse,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        state = _request_state(request)
        if not self._needs_enforcement(response, request.messages, state):
            return response

        retry_request = request
        retry_response = response
        for appendix in RETRY_APPENDICES:
            retry_request = self._build_retry_request(retry_request, appendix)
            retry_response = await handler(retry_request)
            if not self._needs_enforcement(retry_response, request.messages, state):
                return retry_response

        return self._fallback_response(retry_response)

    def _generate_suggested_questions_sync(
        self,
        *,
        request: ModelRequest,
        user_question: str,
        answer_body: str,
        reference_section: str,
    ) -> list[str]:
        refusal = _is_refusal(answer_body)
        user_question = _strip_injected_context(user_question)
        if is_overview_question(user_question):
            return _fallback_suggested_questions(user_question=user_question, refusal=refusal)
        model = getattr(request, "model", None)
        if model is None or not hasattr(model, "invoke"):
            return _fallback_suggested_questions(user_question=user_question, refusal=refusal)

        try:
            result = model.invoke(
                [
                    SystemMessage(content=SUGGESTION_SYSTEM_PROMPT),
                    HumanMessage(
                        content=_build_suggestion_prompt(
                            user_question=user_question,
                            answer_body=answer_body,
                            reference_section=reference_section,
                            findings_context=_current_findings_context(request.messages),
                        )
                    ),
                ]
            )
            return _normalize_suggested_questions(
                text=_stringify_content(getattr(result, "content", result)),
                user_question=user_question,
                refusal=refusal,
            )
        except Exception as exc:  # pragma: no cover - defensive path
            logger.warning("Failed to generate suggested questions synchronously: %s", exc)
            return _fallback_suggested_questions(user_question=user_question, refusal=refusal)

    async def _generate_suggested_questions_async(
        self,
        *,
        request: ModelRequest,
        user_question: str,
        answer_body: str,
        reference_section: str,
    ) -> list[str]:
        refusal = _is_refusal(answer_body)
        user_question = _strip_injected_context(user_question)
        if is_overview_question(user_question):
            return _fallback_suggested_questions(user_question=user_question, refusal=refusal)
        model = getattr(request, "model", None)
        if model is None or not hasattr(model, "ainvoke"):
            return self._generate_suggested_questions_sync(
                request=request,
                user_question=user_question,
                answer_body=answer_body,
                reference_section=reference_section,
            )

        try:
            result = await model.ainvoke(
                [
                    SystemMessage(content=SUGGESTION_SYSTEM_PROMPT),
                    HumanMessage(
                        content=_build_suggestion_prompt(
                            user_question=user_question,
                            answer_body=answer_body,
                            reference_section=reference_section,
                            findings_context=_current_findings_context(request.messages),
                        )
                    ),
                ]
            )
            return _normalize_suggested_questions(
                text=_stringify_content(getattr(result, "content", result)),
                user_question=user_question,
                refusal=refusal,
            )
        except Exception as exc:  # pragma: no cover - defensive path
            logger.warning("Failed to generate suggested questions asynchronously: %s", exc)
            return _fallback_suggested_questions(user_question=user_question, refusal=refusal)

    def _compose_content_sync(self, request: ModelRequest, content: str) -> str:
        state = _request_state(request)
        answer_body = _normalize_answer_citations(
            _strip_generated_sections(content),
            request.messages,
            state,
        )
        if not answer_body:
            return content

        is_ungrounded = _should_mark_ungrounded_answer(answer_body, request.messages, state)

        reference_section = "" if _is_refusal(answer_body) else _build_reference_section(answer_body)
        suggestions = self._generate_suggested_questions_sync(
            request=request,
            user_question=_latest_human_message(request.messages),
            answer_body=answer_body,
            reference_section=reference_section,
        )

        parts = [answer_body]
        if reference_section:
            parts.append(reference_section)
        if suggestions:
            parts.append("建议问题\n" + "\n".join(f"{index}. {question}" for index, question in enumerate(suggestions, start=1)))
        composed = "\n\n".join(parts)
        if is_ungrounded:
            composed += f"\n\n{UNGROUNDED_WARNING_MARKER}"
        return composed

    async def _compose_content_async(self, request: ModelRequest, content: str) -> str:
        state = _request_state(request)
        answer_body = _normalize_answer_citations(
            _strip_generated_sections(content),
            request.messages,
            state,
        )
        if not answer_body:
            return content

        is_ungrounded = _should_mark_ungrounded_answer(answer_body, request.messages, state)

        reference_section = "" if _is_refusal(answer_body) else _build_reference_section(answer_body)
        suggestions = await self._generate_suggested_questions_async(
            request=request,
            user_question=_latest_human_message(request.messages),
            answer_body=answer_body,
            reference_section=reference_section,
        )

        parts = [answer_body]
        if reference_section:
            parts.append(reference_section)
        if suggestions:
            parts.append("建议问题\n" + "\n".join(f"{index}. {question}" for index, question in enumerate(suggestions, start=1)))
        composed = "\n\n".join(parts)
        if is_ungrounded:
            composed += f"\n\n{UNGROUNDED_WARNING_MARKER}"
        return composed

    def _compose_response_sync(self, request: ModelRequest, response: ModelResponse) -> ModelResponse:
        final_ai_index = None
        final_message = None
        for index in range(len(response.result) - 1, -1, -1):
            message = response.result[index]
            if isinstance(message, AIMessage):
                final_ai_index = index
                final_message = message
                break

        if final_ai_index is None or final_message is None or final_message.tool_calls:
            return response

        composed_content = self._compose_content_sync(request, _stringify_content(final_message.content))
        updated_result = list(response.result)
        updated_result[final_ai_index] = final_message.model_copy(update={"content": composed_content})
        return ModelResponse(result=updated_result, structured_response=response.structured_response)

    async def _compose_response_async(self, request: ModelRequest, response: ModelResponse) -> ModelResponse:
        final_ai_index = None
        final_message = None
        for index in range(len(response.result) - 1, -1, -1):
            message = response.result[index]
            if isinstance(message, AIMessage):
                final_ai_index = index
                final_message = message
                break

        if final_ai_index is None or final_message is None or final_message.tool_calls:
            return response

        composed_content = await self._compose_content_async(request, _stringify_content(final_message.content))
        updated_result = list(response.result)
        updated_result[final_ai_index] = final_message.model_copy(update={"content": composed_content})
        return ModelResponse(result=updated_result, structured_response=response.structured_response)

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        response = handler(request)
        enforced_response = self._enforce_with_retry(request, response, handler)
        return self._compose_response_sync(request, enforced_response)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        response = await handler(request)
        enforced_response = await self._aenforce_with_retry(request, response, handler)
        return await self._compose_response_async(request, enforced_response)
