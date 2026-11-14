"""Storage helpers for per-user personal knowledge records."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from src.community.knowledge_base.book_metadata import derive_book_metadata_filename, get_book_metadata_dir, normalize_folder_path
from src.community.knowledge_base.document_parsers import infer_parse_method as infer_document_parse_method
from src.community.knowledge_base.structured_document import save_structured_document
from src.community.knowledge_base.user_spaces import (
    DEFAULT_KNOWLEDGE_SPACE_ID,
    get_default_knowledge_space,
    get_user_knowledge_space_map,
)
from src.config.paths import get_paths

TEXT_PREVIEW_EXTENSIONS = {".md", ".txt"}
USER_RETRIEVAL_ENABLED_SOURCE_KINDS = {"upload", "excerpt", "annotation", "translation", "note"}
USER_RETRIEVAL_DISABLED_SOURCE_KINDS = {"import_ref"}
USER_SOURCE_KINDS = USER_RETRIEVAL_ENABLED_SOURCE_KINDS | USER_RETRIEVAL_DISABLED_SOURCE_KINDS


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_path(user_id: str, record_id: str) -> Path:
    return get_paths().user_knowledge_catalog_dir(user_id) / f"{record_id}.json"


def _write_record(user_id: str, record: dict[str, Any], *, touch_updated_at: bool) -> None:
    record["user_id"] = user_id
    if touch_updated_at:
        record["updated_at"] = _utc_now()
    _record_path(user_id, str(record["id"])).write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _normalize_record_knowledge_space(
    user_id: str,
    record: dict[str, Any],
    *,
    space_map: dict[str, dict[str, Any]] | None = None,
) -> bool:
    available_spaces = space_map or get_user_knowledge_space_map(user_id)
    existing_space_id = str(record.get("knowledge_space_id") or "").strip()
    if existing_space_id and existing_space_id in available_spaces:
        return False

    default_space = available_spaces.get(DEFAULT_KNOWLEDGE_SPACE_ID) or get_default_knowledge_space(user_id)
    record["knowledge_space_id"] = default_space["id"]
    return True


def ensure_user_knowledge_dirs(user_id: str) -> None:
    get_paths().ensure_user_knowledge_dirs(user_id)


def get_user_docs_dir(user_id: str) -> Path:
    ensure_user_knowledge_dirs(user_id)
    return get_paths().user_knowledge_docs_dir(user_id)


def get_user_ingestion_dir(user_id: str) -> Path:
    ensure_user_knowledge_dirs(user_id)
    return get_paths().user_knowledge_ingestion_dir(user_id)


def get_user_derived_dir(user_id: str) -> Path:
    ensure_user_knowledge_dirs(user_id)
    return get_paths().user_knowledge_derived_dir(user_id)


def get_user_catalog_dir(user_id: str) -> Path:
    ensure_user_knowledge_dirs(user_id)
    return get_paths().user_knowledge_catalog_dir(user_id)


def build_user_doc_public_url(filename: str) -> str:
    return f"/api/secure-knowledge/users/me/knowledge/docs/{quote(filename)}"


def build_user_doc_urls(user_id: str, filename: str) -> dict[str, str]:
    path = str(get_user_docs_dir(user_id) / filename)
    return {
        "path": path,
        "artifact_url": build_user_doc_public_url(filename),
    }


def build_user_ingestion_urls(user_id: str, filename: str) -> dict[str, str]:
    return {
        "path": str(get_user_ingestion_dir(user_id) / filename),
    }


def infer_parse_method(filename: str) -> tuple[str, bool]:
    return infer_document_parse_method(filename)


def _base_user_record(
    *,
    user_id: str,
    source_kind: str,
    title: str,
    retrieval_enabled: bool,
    origin_scope: str | None = None,
    origin_doc_id: str | None = None,
    origin_filename: str | None = None,
    origin_anchor: dict[str, Any] | None = None,
    knowledge_space_id: str | None = None,
    folder_path: str | None = None,
) -> dict[str, Any]:
    if source_kind not in USER_SOURCE_KINDS:
        raise ValueError(f"Unsupported user knowledge source kind: {source_kind}")

    now = _utc_now()
    return {
        "id": f"uk_{uuid4().hex}",
        "user_id": user_id,
        "source_kind": source_kind,
        "title": title,
        "display_title": title,
        "origin_scope": origin_scope,
        "origin_doc_id": origin_doc_id,
        "origin_filename": origin_filename,
        "origin_anchor": origin_anchor,
        "knowledge_space_id": knowledge_space_id or DEFAULT_KNOWLEDGE_SPACE_ID,
        "folder_path": normalize_folder_path(folder_path),
        "derived_from_id": None,
        "retrieval_enabled": retrieval_enabled,
        "created_at": now,
        "updated_at": now,
    }


def build_user_upload_record(
    *,
    user_id: str,
    source_filename: str,
    size: int,
    content_type: str | None = None,
    hints: dict[str, str] | None = None,
    knowledge_space_id: str | None = None,
    folder_path: str | None = None,
) -> dict[str, Any]:
    parse_method, indexable = infer_parse_method(source_filename)
    urls = build_user_doc_urls(user_id, source_filename)
    source_extension = Path(source_filename).suffix.lower()
    record = _base_user_record(
        user_id=user_id,
        source_kind="upload",
        title=Path(source_filename).stem,
        retrieval_enabled=True,
        knowledge_space_id=knowledge_space_id,
        folder_path=folder_path,
    )
    record.update(
        {
            "source_filename": source_filename,
            "source_extension": source_extension,
            "source_size": size,
            "content_type": content_type,
            "parse_method": parse_method,
            "parse_status": "uploaded",
            "indexable": indexable,
            "source_path": urls["path"],
            "source_artifact_url": urls["artifact_url"],
            "preview_filename": source_filename if source_extension in TEXT_PREVIEW_EXTENSIONS else None,
            "preview_path": urls["path"] if source_extension in TEXT_PREVIEW_EXTENSIONS else None,
            "preview_artifact_url": urls["artifact_url"] if source_extension in TEXT_PREVIEW_EXTENSIONS else None,
            "structured_filename": None,
            "structured_path": None,
            "structured_artifact_url": None,
            "index_target_filename": None,
            "index_target_path": None,
            "index_target_artifact_url": None,
            "index_target_format": None,
            "hints": hints or {},
            "error": None,
        }
    )
    return record


def build_user_import_ref_record(
    *,
    user_id: str,
    title: str,
    origin_doc_id: str | None,
    origin_filename: str,
    knowledge_space_id: str | None = None,
    folder_path: str | None = None,
) -> dict[str, Any]:
    record = _base_user_record(
        user_id=user_id,
        source_kind="import_ref",
        title=title,
        retrieval_enabled=False,
        origin_scope="global",
        origin_doc_id=origin_doc_id,
        origin_filename=origin_filename,
        knowledge_space_id=knowledge_space_id,
        folder_path=folder_path,
    )
    record.update(
        {
            "source_filename": None,
            "source_extension": Path(origin_filename).suffix.lower(),
            "source_size": 0,
            "content_type": None,
            "parse_method": "reference_only",
            "parse_status": "imported",
            "indexable": False,
            "source_path": None,
            "source_artifact_url": None,
            "preview_filename": None,
            "preview_path": None,
            "preview_artifact_url": None,
            "structured_filename": None,
            "structured_path": None,
            "structured_artifact_url": None,
            "index_target_filename": None,
            "index_target_path": None,
            "index_target_artifact_url": None,
            "index_target_format": None,
            "hints": {},
            "error": None,
        }
    )
    return record


def build_user_derived_record(
    *,
    user_id: str,
    source_kind: str,
    title: str,
    source_filename: str,
    size: int,
    origin_scope: str | None,
    origin_doc_id: str | None,
    origin_filename: str | None,
    origin_anchor: dict[str, Any] | None = None,
    derived_from_id: str | None = None,
    hints: dict[str, str] | None = None,
    knowledge_space_id: str | None = None,
    folder_path: str | None = None,
) -> dict[str, Any]:
    parse_method, indexable = infer_parse_method(source_filename)
    urls = build_user_doc_urls(user_id, source_filename)
    record = _base_user_record(
        user_id=user_id,
        source_kind=source_kind,
        title=title,
        retrieval_enabled=True,
        origin_scope=origin_scope,
        origin_doc_id=origin_doc_id,
        origin_filename=origin_filename,
        origin_anchor=origin_anchor,
        knowledge_space_id=knowledge_space_id,
        folder_path=folder_path,
    )
    record["derived_from_id"] = derived_from_id
    record.update(
        {
            "source_filename": source_filename,
            "source_extension": Path(source_filename).suffix.lower(),
            "source_size": size,
            "content_type": "text/markdown",
            "parse_method": parse_method,
            "parse_status": "uploaded",
            "indexable": indexable,
            "source_path": urls["path"],
            "source_artifact_url": urls["artifact_url"],
            "preview_filename": source_filename,
            "preview_path": urls["path"],
            "preview_artifact_url": urls["artifact_url"],
            "structured_filename": None,
            "structured_path": None,
            "structured_artifact_url": None,
            "index_target_filename": None,
            "index_target_path": None,
            "index_target_artifact_url": None,
            "index_target_format": None,
            "hints": hints or {},
            "error": None,
        }
    )
    return record


def save_user_record(user_id: str, record: dict[str, Any]) -> None:
    _write_record(user_id, record, touch_updated_at=True)


def load_user_record(user_id: str, record_id: str) -> dict[str, Any] | None:
    path = _record_path(user_id, record_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if payload.get("schema_version") == 1:
        return None
    if _normalize_record_knowledge_space(user_id, payload):
        _write_record(user_id, payload, touch_updated_at=False)
    return payload


def list_user_records(user_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    space_map = get_user_knowledge_space_map(user_id)
    for path in sorted(get_user_catalog_dir(user_id).glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("schema_version") == 1:
            continue
        if _normalize_record_knowledge_space(user_id, payload, space_map=space_map):
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        records.append(payload)
    records.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return records


def remove_user_record(user_id: str, record_id: str) -> None:
    path = _record_path(user_id, record_id)
    if path.exists():
        path.unlink()


def move_user_record_to_space(user_id: str, record_id: str, knowledge_space_id: str) -> dict[str, Any] | None:
    record = load_user_record(user_id, record_id)
    if record is None:
        return None
    record["knowledge_space_id"] = knowledge_space_id
    save_user_record(user_id, record)
    return record


def move_user_record_to_folder(
    user_id: str,
    record_id: str,
    *,
    folder_path: str | None = None,
    knowledge_space_id: str | None = None,
) -> dict[str, Any] | None:
    record = load_user_record(user_id, record_id)
    if record is None:
        return None
    if knowledge_space_id:
        record["knowledge_space_id"] = knowledge_space_id
    record["folder_path"] = normalize_folder_path(folder_path)
    save_user_record(user_id, record)
    return record


def find_user_record_by_source_filename(user_id: str, source_filename: str) -> dict[str, Any] | None:
    for record in list_user_records(user_id):
        if record.get("source_filename") == source_filename:
            return record
    return None


def find_user_import_record(
    user_id: str,
    origin_filename: str,
    *,
    knowledge_space_id: str | None = None,
) -> dict[str, Any] | None:
    for record in list_user_records(user_id):
        if record.get("source_kind") != "import_ref":
            continue
        if record.get("origin_filename") == origin_filename:
            if knowledge_space_id and str(record.get("knowledge_space_id") or "") != knowledge_space_id:
                continue
            return record
    return None


def mark_user_record_parsed(
    user_id: str,
    record: dict[str, Any],
    *,
    structured_filename: str,
    preview_filename: str | None = None,
) -> dict[str, Any]:
    structured_urls = build_user_ingestion_urls(user_id, structured_filename)
    record.update(
        {
            "parse_status": "parsed",
            "structured_filename": structured_filename,
            "structured_path": structured_urls["path"],
            "structured_artifact_url": None,
            "index_target_filename": structured_filename,
            "index_target_path": structured_urls["path"],
            "index_target_artifact_url": None,
            "index_target_format": "structured_json",
            "error": None,
        }
    )
    if preview_filename:
        preview_urls = build_user_doc_urls(user_id, preview_filename)
        record.update(
            {
                "preview_filename": preview_filename,
                "preview_path": preview_urls["path"],
                "preview_artifact_url": preview_urls["artifact_url"],
            }
        )
    return record


def mark_user_record_failed(record: dict[str, Any], error: str) -> dict[str, Any]:
    record.update(
        {
            "parse_status": "failed",
            "error": error,
            "structured_filename": None,
            "structured_path": None,
            "structured_artifact_url": None,
            "index_target_filename": None,
            "index_target_path": None,
            "index_target_artifact_url": None,
            "index_target_format": None,
        }
    )
    return record


def mark_user_records_indexed(user_id: str, record_ids: list[str] | None = None) -> None:
    allowed_record_ids = {str(record_id) for record_id in record_ids} if record_ids else None
    for record in list_user_records(user_id):
        record_id = str(record.get("id") or "")
        if allowed_record_ids is not None and record_id not in allowed_record_ids:
            continue
        target_path = record.get("index_target_path")
        if not record.get("retrieval_enabled") or not target_path:
            continue
        if not Path(str(target_path)).exists():
            continue
        record["parse_status"] = "indexed"
        save_user_record(user_id, record)


def persist_user_structured_document(
    user_id: str,
    source_filename: str,
    payload: dict[str, Any],
) -> str:
    path = save_structured_document(get_user_ingestion_dir(user_id), source_filename, payload)
    return path.name


def persist_user_text_document(
    user_id: str,
    source_filename: str,
    content: str,
) -> str:
    path = get_user_docs_dir(user_id) / source_filename
    path.write_text(content, encoding="utf-8")
    return path.name


def cleanup_user_record_artifacts(record: dict[str, Any], *, user_id: str | None = None) -> None:
    def _unlink_if_exists(path_value: Any) -> None:
        if not path_value:
            return
        try:
            candidate = Path(str(path_value))
            if candidate.exists() and candidate.is_file():
                candidate.unlink()
        except OSError:
            return

    source_path = record.get("source_path")
    _unlink_if_exists(source_path)

    structured_path = record.get("structured_path")
    _unlink_if_exists(structured_path)

    preview_filename = record.get("preview_filename")
    source_filename = record.get("source_filename")
    preview_path = record.get("preview_path")
    if preview_path and preview_filename and preview_filename != source_filename:
        _unlink_if_exists(preview_path)

    if user_id and source_filename:
        docs_dir = get_user_docs_dir(user_id)
        book_meta_path = get_book_metadata_dir(docs_dir) / derive_book_metadata_filename(str(source_filename))
        _unlink_if_exists(book_meta_path)
