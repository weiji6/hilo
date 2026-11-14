"""Baidu document parser integration for global knowledge ingestion."""

from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx
from src.community.knowledge_base.structured_document import build_page_reference
from src.community.knowledge_base.structured_document import build_bbox_from_position

TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
TASK_URL = "https://aip.baidubce.com/rest/2.0/brain/online/v2/parser/task"
QUERY_URL = "https://aip.baidubce.com/rest/2.0/brain/online/v2/parser/task/query"
DEFAULT_POLL_INTERVAL_SECONDS = 6
DEFAULT_TIMEOUT_SECONDS = 60 * 30

_token_cache: dict[str, Any] = {"access_token": None, "expires_at": 0.0}


def _get_credentials() -> tuple[str, str]:
    api_key = os.getenv("BAIDU_OCR_API_KEY")
    secret_key = os.getenv("BAIDU_OCR_SECRET_KEY")
    if not api_key or not secret_key:
        raise RuntimeError("Missing BAIDU_OCR_API_KEY or BAIDU_OCR_SECRET_KEY")
    return api_key, secret_key


def _get_access_token() -> str:
    now = time.time()
    cached_token = _token_cache.get("access_token")
    if cached_token and now < float(_token_cache.get("expires_at", 0)) - 60:
        return str(cached_token)

    api_key, secret_key = _get_credentials()
    response = httpx.post(
        TOKEN_URL,
        params={
            "grant_type": "client_credentials",
            "client_id": api_key,
            "client_secret": secret_key,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    access_token = payload.get("access_token")
    expires_in = int(payload.get("expires_in", 0))
    if not access_token:
        raise RuntimeError(f"Failed to get Baidu access token: {payload}")

    _token_cache["access_token"] = access_token
    _token_cache["expires_at"] = now + expires_in
    return str(access_token)


def _map_language_hint(language_hint: str | None) -> str:
    if language_hint == "en":
        return "CHN_ENG"
    return "CHN_ENG"


def submit_document_parse_task(
    *,
    file_name: str,
    file_url: str,
    language_hint: str | None = None,
) -> str:
    access_token = _get_access_token()
    response = httpx.post(
        TASK_URL,
        params={"access_token": access_token},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "file_url": file_url,
            "file_name": file_name,
            "language_type": _map_language_hint(language_hint),
            "html_table_format": True,
            "return_doc_chunks": json.dumps({"switch": False}, ensure_ascii=False),
        },
        timeout=120,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error_code") != 0:
        error_code = payload.get("error_code")
        error_msg = payload.get("error_msg") or payload
        raise RuntimeError(f"Baidu parser task submit failed ({error_code}): {error_msg}")

    task_id = payload.get("result", {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"Baidu parser task submit missing task_id: {payload}")
    return str(task_id)


def query_document_parse_task(task_id: str) -> dict[str, Any]:
    access_token = _get_access_token()
    response = httpx.post(
        QUERY_URL,
        params={"access_token": access_token},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"task_id": task_id},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error_code") != 0:
        raise RuntimeError(f"Baidu parser task query failed: {payload.get('error_msg') or payload}")
    return payload.get("result", {}) or {}


def wait_for_document_parse_result(
    task_id: str,
    *,
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        result = query_document_parse_task(task_id)
        status = result.get("status")
        if status == "success":
            return result
        if status == "failed":
            raise RuntimeError(f"Baidu parser task failed: {result.get('task_error') or result}")
        time.sleep(poll_interval_seconds)
    raise TimeoutError(f"Baidu parser task timed out after {timeout_seconds}s")


def download_parse_result(parse_result_url: str) -> dict[str, Any]:
    response = httpx.get(parse_result_url, timeout=120)
    response.raise_for_status()
    return response.json()


def build_structured_document_from_baidu_result(
    *,
    source_filename: str,
    title: str,
    parser_name: str,
    parse_result: dict[str, Any],
    hints: dict[str, str] | None = None,
) -> dict[str, Any]:
    hints = hints or {}
    pages_payload = parse_result.get("pages") or []
    pages: list[dict[str, Any]] = []
    full_text_parts: list[str] = []
    paragraph_no_in_doc = 1
    global_line = 1

    for page_index, page in enumerate(pages_payload, start=1):
        page_num = int(page.get("page_num", page_index))
        pdf_page_no = page_num + 1 if page_num == 0 else page_num
        page_reference = build_page_reference(pdf_page_no, hints)
        page_text = str(page.get("text") or "").strip()
        full_text_parts.append(page_text)
        paragraphs: list[dict[str, Any]] = []
        paragraph_no_on_page = 1

        tables_by_layout = {
            str(table.get("layout_id")): table
            for table in (page.get("tables") or [])
            if table.get("layout_id")
        }

        for layout in page.get("layouts") or []:
            layout_type = str(layout.get("type") or "para")
            layout_id = str(layout.get("layout_id") or "")
            text = str(layout.get("text") or "").strip()

            if layout_type == "table":
                table = tables_by_layout.get(layout_id, {})
                text = str(table.get("markdown") or text).strip()

            if not text:
                continue

            line_count = max(1, text.count("\n") + 1)
            paragraphs.append(
                {
                    "paragraph_id": layout_id or f"page-{pdf_page_no}-p{paragraph_no_on_page}",
                    "paragraph_no": paragraph_no_on_page,
                    "paragraph_no_in_doc": paragraph_no_in_doc,
                    "text": text,
                    "line_start": global_line,
                    "line_end": global_line + line_count - 1,
                    "layout_type": layout_type,
                    "position": layout.get("position"),
                    "bbox": build_bbox_from_position(layout.get("position")),
                    "bbox_source": "baidu_layout_position",
                    "sub_type": layout.get("sub_type"),
                }
            )
            paragraph_no_on_page += 1
            paragraph_no_in_doc += 1
            global_line += line_count + 1

        if not paragraphs and page_text:
            line_count = max(1, page_text.count("\n") + 1)
            paragraphs.append(
                {
                    "paragraph_id": f"page-{pdf_page_no}-p{paragraph_no_on_page}",
                    "paragraph_no": paragraph_no_on_page,
                    "paragraph_no_in_doc": paragraph_no_in_doc,
                    "text": page_text,
                    "line_start": global_line,
                    "line_end": global_line + line_count - 1,
                    "layout_type": "page_text",
                }
            )
            paragraph_no_on_page += 1
            paragraph_no_in_doc += 1
            global_line += line_count + 1

        pages.append(
            {
                **page_reference,
                "text": page_text,
                "paragraphs": paragraphs,
                "meta": page.get("meta") or {},
            }
        )

    return {
        "schema_version": 1,
        "source_filename": source_filename,
        "title": title,
        "parser_name": parser_name,
        "hints": hints,
        "full_text": "\f".join(full_text_parts),
        "pages": pages,
        "provider": "baidu_doc_parser",
        "provider_result_meta": {
            "file_id": parse_result.get("file_id"),
            "file_name": parse_result.get("file_name"),
        },
    }
