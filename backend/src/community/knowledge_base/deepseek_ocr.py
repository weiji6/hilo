"""DeepSeek document OCR integration."""

from __future__ import annotations

import mimetypes
import os
import re
from pathlib import Path
from typing import Any

import httpx

from src.community.knowledge_base.structured_document import build_structured_document
from src.config.knowledge_base_config import DeepSeekOcrConfig, get_knowledge_base_config

_MAX_FILE_BYTES = 100 * 1024 * 1024
_BOX_MARKUP_PATTERN = re.compile(r"<｜box｜>.*?<｜/box｜>", re.DOTALL)
_SPECIAL_TAG_PATTERN = re.compile(r"<｜/?[^<>｜]+｜>")


def _get_deepseek_ocr_config() -> DeepSeekOcrConfig:
    config = get_knowledge_base_config().deepseek_ocr
    if config is None or not config.enabled:
        raise RuntimeError("DeepSeek OCR is not configured or is disabled")
    return config


def _resolve_api_key(config: DeepSeekOcrConfig) -> str:
    api_key = (
        config.api_key
        or os.getenv("DEEPSEEK_OCR_API_KEY")
        or os.getenv("DEEPSEEK_OFFICIAL_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    if not api_key:
        raise RuntimeError("DeepSeek OCR requires an API key")
    return api_key


def _ocr_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return f"{normalized}/tools/ocr"
    return f"{normalized}/v1/tools/ocr"


def _clean_page_text(text: str) -> str:
    """Remove DeepSeek layout markers while retaining recognized text."""
    without_boxes = _BOX_MARKUP_PATTERN.sub("", text)
    return _SPECIAL_TAG_PATTERN.sub("", without_boxes).strip()


def build_structured_document_from_deepseek_response(
    response: dict[str, Any],
    *,
    source_filename: str,
    title: str,
    parser_name: str,
    hints: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Convert a DeepSeek OCR response into Hilo's structured document schema."""
    if response.get("error"):
        error = response["error"]
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise RuntimeError(f"DeepSeek OCR failed: {message or 'unknown error'}")

    raw_pages = response.get("pages")
    if not isinstance(raw_pages, list) or not raw_pages:
        raise RuntimeError("DeepSeek OCR returned no pages")

    ordered_pages = sorted(raw_pages, key=lambda page: int(page.get("index", 0)))
    page_texts = [_clean_page_text(str(page.get("text") or "")) for page in ordered_pages]
    payload = build_structured_document(
        source_filename=source_filename,
        title=title,
        text="\f".join(page_texts),
        parser_name=parser_name,
        hints=hints,
    )
    for page, provider_page in zip(payload["pages"], ordered_pages, strict=True):
        page["ocr_finish_reason"] = provider_page.get("finish_reason")

    payload["provider"] = "deepseek_ocr"
    payload["provider_result_meta"] = {
        "id": response.get("id"),
        "purpose": response.get("purpose"),
        "page_count": response.get("page_count", len(ordered_pages)),
        "usage": response.get("usage"),
    }
    return payload


def build_structured_document_from_deepseek_ocr(
    file_path: Path,
    *,
    title: str,
    parser_name: str,
    hints: dict[str, str] | None = None,
    file_content: bytes | None = None,
) -> dict[str, Any]:
    """Upload one document to DeepSeek OCR and return structured pages."""
    config = _get_deepseek_ocr_config()
    content = file_content if file_content is not None else file_path.read_bytes()
    if len(content) > _MAX_FILE_BYTES:
        raise ValueError("DeepSeek OCR accepts files up to 100 MiB")

    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    with httpx.Client(timeout=config.request_timeout) as client:
        response = client.post(
            _ocr_url(config.base_url),
            headers={"Authorization": f"Bearer {_resolve_api_key(config)}"},
            data={"purpose": config.purpose},
            files={"file": (file_path.name, content, content_type)},
        )

    try:
        result = response.json()
    except ValueError as exc:
        response.raise_for_status()
        raise RuntimeError("DeepSeek OCR returned an invalid JSON response") from exc
    if response.is_error:
        error = result.get("error") if isinstance(result, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        raise RuntimeError(
            f"DeepSeek OCR HTTP {response.status_code}: {message or 'request failed'}"
        )
    if not isinstance(result, dict):
        raise RuntimeError("DeepSeek OCR returned an invalid response object")
    return build_structured_document_from_deepseek_response(
        result,
        source_filename=file_path.name,
        title=title,
        parser_name=parser_name,
        hints=hints,
    )
