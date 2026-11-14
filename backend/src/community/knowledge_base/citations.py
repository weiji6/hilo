from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from uuid import NAMESPACE_URL, uuid5

from src.community.knowledge_base.locator import locate_document
from src.community.knowledge_base.user_store import build_user_doc_public_url

KNOWLEDGE_CITATION_REGISTRY_KEY = "knowledge_citation_registry"
NUMBERED_CITATION_REFERENCE_PATTERN = re.compile(r"\[citation:\s*(\d+)\s*\]", re.IGNORECASE)


def _normalize_citation_label(label: str | None) -> str:
    cleaned = str(label or "").strip()
    return re.sub(r"\s+", " ", cleaned)



def _normalize_citation_url_for_key(url: str | None) -> str:
    if not url:
        return ""

    parts = urlsplit(url)
    normalized_query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    normalized_path = re.sub(r"/+", "/", parts.path or "")
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            normalized_path,
            normalized_query,
            parts.fragment,
        )
    )



def build_citation_stable_key(
    *,
    citation_label: str,
    citation_link: str | None,
) -> str | None:
    normalized_url = _normalize_citation_url_for_key(citation_link)
    normalized_label = _normalize_citation_label(citation_label)
    if not normalized_url and not normalized_label:
        return None

    stable_seed = normalized_url or normalized_label
    return str(uuid5(NAMESPACE_URL, f"knowledge-citation:{stable_seed}"))



def register_citation_marker(
    state: dict[str, Any] | None,
    *,
    citation_label: str,
    citation_link: str | None,
    stable_ids: bool = False,
) -> str | None:
    """Register a real citation URL in state and return a model-safe numbered marker."""
    import logging
    _logger = logging.getLogger(__name__)
    if not citation_link:
        _logger.debug("register_citation_marker skipped: no citation_link")
        return None
    if state is None:
        _logger.debug("register_citation_marker skipped: no state")
        return None

    normalized_label = _normalize_citation_label(citation_label)
    stable_key = build_citation_stable_key(
        citation_label=normalized_label,
        citation_link=citation_link,
    )

    raw_registry = state.setdefault(KNOWLEDGE_CITATION_REGISTRY_KEY, [])
    if not isinstance(raw_registry, list):
        raw_registry = []
        state[KNOWLEDGE_CITATION_REGISTRY_KEY] = raw_registry

    for item in raw_registry:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            continue
        item_stable_key = str(item.get("stable_key") or "").strip()
        if stable_key and item_stable_key and item_stable_key == stable_key:
            _logger.debug("register_citation_marker reuse by stable_key: %s -> %s", stable_key, item_id)
            return f"[citation:{item_id}]"
        if item.get("label") == normalized_label and item.get("url") == citation_link:
            _logger.debug("register_citation_marker reuse by label+url: %s -> %s", normalized_label, item_id)
            return f"[citation:{item_id}]"

    # Parallel page tools may start from the same state snapshot. Sequential
    # length-based IDs then point at different pages in different branches.
    # PDF locates use a URL-derived 48-bit integer, safe in JavaScript as well.
    citation_id = str(int(stable_key.replace("-", "")[:12], 16)) if stable_ids and stable_key else str(len(raw_registry) + 1)
    entry = {
        "id": citation_id,
        "label": normalized_label,
        "url": citation_link,
    }
    if stable_key:
        entry["stable_key"] = stable_key
    raw_registry.append(entry)
    _logger.info(
        "register_citation_marker new entry: id=%s label=%s url=%s registry_count=%s",
        citation_id,
        normalized_label,
        citation_link,
        len(raw_registry),
    )
    return f"[citation:{citation_id}]"


def merge_citation_registry(
    target_state: dict[str, Any] | None,
    source_registry: list[dict[str, Any]] | None,
) -> dict[str, str]:
    """Merge a child citation registry into target state and return old-id to new-id mapping."""
    import logging
    _logger = logging.getLogger(__name__)

    if target_state is None or not source_registry:
        _logger.debug("merge_citation_registry skipped: target_state=%s source_registry_count=%s", target_state is not None, len(source_registry) if source_registry else 0)
        return {}

    mapping: dict[str, str] = {}
    skipped = 0
    for item in source_registry:
        if not isinstance(item, dict):
            skipped += 1
            continue
        source_id = str(item.get("id") or "").strip()
        label = _normalize_citation_label(str(item.get("label") or "").strip())
        url = str(item.get("url") or "").strip()
        if not source_id or not label or not url:
            _logger.debug("merge_citation_registry skip item: missing field source_id=%s label=%s url=%s", bool(source_id), bool(label), bool(url))
            skipped += 1
            continue
        marker = register_citation_marker(
            target_state,
            citation_label=label,
            citation_link=url,
        )
        if not marker:
            _logger.debug("merge_citation_registry skip item: register_citation_marker returned None for source_id=%s", source_id)
            skipped += 1
            continue
        match = NUMBERED_CITATION_REFERENCE_PATTERN.fullmatch(marker)
        if match:
            mapping[source_id] = match.group(1)
    _logger.info(
        "merge_citation_registry done: source_count=%s merged=%s skipped=%s mapping=%s target_registry_count=%s",
        len(source_registry),
        len(mapping),
        skipped,
        mapping,
        len(target_state.get(KNOWLEDGE_CITATION_REGISTRY_KEY, [])) if target_state else "N/A",
    )
    return mapping


def merge_citation_registries(
    existing: list[dict[str, Any]] | None,
    new: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """LangGraph reducer for ``knowledge_citation_registry``.

    Required because multiple tool calls in a single step (e.g. two parallel
    ``knowledge_search`` calls, or ``knowledge_search`` next to a subagent
    finishing in the same step) can each emit a ``Command`` writing this key.
    Without a reducer LangGraph raises ``INVALID_CONCURRENT_GRAPH_UPDATE``.

    Strategy: union by ``stable_key`` (falling back to ``label|url``); the
    existing list wins on dedupe so previously-assigned numeric IDs remain
    stable across the merge. Branches that registered the same citation will
    collapse cleanly. Branches that genuinely registered different new
    citations may end up with id collisions (each branch numbered from the
    same snapshot) — those new entries are still appended, which is better
    than dropping them, but the in-message ``[citation:N]`` markers from one
    of the branches will resolve to the wrong entry. Avoid relying on this
    edge case; surface registrations through a single tool when possible.
    """

    if existing is None:
        return [item for item in (new or []) if isinstance(item, dict)]
    if new is None:
        return [item for item in existing if isinstance(item, dict)]

    def _dedupe_key(item: dict[str, Any]) -> str | None:
        stable_key = str(item.get("stable_key") or "").strip()
        if stable_key:
            return f"sk:{stable_key}"
        label = _normalize_citation_label(str(item.get("label") or "").strip())
        url = _normalize_citation_url_for_key(str(item.get("url") or "").strip())
        if not label and not url:
            return None
        return f"lu:{label}|{url}"

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in existing:
        if not isinstance(item, dict):
            continue
        merged.append(item)
        key = _dedupe_key(item)
        if key:
            seen.add(key)
    for item in new:
        if not isinstance(item, dict):
            continue
        key = _dedupe_key(item)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        merged.append(item)
    return merged


def citation_registry_update_fragment(state: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    """Return a LangGraph update fragment that syncs the citation registry channel.

    LangGraph only fires channel updates on values returned from middleware /
    tool handlers; in-place mutation of ``runtime.state`` does NOT propagate.
    Any code path that calls ``merge_citation_registry`` (directly or via
    ``prepare_task_memory_matches_for_injection``) must merge this fragment
    into its returned update payload, otherwise the merged citations will not
    reach the frontend even though the in-memory state dict looks correct.
    """

    if not isinstance(state, dict):
        return {}
    raw = state.get(KNOWLEDGE_CITATION_REGISTRY_KEY)
    if not isinstance(raw, list) or not raw:
        return {}
    return {KNOWLEDGE_CITATION_REGISTRY_KEY: list(raw)}


def rewrite_numbered_citations(text: str, citation_id_mapping: dict[str, str]) -> str:
    """Rewrite bare numbered citation markers according to a registry id mapping."""

    if not text or not citation_id_mapping:
        return text

    def replace(match: re.Match[str]) -> str:
        old_id = match.group(1).strip()
        new_id = citation_id_mapping.get(old_id)
        return f"[citation:{new_id}]" if new_id else match.group(0)

    return NUMBERED_CITATION_REFERENCE_PATTERN.sub(replace, text)



def extract_numbered_citation_ids(text: str) -> list[str]:
    if not text:
        return []

    seen: set[str] = set()
    citation_ids: list[str] = []
    for match in NUMBERED_CITATION_REFERENCE_PATTERN.finditer(text):
        citation_id = str(match.group(1) or "").strip()
        if not citation_id or citation_id in seen:
            continue
        seen.add(citation_id)
        citation_ids.append(citation_id)
    return citation_ids



def collect_citation_registry_entries(
    citation_registry: list[dict[str, Any]] | None,
    *,
    citation_ids: list[str] | None = None,
) -> list[dict[str, str]]:
    if not citation_registry:
        return []

    allowed_ids = {str(item).strip() for item in citation_ids or [] if str(item).strip()}
    collected: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in citation_registry:
        if not isinstance(item, dict):
            continue
        citation_id = str(item.get("id") or "").strip()
        label = _normalize_citation_label(str(item.get("label") or "").strip())
        url = str(item.get("url") or "").strip()
        stable_key = str(item.get("stable_key") or "").strip()
        if allowed_ids and citation_id not in allowed_ids:
            continue
        if not citation_id or not label or not url:
            continue
        dedupe_key = stable_key or f"{label}\n{_normalize_citation_url_for_key(url)}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        entry = {
            "id": citation_id,
            "label": label,
            "url": url,
        }
        if stable_key:
            entry["stable_key"] = stable_key
        collected.append(entry)
    return collected


def encode_source_url(url: str | None) -> str | None:
    if not url:
        return url
    return quote(url, safe="/:?=&%#")


def append_pdf_page_fragment(url: str | None, pdf_page_no: int | None) -> str | None:
    if not url or not pdf_page_no or "#page=" in url:
        return url
    return f"{url}#page={pdf_page_no}"


def append_location_params(
    url: str | None,
    *,
    page: int | None = None,
    page_no: int | None = None,
    pdf_page_no: int | None = None,
    paragraph_no: int | None = None,
) -> str | None:
    if not url:
        return url
    base, sep, fragment = url.partition("#")
    params: dict[str, int] = {}
    if page is not None:
        params["page"] = page
    if page_no:
        params["page_no"] = page_no
    if pdf_page_no:
        params["pdf_page_no"] = pdf_page_no
    if paragraph_no:
        params["paragraph_no"] = paragraph_no
    if params:
        joiner = "&" if "?" in base else "?"
        base = f"{base}{joiner}{urlencode(params)}"
    if sep:
        return f"{base}#{fragment}"
    return base


def append_query_params(url: str | None, **params: str | int | None) -> str | None:
    if not url:
        return url

    filtered = [(key, str(value)) for key, value in params.items() if value not in {None, ""}]
    if not filtered:
        return url

    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.extend(filtered)
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        )
    )


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_thread_artifact_url(thread_id: str | None, filename: str | None) -> str | None:
    if not thread_id or not filename:
        return None
    return f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{filename}"


def _apply_result_location(
    url: str | None,
    *,
    source_type: str,
    page: int | None,
    page_no: int | None,
    pdf_page_no: int | None,
    paragraph_no: int | None,
) -> str | None:
    if source_type == "pdf" and page is not None and pdf_page_no is None:
        return append_location_params(url, page=page)
    url = append_pdf_page_fragment(url, pdf_page_no)
    return append_location_params(
        url,
        page_no=page_no,
        pdf_page_no=pdf_page_no,
        paragraph_no=paragraph_no,
    )


def _resolve_original_document(
    metadata: dict[str, Any],
    *,
    thread_id: str | None,
    user_id: str | None,
):
    origin_scope = str(metadata.get("origin_scope") or "").strip().lower()
    origin_doc_id = metadata.get("origin_doc_id")
    origin_filename = metadata.get("origin_filename")
    if origin_scope not in {"global", "thread", "user"}:
        return None
    if not origin_doc_id and not origin_filename:
        return None
    return locate_document(
        thread_id=thread_id if origin_scope == "thread" else None,
        user_id=user_id if origin_scope == "user" else None,
        doc_id=str(origin_doc_id) if origin_doc_id else None,
        filename=str(origin_filename) if origin_filename else None,
    )


def _source_label(scope: str, source_kind: str) -> str | None:
    normalized_scope = (scope or "").strip().lower()
    normalized_kind = (source_kind or "").strip().lower()

    if normalized_scope == "user":
        if normalized_kind in {"excerpt", "annotation", "translation", "note"}:
            return "你的笔记"
        if normalized_kind == "upload":
            return "你上传的文档"
        if normalized_kind == "import_ref":
            return "你导入的参考资料"
        return "你的文档"

    if normalized_scope == "thread":
        return "你上传的文档"

    if normalized_scope == "global":
        return "知识库文档"

    return None


def resolve_result_citation_context(
    result: dict[str, Any],
    *,
    thread_id: str | None,
    user_id: str | None,
) -> dict[str, Any]:
    metadata = result.get("metadata", {})
    filename = str(result.get("filename") or metadata.get("filename") or "")
    title = str(metadata.get("title") or filename or "Unknown")
    scope = str(metadata.get("scope") or "global")
    source_type = str(result.get("source_type", metadata.get("source_type", "unknown")) or "unknown")

    current_page = _coerce_int(result.get("page"))
    current_page_no = _coerce_int(metadata.get("page_no"))
    current_pdf_page_no = _coerce_int(metadata.get("pdf_page_no"))
    current_paragraph_no = _coerce_int(metadata.get("paragraph_no"))

    if scope == "thread":
        source_url = _build_thread_artifact_url(
            str(metadata.get("thread_id") or thread_id or ""),
            filename,
        )
    elif scope == "user":
        source_url = build_user_doc_public_url(filename) if filename else None
    else:
        source_url = f"/api/knowledge/docs/{filename}" if filename else None

    source_url = _apply_result_location(
        source_url,
        source_type=source_type,
        page=current_page,
        page_no=current_page_no,
        pdf_page_no=current_pdf_page_no,
        paragraph_no=current_paragraph_no,
    )

    original_document = _resolve_original_document(
        metadata,
        thread_id=thread_id,
        user_id=user_id,
    )
    origin_anchor = metadata.get("origin_anchor") if isinstance(metadata.get("origin_anchor"), dict) else {}
    citation_page_no = _coerce_int(origin_anchor.get("page_no")) or current_page_no
    citation_pdf_page_no = _coerce_int(origin_anchor.get("pdf_page_no")) or current_pdf_page_no
    citation_paragraph_no = _coerce_int(origin_anchor.get("paragraph_no")) or current_paragraph_no

    original_url: str | None = None
    original_title: str | None = None
    if original_document:
        original_url = original_document.source_url
        original_title = original_document.title
    elif scope == "thread":
        original_url = _build_thread_artifact_url(
            str(metadata.get("thread_id") or thread_id or ""),
            str(metadata.get("origin_filename") or filename or ""),
        )
    elif scope == "user":
        origin_scope = str(metadata.get("origin_scope") or "").strip().lower()
        origin_filename = str(metadata.get("origin_filename") or "")
        if origin_scope == "global" and origin_filename:
            original_url = f"/api/knowledge/docs/{origin_filename}"
        elif origin_scope == "thread":
            original_url = _build_thread_artifact_url(thread_id, origin_filename)
        elif origin_scope == "user" and origin_filename:
            original_url = build_user_doc_public_url(origin_filename)
    elif metadata.get("origin_filename"):
        original_url = f"/api/knowledge/docs/{metadata.get('origin_filename')}"

    original_url = _apply_result_location(
        original_url,
        source_type=source_type,
        page=current_page,
        page_no=citation_page_no,
        pdf_page_no=citation_pdf_page_no,
        paragraph_no=citation_paragraph_no,
    )

    source_kind = str(metadata.get("source_kind") or source_type or "").strip().lower()
    source_label = _source_label(scope, source_kind)

    citation_url = original_url or source_url
    citation_title = original_title or title
    citation_page = current_page
    citation_page_no_value = citation_page_no
    citation_pdf_page_no_value = citation_pdf_page_no
    citation_paragraph_no_value = citation_paragraph_no

    if scope in {"user", "thread"}:
        citation_url = source_url
        citation_title = f"{source_label}：{title}" if source_label else title
        citation_page_no_value = current_page_no
        citation_pdf_page_no_value = current_pdf_page_no
        citation_paragraph_no_value = current_paragraph_no

    citation_url = append_query_params(
        citation_url,
        citation_scope=scope,
        citation_source_kind=source_kind,
        citation_source_label=source_label,
        citation_source_title=title,
        citation_origin_title=original_title,
    )

    return {
        "source_url": encode_source_url(source_url),
        "original_url": encode_source_url(original_url),
        "citation_url": encode_source_url(citation_url),
        "source_title": title,
        "original_title": original_title,
        "citation_title": citation_title,
        "citation_page": citation_page,
        "citation_page_no": citation_page_no_value,
        "citation_pdf_page_no": citation_pdf_page_no_value,
        "citation_paragraph_no": citation_paragraph_no_value,
        "source_scope": scope,
        "source_kind": source_kind,
        "source_label": source_label,
    }
