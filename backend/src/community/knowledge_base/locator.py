"""Structured document locator helpers for page-based lookups."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from src.community.knowledge_base.common import (
    derive_global_doc_id,
    derive_thread_doc_id,
    derive_user_doc_id,
    resolve_project_path,
)
from src.community.knowledge_base.document_parsers import parse_local_text
from src.community.knowledge_base.ingestion import list_ingestion_records
from src.community.knowledge_base.paragraph_store import (
    load_structured_payload_from_db,
    lookup_global_book_meta,
    lookup_global_book_meta_by_filename,
)
from src.community.knowledge_base.structured_document import load_structured_document
from src.community.knowledge_base.user_store import build_user_doc_public_url, list_user_records
from src.config.knowledge_base_config import get_knowledge_base_config


def _load_payload(doc_id: str, structured_path: str | None, *, global_scope: bool = True) -> dict | None:
    """Use the shared SQLite corpus only for global sources, then file fallback."""
    if global_scope:
        payload = load_structured_payload_from_db(doc_id)
        if payload is not None:
            return payload
    if structured_path:
        return load_structured_document(Path(str(structured_path)))
    return None


@dataclass
class LocatedDocument:
    doc_id: str
    title: str
    filename: str
    scope: str
    source_url: str
    original_url: str | None
    payload: dict[str, Any]


def _normalize_filename_for_match(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip()
    text = text.translate(str.maketrans({"　": " ", "\u00a0": " "}))
    return re.sub(r"\s+", "", text).lower()


def _filename_match_score(requested_filename: str | None, candidate_filename: str) -> float:
    requested = _normalize_filename_for_match(requested_filename)
    candidate = _normalize_filename_for_match(candidate_filename)
    if not requested or not candidate:
        return 0.0

    if requested == candidate:
        return 10_000.0

    requested_path = Path(requested)
    candidate_path = Path(candidate)
    requested_stem = requested_path.stem or requested
    candidate_stem = candidate_path.stem or candidate
    requested_suffix = requested_path.suffix
    candidate_suffix = candidate_path.suffix

    if requested_stem == candidate_stem:
        return 9_000.0 + (100.0 if requested_suffix == candidate_suffix else 0.0)

    score = 0.0
    if requested_suffix and candidate_suffix and requested_suffix == candidate_suffix:
        score += 15.0

    full_ratio = SequenceMatcher(None, requested, candidate).ratio()
    stem_ratio = SequenceMatcher(None, requested_stem, candidate_stem).ratio()
    score += max(full_ratio * 100.0, stem_ratio * 120.0)

    if requested_stem and candidate_stem:
        if requested_stem in candidate_stem or candidate_stem in requested_stem:
            score += 20.0

    return score


def _is_exact_identifier_match(
    *,
    requested_doc_id: str | None,
    requested_filename: str | None,
    candidate_doc_id: str,
    candidate_filename: str,
) -> bool:
    if requested_doc_id and requested_doc_id == candidate_doc_id:
        return True
    if requested_filename and requested_filename == candidate_filename:
        return True
    return False


def _locate_global_document(doc_id: str | None, filename: str | None) -> LocatedDocument | None:
    docs_root = resolve_project_path(get_knowledge_base_config().docs_path)

    # Fast path: metadata comes from paragraphs.db; payload comes from the original
    # .structured.json file (which contains bbox/position data the structured-page viewer
    # needs to render text overlays).  paragraphs.db stores text-only — no position —
    # so we must prefer the file here.  load_structured_document is lru_cache'd so
    # repeated calls within the same process are free after the first read.
    def _build_located(resolved_doc_id: str, meta: dict) -> LocatedDocument | None:
        # Primary: load from paragraphs.db (LRU-cached, includes position after migration).
        payload = load_structured_payload_from_db(resolved_doc_id)

        # If the DB payload has no position data (rows ingested before --update-positions
        # was run), fall back to the original .structured.json file which always has it.
        # doc_id is a relative POSIX path from docs_root (e.g. ".ingestion/filename.pdf"),
        # so the structured file lives at docs_root / resolved_doc_id + ".structured.json".
        if payload is not None:
            pages = payload.get("pages") or []
            has_position = any(
                para.get("position") is not None
                for page in pages
                for para in (page.get("paragraphs") or [])
            )
            if not has_position:
                structured_file = Path(str(docs_root / resolved_doc_id) + ".structured.json")
                file_payload = load_structured_document(structured_file)
                if file_payload is not None:
                    payload = file_payload
        else:
            # Doc not in DB yet — try file directly.
            structured_file = Path(str(docs_root / resolved_doc_id) + ".structured.json")
            payload = load_structured_document(structured_file)

        if payload is None:
            return None
        fname = meta["filename"]
        source_url = meta["source_url"] or f"/api/knowledge/docs/{fname}"
        # Normalize doc_id to catalog format: strip legacy .ingestion/ prefix so
        # the returned doc_id matches what catalog entries use.
        canonical_doc_id = resolved_doc_id.removeprefix(".ingestion/")
        return LocatedDocument(
            doc_id=canonical_doc_id,
            title=meta["title"] or str(payload.get("title") or ""),
            filename=fname,
            scope="global",
            source_url=source_url,
            original_url=meta["original_url"],
            payload=payload,
        )

    if doc_id:
        meta = lookup_global_book_meta(doc_id)
        if meta is not None:
            located = _build_located(meta["doc_id"], meta)
            if located is not None:
                return located
        # Exact doc_id miss — likely the catalog uses "filename.pdf" while the DB
        # stores ".ingestion/filename.pdf".  Try a filename-based lookup which
        # matches on books.filename (always the bare filename with no prefix).
        doc_basename = Path(doc_id).name
        if doc_basename:
            meta2 = lookup_global_book_meta_by_filename(doc_basename)
            if meta2 is not None:
                located = _build_located(meta2["doc_id"], meta2)
                if located is not None:
                    return located
    elif filename:
        meta = lookup_global_book_meta_by_filename(filename)
        if meta is not None:
            located = _build_located(meta["doc_id"], meta)
            if located is not None:
                return located

    # Raw text sources (including quick-start fixtures) need no OCR sidecar.
    requested = doc_id or filename
    if requested:
        source = (docs_root / requested).resolve()
        if source.is_relative_to(docs_root.resolve()) and source.is_file() and source.suffix.lower() in {".md", ".txt"}:
            canonical_id = derive_global_doc_id(docs_root, source)
            return LocatedDocument(
                doc_id=canonical_id, title=source.stem, filename=source.name,
                scope="global", source_url=f"/api/knowledge/docs/{canonical_id}",
                original_url=None, payload=parse_local_text(source, title=source.stem),
            )

    # Slow path: scan ingestion records (DB miss — doc not yet ingested or filename fuzzy match).
    ingestion_dir = docs_root / ".ingestion"
    # Store (score, source_filename, record) — defer payload loading until we know the winner.
    best_match: tuple[float, str, dict] | None = None

    if ingestion_dir.exists():
        for record_path in sorted(ingestion_dir.glob("*.json")):
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if record.get("schema_version") == 1:
                continue

            source_filename = str(record.get("source_filename") or "")
            if not source_filename:
                continue
            candidate_doc_id = derive_global_doc_id(docs_root, docs_root / source_filename)

            # Check identity BEFORE loading the (potentially large) structured document.
            if _is_exact_identifier_match(
                requested_doc_id=doc_id,
                requested_filename=filename,
                candidate_doc_id=candidate_doc_id,
                candidate_filename=source_filename,
            ):
                structured_path = record.get("structured_path")
                payload = _load_payload(candidate_doc_id, structured_path)
                if not payload:
                    continue
                return LocatedDocument(
                    doc_id=candidate_doc_id,
                    title=str(payload.get("title") or record.get("display_title") or Path(source_filename).stem),
                    filename=source_filename,
                    scope="global",
                    source_url=str(record.get("preview_artifact_url") or f"/api/knowledge/docs/{source_filename}"),
                    original_url=record.get("source_artifact_url"),
                    payload=payload,
                )

            if filename:
                score = _filename_match_score(filename, source_filename)
                if score >= 70.0 and (best_match is None or score > best_match[0]):
                    best_match = (score, source_filename, record)

    # Load the payload for the single best fuzzy match (at most one file read).
    if best_match is None:
        return None
    _, best_filename, best_record = best_match
    best_doc_id = derive_global_doc_id(docs_root, docs_root / best_filename)
    structured_path = best_record.get("structured_path")
    payload = _load_payload(best_doc_id, structured_path)
    if not payload:
        return None
    return LocatedDocument(
        doc_id=best_doc_id,
        title=str(payload.get("title") or best_record.get("display_title") or Path(best_filename).stem),
        filename=best_filename,
        scope="global",
        source_url=str(best_record.get("preview_artifact_url") or f"/api/knowledge/docs/{best_filename}"),
        original_url=best_record.get("source_artifact_url"),
        payload=payload,
    )


def _locate_thread_document(thread_id: str, doc_id: str | None, filename: str | None) -> LocatedDocument | None:
    best_match: tuple[float, str, dict] | None = None
    for record in list_ingestion_records(thread_id):
        source_filename = str(record.get("source_filename") or record.get("index_target_filename") or "")
        if not source_filename:
            continue
        candidate_doc_id = derive_thread_doc_id(Path(source_filename))

        # Check identity BEFORE loading the structured document.
        if _is_exact_identifier_match(
            requested_doc_id=doc_id,
            requested_filename=filename,
            candidate_doc_id=candidate_doc_id,
            candidate_filename=source_filename,
        ):
            structured_path = record.get("structured_path")
            payload = _load_payload(candidate_doc_id, structured_path, global_scope=False)
            if not payload:
                continue
            return LocatedDocument(
                doc_id=candidate_doc_id,
                title=str(payload.get("title") or record.get("display_title") or Path(source_filename).stem),
                filename=source_filename,
                scope="thread",
                source_url=str(record.get("preview_artifact_url") or record.get("source_artifact_url") or ""),
                original_url=record.get("source_artifact_url"),
                payload=payload,
            )

        if filename:
            score = _filename_match_score(filename, source_filename)
            if score >= 70.0 and (best_match is None or score > best_match[0]):
                best_match = (score, source_filename, record)

    # Load the payload for the single best fuzzy match (at most one file read).
    if best_match is None:
        return None
    _, best_filename, best_record = best_match
    best_doc_id = derive_thread_doc_id(Path(best_filename))
    structured_path = best_record.get("structured_path")
    payload = _load_payload(best_doc_id, structured_path, global_scope=False)
    if not payload:
        return None
    return LocatedDocument(
        doc_id=best_doc_id,
        title=str(payload.get("title") or best_record.get("display_title") or Path(best_filename).stem),
        filename=best_filename,
        scope="thread",
        source_url=str(best_record.get("preview_artifact_url") or best_record.get("source_artifact_url") or ""),
        original_url=best_record.get("source_artifact_url"),
        payload=payload,
    )


def _locate_user_document(user_id: str, doc_id: str | None, filename: str | None) -> LocatedDocument | None:
    best_match: tuple[float, str, str, dict] | None = None
    for record in list_user_records(user_id):
        source_filename = str(record.get("source_filename") or record.get("index_target_filename") or "")
        record_id = str(record.get("id") or "")
        if not source_filename or not record_id:
            continue
        candidate_doc_id = derive_user_doc_id(record_id)

        # Check identity BEFORE loading the structured document.
        if _is_exact_identifier_match(
            requested_doc_id=doc_id,
            requested_filename=filename,
            candidate_doc_id=candidate_doc_id,
            candidate_filename=source_filename,
        ):
            structured_path = record.get("structured_path")
            payload = _load_payload(candidate_doc_id, structured_path, global_scope=False)
            if not payload:
                continue
            return LocatedDocument(
                doc_id=candidate_doc_id,
                title=str(payload.get("title") or record.get("display_title") or Path(source_filename).stem),
                filename=source_filename,
                scope="user",
                source_url=build_user_doc_public_url(source_filename),
                original_url=build_user_doc_public_url(source_filename),
                payload=payload,
            )

        if filename:
            score = _filename_match_score(filename, source_filename)
            if score >= 70.0 and (best_match is None or score > best_match[0]):
                best_match = (score, source_filename, record_id, record)

    # Load the payload for the single best fuzzy match (at most one file read).
    if best_match is None:
        return None
    _, best_filename, best_record_id, best_record = best_match
    best_doc_id = derive_user_doc_id(best_record_id)
    structured_path = best_record.get("structured_path")
    payload = _load_payload(best_doc_id, structured_path, global_scope=False)
    if not payload:
        return None
    return LocatedDocument(
        doc_id=best_doc_id,
        title=str(payload.get("title") or best_record.get("display_title") or Path(best_filename).stem),
        filename=best_filename,
        scope="user",
        source_url=build_user_doc_public_url(best_filename),
        original_url=build_user_doc_public_url(best_filename),
        payload=payload,
    )


def locate_document(
    thread_id: str | None,
    user_id: str | None = None,
    doc_id: str | None = None,
    filename: str | None = None,
) -> LocatedDocument | None:
    """Resolve a structured document from a doc_id or filename."""
    if user_id:
        user_match = _locate_user_document(user_id, doc_id, filename)
        if user_match:
            return user_match
    if thread_id:
        thread_match = _locate_thread_document(thread_id, doc_id, filename)
        if thread_match:
            return thread_match
    return _locate_global_document(doc_id, filename)


def locate_document_from_entry(entry: Any) -> LocatedDocument | None:
    """Build a LocatedDocument from a BookCatalogEntry without rescanning record files.

    Uses the entry's structured_path (stored in catalog) to load the payload directly
    via the lru_cache'd loader, skipping the O(n) ingestion-record scan in locate_document.
    Falls back gracefully to None if structured_path is absent or the file can't be read.
    """
    structured_path = getattr(entry, "structured_path", None)
    payload = _load_payload(entry.doc_id, structured_path, global_scope=entry.scope == "global")
    if not payload:
        return _locate_global_document(entry.doc_id, None) if entry.scope == "global" else None
    return LocatedDocument(
        doc_id=entry.doc_id,
        title=entry.title,
        filename=entry.filename,
        scope=entry.scope,
        source_url=entry.source_url,
        original_url=entry.original_url,
        payload=payload,
    )


def extract_document_context(
    *,
    payload: dict[str, Any],
    page_no: int | None = None,
    page_no_end: int | None = None,
    pdf_page_no: int | None = None,
    pdf_page_no_end: int | None = None,
) -> list[dict[str, Any]]:
    """Extract full-page text blocks for the requested page range."""
    if page_no is None and page_no_end is None and pdf_page_no is None and pdf_page_no_end is None:
        raise ValueError(
            "At least one of page_no, page_no_end, pdf_page_no, or pdf_page_no_end is required"
        )
    if page_no_end is not None and page_no is None:
        raise ValueError("page_no_end requires page_no")
    if pdf_page_no_end is not None and pdf_page_no is None:
        raise ValueError("pdf_page_no_end requires pdf_page_no")
    if page_no is not None and page_no_end is not None and page_no_end < page_no:
        raise ValueError("page_no_end must be greater than or equal to page_no")
    if pdf_page_no is not None and pdf_page_no_end is not None and pdf_page_no_end < pdf_page_no:
        raise ValueError("pdf_page_no_end must be greater than or equal to pdf_page_no")

    pages = payload.get("pages") or []
    selected: list[dict[str, Any]] = []
    for page in pages:
        current_page_no = int(page.get("page_no") or 0)
        current_pdf_page_no = int(page.get("pdf_page_no") or current_page_no)

        matches = True
        if page_no is not None:
            page_no_upper = page_no_end if page_no_end is not None else page_no
            if not (page_no <= current_page_no <= page_no_upper):
                matches = False
        if pdf_page_no is not None:
            pdf_page_upper = pdf_page_no_end if pdf_page_no_end is not None else pdf_page_no
            if not (pdf_page_no <= current_pdf_page_no <= pdf_page_upper):
                matches = False
        if not matches:
            continue

        page_text = str(page.get("text") or "").strip()
        if not page_text:
            paragraphs = page.get("paragraphs") or []
            page_text = "\n\n".join(
                str(paragraph.get("text") or "").strip()
                for paragraph in paragraphs
                if str(paragraph.get("text") or "").strip()
            ).strip()

        selected.append(
            {
                "page_no": current_page_no,
                "pdf_page_no": current_pdf_page_no,
                "book_page_no": page.get("book_page_no"),
                "page_number_source": str(page.get("page_number_source") or "pdf"),
                "page_meta": page.get("meta") or {},
                "text": page_text,
            }
        )

    return selected


def extract_paragraph_location(
    *,
    payload: dict[str, Any],
    page_no: int | None = None,
    pdf_page_no: int | None = None,
    paragraph_no: int | None = None,
) -> dict[str, Any] | None:
    """Extract one paragraph payload for citation/highlight routes."""
    if page_no is None and pdf_page_no is None and paragraph_no is None:
        raise ValueError("At least one of page_no, pdf_page_no, or paragraph_no is required")

    pages = payload.get("pages") or []
    first_match_on_page: dict[str, Any] | None = None

    for page in pages:
        current_page_no = int(page.get("page_no") or 0)
        current_pdf_page_no = int(page.get("pdf_page_no") or current_page_no)

        if page_no is not None and current_page_no != page_no:
            continue
        if pdf_page_no is not None and current_pdf_page_no != pdf_page_no:
            continue

        page_context = {
            "page_no": current_page_no,
            "pdf_page_no": current_pdf_page_no,
            "book_page_no": page.get("book_page_no"),
            "page_number_source": str(page.get("page_number_source") or "pdf"),
            "page_meta": page.get("meta") or {},
        }
        paragraphs = page.get("paragraphs") or []
        for paragraph in paragraphs:
            candidate = {
                **page_context,
                **paragraph,
            }
            if first_match_on_page is None:
                first_match_on_page = candidate
            if paragraph_no is None:
                continue
            if int(paragraph.get("paragraph_no") or 0) == paragraph_no:
                return candidate

        if paragraph_no is None and first_match_on_page is not None:
            return first_match_on_page

    return first_match_on_page if paragraph_no is None else None
