"""SQLite-backed paragraph store — fast alternative to reading .structured.json files.

Populated by scripts/ingest_structured_docs_to_db.py.
Used by locator.py as the primary source; falls back to file-based loading when
the DB doesn't exist or the doc_id isn't found.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.community.knowledge_base.common import resolve_project_path
from src.config.knowledge_base_config import get_knowledge_base_config

logger = logging.getLogger(__name__)


def _paragraphs_db_path() -> Path:
    kb_config = get_knowledge_base_config()
    docs_path = resolve_project_path(kb_config.docs_path)
    return docs_path.parent / "paragraphs.db"


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA query_only=ON")
    return conn


def _reconstruct_payload(doc_id: str, rows: list[sqlite3.Row], title: str, filename: str) -> dict[str, Any]:
    """Reconstruct the structured-document dict format from DB rows.

    The output matches what load_structured_document() returns so all
    downstream locator/retriever code works without modification.
    """
    pages_map: dict[int, dict[str, Any]] = {}
    for row in rows:
        pdf_page_no = int(row["pdf_page_no"])
        if pdf_page_no not in pages_map:
            pages_map[pdf_page_no] = {
                "pdf_page_no": pdf_page_no,
                "page_no": int(row["page_no"]),
                "book_page_no": row["book_page_no"],
                "page_number_source": "book" if row["book_page_no"] is not None else "pdf",
                "text": "",
                "paragraphs": [],
            }
        page = pages_map[pdf_page_no]
        # Deserialize position stored as a JSON array, e.g. [x, y, width, height]
        raw_pos = row["position"] if "position" in row.keys() else None
        position = json.loads(raw_pos) if raw_pos else None
        para: dict[str, Any] = {
            "paragraph_id": str(row["paragraph_id"]),
            "paragraph_no": int(row["paragraph_no"]),
            "paragraph_no_in_doc": int(row["paragraph_no_in_doc"]),
            "text": str(row["text"]),
        }
        if position is not None:
            para["position"] = position
        layout_type = row["layout_type"] if "layout_type" in row.keys() else None
        if layout_type:
            para["layout_type"] = str(layout_type)
        page["paragraphs"].append(para)

    for page in pages_map.values():
        page["text"] = "\n\n".join(p["text"] for p in page["paragraphs"])

    pages = sorted(pages_map.values(), key=lambda p: p["pdf_page_no"])
    return {
        "schema_version": 1,
        "source_filename": filename,
        "title": title,
        "pages": pages,
    }


def _normalize_db_doc_id(doc_id: str) -> str:
    """Strip the legacy .ingestion/ prefix from a DB doc_id.

    The ingest script used to store doc_ids as ".ingestion/filename.pdf"
    (relative to docs_root including the staging subdir).  Catalog code
    always uses just "filename.pdf".  This helper normalizes both forms to
    the catalog format so comparisons work correctly.
    """
    return doc_id[len(".ingestion/"):] if doc_id.startswith(".ingestion/") else doc_id


def _build_catalog_to_db_id_map(conn: sqlite3.Connection, catalog_ids: list[str]) -> dict[str, str]:
    """Return {catalog_id → DB_doc_id} for every catalog_id that exists in the DB.

    Matches first by exact doc_id, then by the books.filename column (which is just
    the bare filename, e.g. "中国财政通史 第8卷（下）.pdf").  The second path handles
    the common case where the DB stores ".ingestion/filename.pdf" but the catalog
    passes "filename.pdf".
    """
    if not catalog_ids:
        return {}
    from pathlib import Path as _Path

    placeholders = ",".join("?" * len(catalog_ids))
    basenames = [_Path(d).name for d in catalog_ids]
    bn_placeholders = ",".join("?" * len(basenames))
    rows = conn.execute(
        f"SELECT doc_id, filename FROM books WHERE doc_id IN ({placeholders}) OR filename IN ({bn_placeholders})",
        catalog_ids + basenames,
    ).fetchall()

    by_doc_id: dict[str, str] = {str(r["doc_id"]): str(r["doc_id"]) for r in rows}
    by_filename: dict[str, str] = {str(r["filename"]): str(r["doc_id"]) for r in rows}

    result: dict[str, str] = {}
    for cid in catalog_ids:
        if cid in by_doc_id:
            result[cid] = cid  # exact match
        else:
            db_id = by_filename.get(_Path(cid).name)
            if db_id is not None:
                result[cid] = db_id  # filename-based match
    return result


def get_global_doc_ids_in_db(doc_ids: list[str]) -> set[str]:
    """Return the subset of doc_ids (catalog format) that exist in paragraphs.db.

    Handles the legacy case where DB stores ".ingestion/filename.pdf" while
    catalog code passes "filename.pdf" — matches on both doc_id and filename.
    Returns the INPUT catalog-format doc_ids (not the raw DB doc_ids).
    """
    if not doc_ids:
        return set()
    db_path = _paragraphs_db_path()
    if not db_path.exists():
        return set()
    try:
        conn = _connect(db_path)
        try:
            return set(_build_catalog_to_db_id_map(conn, doc_ids).keys())
        finally:
            conn.close()
    except Exception:
        logger.debug("paragraph_store: get_global_doc_ids_in_db failed", exc_info=True)
        return set()


def search_fts(
    query: str,
    *,
    doc_ids: list[str],
    top_k: int,
) -> list[dict[str, Any]]:
    """FTS5 关键词检索，只查 paragraphs.db 里的全局书目。

    doc_ids are in catalog format (e.g., "filename.pdf").  Internally translates
    them to the DB format (which may be ".ingestion/filename.pdf") before querying.
    Returns results with doc_id normalized to catalog format (no .ingestion/ prefix).
    """
    from src.community.knowledge_base.common import normalize_search_text, tokenize_search_text

    db_path = _paragraphs_db_path()
    if not db_path.exists() or not doc_ids:
        return []

    # 构造 FTS MATCH 表达式
    terms = list(dict.fromkeys(tokenize_search_text(query)))[:24]
    if not terms:
        return []
    match_expr = " OR ".join(f'"{t.replace(chr(34), "")}"' for t in terms)

    try:
        conn = _connect(db_path)
        try:
            # Translate catalog doc_ids → DB doc_ids (handles .ingestion/ prefix mismatch)
            id_map = _build_catalog_to_db_id_map(conn, doc_ids)
            if not id_map:
                return []
            db_ids = list(id_map.values())

            placeholders = ",".join("?" * len(db_ids))
            sql = f"""
                SELECT doc_id, title, filename,
                       page_no, pdf_page_no,
                       paragraph_no, paragraph_no_in_doc, text
                FROM paragraph_fts
                WHERE paragraph_fts MATCH ?
                  AND doc_id IN ({placeholders})
                LIMIT ?
            """
            params: list[Any] = [match_expr, *db_ids, max(200, top_k * 40)]
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
    except Exception:
        logger.debug("paragraph_store: search_fts failed", exc_info=True)
        return []

    # 评分：主词命中数
    primary_terms = list(dict.fromkeys(
        t for t in normalize_search_text(query).split() if t
    ))[:12]

    def _score(row: sqlite3.Row) -> tuple[int, int, int]:
        txt = normalize_search_text(str(row["text"])).replace(" ", "")
        primary_hits = sum(1 for t in primary_terms if t in txt)
        exact_hit = int(bool(normalize_search_text(query) and normalize_search_text(query) in txt))
        token_hits = sum(1 for t in terms if t in txt)
        return (exact_hit, primary_hits, token_hits)

    scored = sorted(rows, key=_score, reverse=True)
    results = []
    for row in scored[:top_k]:
        text = str(row["text"] or "").strip()
        norm_txt = normalize_search_text(text).replace(" ", "")
        matched_keywords = [t for t in primary_terms if t in norm_txt]
        # Normalize doc_id to catalog format (strip legacy .ingestion/ prefix)
        result_doc_id = _normalize_db_doc_id(str(row["doc_id"] or ""))
        results.append({
            "content": text,
            "metadata": {
                "title": row["title"],
                "doc_id": result_doc_id,
                "page_no": row["page_no"],
                "pdf_page_no": row["pdf_page_no"],
                "paragraph_no": row["paragraph_no"],
                "paragraph_no_in_doc": row["paragraph_no_in_doc"],
                "scope": "global",
                "filename": row["filename"],
                "source": row["filename"],
                "source_kind": "global_document",
            },
            "score": float(sum(_score(row))),
            "matched_keywords": matched_keywords,
            "match_type": "keyword_fts",
            "source": row["filename"],
            "filename": row["filename"],
            "collection_name": "keyword_fts",
        })
    return results


def lookup_global_book_meta(doc_id: str) -> dict[str, Any] | None:
    """从 paragraphs.db 查单本书的元数据（title/filename/source_url/original_url）。

    Performs an exact doc_id match only.  Returns None if not found — callers
    should fall back to lookup_global_book_meta_by_filename or file scanning.
    """
    db_path = _paragraphs_db_path()
    if not db_path.exists():
        return None
    try:
        conn = _connect(db_path)
        try:
            row = conn.execute(
                "SELECT doc_id, title, filename, source_url, original_url FROM books WHERE doc_id = ?",
                (doc_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "doc_id": str(row["doc_id"]),
                "title": str(row["title"] or ""),
                "filename": str(row["filename"] or ""),
                "source_url": str(row["source_url"] or ""),
                "original_url": row["original_url"],
            }
        finally:
            conn.close()
    except Exception:
        logger.debug("paragraph_store: lookup_global_book_meta failed for doc_id=%s", doc_id, exc_info=True)
        return None


def lookup_global_book_meta_by_filename(filename: str) -> dict[str, Any] | None:
    """从 paragraphs.db 按 filename 查单本书的元数据。"""
    db_path = _paragraphs_db_path()
    if not db_path.exists():
        return None
    try:
        conn = _connect(db_path)
        try:
            row = conn.execute(
                "SELECT doc_id, title, filename, source_url, original_url FROM books WHERE filename = ? LIMIT 1",
                (filename,),
            ).fetchone()
            if row is None:
                return None
            return {
                "doc_id": str(row["doc_id"]),
                "title": str(row["title"] or ""),
                "filename": str(row["filename"] or ""),
                "source_url": str(row["source_url"] or ""),
                "original_url": row["original_url"],
            }
        finally:
            conn.close()
    except Exception:
        logger.debug("paragraph_store: lookup_global_book_meta_by_filename failed for filename=%s", filename, exc_info=True)
        return None


@lru_cache(maxsize=256)
def _load_payload_cached(db_path_str: str, doc_id: str) -> dict[str, Any] | None:
    """Inner cached loader — keyed by (db_path, doc_id) so the cache auto-scopes to one DB."""
    try:
        conn = _connect(Path(db_path_str))
        try:
            book = conn.execute(
                "SELECT title, filename FROM books WHERE doc_id = ?", (doc_id,)
            ).fetchone()
            if book is None:
                return None
            rows = conn.execute(
                """
                SELECT pdf_page_no, page_no, book_page_no,
                       paragraph_no, paragraph_no_in_doc, paragraph_id, text,
                       position, layout_type
                FROM paragraphs
                WHERE doc_id = ?
                ORDER BY paragraph_no_in_doc
                """,
                (doc_id,),
            ).fetchall()
            if not rows:
                return None
            return _reconstruct_payload(
                doc_id,
                rows,
                title=str(book["title"] or ""),
                filename=str(book["filename"] or ""),
            )
        finally:
            conn.close()
    except Exception:
        logger.debug("paragraph_store: failed to load doc_id=%s from DB", doc_id, exc_info=True)
        return None


def load_structured_payload_from_db(doc_id: str) -> dict[str, Any] | None:
    """Return the structured-document payload for doc_id from paragraphs.db.

    Returns None if the DB doesn't exist, the doc isn't in the DB, or any
    error occurs — callers should fall back to file-based loading.
    Result is LRU-cached by (db_path, doc_id) — identical to load_structured_document's
    caching strategy, so repeated calls for the same doc within a process are free.
    """
    db_path = _paragraphs_db_path()
    if not db_path.exists():
        return None
    return _load_payload_cached(str(db_path), doc_id)
