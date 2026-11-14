from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Generic, TypeVar

from langchain_core.messages import ToolMessage
from langgraph.types import Command
from pydantic import BaseModel, Field, field_validator

try:
    from langchain.tools import InjectedToolCallId, ToolRuntime, tool
except ImportError:  # pragma: no cover - compatibility with older LangChain layouts
    from langchain.tools import InjectedToolCallId, tool

    _ToolRuntimeContextT = TypeVar("_ToolRuntimeContextT")
    _ToolRuntimeStateT = TypeVar("_ToolRuntimeStateT")

    class ToolRuntime(Generic[_ToolRuntimeContextT, _ToolRuntimeStateT]):  # type: ignore[no-redef]
        pass


try:
    from langgraph.typing import ContextT
except ImportError:  # pragma: no cover - compatibility with older LangGraph layouts
    ContextT = TypeVar("ContextT")

if TYPE_CHECKING:
    from src.agents.thread_state import ThreadState
else:  # pragma: no cover - runtime fallback for import-light utility modules
    ThreadState = Any  # type: ignore[assignment]

from src.community.knowledge_base.book_metadata import normalize_folder_path
from src.community.knowledge_base.catalog import (
    BOOK_LAYER_ORDER,
    CORE_TYPE,
    REFERENCE_TYPE,
    SPECIALIZED_TYPE,
    UNFILED_FOLDER_NAME,
    BookCatalogEntry,
    filter_book_catalog_entries,
    list_book_catalog,
    render_book_catalog_directory_tree,
    search_book_catalog,
)
from src.community.knowledge_base.citations import (
    citation_registry_update_fragment,
    register_citation_marker,
    resolve_result_citation_context,
)
from src.community.knowledge_base.common import tokenize_search_text
from src.community.knowledge_base.locator import LocatedDocument, extract_document_context, locate_document, locate_document_from_entry
from src.community.knowledge_base.query_expansion import retry_queries
from src.community.knowledge_base.reading_state import (
    COVERED_DOC_IDS_KEY,
    READING_SET_DOC_IDS_KEY,
    READING_SET_HUMAN_INDEX_KEY,
    READING_SET_QUERY_KEY,
    READING_SET_TITLES_KEY,
    latest_human_index,
)
from src.community.knowledge_base.source_evidence import page_kind, search_body_pages

BOOK_SEARCH_TOP_K = 20
KNOWLEDGE_SEARCH_TOP_K = 6
KNOWLEDGE_RESULT_MAX_CHARS = 1400
KNOWLEDGE_RESULT_MAX_LINES = 36
BOOK_READING_SET_LIMIT = 6
ALLOWED_SEARCH_SCOPES = {"user", "thread", "global"}
SEARCH_SCOPE_ORDER = ("user", "thread", "global")
_TASK_PROMPT_DOC_ID_PATTERN = re.compile(r"doc_id\s*=\s*['\"]([^'\"]+)['\"]")
logger = logging.getLogger(__name__)


class KnowledgeSearchArgs(BaseModel):
    query: str = Field(description="Search query for prior main-task/subtask results. Use at most once per topic.")
    doc_ids: list[str] | None = Field(
        default=None,
        description=("Deprecated compatibility field. Do not pass book doc_ids here; dispatch raw document reading to subtasks."),
    )
    scopes: str | None = Field(
        default=None,
        description="Deprecated compatibility field. Do not pass scopes here; this tool is not raw document search.",
    )
    knowledge_folders: list[str] | None = Field(
        default=None,
        description="Deprecated compatibility field. Use `book_search` for folder/book routing instead.",
    )

    @field_validator("doc_ids", mode="before")
    @classmethod
    def _coerce_doc_ids(cls, value: object) -> object:
        if value is None or isinstance(value, list):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            try:
                decoded = json.loads(stripped)
            except Exception:
                return value
            if isinstance(decoded, list):
                return decoded
        return value


def _tool_runtime_state(runtime: ToolRuntime[ContextT, ThreadState]) -> dict[str, Any] | None:
    state = getattr(runtime, "state", None)
    return state if isinstance(state, dict) else None


def _message_content_as_text(message: Any) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


def _list_book_catalog_for_tools(
    *,
    thread_id: str | None,
    user_id: str | None,
    include_search_content: bool,
    caller: str,
) -> list[BookCatalogEntry]:
    try:
        return list_book_catalog(
            thread_id=thread_id,
            user_id=user_id,
            include_search_content=include_search_content,
            caller=caller,
        )
    except TypeError:
        return list_book_catalog(thread_id=thread_id, user_id=user_id)


def _select_reading_set_candidates(
    candidates: list[BookCatalogEntry],
    *,
    limit: int = BOOK_READING_SET_LIMIT,
) -> list[BookCatalogEntry]:
    if len(candidates) <= limit:
        return list(candidates)

    selected: list[BookCatalogEntry] = []
    selected_ids: set[str] = set()

    for candidate in candidates[:limit]:
        if candidate.doc_id in selected_ids:
            continue
        selected.append(candidate)
        selected_ids.add(candidate.doc_id)

    for layer in BOOK_LAYER_ORDER:
        layer_candidate = next(
            (candidate for candidate in candidates if _candidate_layer_key(candidate) == layer),
            None,
        )
        if layer_candidate is None or layer_candidate.doc_id in selected_ids:
            continue
        selected.append(layer_candidate)
        selected_ids.add(layer_candidate.doc_id)

    return selected[:limit]


def _update_runtime_reading_set(
    runtime: ToolRuntime[ContextT, ThreadState],
    *,
    query: str,
    candidates: list[BookCatalogEntry],
) -> None:
    state = _tool_runtime_state(runtime)
    if state is None:
        return

    selected = _select_reading_set_candidates(candidates)
    state[READING_SET_DOC_IDS_KEY] = [candidate.doc_id for candidate in selected]
    state[READING_SET_TITLES_KEY] = {candidate.doc_id: candidate.title for candidate in selected if candidate.doc_id and candidate.title}
    state[COVERED_DOC_IDS_KEY] = []
    state[READING_SET_QUERY_KEY] = query.strip()
    state[READING_SET_HUMAN_INDEX_KEY] = latest_human_index(state.get("messages"))


def _mark_runtime_covered_doc_ids(
    runtime: ToolRuntime[ContextT, ThreadState],
    doc_ids: list[str] | None,
) -> None:
    state = _tool_runtime_state(runtime)
    if state is None or not doc_ids:
        return

    reading_set = state.get(READING_SET_DOC_IDS_KEY)
    if not isinstance(reading_set, list) or not reading_set:
        return

    reading_set_ids = {str(item).strip() for item in reading_set if str(item).strip()}
    normalized_doc_ids = [doc_id.strip() for doc_id in doc_ids if doc_id and doc_id.strip() in reading_set_ids]
    if not normalized_doc_ids:
        return

    existing = state.get(COVERED_DOC_IDS_KEY)
    existing_ids = [str(item).strip() for item in existing] if isinstance(existing, list) else []
    seen = set(existing_ids)
    for doc_id in normalized_doc_ids:
        if doc_id in seen:
            continue
        existing_ids.append(doc_id)
        seen.add(doc_id)
    state[COVERED_DOC_IDS_KEY] = existing_ids


def _split_loose_delimited_values(
    value: str | list[str] | tuple[str, ...] | set[str] | None,
) -> list[str] | None:
    if value is None:
        return None

    raw_items = [value] if isinstance(value, str) else list(value)
    if isinstance(value, str):
        stripped_value = value.strip()
        if stripped_value.startswith("[") and stripped_value.endswith("]"):
            try:
                decoded = json.loads(stripped_value)
            except Exception:
                decoded = None
            if isinstance(decoded, list):
                raw_items = decoded

    parsed: list[str] = []
    seen: set[str] = set()

    for raw_item in raw_items:
        for candidate in re.split(r"[,，、;\n；]+", str(raw_item)):
            normalized = candidate.strip().strip("`\"'")
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            parsed.append(normalized)

    return parsed or None


def _parse_doc_ids(doc_ids: object) -> list[str] | None:
    if not doc_ids:
        return None
    if isinstance(doc_ids, str):
        stripped = doc_ids.strip()
        try:
            decoded = json.loads(stripped)
        except Exception as exc:
            raise ValueError('Invalid `doc_ids` format. Pass a JSON array like `["doc_id_1", "doc_id_2"]`.') from exc
        if not isinstance(decoded, list):
            raise ValueError('Invalid `doc_ids` format. Pass a JSON array like `["doc_id_1", "doc_id_2"]`.')
        parsed = _split_loose_delimited_values(decoded)
        if not parsed:
            raise ValueError("Invalid `doc_ids` format: no non-empty doc_id found.")
        return parsed
    return _split_loose_delimited_values(doc_ids)


def _parse_folder_paths(folder_paths: str | list[str] | tuple[str, ...] | None) -> list[str] | None:
    if folder_paths is None:
        return None
    parsed: list[str] = []
    seen: set[str] = set()
    for candidate in _split_loose_delimited_values(folder_paths) or []:
        normalized = normalize_folder_path(candidate)
        if normalized == "未归档":
            normalized = UNFILED_FOLDER_NAME
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        parsed.append(normalized)
    return parsed or None


def _parse_knowledge_folders(
    knowledge_folders: str | list[str] | tuple[str, ...] | None,
) -> list[str] | None:
    return _parse_folder_paths(knowledge_folders)


def _normalize_knowledge_folder_candidate(value: str) -> str:
    normalized = normalize_folder_path(value)
    if normalized:
        return normalized
    return re.sub(r"\s+", " ", value.strip()).strip("/")


def _coerce_runtime_string_list(value: object) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        parsed = [item.strip() for item in value.split(",") if item.strip()]
        return parsed or None
    if isinstance(value, (list, tuple, set)):
        parsed = [str(item).strip() for item in value if str(item).strip()]
        return parsed or None
    return None


def _parse_scopes(scopes: str | None) -> list[str] | None:
    if not scopes:
        return None
    parsed = []
    seen: set[str] = set()
    for item in scopes.split(","):
        normalized = item.strip().lower()
        if not normalized or normalized not in ALLOWED_SEARCH_SCOPES or normalized in seen:
            continue
        seen.add(normalized)
        parsed.append(normalized)
    return parsed or None


def _runtime_selected_doc_ids(runtime: ToolRuntime[ContextT, ThreadState]) -> list[str] | None:
    return _coerce_runtime_string_list(runtime.context.get("selected_doc_ids"))


def _runtime_selected_scopes(runtime: ToolRuntime[ContextT, ThreadState]) -> list[str] | None:
    selected_scopes = _coerce_runtime_string_list(runtime.context.get("selected_sources_scope"))
    return _parse_scopes(",".join(selected_scopes)) if selected_scopes else None


def _entry_folder_path(entry: BookCatalogEntry) -> str | None:
    normalized = normalize_folder_path(entry.folder_path)
    if normalized:
        return normalized
    relative_parent = normalize_folder_path(str(Path(entry.filename).parent))
    if relative_parent:
        return relative_parent
    return UNFILED_FOLDER_NAME


def _entry_matches_any_knowledge_folder(entry: BookCatalogEntry, knowledge_folders: list[str]) -> bool:
    entry_folder = _entry_folder_path(entry)
    if not entry_folder:
        return False
    return any(entry_folder == folder or entry_folder.startswith(f"{folder}/") for folder in knowledge_folders)


def _visible_catalog_entries(
    *,
    thread_id: str | None,
    user_id: str | None,
    selected_doc_ids: list[str] | None,
    selected_scopes: list[str] | None,
) -> list[BookCatalogEntry]:
    return filter_book_catalog_entries(
        _list_book_catalog_for_tools(
            thread_id=thread_id,
            user_id=user_id,
            include_search_content=False,
            caller="tools._visible_catalog_entries",
        ),
        doc_ids=selected_doc_ids,
        scopes=selected_scopes,
    )


def _build_knowledge_folder_guidance(
    *,
    visible_entries: list[BookCatalogEntry],
    reason: str,
) -> str:
    directory_tree = render_book_catalog_directory_tree(visible_entries) or "（当前范围没有可见知识库目录）"
    return (
        f"{reason}\n"
        "`knowledge_folders` 指的是知识库目录树中的逻辑目录，不是 sandbox / 容器 / 本地文件系统路径。\n"
        "也不要填写 `用户书籍`、`当前线程书籍`、`核心通用书`、`专题支撑书`、`补充材料`、`参考工具书` 这类层级标签；它们只是系统内部的分层概念，不是可检索目录。\n"
        "也不要填写 `user`、`thread`、`global` 这类 scope 标签；它们是资料范围过滤标签，不是知识库目录。\n"
        "不要把它理解成 `/mnt/...`、`./...`、`knowledge/docs/...` 这类本地目录，也不要试图通过 `ls`、`read_file`、`bash` 等其他方式自己推断它。\n"
        "请直接从下面的知识库目录树中复制目录名来填写 `knowledge_folders`。\n\n"
        "## 可见知识库目录树\n\n"
        f"{directory_tree}\n\n"
        '示例: `knowledge_folders=["人物传记/晚清", "档案资料/盛宣怀"]`'
    )


def _looks_like_local_filesystem_path(value: str) -> bool:
    normalized = value.strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    return normalized.startswith(("/", "./", "../", "~")) or lowered.startswith(("mnt/", "knowledge/", "backend/", "frontend/")) or "\\" in normalized or lowered.endswith((".pdf", ".md", ".txt", ".json", ".jsonl"))


_VIRTUAL_KNOWLEDGE_FOLDER_LABELS = {
    "用户书籍",
    "当前线程书籍",
    "系统知识库",
    "核心通用书",
    "专题支撑书",
    "补充材料",
    "参考工具书",
    "补充材料 / 参考工具书",
    "其他资料",
    "user",
    "thread",
    "global",
}


def _looks_like_virtual_knowledge_folder_label(value: str) -> bool:
    normalized = _normalize_knowledge_folder_candidate(value)
    return normalized in _VIRTUAL_KNOWLEDGE_FOLDER_LABELS


def _intersect_doc_ids(
    requested_doc_ids: list[str] | None,
    selected_doc_ids: list[str] | None,
) -> list[str] | None:
    if not requested_doc_ids:
        return selected_doc_ids
    if not selected_doc_ids:
        return requested_doc_ids
    allowed = set(selected_doc_ids)
    intersection = [doc_id for doc_id in requested_doc_ids if doc_id in allowed]
    return intersection or []


def _format_doc_ids_json(doc_ids: list[str]) -> str:
    return json.dumps(doc_ids, ensure_ascii=False)


def _is_substantive_search_excerpt(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 18:
        return False
    return len(tokenize_search_text(stripped)) >= 3


def _normalize_doc_id_match_key(value: str) -> str:
    return re.sub(r"\s+", "", value).strip()


def _resolve_requested_doc_ids(
    requested_doc_ids: list[str] | None,
    *,
    visible_entries: list[BookCatalogEntry],
) -> tuple[list[str] | None, list[str], list[str]]:
    if not requested_doc_ids:
        return None, [], []

    exact_doc_ids = {entry.doc_id: entry.doc_id for entry in visible_entries}
    normalized_doc_ids: dict[str, list[str]] = {}
    for entry in visible_entries:
        normalized_key = _normalize_doc_id_match_key(entry.doc_id)
        normalized_doc_ids.setdefault(normalized_key, []).append(entry.doc_id)

    resolved: list[str] = []
    missing: list[str] = []
    ambiguous: list[str] = []

    for requested_doc_id in requested_doc_ids:
        if requested_doc_id in exact_doc_ids:
            resolved.append(exact_doc_ids[requested_doc_id])
            continue

        normalized_key = _normalize_doc_id_match_key(requested_doc_id)
        matches = normalized_doc_ids.get(normalized_key, [])
        if len(matches) == 1:
            resolved.append(matches[0])
            continue
        if len(matches) > 1:
            ambiguous.append(requested_doc_id)
            continue
        missing.append(requested_doc_id)

    return resolved, missing, ambiguous


def _build_retry_query_suggestions(query: str) -> list[str]:
    return retry_queries(query)


def _build_no_result_guidance(query: str, doc_ids: list[str] | None) -> str:
    lines = ["## 检索结果", "", "本轮没有命中到可直接使用的内部知识片段。", "", "---"]
    if doc_ids:
        lines.append("不要在同一批 `doc_ids` 上继续反复调用 `knowledge_search`。")
        lines.append("若当前是主任务，直接派发子任务从零检索；子任务再用 `knowledge_locate(doc_id=...)` 做原文定位，优先看目录、序言、章节开头，再顺着相关板块继续找正文。")
    else:
        lines.append("先回到 `book_search` 找更匹配的书，再继续检索。")

    suggestions = _build_retry_query_suggestions(query)
    if suggestions:
        lines.append("建议下一轮 query：")
        for suggestion in suggestions[:2]:
            lines.append(f"- `{suggestion}`")
    return "\n".join(lines)


def _merge_scopes(*scope_groups: list[str] | None) -> list[str] | None:
    seen: set[str] = set()
    merged: list[str] = []
    for scope in SEARCH_SCOPE_ORDER:
        for group in scope_groups:
            if not group or scope not in group or scope in seen:
                continue
            seen.add(scope)
            merged.append(scope)
    return merged or None


def _infer_scopes_from_doc_ids(
    doc_ids: list[str] | None,
    *,
    thread_id: str | None,
    user_id: str | None,
) -> list[str] | None:
    if not doc_ids:
        return None

    candidate_map = {
        candidate.doc_id: candidate.scope
        for candidate in _list_book_catalog_for_tools(
            thread_id=thread_id,
            user_id=user_id,
            include_search_content=False,
            caller="tools._infer_scopes_from_doc_ids",
        )
        if candidate.scope in ALLOWED_SEARCH_SCOPES
    }
    inferred: list[str] = []
    for doc_id in doc_ids:
        scope = candidate_map.get(doc_id)
        if scope and scope not in inferred:
            inferred.append(scope)
    return inferred or None


def _build_location_text(
    *,
    page: int | None = None,
    page_no: int | None,
    pdf_page_no: int | None,
    paragraph_no: int | None,
) -> str | None:
    if page_no:
        location = f"原书第 {page_no} 页"
        if paragraph_no:
            location += f" 第 {paragraph_no} 段"
        if pdf_page_no and pdf_page_no != page_no:
            location += f"（PDF 第 {pdf_page_no} 页）"
        return location
    if pdf_page_no:
        location = f"PDF 第 {pdf_page_no} 页"
        if paragraph_no:
            location += f" 第 {paragraph_no} 段"
        return location
    if page is not None:
        return f"PDF 第 {page + 1} 页"
    return None


def _build_citation_label(
    title: str,
    page_no: int | None,
    pdf_page_no: int | None,
    paragraph_no: int | None,
    page: int | None = None,
) -> str:
    parts = [title]
    location = _build_location_text(
        page=page,
        page_no=page_no,
        pdf_page_no=pdf_page_no,
        paragraph_no=paragraph_no,
    )
    if location:
        location = location.replace(" ", "")
        parts.append(location)
    return " ".join(parts)


def _build_citation(
    citation_label: str,
    citation_link: str | None,
    *,
    state: dict[str, Any] | None = None,
) -> str | None:
    return register_citation_marker(
        state,
        citation_label=citation_label,
        citation_link=citation_link,
    )


def _build_locate_excerpt_citation(
    *,
    document: LocatedDocument,
    excerpt: dict[str, Any],
    thread_id: str | None,
    user_id: str | None,
    state: dict[str, Any] | None = None,
) -> str | None:
    citation_context = resolve_result_citation_context(
        {
            "filename": document.filename,
            "metadata": {
                "title": document.title,
                "filename": document.filename,
                "scope": document.scope,
                # Imported book numbering can be incorrect (including covers
                # numbered as book page 1). Anchor the physical PDF page.
                "page_no": None,
                "pdf_page_no": excerpt.get("pdf_page_no"),
                "paragraph_no": excerpt.get("paragraph_no"),
            },
        },
        thread_id=thread_id,
        user_id=user_id,
    )
    citation_label = _build_citation_label(
        str(citation_context["citation_title"] or document.title),
        citation_context["citation_page_no"],
        citation_context["citation_pdf_page_no"],
        citation_context["citation_paragraph_no"],
        page=citation_context["citation_page"],
    )
    return register_citation_marker(
        state,
        citation_label=citation_label,
        citation_link=citation_context.get("citation_url") or citation_context.get("source_url"),
        stable_ids=True,
    )


def _looks_like_navigation_page(page_text: str) -> bool:
    return page_kind(page_text) == "toc"


def _build_navigation_locate_preview(
    *,
    payload: dict[str, Any],
    max_pages: int = 3,
) -> list[dict[str, Any]]:
    pages = payload.get("pages") or []
    if not pages:
        return []

    selected_pages: list[dict[str, Any]] = []
    seen_pdf_pages: set[int] = set()

    def add_page(page: dict[str, Any]) -> None:
        pdf_page_no = int(page.get("pdf_page_no") or page.get("page_no") or 0)
        if pdf_page_no in seen_pdf_pages:
            return
        seen_pdf_pages.add(pdf_page_no)
        selected_pages.append(page)

    for page in pages[: min(len(pages), 20)]:
        page_text = str(page.get("text") or "")
        if _looks_like_navigation_page(page_text):
            add_page(page)
        if len(selected_pages) >= max_pages:
            break

    if len(selected_pages) < max_pages:
        for page in pages[: min(len(pages), 6)]:
            add_page(page)
            if len(selected_pages) >= max_pages:
                break

    previews: list[dict[str, Any]] = []
    for page in selected_pages[:max_pages]:
        page_text = str(page.get("text") or "").strip()
        if not page_text:
            paragraphs = page.get("paragraphs") or []
            page_text = "\n\n".join(str(paragraph.get("text") or "").strip() for paragraph in paragraphs if str(paragraph.get("text") or "").strip()).strip()
        if not page_text:
            continue
        previews.append(
            {
                "page_no": page.get("page_no"),
                "pdf_page_no": page.get("pdf_page_no"),
                "book_page_no": page.get("book_page_no"),
                "text": page_text,
                "is_navigation_page": _looks_like_navigation_page(page_text),
            }
        )
    return previews


def _truncate_text(text: str, *, max_chars: int, max_lines: int | None = None) -> str:
    normalized = text.strip()
    if not normalized:
        return normalized

    if max_lines is not None:
        lines = normalized.splitlines()
        if len(lines) > max_lines:
            normalized = "\n".join(lines[:max_lines]).rstrip() + "\n..."

    if len(normalized) > max_chars:
        normalized = normalized[: max_chars - 3].rstrip() + "..."

    return normalized


def _normalize_type(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"user", "thread", CORE_TYPE, SPECIALIZED_TYPE, REFERENCE_TYPE}:
        return normalized
    return "unknown"


def _format_book_metadata(candidate: BookCatalogEntry) -> str:
    parts: list[str] = []
    book_type = _normalize_type(candidate.type)
    if book_type != "unknown":
        parts.append(f"类型: {book_type}")
    if candidate.categories:
        parts.append(f"分类: {'、'.join(candidate.categories)}")
    if candidate.eras:
        parts.append(f"时代: {'、'.join(candidate.eras)}")
    if candidate.regions:
        parts.append(f"地区: {'、'.join(candidate.regions)}")
    if candidate.priority is not None:
        parts.append(f"优先级: {candidate.priority}")
    if candidate.score is not None:
        parts.append(f"相关度: {candidate.score:.2f}")
    if candidate.summary:
        parts.append(f"摘要: {candidate.summary}")
    return " | ".join(parts)


def _group_book_candidates(candidates: list[BookCatalogEntry]) -> dict[str, list[BookCatalogEntry]]:
    grouped = {
        "user": [],
        "thread": [],
        CORE_TYPE: [],
        SPECIALIZED_TYPE: [],
        REFERENCE_TYPE: [],
        "unknown": [],
    }
    for candidate in candidates:
        candidate_key = "user" if candidate.scope == "user" else "thread" if candidate.scope == "thread" else _normalize_type(candidate.type)
        grouped.setdefault(candidate_key, grouped["unknown"]).append(candidate)
    return grouped


def _candidate_layer_key(candidate: BookCatalogEntry) -> str:
    if candidate.scope == "user":
        return "user"
    if candidate.scope == "thread":
        return "thread"
    return _normalize_type(candidate.type)


def _candidate_layer_label(layer: str) -> str:
    labels = {
        "user": "用户书籍",
        "thread": "当前线程书籍",
        CORE_TYPE: "核心通用书",
        SPECIALIZED_TYPE: "专题支撑书",
        REFERENCE_TYPE: "补充材料 / 参考工具书",
        "unknown": "其他候选书",
    }
    return labels.get(layer, "其他候选书")


def _format_language_hint(language_hint: str | None) -> str | None:
    normalized = str(language_hint or "").strip()
    if not normalized:
        return None
    labels = {
        "zh-Hans": "简体中文",
        "zh-CN": "简体中文",
        "zh-Hant": "繁体中文",
        "zh-TW": "繁体中文",
        "zh-HK": "繁体中文",
        "en": "英文",
    }
    label = labels.get(normalized)
    if label:
        return f"{label} ({normalized})"
    return normalized


def _format_candidate_brief(candidate: BookCatalogEntry) -> str:
    parts = [candidate.title, f"doc_id={candidate.doc_id}"]
    if candidate.score is not None:
        parts.append(f"相关度={candidate.score:.2f}")
    if candidate.folder_path:
        parts.append(f"目录={candidate.folder_path}")
    if formatted_language := _format_language_hint(candidate.language_hint):
        parts.append(f"语言={formatted_language}")
    # Expose era and category metadata so subtasks can pre-filter without a navigation locate call.
    if candidate.eras:
        parts.append(f"时代={' '.join(candidate.eras[:4])}")
    if candidate.categories:
        parts.append(f"类别={' '.join(candidate.categories[:3])}")
    return " | ".join(parts)


def _format_locate_call_template(doc_id: str) -> str:
    return f'next: knowledge_locate(doc_id="{doc_id}")'


@tool("book_search", parse_docstring=True)
def book_search_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    query: str,
    knowledge_folders: list[str],
) -> str:
    """Search candidate books before full-text retrieval.

    Use this tool first for historical/domain questions. It finds likely user
    books and system books before full-text retrieval so the agent can search
    in a layered order instead of jumping directly into the whole corpus.

    Args:
        query: The user's research question or topic description.
        knowledge_folders: Required knowledge-base folder array. These are
            logical folders from the injected knowledge directory tree, not
            sandbox/local filesystem paths. `book_search` is not allowed to run
            as a whole-corpus catalog search; it must stay inside the chosen
            knowledge folders.
    """
    started_at = time.perf_counter()
    thread_id = runtime.context.get("thread_id")
    user_id = runtime.context.get("user_id")
    selected_doc_ids = _runtime_selected_doc_ids(runtime)
    selected_scopes = _runtime_selected_scopes(runtime)
    logger.info(
        "Book search start: query=%r thread_id=%s has_user=%s selected_doc_ids=%s selected_scopes=%s raw_knowledge_folders=%s",
        query,
        thread_id,
        bool(user_id),
        len(selected_doc_ids or []),
        ",".join(selected_scopes or []),
        _split_loose_delimited_values(knowledge_folders) or [],
    )
    visible_entries = _visible_catalog_entries(
        thread_id=thread_id,
        user_id=user_id,
        selected_doc_ids=selected_doc_ids,
        selected_scopes=selected_scopes,
    )
    raw_knowledge_folders = _split_loose_delimited_values(knowledge_folders) or []
    parsed_knowledge_folders = _parse_knowledge_folders(knowledge_folders)
    if not parsed_knowledge_folders:
        logger.info(
            "Book search rejected: query=%r reason=missing_knowledge_folders elapsed_ms=%.1f",
            query,
            (time.perf_counter() - started_at) * 1000,
        )
        return _build_knowledge_folder_guidance(
            visible_entries=visible_entries,
            reason="Error: `book_search` 禁止整库全量搜索，必须传入 `knowledge_folders`。",
        )
    if any(_looks_like_virtual_knowledge_folder_label(folder) for folder in raw_knowledge_folders):
        logger.info(
            "Book search rejected: query=%r reason=virtual_folder_labels elapsed_ms=%.1f",
            query,
            (time.perf_counter() - started_at) * 1000,
        )
        return _build_knowledge_folder_guidance(
            visible_entries=visible_entries,
            reason="Error: 你传入的 `knowledge_folders` 是层级标签（如 `用户书籍`、`核心通用书`），不是知识库逻辑目录。",
        )
    if any(_looks_like_local_filesystem_path(folder) for folder in raw_knowledge_folders):
        logger.info(
            "Book search rejected: query=%r reason=local_filesystem_path elapsed_ms=%.1f",
            query,
            (time.perf_counter() - started_at) * 1000,
        )
        return _build_knowledge_folder_guidance(
            visible_entries=visible_entries,
            reason="Error: 你传入的 `knowledge_folders` 看起来像本地 sandbox 路径或文件名，不是知识库逻辑目录。",
        )
    if not any(_entry_matches_any_knowledge_folder(entry, parsed_knowledge_folders) for entry in visible_entries):
        logger.info(
            "Book search rejected: query=%r reason=folder_not_visible visible_entries=%s parsed_knowledge_folders=%s elapsed_ms=%.1f",
            query,
            len(visible_entries),
            ",".join(parsed_knowledge_folders),
            (time.perf_counter() - started_at) * 1000,
        )
        return _build_knowledge_folder_guidance(
            visible_entries=visible_entries,
            reason="Error: 当前 `knowledge_folders` 在知识库目录树中没有匹配到任何可见目录。",
        )
    search_started_at = time.perf_counter()
    candidates = search_book_catalog(
        query,
        thread_id=thread_id,
        user_id=user_id,
        top_k=BOOK_SEARCH_TOP_K,
        doc_ids=selected_doc_ids,
        scopes=selected_scopes,
        folder_paths=parsed_knowledge_folders,
        entries=visible_entries,
    )
    logger.info(
        "Book search catalog phase complete: query=%r candidates=%s visible_entries=%s parsed_knowledge_folders=%s elapsed_ms=%.1f",
        query,
        len(candidates),
        len(visible_entries),
        ",".join(parsed_knowledge_folders),
        (time.perf_counter() - search_started_at) * 1000,
    )
    if not candidates:
        _update_runtime_reading_set(runtime, query=query, candidates=[])
        if selected_doc_ids:
            logger.info(
                "Book search no candidates: query=%r selected_doc_ids=%s elapsed_ms=%.1f",
                query,
                len(selected_doc_ids or []),
                (time.perf_counter() - started_at) * 1000,
            )
            return "当前对话已限定在所选资料范围内，但这些资料里没有找到匹配的候选书目。"
        logger.info(
            "Book search no candidates: query=%r elapsed_ms=%.1f",
            query,
            (time.perf_counter() - started_at) * 1000,
        )
        return "No likely books found for this query."

    _update_runtime_reading_set(runtime, query=query, candidates=candidates)

    grouped = _group_book_candidates(candidates)
    lines = []
    lines.extend(["## 候选书目", ""])
    section_titles = (
        ("user", "用户书籍"),
        ("thread", "当前线程书籍"),
        (CORE_TYPE, "核心通用书"),
        (SPECIALIZED_TYPE, "专题支撑书"),
        (REFERENCE_TYPE, "补充材料 / 参考工具书"),
        ("unknown", "其他候选书"),
    )
    for role, title in section_titles:
        items = grouped.get(role, [])
        if not items:
            continue
        lines.append(f"### {title}")
        for candidate in items[:10]:
            lines.append(f"- {_format_candidate_brief(candidate)}")
            lines.append(f"  {_format_locate_call_template(candidate.doc_id)}")
        if len(items) > 10:
            lines.append(f"- 其余 {len(items) - 10} 本已省略")
        lines.append(f"doc_ids: {_format_doc_ids_json([candidate.doc_id for candidate in items])}")
        lines.append("")

    user_doc_ids = _format_doc_ids_json([candidate.doc_id for candidate in grouped["user"]]) if grouped["user"] else ""
    thread_doc_ids = _format_doc_ids_json([candidate.doc_id for candidate in grouped["thread"]]) if grouped["thread"] else ""
    core_doc_ids = _format_doc_ids_json([candidate.doc_id for candidate in grouped[CORE_TYPE]]) if grouped[CORE_TYPE] else ""
    specialized_doc_ids = _format_doc_ids_json([candidate.doc_id for candidate in grouped[SPECIALIZED_TYPE]]) if grouped[SPECIALIZED_TYPE] else ""
    reference_doc_ids = _format_doc_ids_json([candidate.doc_id for candidate in grouped[REFERENCE_TYPE]]) if grouped[REFERENCE_TYPE] else ""

    lines.append("---")
    lines.append("检索规则:")
    lines.append("1. `knowledge_search` 只检索历史主任务/子任务结果，不检索这些书的正文；不要把这里的 `doc_ids` 传给 `knowledge_search`。")
    lines.append('2. 如果你是子任务，下一步应先判断候选书与任务目标是否适配；只复制上方 `next: knowledge_locate(doc_id="...")` 模板里的 `doc_id` 调用 `knowledge_locate`，不要用书名代替。')
    lines.append("3. 如果问题涉及多本书且已启用子任务，不要由主任务继续串行深挖。")
    lines.append("4. 默认顺序：用户书籍 -> 当前线程书籍 -> 核心通用书 -> 专题支撑书 -> 补充材料。")
    lines.append("5. 检索前先看每本候选书的 metadata，尤其 `语言`、`目录`、`摘要` 等信号。")
    lines.append("6. 如果某本书标记为 `zh-Hant` / 繁体中文，就用繁体检索词；如果标记为 `zh-Hans` / 简体中文，就用简体检索词。混合不同字形的书时，优先按书或按字形分开读。")
    if user_doc_ids:
        lines.append(f"user doc_ids: {user_doc_ids}")
    if thread_doc_ids:
        lines.append(f"thread doc_ids: {thread_doc_ids}")
    if core_doc_ids:
        lines.append(f"core doc_ids: {core_doc_ids}")
    if specialized_doc_ids:
        lines.append(f"specialized doc_ids: {specialized_doc_ids}")
    if reference_doc_ids:
        lines.append(f"reference doc_ids: {reference_doc_ids}")
    if parsed_knowledge_folders:
        lines.append(f"knowledge_folders: {', '.join(parsed_knowledge_folders)}")
    logger.info(
        "Book search complete: query=%r grouped_user=%s grouped_thread=%s grouped_core=%s grouped_specialized=%s grouped_reference=%s elapsed_ms=%.1f",
        query,
        len(grouped["user"]),
        len(grouped["thread"]),
        len(grouped[CORE_TYPE]),
        len(grouped[SPECIALIZED_TYPE]),
        len(grouped[REFERENCE_TYPE]),
        (time.perf_counter() - started_at) * 1000,
    )
    return "\n".join(lines)


@tool("knowledge_search", args_schema=KnowledgeSearchArgs)
def knowledge_search_tool(
    runtime: ToolRuntime[ContextT, ThreadState] | None = None,
    query: str = "",
    doc_ids: list[str] | None = None,
    scopes: str | None = None,
    knowledge_folders: list[str] | None = None,
    tool_call_id: Annotated[str | None, InjectedToolCallId] = None,
) -> str | Command:
    """Search historical main-task/subtask results in the task-memory vector store.

    `knowledge_search` now prioritizes the dedicated task-memory collection
    instead of asking the model to pass book IDs. Write a clear query and let
    the system retrieve prior main-task and subtask results by title + query
    similarity. The deprecated compatibility fields (`doc_ids`, `scopes`,
    `knowledge_folders`) are ignored.
    """

    def _finalize(output_text: str, *, target_state: dict[str, Any] | None) -> str | Command:
        # If the caller did not give us a tool_call_id (e.g. the gateway debug
        # endpoint or tests invoking the tool directly), there is no ToolMessage
        # to attach the registry to — fall back to returning the raw text.
        if not tool_call_id:
            return output_text
        update: dict[str, Any] = {
            "messages": [
                ToolMessage(
                    content=output_text,
                    tool_call_id=tool_call_id,
                    name="knowledge_search",
                )
            ],
        }
        # search_and_prepare_task_memory mutated runtime.state in place, but
        # LangGraph only fires channel updates on values returned via Command,
        # so we must echo the merged registry back through `update`.
        update.update(citation_registry_update_fragment(target_state))
        return Command(update=update)

    started_at = time.perf_counter()
    try:
        if doc_ids or scopes or knowledge_folders:
            logger.info(
                "Knowledge search rejected deprecated routing args: query=%r doc_ids=%s scopes=%r knowledge_folders=%s",
                query,
                len(doc_ids or []),
                scopes,
                knowledge_folders or [],
            )
            return _finalize(
                (
                    "## 检索结果\n\n"
                    "`knowledge_search` 现在只检索历史主任务/子任务结果，不检索书籍正文；"
                    "`doc_ids`、`scopes`、`knowledge_folders` 在这里都是误用参数。\n\n"
                    "---\n"
                    "不要继续改写 query 反复调用 `knowledge_search`。如果当前是主任务，下一步应按证据缺口或探索方向派发子任务；"
                    "子任务再自行用 `book_search` 选源，并用 `knowledge_locate(doc_id=...)` 读原文目录、章节页、命中页或连续页正文。"
                ),
                target_state=None,
            )

        from src.community.knowledge_base.task_memory import (
            render_task_memory_matches,
            search_and_prepare_task_memory,
        )

        current_task_title = ""
        target_state = _tool_runtime_state(runtime) if runtime is not None else None
        if target_state is not None:
            current_task_title = str(target_state.get("current_task_title") or "").strip()

        logger.info(
            "Knowledge task-memory search start: query=%r current_task_title=%r elapsed_ms=%.1f",
            query,
            current_task_title,
            (time.perf_counter() - started_at) * 1000,
        )
        results = search_and_prepare_task_memory(
            query=query,
            title=current_task_title or None,
            target_state=target_state,
            top_k=KNOWLEDGE_SEARCH_TOP_K,
        )
        logger.info(
            "Knowledge task-memory search complete: query=%r results=%s elapsed_ms=%.1f",
            query,
            len(results),
            (time.perf_counter() - started_at) * 1000,
        )
        output = render_task_memory_matches(results, heading="## 检索结果")
    except Exception as e:
        logger.exception(
            "Knowledge task-memory search exception: query=%r elapsed_ms=%.1f",
            query,
            (time.perf_counter() - started_at) * 1000,
        )
        return _finalize(f"Error searching task memory: {e}", target_state=None)

    if "本轮没有命中" in output:
        output += (
            "\n\n---\n"
            "把这次未命中视为当前主题没有可复用历史结果。不要继续改写 query 反复调用 `knowledge_search`；"
            "下一步直接从零走原始资料路线：主任务按证据缺口或探索方向派发子任务；"
            "子任务再用 `book_search` 选源，并用 `knowledge_locate` 读目录、章节页、命中页或连续页正文。"
        )
    return _finalize(output, target_state=target_state)


LOCATE_PAGE_WINDOW = 5


def _bounded_locate_range(doc_id, page_no, page_no_end, pdf_page_no, pdf_page_no_end):
    """Bound each numbering system before extraction; disclose exact continuation."""
    args = dict(page_no=page_no, page_no_end=page_no_end, pdf_page_no=pdf_page_no, pdf_page_no_end=pdf_page_no_end)
    notices = []
    for start_key, end_key in (("page_no", "page_no_end"), ("pdf_page_no", "pdf_page_no_end")):
        start, end = args[start_key], args[end_key]
        if start is not None and end is not None and end - start + 1 > LOCATE_PAGE_WINDOW:
            args[end_key] = start + LOCATE_PAGE_WINDOW - 1
            # Preserve the original upper bound; the next call will be bounded too.
            notices.append(f"本次仅返回 {start_key}={start}–{args[end_key]}，请求的后续页尚未读取。确需续读时调用 knowledge_locate(doc_id={json.dumps(doc_id, ensure_ascii=False)}, {start_key}={args[end_key] + 1}, {end_key}={end})。")
    return args, notices


@tool("knowledge_locate", parse_docstring=True)
def knowledge_locate_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    doc_id: str,
    page_no: int | None = None,
    page_no_end: int | None = None,
    pdf_page_no: int | None = None,
    pdf_page_no_end: int | None = None,
    queries: list[str] | None = None,
    pages_per_query: int = 2,
) -> str:
    """Locate full-page source context from a known document and page range.

    Use this after `book_search` when you already know the relevant `doc_id`
    and need the full text of one page or a contiguous page range (up to 5 pages
    per call; larger ranges return an explicit continuation). Prefer
    `doc_id` for model calls; copy it exactly from the `book_search` `next:
    knowledge_locate(doc_id="...")` template.
    If you only know the relevant book but not the exact location yet, you may
    call `knowledge_locate` with only `doc_id` to get a
    navigation preview of likely目录/序言/开篇页，再据此继续按页定位正文。

    Args:
        doc_id: Required document ID copied exactly from `book_search`. Use
            this for all model calls; do not pass null or an empty string.
        page_no: Optional original-book page number to inspect.
        page_no_end: Optional inclusive ending original-book page number for contiguous reading.
        pdf_page_no: Optional physical PDF page number to inspect.
        pdf_page_no_end: Optional inclusive ending PDF page number for contiguous reading.
        queries: Optional 1–8 topic queries to search the full text of this book.
            Returns matching complete body pages per query, excluding contents,
            covers, copyright and blank pages. Prefer this to guessing a PDF
            offset from the page numbers printed in a table of contents.
        pages_per_query: Matching body pages per query, from 1 to 3 (default 2).
    """
    from src.utils.subtask_logging import log_subtask_event

    runtime_context = getattr(runtime, "context", {}) or {}
    log_subtask_event(
        "knowledge_locate_invoked",
        trace_id=runtime_context.get("trace_id"),
        task_id=runtime_context.get("subtask_id"),
        subagent_name=runtime_context.get("subagent_name"),
        thread_id=runtime_context.get("thread_id"),
        doc_id=doc_id,
        page_no=page_no,
        page_no_end=page_no_end,
        pdf_page_no=pdf_page_no,
        pdf_page_no_end=pdf_page_no_end,
    )
    doc_id = str(doc_id or "").strip()
    if not doc_id:
        log_subtask_event(
            "knowledge_locate_missing_document_id",
            trace_id=runtime_context.get("trace_id"),
            task_id=runtime_context.get("subtask_id"),
            subagent_name=runtime_context.get("subagent_name"),
            thread_id=runtime_context.get("thread_id"),
        )
        return (
            "knowledge_locate requires a doc_id. "
            "Your previous tool call omitted the document identifier. "
            "Retry only if you can copy the exact original `doc_id` from the "
            '`book_search` `next: knowledge_locate(doc_id="...")` template; otherwise stop and return '
            "`【证据不足】`. Do not call `knowledge_locate` again with empty args."
        )

    thread_id = runtime.context.get("thread_id")
    user_id = runtime.context.get("user_id")
    selected_doc_ids = _runtime_selected_doc_ids(runtime)
    selected_scopes = _runtime_selected_scopes(runtime)
    visible_entries = _visible_catalog_entries(
        thread_id=thread_id,
        user_id=user_id,
        selected_doc_ids=selected_doc_ids,
        selected_scopes=selected_scopes,
    )

    resolved_doc_id = doc_id
    if doc_id:
        resolved_doc_ids, missing_doc_ids, ambiguous_doc_ids = _resolve_requested_doc_ids(
            [doc_id],
            visible_entries=visible_entries,
        )
        if ambiguous_doc_ids:
            return f"Error: 当前 `knowledge_locate` 传入的 `doc_id` 去除空格后匹配到多个候选：{_format_doc_ids_json(ambiguous_doc_ids)}。请改用 `book_search` / `knowledge_search` 返回的原样 `doc_id`。"
        if missing_doc_ids:
            return f"Error: 当前 `knowledge_locate` 传入的 `doc_id` 在可见资料范围内不存在：{_format_doc_ids_json(missing_doc_ids)}。请使用 `book_search` / `knowledge_search` 返回的原样 `doc_id`。"
        resolved_doc_id = resolved_doc_ids[0] if resolved_doc_ids else doc_id

    try:
        # Fast path: if the catalog entry already carries structured_path, load the
        # payload directly via the lru_cache'd loader — no record-file scanning needed.
        matching_entry = next((e for e in visible_entries if e.doc_id == resolved_doc_id), None)
        document = locate_document_from_entry(matching_entry) if matching_entry else None
        if document is None:
            document = locate_document(thread_id, user_id=user_id, doc_id=resolved_doc_id)
    except Exception as e:
        return f"Error locating document: {e}"
    if not document:
        return "No structured document found for the requested doc_id."

    if queries is not None and any(value is not None for value in (page_no, page_no_end, pdf_page_no, pdf_page_no_end)):
        return "Error: queries and explicit page ranges are separate modes; choose one."
    navigation_mode = queries is None and (page_no is None and page_no_end is None and pdf_page_no is None and pdf_page_no_end is None)
    multi_page_mode = (page_no is not None and page_no_end is not None and page_no_end != page_no) or (pdf_page_no is not None and pdf_page_no_end is not None and pdf_page_no_end != pdf_page_no)

    if navigation_mode:
        previews = _build_navigation_locate_preview(payload=document.payload)
        if not previews:
            return "No navigation preview available for the requested document."

        _mark_runtime_covered_doc_ids(runtime, [str(document.doc_id)])

        lines = ["## 导航预览结果", ""]
        lines.append(f"标题: {document.title}")
        lines.append(f"doc_id: {document.doc_id}")
        lines.append(f"文件: {document.filename}")
        lines.append(f"范围: {document.scope}")
        lines.append(f"文档链接: {document.source_url}")
        lines.append("目录仅供导航，不是正文证据。目录里的书内页码与 PDF 页码可能不同，不能直接互换。")
        if document.original_url and document.original_url != document.source_url:
            lines.append(f"原始文件: {document.original_url}")
        lines.append("")

        for index, preview in enumerate(previews, 1):
            location_text = (
                _build_location_text(
                    page_no=None,
                    pdf_page_no=preview.get("pdf_page_no"),
                    paragraph_no=None,
                )
                or "未标注页码"
            )
            kind = "目录/导航页" if preview.get("is_navigation_page") else "开篇预览页"
            lines.append(f"### 导航片段 {index}: {kind} - {location_text}")
            lines.append(str(preview.get("text") or "").strip())
            lines.append("")

        lines.append("---")
        lines.append("下一步：用 knowledge_locate(doc_id=原样doc_id, queries=[各个时期或主题的查询]) 在整本书正文中批量定位；返回的 PDF 页码才可用于续读。不要把目录标题用作历史断言的依据。")
        lines.append("如果这是人物生平、经历、制度沿革这类零散问题，优先沿目录里的阶段/专题板块继续定位，不要只反复改关键词。")
        lines.append("为了减少反复调用，优先一次性读取更有代表性的连续页，不要机械地一页一页连续点开。")
        return "\n".join(lines)

    bounded_args, continuation_notices = _bounded_locate_range(resolved_doc_id, page_no, page_no_end, pdf_page_no, pdf_page_no_end)
    try:
        if queries is not None:
            excerpts, missing_queries = search_body_pages(document.payload, queries, pages_per_query=pages_per_query)
            continuation_notices += [f"未找到正文匹配: {query}；不能用目录补足该主题。" for query in missing_queries]
        else:
            excerpts = extract_document_context(payload=document.payload, **bounded_args)
    except Exception as e:
        return f"Error extracting source context: {e}"

    if not excerpts:
        return "No matching body/page context found. " + " ".join(continuation_notices)

    _mark_runtime_covered_doc_ids(runtime, [str(document.doc_id)])
    state = _tool_runtime_state(runtime)

    lines = ["## 原文定位结果", "", *continuation_notices, ""]
    lines.append(f"标题: {document.title}")
    lines.append(f"doc_id: {document.doc_id}")
    lines.append(f"文件: {document.filename}")
    lines.append(f"范围: {document.scope}")
    lines.append(f"文档链接: {document.source_url}")
    if document.original_url and document.original_url != document.source_url:
        lines.append(f"原始文件: {document.original_url}")
    lines.append("")

    for index, excerpt in enumerate(excerpts, 1):
        location_text = (
            _build_location_text(
                page_no=None,
                pdf_page_no=excerpt.get("pdf_page_no"),
                paragraph_no=None,
            )
            or "未标注页码"
        )
        lines.append(f"### 整页 {index}: {location_text}")
        kind = page_kind(str(excerpt.get("text") or ""))
        for query in excerpt.get("matched_queries", []):
            lines.append(f"主题: {query}")
        if excerpt.get("source_chapter"):
            lines.append(f"所属章: {excerpt['source_chapter']}")
        lines.append(f"页面类型: {kind}")
        citation = (
            _build_locate_excerpt_citation(
                document=document,
                excerpt=excerpt,
                thread_id=thread_id,
                user_id=user_id,
                state=state,
            )
            if kind == "body"
            else None
        )
        if citation:
            lines.append(f"citation: {citation}")
        else:
            lines.append("此页不能作为正文证据，不生成 citation；仅供导航或版本信息核对。")
        lines.append(str(excerpt.get("text") or "").strip())
        lines.append("")

    lines.append("---")
    if multi_page_mode:
        lines.append("这次 `knowledge_locate` 已按连续页范围展开，适合快速通读多页正文。")
    else:
        lines.append("如果同一主题明显跨相邻多页，优先直接用 `page_no_end` / `pdf_page_no_end` 一次展开连续页。")
    lines.append("使用答案时，优先直接复制上面的编号 `citation:` 行，不要自己重写。")
    lines.append("IMPORTANT: Use these excerpts as the follow-up source context. Do not inspect raw PDFs or `.structured.json` files directly.")
    return "\n".join(lines)
