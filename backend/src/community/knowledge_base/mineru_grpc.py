"""MinerU gRPC integration for PDF parsing."""

from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import grpc

from src.community.knowledge_base.mineru_proto import mineru_pb2, mineru_pb2_grpc
from src.community.knowledge_base.structured_document import (
    build_bbox,
    build_page_reference,
    build_structured_document,
)
from src.config.knowledge_base_config import MineruConfig, get_knowledge_base_config

DEFAULT_MAX_GRPC_MESSAGE_BYTES = 256 * 1024 * 1024
DEFAULT_PDF_SPLIT_SIZE_RATIO = 0.8

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PdfChunkPlan:
    total_pages: int
    chunk_page_count: int
    chunk_ranges: list[tuple[int, int]]
    file_size_bytes: int


def _get_max_grpc_message_bytes(config: MineruConfig) -> int:
    configured_value = _coerce_positive_int(getattr(config, "max_message_bytes", None))
    if configured_value is not None:
        return configured_value

    raw_value = (os.getenv("MINERU_GRPC_MAX_MESSAGE_BYTES") or "").strip()
    if not raw_value:
        return DEFAULT_MAX_GRPC_MESSAGE_BYTES
    try:
        parsed = int(raw_value)
    except ValueError:
        return DEFAULT_MAX_GRPC_MESSAGE_BYTES
    return parsed if parsed > 0 else DEFAULT_MAX_GRPC_MESSAGE_BYTES


def _get_mineru_config() -> MineruConfig:
    config = get_knowledge_base_config().mineru
    if config is None or not config.enabled:
        raise RuntimeError("MinerU gRPC is not configured or is disabled")
    return config


def _coerce_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _build_metadata(config: MineruConfig) -> list[tuple[str, str]]:
    if not config.api_token:
        return []
    return [("authorization", f"Bearer {config.api_token}")]


def _build_parse_pdf_request(
    *,
    file_path: Path,
    config: MineruConfig,
    hints: dict[str, str] | None,
    language_hint: str | None,
    file_content: bytes | None = None,
) -> mineru_pb2.ParsePdfRequest:
    hints = hints or {}
    return mineru_pb2.ParsePdfRequest(
        filename=file_path.name,
        file_content=file_content if file_content is not None else file_path.read_bytes(),
        language_hint=language_hint or "",
        layout_hint=hints.get("layout_hint", ""),
        document_type_hint=hints.get("document_type_hint", ""),
        book_page_start_pdf_page=hints.get("book_page_start_pdf_page", ""),
        book_page_start_value=hints.get("book_page_start_value", ""),
        model_version=config.model_version,
    )


def _build_channel(config: MineruConfig) -> grpc.Channel:
    max_message_bytes = _get_max_grpc_message_bytes(config)
    options = [
        ("grpc.max_send_message_length", max_message_bytes),
        ("grpc.max_receive_message_length", max_message_bytes),
        ("grpc.keepalive_time_ms", config.keepalive_time_ms),
        ("grpc.keepalive_timeout_ms", config.keepalive_timeout_ms),
        ("grpc.keepalive_permit_without_calls", int(config.keepalive_permit_without_calls)),
        # Allow proactive pings on long-lived channels so upstream proxies do not
        # silently age out the HTTP/2 connection during large OCR requests.
        ("grpc.http2.max_pings_without_data", 0),
        ("grpc.http2.min_time_between_pings_ms", config.keepalive_time_ms),
        ("grpc.http2.min_ping_interval_without_data_ms", config.keepalive_time_ms),
    ]
    logger.info(
        "[mineru-grpc] building channel target=%s tls=%s max_message_bytes=%s "
        "keepalive_time_ms=%s keepalive_timeout_ms=%s permit_without_calls=%s request_timeout=%s",
        config.target,
        config.use_tls,
        max_message_bytes,
        config.keepalive_time_ms,
        config.keepalive_timeout_ms,
        config.keepalive_permit_without_calls,
        config.request_timeout,
    )
    if config.use_tls:
        credentials = grpc.ssl_channel_credentials()
        return grpc.secure_channel(config.target, credentials, options=options)
    return grpc.insecure_channel(config.target, options=options)


def _watch_channel_connectivity(channel: grpc.Channel, tag: str) -> threading.Event:
    """Log every channel connectivity transition for the lifetime of ``channel``.

    Returns an ``Event`` the caller can set to stop the watcher early. The
    callback is registered exactly once — ``grpc.Channel.subscribe`` is sticky
    (each state change re-invokes the callback automatically), so resubscribing
    inside the callback would produce duplicate log lines.
    """
    stop_event = threading.Event()

    def _on_state(state: grpc.ChannelConnectivity) -> None:
        if stop_event.is_set():
            return
        logger.info("[mineru-grpc] %s channel state -> %s", tag, state.name)

    try:
        channel.subscribe(_on_state, try_to_connect=True)
    except Exception:  # pragma: no cover - defensive
        logger.debug("[mineru-grpc] %s could not subscribe to channel state", tag, exc_info=True)
    return stop_event


_RETRYABLE_GRPC_CODES = frozenset([
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.INTERNAL,
])


def _parse_pdf_response_via_mineru_grpc(
    file_path: Path,
    *,
    config: MineruConfig,
    hints: dict[str, str] | None = None,
    language_hint: str | None = None,
    file_content: bytes | None = None,
) -> mineru_pb2.ParsePdfResponse:
    tag = f"ParsePdf({file_path.name})"
    try:
        request_size = file_path.stat().st_size
    except OSError:
        request_size = -1
    request = _build_parse_pdf_request(
        file_path=file_path,
        config=config,
        hints=hints,
        language_hint=language_hint,
        file_content=file_content,
    )
    started_at = time.monotonic()
    logger.info(
        "[mineru-grpc] %s request prepared file_size_bytes=%s hints=%s language_hint=%r",
        tag,
        request_size,
        hints,
        language_hint,
    )
    max_attempts = max(1, config.retry_attempts + 1)
    last_exc: grpc.RpcError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with _build_channel(config) as channel:
                stop_watch = _watch_channel_connectivity(channel, tag)
                stub = mineru_pb2_grpc.MineruPdfExtractorStub(channel)
                send_at = time.monotonic()
                logger.info(
                    "[mineru-grpc] %s SENDING request attempt=%d/%d (waited %.2fs for channel setup, deadline=%ss)",
                    tag,
                    attempt,
                    max_attempts,
                    send_at - started_at,
                    config.request_timeout,
                )
                try:
                    response = stub.ParsePdf(
                        request,
                        timeout=config.request_timeout,
                        metadata=_build_metadata(config),
                    )
                finally:
                    stop_watch.set()
                logger.info(
                    "[mineru-grpc] %s RESPONSE received in %.2fs (channel-send→response)",
                    tag,
                    time.monotonic() - send_at,
                )
                return response
        except grpc.RpcError as exc:
            def _safe(getter, default=None):
                try:
                    value = getter()
                    return value if value is not None else default
                except Exception:  # pragma: no cover - defensive
                    return default

            code = _safe(lambda: exc.code())
            details = _safe(lambda: exc.details(), default="")
            debug_error = _safe(lambda: exc.debug_error_string(), default="")
            initial_md = _safe(lambda: list(exc.initial_metadata() or []), default=[])
            trailing_md = _safe(lambda: list(exc.trailing_metadata() or []), default=[])
            elapsed = time.monotonic() - started_at
            code_name = code.name if code is not None else "UNKNOWN"

            is_retryable = code in _RETRYABLE_GRPC_CODES
            if is_retryable and attempt < max_attempts:
                logger.warning(
                    "[mineru-grpc] %s attempt %d/%d FAILED code=%s details=%r — retrying in %.1fs",
                    tag,
                    attempt,
                    max_attempts,
                    code_name,
                    details,
                    config.retry_delay_seconds,
                )
                time.sleep(config.retry_delay_seconds)
                last_exc = exc
                continue

            logger.error(
                "[mineru-grpc] %s FAILED after %.2fs attempt=%d/%d code=%s details=%r initial_md=%s trailing_md=%s debug_error=%s",
                tag,
                elapsed,
                attempt,
                max_attempts,
                code_name,
                details,
                initial_md,
                trailing_md,
                debug_error,
            )
            raise RuntimeError(
                f"MinerU gRPC failed after {elapsed:.1f}s: {code_name} {details}"
            ) from exc

    raise RuntimeError("MinerU gRPC retry loop exhausted without result") from last_exc


def _count_pdf_pages(file_path: Path, file_content: bytes | None = None) -> int:
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(file_content) if file_content is not None else str(file_path))
    return len(reader.pages)


def _default_pdf_split_size_threshold_bytes(config: MineruConfig) -> int:
    max_message_bytes = _get_max_grpc_message_bytes(config)
    threshold = int(max_message_bytes * DEFAULT_PDF_SPLIT_SIZE_RATIO)
    return max(1, threshold)


def _build_pdf_chunk_ranges(total_pages: int, chunk_page_count: int) -> list[tuple[int, int]]:
    normalized_chunk_page_count = max(1, int(chunk_page_count))
    return [
        (start_page_index, min(start_page_index + normalized_chunk_page_count, total_pages))
        for start_page_index in range(0, total_pages, normalized_chunk_page_count)
    ]


def _maybe_build_pdf_chunk_plan(file_path: Path, config: MineruConfig, file_content: bytes | None = None) -> PdfChunkPlan | None:
    if file_path.suffix.lower() != ".pdf" or not config.enable_pdf_chunking:
        return None

    file_size_bytes = len(file_content) if file_content is not None else file_path.stat().st_size
    size_threshold_bytes = _coerce_positive_int(config.pdf_split_size_threshold_bytes)
    if size_threshold_bytes is None:
        size_threshold_bytes = _default_pdf_split_size_threshold_bytes(config)

    total_pages = _count_pdf_pages(file_path, file_content)
    should_split = (
        total_pages > config.pdf_split_page_threshold
        or file_size_bytes > size_threshold_bytes
    )
    if not should_split or total_pages <= 1:
        return None

    chunk_ranges = _build_pdf_chunk_ranges(total_pages, config.pdf_chunk_page_count)
    if len(chunk_ranges) <= 1:
        return None

    return PdfChunkPlan(
        total_pages=total_pages,
        chunk_page_count=max(1, int(config.pdf_chunk_page_count)),
        chunk_ranges=chunk_ranges,
        file_size_bytes=file_size_bytes,
    )


def _bbox_to_payload(bbox: mineru_pb2.BBox | None) -> dict[str, float] | None:
    if bbox is None:
        return None
    if bbox.width <= 0 or bbox.height <= 0:
        return None
    return build_bbox(x=bbox.x, y=bbox.y, width=bbox.width, height=bbox.height)


def _build_chunk_local_hints(
    *,
    hints: dict[str, str] | None,
    start_page_index: int,
    end_page_index: int,
) -> dict[str, str]:
    local_hints = dict(hints or {})
    start_pdf_page = _coerce_positive_int(local_hints.get("book_page_start_pdf_page"))
    start_value = _coerce_positive_int(local_hints.get("book_page_start_value"))
    if start_pdf_page is None or start_value is None:
        local_hints.pop("book_page_start_pdf_page", None)
        local_hints.pop("book_page_start_value", None)
        return local_hints

    chunk_start_pdf_page = start_page_index + 1
    chunk_end_pdf_page = end_page_index
    if start_pdf_page > chunk_end_pdf_page:
        local_hints.pop("book_page_start_pdf_page", None)
        local_hints.pop("book_page_start_value", None)
        return local_hints

    if start_pdf_page >= chunk_start_pdf_page:
        local_hints["book_page_start_pdf_page"] = str(start_pdf_page - chunk_start_pdf_page + 1)
        local_hints["book_page_start_value"] = str(start_value)
        return local_hints

    local_hints["book_page_start_pdf_page"] = "1"
    local_hints["book_page_start_value"] = str(start_value + (chunk_start_pdf_page - start_pdf_page))
    return local_hints


def _build_single_paragraph_from_page_text(
    *,
    page_text: str,
    pdf_page_no: int,
    paragraph_no_in_doc_start: int,
    global_line_start: int,
) -> tuple[list[dict[str, Any]], int, int]:
    text = page_text.strip()
    if not text:
        return [], paragraph_no_in_doc_start, global_line_start

    line_count = max(1, text.count("\n") + 1)
    line_end = global_line_start + line_count - 1
    paragraphs = [
        {
            "paragraph_id": f"page-{pdf_page_no}-p1",
            "paragraph_no": 1,
            "paragraph_no_in_doc": paragraph_no_in_doc_start,
            "text": text,
            "line_start": global_line_start,
            "line_end": line_end,
        }
    ]
    return paragraphs, paragraph_no_in_doc_start + 1, line_end + 2


def build_structured_document_from_mineru_response(
    *,
    source_filename: str,
    title: str,
    parser_name: str,
    response: mineru_pb2.ParsePdfResponse,
    hints: dict[str, str] | None = None,
) -> dict[str, Any]:
    hints = hints or {}

    if not response.document.pages and response.document.full_text.strip():
        payload = build_structured_document(
            source_filename=source_filename,
            title=title,
            text=response.document.full_text,
            parser_name=parser_name,
            hints=hints,
        )
        payload["provider"] = "mineru_grpc"
        if response.task_id:
            payload["provider_result_meta"] = {"task_id": response.task_id}
        return payload

    pages: list[dict[str, Any]] = []
    page_texts: list[str] = []
    paragraph_no_in_doc = 1
    global_line = 1

    for page_index, page in enumerate(response.document.pages, start=1):
        pdf_page_no = page.pdf_page_no or page.page_no or page_index
        page_reference = build_page_reference(
            pdf_page_no,
            hints,
            page_no=page.page_no or None,
            book_page_no=page.book_page_no or None,
            page_number_source=page.page_number_source or None,
        )
        paragraphs: list[dict[str, Any]] = []
        page_text_parts: list[str] = []

        for paragraph_index, paragraph in enumerate(page.paragraphs, start=1):
            text = paragraph.text.strip()
            if not text:
                continue

            line_start = _coerce_positive_int(paragraph.line_start) or global_line
            line_end = _coerce_positive_int(paragraph.line_end)
            if line_end is None or line_end < line_start:
                line_end = line_start + max(1, text.count("\n") + 1) - 1

            bbox = _bbox_to_payload(paragraph.bbox if paragraph.HasField("bbox") else None)
            payload = {
                "paragraph_id": paragraph.paragraph_id or f"page-{pdf_page_no}-p{paragraph_index}",
                "paragraph_no": paragraph_index,
                "paragraph_no_in_doc": paragraph_no_in_doc,
                "text": text,
                "line_start": line_start,
                "line_end": line_end,
            }
            if bbox is not None:
                payload["bbox"] = bbox
                payload["bbox_source"] = paragraph.bbox_source or "mineru_grpc"

            paragraphs.append(payload)
            page_text_parts.append(text)
            paragraph_no_in_doc += 1
            global_line = line_end + 2

        page_text = page.text.strip() or "\n\n".join(page_text_parts).strip()
        if not paragraphs and page_text:
            paragraphs, paragraph_no_in_doc, global_line = _build_single_paragraph_from_page_text(
                page_text=page_text,
                pdf_page_no=pdf_page_no,
                paragraph_no_in_doc_start=paragraph_no_in_doc,
                global_line_start=global_line,
            )

        meta = {}
        if page.page_width > 0:
            meta["page_width"] = page.page_width
        if page.page_height > 0:
            meta["page_height"] = page.page_height

        pages.append(
            {
                **page_reference,
                "text": page_text,
                "paragraphs": paragraphs,
                "meta": meta,
            }
        )
        page_texts.append(page_text)

    payload = {
        "schema_version": 1,
        "source_filename": source_filename,
        "title": title,
        "parser_name": parser_name,
        "hints": hints,
        "full_text": response.document.full_text.strip() or "\f".join(page_texts).strip(),
        "pages": pages,
        "provider": "mineru_grpc",
    }
    if response.task_id:
        payload["provider_result_meta"] = {"task_id": response.task_id}
    return payload


def _merge_chunked_structured_documents(
    *,
    source_filename: str,
    title: str,
    parser_name: str,
    hints: dict[str, str] | None,
    chunk_payloads: list[dict[str, Any]],
    chunk_plan: PdfChunkPlan,
) -> dict[str, Any]:
    hints = hints or {}
    merged_pages: list[dict[str, Any]] = []
    page_texts: list[str] = []
    paragraph_no_in_doc = 1
    global_line = 1
    task_ids: list[str] = []

    for payload, (start_page_index, end_page_index) in zip(chunk_payloads, chunk_plan.chunk_ranges, strict=False):
        provider_meta = payload.get("provider_result_meta")
        if isinstance(provider_meta, dict):
            task_id = str(provider_meta.get("task_id") or "").strip()
            if task_id:
                task_ids.append(task_id)

        chunk_page_count = end_page_index - start_page_index
        for page_offset, page in enumerate(payload.get("pages") or [], start=1):
            raw_pdf_page_no = _coerce_positive_int(page.get("pdf_page_no"))
            if raw_pdf_page_no is None:
                raw_pdf_page_no = _coerce_positive_int(page.get("page_no")) or page_offset

            if 1 <= raw_pdf_page_no <= chunk_page_count:
                global_pdf_page_no = start_page_index + raw_pdf_page_no
            else:
                global_pdf_page_no = raw_pdf_page_no

            page_text = str(page.get("text") or "").strip()
            raw_paragraphs = page.get("paragraphs") or []
            paragraphs: list[dict[str, Any]] = []

            for paragraph in raw_paragraphs:
                text = str(paragraph.get("text") or "").strip()
                if not text:
                    continue

                paragraph_index = len(paragraphs) + 1
                line_start = global_line
                line_end = line_start + max(1, text.count("\n") + 1) - 1

                paragraph_payload = {
                    "paragraph_id": f"page-{global_pdf_page_no}-p{paragraph_index}",
                    "paragraph_no": paragraph_index,
                    "paragraph_no_in_doc": paragraph_no_in_doc,
                    "text": text,
                    "line_start": line_start,
                    "line_end": line_end,
                }
                if paragraph.get("bbox") is not None:
                    paragraph_payload["bbox"] = paragraph.get("bbox")
                if paragraph.get("bbox_source") is not None:
                    paragraph_payload["bbox_source"] = paragraph.get("bbox_source")

                paragraphs.append(paragraph_payload)
                paragraph_no_in_doc += 1
                global_line = line_end + 2

            if not paragraphs and page_text:
                paragraphs, paragraph_no_in_doc, global_line = _build_single_paragraph_from_page_text(
                    page_text=page_text,
                    pdf_page_no=global_pdf_page_no,
                    paragraph_no_in_doc_start=paragraph_no_in_doc,
                    global_line_start=global_line,
                )

            page_payload = {
                **build_page_reference(global_pdf_page_no, hints),
                "text": page_text,
                "paragraphs": paragraphs,
            }
            if isinstance(page.get("meta"), dict) and page.get("meta"):
                page_payload["meta"] = page.get("meta")

            merged_pages.append(page_payload)
            page_texts.append(page_text)

    merged_payload: dict[str, Any] = {
        "schema_version": 1,
        "source_filename": source_filename,
        "title": title,
        "parser_name": parser_name,
        "hints": hints,
        "full_text": "\f".join(page_texts).strip(),
        "pages": merged_pages,
        "provider": "mineru_grpc",
        "provider_result_meta": {
            "chunked": True,
            "chunk_count": len(chunk_payloads),
            "total_pages": chunk_plan.total_pages,
            "chunk_page_count": chunk_plan.chunk_page_count,
            "chunk_ranges": [
                {
                    "start_pdf_page": start_page_index + 1,
                    "end_pdf_page": end_page_index,
                }
                for start_page_index, end_page_index in chunk_plan.chunk_ranges
            ],
        },
    }
    if task_ids:
        merged_payload["provider_result_meta"]["task_ids"] = task_ids
    return merged_payload


def build_structured_document_from_mineru_grpc(
    file_path: Path,
    *,
    title: str,
    parser_name: str,
    hints: dict[str, str] | None = None,
    language_hint: str | None = None,
    file_content: bytes | None = None,
) -> dict[str, Any]:
    config = _get_mineru_config()
    hints = hints or {}
    chunk_plan = _maybe_build_pdf_chunk_plan(file_path, config, file_content)
    if chunk_plan is None:
        response = _parse_pdf_response_via_mineru_grpc(
            file_path,
            config=config,
            hints=hints,
            language_hint=language_hint,
            file_content=file_content,
        )
        return build_structured_document_from_mineru_response(
            source_filename=file_path.name,
            title=title,
            parser_name=parser_name,
            response=response,
            hints=hints,
        )

    logger.info(
        "Auto-splitting PDF for MinerU OCR: %s (%s pages, %s bytes) into %s chunks of up to %s pages",
        file_path.name,
        chunk_plan.total_pages,
        chunk_plan.file_size_bytes,
        len(chunk_plan.chunk_ranges),
        chunk_plan.chunk_page_count,
    )

    chunk_payloads: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="mineru-pdf-chunks-") as temp_dir:
        import io

        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(io.BytesIO(file_content) if file_content is not None else str(file_path))
        temp_dir_path = Path(temp_dir)
        for chunk_index, (start_page_index, end_page_index) in enumerate(chunk_plan.chunk_ranges, start=1):
            chunk_path = temp_dir_path / f"{file_path.stem}.part{chunk_index:03d}.pdf"
            writer = PdfWriter()
            for page_index in range(start_page_index, end_page_index):
                writer.add_page(reader.pages[page_index])
            with chunk_path.open("wb") as handle:
                writer.write(handle)

            chunk_hints = _build_chunk_local_hints(
                hints=hints,
                start_page_index=start_page_index,
                end_page_index=end_page_index,
            )
            response = _parse_pdf_response_via_mineru_grpc(
                chunk_path,
                config=config,
                hints=chunk_hints,
                language_hint=language_hint,
            )
            chunk_payloads.append(
                build_structured_document_from_mineru_response(
                    source_filename=file_path.name,
                    title=title,
                    parser_name=parser_name,
                    response=response,
                    hints=chunk_hints,
                )
            )

    return _merge_chunked_structured_documents(
        source_filename=file_path.name,
        title=title,
        parser_name=parser_name,
        hints=hints,
        chunk_payloads=chunk_payloads,
        chunk_plan=chunk_plan,
    )
