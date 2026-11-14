import json
import logging
import mimetypes
import threading
import time
from collections.abc import Generator
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

from src.community.knowledge_base.book_metadata import (
    MetadataField,
    build_book_metadata_prompt_input,
    build_book_metadata_record,
    derive_book_metadata_filename,
    get_book_metadata_dir,
    load_book_metadata_for_source,
    normalize_folder_path,
    resolve_book_folder,
    save_book_metadata,
)
from src.community.knowledge_base.book_metadata_runtime import (
    build_existing_folder_tree,
    generate_book_metadata_record,
    maybe_generate_book_metadata,
)
from src.community.knowledge_base.catalog import list_book_catalog
from src.community.knowledge_base.citations import (
    encode_source_url,
    resolve_result_citation_context,
)
from src.community.knowledge_base.common import derive_global_doc_id, resolve_project_path
from src.community.knowledge_base.document_parsers import OFFICE_EXTENSIONS, PDF_EXTENSIONS
from src.community.knowledge_base.folder_registry import (
    delete_folder_path,
    ensure_folder_path,
    ensure_folder_paths,
    list_folder_paths,
    rename_folder_path,
    render_folder_tree,
)
from src.community.knowledge_base.indexer import (
    delete_global_knowledge_documents,
)
from src.community.knowledge_base.locator import extract_paragraph_location, locate_document
from src.community.knowledge_base.mineru_grpc import build_structured_document_from_mineru_grpc
from src.community.knowledge_base.retriever import get_qdrant_client, get_retriever
from src.community.knowledge_base.structured_document import (
    build_bbox_from_position,
    build_structured_document,
    load_structured_document,
    save_structured_document,
)
from src.community.knowledge_base.tools import knowledge_search_tool
from src.community.knowledge_base.translation_grpc import translate_blocks_to_chinese_via_grpc
from src.config.knowledge_base_config import get_knowledge_base_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge-base"])
logger = logging.getLogger(__name__)

UPLOAD_CHUNK_SIZE = 1024 * 1024

INDEXABLE_EXTENSIONS = {".md", ".txt"}

# Recovery is opinionated: we re-queue anything that a prior process left
# mid-flight, including ``parsing`` (the worker died mid-OCR) and ``failed``
# (transient gRPC outage, container restart, etc.). To avoid burning gRPC time
# on genuinely corrupt PDFs, ``failed`` records are auto-recovered at most
# ``MAX_FAILED_RETRIES`` total failures — past that the UI's manual retry
# button must be hit (which resets the counter).
RECOVERABLE_PARSE_STATUSES = frozenset(
    {"queued", "queued_ocr", "pending_parse", "parsing", "failed"}
)
MAX_FAILED_RETRIES = 3

_knowledge_operation_lock = threading.Lock()
_global_inflight_lock = threading.Lock()
_global_inflight_ocr: set[str] = set()
_UNSET: object = object()
# Limits concurrent disk-heavy phases (file read + JSON write) independently of
# the total OCR worker count. Workers waiting for gRPC responses (remote OCR) do
# not hold this semaphore, so the disk stays free for the next worker's read/write.
_disk_io_semaphore: threading.Semaphore | None = None
_disk_io_semaphore_lock = threading.Lock()


def _get_disk_io_semaphore() -> threading.Semaphore:
    global _disk_io_semaphore
    with _disk_io_semaphore_lock:
        if _disk_io_semaphore is None:
            workers = _resolve_ocr_max_workers()
            slots = 2
            _disk_io_semaphore = threading.Semaphore(slots)
    return _disk_io_semaphore
# Two executors so startup-recovery work cannot starve fresh user uploads:
#   * ``_global_ocr_executor`` — high priority, sized by
#     ``mineru.max_concurrent_ocr_jobs``. Receives uploads / manual retries.
#   * ``_recovery_ocr_executor`` — low priority, single worker. Drains the
#     backlog of ``parsing`` / ``queued_ocr`` / ``failed`` records left by a
#     prior process without blocking new requests.
_global_ocr_executor: ThreadPoolExecutor | None = None
_global_ocr_executor_workers: int = 0
_recovery_ocr_executor: ThreadPoolExecutor | None = None


def _encode_url_path(url: str | None) -> str | None:
    return encode_source_url(url)


def _acquire_knowledge_operation_lock() -> None:
    if not _knowledge_operation_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="Another knowledge-base operation is already in progress. Please wait for it to finish.",
        )


def _release_knowledge_operation_lock() -> None:
    if _knowledge_operation_lock.locked():
        _knowledge_operation_lock.release()


def _remove_global_queued_filename(filename: str) -> None:
    """Allow the same filename to be resubmitted.

    The executor cannot cancel a task that is already mid-flight, but clearing
    the inflight marker lets a subsequent ``_submit_global_ocr`` call enqueue a
    fresh run (mirrors the previous deque-based behaviour).
    """
    with _global_inflight_lock:
        _global_inflight_ocr.discard(filename)


def _resolve_ocr_max_workers() -> int:
    try:
        mineru_config = get_knowledge_base_config().mineru
    except Exception:  # pragma: no cover - defensive: config not loaded yet
        return 4
    if mineru_config is None:
        return 4
    return max(1, int(getattr(mineru_config, "max_concurrent_ocr_jobs", 4) or 4))


def _ensure_global_queue_workers_started() -> None:
    """Lazily create the OCR executor and recover any pending records."""
    global _global_ocr_executor, _global_ocr_executor_workers
    started = False
    with _global_inflight_lock:
        if _global_ocr_executor is None:
            _global_ocr_executor_workers = _resolve_ocr_max_workers()
            _global_ocr_executor = ThreadPoolExecutor(
                max_workers=_global_ocr_executor_workers,
                thread_name_prefix="global-ocr",
            )
            started = True
    # Recovery disabled: OCR is run locally via scripts/local_ocr.py.
    # Pending records are left in their current status; use the UI retry
    # button or re-upload to reprocess individual files.


def _submit_global_ocr(filename: str) -> None:
    """Submit a file for OCR processing.

    The ThreadPoolExecutor caps concurrent gRPC calls at
    ``mineru.max_concurrent_ocr_jobs``; anything beyond that waits in the
    executor's own work queue. Duplicate submissions for the same filename are
    ignored while one is still inflight.
    """
    _ensure_global_queue_workers_started()
    with _global_inflight_lock:
        if filename in _global_inflight_ocr:
            logger.info(
                "[ocr-task] %s SUBMIT skipped: already inflight (inflight=%s)",
                filename,
                len(_global_inflight_ocr),
            )
            return
        _global_inflight_ocr.add(filename)
        executor = _global_ocr_executor
        inflight_after = len(_global_inflight_ocr)
    assert executor is not None  # _ensure_global_queue_workers_started guarantees it
    logger.info(
        "[ocr-task] %s SUBMIT accepted (inflight=%s, workers=%s)",
        filename,
        inflight_after,
        _global_ocr_executor_workers,
    )
    future = executor.submit(_run_global_ocr_task, filename)
    # ThreadPoolExecutor silently swallows exceptions raised inside the worker
    # if no one calls ``Future.result()``. Attach a callback so any unhandled
    # exception from ``_run_global_ocr_task`` shows up in logs instead of
    # disappearing into the void. Tolerate stubs (used in tests) whose
    # ``submit`` returns ``None``.
    if future is not None and hasattr(future, "add_done_callback"):
        def _log_future_outcome(fut: "Future[None]", _filename: str = filename) -> None:
            exc = fut.exception()
            if exc is not None:
                logger.error(
                    "[ocr-task] %s WORKER raised uncaught exception: %s: %s",
                    _filename,
                    type(exc).__name__,
                    exc,
                    exc_info=exc,
                )

        future.add_done_callback(_log_future_outcome)


def _run_global_ocr_task(filename: str) -> None:
    started_at = time.monotonic()
    logger.info("[ocr-task] %s WORKER picked up task (start)", filename)
    try:
        _process_single_global_ocr(filename)
        logger.info(
            "[ocr-task] %s WORKER finished cleanly in %.2fs",
            filename,
            time.monotonic() - started_at,
        )
    except BaseException as exc:
        # ``_process_single_global_ocr`` already wraps its OCR/parse phase in a
        # try/except, but pre- and post-OCR steps (load record, initial save,
        # final save) are NOT wrapped. Anything escaping from those must still
        # be marked on the record AND surfaced in logs — otherwise the file
        # silently disappears from view.
        logger.exception(
            "[ocr-task] %s WORKER unexpected exception after %.2fs: %s",
            filename,
            time.monotonic() - started_at,
            exc,
        )
        try:
            record = _load_global_record(filename) or {}
            record = _mark_global_record_failed(
                record,
                f"worker crashed: {type(exc).__name__}: {exc}",
            )
            _save_global_record(filename, record)
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "[ocr-task] %s failed to persist failure record after worker crash",
                filename,
            )
        raise
    finally:
        with _global_inflight_lock:
            _global_inflight_ocr.discard(filename)
            inflight_after = len(_global_inflight_ocr)
        logger.info(
            "[ocr-task] %s WORKER inflight marker released (remaining inflight=%s)",
            filename,
            inflight_after,
        )


def _recover_pending_global_jobs() -> None:
    """Re-queue any documents the previous process left mid-flight.

    Catches:
    - ``queued`` / ``queued_ocr`` / ``pending_parse``: never started
    - ``parsing``: worker died mid-OCR, no one will finish it
    - ``failed``: previous attempt errored — give it up to ``MAX_FAILED_RETRIES``
      total tries before requiring manual intervention

    For ``parsing`` / ``failed`` records we also normalise the status back to
    ``queued_ocr`` so the UI and listing endpoints reflect reality (otherwise
    a ``parsing`` record sits there forever pretending work is in progress).
    """
    recovered = 0
    skipped_failed = 0
    for record in _list_global_records():
        filename = record.get("source_filename")
        if not filename or not record.get("indexable"):
            continue
        status = str(record.get("parse_status") or "")
        if status not in RECOVERABLE_PARSE_STATUSES:
            continue
        if status == "failed":
            retry_count = int(record.get("retry_count") or 0)
            if retry_count >= MAX_FAILED_RETRIES:
                skipped_failed += 1
                continue
        # Normalise the status before resubmission so listing endpoints stop
        # claiming "still parsing" for a record whose worker is long gone.
        if status in {"parsing", "failed", "queued"}:
            record["parse_status"] = "queued_ocr"
            record["error"] = None
            _save_global_record(str(filename), record)
        _submit_global_ocr(str(filename))
        recovered += 1
    if recovered or skipped_failed:
        logger.info(
            "Global OCR recovery scan complete: resubmitted=%s skipped_failed_at_cap=%s",
            recovered,
            skipped_failed,
        )


def _current_global_queue_positions() -> dict[str, int]:
    """Return inflight filenames.

    Precise queue positions are no longer tracked (the executor owns the
    pending queue). All entries report position ``1`` so callers can still
    detect "this file is being processed / waiting" without exposing internal
    queue ordering. The frontend only renders the status label, so this is
    sufficient.
    """
    with _global_inflight_lock:
        return {filename: 1 for filename in _global_inflight_ocr}


def bootstrap_global_ocr_recovery() -> None:
    """Run once at process startup to resume any in-flight OCR work.

    Recovery is normally lazy — it triggers the first time something is
    submitted. That means a freshly-deployed process which received no uploads
    would leave previously-queued docs stuck. This entry point makes recovery
    eager so users do not need to manually poke the system after a redeploy.
    """
    try:
        config = get_knowledge_base_config()
    except Exception:
        logger.exception("Failed to load knowledge base config during OCR recovery bootstrap")
        return
    if not getattr(config, "enabled", False):
        logger.info("Knowledge base disabled; skipping global OCR recovery bootstrap")
        return
    try:
        _ensure_global_queue_workers_started()
        logger.info("Global OCR recovery bootstrap completed")
    except Exception:
        logger.exception("Global OCR recovery bootstrap failed")


class KnowledgeBaseStatus(BaseModel):
    """Response model for knowledge base status."""
    enabled: bool
    doc_count: int
    collection_name: str
    docs_path: str


class SearchResult(BaseModel):
    """Response model for search result."""
    content: str
    score: float
    filename: str
    source: str
    line_start: int | None = None
    line_end: int | None = None
    page_no: int | None = None
    pdf_page_no: int | None = None
    book_page_no: int | None = None
    paragraph_no: int | None = None
    bbox: dict[str, float] | None = None
    source_url: str | None = None
    original_url: str | None = None
    page: int | None = None
    source_type: str = "unknown"


class SearchResponse(BaseModel):
    """Response model for search operation."""
    query: str
    results: list[SearchResult]


class KnowledgeDebugBookInfo(BaseModel):
    doc_id: str
    title: str
    filename: str
    scope: str
    folder: str | None = None
    summary: str | None = None
    language_hint: str | None = None
    parse_status: str | None = None
    indexable: bool = False
    modified: float | None = None


class KnowledgeDebugBooksResponse(BaseModel):
    books: list[KnowledgeDebugBookInfo]
    count: int


class KnowledgeDebugSearchRequest(BaseModel):
    query: str
    doc_ids: list[str]
    top_k: int = 8


class KnowledgeDebugSearchResult(BaseModel):
    content: str
    score: float
    filename: str
    title: str | None = None
    doc_id: str | None = None
    scope: str | None = None
    source: str
    source_kind: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    page_no: int | None = None
    pdf_page_no: int | None = None
    book_page_no: int | None = None
    paragraph_no: int | None = None
    matched_keywords: list[str] | None = None
    source_url: str | None = None
    original_url: str | None = None


class KnowledgeDebugQdrantResponse(BaseModel):
    query: str
    doc_ids: list[str]
    top_k: int
    elapsed_ms: float
    results: list[KnowledgeDebugSearchResult]


class KnowledgeDebugToolResponse(BaseModel):
    query: str
    doc_ids: list[str]
    elapsed_ms: float
    output: str


class KnowledgeParagraphLocationResponse(BaseModel):
    doc_id: str | None = None
    scope: str | None = None
    filename: str
    title: str
    page_count: int | None = None
    page_no: int | None = None
    pdf_page_no: int | None = None
    book_page_no: int | None = None
    paragraph_no: int | None = None
    bbox: dict[str, float] | None = None
    page_meta: dict[str, Any] | None = None
    text: str
    source_url: str | None = None
    original_url: str | None = None


class KnowledgeUploadResponse(BaseModel):
    """Response model for global knowledge upload operations."""

    success: bool
    files: list[dict[str, Any]]
    message: str


class UploadKnowledgeDocumentResponse(BaseModel):
    """Compatibility response model for settings-page uploads."""

    status: str
    message: str
    filename: str
    markdown_filename: str | None = None


class KnowledgeDocumentInfo(BaseModel):
    """Compatibility metadata model for settings-page document listing."""

    filename: str
    size: int
    modified: float
    extension: str


class KnowledgeDocumentListResponse(BaseModel):
    """Compatibility response model for settings-page document listing."""

    docs: list[KnowledgeDocumentInfo]


class KnowledgeMetadataUpdateRequest(BaseModel):
    type: str | None = None
    folder: str | None = None
    categories: list[str] | None = None
    eras: list[str] | None = None
    regions: list[str] | None = None
    keywords: list[str] | None = None
    summary: str | None = None
    author: str | None = None
    publisher: str | None = None
    language_hint: str | None = None
    layout_hint: str | None = None
    document_type_hint: str | None = None


class FolderMutationRequest(BaseModel):
    path: str
    new_path: str | None = None


class FolderMoveRequest(BaseModel):
    """Move a folder under a new parent, keeping its own name.

    Example: ``FolderMoveRequest(path="history/ancient", target_parent="geography")``
    results in ``geography/ancient``.  Set ``target_parent`` to ``null`` or omit it
    to promote the folder to the root level.
    """

    path: str
    target_parent: str | None = None


class FolderMergeRequest(BaseModel):
    """Merge ``source_path`` into ``target_path``.

    All books directly in ``source_path`` are reassigned to ``target_path``.
    Books in ``source_path/sub`` are reassigned to ``target_path/sub``
    (sub-tree structure is preserved).  The source folder is deleted from
    the registry after the move.
    """

    source_path: str
    target_path: str


class FolderReorganizeRequest(BaseModel):
    """Request to AI-analyze and auto-reorganize the knowledge folder tree."""

    model_name: str | None = None
    """LLM model to use for analysis. Defaults to the first model in config."""

    focus_path: str | None = None
    """Limit analysis to a sub-tree (e.g. ``"历史"``). Omit to analyze the entire tree."""


class TranslationBlockRequest(BaseModel):
    key: str
    text: str


class TranslateBlocksRequest(BaseModel):
    paragraphs: list[TranslationBlockRequest]
    source_language_hint: str | None = None


def _build_structured_page_payload(document: Any, *, page_no: int | None, pdf_page_no: int | None) -> dict[str, Any] | None:
    for page in document.payload.get("pages") or []:
        current_page_no = int(page.get("page_no") or 0)
        current_pdf_page_no = int(page.get("pdf_page_no") or current_page_no)
        if page_no is not None and current_page_no != page_no:
            continue
        if pdf_page_no is not None and current_pdf_page_no != pdf_page_no:
            continue
        return {
            "doc_id": document.doc_id,
            "scope": document.scope,
            "filename": document.filename,
            "title": document.title,
            "layout_hint": (document.payload.get("hints") or {}).get("layout_hint"),
            "page_count": len(list(document.payload.get("pages") or [])),
            "page_no": page.get("page_no"),
            "pdf_page_no": page.get("pdf_page_no"),
            "book_page_no": page.get("book_page_no"),
            "page_number_source": page.get("page_number_source"),
            "page_meta": page.get("meta") or {},
            "paragraphs": [
                {
                    **paragraph,
                    "bbox": paragraph.get("bbox") or build_bbox_from_position(paragraph.get("position")),
                }
                for paragraph in page.get("paragraphs") or []
            ],
            "source_url": _encode_url_path(document.source_url),
            "original_url": _encode_url_path(document.original_url),
        }
    return None


async def save_upload_file(file: UploadFile, destination: Path, chunk_size: int = UPLOAD_CHUNK_SIZE) -> int:
    """Stream an uploaded file to disk and return its size in bytes."""
    size = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as buffer:
        while chunk := await file.read(chunk_size):
            buffer.write(chunk)
            size += len(chunk)
    await file.close()
    return size


def get_global_docs_dir() -> Path:
    """Resolve and create the global knowledge docs directory."""
    docs_dir = resolve_project_path(get_knowledge_base_config().docs_path)
    docs_dir.mkdir(parents=True, exist_ok=True)
    return docs_dir


def get_global_ingestion_dir() -> Path:
    """Directory storing ingestion metadata for global uploads."""
    ingestion_dir = get_global_docs_dir() / ".ingestion"
    ingestion_dir.mkdir(parents=True, exist_ok=True)
    return ingestion_dir


def _global_folder_registry_path() -> Path:
    return get_global_docs_dir() / ".folders.json"


def _global_record_path(filename: str) -> Path:
    return get_global_ingestion_dir() / f"{filename}.json"


def _save_global_record(filename: str, record: dict[str, Any]) -> None:
    _global_record_path(filename).write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_global_record(filename: str) -> dict[str, Any] | None:
    path = _global_record_path(filename)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _list_global_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(get_global_ingestion_dir().glob("*.json")):
        # Skip large structured-document files by filename — they can be tens of MB
        # each and are always schema_version=1 (never ingestion records).
        if ".structured." in path.name or path.name.endswith(".resolved"):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("schema_version") == 1:
                continue
            records.append(payload)
        except Exception:
            continue
    return records


def _build_global_record_lookup() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_source: dict[str, dict[str, Any]] = {}
    by_index_target: dict[str, dict[str, Any]] = {}
    for record in _list_global_records():
        source_filename = record.get("source_filename")
        if source_filename:
            by_source[source_filename] = record
        index_target_filename = record.get("index_target_filename")
        if index_target_filename:
            by_index_target[index_target_filename] = record
    return by_source, by_index_target


def _remove_global_record(filename: str) -> None:
    path = _global_record_path(filename)
    if path.exists():
        path.unlink()


def _find_global_record(filename: str) -> dict[str, Any] | None:
    record = _load_global_record(filename)
    if record:
        return record
    for candidate in _list_global_records():
        if candidate.get("index_target_filename") == filename:
            return candidate
    return None


def _build_global_urls(filename: str) -> dict[str, str]:
    return {
        "source_url": f"/api/knowledge/docs/{filename}",
    }


def _metadata_value(field: MetadataField | None) -> str | None:
    if field is None:
        return None
    value = str(field.value or "").strip()
    return value or None


def _metadata_values(fields: list[MetadataField] | None) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for field in fields or []:
        value = _metadata_value(field)
        if not value or value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def _resolve_metadata_folder(
    suggestion: Any | None,
    *,
    fallback_tags: list[str] | None = None,
) -> str:
    folder = resolve_book_folder(suggestion)
    if folder:
        return folder
    for tag in fallback_tags or []:
        normalized = normalize_folder_path(tag)
        if normalized:
            return normalized
    return "未分类"


def _manual_metadata_field(value: str | None) -> MetadataField | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return MetadataField(value=normalized, confidence=1.0, evidence="manual_edit")


def _manual_metadata_fields(values: list[str] | None) -> list[MetadataField]:
    fields: list[MetadataField] = []
    seen: set[str] = set()
    for raw in values or []:
        normalized = str(raw or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        fields.append(MetadataField(value=normalized, confidence=1.0, evidence="manual_edit"))
    return fields


def _load_global_book_metadata(filename: str, ingestion_record: dict[str, Any] | None | object = _UNSET) -> dict[str, Any]:
    record = load_book_metadata_for_source(get_global_docs_dir(), filename)
    if ingestion_record is _UNSET:
        ingestion_record = _find_global_record(filename)
    suggestion = record.suggestion if record else None
    book_type = _metadata_value(suggestion.type) if suggestion else None
    categories = _metadata_values(suggestion.categories) if suggestion else []
    eras = _metadata_values(suggestion.eras) if suggestion else []
    regions = _metadata_values(suggestion.regions) if suggestion else []
    keywords = _metadata_values(suggestion.keywords) if suggestion else []
    summary = _metadata_value(suggestion.summary) if suggestion else None
    tags: list[str] = []
    for value in [*categories, *eras, *regions, *keywords]:
        if value and value not in tags:
            tags.append(value)
    folder = normalize_folder_path((ingestion_record or {}).get("folder_path")) or _resolve_metadata_folder(
        suggestion,
        fallback_tags=tags,
    )
    return {
        "type": book_type,
        "folder": folder,
        "categories": categories,
        "eras": eras,
        "regions": regions,
        "keywords": keywords,
        "summary": summary,
        "author": _metadata_value(suggestion.author) if suggestion else None,
        "publisher": _metadata_value(suggestion.publisher) if suggestion else None,
        "tags": tags,
        "language_hint": (ingestion_record or {}).get("hints", {}).get("language_hint"),
        "layout_hint": (ingestion_record or {}).get("hints", {}).get("layout_hint"),
        "document_type_hint": (ingestion_record or {}).get("hints", {}).get("document_type_hint"),
    }


def _list_global_folder_paths(files: list[dict[str, Any]] | None = None) -> list[str]:
    explicit_folders = list_folder_paths(_global_folder_registry_path())
    implicit_folders = [item.get("folder") for item in files or []]
    return ensure_folder_paths(_global_folder_registry_path(), [*explicit_folders, *implicit_folders])


def _load_structured_payload_for_metadata(filename: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None, Path]:
    record = _find_global_record(filename)
    docs_dir = get_global_docs_dir()
    file_path = docs_dir / filename

    if record is None and not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    structured_payload = None
    if record:
        raw_path = record.get("structured_path") or (
            str(get_global_ingestion_dir() / record["structured_filename"])
            if record.get("structured_filename")
            else None
        )
        if raw_path:
            structured_payload = load_structured_document(Path(raw_path))
    elif file_path.suffix.lower() in INDEXABLE_EXTENSIONS:
        structured_payload = build_structured_document(
            source_filename=filename,
            title=Path(filename).stem,
            text=file_path.read_text(encoding="utf-8"),
            parser_name="manual_metadata_edit",
            hints={},
        )

    return structured_payload, record, docs_dir


def _build_debug_search_result(
    result: dict[str, Any],
    *,
    thread_id: str | None = None,
    user_id: str | None = None,
) -> KnowledgeDebugSearchResult:
    metadata = result.get("metadata", {})
    citation_context = resolve_result_citation_context(
        result,
        thread_id=thread_id,
        user_id=user_id,
    )
    return KnowledgeDebugSearchResult(
        content=str(result.get("content") or ""),
        score=float(result.get("score") or 0.0),
        filename=str(result.get("filename") or metadata.get("filename") or "Unknown"),
        title=metadata.get("title"),
        doc_id=metadata.get("origin_doc_id") or metadata.get("doc_id"),
        scope=metadata.get("scope"),
        source=str(result.get("source") or metadata.get("source") or "Unknown"),
        source_kind=metadata.get("source_kind"),
        line_start=metadata.get("line_start"),
        line_end=metadata.get("line_end"),
        page_no=metadata.get("page_no"),
        pdf_page_no=metadata.get("pdf_page_no"),
        book_page_no=metadata.get("book_page_no"),
        paragraph_no=metadata.get("paragraph_no"),
        matched_keywords=[
            str(item)
            for item in result.get("matched_keywords") or []
            if str(item).strip()
        ]
        or None,
        source_url=citation_context["source_url"],
        original_url=citation_context["original_url"],
    )


def _cleanup_global_record_artifacts(record: dict[str, Any], *, remove_source_file: bool) -> None:
    docs_dir = get_global_docs_dir()
    source_filename = record.get("source_filename")
    if remove_source_file and source_filename:
        source_path = docs_dir / str(source_filename)
        if source_path.exists():
            source_path.unlink()

    structured_path = record.get("structured_path")
    if structured_path:
        candidate = Path(str(structured_path))
        if candidate.exists():
            candidate.unlink()

    preview_filename = record.get("preview_filename")
    if preview_filename and preview_filename not in {record.get("source_filename"), record.get("index_target_filename")}:
        preview_path = docs_dir / str(preview_filename)
        if preview_path.exists():
            preview_path.unlink()

    if source_filename:
        book_meta_path = get_book_metadata_dir(docs_dir) / derive_book_metadata_filename(str(source_filename))
        if book_meta_path.exists():
            book_meta_path.unlink()


def _build_global_ingestion_record(
    filename: str,
    size: int,
    content_type: str | None,
    hints: dict[str, str],
    folder_path: str | None = None,
) -> dict[str, Any]:
    suffix = Path(filename).suffix.lower()
    parse_method = "binary_only"
    indexable = False
    if suffix in INDEXABLE_EXTENSIONS or suffix in PDF_EXTENSIONS or suffix in OFFICE_EXTENSIONS:
        parse_method = "ocr_pdf_mineru_grpc"
        indexable = True

    urls = _build_global_urls(filename)
    return {
        "source_filename": filename,
        "display_title": Path(filename).stem,
        "source_extension": suffix,
        "source_size": size,
        "content_type": content_type,
        "parse_method": parse_method,
        "parse_status": "queued_ocr" if indexable else "uploaded",
        "indexable": indexable,
        "source_artifact_url": urls["source_url"],
        "preview_filename": filename if suffix in INDEXABLE_EXTENSIONS else None,
        "preview_artifact_url": urls["source_url"] if suffix in INDEXABLE_EXTENSIONS else None,
        "structured_filename": None,
        "structured_path": None,
        "structured_artifact_url": None,
        "index_target_filename": None,
        "index_target_path": None,
        "index_target_artifact_url": None,
        "index_target_format": None,
        "hints": hints,
        "folder_path": normalize_folder_path(folder_path),
        "error": None,
        "replace_existing_index": False,
    }


def _mark_global_record_parsed(
    record: dict[str, Any],
    *,
    structured_filename: str,
    structured_path: str,
    preview_filename: str | None = None,
) -> dict[str, Any]:
    record.update(
        {
            "parse_status": "parsed",
            "structured_filename": structured_filename,
            "structured_path": structured_path,
            "structured_artifact_url": None,
            "index_target_filename": structured_filename,
            "index_target_path": structured_path,
            "index_target_artifact_url": None,
            "index_target_format": "structured_json",
            "error": None,
        }
    )
    if preview_filename:
        record["preview_filename"] = preview_filename
        record["preview_artifact_url"] = _build_global_urls(preview_filename)["source_url"]
    return record


def _mark_global_record_failed(record: dict[str, Any], error: str) -> dict[str, Any]:
    previous_retry_count = int(record.get("retry_count") or 0)
    record.update(
        {
            "parse_status": "failed",
            "structured_filename": None,
            "structured_path": None,
            "structured_artifact_url": None,
            "index_target_filename": None,
            "index_target_path": None,
            "index_target_artifact_url": None,
            "index_target_format": None,
            "error": error,
            # Bumped every time a parse attempt fails. Capped by
            # ``MAX_FAILED_RETRIES`` during restart recovery so corrupt PDFs do
            # not loop forever; manual retry / reparse resets it to 0.
            "retry_count": previous_retry_count + 1,
        }
    )
    return record


def _mark_global_record_pending(record: dict[str, Any], error: str) -> dict[str, Any]:
    record.update(
        {
            "parse_status": "pending_parse",
            "structured_filename": None,
            "structured_path": None,
            "structured_artifact_url": None,
            "index_target_filename": None,
            "index_target_path": None,
            "index_target_artifact_url": None,
            "index_target_format": None,
            "error": error,
        }
    )
    return record


def _process_single_global_ocr(filename: str) -> None:
    logger.info("[ocr-step] %s STEP 1: loading record", filename)
    docs_dir = get_global_docs_dir()
    ingestion_dir = get_global_ingestion_dir()
    metadata_config = get_knowledge_base_config().book_metadata
    record = _load_global_record(filename)
    if not record:
        logger.warning("[ocr-step] %s ABORT: record not found in ingestion dir", filename)
        return
    if not record.get("indexable"):
        logger.warning(
            "[ocr-step] %s ABORT: record.indexable=False (parse_status=%s)",
            filename,
            record.get("parse_status"),
        )
        return

    file_path = docs_dir / filename
    if not file_path.exists():
        logger.error("[ocr-step] %s ABORT: source file missing on disk: %s", filename, file_path)
        record = _mark_global_record_failed(record, "source file missing")
        _save_global_record(filename, record)
        return

    record["parse_status"] = "parsing"
    record["error"] = None
    _save_global_record(filename, record)
    logger.info("[ocr-step] %s STEP 2: marked parsing, status saved", filename)

    try:
        file_ext = file_path.suffix.lower()
        if file_ext in PDF_EXTENSIONS or file_ext in OFFICE_EXTENSIONS or file_ext in INDEXABLE_EXTENSIONS:
            hints = record.get("hints") or {}
            record["parse_method"] = "ocr_pdf_mineru_grpc"
            _save_global_record(filename, record)

            disk_sem = _get_disk_io_semaphore()

            # Phase 1: read file from disk (gated — limits concurrent reads)
            logger.info("[ocr-step] %s STEP 3a: waiting for disk-read slot", filename)
            with disk_sem:
                logger.info("[ocr-step] %s STEP 3b: reading file from disk (%s bytes)", filename, file_path.stat().st_size)
                file_content = file_path.read_bytes()

            # Phase 2: remote OCR via gRPC (ungated — disk is free while we wait)
            logger.info("[ocr-step] %s STEP 3c: calling MinerU gRPC (file_ext=%s)", filename, file_ext)
            structured_payload = build_structured_document_from_mineru_grpc(
                file_path,
                title=record["display_title"],
                parser_name=record["parse_method"],
                hints=hints,
                language_hint=hints.get("language_hint"),
                file_content=file_content,
            )
            del file_content  # release memory before acquiring disk semaphore again

            # Phase 3: write structured JSON to disk (gated — limits concurrent writes)
            logger.info(
                "[ocr-step] %s STEP 4a: gRPC returned payload (pages=%s); waiting for disk-write slot",
                filename,
                len((structured_payload or {}).get("pages") or []),
            )
            with disk_sem:
                logger.info("[ocr-step] %s STEP 4b: writing structured JSON", filename)
                structured_path = save_structured_document(
                    ingestion_dir,
                    filename,
                    structured_payload,
                )
            logger.info(
                "[ocr-step] %s STEP 5: structured JSON written to %s; generating book metadata",
                filename,
                structured_path,
            )
            maybe_generate_book_metadata(
                structured_payload=structured_payload,
                source_filename=filename,
                title=record["display_title"],
                output_dir=docs_dir,
                config=metadata_config,
            )
            logger.info("[ocr-step] %s STEP 6: book metadata done; marking parsed", filename)
            record = _mark_global_record_parsed(
                record,
                structured_filename=structured_path.name,
                structured_path=str(structured_path),
                preview_filename=filename if file_ext in INDEXABLE_EXTENSIONS else None,
            )
        else:
            logger.info(
                "[ocr-step] %s STEP 3 (alt): non-parseable extension %s, marking uploaded",
                filename,
                file_ext,
            )
            record["parse_status"] = "uploaded"

        _save_global_record(filename, record)
        logger.info("[ocr-step] %s STEP 7: final record saved (parse_status=%s)", filename, record.get("parse_status"))
    except Exception as exc:
        logger.exception("[ocr-step] %s FAILED inside try block: %s", filename, exc)
        record = _mark_global_record_failed(record, f"parse failed: {exc}")
        _save_global_record(filename, record)


def _process_global_knowledge_uploads(filenames: list[str]) -> None:
    """Parse uploaded global knowledge files in the background."""
    try:
        docs_dir = get_global_docs_dir()
        ingestion_dir = get_global_ingestion_dir()
        metadata_config = get_knowledge_base_config().book_metadata

        for safe_filename in filenames:
            record = _load_global_record(safe_filename)
            if not record:
                logger.warning("Global ingestion record missing for %s", safe_filename)
                continue

            file_path = docs_dir / safe_filename
            if not file_path.exists():
                record = _mark_global_record_failed(record, "source file missing")
                _save_global_record(safe_filename, record)
                continue

            record["parse_status"] = "parsing"
            record["error"] = None
            _save_global_record(safe_filename, record)

            try:
                file_ext = file_path.suffix.lower()
                if file_ext in PDF_EXTENSIONS or file_ext in OFFICE_EXTENSIONS or file_ext in INDEXABLE_EXTENSIONS:
                    hints = record.get("hints") or {}
                    record["parse_method"] = "ocr_pdf_mineru_grpc"
                    _save_global_record(safe_filename, record)
                    structured_payload = build_structured_document_from_mineru_grpc(
                        file_path,
                        title=record["display_title"],
                        parser_name=record["parse_method"],
                        hints=hints,
                        language_hint=hints.get("language_hint"),
                    )
                    structured_path = save_structured_document(
                        ingestion_dir,
                        safe_filename,
                        structured_payload,
                    )
                    maybe_generate_book_metadata(
                        structured_payload=structured_payload,
                        source_filename=safe_filename,
                        title=record["display_title"],
                        output_dir=docs_dir,
                        config=metadata_config,
                    )
                    record = _mark_global_record_parsed(
                        record,
                        structured_filename=structured_path.name,
                        structured_path=str(structured_path),
                        preview_filename=safe_filename if file_ext in INDEXABLE_EXTENSIONS else None,
                    )
                else:
                    record["parse_status"] = "uploaded"
            except Exception as exc:
                logger.exception("Failed to parse global upload %s: %s", safe_filename, exc)
                record = _mark_global_record_failed(record, f"parse failed: {exc}")

            _save_global_record(safe_filename, record)
    finally:
        _release_knowledge_operation_lock()


@router.get("/status", response_model=KnowledgeBaseStatus, summary="Get Knowledge Base Status")
def get_status() -> KnowledgeBaseStatus:
    """Get the current status of the knowledge base."""
    config = get_knowledge_base_config()
    
    if not config.enabled:
        return KnowledgeBaseStatus(
            enabled=False,
            doc_count=0,
            collection_name=config.qdrant.collection_name,
            docs_path=config.docs_path
        )

    # Count vectors in Qdrant collection
    try:
        client = get_qdrant_client()
        collection_info = client.get_collection(config.qdrant.collection_name)
        doc_count = collection_info.points_count
    except Exception:
        doc_count = 0

    return KnowledgeBaseStatus(
        enabled=True,
        doc_count=doc_count,
        collection_name=config.qdrant.collection_name,
        docs_path=config.docs_path
    )



@router.post("/uploads", response_model=KnowledgeUploadResponse, summary="Upload Global Knowledge Documents")
async def upload_global_knowledge_files(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    language_hint: str | None = Form(default=None),
    layout_hint: str | None = Form(default=None),
    document_type_hint: str | None = Form(default=None),
    folder_path: str | None = Form(default=None),
) -> KnowledgeUploadResponse:
    """Upload files into the global knowledge base and reindex them."""
    _ = background_tasks
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    docs_dir = get_global_docs_dir()
    uploaded_files: list[dict[str, Any]] = []
    queued_filenames: list[str] = []
    normalized_folder_path = normalize_folder_path(folder_path)
    if normalized_folder_path:
        ensure_folder_path(_global_folder_registry_path(), normalized_folder_path)
    hints = {
        key: value
        for key, value in {
            "language_hint": language_hint,
            "layout_hint": layout_hint,
            "document_type_hint": document_type_hint,
        }.items()
        if value
    }

    for file in files:
        if not file.filename:
            continue
        safe_filename = Path(file.filename).name
        if not safe_filename:
            continue

        try:
            file_path = docs_dir / safe_filename
            file_size = await save_upload_file(file, file_path)
            existing_record = _load_global_record(safe_filename)
            if existing_record:
                _cleanup_global_record_artifacts(existing_record, remove_source_file=False)
                _remove_global_record(safe_filename)
            _remove_global_queued_filename(safe_filename)

            record = _build_global_ingestion_record(
                filename=safe_filename,
                size=file_size,
                content_type=file.content_type,
                hints=hints,
                folder_path=normalized_folder_path,
            )
            if existing_record and existing_record.get("index_target_path"):
                record["replace_existing_index"] = True

            file_info: dict[str, Any] = {
                "filename": safe_filename,
                "size": file_size,
                "artifact_url": _build_global_urls(safe_filename)["source_url"],
                "parse_method": record["parse_method"],
                "parse_status": record["parse_status"],
                "indexable": record["indexable"],
                "preview_filename": record.get("preview_filename"),
                "preview_artifact_url": record.get("preview_artifact_url"),
                "structured_filename": record.get("structured_filename"),
                "structured_artifact_url": record.get("structured_artifact_url"),
                "index_target_filename": record.get("index_target_filename"),
                "index_target_artifact_url": record.get("index_target_artifact_url"),
                "hints": hints,
            }
            if normalized_folder_path:
                file_info["folder"] = normalized_folder_path

            _save_global_record(safe_filename, record)
            if normalized_folder_path:
                try:
                    await update_global_knowledge_metadata(
                        safe_filename,
                        KnowledgeMetadataUpdateRequest(folder=normalized_folder_path),
                    )
                except HTTPException:
                    pass
            uploaded_files.append(file_info)
            if record.get("indexable"):
                queued_filenames.append(safe_filename)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to upload {safe_filename}: {exc}")

    for filename in queued_filenames:
        _submit_global_ocr(filename)

    return KnowledgeUploadResponse(
        success=True,
        files=uploaded_files,
        message=(
            f"Successfully uploaded {len(uploaded_files)} file(s); "
            "files are queued for OCR parsing in the background"
        ),
    )
    


def _list_global_knowledge_files_all() -> dict:
    """List every file stored in the global knowledge directory.

    优先从 catalog SQLite 读取书目（覆盖 .ingestion/ 等非顶层路径下的书籍）；
    SQLite 为空时降级为文件系统扫描（原始行为）。
    """
    from src.community.knowledge_base.book_catalog_index import load_global_entries_from_db  # noqa: PLC0415

    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")

    docs_dir = get_global_docs_dir()
    ocr_positions = _current_global_queue_positions()

    catalog_entries = load_global_entries_from_db()

    files: list[dict[str, Any]] = []

    if catalog_entries is not None:
        # ── 主路径：纯 SQLite，零文件 I/O ────────────────────────────────────────
        # catalog SQLite 已包含所有展示所需字段，无需读 .ingestion/ 下任何文件。
        # 只有正在 OCR 队列中的文件才需要额外读一次 ingestion record 获取实时状态。
        for cat_entry in sorted(catalog_entries, key=lambda e: e.filename):
            filename = cat_entry.filename
            if not filename:
                continue

            tags = list(dict.fromkeys(v for v in [
                *cat_entry.categories, *cat_entry.eras,
                *cat_entry.regions, *cat_entry.keywords,
            ] if v))

            queue_stage: str | None = None
            queue_position: int | None = None
            if filename in ocr_positions:
                queue_stage = "ocr"
                queue_position = ocr_positions[filename]

            files.append({
                "doc_id": cat_entry.doc_id,
                "scope": "global",
                "filename": filename,
                "size": 0,
                "extension": Path(filename).suffix,
                "modified": None,
                "artifact_url": cat_entry.source_url or _build_global_urls(filename)["source_url"],
                "type": cat_entry.type if cat_entry.type and cat_entry.type != "unknown" else None,
                "folder": cat_entry.folder_path,
                "categories": cat_entry.categories,
                "eras": cat_entry.eras,
                "regions": cat_entry.regions,
                "keywords": cat_entry.keywords,
                "summary": cat_entry.summary or None,
                "author": cat_entry.author or None,
                "publisher": cat_entry.publisher or None,
                "tags": tags,
                "language_hint": cat_entry.language_hint,
                "layout_hint": None,
                "document_type_hint": None,
                "parse_method": "untracked",
                "parse_status": "indexed",
                "indexable": True,
                "preview_filename": None,
                "preview_artifact_url": None,
                "structured_filename": cat_entry.structured_path,
                "structured_artifact_url": None,
                "index_target_filename": None,
                "index_target_artifact_url": None,
                "hints": {},
                "error": None,
                "queue_stage": queue_stage,
                "queue_position": queue_position,
            })

    else:
        # ── 降级路径：文件系统扫描（原始行为，catalog 为空时触发）─────────────
        # 仅在降级时才批量读 ingestion records（SQLite 路径用按需单读，无需此步骤）。
        source_records, target_records = _build_global_record_lookup()
        preview_filenames = {
            str(record.get("preview_filename"))
            for record in source_records.values()
            if record.get("preview_filename") and record.get("preview_filename") != record.get("source_filename")
        }
        for file_path in sorted(docs_dir.iterdir()):
            if not file_path.is_file():
                continue
            if file_path.name.startswith("."):
                continue
            record = source_records.get(file_path.name)
            if target_records.get(file_path.name) and not record:
                continue
            if file_path.name in preview_filenames and not record:
                continue
            stat = file_path.stat()
            entry = {
                "doc_id": derive_global_doc_id(docs_dir, file_path),
                "scope": "global",
                "filename": file_path.name,
                "size": stat.st_size,
                "extension": file_path.suffix,
                "modified": stat.st_mtime,
                "artifact_url": _build_global_urls(file_path.name)["source_url"],
            }
            entry.update(_load_global_book_metadata(file_path.name, ingestion_record=record))
            if record:
                queue_position = None
                queue_stage = None
                if file_path.name in ocr_positions:
                    queue_stage = "ocr"
                    queue_position = ocr_positions[file_path.name]
                entry.update({
                    "parse_method": record.get("parse_method"),
                    "parse_status": record.get("parse_status"),
                    "indexable": record.get("indexable", False),
                    "preview_filename": record.get("preview_filename"),
                    "preview_artifact_url": record.get("preview_artifact_url"),
                    "structured_filename": record.get("structured_filename"),
                    "structured_artifact_url": record.get("structured_artifact_url"),
                    "index_target_filename": record.get("index_target_filename"),
                    "index_target_artifact_url": record.get("index_target_artifact_url"),
                    "hints": record.get("hints", {}),
                    "error": record.get("error"),
                    "queue_stage": queue_stage,
                    "queue_position": queue_position,
                })
            else:
                entry.update({
                    "parse_method": "untracked",
                    "parse_status": "uploaded",
                    "indexable": False,
                    "preview_filename": None,
                    "preview_artifact_url": None,
                    "structured_filename": None,
                    "structured_artifact_url": None,
                    "index_target_filename": None,
                    "index_target_artifact_url": None,
                    "hints": {},
                    "error": None,
                })
            files.append(entry)

    return {"files": files, "folders": _list_global_folder_paths(files), "count": len(files)}


def _is_direct_folder_match(file_folder: Any, folder_path: str | None) -> bool:
    normalized_file_folder = normalize_folder_path(file_folder)
    if folder_path:
        return normalized_file_folder == folder_path
    return normalized_file_folder is None


def _build_global_folder_summaries(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    folder_paths = _list_global_folder_paths(files)
    direct_counts: dict[str, int] = {}
    recursive_counts: dict[str, int] = {}
    for file_info in files:
        folder = normalize_folder_path(file_info.get("folder"))
        if not folder:
            continue
        direct_counts[folder] = direct_counts.get(folder, 0) + 1
        parts = folder.split("/")
        for index in range(1, len(parts) + 1):
            ancestor = "/".join(parts[:index])
            recursive_counts[ancestor] = recursive_counts.get(ancestor, 0) + 1

    summaries: list[dict[str, Any]] = []
    for path in folder_paths:
        parent = "/".join(path.split("/")[:-1]) or None
        summaries.append(
            {
                "name": path.split("/")[-1],
                "path": path,
                "parent_path": parent,
                "file_count": recursive_counts.get(path, 0),
                "direct_file_count": direct_counts.get(path, 0),
            }
        )
    return summaries


@router.get("/uploads/folders", response_model=dict, summary="List Global Knowledge Upload Folders")
def list_global_knowledge_upload_folders() -> dict:
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")

    files = _list_global_knowledge_files_all().get("files", [])
    folders = _build_global_folder_summaries(files)
    root_file_count = sum(1 for item in files if _is_direct_folder_match(item.get("folder"), None))
    return {
        "folders": folders,
        "count": len(folders),
        "root_file_count": root_file_count,
        "total_file_count": len(files),
    }


@router.get("/uploads/list", response_model=dict, summary="List Global Knowledge Uploads In Folder")
def list_global_knowledge_files(
    folder_path: str | None = Query(default=None, description="Logical folder path to list; omitted means root"),
) -> dict:
    """List only the files directly visible in the requested global folder."""
    normalized_folder_path = normalize_folder_path(folder_path)
    files = [
        file_info
        for file_info in _list_global_knowledge_files_all().get("files", [])
        if _is_direct_folder_match(file_info.get("folder"), normalized_folder_path)
    ]
    return {"files": files, "folder_path": normalized_folder_path, "count": len(files)}


@router.post("/folders", response_model=dict, summary="Create Global Knowledge Folder")
def create_global_knowledge_folder(payload: FolderMutationRequest) -> dict:
    try:
        folders = ensure_folder_path(_global_folder_registry_path(), payload.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "success": True,
        "folders": folders,
        "path": normalize_folder_path(payload.path),
        "message": "Created global knowledge folder",
    }


@router.patch("/folders", response_model=dict, summary="Rename Global Knowledge Folder")
async def rename_global_knowledge_folder(payload: FolderMutationRequest) -> dict:
    normalized_old = normalize_folder_path(payload.path)
    normalized_new = normalize_folder_path(payload.new_path)
    if not normalized_old or not normalized_new:
        raise HTTPException(status_code=400, detail="Both path and new_path are required")

    current_files = _list_global_knowledge_files_all().get("files", [])
    for file_info in current_files:
        current_folder = normalize_folder_path(file_info.get("folder"))
        if current_folder == normalized_old or (
            current_folder and current_folder.startswith(f"{normalized_old}/")
        ):
            suffix = current_folder[len(normalized_old) :] if current_folder else ""
            filename = str(file_info.get("filename") or "")
            if not filename:
                continue
            updated_folder = f"{normalized_new}{suffix}"
            await update_global_knowledge_metadata(
                filename,
                KnowledgeMetadataUpdateRequest(folder=updated_folder),
            )

    try:
        folders = rename_folder_path(
            _global_folder_registry_path(),
            normalized_old,
            normalized_new,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "success": True,
        "folders": folders,
        "path": normalized_new,
        "message": "Renamed global knowledge folder",
    }


def _clear_book_folder_in_metadata(docs_dir: Path, filename: str) -> None:
    """Clear the folder field from a book's metadata sidecar (best-effort)."""
    meta_path = get_book_metadata_dir(docs_dir) / derive_book_metadata_filename(filename)
    if not meta_path.exists():
        return
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        suggestion = data.get("suggestion")
        if isinstance(suggestion, dict) and suggestion.get("folder"):
            suggestion["folder"] = None
            data["suggestion"] = suggestion
            meta_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _set_book_folder_in_metadata(docs_dir: Path, filename: str, new_folder: str | None) -> None:
    """Set (or clear) the folder field in a book's metadata sidecar (best-effort)."""
    meta_path = get_book_metadata_dir(docs_dir) / derive_book_metadata_filename(filename)
    if not meta_path.exists():
        return
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        suggestion = data.get("suggestion")
        if isinstance(suggestion, dict):
            suggestion["folder"] = (
                {"value": new_folder, "confidence": 1.0, "evidence": "manual_edit"}
                if new_folder
                else None
            )
            data["suggestion"] = suggestion
            meta_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _bulk_update_file_folders(updates: list[tuple[str, str | None]]) -> None:
    """Bulk update folder assignments for a list of ``(filename, new_folder)`` pairs.

    Writes to three places atomically (best-effort for each):
    1. Ingestion record JSON — the authoritative source for the ingest pipeline.
    2. Book metadata sidecar — prevents the UI from showing the stale folder.
    3. SQLite catalog — reflects the change immediately in ``list_global_knowledge_files``.
    """
    if not updates:
        return
    docs_dir = get_global_docs_dir()
    for filename, new_folder in updates:
        record = _load_global_record(filename)
        if record is not None:
            record["folder_path"] = new_folder
            _save_global_record(filename, record)
        _set_book_folder_in_metadata(docs_dir, filename, new_folder)

    from src.community.knowledge_base.book_catalog_index import bulk_update_catalog_folder  # noqa: PLC0415

    bulk_update_catalog_folder(updates)


@router.delete("/folders", response_model=dict, summary="Delete Global Knowledge Folder")
def delete_global_knowledge_folder(path: str = Query(..., description="Logical folder path to delete")) -> dict:
    normalized_path = normalize_folder_path(path)
    if not normalized_path:
        raise HTTPException(status_code=400, detail="path is required")

    docs_dir = get_global_docs_dir()

    # Clear folder_path on every file that belongs to this folder or its subfolders.
    # This resets both the ingestion record (read by fetch_remote_folders.py) and
    # the book-metadata sidecar (prevents the UI from falling back to the stale folder).
    current_files = _list_global_knowledge_files_all().get("files", [])
    cleared_count = 0
    for file_info in current_files:
        current_folder = normalize_folder_path(file_info.get("folder"))
        if current_folder == normalized_path or (
            current_folder and current_folder.startswith(f"{normalized_path}/")
        ):
            filename = str(file_info.get("filename") or "")
            if not filename:
                continue
            record = _load_global_record(filename)
            if record is not None:
                record["folder_path"] = None
                _save_global_record(filename, record)
            _clear_book_folder_in_metadata(docs_dir, filename)
            cleared_count += 1

    try:
        folders = delete_folder_path(_global_folder_registry_path(), normalized_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    message = f"Deleted folder '{normalized_path}'"
    if cleared_count:
        message += f", cleared folder assignment for {cleared_count} file(s)"
    return {
        "success": True,
        "folders": folders,
        "deleted_path": normalized_path,
        "cleared_files": cleared_count,
        "message": message,
    }


@router.post("/folders/move", response_model=dict, summary="Move Global Knowledge Folder")
def move_global_knowledge_folder(payload: FolderMoveRequest) -> dict:
    """Move folder ``path`` under ``target_parent``, keeping its own leaf name.

    Example: ``move("history/ancient", "geography")`` → ``"geography/ancient"``.
    Pass ``target_parent=null`` (or omit it) to promote the folder to the root level.
    All books and sub-folders are relocated accordingly.
    """
    normalized_path = normalize_folder_path(payload.path)
    if not normalized_path:
        raise HTTPException(status_code=400, detail="path is required")

    leaf = normalized_path.split("/")[-1]
    target_parent = normalize_folder_path(payload.target_parent)
    new_path = f"{target_parent}/{leaf}" if target_parent else leaf

    if new_path == normalized_path:
        raise HTTPException(status_code=400, detail="Source and target paths are the same")
    if new_path.startswith(f"{normalized_path}/"):
        raise HTTPException(status_code=400, detail="Cannot move a folder into itself or one of its descendants")

    # Collect per-file folder updates, preserving sub-folder structure.
    current_files = _list_global_knowledge_files_all().get("files", [])
    updates: list[tuple[str, str | None]] = []
    for file_info in current_files:
        current_folder = normalize_folder_path(file_info.get("folder"))
        if not current_folder:
            continue
        if current_folder == normalized_path:
            filename = str(file_info.get("filename") or "")
            if filename:
                updates.append((filename, new_path))
        elif current_folder.startswith(f"{normalized_path}/"):
            filename = str(file_info.get("filename") or "")
            if filename:
                suffix = current_folder[len(normalized_path):]  # e.g. "/sub1"
                updates.append((filename, f"{new_path}{suffix}"))

    _bulk_update_file_folders(updates)

    try:
        folders = rename_folder_path(_global_folder_registry_path(), normalized_path, new_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "success": True,
        "old_path": normalized_path,
        "new_path": new_path,
        "moved_files": len(updates),
        "folders": folders,
        "message": f"Moved '{normalized_path}' → '{new_path}' ({len(updates)} file(s) updated)",
    }


@router.post("/folders/merge", response_model=dict, summary="Merge Global Knowledge Folder")
def merge_global_knowledge_folder(payload: FolderMergeRequest) -> dict:
    """Move all books from ``source_path`` into ``target_path``, then delete the source.

    Books directly in ``source_path`` go to ``target_path``.
    Books in ``source_path/sub`` go to ``target_path/sub`` (sub-tree preserved).
    The ``source_path`` folder (and any sub-folders) is removed from the registry.
    """
    normalized_source = normalize_folder_path(payload.source_path)
    normalized_target = normalize_folder_path(payload.target_path)
    if not normalized_source:
        raise HTTPException(status_code=400, detail="source_path is required")
    if not normalized_target:
        raise HTTPException(status_code=400, detail="target_path is required")
    if normalized_source == normalized_target:
        raise HTTPException(status_code=400, detail="source_path and target_path must be different")
    if normalized_target.startswith(f"{normalized_source}/"):
        raise HTTPException(status_code=400, detail="Cannot merge a folder into its own descendant")

    current_files = _list_global_knowledge_files_all().get("files", [])
    updates: list[tuple[str, str | None]] = []
    for file_info in current_files:
        current_folder = normalize_folder_path(file_info.get("folder"))
        if not current_folder:
            continue
        if current_folder == normalized_source:
            filename = str(file_info.get("filename") or "")
            if filename:
                updates.append((filename, normalized_target))
        elif current_folder.startswith(f"{normalized_source}/"):
            filename = str(file_info.get("filename") or "")
            if filename:
                suffix = current_folder[len(normalized_source):]  # e.g. "/sub1"
                updates.append((filename, f"{normalized_target}{suffix}"))

    _bulk_update_file_folders(updates)

    try:
        ensure_folder_path(_global_folder_registry_path(), normalized_target)
        folders = delete_folder_path(_global_folder_registry_path(), normalized_source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "success": True,
        "source_path": normalized_source,
        "target_path": normalized_target,
        "merged_files": len(updates),
        "folders": folders,
        "message": f"Merged '{normalized_source}' → '{normalized_target}' ({len(updates)} file(s) moved)",
    }


# ---------------------------------------------------------------------------
# Folder Reorganization Agent
# ---------------------------------------------------------------------------

_REORGANIZE_SYSTEM_PROMPT = """\
你是一个知识库目录整理专家。请仔细分析给出的目录结构，找出不合理之处并给出整理方案。

分析原则（按优先级排序）：
1. **合并重叠/同义目录**：同层级下含义相近或有交叉的目录（如"明代"和"明朝"、"近代"和"近现代"）应合并
2. **移动错层目录**：目录放错了层级（如"经济史"作为"政治史"的子目录）应移动到正确位置
3. **提升孤单子目录**：某目录下只有1个子目录而无直属书籍，考虑将子目录提升一级
4. **统一命名规范**：同类目录命名风格应一致（如"宋代"/"元代"/"明代"不应混有"宋朝史"）
5. **拆解过大目录**：若某目录书籍数超过100本，考虑是否需要细分子目录（不强制）

输出格式（仅输出 JSON 数组，不要任何解释性文字）：
[
  {"op": "move",   "path": "历史/古代",      "target_parent": "中国历史",    "reason": "应归入中国历史大类下"},
  {"op": "merge",  "source_path": "宋代史",  "target_path": "历史/宋代",     "reason": "重复目录，内容相同"},
  {"op": "rename", "path": "历史/上古史",    "new_path": "历史/远古",        "reason": "统一命名风格"}
]

约束：
- 最多返回 15 个操作，优先处理最明显的问题
- move 的 target_parent 填 null 表示移至根目录
- 如果目录已经合理，返回空数组 []
- 只修改路径（不增删文件），所有操作必须只包含已存在的目录路径
"""


def _sse(data: dict) -> str:
    """Encode a single SSE data frame."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _extract_json_array(text: str) -> list:
    """Extract the first JSON array from LLM output (handles markdown fences)."""
    normalized = text.strip()
    # Strip ```json ... ``` fences
    if normalized.startswith("```"):
        lines = normalized.splitlines()
        if len(lines) > 2:
            normalized = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    start = normalized.find("[")
    end = normalized.rfind("]")
    if start < 0 or end < 0 or end < start:
        return []
    try:
        result = json.loads(normalized[start : end + 1])
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        return []


def _validate_reorganize_ops(ops: list, known_folders: set[str]) -> list[dict]:
    """Filter out ops that reference non-existent folders or have wrong shape."""
    valid: list[dict] = []
    for op in ops:
        if not isinstance(op, dict):
            continue
        op_type = op.get("op")
        if op_type == "move":
            if "path" not in op:
                continue
            path = normalize_folder_path(op.get("path"))
            if not path or path not in known_folders:
                continue
            target_parent = normalize_folder_path(op.get("target_parent"))
            # Prevent moving into self / descendant
            new_full = f"{target_parent}/{path.split('/')[-1]}" if target_parent else path.split("/")[-1]
            if new_full == path or new_full.startswith(f"{path}/"):
                continue
            valid.append({**op, "path": path, "target_parent": target_parent or None})
        elif op_type == "merge":
            src = normalize_folder_path(op.get("source_path"))
            tgt = normalize_folder_path(op.get("target_path"))
            if not src or not tgt or src == tgt:
                continue
            if src not in known_folders:
                continue
            valid.append({**op, "source_path": src, "target_path": tgt})
        elif op_type == "rename":
            old = normalize_folder_path(op.get("path"))
            new = normalize_folder_path(op.get("new_path"))
            if not old or not new or old == new:
                continue
            if old not in known_folders:
                continue
            valid.append({**op, "path": old, "new_path": new})
    return valid


def _execute_reorganize_op(op: dict) -> dict:
    """Execute a single reorganization operation synchronously."""
    op_type = op.get("op")
    if op_type == "move":
        return move_global_knowledge_folder(
            FolderMoveRequest(path=op["path"], target_parent=op.get("target_parent"))
        )
    if op_type == "merge":
        return merge_global_knowledge_folder(
            FolderMergeRequest(source_path=op["source_path"], target_path=op["target_path"])
        )
    if op_type == "rename":
        normalized_old = str(op["path"])
        normalized_new = str(op["new_path"])
        current_files = _list_global_knowledge_files_all().get("files", [])
        updates: list[tuple[str, str | None]] = []
        for file_info in current_files:
            current_folder = normalize_folder_path(file_info.get("folder"))
            if not current_folder:
                continue
            if current_folder == normalized_old or current_folder.startswith(f"{normalized_old}/"):
                suffix = current_folder[len(normalized_old):]
                filename = str(file_info.get("filename") or "")
                if filename:
                    updates.append((filename, f"{normalized_new}{suffix}"))
        _bulk_update_file_folders(updates)
        folders = rename_folder_path(_global_folder_registry_path(), normalized_old, normalized_new)
        return {"success": True, "old_path": normalized_old, "new_path": normalized_new,
                "moved_files": len(updates), "folders": folders}
    raise ValueError(f"Unknown op type: {op_type!r}")


def _run_folder_reorganize(
    model_name: str | None,
    focus_path: str | None,
) -> Generator[str, None, None]:
    """Generator that yields SSE frames driving the full reorganize workflow."""
    # ── Phase 1: collect folder + file info ───────────────────────────────
    try:
        current_files = _list_global_knowledge_files_all().get("files", [])
        all_folders = _list_global_folder_paths(current_files)

        if focus_path:
            norm_focus = normalize_folder_path(focus_path)
            all_folders = [
                f for f in all_folders
                if f == norm_focus or f.startswith(f"{norm_focus}/")
            ]

        # Count books per folder
        folder_counts: dict[str, int] = {}
        for file_info in current_files:
            folder = normalize_folder_path(file_info.get("folder"))
            if folder:
                folder_counts[folder] = folder_counts.get(folder, 0) + 1

        folder_count = len(all_folders)
        yield _sse({"type": "analyzing", "folder_count": folder_count})
    except Exception as exc:
        yield _sse({"type": "error", "message": f"Failed to read folder tree: {exc}"})
        return

    # ── Phase 2: build prompt and call LLM ────────────────────────────────
    try:
        tree_text = render_folder_tree(folder_paths=all_folders) or "(空目录树)"
        count_lines = "\n".join(
            f"  {f}: {folder_counts.get(f, 0)} 本书"
            for f in sorted(all_folders)
        )
        user_prompt = (
            f"当前知识库目录结构：\n\n{tree_text}\n\n"
            f"各目录书籍数量：\n{count_lines}\n\n"
            "请输出整理方案（JSON 数组）："
        )

        from src.models import create_chat_model  # noqa: PLC0415
        from langchain_core.messages import HumanMessage, SystemMessage  # noqa: PLC0415

        model = create_chat_model(name=model_name, thinking_enabled=False)
        response = model.invoke([
            SystemMessage(content=_REORGANIZE_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ])
        response_text = str(response.content) if hasattr(response, "content") else str(response)
    except Exception as exc:
        yield _sse({"type": "error", "message": f"LLM call failed: {exc}"})
        return

    # ── Phase 3: parse and validate plan ──────────────────────────────────
    raw_ops = _extract_json_array(response_text)
    known_folders = set(all_folders)
    operations = _validate_reorganize_ops(raw_ops, known_folders)

    yield _sse({"type": "plan", "operations": operations, "total": len(operations),
                "raw_response": response_text[:2000] if len(response_text) > 2000 else response_text})

    if not operations:
        yield _sse({"type": "done", "executed": 0, "skipped": 0,
                    "message": "目录结构已经很合理，无需整理。"})
        return

    # ── Phase 4: execute operations ───────────────────────────────────────
    executed = 0
    skipped = 0
    for i, op in enumerate(operations):
        try:
            result = _execute_reorganize_op(op)
            executed += 1
            yield _sse({
                "type": "progress",
                "step": i + 1,
                "total": len(operations),
                "op": op,
                "success": True,
                "result": {k: v for k, v in result.items() if k != "folders"},
            })
        except Exception as exc:
            skipped += 1
            yield _sse({
                "type": "progress",
                "step": i + 1,
                "total": len(operations),
                "op": op,
                "success": False,
                "error": str(exc),
            })

    yield _sse({
        "type": "done",
        "executed": executed,
        "skipped": skipped,
        "message": f"完成：执行 {executed} 个操作，跳过 {skipped} 个。",
    })


@router.post("/folders/reorganize", summary="AI-Powered Folder Reorganization")
def reorganize_global_knowledge_folders(payload: FolderReorganizeRequest) -> StreamingResponse:
    """Analyze the folder tree with an LLM and auto-execute a reorganization plan.

    Returns ``text/event-stream`` with JSON frames:

    * ``{"type": "analyzing", "folder_count": N}`` — scan started
    * ``{"type": "plan", "operations": [...], "total": N}`` — LLM plan ready
    * ``{"type": "progress", "step": K, "total": N, "op": {...}, "success": bool, ...}``
    * ``{"type": "done", "executed": N, "skipped": N, "message": "..."}``
    * ``{"type": "error", "message": "..."}`` — on fatal failure
    """
    def generate() -> Generator[str, None, None]:
        yield from _run_folder_reorganize(payload.model_name, payload.focus_path)

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.patch("/uploads/{filename}/metadata", response_model=dict, summary="Update Global Knowledge Metadata")
async def update_global_knowledge_metadata(
    filename: str,
    payload: KnowledgeMetadataUpdateRequest,
) -> dict:
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    structured_payload, record, docs_dir = _load_structured_payload_for_metadata(filename)

    if structured_payload is None:
        raise HTTPException(status_code=400, detail="This file does not have editable structured metadata yet")

    existing = load_book_metadata_for_source(docs_dir, filename)
    existing_suggestion = existing.suggestion if existing else None
    provided_fields = payload.model_fields_set
    prompt_input = (
        existing.prompt_input
        if existing is not None
        else build_book_metadata_prompt_input(
            structured_payload,
            source_filename=filename,
            title=str((record or {}).get("display_title") or Path(filename).stem),
            front_page_limit=(config.book_metadata.front_page_limit if config.book_metadata else 10),
            max_excerpt_chars=(config.book_metadata.max_excerpt_chars if config.book_metadata else 1200),
            existing_folder_tree=build_existing_folder_tree(
                docs_dir,
                exclude_source_filename=filename,
                folder_registry_path=_global_folder_registry_path(),
            ),
        )
    )

    suggestion = {
        "title": str((existing_suggestion.title if existing_suggestion else None) or (record or {}).get("display_title") or Path(filename).stem),
        "author": (
            _manual_metadata_field(payload.author)
            if "author" in provided_fields
            else (existing_suggestion.author if existing_suggestion else None)
        ),
        "publisher": (
            _manual_metadata_field(payload.publisher)
            if "publisher" in provided_fields
            else (existing_suggestion.publisher if existing_suggestion else None)
        ),
        "type": (
            _manual_metadata_field(payload.type)
            if "type" in provided_fields
            else (existing_suggestion.type if existing_suggestion else None)
        ),
        "folder": (
            _manual_metadata_field(normalize_folder_path(payload.folder))
            if "folder" in provided_fields
            else (existing_suggestion.folder if existing_suggestion else None)
        ),
        "categories": (
            _manual_metadata_fields(payload.categories)
            if "categories" in provided_fields
            else (existing_suggestion.categories if existing_suggestion else [])
        ),
        "eras": (
            _manual_metadata_fields(payload.eras)
            if "eras" in provided_fields
            else (existing_suggestion.eras if existing_suggestion else [])
        ),
        "regions": (
            _manual_metadata_fields(payload.regions)
            if "regions" in provided_fields
            else (existing_suggestion.regions if existing_suggestion else [])
        ),
        "keywords": (
            _manual_metadata_fields(payload.keywords)
            if "keywords" in provided_fields
            else (existing_suggestion.keywords if existing_suggestion else [])
        ),
        "summary": (
            _manual_metadata_field(payload.summary)
            if "summary" in provided_fields
            else (existing_suggestion.summary if existing_suggestion else None)
        ),
        "ocr_quality": existing_suggestion.ocr_quality if existing_suggestion else None,
        "notes": "manual_edit",
    }

    book_metadata_record = build_book_metadata_record(
        source_filename=filename,
        source_title=str((record or {}).get("display_title") or Path(filename).stem),
        page_count=len(list(structured_payload.get("pages") or [])),
        prompt_input=prompt_input,
        suggestion=suggestion,
        model_name=(existing.model_name if existing else (config.book_metadata.model_name if config.book_metadata else None)),
    )
    save_book_metadata(docs_dir, filename, book_metadata_record)
    if record is not None:
        next_hints = dict(record.get("hints") or {})
        if "folder" in provided_fields:
            record["folder_path"] = normalize_folder_path(payload.folder)
            if payload.folder:
                ensure_folder_path(_global_folder_registry_path(), payload.folder)
        if "language_hint" in provided_fields:
            if payload.language_hint:
                next_hints["language_hint"] = payload.language_hint
            else:
                next_hints.pop("language_hint", None)
        if "layout_hint" in provided_fields:
            if payload.layout_hint:
                next_hints["layout_hint"] = payload.layout_hint
            else:
                next_hints.pop("layout_hint", None)
        if "document_type_hint" in provided_fields:
            if payload.document_type_hint:
                next_hints["document_type_hint"] = payload.document_type_hint
            else:
                next_hints.pop("document_type_hint", None)
        record["hints"] = next_hints
        _save_global_record(filename, record)
    return {
        "success": True,
        "message": f"Updated metadata for {filename}",
        "metadata": _load_global_book_metadata(filename),
    }


@router.post("/uploads/{filename}/metadata/regenerate", response_model=dict, summary="Regenerate Global Knowledge Metadata")
async def regenerate_global_knowledge_metadata(filename: str) -> dict:
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if config.book_metadata is None or not config.book_metadata.enabled:
        raise HTTPException(status_code=400, detail="Book metadata generation is not enabled")

    structured_payload, record, docs_dir = _load_structured_payload_for_metadata(filename)
    if structured_payload is None:
        raise HTTPException(status_code=400, detail="This file does not have editable structured metadata yet")

    source_title = str((record or {}).get("display_title") or Path(filename).stem)
    try:
        generate_book_metadata_record(
            structured_payload=structured_payload,
            source_filename=filename,
            title=source_title,
            output_dir=docs_dir,
            config=config.book_metadata,
        )
    except Exception as exc:
        logger.exception("Failed to regenerate metadata for %s: %s", filename, exc)
        raise HTTPException(status_code=500, detail=f"Failed to regenerate metadata: {exc}")

    return {
        "success": True,
        "message": f"Regenerated metadata for {filename}",
        "metadata": _load_global_book_metadata(filename),
    }


@router.delete("/uploads/{filename}", response_model=dict, summary="Delete Global Knowledge Upload")
async def delete_global_knowledge_file(filename: str) -> dict:
    """Delete a file from the global knowledge directory and rebuild the global index."""
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    _remove_global_queued_filename(filename)
    _acquire_knowledge_operation_lock()
    docs_dir = get_global_docs_dir()
    file_path = docs_dir / filename
    record = _find_global_record(filename)

    try:
        if record:
            source_filename = record.get("source_filename")
            _cleanup_global_record_artifacts(record, remove_source_file=True)
            if source_filename:
                _remove_global_record(str(source_filename))
        elif file_path.exists():
            file_path.unlink()
        else:
            raise HTTPException(status_code=404, detail=f"File not found: {filename}")

        delete_global_knowledge_documents([record.get("source_filename") or filename] if record else [filename])
        return {
            "success": True,
            "message": f"Deleted {filename} from global knowledge base and updated the index",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete {filename}: {exc}")
    finally:
        _release_knowledge_operation_lock()


@router.delete("/uploads/{filename}/artifacts-only", response_model=dict, summary="Delete Artifacts for Non-indexed Global File")
async def delete_global_knowledge_file_artifacts_only(filename: str) -> dict:
    """Delete all on-disk artifacts for a file that has NOT been indexed yet.

    Unlike the full delete endpoint, this path skips the Qdrant operation and the
    global operation lock, making it safe and fast for batch-deleting files that are
    only in the uploaded / parsed / failed state.  Returns 409 if the file is currently
    being processed or has already been indexed (use the regular DELETE endpoint instead).
    """
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    record = _find_global_record(filename)
    if record is None:
        docs_dir = get_global_docs_dir()
        file_path = docs_dir / filename
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"File not found: {filename}")
        file_path.unlink()
        return {"success": True, "message": f"Deleted {filename}"}

    parse_status = str(record.get("parse_status") or "")
    active_statuses = {"queued", "queued_ocr", "parsing", "queued_embedding", "indexing"}
    if parse_status in active_statuses:
        raise HTTPException(status_code=409, detail=f"File is currently being processed (status={parse_status}); cannot delete now")
    if parse_status == "indexed":
        raise HTTPException(status_code=409, detail="File is already indexed; use the regular delete endpoint to also update the vector index")

    source_filename = str(record.get("source_filename") or filename)
    try:
        _cleanup_global_record_artifacts(record, remove_source_file=True)
        _remove_global_record(source_filename)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete artifacts for {filename}: {exc}")

    return {"success": True, "message": f"Deleted all artifacts for {filename}"}


@router.post("/uploads/{filename}/build-index", response_model=dict, summary="Build Qdrant Index for Pre-parsed File")
def build_index_for_global_file(filename: str) -> dict:
    """Build the Qdrant vector index for a file that already has a structured JSON.

    Intended for the local-OCR workflow: after syncing pre-built ingestion records
    to the server, call this to embed and index the file without re-running OCR.
    """
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    record = _find_global_record(filename)
    if record is None:
        raise HTTPException(status_code=404, detail="Ingestion record not found — sync the .json files first")
    if not record.get("indexable"):
        raise HTTPException(status_code=400, detail="File is not indexable")
    if record.get("parse_status") != "parsed":
        raise HTTPException(
            status_code=409,
            detail=f"Expected parse_status=parsed, got {record.get('parse_status')}",
        )

    ingestion_dir = get_global_ingestion_dir()
    structured_filename = record.get("index_target_filename") or record.get("structured_filename")
    if not structured_filename:
        raise HTTPException(status_code=400, detail="No structured_filename in record")
    structured_path = Path(record["index_target_path"]) if record.get("index_target_path") else ingestion_dir / structured_filename
    if not structured_path.exists():
        raise HTTPException(status_code=404, detail=f"Structured JSON not found: {structured_path.name}")

    try:
        from src.community.knowledge_base.indexer import upsert_global_knowledge_record
        chunks, _ = upsert_global_knowledge_record(filename)
        return {"success": True, "message": f"Indexed {chunks} chunks for {filename}", "chunks": chunks}
    except Exception as exc:
        logger.exception("build-index failed for %s: %s", filename, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/uploads/{filename}/reindex", response_model=dict, summary="Retry Global Knowledge Indexing")
async def retry_global_knowledge_file(filename: str) -> dict:
    """Retry OCR or indexing for a single tracked global knowledge file."""
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    record = _find_global_record(filename)
    if record is None:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    if not record.get("indexable"):
        raise HTTPException(status_code=400, detail="This file type does not support indexing")

    source_filename = str(record.get("source_filename") or filename)
    file_path = get_global_docs_dir() / source_filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Source file missing: {source_filename}")

    current_status = str(record.get("parse_status") or "")
    if current_status in {"queued", "queued_ocr", "parsing"}:
        raise HTTPException(status_code=409, detail="This file is already being processed")

    record["error"] = None
    record["parse_status"] = "queued_ocr"
    record["retry_count"] = 0  # explicit user intervention — start counting fresh
    _save_global_record(source_filename, record)
    _submit_global_ocr(source_filename)
    return {
        "success": True,
        "message": f"已重新加入解析队列：{source_filename}",
    }


@router.post("/uploads/{filename}/reparse", response_model=dict, summary="Reparse Global Knowledge File")
async def reparse_global_knowledge_file(filename: str) -> dict:
    """Re-run OCR/parsing for a single tracked global knowledge file."""
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    record = _find_global_record(filename)
    if record is None:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    if not record.get("indexable"):
        raise HTTPException(status_code=400, detail="This file type does not support indexing")

    source_filename = str(record.get("source_filename") or filename)
    file_path = get_global_docs_dir() / source_filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Source file missing: {source_filename}")

    current_status = str(record.get("parse_status") or "")
    if current_status in {"queued", "queued_ocr", "parsing"}:
        raise HTTPException(status_code=409, detail="This file is already being processed")

    record["error"] = None
    record["parse_status"] = "queued_ocr"
    record["retry_count"] = 0  # explicit user intervention — start counting fresh
    _save_global_record(source_filename, record)
    _submit_global_ocr(source_filename)
    return {
        "success": True,
        "message": f"已重新加入解析队列：{source_filename}",
    }


@router.get("/debug/books", response_model=KnowledgeDebugBooksResponse, summary="List Debug Search Books")
def list_debug_search_books() -> KnowledgeDebugBooksResponse:
    """List searchable global books for retrieval debugging UI."""
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")

    uploads = _list_global_knowledge_files_all().get("files", [])
    upload_by_doc_id = {
        str(item.get("doc_id") or ""): item
        for item in uploads
        if str(item.get("doc_id") or "").strip()
    }
    entries = list_book_catalog(
        include_search_content=False,
        caller="knowledge.debug_books",
    )
    books: list[KnowledgeDebugBookInfo] = []
    for entry in entries:
        upload = upload_by_doc_id.get(entry.doc_id, {})
        books.append(
            KnowledgeDebugBookInfo(
                doc_id=entry.doc_id,
                title=entry.title,
                filename=entry.filename,
                scope=entry.scope,
                folder=entry.folder_path,
                summary=entry.summary or None,
                language_hint=entry.language_hint,
                parse_status=upload.get("parse_status"),
                indexable=bool(upload.get("indexable", False)),
                modified=upload.get("modified"),
            )
        )

    books.sort(key=lambda item: ((item.folder or ""), item.title, item.filename))
    return KnowledgeDebugBooksResponse(books=books, count=len(books))


@router.post(
    "/debug/qdrant-search",
    response_model=KnowledgeDebugQdrantResponse,
    summary="Run Direct Qdrant Search",
)
def debug_qdrant_search(payload: KnowledgeDebugSearchRequest) -> KnowledgeDebugQdrantResponse:
    """Run direct vector retrieval against Qdrant for the selected books."""
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")
    if not payload.doc_ids:
        raise HTTPException(status_code=400, detail="At least one doc_id is required")

    started_at = time.perf_counter()
    try:
        results = get_retriever().search_qdrant(
            payload.query,
            doc_ids=payload.doc_ids,
            top_k=payload.top_k,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Qdrant debug search failed: {exc}") from exc

    return KnowledgeDebugQdrantResponse(
        query=payload.query,
        doc_ids=payload.doc_ids,
        top_k=payload.top_k,
        elapsed_ms=(time.perf_counter() - started_at) * 1000,
        results=[_build_debug_search_result(result) for result in results],
    )


@router.post(
    "/debug/knowledge-search",
    response_model=KnowledgeDebugToolResponse,
    summary="Run knowledge_search Tool",
)
def debug_knowledge_search_tool(payload: KnowledgeDebugSearchRequest) -> KnowledgeDebugToolResponse:
    """Run the knowledge_search tool in conservative keyword mode."""
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")
    if not payload.doc_ids:
        raise HTTPException(status_code=400, detail="At least one doc_id is required")

    runtime = SimpleNamespace(context={})
    started_at = time.perf_counter()
    try:
        output = knowledge_search_tool.func(
            runtime,
            query=payload.query,
            doc_ids=payload.doc_ids,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"knowledge_search debug call failed: {exc}") from exc

    return KnowledgeDebugToolResponse(
        query=payload.query,
        doc_ids=payload.doc_ids,
        elapsed_ms=(time.perf_counter() - started_at) * 1000,
        output=str(output or ""),
    )


@router.get("/search", response_model=SearchResponse, summary="Search Knowledge Base")
def search_knowledge_base(
    q: str = Query(..., description="Search query"),
    thread_id: str | None = Query(default=None, description="Optional thread ID to include uploaded docs"),
    user_id: str | None = Query(default=None, description="Optional user ID to include personal knowledge docs"),
    doc_ids: str | None = Query(default=None, description="Optional comma-separated doc_ids to filter candidate books"),
    folder_path: list[str] | None = Query(default=None, description="Optional folder-path filters"),
) -> SearchResponse:
    """Search the knowledge base for relevant documents."""
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")

    try:
        retriever = get_retriever()
        parsed_doc_ids = [item.strip() for item in doc_ids.split(",") if item.strip()] if doc_ids else None
        parsed_folder_paths = [normalized for raw in (folder_path or []) if (normalized := normalize_folder_path(raw))]
        results = retriever.search(
            q,
            thread_id=thread_id,
            user_id=user_id,
            doc_ids=parsed_doc_ids,
            folder_paths=parsed_folder_paths or None,
        )

        search_results = []
        for res in results:
            metadata = res.get("metadata", {})
            citation_context = resolve_result_citation_context(
                res,
                thread_id=thread_id,
                user_id=user_id,
            )

            search_results.append(
                SearchResult(
                    content=res["content"],
                    score=res["score"],
                    filename=res["filename"],
                    source=res["source"],
                    line_start=metadata.get("line_start"),
                    line_end=metadata.get("line_end"),
                    page_no=metadata.get("page_no"),
                    pdf_page_no=metadata.get("pdf_page_no"),
                    book_page_no=metadata.get("book_page_no"),
                    paragraph_no=metadata.get("paragraph_no"),
                    bbox=metadata.get("bbox"),
                    source_url=citation_context["source_url"],
                    original_url=citation_context["original_url"],
                    page=res.get("page"),
                    source_type=res.get("source_type", "unknown"),
                )
            )

        return SearchResponse(query=q, results=search_results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.get(
    "/docs",
    response_model=KnowledgeDocumentListResponse,
    summary="List Knowledge Documents",
)
def list_knowledge_documents() -> KnowledgeDocumentListResponse:
    """List all visible files under the knowledge docs directory."""
    response = _list_global_knowledge_files_all()
    docs = [
        KnowledgeDocumentInfo(
            filename=file_info["filename"],
            size=int(file_info["size"]),
            modified=float(file_info.get("modified") or 0),
            extension=str(file_info.get("extension") or ""),
        )
        for file_info in response.get("files", [])
    ]
    return KnowledgeDocumentListResponse(docs=docs)


@router.post(
    "/docs/upload",
    response_model=UploadKnowledgeDocumentResponse,
    summary="Upload Knowledge Document",
)
async def upload_knowledge_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Knowledge document"),
    reindex: bool = Query(
        True,
        description="Compatibility flag. Structured uploads always reindex in the background.",
    ),
) -> UploadKnowledgeDocumentResponse:
    """Compatibility wrapper for the settings-page upload flow."""
    _ = reindex
    upload_response = await upload_global_knowledge_files(
        background_tasks,
        [file],
    )
    uploaded = upload_response.files[0] if upload_response.files else {}
    return UploadKnowledgeDocumentResponse(
        status="success" if upload_response.success else "error",
        message=upload_response.message,
        filename=str(uploaded.get("filename") or file.filename or ""),
        markdown_filename=str(uploaded.get("preview_filename") or "") or None,
    )


@router.delete(
    "/docs/{filename}",
    response_model=dict,
    summary="Delete Knowledge Document",
)
async def delete_knowledge_document(
    filename: str,
) -> dict:
    """Compatibility wrapper for deleting a knowledge document."""
    return await delete_global_knowledge_file(filename)


@router.get("/docs/{filename}", summary="Get Knowledge Document")
def get_knowledge_document(
    filename: str,
    download: bool = False,
    page: int | None = Query(None, description="Page number for PDF files (0-based)"),
):
    """Get a knowledge document by filename.

    Supports URL-encoded names like 民国财政史_(杨荫溥).md.
    For PDF files, the page parameter can be used to indicate the target page
    (passed to frontend via X-Page header).
    """
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")

    if "/" in filename or "\\" in filename or filename.startswith(".."):
        raise HTTPException(status_code=400, detail="Invalid filename")

    docs_root = get_global_docs_dir()
    file_path = docs_root / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Document not found")

    # Ensure resolved path is under docs_root (path traversal protection)
    try:
        file_path = file_path.resolve()
        docs_root = docs_root.resolve()
        if not str(file_path).startswith(str(docs_root)):
            raise HTTPException(status_code=400, detail="Invalid filename")
    except Exception:
        raise HTTPException(status_code=404, detail="Document not found")

    ext = Path(filename).suffix.lower()
    if download:
        media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type=media_type,
        )
    if ext == ".pdf":
        headers = {}
        if page is not None:
            headers["X-PDF-Page"] = str(page)
        return FileResponse(
            path=file_path,
            media_type="application/pdf",
            headers=headers,
        )

    # Handle text/markdown files
    return FileResponse(
        path=file_path,
        media_type="text/markdown"
    )


@router.get(
    "/docs/{filename}/structured-page",
    response_model=dict,
    summary="Get structured page data for a knowledge document",
)
def get_knowledge_structured_page(
    response: Response,
    filename: str,
    page_no: int | None = Query(default=None),
    pdf_page_no: int | None = Query(default=None),
):
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if page_no is None and pdf_page_no is None:
        raise HTTPException(status_code=400, detail="page_no or pdf_page_no is required")

    document = locate_document(thread_id=None, filename=filename)
    if not document:
        raise HTTPException(status_code=404, detail="Structured document not found")

    payload = _build_structured_page_payload(document, page_no=page_no, pdf_page_no=pdf_page_no)
    if payload is not None:
        response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=3600"
        return payload

    raise HTTPException(status_code=404, detail="Structured page not found")


@router.post(
    "/docs/{filename}/translate-blocks",
    response_model=dict,
    summary="Translate structured page paragraphs into Chinese",
)
def translate_knowledge_blocks(
    filename: str,
    payload: TranslateBlocksRequest,
):
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    document = locate_document(thread_id=None, filename=filename)
    if not document:
        raise HTTPException(status_code=404, detail="Structured document not found")

    blocks = [
        {
            "id": paragraph.key,
            "text": paragraph.text,
        }
        for paragraph in payload.paragraphs
        if paragraph.key.strip() and paragraph.text.strip()
    ]
    if not blocks:
        return {"translations": []}

    try:
        translations = translate_blocks_to_chinese_via_grpc(
            blocks,
            source_language_hint=payload.source_language_hint,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Translation failed: {exc}") from exc

    return {
        "translations": [
            {
                "key": item["id"],
                "translation": item["translation"],
            }
            for item in translations
        ]
    }


@router.get(
    "/docs/{filename}/paragraph-location",
    response_model=KnowledgeParagraphLocationResponse,
    summary="Get paragraph location metadata for a knowledge document",
)
def get_knowledge_paragraph_location(
    filename: str,
    page_no: int | None = Query(default=None),
    pdf_page_no: int | None = Query(default=None),
    paragraph_no: int | None = Query(default=None),
):
    """Resolve page/paragraph metadata including bbox for a knowledge citation."""
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if page_no is None and pdf_page_no is None and paragraph_no is None:
        raise HTTPException(status_code=400, detail="At least one of page_no, pdf_page_no, or paragraph_no is required")

    document = locate_document(thread_id=None, filename=filename)
    if not document:
        raise HTTPException(status_code=404, detail="Structured document not found")

    excerpt = extract_paragraph_location(
        payload=document.payload,
        page_no=page_no,
        pdf_page_no=pdf_page_no,
        paragraph_no=paragraph_no,
    )
    if not excerpt:
        raise HTTPException(status_code=404, detail="Paragraph location not found")
    return KnowledgeParagraphLocationResponse(
        doc_id=document.doc_id,
        scope=document.scope,
        filename=document.filename,
        title=document.title,
        page_count=len(list(document.payload.get("pages") or [])),
        page_no=excerpt.get("page_no"),
        pdf_page_no=excerpt.get("pdf_page_no"),
        book_page_no=excerpt.get("book_page_no"),
        paragraph_no=excerpt.get("paragraph_no"),
        bbox=excerpt.get("bbox") or build_bbox_from_position(excerpt.get("position")),
        page_meta=excerpt.get("page_meta"),
        text=str(excerpt.get("text") or ""),
        source_url=_encode_url_path(document.source_url),
        original_url=_encode_url_path(document.original_url),
    )


@router.get("/docs/{filename}/page-image", summary="Render a PDF page image for citation viewing")
def get_knowledge_document_page_image(
    request: Request,
    filename: str,
    pdf_page_no: int = Query(..., ge=1),
    dpi: int = Query(default=120, ge=72, le=300),
):
    """Render a physical PDF page to JPEG for bbox-based citation highlighting."""
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    docs_root = get_global_docs_dir()
    file_path = docs_root / filename
    try:
        file_path = file_path.resolve()
        docs_root_resolved = docs_root.resolve()
        if not str(file_path).startswith(str(docs_root_resolved)):
            raise HTTPException(status_code=400, detail="Invalid filename")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Document not found")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Document not found")
    if file_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Page images are only available for PDF documents")

    try:
        mtime_ns = file_path.stat().st_mtime_ns
    except OSError:
        raise HTTPException(status_code=404, detail="Document not found")

    etag = f'"{mtime_ns}:{pdf_page_no}:{dpi}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400"})

    try:
        import fitz
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF rendering dependency unavailable: {exc}") from exc

    try:
        with fitz.open(file_path) as document:
            page_index = pdf_page_no - 1
            if page_index < 0 or page_index >= document.page_count:
                raise HTTPException(status_code=404, detail="PDF page not found")
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
            img_bytes = pixmap.tobytes("jpeg", jpg_quality=85)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to render PDF page: {exc}") from exc

    return Response(
        content=img_bytes,
        media_type="image/jpeg",
        headers={
            "ETag": etag,
            "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400",
        },
    )
