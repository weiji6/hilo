"""Upload router for handling file uploads."""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from src.community.knowledge_base.book_metadata_runtime import maybe_generate_book_metadata
from src.community.knowledge_base.document_parsers import OFFICE_EXTENSIONS, PDF_EXTENSIONS
from src.community.knowledge_base.ingestion import (
    build_ingestion_record,
    build_ingestion_urls,
    build_record_lookup,
    find_ingestion_record,
    mark_record_failed,
    mark_record_parsed,
    persist_thread_structured_document,
    remove_ingestion_record,
    save_ingestion_record,
)
from src.community.knowledge_base.mineru_api import build_structured_document_from_mineru_api
from src.community.knowledge_base.mineru_grpc import build_structured_document_from_mineru_grpc
from src.config.knowledge_base_config import get_knowledge_base_config
from src.config.paths import VIRTUAL_PATH_PREFIX, get_paths
from src.sandbox.sandbox_provider import get_sandbox_provider

logger = logging.getLogger(__name__)

UPLOAD_CHUNK_SIZE = 1024 * 1024

router = APIRouter(prefix="/api/threads/{thread_id}/uploads", tags=["uploads"])

class UploadResponse(BaseModel):
    """Response model for file upload."""

    success: bool
    files: list[dict[str, Any]]
    message: str


def get_uploads_dir(thread_id: str) -> Path:
    """Get the uploads directory for a thread.

    Args:
        thread_id: The thread ID.

    Returns:
        Path to the uploads directory.
    """
    base_dir = get_paths().sandbox_uploads_dir(thread_id)
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


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


@router.post("", response_model=UploadResponse)
async def upload_files(
    thread_id: str,
    files: list[UploadFile] = File(...),
    language_hint: str | None = Form(default=None),
    layout_hint: str | None = Form(default=None),
    document_type_hint: str | None = Form(default=None),
) -> UploadResponse:
    """Upload multiple files to a thread's uploads directory.

    For PDF, PPT, Excel, and Word files, text is extracted and saved as structured JSON.
    Original files remain in /mnt/user-data/uploads.

    Args:
        thread_id: The thread ID to upload files to.
        files: List of files to upload.

    Returns:
        Upload response with success status and file information.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    uploads_dir = get_uploads_dir(thread_id)
    uploaded_files = []
    hints = {
        key: value
        for key, value in {
            "language_hint": language_hint,
            "layout_hint": layout_hint,
            "document_type_hint": document_type_hint,
        }.items()
        if value
    }

    sandbox_provider = get_sandbox_provider()
    sandbox_id = sandbox_provider.acquire(thread_id)
    sandbox = sandbox_provider.get(sandbox_id)
    is_local_sandbox = sandbox_id == "local"
    metadata_config = get_knowledge_base_config().book_metadata

    for file in files:
        if not file.filename:
            continue

        try:
            # Normalize filename to prevent path traversal
            safe_filename = Path(file.filename).name
            if not safe_filename:
                logger.warning(f"Skipping file with unsafe filename: {file.filename!r}")
                continue

            # Save the original file
            file_path = uploads_dir / safe_filename
            file_size = await save_upload_file(file, file_path)
            record = build_ingestion_record(
                thread_id=thread_id,
                source_filename=safe_filename,
                size=file_size,
                content_type=file.content_type,
                hints=hints,
            )

            # Build relative path from backend root
            relative_path = str(get_paths().sandbox_uploads_dir(thread_id) / safe_filename)
            virtual_path = f"{VIRTUAL_PATH_PREFIX}/uploads/{safe_filename}"
            if not is_local_sandbox:
                sandbox.update_file(virtual_path, file_path.read_bytes())

            file_info = {
                "filename": safe_filename,
                "size": file_size,
                "path": relative_path,  # Actual filesystem path (relative to backend/)
                "virtual_path": virtual_path,  # Path for Agent in sandbox
                "artifact_url": f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{safe_filename}",  # HTTP URL
                "parse_method": record["parse_method"],
                "parse_status": record["parse_status"],
                "indexable": record["indexable"],
                "hints": hints,
            }

            logger.info(f"Saved file: {safe_filename} ({file_size} bytes) to {relative_path}")

            # Check if file should be parsed into structured text
            file_ext = file_path.suffix.lower()
            if file_ext in PDF_EXTENSIONS or file_ext in OFFICE_EXTENSIONS or file_ext in {".md", ".txt"}:
                kb_config = get_knowledge_base_config()
                use_remote_api = (
                    kb_config.mineru_api is not None
                    and kb_config.mineru_api.enabled
                )
                record["parse_method"] = "ocr_pdf_mineru_api" if use_remote_api else "ocr_pdf_mineru_grpc"
                file_info["parse_method"] = record["parse_method"]
                try:
                    if use_remote_api:
                        structured_payload = build_structured_document_from_mineru_api(
                            file_path,
                            title=record["display_title"],
                            parser_name=record["parse_method"],
                            hints=hints,
                        )
                    else:
                        structured_payload = build_structured_document_from_mineru_grpc(
                            file_path,
                            title=record["display_title"],
                            parser_name=record["parse_method"],
                            hints=hints,
                            language_hint=hints.get("language_hint"),
                        )
                except Exception as exc:
                    structured_payload = None
                    logger.error("MinerU parsing failed for %s: %s", file_path.name, exc)
                if structured_payload:
                    structured_filename = persist_thread_structured_document(
                        thread_id,
                        safe_filename,
                        structured_payload,
                    )
                    maybe_generate_book_metadata(
                        structured_payload=structured_payload,
                        source_filename=safe_filename,
                        title=record["display_title"],
                        output_dir=uploads_dir,
                        config=metadata_config,
                    )
                    if not is_local_sandbox:
                        ingestion_urls = build_ingestion_urls(thread_id, structured_filename)
                        sandbox.update_file(
                            ingestion_urls["virtual_path"],
                            (get_paths().sandbox_uploads_dir(thread_id) / ".ingestion" / structured_filename).read_bytes(),
                        )
                    record = mark_record_parsed(
                        thread_id,
                        record,
                        structured_filename=structured_filename,
                        preview_filename=safe_filename if file_ext in {".md", ".txt"} else None,
                    )
                    file_info["structured_file"] = structured_filename
                    file_info["structured_artifact_url"] = record["structured_artifact_url"]
                    file_info["index_target_filename"] = structured_filename
                    file_info["parse_status"] = record["parse_status"]
                else:
                    record = mark_record_failed(record, "MinerU returned no structured text")
                    file_info["parse_status"] = record["parse_status"]
                    file_info["error"] = record["error"]
            else:
                record["parse_status"] = "uploaded"

            save_ingestion_record(thread_id, safe_filename, record)
            uploaded_files.append(file_info)

        except Exception as e:
            logger.error(f"Failed to upload {file.filename}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to upload {file.filename}: {str(e)}")

    return UploadResponse(
        success=True,
        files=uploaded_files,
        message=f"Successfully uploaded {len(uploaded_files)} file(s)",
    )


@router.get("/list", response_model=dict)
async def list_uploaded_files(thread_id: str) -> dict:
    """List all files in a thread's uploads directory.

    Args:
        thread_id: The thread ID to list files for.

    Returns:
        Dictionary containing list of files with their metadata.
    """
    uploads_dir = get_uploads_dir(thread_id)

    if not uploads_dir.exists():
        return {"files": [], "count": 0}

    source_records, target_records = build_record_lookup(thread_id)
    preview_filenames = {
        str(record.get("preview_filename"))
        for record in source_records.values()
        if record.get("preview_filename") and record.get("preview_filename") != record.get("source_filename")
    }
    files = []
    for file_path in sorted(uploads_dir.iterdir()):
        if file_path.is_file():
            record = source_records.get(file_path.name)
            if target_records.get(file_path.name) and not record:
                continue
            if file_path.name in preview_filenames and not record:
                continue

            stat = file_path.stat()
            relative_path = str(get_paths().sandbox_uploads_dir(thread_id) / file_path.name)
            entry = {
                "filename": file_path.name,
                "size": stat.st_size,
                "path": relative_path,  # Actual filesystem path
                "virtual_path": f"{VIRTUAL_PATH_PREFIX}/uploads/{file_path.name}",  # Path for Agent in sandbox
                "artifact_url": f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{file_path.name}",  # HTTP URL
                "extension": file_path.suffix,
                "modified": stat.st_mtime,
            }
            if record:
                entry.update(
                    {
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
                    }
                )
            files.append(entry)

    return {"files": files, "count": len(files)}


@router.delete("/{filename}")
async def delete_uploaded_file(thread_id: str, filename: str) -> dict:
    """Delete a file from a thread's uploads directory.

    Args:
        thread_id: The thread ID.
        filename: The filename to delete.

    Returns:
        Success message.
    """
    uploads_dir = get_uploads_dir(thread_id)
    file_path = uploads_dir / filename
    record = find_ingestion_record(thread_id, filename)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    # Security check: ensure the path is within the uploads directory
    try:
        file_path.resolve().relative_to(uploads_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        file_path.unlink()
        if record:
            index_target_filename = record.get("index_target_filename")
            source_filename = record.get("source_filename")
            structured_filename = record.get("structured_filename")
            if index_target_filename and index_target_filename != filename:
                derived_path = Path(str(record.get("index_target_path")))
                if derived_path.exists():
                    derived_path.unlink()
            elif structured_filename and structured_filename != filename:
                structured_path = Path(str(record.get("structured_path")))
                if structured_path.exists():
                    structured_path.unlink()
            if source_filename and source_filename != filename:
                source_path = uploads_dir / source_filename
                if source_path.exists():
                    source_path.unlink()
            preview_filename = record.get("preview_filename")
            if preview_filename and preview_filename not in {filename, source_filename, index_target_filename}:
                preview_path = uploads_dir / preview_filename
                if preview_path.exists():
                    preview_path.unlink()
            if source_filename:
                remove_ingestion_record(thread_id, source_filename)
        logger.info(f"Deleted file: {filename}")
        return {"success": True, "message": f"Deleted {filename}"}
    except Exception as e:
        logger.error(f"Failed to delete {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete {filename}: {str(e)}")
