"""Document parsing metadata helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.community.knowledge_base.structured_document import build_structured_document
from src.config.knowledge_base_config import get_knowledge_base_config

PDF_EXTENSIONS = {".pdf"}
OFFICE_EXTENSIONS = {
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".doc",
    ".docx",
}
DEEPSEEK_OCR_EXTENSIONS = PDF_EXTENSIONS | {".doc", ".docx", ".ppt", ".pptx"}


def infer_parse_method(filename: str) -> tuple[str, bool]:
    """Infer the parser used for a given source file."""
    suffix = Path(filename).suffix.lower()
    if suffix in {".md", ".txt"}:
        return "local_text", True
    if suffix in PDF_EXTENSIONS | OFFICE_EXTENSIONS:
        return "ocr_pdf_mineru_grpc", True
    return "binary_only", False


def get_configured_ocr_parse_method(filename: str | Path | None = None) -> str:
    """Return the parser selected by the active knowledge-base configuration."""
    config = get_knowledge_base_config()
    suffix = Path(filename).suffix.lower() if filename is not None else None
    if (
        config.deepseek_ocr is not None
        and config.deepseek_ocr.enabled
        and (suffix is None or suffix in DEEPSEEK_OCR_EXTENSIONS)
    ):
        return "ocr_deepseek"
    if config.mineru_api is not None and config.mineru_api.enabled:
        return "ocr_pdf_mineru_api"
    return "ocr_pdf_mineru_grpc"


def parse_document_with_configured_ocr(
    file_path: Path,
    *,
    title: str,
    parser_name: str,
    hints: dict[str, str] | None = None,
    file_content: bytes | None = None,
) -> dict[str, Any]:
    """Parse a document with the configured OCR provider."""
    if parser_name == "ocr_deepseek":
        from src.community.knowledge_base.deepseek_ocr import (
            build_structured_document_from_deepseek_ocr,
        )

        return build_structured_document_from_deepseek_ocr(
            file_path,
            title=title,
            parser_name=parser_name,
            hints=hints,
            file_content=file_content,
        )
    if parser_name == "ocr_pdf_mineru_api":
        from src.community.knowledge_base.mineru_api import (
            build_structured_document_from_mineru_api,
        )

        return build_structured_document_from_mineru_api(
            file_path,
            title=title,
            parser_name=parser_name,
            hints=hints,
            file_content=file_content,
        )

    from src.community.knowledge_base.mineru_grpc import (
        build_structured_document_from_mineru_grpc,
    )

    return build_structured_document_from_mineru_grpc(
        file_path,
        title=title,
        parser_name=parser_name,
        hints=hints,
        language_hint=(hints or {}).get("language_hint"),
        file_content=file_content,
    )


def parse_local_text(file_path: Path, *, title: str, hints: dict[str, str] | None = None) -> dict[str, Any]:
    """Parse UTF-8 Markdown/TXT locally, without an OCR or model service."""
    if file_path.suffix.lower() not in {".md", ".txt"}:
        raise ValueError("Local text parsing supports Markdown and TXT only")
    return build_structured_document(
        source_filename=file_path.name,
        title=title,
        text=file_path.read_text(encoding="utf-8-sig"),
        parser_name="local_text",
        hints=hints,
    )
