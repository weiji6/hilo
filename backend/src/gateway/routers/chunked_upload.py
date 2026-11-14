"""
Chunked upload API for large file uploads to knowledge base.

Supports uploading files in chunks (5MB recommended) with resume capability.
"""

import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from src.config.knowledge_base_config import get_knowledge_base_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge/uploads", tags=["knowledge-base"])

CHUNK_SIZE = 5 * 1024 * 1024  # 5MB default chunk size


def _get_uploads_temp_dir() -> Path:
    """Get the temporary directory for chunked uploads."""
    cwd = Path(os.getcwd())
    project_root = cwd.parent if cwd.name == "backend" else cwd
    if not (project_root / "backend").exists():
        project_root = cwd
    return project_root / ".deer-flow" / "chunked-uploads"


def _get_upload_dir(upload_id: str) -> Path:
    """Get the directory for a specific upload session."""
    return _get_uploads_temp_dir() / upload_id


def _resolve_knowledge_docs_root() -> Path:
    """Resolve knowledge docs directory (same logic as knowledge.py)."""
    docs_path = Path(get_knowledge_base_config().docs_path)
    if docs_path.is_absolute():
        return docs_path
    cwd = Path(os.getcwd())
    project_root = cwd.parent if cwd.name == "backend" else cwd
    if not (project_root / "backend").exists():
        project_root = cwd
    return project_root / get_knowledge_base_config().docs_path


# In-memory upload session tracking
_upload_sessions: Dict[str, dict] = {}


class InitUploadRequest(BaseModel):
    """Request model for initializing a chunked upload."""
    filename: str
    file_size: int
    chunk_size: int = CHUNK_SIZE
    content_type: str = "application/octet-stream"


class InitUploadResponse(BaseModel):
    """Response model for upload initialization."""
    upload_id: str
    chunk_size: int
    total_chunks: int
    filename: str


class ChunkUploadResponse(BaseModel):
    """Response model for chunk upload."""
    chunk_index: int
    received: bool
    chunks_received: int
    total_chunks: int


class CompleteUploadResponse(BaseModel):
    """Response model for completing upload."""
    status: str
    message: str
    filename: str
    file_size: int


@router.post("/init", response_model=InitUploadResponse, summary="Initialize Chunked Upload")
async def init_upload(request: InitUploadRequest) -> InitUploadResponse:
    """Initialize a chunked upload session.
    
    Creates an upload session and returns an upload_id for subsequent chunk uploads.
    """
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")

    # Validate filename
    safe_filename = Path(request.filename).name
    if not safe_filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    ext = Path(safe_filename).suffix.lower()
    if ext not in {".md", ".markdown", ".pdf", ".txt"}:
        raise HTTPException(
            status_code=400,
            detail="Only .md, .markdown, .pdf and .txt files are supported"
        )

    # Generate upload ID
    upload_id = str(uuid.uuid4())
    
    # Calculate total chunks
    chunk_size = request.chunk_size or CHUNK_SIZE
    total_chunks = (request.file_size + chunk_size - 1) // chunk_size

    # Create upload directory
    upload_dir = _get_upload_dir(upload_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Store session info
    _upload_sessions[upload_id] = {
        "filename": safe_filename,
        "file_size": request.file_size,
        "chunk_size": chunk_size,
        "total_chunks": total_chunks,
        "chunks_received": set(),
        "content_type": request.content_type,
    }

    logger.info(f"Initialized chunked upload: {upload_id}, file: {safe_filename}, "
                f"size: {request.file_size}, chunks: {total_chunks}")

    return InitUploadResponse(
        upload_id=upload_id,
        chunk_size=chunk_size,
        total_chunks=total_chunks,
        filename=safe_filename,
    )


@router.post("/{upload_id}/chunk", response_model=ChunkUploadResponse, summary="Upload Chunk")
async def upload_chunk(
    upload_id: str,
    chunk_index: int = Form(..., description="Zero-based chunk index"),
    chunk: UploadFile = File(..., description="Chunk data"),
) -> ChunkUploadResponse:
    """Upload a single chunk of a file.
    
    Chunks should be uploaded with the chunk_index corresponding to their position.
    The last chunk may be smaller than chunk_size.
    """
    if upload_id not in _upload_sessions:
        raise HTTPException(status_code=404, detail="Upload session not found")

    session = _upload_sessions[upload_id]
    total_chunks = session["total_chunks"]

    if chunk_index < 0 or chunk_index >= total_chunks:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid chunk index. Expected 0-{total_chunks - 1}"
        )

    # Save chunk to disk
    upload_dir = _get_upload_dir(upload_id)
    chunk_path = upload_dir / f"chunk_{chunk_index:06d}"

    try:
        content = await chunk.read()
        chunk_path.write_bytes(content)
        session["chunks_received"].add(chunk_index)
        
        logger.debug(f"Received chunk {chunk_index}/{total_chunks} for upload {upload_id}")
    except Exception as e:
        logger.exception(f"Failed to save chunk {chunk_index} for upload {upload_id}")
        raise HTTPException(status_code=500, detail=f"Failed to save chunk: {e}")

    return ChunkUploadResponse(
        chunk_index=chunk_index,
        received=True,
        chunks_received=len(session["chunks_received"]),
        total_chunks=total_chunks,
    )


@router.post("/{upload_id}/complete", response_model=CompleteUploadResponse, summary="Complete Upload")
async def complete_upload(
    upload_id: str,
    reindex: bool = Query(False, description="Trigger reindex after upload"),
) -> CompleteUploadResponse:
    """Complete a chunked upload by merging all chunks.
    
    All chunks must be uploaded before calling this endpoint.
    The merged file will be saved to the knowledge docs directory.
    """
    if upload_id not in _upload_sessions:
        raise HTTPException(status_code=404, detail="Upload session not found")

    session = _upload_sessions[upload_id]
    total_chunks = session["total_chunks"]
    chunks_received = session["chunks_received"]

    # Verify all chunks received
    missing_chunks = set(range(total_chunks)) - chunks_received
    if missing_chunks:
        raise HTTPException(
            status_code=400,
            detail=f"Missing chunks: {sorted(missing_chunks)[:10]}{'...' if len(missing_chunks) > 10 else ''}"
        )

    upload_dir = _get_upload_dir(upload_id)
    filename = session["filename"]
    
    # Ensure docs directory exists
    docs_root = _resolve_knowledge_docs_root()
    docs_root.mkdir(parents=True, exist_ok=True)
    
    target_path = docs_root / filename

    try:
        # Merge chunks
        with open(target_path, "wb") as outfile:
            for i in range(total_chunks):
                chunk_path = upload_dir / f"chunk_{i:06d}"
                outfile.write(chunk_path.read_bytes())

        file_size = target_path.stat().st_size
        logger.info(f"Completed chunked upload: {filename}, size: {file_size}")

        # Cleanup upload directory
        shutil.rmtree(upload_dir, ignore_errors=True)
        del _upload_sessions[upload_id]

    except Exception as e:
        logger.exception(f"Failed to merge chunks for upload {upload_id}")
        raise HTTPException(status_code=500, detail=f"Failed to merge chunks: {e}")

    # Trigger reindex if requested
    if reindex:
        try:
            from src.community.knowledge_base.indexer import run_indexer
            run_indexer()
            logger.info("Reindex triggered after chunked upload")
        except Exception as e:
            logger.exception("File uploaded but failed to reindex")
            return CompleteUploadResponse(
                status="partial",
                message=f"File uploaded but reindex failed: {e}",
                filename=filename,
                file_size=file_size,
            )

    return CompleteUploadResponse(
        status="success",
        message="File uploaded successfully",
        filename=filename,
        file_size=file_size,
    )


@router.delete("/{upload_id}", summary="Cancel Upload")
async def cancel_upload(upload_id: str) -> dict:
    """Cancel and cleanup an upload session.
    
    Removes all uploaded chunks and session data.
    """
    if upload_id not in _upload_sessions:
        raise HTTPException(status_code=404, detail="Upload session not found")

    upload_dir = _get_upload_dir(upload_id)
    
    try:
        shutil.rmtree(upload_dir, ignore_errors=True)
        del _upload_sessions[upload_id]
        logger.info(f"Cancelled upload session: {upload_id}")
    except Exception as e:
        logger.exception(f"Failed to cleanup upload {upload_id}")
        raise HTTPException(status_code=500, detail=f"Failed to cleanup: {e}")

    return {"status": "cancelled", "upload_id": upload_id}


@router.get("/{upload_id}/status", summary="Get Upload Status")
async def get_upload_status(upload_id: str) -> dict:
    """Get the status of an upload session.
    
    Returns information about received chunks and remaining chunks.
    """
    if upload_id not in _upload_sessions:
        raise HTTPException(status_code=404, detail="Upload session not found")

    session = _upload_sessions[upload_id]
    chunks_received = sorted(session["chunks_received"])
    total_chunks = session["total_chunks"]
    missing_chunks = sorted(set(range(total_chunks)) - session["chunks_received"])

    return {
        "upload_id": upload_id,
        "filename": session["filename"],
        "file_size": session["file_size"],
        "chunk_size": session["chunk_size"],
        "total_chunks": total_chunks,
        "chunks_received": len(chunks_received),
        "missing_chunks": missing_chunks[:20],  # Limit response size
        "progress": len(chunks_received) / total_chunks if total_chunks > 0 else 0,
    }
