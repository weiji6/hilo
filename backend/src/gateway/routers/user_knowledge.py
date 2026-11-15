import mimetypes
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from src.community.knowledge_base.book_metadata import normalize_folder_path
from src.community.knowledge_base.common import derive_global_doc_id, get_user_collection_name, resolve_project_path
from src.community.knowledge_base.document_parsers import OFFICE_EXTENSIONS, PDF_EXTENSIONS, parse_local_text
from src.community.knowledge_base.folder_registry import (
    delete_folder_path,
    ensure_folder_path,
    ensure_folder_paths,
    list_folder_paths,
    rename_folder_path,
)
from src.community.knowledge_base.indexer import (
    delete_user_knowledge_records,
    upsert_user_knowledge_records,
)
from src.community.knowledge_base.locator import extract_paragraph_location, locate_document
from src.community.knowledge_base.mineru_grpc import build_structured_document_from_mineru_grpc
from src.community.knowledge_base.retriever import get_qdrant_client
from src.community.knowledge_base.structured_document import build_bbox_from_position, build_structured_document
from src.community.knowledge_base.translation_grpc import translate_blocks_to_chinese_via_grpc
from src.community.knowledge_base.user_spaces import (
    DEFAULT_KNOWLEDGE_SPACE_ID,
    create_user_knowledge_space,
    delete_user_knowledge_space,
    get_default_knowledge_space,
    get_user_knowledge_space_map,
    list_user_knowledge_spaces,
)
from src.community.knowledge_base.user_store import (
    build_user_derived_record,
    build_user_doc_public_url,
    build_user_import_ref_record,
    build_user_upload_record,
    cleanup_user_record_artifacts,
    find_user_import_record,
    find_user_record_by_source_filename,
    get_user_docs_dir,
    list_user_records,
    load_user_record,
    mark_user_record_failed,
    mark_user_record_parsed,
    mark_user_records_indexed,
    move_user_record_to_folder,
    persist_user_structured_document,
    persist_user_text_document,
    remove_user_record,
    save_user_record,
)
from src.config.knowledge_base_config import get_knowledge_base_config

router = APIRouter(prefix="/api/users/{user_id}/knowledge", tags=["knowledge-base"])

UPLOAD_CHUNK_SIZE = 1024 * 1024


class UserKnowledgeImportRequest(BaseModel):
    filename: str


class CreateUserDerivedKnowledgeRequest(BaseModel):
    title: str
    content: str
    source_kind: str
    origin_scope: str | None = None
    origin_doc_id: str | None = None
    origin_filename: str | None = None
    origin_anchor: dict[str, Any] | None = None
    derived_from_id: str | None = None
    hints: dict[str, str] | None = None
    knowledge_space_id: str | None = None
    folder_path: str | None = None


class CreateUserKnowledgeSpaceRequest(BaseModel):
    name: str
    description: str = ""


class FolderMutationRequest(BaseModel):
    path: str
    new_path: str | None = None


class UpdateUserKnowledgeContentRequest(BaseModel):
    title: str
    content: str = ""


class AppendExcerptToUserNoteRequest(BaseModel):
    excerpt_text: str
    origin_scope: str | None = None
    origin_doc_id: str | None = None
    origin_filename: str | None = None
    origin_anchor: dict[str, Any] | None = None


class MoveUserKnowledgeRecordRequest(BaseModel):
    knowledge_space_id: str | None = None
    folder_path: str | None = None


class TranslationBlockRequest(BaseModel):
    key: str
    text: str


class TranslateBlocksRequest(BaseModel):
    paragraphs: list[TranslationBlockRequest]
    source_language_hint: str | None = None


async def save_upload_file(file: UploadFile, destination: Path, chunk_size: int = UPLOAD_CHUNK_SIZE) -> int:
    size = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as buffer:
        while chunk := await file.read(chunk_size):
            buffer.write(chunk)
            size += len(chunk)
    await file.close()
    return size


def _serialize_space(space: dict[str, Any], *, stats: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "id": space.get("id"),
        "name": space.get("name"),
        "description": space.get("description"),
        "type": space.get("type"),
        "readonly": bool(space.get("readonly", False)),
        "is_default": bool(space.get("is_default", False)),
        "created_at": space.get("created_at"),
        "updated_at": space.get("updated_at"),
    }
    if stats:
        payload.update(stats)
    return payload


def _personal_folder_registry_path(user_id: str) -> Path:
    return get_user_docs_dir(user_id).parent / ".folders.json"


def _legacy_personal_folder_path(
    record: dict[str, Any],
    *,
    knowledge_space_map: dict[str, dict[str, Any]] | None = None,
) -> str | None:
    explicit_folder = normalize_folder_path(record.get("folder_path"))
    if explicit_folder:
        return explicit_folder

    space_map = knowledge_space_map or get_user_knowledge_space_map(str(record.get("user_id") or ""))
    knowledge_space_id = str(record.get("knowledge_space_id") or "")
    if not knowledge_space_id or knowledge_space_id == DEFAULT_KNOWLEDGE_SPACE_ID:
        return None
    space = space_map.get(knowledge_space_id)
    if not space or bool(space.get("readonly", False)):
        return None
    return normalize_folder_path(space.get("name"))


def _serialize_record(
    record: dict[str, Any],
    *,
    knowledge_space_map: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    source_filename = record.get("source_filename")
    preview_filename = record.get("preview_filename")
    space_map = knowledge_space_map or {}
    knowledge_space_id = str(record.get("knowledge_space_id") or "")
    if not knowledge_space_id:
        knowledge_space_id = DEFAULT_KNOWLEDGE_SPACE_ID
    knowledge_space = space_map.get(knowledge_space_id)
    document_type = (
        record.get("hints", {}).get("document_type_hint")
        if isinstance(record.get("hints"), dict)
        else None
    )
    return {
        "id": record.get("id"),
        "user_id": record.get("user_id"),
        "source_kind": record.get("source_kind"),
        "title": record.get("title"),
        "display_title": record.get("display_title"),
        "origin_scope": record.get("origin_scope"),
        "origin_doc_id": record.get("origin_doc_id"),
        "origin_filename": record.get("origin_filename"),
        "origin_anchor": record.get("origin_anchor"),
        "knowledge_space_id": knowledge_space_id,
        "knowledge_space_name": knowledge_space.get("name") if knowledge_space else None,
        "folder_path": _legacy_personal_folder_path(
            record,
            knowledge_space_map=space_map,
        ),
        "retrieval_enabled": record.get("retrieval_enabled", False),
        "filename": source_filename,
        "size": record.get("source_size", 0),
        "extension": record.get("source_extension"),
        "content_type": record.get("content_type"),
        "parse_method": record.get("parse_method"),
        "parse_status": record.get("parse_status"),
        "indexable": record.get("indexable", False),
        "artifact_url": build_user_doc_public_url(str(source_filename)) if source_filename else None,
        "preview_filename": preview_filename,
        "preview_artifact_url": build_user_doc_public_url(str(preview_filename)) if preview_filename else None,
        "structured_filename": record.get("structured_filename"),
        "index_target_filename": record.get("index_target_filename"),
        "hints": record.get("hints", {}),
        "document_type": document_type,
        "error": record.get("error"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


def _resolve_personal_knowledge_space_id(user_id: str, requested_space_id: str | None) -> str:
    available_spaces = get_user_knowledge_space_map(user_id)
    normalized = str(requested_space_id or "").strip()
    if normalized:
        space = available_spaces.get(normalized)
        if not space:
            raise HTTPException(status_code=404, detail="Knowledge space not found")
        if str(space.get("type") or "") != "personal" or bool(space.get("readonly", False)):
            raise HTTPException(status_code=400, detail="Knowledge space is read-only")
        return normalized
    return get_default_knowledge_space(user_id)["id"]


def _build_space_stats(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for record in records:
        space_id = str(record.get("knowledge_space_id") or "")
        if not space_id:
            continue
        stat = stats.setdefault(
            space_id,
            {
                "record_count": 0,
                "document_count": 0,
                "note_count": 0,
                "latest_updated_at": None,
            },
        )
        stat["record_count"] += 1
        source_kind = str(record.get("source_kind") or "")
        if source_kind in {"upload", "import_ref"}:
            stat["document_count"] += 1
        else:
            stat["note_count"] += 1
        updated_at = record.get("updated_at")
        if updated_at and (not stat["latest_updated_at"] or str(updated_at) > str(stat["latest_updated_at"])):
            stat["latest_updated_at"] = updated_at
    return stats


def _list_personal_folder_paths(
    user_id: str,
    *,
    records: list[dict[str, Any]] | None = None,
    knowledge_space_map: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    records = records if records is not None else list_user_records(user_id)
    knowledge_space_map = knowledge_space_map or get_user_knowledge_space_map(user_id)
    registry_path = _personal_folder_registry_path(user_id)
    explicit_folders = list_folder_paths(registry_path)
    implicit_folders = [
        _legacy_personal_folder_path(record, knowledge_space_map=knowledge_space_map)
        for record in records
    ]
    return ensure_folder_paths(registry_path, [*explicit_folders, *implicit_folders])


def _build_global_doc_id(filename: str) -> str:
    docs_root = resolve_project_path(get_knowledge_base_config().docs_path)
    return derive_global_doc_id(docs_root, docs_root / filename)


def _record_source_file_path(user_id: str, record: dict[str, Any]) -> Path | None:
    source_filename = record.get("source_filename")
    if not source_filename:
        return None
    return get_user_docs_dir(user_id) / str(source_filename)


def _read_record_text_content(user_id: str, record: dict[str, Any]) -> str | None:
    source_path = _record_source_file_path(user_id, record)
    if not source_path or not source_path.exists() or not source_path.is_file():
        return None
    try:
        return source_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return source_path.read_text(encoding="utf-8", errors="ignore")


def _format_origin_location(origin_anchor: dict[str, Any] | None) -> str | None:
    if not origin_anchor:
        return None

    location_parts: list[str] = []
    pdf_page_no = origin_anchor.get("pdf_page_no")
    page_no = origin_anchor.get("page_no")
    paragraph_no = origin_anchor.get("paragraph_no")

    if pdf_page_no:
        location_parts.append(f"PDF 第 {pdf_page_no} 页")
    elif page_no:
        location_parts.append(f"第 {page_no} 页")
    if paragraph_no:
        location_parts.append(f"第 {paragraph_no} 段")
    return " · ".join(location_parts) if location_parts else None


def _strip_markdown_quote_prefix(text: str) -> str:
    cleaned_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("> "):
            cleaned_lines.append(line[2:])
        elif line == ">":
            cleaned_lines.append("")
        elif line.startswith(">"):
            cleaned_lines.append(line[1:].lstrip())
        else:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip("\n")


def _extract_derived_sections(content: str) -> tuple[str | None, str, str]:
    normalized = content.replace("\r\n", "\n")
    lines = normalized.split("\n")
    title: str | None = None
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip() or None

    excerpt_heading_index = next(
        (index for index, line in enumerate(lines) if line.strip() == "## 原文摘录"),
        None,
    )
    editable_heading_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.strip() in {"## 我的摘抄笔记", "## 我的批注", "## 我的笔记", "## 我的内容"}
        ),
        None,
    )

    excerpt = ""
    if excerpt_heading_index is not None:
        excerpt_lines: list[str] = []
        for line in lines[excerpt_heading_index + 1 :]:
            if line.startswith("## "):
                break
            excerpt_lines.append(line)
        excerpt = _strip_markdown_quote_prefix("\n".join(excerpt_lines))

    editable_content = normalized.strip("\n")
    if editable_heading_index is not None:
        editable_content = "\n".join(lines[editable_heading_index + 1 :]).lstrip("\n")

    return title, excerpt, editable_content.rstrip("\n")


def _build_derived_markdown(
    *,
    title: str,
    source_kind: str,
    origin_filename: str | None,
    origin_anchor: dict[str, Any] | None,
    locked_excerpt: str,
    editable_content: str,
) -> str:
    location_label = _format_origin_location(origin_anchor)
    note_heading = "## 我的批注" if source_kind == "annotation" else "## 我的摘抄笔记"
    quote_block = locked_excerpt.strip("\n")
    quoted_excerpt = (
        "\n".join(f"> {line}" if line else ">" for line in quote_block.splitlines())
        if quote_block
        else "> "
    )
    parts = [
        f"# {title}",
        "",
        f"来源：{origin_filename or '未知来源'}",
        f"定位：{location_label}" if location_label else None,
        "",
        "## 原文摘录",
        "",
        quoted_excerpt,
        "",
        note_heading,
        "",
        editable_content.rstrip("\n"),
    ]
    return "\n".join(part for part in parts if part is not None).rstrip() + "\n"


def _extract_note_sections(content: str) -> tuple[str | None, str]:
    normalized = content.replace("\r\n", "\n")
    lines = normalized.split("\n")
    title: str | None = None
    body_lines = lines

    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip() or None
        body_lines = lines[1:]
        while body_lines and not body_lines[0].strip():
            body_lines = body_lines[1:]

    editable_content = "\n".join(body_lines).rstrip("\n")
    return title, editable_content


def _build_note_markdown(*, title: str, content: str) -> str:
    body = content.replace("\r\n", "\n").rstrip("\n")
    parts = [f"# {title}"]
    if body:
        parts.extend(["", body])
    return "\n".join(parts).rstrip() + "\n"


def _build_note_excerpt_block(
    *,
    origin_filename: str | None,
    origin_scope: str | None,
    origin_anchor: dict[str, Any] | None,
    excerpt_text: str,
) -> str:
    location_label = _format_origin_location(origin_anchor)
    quote_block = excerpt_text.strip("\n")
    quoted_excerpt = (
        "\n".join(f"> {line}" if line else ">" for line in quote_block.splitlines())
        if quote_block
        else "> "
    )
    parts = [
        "## 原文摘录",
        "",
        f"来源：{origin_filename or '未知来源'}",
        f"范围：{origin_scope}" if origin_scope else None,
        f"定位：{location_label}" if location_label else None,
        "",
        quoted_excerpt,
    ]
    return "\n".join(part for part in parts if part is not None).rstrip()


def _record_is_text_editable(record: dict[str, Any]) -> bool:
    if record.get("source_kind") in {"excerpt", "annotation", "translation", "note"}:
        return True
    if record.get("source_kind") != "upload":
        return False
    source_filename = str(record.get("source_filename") or "")
    return Path(source_filename).suffix.lower() in {".md", ".txt"}


def _build_record_editor_payload(user_id: str, record: dict[str, Any]) -> dict[str, Any]:
    raw_content = _read_record_text_content(user_id, record)
    source_kind = str(record.get("source_kind") or "")
    title = str(record.get("display_title") or record.get("title") or "未命名资料")
    origin_anchor = record.get("origin_anchor") if isinstance(record.get("origin_anchor"), dict) else None

    mode = "readonly"
    editable = False
    editable_content = ""
    locked_excerpt = ""

    if source_kind in {"excerpt", "annotation", "translation"}:
        parsed_title, parsed_excerpt, parsed_editable_content = _extract_derived_sections(raw_content or "")
        title = parsed_title or title
        locked_excerpt = str(origin_anchor.get("text") or parsed_excerpt or "").strip("\n") if origin_anchor else parsed_excerpt
        editable_content = parsed_editable_content
        mode = "derived"
        editable = True
    elif source_kind == "note":
        parsed_title, parsed_editable_content = _extract_note_sections(raw_content or "")
        title = parsed_title or title
        editable_content = parsed_editable_content
        mode = "text"
        editable = True
    elif _record_is_text_editable(record):
        editable_content = raw_content or ""
        mode = "text"
        editable = True

    return {
        "record": _serialize_record(
            record,
            knowledge_space_map=get_user_knowledge_space_map(user_id),
        ),
        "title": title,
        "mode": mode,
        "editable": editable,
        "content": raw_content or "",
        "editable_content": editable_content,
        "locked_excerpt": locked_excerpt,
        "origin_filename": record.get("origin_filename"),
        "location_label": _format_origin_location(origin_anchor),
    }


def _persist_text_record_and_reindex(
    user_id: str,
    record_id: str,
    record: dict[str, Any],
    *,
    title: str,
    persisted_content: str,
    hints: dict[str, str] | None = None,
) -> dict[str, Any]:
    source_filename = record.get("source_filename")
    if not source_filename:
        raise HTTPException(status_code=400, detail="Missing source filename")

    record["title"] = title
    record["display_title"] = title
    record["source_size"] = len(persisted_content.encode("utf-8"))

    persist_user_text_document(user_id, str(source_filename), persisted_content)
    structured_payload = build_structured_document(
        source_filename=str(source_filename),
        title=title,
        text=persisted_content,
        parser_name=str(record.get("parse_method") or "markdown"),
        hints=hints if hints is not None else (record.get("hints") or {}),
    )
    structured_filename = persist_user_structured_document(
        user_id,
        str(source_filename),
        structured_payload,
    )
    record = mark_user_record_parsed(
        user_id,
        record,
        structured_filename=structured_filename,
        preview_filename=str(source_filename),
    )
    save_user_record(user_id, record)
    indexed_record_id = str(record.get("id") or record_id)
    indexed_chunks = upsert_user_knowledge_records(user_id, [indexed_record_id])
    if indexed_chunks <= 0:
        error = "reindex failed: No chunks were indexed into Qdrant"
        _mark_user_records_index_failed(user_id, [indexed_record_id], error)
        raise HTTPException(status_code=500, detail=error)
    mark_user_records_indexed(user_id, [indexed_record_id])
    return load_user_record(user_id, record_id) or record


def _mark_user_records_index_failed(user_id: str, record_ids: list[str], error: str) -> None:
    for record_id in record_ids:
        record = load_user_record(user_id, str(record_id))
        if not record:
            continue
        record["parse_status"] = "index_failed"
        record["error"] = error
        save_user_record(user_id, record)


def _cleanup_existing_upload(user_id: str, source_filename: str) -> None:
    existing = find_user_record_by_source_filename(user_id, source_filename)
    if existing:
        existing_record_id = existing.get("id")
        if existing_record_id:
            delete_user_knowledge_records(user_id, [str(existing_record_id)])
        cleanup_user_record_artifacts(existing, user_id=user_id)
        remove_user_record(user_id, str(existing["id"]))


def _mark_user_record_index_failed(user_id: str, record_id: str, error: str) -> None:
    record = load_user_record(user_id, record_id)
    if not record:
        return
    record["parse_status"] = "index_failed"
    record["error"] = error
    save_user_record(user_id, record)


def _process_user_record_embedding(user_id: str, record_id: str) -> None:
    record = load_user_record(user_id, record_id)
    if not record or not record.get("indexable") or not record.get("index_target_path"):
        return

    record["parse_status"] = "indexing"
    record["error"] = None
    save_user_record(user_id, record)

    try:
        indexed_chunks = upsert_user_knowledge_records(user_id, [record_id])
        if indexed_chunks <= 0:
            raise ValueError("No chunks were indexed into Qdrant")
        mark_user_records_indexed(user_id, [record_id])
    except Exception as exc:
        _mark_user_record_index_failed(user_id, record_id, f"reindex failed: {exc}")


def _process_user_record_ocr(user_id: str, record_id: str) -> None:
    record = load_user_record(user_id, record_id)
    if not record or not record.get("indexable"):
        return

    source_filename = str(record.get("source_filename") or "")
    if not source_filename:
        return

    file_path = get_user_docs_dir(user_id) / source_filename
    if not file_path.exists():
        record = mark_user_record_failed(record, "source file missing")
        save_user_record(user_id, record)
        return

    record["parse_status"] = "parsing"
    record["error"] = None
    save_user_record(user_id, record)

    try:
        file_ext = file_path.suffix.lower()
        if file_ext in PDF_EXTENSIONS or file_ext in OFFICE_EXTENSIONS or file_ext in {".md", ".txt"}:
            hints = record.get("hints") or {}
            record["parse_method"] = "local_text" if file_ext in {".md", ".txt"} else "ocr_pdf_mineru_grpc"
            save_user_record(user_id, record)
            if file_ext in {".md", ".txt"}:
                structured_payload = parse_local_text(file_path, title=str(record.get("display_title") or file_path.stem), hints=hints)
            else:
                structured_payload = build_structured_document_from_mineru_grpc(
                    file_path,
                    title=str(record.get("display_title") or Path(source_filename).stem),
                    parser_name=str(record["parse_method"]),
                    hints=hints,
                    language_hint=hints.get("language_hint"),
                )
            structured_filename = persist_user_structured_document(
                user_id,
                source_filename,
                structured_payload,
            )
            record = mark_user_record_parsed(
                user_id,
                record,
                structured_filename=structured_filename,
                preview_filename=source_filename if file_ext in {".md", ".txt"} else None,
            )
            record["parse_status"] = "queued_embedding"
        else:
            record["parse_status"] = "uploaded"

        save_user_record(user_id, record)
        if record.get("index_target_path"):
            _process_user_record_embedding(user_id, record_id)
    except Exception as exc:
        record = mark_user_record_failed(record, f"parse failed: {exc}")
        save_user_record(user_id, record)


def _structured_page_payload(document: Any, *, page_no: int | None, pdf_page_no: int | None) -> dict[str, Any] | None:
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
            "source_url": build_user_doc_public_url(document.filename),
            "original_url": build_user_doc_public_url(document.filename),
        }
    return None


@router.get("/list", response_model=dict)
def list_user_knowledge_records(
    user_id: str,
    knowledge_space_id: str | None = Query(default=None),
) -> dict:
    records = list_user_records(user_id)
    knowledge_space_map = get_user_knowledge_space_map(user_id)
    if knowledge_space_id:
        records = [
            record
            for record in records
            if str(record.get("knowledge_space_id") or "") == knowledge_space_id
        ]
    indexed_count = sum(1 for record in records if record.get("parse_status") == "indexed")
    latest_updated_at = next(
        (record.get("updated_at") for record in records if record.get("updated_at")),
        None,
    )

    doc_count = 0
    try:
        config = get_knowledge_base_config()
        client = get_qdrant_client()
        collection = client.get_collection(get_user_collection_name(config.qdrant.collection_name, user_id))
        doc_count = collection.points_count or 0
    except Exception:
        doc_count = 0

    return {
        "records": [
            _serialize_record(record, knowledge_space_map=knowledge_space_map)
            for record in records
        ],
        "folders": _list_personal_folder_paths(
            user_id,
            records=records,
            knowledge_space_map=knowledge_space_map,
        ),
        "count": len(records),
        "indexed_count": indexed_count,
        "doc_count": doc_count,
        "latest_updated_at": latest_updated_at,
    }


@router.get("/spaces", response_model=dict)
def get_user_knowledge_spaces(user_id: str) -> dict:
    spaces = list_user_knowledge_spaces(user_id)
    stats_by_space = _build_space_stats(list_user_records(user_id))
    return {
        "spaces": [
            _serialize_space(space, stats=stats_by_space.get(str(space.get("id"))))
            for space in spaces
        ]
    }


@router.post("/folders", response_model=dict)
def create_user_knowledge_folder(
    user_id: str,
    payload: FolderMutationRequest,
) -> dict:
    try:
        folders = ensure_folder_path(_personal_folder_registry_path(user_id), payload.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "success": True,
        "folders": folders,
        "path": normalize_folder_path(payload.path),
        "message": "Created personal knowledge folder",
    }


@router.patch("/folders", response_model=dict)
def rename_user_knowledge_folder(
    user_id: str,
    payload: FolderMutationRequest,
) -> dict:
    normalized_old = normalize_folder_path(payload.path)
    normalized_new = normalize_folder_path(payload.new_path)
    if not normalized_old or not normalized_new:
        raise HTTPException(status_code=400, detail="Both path and new_path are required")

    records = list_user_records(user_id)
    knowledge_space_map = get_user_knowledge_space_map(user_id)
    for record in records:
        current = _legacy_personal_folder_path(record, knowledge_space_map=knowledge_space_map)
        if current == normalized_old or (current and current.startswith(f"{normalized_old}/")):
            suffix = current[len(normalized_old) :] if current else ""
            record["folder_path"] = f"{normalized_new}{suffix}"
            save_user_record(user_id, record)

    try:
        folders = rename_folder_path(
            _personal_folder_registry_path(user_id),
            normalized_old,
            normalized_new,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "success": True,
        "folders": folders,
        "path": normalized_new,
        "message": "Renamed personal knowledge folder",
    }


@router.delete("/folders", response_model=dict)
def delete_user_knowledge_folder(
    user_id: str,
    path: str = Query(..., description="Logical folder path to delete"),
) -> dict:
    normalized_path = normalize_folder_path(path)
    if not normalized_path:
        raise HTTPException(status_code=400, detail="path is required")

    records = list_user_records(user_id)
    knowledge_space_map = get_user_knowledge_space_map(user_id)
    for record in records:
        current = _legacy_personal_folder_path(record, knowledge_space_map=knowledge_space_map)
        if current == normalized_path or (current and current.startswith(f"{normalized_path}/")):
            raise HTTPException(status_code=400, detail="Folder is not empty")

    try:
        folders = delete_folder_path(_personal_folder_registry_path(user_id), normalized_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "success": True,
        "folders": folders,
        "deleted_path": normalized_path,
        "message": "Deleted personal knowledge folder",
    }


@router.post("/spaces", response_model=dict)
def create_personal_knowledge_space(
    user_id: str,
    payload: CreateUserKnowledgeSpaceRequest,
) -> dict:
    try:
        space = create_user_knowledge_space(
            user_id,
            name=payload.name,
            description=payload.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "success": True,
        "space": _serialize_space(space),
        "message": f"Created knowledge space {space['name']}",
    }


@router.delete("/spaces/{space_id}", response_model=dict)
def delete_personal_knowledge_space(
    user_id: str,
    space_id: str,
) -> dict:
    normalized_space_id = str(space_id or "").strip()
    if not normalized_space_id:
        raise HTTPException(status_code=400, detail="space_id is required")

    target_space = get_user_knowledge_space_map(user_id).get(normalized_space_id)
    if target_space is None:
        raise HTTPException(status_code=404, detail="Knowledge space not found")
    if bool(target_space.get("readonly", False)) or str(target_space.get("type") or "") != "personal":
        raise HTTPException(status_code=400, detail="Knowledge space is read-only")
    if normalized_space_id == DEFAULT_KNOWLEDGE_SPACE_ID:
        raise HTTPException(status_code=400, detail="Default knowledge space cannot be deleted")

    default_space = get_default_knowledge_space(user_id)
    moved_record_ids: list[str] = []
    for record in list_user_records(user_id):
        if str(record.get("knowledge_space_id") or "") != normalized_space_id:
            continue
        record["knowledge_space_id"] = default_space["id"]
        save_user_record(user_id, record)
        moved_record_ids.append(str(record.get("id") or ""))

    try:
        deleted_space = delete_user_knowledge_space(user_id, normalized_space_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "success": True,
        "deleted_space_id": deleted_space["id"],
        "moved_record_ids": [record_id for record_id in moved_record_ids if record_id],
        "fallback_space_id": default_space["id"],
        "message": f"Deleted knowledge space {deleted_space['name']} and moved files to {default_space['name']}",
    }


@router.post("/upload", response_model=dict)
async def upload_user_knowledge_files(
    background_tasks: BackgroundTasks,
    user_id: str,
    files: list[UploadFile] = File(...),
    language_hint: str | None = Form(default=None),
    layout_hint: str | None = Form(default=None),
    document_type_hint: str | None = Form(default=None),
    knowledge_space_id: str | None = Form(default=None),
    folder_path: str | None = Form(default=None),
) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    docs_dir = get_user_docs_dir(user_id)
    uploaded: list[dict[str, Any]] = []
    resolved_space_id = _resolve_personal_knowledge_space_id(user_id, knowledge_space_id)
    knowledge_space_map = get_user_knowledge_space_map(user_id)
    normalized_folder_path = normalize_folder_path(folder_path)
    if normalized_folder_path:
        ensure_folder_path(_personal_folder_registry_path(user_id), normalized_folder_path)
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

        _cleanup_existing_upload(user_id, safe_filename)
        file_path = docs_dir / safe_filename
        file_size = await save_upload_file(file, file_path)
        record = build_user_upload_record(
            user_id=user_id,
            source_filename=safe_filename,
            size=file_size,
            content_type=file.content_type,
            hints=hints,
            knowledge_space_id=resolved_space_id,
            folder_path=normalized_folder_path,
        )

        if record.get("indexable"):
            record["parse_status"] = "queued_ocr"

        save_user_record(user_id, record)
        uploaded.append(_serialize_record(record, knowledge_space_map=knowledge_space_map))
        if record.get("indexable"):
            background_tasks.add_task(_process_user_record_ocr, user_id, str(record["id"]))

    return {
        "success": True,
        "records": uploaded,
        "folders": _list_personal_folder_paths(
            user_id,
            records=list_user_records(user_id),
            knowledge_space_map=knowledge_space_map,
        ),
        "message": (
            f"Successfully uploaded {len(uploaded)} personal knowledge file(s); "
            "files are queued for OCR and embedding in the background"
        ),
    }


@router.post("/import-from-global", response_model=dict)
def import_global_document_reference(
    user_id: str,
    payload: UserKnowledgeImportRequest,
    knowledge_space_id: str | None = Query(default=None),
    folder_path: str | None = Query(default=None),
) -> dict:
    filename = Path(payload.filename).name
    if not filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    resolved_space_id = _resolve_personal_knowledge_space_id(user_id, knowledge_space_id)
    normalized_folder_path = normalize_folder_path(folder_path)
    if normalized_folder_path:
        ensure_folder_path(_personal_folder_registry_path(user_id), normalized_folder_path)
    docs_root = resolve_project_path(get_knowledge_base_config().docs_path)
    file_path = docs_root / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Global knowledge document not found")

    existing = find_user_import_record(
        user_id,
        filename,
        knowledge_space_id=resolved_space_id,
    )
    if existing:
        return {
            "success": True,
            "record": _serialize_record(
                existing,
                knowledge_space_map=get_user_knowledge_space_map(user_id),
            ),
            "message": f"{filename} is already in personal knowledge favorites",
        }

    record = build_user_import_ref_record(
        user_id=user_id,
        title=file_path.stem,
        origin_doc_id=_build_global_doc_id(filename),
        origin_filename=filename,
        knowledge_space_id=resolved_space_id,
        folder_path=normalized_folder_path,
    )
    save_user_record(user_id, record)
    return {
        "success": True,
        "record": _serialize_record(
            record,
            knowledge_space_map=get_user_knowledge_space_map(user_id),
        ),
        "message": f"Added {filename} to personal knowledge favorites",
    }


@router.delete("/{record_id}", response_model=dict)
def delete_user_knowledge_record(user_id: str, record_id: str) -> dict:
    record = load_user_record(user_id, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Personal knowledge record not found")

    record_id_value = str(record.get("id") or record_id)
    cleanup_user_record_artifacts(record, user_id=user_id)
    remove_user_record(user_id, record_id)
    delete_user_knowledge_records(user_id, [record_id_value])
    mark_user_records_indexed(user_id)
    return {
        "success": True,
        "message": f"Deleted personal knowledge record {record_id}",
    }


@router.delete("/{record_id}/artifacts-only", response_model=dict)
def delete_user_knowledge_record_artifacts_only(user_id: str, record_id: str) -> dict:
    """Delete all on-disk artifacts for a personal knowledge record that has NOT been indexed yet.

    Skips the Qdrant operation, making it fast for batch-deleting records in the
    uploaded / parsed / failed state.  Returns 409 if the record is currently being
    processed or has already been indexed (use the regular DELETE endpoint instead).
    """
    record = load_user_record(user_id, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Personal knowledge record not found")

    parse_status = str(record.get("parse_status") or "")
    active_statuses = {"queued", "queued_ocr", "parsing", "queued_embedding", "indexing"}
    if parse_status in active_statuses:
        raise HTTPException(status_code=409, detail=f"Record is currently being processed (status={parse_status}); cannot delete now")
    if parse_status == "indexed":
        raise HTTPException(status_code=409, detail="Record is already indexed; use the regular delete endpoint to also update the vector index")

    cleanup_user_record_artifacts(record, user_id=user_id)
    remove_user_record(user_id, record_id)
    mark_user_records_indexed(user_id)
    return {"success": True, "message": f"Deleted all artifacts for personal knowledge record {record_id}"}


@router.post("/{record_id}/reindex", response_model=dict)
def retry_user_knowledge_record_indexing(
    background_tasks: BackgroundTasks,
    user_id: str,
    record_id: str,
) -> dict:
    record = load_user_record(user_id, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Personal knowledge record not found")
    if not record.get("indexable"):
        raise HTTPException(status_code=400, detail="This file type does not support indexing")

    current_status = str(record.get("parse_status") or "")
    if current_status in {"queued", "queued_ocr", "parsing", "queued_embedding", "indexing"}:
        raise HTTPException(status_code=409, detail="This file is already being processed")

    source_filename = str(record.get("source_filename") or "")
    if not source_filename:
        raise HTTPException(status_code=400, detail="Missing source filename")
    file_path = get_user_docs_dir(user_id) / source_filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Source file missing: {source_filename}")

    should_enqueue_embedding = bool(record.get("index_target_path")) and current_status in {
        "parsed",
        "index_failed",
        "indexed",
    }

    record["error"] = None
    record["parse_status"] = "queued_embedding" if should_enqueue_embedding else "queued_ocr"
    save_user_record(user_id, record)

    if should_enqueue_embedding:
        background_tasks.add_task(_process_user_record_embedding, user_id, record_id)
        return {
            "success": True,
            "message": f"已重新加入个人文档入库队列：{source_filename}",
        }

    background_tasks.add_task(_process_user_record_ocr, user_id, record_id)
    return {
        "success": True,
        "message": f"已重新加入个人文档解析队列：{source_filename}",
    }


@router.post("/{record_id}/reparse", response_model=dict)
def reparse_user_knowledge_record(
    background_tasks: BackgroundTasks,
    user_id: str,
    record_id: str,
) -> dict:
    record = load_user_record(user_id, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Personal knowledge record not found")
    if not record.get("indexable"):
        raise HTTPException(status_code=400, detail="This file type does not support indexing")

    current_status = str(record.get("parse_status") or "")
    if current_status in {"queued", "queued_ocr", "parsing", "queued_embedding", "indexing"}:
        raise HTTPException(status_code=409, detail="This file is already being processed")

    source_filename = str(record.get("source_filename") or "")
    if not source_filename:
        raise HTTPException(status_code=400, detail="Missing source filename")
    file_path = get_user_docs_dir(user_id) / source_filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Source file missing: {source_filename}")

    record["error"] = None
    record["parse_status"] = "queued_ocr"
    save_user_record(user_id, record)
    background_tasks.add_task(_process_user_record_ocr, user_id, record_id)
    return {
        "success": True,
        "message": f"已重新加入个人文档解析队列：{source_filename}",
    }


@router.post("/{record_id}/move", response_model=dict)
def move_user_knowledge_record(
    user_id: str,
    record_id: str,
    payload: MoveUserKnowledgeRecordRequest,
) -> dict:
    resolved_space_id = _resolve_personal_knowledge_space_id(user_id, payload.knowledge_space_id)
    normalized_folder_path = normalize_folder_path(payload.folder_path)
    if normalized_folder_path:
        ensure_folder_path(_personal_folder_registry_path(user_id), normalized_folder_path)
    record = move_user_record_to_folder(
        user_id,
        record_id,
        knowledge_space_id=resolved_space_id,
        folder_path=normalized_folder_path,
    )
    if not record:
        raise HTTPException(status_code=404, detail="Personal knowledge record not found")
    return {
        "success": True,
        "record": _serialize_record(
            record,
            knowledge_space_map=get_user_knowledge_space_map(user_id),
        ),
        "message": "Moved personal knowledge record",
    }


@router.get("/{record_id}/content", response_model=dict)
def get_user_knowledge_record_content(user_id: str, record_id: str) -> dict:
    record = load_user_record(user_id, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Personal knowledge record not found")
    return _build_record_editor_payload(user_id, record)


@router.put("/{record_id}/content", response_model=dict)
def update_user_knowledge_record_content(
    user_id: str,
    record_id: str,
    payload: UpdateUserKnowledgeContentRequest,
) -> dict:
    record = load_user_record(user_id, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Personal knowledge record not found")
    if not _record_is_text_editable(record):
        raise HTTPException(status_code=400, detail="This record is not editable")

    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    editable_content = payload.content.replace("\r\n", "\n")

    if record.get("source_kind") in {"excerpt", "annotation", "translation"}:
        origin_anchor = record.get("origin_anchor") if isinstance(record.get("origin_anchor"), dict) else None
        existing_content = _read_record_text_content(user_id, record) or ""
        _, parsed_excerpt, _ = _extract_derived_sections(existing_content)
        locked_excerpt = str(origin_anchor.get("text") or parsed_excerpt or "").strip("\n") if origin_anchor else parsed_excerpt
        persisted_content = _build_derived_markdown(
            title=title,
            source_kind=str(record.get("source_kind") or ""),
            origin_filename=record.get("origin_filename"),
            origin_anchor=origin_anchor,
            locked_excerpt=locked_excerpt,
            editable_content=editable_content,
        )
    elif record.get("source_kind") == "note":
        persisted_content = _build_note_markdown(title=title, content=editable_content)
    else:
        persisted_content = editable_content

    latest = _persist_text_record_and_reindex(
        user_id,
        record_id,
        record,
        title=title,
        persisted_content=persisted_content,
    )
    return _build_record_editor_payload(user_id, latest)


@router.post("/{record_id}/append-excerpt", response_model=dict)
def append_excerpt_to_user_record(
    user_id: str,
    record_id: str,
    payload: AppendExcerptToUserNoteRequest,
) -> dict:
    record = load_user_record(user_id, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Personal knowledge record not found")
    source_kind = str(record.get("source_kind") or "")
    if source_kind not in {"note", "excerpt", "annotation", "translation"}:
        raise HTTPException(status_code=400, detail="This record type does not support appended excerpts")
    if not _record_is_text_editable(record):
        raise HTTPException(status_code=400, detail="This record is not editable")

    excerpt_text = payload.excerpt_text.replace("\r\n", "\n").strip("\n")
    if not excerpt_text.strip():
        raise HTTPException(status_code=400, detail="excerpt_text is required")

    existing_content = _read_record_text_content(user_id, record) or ""
    if source_kind in {"excerpt", "annotation", "translation"}:
        parsed_title, parsed_locked_excerpt, parsed_editable_content = _extract_derived_sections(existing_content)
        origin_anchor = record.get("origin_anchor") if isinstance(record.get("origin_anchor"), dict) else None
        locked_excerpt = str(origin_anchor.get("text") or parsed_locked_excerpt or "").strip("\n") if origin_anchor else parsed_locked_excerpt
    else:
        parsed_title, parsed_editable_content = _extract_note_sections(existing_content)
        locked_excerpt = ""

    title = str(parsed_title or record.get("display_title") or record.get("title") or "未命名笔记").strip()
    if not title:
        title = "未命名笔记"

    excerpt_block = _build_note_excerpt_block(
        origin_filename=payload.origin_filename,
        origin_scope=payload.origin_scope,
        origin_anchor=payload.origin_anchor,
        excerpt_text=excerpt_text,
    )
    next_body_parts = [parsed_editable_content.rstrip("\n"), excerpt_block]
    next_body = "\n\n".join(part for part in next_body_parts if part)
    if source_kind in {"excerpt", "annotation", "translation"}:
        persisted_content = _build_derived_markdown(
            title=title,
            source_kind=source_kind,
            origin_filename=record.get("origin_filename"),
            origin_anchor=record.get("origin_anchor") if isinstance(record.get("origin_anchor"), dict) else None,
            locked_excerpt=locked_excerpt,
            editable_content=next_body,
        )
    else:
        persisted_content = _build_note_markdown(title=title, content=next_body)

    latest = _persist_text_record_and_reindex(
        user_id,
        record_id,
        record,
        title=title,
        persisted_content=persisted_content,
    )
    return {
        "success": True,
        "record": _serialize_record(
            latest,
            knowledge_space_map=get_user_knowledge_space_map(user_id),
        ),
        "message": "Appended excerpt to personal note",
    }


@router.post("/derived", response_model=dict)
def create_user_derived_knowledge_record(
    user_id: str,
    payload: CreateUserDerivedKnowledgeRequest,
) -> dict:
    source_kind = payload.source_kind.strip().lower()
    if source_kind not in {"excerpt", "annotation", "note", "translation"}:
        raise HTTPException(status_code=400, detail="source_kind must be excerpt, annotation, note, or translation")

    title = payload.title.strip()
    content = payload.content.replace("\r\n", "\n")
    trimmed_content = content.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    if source_kind != "note" and not trimmed_content:
        raise HTTPException(status_code=400, detail="content is required")

    persisted_content = _build_note_markdown(title=title, content=content) if source_kind == "note" else trimmed_content
    resolved_space_id = _resolve_personal_knowledge_space_id(user_id, payload.knowledge_space_id)
    normalized_folder_path = normalize_folder_path(payload.folder_path)
    if normalized_folder_path:
        ensure_folder_path(_personal_folder_registry_path(user_id), normalized_folder_path)

    temp_record = build_user_derived_record(
        user_id=user_id,
        source_kind=source_kind,
        title=title,
        source_filename="pending.md",
        size=0,
        origin_scope=payload.origin_scope,
        origin_doc_id=payload.origin_doc_id,
        origin_filename=payload.origin_filename,
        origin_anchor=payload.origin_anchor,
        derived_from_id=payload.derived_from_id,
        hints=payload.hints,
        knowledge_space_id=resolved_space_id,
        folder_path=normalized_folder_path,
    )
    source_filename = f"{temp_record['id']}.md"
    encoded_content = persisted_content.encode("utf-8")
    record = build_user_derived_record(
        user_id=user_id,
        source_kind=source_kind,
        title=title,
        source_filename=source_filename,
        size=len(encoded_content),
        origin_scope=payload.origin_scope,
        origin_doc_id=payload.origin_doc_id,
        origin_filename=payload.origin_filename,
        origin_anchor=payload.origin_anchor,
        derived_from_id=payload.derived_from_id,
        hints=payload.hints,
        knowledge_space_id=resolved_space_id,
        folder_path=normalized_folder_path,
    )
    record["id"] = temp_record["id"]
    record["created_at"] = temp_record["created_at"]
    record["updated_at"] = temp_record["updated_at"]

    persist_user_text_document(user_id, source_filename, persisted_content)
    structured_payload = build_structured_document(
        source_filename=source_filename,
        title=title,
        text=persisted_content,
        parser_name=str(record["parse_method"]),
        hints=payload.hints or {},
    )
    structured_filename = persist_user_structured_document(
        user_id,
        source_filename,
        structured_payload,
    )
    record = mark_user_record_parsed(
        user_id,
        record,
        structured_filename=structured_filename,
        preview_filename=source_filename,
    )
    save_user_record(user_id, record)
    indexed_record_id = str(record["id"])
    indexed_chunks = upsert_user_knowledge_records(user_id, [indexed_record_id])
    if indexed_chunks <= 0:
        error = "reindex failed: No chunks were indexed into Qdrant"
        _mark_user_records_index_failed(user_id, [indexed_record_id], error)
        raise HTTPException(status_code=500, detail=error)
    mark_user_records_indexed(user_id, [indexed_record_id])
    latest = load_user_record(user_id, str(record["id"])) or record
    return {
        "success": True,
        "record": _serialize_record(
            latest,
            knowledge_space_map=get_user_knowledge_space_map(user_id),
        ),
        "message": f"Created personal {source_kind} document",
    }


@router.get("/docs/{filename}", summary="Get a personal knowledge document by filename")
def get_user_knowledge_document(
    user_id: str,
    filename: str,
    download: bool = Query(default=False),
    page: int | None = Query(default=None),
):
    if "/" in filename or "\\" in filename or filename.startswith(".."):
        raise HTTPException(status_code=400, detail="Invalid filename")

    docs_dir = get_user_docs_dir(user_id)
    file_path = docs_dir / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Document not found")

    ext = file_path.suffix.lower()
    if download:
        media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return FileResponse(path=file_path, filename=filename, media_type=media_type)
    if ext == ".pdf":
        headers = {}
        if page is not None:
            headers["X-PDF-Page"] = str(page)
        return FileResponse(path=file_path, media_type="application/pdf", headers=headers)
    return FileResponse(path=file_path, media_type="text/markdown")


@router.get("/docs/{filename}/structured-page", response_model=dict)
def get_user_knowledge_structured_page(
    response: Response,
    user_id: str,
    filename: str,
    page_no: int | None = Query(default=None),
    pdf_page_no: int | None = Query(default=None),
) -> dict:
    if page_no is None and pdf_page_no is None:
        raise HTTPException(status_code=400, detail="page_no or pdf_page_no is required")

    document = locate_document(thread_id=None, user_id=user_id, filename=filename)
    if not document:
        raise HTTPException(status_code=404, detail="Structured document not found")

    page_payload = _structured_page_payload(document, page_no=page_no, pdf_page_no=pdf_page_no)
    if page_payload is not None:
        response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=3600"
        return page_payload
    raise HTTPException(status_code=404, detail="Structured page not found")


@router.post("/docs/{filename}/translate-blocks", response_model=dict)
def translate_user_knowledge_blocks(
    user_id: str,
    filename: str,
    payload: TranslateBlocksRequest,
) -> dict:
    document = locate_document(thread_id=None, user_id=user_id, filename=filename)
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


@router.get("/docs/{filename}/paragraph-location", response_model=dict)
def get_user_knowledge_paragraph_location(
    user_id: str,
    filename: str,
    page_no: int | None = Query(default=None),
    pdf_page_no: int | None = Query(default=None),
    paragraph_no: int | None = Query(default=None),
) -> dict:
    if page_no is None and pdf_page_no is None and paragraph_no is None:
        raise HTTPException(status_code=400, detail="At least one of page_no, pdf_page_no, or paragraph_no is required")

    document = locate_document(thread_id=None, user_id=user_id, filename=filename)
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
    return {
        "doc_id": document.doc_id,
        "scope": document.scope,
        "filename": document.filename,
        "title": document.title,
        "page_count": len(list(document.payload.get("pages") or [])),
        "page_no": excerpt.get("page_no"),
        "pdf_page_no": excerpt.get("pdf_page_no"),
        "book_page_no": excerpt.get("book_page_no"),
        "paragraph_no": excerpt.get("paragraph_no"),
        "bbox": excerpt.get("bbox") or build_bbox_from_position(excerpt.get("position")),
        "page_meta": excerpt.get("page_meta"),
        "text": str(excerpt.get("text") or ""),
        "source_url": build_user_doc_public_url(document.filename),
        "original_url": build_user_doc_public_url(document.filename),
    }


@router.get("/docs/{filename}/page-image", summary="Render a personal knowledge PDF page image")
def get_user_knowledge_document_page_image(
    request: Request,
    user_id: str,
    filename: str,
    pdf_page_no: int = Query(..., ge=1),
    dpi: int = Query(default=120, ge=72, le=300),
):
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    document_record = locate_document(thread_id=None, user_id=user_id, filename=filename)
    if not document_record:
        raise HTTPException(status_code=404, detail="Document not found")

    file_path = get_user_docs_dir(user_id) / document_record.filename
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
