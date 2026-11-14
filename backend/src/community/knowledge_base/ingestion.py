"""Helpers for tracking upload ingestion and parse outputs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.community.knowledge_base.document_parsers import infer_parse_method as infer_document_parse_method
from src.community.knowledge_base.structured_document import save_structured_document
from src.config.paths import VIRTUAL_PATH_PREFIX, get_paths

TEXT_EXTENSIONS = {".md", ".txt"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_ingestion_dir(thread_id: str) -> Path:
    """Return the metadata directory for a thread's upload ingestion records."""
    ingestion_dir = get_paths().sandbox_uploads_dir(thread_id) / ".ingestion"
    ingestion_dir.mkdir(parents=True, exist_ok=True)
    return ingestion_dir


def _record_path(thread_id: str, source_filename: str) -> Path:
    return get_ingestion_dir(thread_id) / f"{source_filename}.json"


def build_upload_urls(thread_id: str, filename: str) -> dict[str, str]:
    """Build host/sandbox/http paths for an uploaded artifact."""
    relative_path = str(get_paths().sandbox_uploads_dir(thread_id) / filename)
    virtual_path = f"{VIRTUAL_PATH_PREFIX}/uploads/{filename}"
    artifact_url = f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{filename}"
    return {
        "path": relative_path,
        "virtual_path": virtual_path,
        "artifact_url": artifact_url,
    }


def build_ingestion_urls(thread_id: str, filename: str) -> dict[str, str]:
    """Build host/sandbox/http paths for an ingestion artifact."""
    relative_path = str(get_ingestion_dir(thread_id) / filename)
    virtual_path = f"{VIRTUAL_PATH_PREFIX}/uploads/.ingestion/{filename}"
    artifact_url = f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/.ingestion/{filename}"
    return {
        "path": relative_path,
        "virtual_path": virtual_path,
        "artifact_url": artifact_url,
    }


def infer_parse_method(filename: str) -> tuple[str, bool]:
    """Infer the initial parse method and whether the file is indexable."""
    return infer_document_parse_method(filename)


def build_ingestion_record(
    thread_id: str,
    source_filename: str,
    size: int,
    content_type: str | None = None,
    hints: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Create a baseline ingestion record for an uploaded source file."""
    parse_method, indexable = infer_parse_method(source_filename)
    urls = build_upload_urls(thread_id, source_filename)
    now = _utc_now()
    return {
        "source_filename": source_filename,
        "display_title": Path(source_filename).stem,
        "source_extension": Path(source_filename).suffix.lower(),
        "source_size": size,
        "content_type": content_type,
        "thread_id": thread_id,
        "parse_method": parse_method,
        "parse_status": "uploaded",
        "indexable": indexable,
        "source_path": urls["path"],
        "source_virtual_path": urls["virtual_path"],
        "source_artifact_url": urls["artifact_url"],
        "preview_filename": source_filename if Path(source_filename).suffix.lower() in TEXT_EXTENSIONS else None,
        "preview_path": urls["path"] if Path(source_filename).suffix.lower() in TEXT_EXTENSIONS else None,
        "preview_virtual_path": urls["virtual_path"] if Path(source_filename).suffix.lower() in TEXT_EXTENSIONS else None,
        "preview_artifact_url": urls["artifact_url"] if Path(source_filename).suffix.lower() in TEXT_EXTENSIONS else None,
        "structured_filename": None,
        "structured_path": None,
        "structured_virtual_path": None,
        "structured_artifact_url": None,
        "index_target_filename": None,
        "index_target_path": None,
        "index_target_virtual_path": None,
        "index_target_artifact_url": None,
        "index_target_format": None,
        "hints": hints or {},
        "error": None,
        "created_at": now,
        "updated_at": now,
    }


def save_ingestion_record(thread_id: str, source_filename: str, record: dict[str, Any]) -> None:
    """Persist an ingestion record."""
    record["thread_id"] = thread_id
    record["updated_at"] = _utc_now()
    _record_path(thread_id, source_filename).write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_ingestion_record(thread_id: str, source_filename: str) -> dict[str, Any] | None:
    """Load a single ingestion record by source filename."""
    path = _record_path(thread_id, source_filename)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_ingestion_records(thread_id: str) -> list[dict[str, Any]]:
    """Load all ingestion records for a thread."""
    ingestion_dir = get_ingestion_dir(thread_id)
    records: list[dict[str, Any]] = []
    for path in sorted(ingestion_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("schema_version") == 1:
                continue
            records.append(payload)
        except Exception:
            continue
    return records


def find_ingestion_record(thread_id: str, filename: str) -> dict[str, Any] | None:
    """Find an ingestion record by either source filename or index target filename."""
    record = load_ingestion_record(thread_id, filename)
    if record:
        return record
    for candidate in list_ingestion_records(thread_id):
        if candidate.get("index_target_filename") == filename:
            return candidate
    return None


def remove_ingestion_record(thread_id: str, source_filename: str) -> None:
    """Delete a persisted ingestion record."""
    path = _record_path(thread_id, source_filename)
    if path.exists():
        path.unlink()


def mark_record_parsed(
    thread_id: str,
    record: dict[str, Any],
    *,
    structured_filename: str,
    preview_filename: str | None = None,
) -> dict[str, Any]:
    """Update an ingestion record after a parse step generated indexable text."""
    structured_urls = build_ingestion_urls(thread_id, structured_filename)
    record.update(
        {
            "parse_status": "parsed",
            "structured_filename": structured_filename,
            "structured_path": structured_urls["path"],
            "structured_virtual_path": structured_urls["virtual_path"],
            "structured_artifact_url": structured_urls["artifact_url"],
            "index_target_filename": structured_filename,
            "index_target_path": structured_urls["path"],
            "index_target_virtual_path": structured_urls["virtual_path"],
            "index_target_artifact_url": structured_urls["artifact_url"],
            "index_target_format": "structured_json",
            "error": None,
        }
    )
    if preview_filename:
        preview_urls = build_upload_urls(thread_id, preview_filename)
        record.update(
            {
                "preview_filename": preview_filename,
                "preview_path": preview_urls["path"],
                "preview_virtual_path": preview_urls["virtual_path"],
                "preview_artifact_url": preview_urls["artifact_url"],
            }
        )
    return record


def mark_record_failed(record: dict[str, Any], error: str) -> dict[str, Any]:
    """Update an ingestion record after a parse step failed."""
    record.update(
        {
            "parse_status": "failed",
            "error": error,
            "structured_filename": None,
            "structured_path": None,
            "structured_virtual_path": None,
            "structured_artifact_url": None,
            "index_target_filename": None,
            "index_target_path": None,
            "index_target_virtual_path": None,
            "index_target_artifact_url": None,
            "index_target_format": None,
        }
    )
    return record


def mark_thread_records_indexed(thread_id: str) -> None:
    """Mark indexable records as indexed when their index targets are present."""
    for record in list_ingestion_records(thread_id):
        target_path = record.get("index_target_path")
        if not record.get("indexable") or not target_path:
            continue
        if not Path(str(target_path)).exists():
            continue
        record["parse_status"] = "indexed"
        save_ingestion_record(thread_id, record["source_filename"], record)


def build_record_lookup(
    thread_id: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Build lookups keyed by source filename and index target filename."""
    by_source: dict[str, dict[str, Any]] = {}
    by_index_target: dict[str, dict[str, Any]] = {}
    for record in list_ingestion_records(thread_id):
        source_filename = record.get("source_filename")
        if source_filename:
            by_source[source_filename] = record
        index_target_filename = record.get("index_target_filename")
        if index_target_filename:
            by_index_target[index_target_filename] = record
    return by_source, by_index_target


def persist_thread_structured_document(
    thread_id: str,
    source_filename: str,
    payload: dict[str, Any],
) -> str:
    """Persist a structured document payload for a thread upload."""
    path = save_structured_document(get_ingestion_dir(thread_id), source_filename, payload)
    return path.name
