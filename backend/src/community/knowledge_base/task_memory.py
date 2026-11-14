from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime
from time import sleep
from typing import Any
from urllib.parse import parse_qsl, urlsplit
from uuid import NAMESPACE_URL, uuid5

from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from qdrant_client.models import Distance, VectorParams

from src.community.knowledge_base.citations import (
    collect_citation_registry_entries,
    extract_numbered_citation_ids,
    merge_citation_registry,
    rewrite_numbered_citations,
)
from src.community.knowledge_base.retriever import get_embedding_model, get_qdrant_client
from src.config.knowledge_base_config import get_knowledge_base_config

logger = logging.getLogger(__name__)

_EMBED_RETRY_ATTEMPTS = 3
_EMBED_RETRY_DELAY_SECONDS = 2.0

TASK_MEMORY_COLLECTION_SUFFIX = "__task_memory"
TASK_MEMORY_TOP_K = 5
TASK_MEMORY_TITLE_MATCH_BOOST = 0.15
TASK_MEMORY_TITLE_PARTIAL_BOOST = 0.05

# If a historical result's citations come from ≤ this many distinct books, it is
# considered "narrow" and must be supplemented with evidence from other sources.
_NARROW_CITATION_BOOK_THRESHOLD = 2


def _task_memory_enabled() -> bool:
    return os.getenv("TASK_MEMORY_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def _count_distinct_books_in_citation_registry(registry: list[dict] | None) -> int:
    """Count the number of distinct source books referenced in a citation registry.

    Extracts ``citation_source_title`` from each entry's URL query string (the
    authoritative book-title field written by the citation builder).  Falls back
    to the ``label`` field when the URL is absent or unparseable.

    Returns 0 when *registry* is empty or None (caller should treat as unknown).
    """
    if not registry:
        return 0
    titles: set[str] = set()
    for entry in registry:
        title = ""
        url = str(entry.get("url") or "").strip()
        if url:
            try:
                params = dict(parse_qsl(urlsplit(url).query))
                title = params.get("citation_source_title", "").strip()
            except Exception:
                pass
        if not title:
            title = str(entry.get("label") or "").strip()
        if title:
            titles.add(title)
    return len(titles)
def _retryable_embedding_exception(exc: Exception) -> bool:
    message = str(exc).lower()
    if "no embedding data received" in message:
        return True
    if "rate limit" in message or "temporarily unavailable" in message:
        return True
    error_name = exc.__class__.__name__
    if error_name in {"APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError"}:
        return True
    try:
        import httpx

        if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
            return True
    except ImportError:
        pass
    cause = getattr(exc, "__cause__", None)
    if isinstance(cause, Exception) and cause is not exc and _retryable_embedding_exception(cause):
        return True
    return False


LINKED_CITATION_PATTERN = re.compile(r"\[citation:[^\]]+\]\((?:<[^>\n]+>|[^)\n]*)\)", re.IGNORECASE)
NUMBERED_CITATION_PATTERN = re.compile(r"\[citation:\s*\d+\s*\]", re.IGNORECASE)
BARE_CITATION_PATTERN = re.compile(r"\[citation:[^\]]+\](?!\()", re.IGNORECASE)
EMPTY_CITATION_PATTERN = re.compile(r"\[citation:[^\]]+\]\(\s*\)", re.IGNORECASE)
INSUFFICIENT_EVIDENCE_PATTERN = re.compile(r"^\s*(?:[#>*\-\s\d.、:：`]+)?【(?:证据不足|无法确认|无法回答|信息不足)】")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def normalize_task_title(title: str | None) -> str:
    text = str(title or "").strip().lower()
    text = text.replace("：", ":")
    text = re.sub(r"\s+", " ", text)
    return text


def build_task_memory_id(title: str) -> str:
    normalized_title = normalize_task_title(title)
    return str(uuid5(NAMESPACE_URL, f"task-memory:{normalized_title}"))


def get_task_memory_collection_name(base_collection_name: str | None = None) -> str:
    config = get_knowledge_base_config()
    base_name = base_collection_name or config.qdrant.collection_name
    return f"{base_name}{TASK_MEMORY_COLLECTION_SUFFIX}"


def _normalize_string_list(value: list[str] | None) -> list[str]:
    return [str(item).strip() for item in value or [] if str(item).strip()]


def _is_complete_citation(text: str) -> bool:
    return bool(NUMBERED_CITATION_PATTERN.fullmatch(text.strip()))


def _complete_citations(value: list[str] | None) -> list[str]:
    return [item for item in _normalize_string_list(value) if _is_complete_citation(item)]


def _sanitize_injected_text(text: str) -> str:
    """Remove broken citation tokens from injected memory so models don't copy them."""

    sanitized = EMPTY_CITATION_PATTERN.sub("", text)

    sanitized = LINKED_CITATION_PATTERN.sub("", sanitized)
    sanitized = BARE_CITATION_PATTERN.sub(lambda match: match.group(0) if _is_complete_citation(match.group(0)) else "", sanitized)
    sanitized = re.sub(r"[ \t]+\n", "\n", sanitized)
    sanitized = re.sub(r"\n{3,}", "\n\n", sanitized)
    return sanitized.strip()


def is_non_reusable_failure_summary(text: str) -> bool:
    """Return True when a result is an explicit failed/insufficient-evidence answer."""

    cleaned = _sanitize_injected_text(str(text or "")).strip()
    if not cleaned:
        return False
    if INSUFFICIENT_EVIDENCE_PATTERN.search(cleaned):
        return True
    for line in cleaned.splitlines():
        stripped = line.strip()
        if not stripped or re.match(r"^#{1,6}\s+", stripped):
            continue
        return bool(INSUFFICIENT_EVIDENCE_PATTERN.search(stripped))
    return False



def _strip_unsupported_numbered_citations(text: str) -> str:
    stripped = NUMBERED_CITATION_PATTERN.sub("", str(text or ""))
    stripped = re.sub(r"[ \t]+\n", "\n", stripped)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped)
    stripped = re.sub(r"\s{2,}", " ", stripped)
    return stripped.strip()



def _collect_citation_ids_from_task_memory_payload(
    *,
    summary: str,
    findings: list[str],
    citations: list[str],
    open_questions: list[str],
) -> list[str]:
    combined_ids: list[str] = []
    for text in [summary, *findings, *citations, *open_questions]:
        combined_ids.extend(extract_numbered_citation_ids(text))
    seen: set[str] = set()
    ordered_ids: list[str] = []
    for citation_id in combined_ids:
        if citation_id in seen:
            continue
        seen.add(citation_id)
        ordered_ids.append(citation_id)
    return ordered_ids



def build_task_memory_citation_registry(
    *,
    summary: str,
    findings: list[str] | None,
    citations: list[str] | None,
    open_questions: list[str] | None,
    citation_registry: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    return collect_citation_registry_entries(
        citation_registry,
        citation_ids=_collect_citation_ids_from_task_memory_payload(
            summary=summary,
            findings=_normalize_string_list(findings),
            citations=_normalize_string_list(citations),
            open_questions=_normalize_string_list(open_questions),
        ),
    )



def prepare_task_memory_matches_for_injection(
    results: list[dict[str, Any]],
    *,
    target_state: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for item in results:
        metadata = dict(item.get("metadata") or {})
        summary = str(metadata.get("summary") or "").strip()
        findings = _normalize_string_list(metadata.get("findings"))
        citations = _normalize_string_list(metadata.get("citations"))
        open_questions = _normalize_string_list(metadata.get("open_questions"))
        citation_registry = build_task_memory_citation_registry(
            summary=summary,
            findings=findings,
            citations=citations,
            open_questions=open_questions,
            citation_registry=metadata.get("citation_registry") if isinstance(metadata.get("citation_registry"), list) else None,
        )

        if citation_registry and target_state is not None:
            citation_id_mapping = merge_citation_registry(target_state, citation_registry)
            metadata["summary"] = rewrite_numbered_citations(summary, citation_id_mapping)
            metadata["findings"] = [rewrite_numbered_citations(value, citation_id_mapping) for value in findings]
            metadata["citations"] = [rewrite_numbered_citations(value, citation_id_mapping) for value in citations]
            metadata["open_questions"] = [rewrite_numbered_citations(value, citation_id_mapping) for value in open_questions]
            metadata["citation_registry"] = citation_registry
        else:
            metadata["summary"] = _strip_unsupported_numbered_citations(summary)
            metadata["findings"] = [_strip_unsupported_numbered_citations(value) for value in findings]
            metadata["citations"] = []
            metadata["open_questions"] = [_strip_unsupported_numbered_citations(value) for value in open_questions]
            metadata["citation_registry"] = []

        prepared.append({**item, "metadata": metadata})
    return prepared


def search_and_prepare_task_memory(
    *,
    query: str,
    title: str | None,
    target_state: dict[str, Any] | None,
    top_k: int = TASK_MEMORY_TOP_K,
    task_level: str | None = None,
) -> list[dict[str, Any]]:
    """Search task memory and merge any saved citation registries into ``target_state``.

    This bundles the two atomic steps every caller needs: vector search over historical
    main-task/subtask records, and merging the saved citation registry of each match
    into the live state so that ``[citation:N]`` markers in the rendered text point at
    valid IDs in ``state["knowledge_citation_registry"]``. Skipping the second step
    leaves the model with orphan citation numbers that the frontend cannot resolve.
    """

    matches = search_task_memory(query, title=title, top_k=top_k, task_level=task_level)
    return prepare_task_memory_matches_for_injection(matches, target_state=target_state)


def _compact_query_for_storage(query: str, *, task_level: str) -> str:
    cleaned = str(query or "").strip()
    if not cleaned:
        return ""
    todo_match = re.search(r"(?im)^\s*Todo:\s*(.+?)\s*$", cleaned)
    if task_level == "subtask" and todo_match:
        return todo_match.group(1).strip()
    if task_level == "subtask" and ("你只负责执行下面这一项 todo" in cleaned or "要求：" in cleaned):
        first_line = next((line.strip() for line in cleaned.splitlines() if line.strip()), "")
        return first_line[:500]
    return cleaned


def _render_query_for_injection(query: str, *, task_level: str) -> str:
    cleaned = _sanitize_injected_text(str(query or "").strip())
    if not cleaned:
        return ""

    todo_match = re.search(r"(?im)^\s*Todo:\s*(.+?)\s*$", cleaned)
    if task_level == "subtask" and todo_match:
        return f"任务目标: {todo_match.group(1).strip()}"

    # Avoid injecting long delegated-task prompts; they are instructions from an
    # older run, not evidence for the current task.
    if task_level == "subtask" and ("你只负责执行下面这一项 todo" in cleaned or "要求：" in cleaned):
        first_line = next((line.strip() for line in cleaned.splitlines() if line.strip()), "")
        return f"任务目标: {first_line[:240]}{'…' if len(first_line) > 240 else ''}"

    if len(cleaned) > 500:
        return cleaned[:499].rstrip() + "…"
    return cleaned


def _build_task_memory_text(
    *,
    title: str,
    query: str,
    summary: str,
    findings: list[str],
    citations: list[str],
    open_questions: list[str],
) -> str:
    sections = [f"标题: {title.strip()}"]
    if query.strip():
        sections.append(f"查询: {query.strip()}")
    if summary.strip():
        sections.append(f"摘要:\n{summary.strip()}")
    if findings:
        sections.append("关键发现:\n" + "\n".join(f"- {item}" for item in findings))
    if citations:
        sections.append("关键引文:\n" + "\n".join(f"- {item}" for item in citations))
    if open_questions:
        sections.append("未解决缺口:\n" + "\n".join(f"- {item}" for item in open_questions))
    return "\n\n".join(section for section in sections if section.strip()).strip()


def _build_task_memory_embedding_text(
    *,
    title: str,
    query: str,
    summary: str,
    findings: list[str],
    citations: list[str],
    open_questions: list[str],
    task_level: str,
) -> str:
    """Build the text embedded into the vector DB.

    For subtasks, keep delegated prompts out of the vector text. The reusable
    memory is the subtask's final result, findings, citations, and gaps; the
    parent prompt is orchestration noise and can dominate retrieval.
    """

    vector_query = "" if task_level == "subtask" else query
    return _build_task_memory_text(
        title=title,
        query=vector_query,
        summary=summary,
        findings=findings,
        citations=citations,
        open_questions=open_questions,
    )


def _ensure_task_memory_collection() -> tuple[Any, Any, str]:
    config = get_knowledge_base_config()
    if not config.enabled or config.embedding is None:
        raise ValueError("Task memory requires the knowledge base and embedding model to be enabled")

    client = get_qdrant_client()
    embeddings = get_embedding_model()
    collection_name = get_task_memory_collection_name()

    try:
        client.get_collection(collection_name=collection_name)
    except Exception:
        sample_embedding = embeddings.embed_query("task-memory-collection-probe")
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=len(sample_embedding),
                distance=Distance.COSINE,
            ),
        )

    return client, embeddings, collection_name


def upsert_task_memory_record(
    *,
    title: str,
    query: str,
    summary: str,
    findings: list[str] | None = None,
    citations: list[str] | None = None,
    open_questions: list[str] | None = None,
    citation_registry: list[dict[str, Any]] | None = None,
    task_level: str,
    thread_id: str | None,
    user_id: str | None,
    task_id: str | None,
    status: str = "completed",
    raw_result: str | None = None,
) -> str | None:
    if not _task_memory_enabled():
        return None
    normalized_title = normalize_task_title(title)
    normalized_summary = str(summary or "").strip()
    if not normalized_title or not normalized_summary:
        return None
    if is_non_reusable_failure_summary(normalized_summary) or is_non_reusable_failure_summary(str(raw_result or "")):
        return None

    normalized_query = _compact_query_for_storage(str(query or ""), task_level=task_level)
    normalized_findings = _normalize_string_list(findings)
    normalized_citations = _normalize_string_list(citations)
    normalized_open_questions = _normalize_string_list(open_questions)
    normalized_citation_registry = build_task_memory_citation_registry(
        summary=normalized_summary,
        findings=normalized_findings,
        citations=normalized_citations,
        open_questions=normalized_open_questions,
        citation_registry=citation_registry,
    )

    try:
        client, embeddings, collection_name = _ensure_task_memory_collection()
    except Exception:
        return None
    vector_store = QdrantVectorStore(
        client=client,
        collection_name=collection_name,
        embedding=embeddings,
    )

    content = _build_task_memory_embedding_text(
        title=title,
        query=normalized_query,
        summary=normalized_summary,
        findings=normalized_findings,
        citations=normalized_citations,
        open_questions=normalized_open_questions,
        task_level=task_level,
    )
    record_id = build_task_memory_id(title)
    document = Document(
        id=record_id,
        page_content=content,
        metadata={
            "record_id": record_id,
            "title": title.strip(),
            "normalized_title": normalized_title,
            "query": normalized_query,
            "summary": normalized_summary,
            "findings": normalized_findings,
            "citations": normalized_citations,
            "open_questions": normalized_open_questions,
            "citation_registry": normalized_citation_registry,
            "task_level": task_level,
            "thread_id": thread_id,
            "user_id": user_id,
            "task_id": task_id,
            "status": status,
            "raw_result": str(raw_result or normalized_summary).strip(),
            "updated_at": _utc_now(),
        },
    )
    vector_store.add_documents([document], ids=[record_id])
    return record_id


def search_task_memory(
    query: str,
    *,
    title: str | None = None,
    top_k: int = TASK_MEMORY_TOP_K,
    task_level: str | None = None,
) -> list[dict[str, Any]]:
    if not _task_memory_enabled():
        return []
    normalized_query = str(query or "").strip()
    normalized_title = normalize_task_title(title)
    if not normalized_query and not normalized_title:
        return []

    try:
        client, embeddings, collection_name = _ensure_task_memory_collection()
    except Exception:
        return []
    vector_store = QdrantVectorStore(
        client=client,
        collection_name=collection_name,
        embedding=embeddings,
    )

    search_text = "\n".join(
        part
        for part in [
            f"标题: {title.strip()}" if title and title.strip() else "",
            f"查询: {normalized_query}" if normalized_query else "",
        ]
        if part
    )
    results: list = []
    for _attempt in range(1, _EMBED_RETRY_ATTEMPTS + 1):
        try:
            results = vector_store.similarity_search_with_score(
                search_text,
                k=max(top_k, 3),
                score_threshold=0.0,
            )
            break
        except Exception as exc:
            if not _retryable_embedding_exception(exc) or _attempt >= _EMBED_RETRY_ATTEMPTS:
                raise
            logger.warning(
                "Task memory search transient failure on attempt %s/%s (%s); retrying in %.1fs",
                _attempt,
                _EMBED_RETRY_ATTEMPTS,
                exc,
                _EMBED_RETRY_DELAY_SECONDS,
            )
            sleep(_EMBED_RETRY_DELAY_SECONDS)

    min_score = float(get_knowledge_base_config().retrieval.score_threshold or 0.0)
    ranked: list[dict[str, Any]] = []
    seen_record_ids: set[str] = set()

    for doc, score in results:
        metadata = dict(doc.metadata or {})
        record_id = str(metadata.get("record_id") or doc.id or "").strip()
        if not record_id or record_id in seen_record_ids:
            continue
        if task_level and str(metadata.get("task_level") or "").strip() != task_level:
            continue

        candidate_title = str(metadata.get("title") or "").strip()
        candidate_normalized_title = normalize_task_title(candidate_title)
        weighted_score = float(score)
        if normalized_title and candidate_normalized_title == normalized_title:
            weighted_score += TASK_MEMORY_TITLE_MATCH_BOOST
        elif normalized_title and normalized_title in candidate_normalized_title:
            weighted_score += TASK_MEMORY_TITLE_PARTIAL_BOOST

        if weighted_score < min_score and candidate_normalized_title != normalized_title:
            continue

        seen_record_ids.add(record_id)
        ranked.append(
            {
                "content": doc.page_content,
                "metadata": metadata,
                "score": float(score),
                "weighted_score": weighted_score,
            }
        )

    ranked.sort(key=lambda item: item.get("weighted_score", item.get("score", 0.0)), reverse=True)
    return ranked[:top_k]


def render_task_memory_matches(
    results: list[dict[str, Any]],
    *,
    heading: str = "## 检索结果",
) -> str:
    if not results:
        return (
            f"{heading}\n\n"
            "本轮没有命中可直接复用的历史主任务/子任务结果。\n\n"
            "---\n"
            "把这次未命中视为当前主题没有可复用历史结果。不要继续改写 query 反复调用 `knowledge_search`；"
            "下一步直接从零走原始资料路线：主任务按证据缺口或探索方向派发子任务；子任务再用 `book_search` 选源，并用 `knowledge_locate` 读目录、章节页、命中页或连续页正文。"
        )

    lines = [heading, ""]
    for index, item in enumerate(results, 1):
        metadata = item.get("metadata", {}) or {}
        title = str(metadata.get("title") or "未命名任务").strip()
        task_level = str(metadata.get("task_level") or "unknown").strip()
        query = _render_query_for_injection(str(metadata.get("query") or "").strip(), task_level=task_level)
        summary = _sanitize_injected_text(str(metadata.get("summary") or "").strip())
        findings = _normalize_string_list(metadata.get("findings"))
        citations = _complete_citations(metadata.get("citations"))
        open_questions = [_sanitize_injected_text(item) for item in _normalize_string_list(metadata.get("open_questions"))]
        thread_id = str(metadata.get("thread_id") or "").strip()
        task_id = str(metadata.get("task_id") or "").strip()

        lines.append(
            f"### 历史结果 {index}: {title} - 相关度: {float(item.get('weighted_score') or item.get('score') or 0.0):.2f}"
        )
        lines.append(f"任务层级: {task_level}")
        if query:
            lines.append(query)
        if thread_id:
            lines.append(f"thread_id: {thread_id}")
        if task_id:
            lines.append(f"task_id: {task_id}")
        if summary:
            lines.append("任务结果:")
            lines.append(summary)
        if findings:
            lines.append("关键发现:")
            lines.extend(f"- {_sanitize_injected_text(item)}" for item in findings)
        if citations:
            lines.append("关键引文:")
            lines.extend(f"- {item}" for item in citations)
        if open_questions:
            lines.append("未解决缺口:")
            lines.extend(f"- {item}" for item in open_questions)

        # Citation diversity check — shown immediately after the citations block
        # so the model sees the warning in context before reaching the global rules.
        citation_registry_data = metadata.get("citation_registry") or []
        distinct_book_count = _count_distinct_books_in_citation_registry(citation_registry_data)
        if 0 < distinct_book_count <= _NARROW_CITATION_BOOK_THRESHOLD:
            lines.append(
                f"⚠️ 引用书目较少（本条历史结果仅涉及 {distinct_book_count} 本书）："
                "即使结论与当前问题相关，也必须视为「需要补充」——"
                "需另从其他细化书籍或专题书中寻找额外佐证和细节，不可将此作为充分证据直接使用。"
            )
        elif distinct_book_count == 0 and citations:
            # Citations exist but no registry to count from — flag as unverifiable breadth.
            lines.append(
                "⚠️ 无法确认本条引用的书目数量（citation 注册信息不完整）："
                "请把它视为「需要补充」，主动去其他书目中寻找佐证，不要默认已覆盖充分。"
            )

        lines.append("")

    lines.append("---")
    lines.append("这些历史主任务/子任务结果是当前任务的强制证据包，不等于当前问题已经自动完成，但也不能被忽略。")
    lines.append("后续行动必须先完成三类判断：`可直接复用`、`需要补充`、`应该纠正/弃用`。")
    lines.append(
        "判断标准——同时满足以下两条才可标为「可直接复用」：\n"
        "  ① 内容与当前问题高度重合，已包含可用结论和编号 citation；\n"
        "  ② 引用书目涉及 3 本以上（结果块内若显示⚠️书目警告，则必须标「需要补充」）。\n"
        "仅满足①但书目 ≤ 2 本时，必须标「需要补充」：\n"
        "  - 结论部分可先复用，但需另派子任务或检索，从细化书籍或专题书中补充更多佐证和细节；\n"
        "  - 不要把「仅 1-2 本书的引文」当作覆盖充分的证据。"
    )
    lines.append("如果复用历史结果中的事实、数字、分期、判断或缺口，最终回答必须把对应 citation 一并带上。")
    lines.append("严禁把历史结果里的 citation 改写成空链接、普通书名或空括号；无法确认可用 citation 时，把它列为证据缺口，不要当作有效引文。")
    return "\n".join(lines).strip()


def build_task_memory_injection_message(
    *,
    title: str,
    query: str,
    results: list[dict[str, Any]],
) -> str:
    rendered = render_task_memory_matches(results, heading="## 历史任务结果匹配")
    return (
        "<task_memory_matches>\n"
        "系统插入提示（不是用户的新问题）：以下是基于当前任务标题与 query 匹配到的历史主任务/子任务结果。\n"
        "这是当前任务的强制历史证据包。你必须先处理它，再决定是否需要新检索、下发子任务或直接综合回答。\n"
        f"当前任务标题：{title.strip() or '未命名任务'}\n"
        f"当前 query：{query.strip()}\n\n"
        f"{rendered}\n\n"
        "执行要求：\n"
        "1. 先逐条判断历史结果的可用性，判断标准如下：\n"
        "   - `可直接复用`：内容与当前问题高度重合 **且** 引用书目涉及 3 本以上（结果块无⚠️书目警告）。\n"
        "   - `需要补充`：内容相关但引用书目仅 1-2 本（有⚠️书目警告），或存在明显内容缺口。\n"
        "     → 可先复用已有结论，但必须额外从细化书籍或专题书中补充更多佐证和细节，不可视为充分证据。\n"
        "   - `应该纠正/弃用`：内容与当前问题不符或结论明显有误。\n"
        "   不要跳过这一步。\n"
        "2. 若历史结果已覆盖当前问题的大部分内容，不要重复派发同题子任务；只补查未解决缺口或疑似错误点。\n"
        "3. 综合回答时，必须显式吸收所有与当前问题高度相关的历史结论、关键发现、关键引文和未解决缺口。\n"
        "4. 复用历史结果时，只能复制可用 citation；空括号或格式损坏的 citation 不能输出为有效引文。\n"
        "5. 输出前自检：凡是引用历史结果中的事实、数字、页码、分期或因果判断，都必须在该句或该要点后带上对应 citation。\n"
        "</task_memory_matches>"
    )
