"""MinerU remote HTTP API integration for document parsing."""

from __future__ import annotations

import io
import logging
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx

from src.community.knowledge_base.structured_document import build_structured_document
from src.config.knowledge_base_config import MineruApiConfig, get_knowledge_base_config

logger = logging.getLogger(__name__)


def _get_mineru_api_config() -> MineruApiConfig:
    config = get_knowledge_base_config().mineru_api
    if config is None or not config.enabled:
        raise RuntimeError("MinerU API is not configured or is disabled")
    return config


def _auth_headers(config: MineruApiConfig) -> dict[str, str]:
    return {"Authorization": f"Bearer {config.api_token}"}


def _request_upload_url(filename: str, config: MineruApiConfig) -> tuple[str, str]:
    """POST /api/v4/file-urls/batch to get a presigned PUT URL.

    Returns (batch_id, upload_url).
    """
    url = f"{config.base_url}/api/v4/file-urls/batch"
    payload = {
        "files": [{"name": filename, "data_id": filename}],
        "model_version": config.model_version,
    }
    with httpx.Client(timeout=config.request_timeout) as client:
        resp = client.post(url, headers=_auth_headers(config), json=payload)
        resp.raise_for_status()
        data = resp.json()

    if data.get("code") != 0:
        raise RuntimeError(f"MinerU API error requesting upload URL: {data.get('msg')}")

    batch_id: str = data["data"]["batch_id"]
    file_urls: list[str] = data["data"]["file_urls"]
    if not file_urls:
        raise RuntimeError("MinerU API returned no upload URLs")

    logger.info("[mineru-api] Got batch_id=%s upload_url=%.60s...", batch_id, file_urls[0])
    return batch_id, file_urls[0]


def _upload_file(upload_url: str, file_content: bytes, timeout: int) -> None:
    """PUT file bytes to the presigned URL (no auth headers required)."""
    with httpx.Client(timeout=timeout) as client:
        resp = client.put(upload_url, content=file_content)
        resp.raise_for_status()


def _poll_for_result(batch_id: str, filename: str, config: MineruApiConfig) -> str:
    """Poll GET /api/v4/extract-results/batch/{batch_id} until done.

    Returns full_zip_url when state is "done".
    Raises RuntimeError on failure or timeout.
    """
    url = f"{config.base_url}/api/v4/extract-results/batch/{batch_id}"
    headers = _auth_headers(config)

    for attempt in range(1, config.max_poll_attempts + 1):
        if attempt > 1:
            time.sleep(config.poll_interval_seconds)

        with httpx.Client(timeout=config.request_timeout) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(f"MinerU API polling error: {data.get('msg')}")

        for result in data["data"].get("extract_result", []):
            if result.get("file_name") != filename:
                continue
            state = result.get("state")
            if state == "done":
                return result["full_zip_url"]
            if state == "failed":
                raise RuntimeError(f"MinerU extraction failed: {result.get('err_msg') or 'unknown'}")
            progress = result.get("extract_progress") or {}
            logger.info(
                "[mineru-api] %s attempt=%d/%d state=%s pages=%s/%s",
                filename,
                attempt,
                config.max_poll_attempts,
                state,
                progress.get("extracted_pages", "?"),
                progress.get("total_pages", "?"),
            )
            break

    raise RuntimeError(
        f"MinerU extraction timed out after {config.max_poll_attempts} polling attempts"
    )


def _extract_markdown_from_zip(zip_content: bytes, source_filename: str) -> str:
    """Extract the .md file from the MinerU result ZIP."""
    with zipfile.ZipFile(io.BytesIO(zip_content)) as zf:
        md_names = [n for n in zf.namelist() if n.endswith(".md")]
        if not md_names:
            raise RuntimeError(
                f"No markdown file found in MinerU result ZIP for {source_filename}"
            )
        stem = Path(source_filename).stem
        target = next((n for n in md_names if stem in n), md_names[0])
        return zf.read(target).decode("utf-8")


def build_structured_document_from_mineru_api(
    file_path: Path,
    *,
    title: str,
    parser_name: str,
    hints: dict[str, str] | None = None,
    file_content: bytes | None = None,
) -> dict[str, Any]:
    """Parse a document via MinerU's remote HTTP API and return a structured document.

    Flow:
      1. POST /api/v4/file-urls/batch  → batch_id + presigned PUT URL
      2. PUT file bytes to upload URL
      3. Poll GET /api/v4/extract-results/batch/{batch_id} until done
      4. Download ZIP, extract markdown
      5. Wrap markdown in the standard structured-document schema
    """
    config = _get_mineru_api_config()
    hints = hints or {}
    content = file_content if file_content is not None else file_path.read_bytes()

    logger.info(
        "[mineru-api] Submitting %s (%d bytes) model_version=%s",
        file_path.name,
        len(content),
        config.model_version,
    )

    batch_id, upload_url = _request_upload_url(file_path.name, config)

    logger.info("[mineru-api] Uploading %s to presigned URL", file_path.name)
    _upload_file(upload_url, content, config.request_timeout)

    logger.info("[mineru-api] Polling batch_id=%s for %s", batch_id, file_path.name)
    zip_url = _poll_for_result(batch_id, file_path.name, config)

    logger.info("[mineru-api] Downloading result ZIP from %s", zip_url)
    with httpx.Client(timeout=config.request_timeout) as client:
        zip_resp = client.get(zip_url)
        zip_resp.raise_for_status()
        zip_content = zip_resp.content

    markdown_text = _extract_markdown_from_zip(zip_content, file_path.name)
    logger.info(
        "[mineru-api] Extraction done for %s (%d chars markdown)",
        file_path.name,
        len(markdown_text),
    )

    payload = build_structured_document(
        source_filename=file_path.name,
        title=title,
        text=markdown_text,
        parser_name=parser_name,
        hints=hints,
    )
    payload["provider"] = "mineru_api"
    payload["provider_result_meta"] = {"batch_id": batch_id}
    return payload
