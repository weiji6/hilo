"""SQLite FTS-backed keyword search over structured document paragraphs."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.community.knowledge_base.common import (
    derive_global_doc_id,
    derive_thread_doc_id,
    derive_user_doc_id,
    normalize_search_text,
    resolve_project_path,
    tokenize_search_text,
)
from src.community.knowledge_base.ingestion import list_ingestion_records
from src.community.knowledge_base.structured_document import load_structured_document
from src.community.knowledge_base.user_store import list_user_records
from src.config.knowledge_base_config import get_knowledge_base_config
from src.config.paths import get_paths

logger = logging.getLogger(__name__)

INDEX_VERSION = 1
MIN_INDEXED_CHARS = 18
MIN_INDEXED_TOKENS = 3
DEFAULT_CANDIDATE_LIMIT = 200

_LOCK_GUARD = threading.Lock()
_DOC_LOCKS: dict[tuple[str, str, str], threading.Lock] = {}


@dataclass(frozen=True)
class IndexedDocument:
    scope: str
    owner_id: str
    doc_id: str
    title: str
    filename: str
    structured_path: Path
    source_path: str
    source_kind: str
    origin_doc_id: str | None = None
    user_id: str | None = None
    thread_id: str | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owner_value(value: str | None) -> str:
    return value or ""


def _doc_lock(scope: str, owner_id: str, doc_id: str) -> threading.Lock:
    key = (scope, owner_id, doc_id)
    with _LOCK_GUARD:
        lock = _DOC_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _DOC_LOCKS[key] = lock
        return lock


def _db_path() -> Path:
    paths = get_paths()
    paths.ensure_knowledge_search_dirs()
    return paths.knowledge_search_db_path()


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(_db_path())
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA temp_store=MEMORY")
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS doc_index_state (
            scope TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            structured_path TEXT NOT NULL,
            structured_mtime_ns INTEGER NOT NULL,
            structured_size INTEGER NOT NULL,
            index_version INTEGER NOT NULL,
            indexed_at TEXT NOT NULL,
            PRIMARY KEY (scope, owner_id, doc_id)
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS paragraph_fts USING fts5(
            search_text,
            scope UNINDEXED,
            owner_id UNINDEXED,
            doc_id UNINDEXED,
            title UNINDEXED,
            filename UNINDEXED,
            source_path UNINDEXED,
            source_kind UNINDEXED,
            origin_doc_id UNINDEXED,
            page_no UNINDEXED,
            pdf_page_no UNINDEXED,
            paragraph_no UNINDEXED,
            paragraph_no_in_doc UNINDEXED,
            line_start UNINDEXED,
            line_end UNINDEXED,
            text UNINDEXED,
            tokenize='unicode61 remove_diacritics 2'
        );
        """
    )


def _iter_global_documents(doc_id_set: set[str]) -> Iterable[IndexedDocument]:
    docs_root = resolve_project_path(get_knowledge_base_config().docs_path)
    ingestion_dir = docs_root / ".ingestion"
    if not ingestion_dir.exists():
        return []

    documents: list[IndexedDocument] = []
    for record_path in sorted(ingestion_dir.glob("*.json")):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if record.get("schema_version") == 1:
            continue
        source_filename = str(record.get("source_filename") or "")
        if not source_filename or not record.get("indexable"):
            continue
        doc_id = derive_global_doc_id(docs_root, docs_root / source_filename)
        if doc_id not in doc_id_set:
            continue
        structured_path = Path(str(record.get("structured_path"))) if record.get("structured_path") else None
        if structured_path is None or not structured_path.exists():
            continue
        payload = load_structured_document(structured_path)
        if not payload:
            continue
        documents.append(
            IndexedDocument(
                scope="global",
                owner_id="",
                doc_id=doc_id,
                title=str(payload.get("title") or record.get("display_title") or Path(source_filename).stem),
                filename=source_filename,
                structured_path=structured_path,
                source_path=str(record.get("structured_path") or record.get("source_path") or source_filename),
                source_kind="global_document",
            )
        )
    return documents


def _iter_thread_documents(thread_id: str, doc_id_set: set[str]) -> Iterable[IndexedDocument]:
    documents: list[IndexedDocument] = []
    for record in list_ingestion_records(thread_id):
        source_filename = str(record.get("source_filename") or record.get("index_target_filename") or "")
        if not source_filename or not record.get("indexable"):
            continue
        doc_id = derive_thread_doc_id(Path(source_filename))
        if doc_id not in doc_id_set:
            continue
        structured_path = Path(str(record.get("structured_path"))) if record.get("structured_path") else None
        if structured_path is None or not structured_path.exists():
            continue
        payload = load_structured_document(structured_path)
        if not payload:
            continue
        documents.append(
            IndexedDocument(
                scope="thread",
                owner_id=thread_id,
                doc_id=doc_id,
                title=str(payload.get("title") or record.get("display_title") or Path(source_filename).stem),
                filename=source_filename,
                structured_path=structured_path,
                source_path=str(record.get("structured_path") or record.get("source_path") or source_filename),
                source_kind="thread_upload",
                thread_id=thread_id,
            )
        )
    return documents


def _iter_user_documents(user_id: str, doc_id_set: set[str]) -> Iterable[IndexedDocument]:
    documents: list[IndexedDocument] = []
    for record in list_user_records(user_id):
        if not record.get("retrieval_enabled") or not record.get("indexable"):
            continue
        source_filename = str(record.get("source_filename") or record.get("index_target_filename") or "")
        record_id = str(record.get("id") or "")
        if not source_filename or not record_id:
            continue
        doc_id = derive_user_doc_id(record_id)
        if doc_id not in doc_id_set:
            continue
        structured_path = Path(str(record.get("structured_path"))) if record.get("structured_path") else None
        if structured_path is None or not structured_path.exists():
            continue
        payload = load_structured_document(structured_path)
        if not payload:
            continue
        documents.append(
            IndexedDocument(
                scope="user",
                owner_id=user_id,
                doc_id=doc_id,
                title=str(payload.get("title") or record.get("display_title") or Path(source_filename).stem),
                filename=source_filename,
                structured_path=structured_path,
                source_path=str(record.get("structured_path") or record.get("source_path") or source_filename),
                source_kind=str(record.get("source_kind") or "upload"),
                origin_doc_id=record.get("origin_doc_id"),
                user_id=user_id,
            )
        )
    return documents


def resolve_documents_for_doc_ids(
    *,
    thread_id: str | None,
    user_id: str | None,
    doc_ids: list[str],
) -> list[IndexedDocument]:
    doc_id_set = {doc_id.strip() for doc_id in doc_ids if doc_id and doc_id.strip()}
    if not doc_id_set:
        return []

    documents: list[IndexedDocument] = []
    seen: set[tuple[str, str, str]] = set()

    if user_id:
        for document in _iter_user_documents(user_id, doc_id_set):
            key = (document.scope, document.owner_id, document.doc_id)
            if key not in seen:
                seen.add(key)
                documents.append(document)

    if thread_id:
        for document in _iter_thread_documents(thread_id, doc_id_set):
            key = (document.scope, document.owner_id, document.doc_id)
            if key not in seen:
                seen.add(key)
                documents.append(document)

    for document in _iter_global_documents(doc_id_set):
        key = (document.scope, document.owner_id, document.doc_id)
        if key not in seen:
            seen.add(key)
            documents.append(document)

    return documents


def _is_indexable_paragraph(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < MIN_INDEXED_CHARS:
        return False
    return len(tokenize_search_text(stripped)) >= MIN_INDEXED_TOKENS


def _build_search_text(text: str) -> str:
    return " ".join(tokenize_search_text(text))


def _paragraph_rows(document: IndexedDocument) -> list[tuple[Any, ...]]:
    payload = load_structured_document(document.structured_path)
    if not payload:
        return []

    rows: list[tuple[Any, ...]] = []
    for page in payload.get("pages") or []:
        page_no = page.get("page_no")
        pdf_page_no = page.get("pdf_page_no") or page_no
        for paragraph in page.get("paragraphs") or []:
            text = str(paragraph.get("text") or "").strip()
            if not _is_indexable_paragraph(text):
                continue
            search_text = _build_search_text(text)
            if not search_text:
                continue
            rows.append(
                (
                    search_text,
                    document.scope,
                    document.owner_id,
                    document.doc_id,
                    document.title,
                    document.filename,
                    document.source_path,
                    document.source_kind,
                    document.origin_doc_id,
                    page_no,
                    pdf_page_no,
                    paragraph.get("paragraph_no"),
                    paragraph.get("paragraph_no_in_doc"),
                    paragraph.get("line_start"),
                    paragraph.get("line_end"),
                    text,
                )
            )
    return rows


def _needs_reindex(connection: sqlite3.Connection, document: IndexedDocument) -> bool:
    try:
        stat = document.structured_path.stat()
    except OSError:
        return False

    row = connection.execute(
        """
        SELECT structured_mtime_ns, structured_size, index_version
        FROM doc_index_state
        WHERE scope = ? AND owner_id = ? AND doc_id = ?
        """,
        (document.scope, document.owner_id, document.doc_id),
    ).fetchone()
    if row is None:
        return True
    return (
        int(row["structured_mtime_ns"]) != int(stat.st_mtime_ns)
        or int(row["structured_size"]) != int(stat.st_size)
        or int(row["index_version"]) != INDEX_VERSION
    )


def ensure_documents_indexed(documents: list[IndexedDocument]) -> None:
    if not documents:
        return

    connection = _connect()
    try:
        _ensure_schema(connection)
        for document in documents:
            lock = _doc_lock(document.scope, document.owner_id, document.doc_id)
            with lock:
                if not _needs_reindex(connection, document):
                    continue
                try:
                    stat = document.structured_path.stat()
                except OSError:
                    continue
                rows = _paragraph_rows(document)
                with connection:
                    connection.execute(
                        "DELETE FROM paragraph_fts WHERE scope = ? AND owner_id = ? AND doc_id = ?",
                        (document.scope, document.owner_id, document.doc_id),
                    )
                    if rows:
                        connection.executemany(
                            """
                            INSERT INTO paragraph_fts (
                                search_text,
                                scope,
                                owner_id,
                                doc_id,
                                title,
                                filename,
                                source_path,
                                source_kind,
                                origin_doc_id,
                                page_no,
                                pdf_page_no,
                                paragraph_no,
                                paragraph_no_in_doc,
                                line_start,
                                line_end,
                                text
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            rows,
                        )
                    connection.execute(
                        """
                        INSERT INTO doc_index_state (
                            scope,
                            owner_id,
                            doc_id,
                            structured_path,
                            structured_mtime_ns,
                            structured_size,
                            index_version,
                            indexed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(scope, owner_id, doc_id) DO UPDATE SET
                            structured_path = excluded.structured_path,
                            structured_mtime_ns = excluded.structured_mtime_ns,
                            structured_size = excluded.structured_size,
                            index_version = excluded.index_version,
                            indexed_at = excluded.indexed_at
                        """,
                        (
                            document.scope,
                            document.owner_id,
                            document.doc_id,
                            str(document.structured_path),
                            int(stat.st_mtime_ns),
                            int(stat.st_size),
                            INDEX_VERSION,
                            _utc_now(),
                        ),
                    )
                logger.info(
                    "Keyword search index built: scope=%s owner=%s doc_id=%s paragraphs=%s path=%s",
                    document.scope,
                    document.owner_id,
                    document.doc_id,
                    len(rows),
                    document.structured_path,
                )
    finally:
        connection.close()


def _extract_exact_keywords(query: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for token in tokenize_search_text(query):
        normalized = token.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        candidates.append(normalized)
    return candidates[:24]


def _extract_primary_terms(query: str) -> list[str]:
    normalized = normalize_search_text(query)
    if not normalized:
        return []
    primary_terms: list[str] = []
    seen: set[str] = set()
    for term in [item.strip() for item in normalized.split(" ") if item.strip()]:
        if term in seen:
            continue
        seen.add(term)
        primary_terms.append(term)
    return primary_terms[:12]


def _minimum_primary_match_count(query: str) -> int:
    primary_terms = _extract_primary_terms(query)
    if len(primary_terms) >= 3:
        return 2
    if len(primary_terms) >= 1:
        return 1
    return 0


def _match_expression(query: str) -> str | None:
    terms = _extract_exact_keywords(query)
    if not terms:
        return None
    quoted_terms: list[str] = []
    for term in terms:
        escaped = term.replace('"', '""')
        quoted_terms.append(f'"{escaped}"')
    return " OR ".join(quoted_terms)


def _candidate_limit(top_k: int) -> int:
    return max(DEFAULT_CANDIDATE_LIMIT, top_k * 40)


def _search_rows(
    connection: sqlite3.Connection,
    *,
    documents: list[IndexedDocument],
    query: str,
    top_k: int,
) -> list[sqlite3.Row]:
    match_expr = _match_expression(query)
    if not match_expr or not documents:
        return []

    clauses: list[str] = []
    params: list[Any] = [match_expr]
    for document in documents:
        clauses.append("(scope = ? AND owner_id = ? AND doc_id = ?)")
        params.extend((document.scope, document.owner_id, document.doc_id))

    params.append(_candidate_limit(top_k))
    sql = f"""
        SELECT
            rowid,
            scope,
            owner_id,
            doc_id,
            title,
            filename,
            source_path,
            source_kind,
            origin_doc_id,
            page_no,
            pdf_page_no,
            paragraph_no,
            paragraph_no_in_doc,
            line_start,
            line_end,
            text,
            search_text
        FROM paragraph_fts
        WHERE paragraph_fts MATCH ?
          AND ({' OR '.join(clauses)})
        LIMIT ?
    """
    return connection.execute(sql, params).fetchall()


def _score_row(query: str, row: sqlite3.Row) -> tuple[int, int, int, int]:
    text = str(row["text"] or "").strip()
    normalized_text = normalize_search_text(text)
    normalized_text_compact = normalized_text.replace(" ", "")
    primary_terms = _extract_primary_terms(query)
    matched_primary_terms = [
        term
        for term in primary_terms
        if term and term in normalized_text_compact
    ]
    exact_keywords = _extract_exact_keywords(query)
    fallback_keywords = [keyword for keyword in exact_keywords if keyword not in primary_terms]
    matched_fallback_keywords = [
        keyword
        for keyword in fallback_keywords
        if keyword and keyword in normalized_text_compact
    ]
    search_tokens = set(str(row["search_text"] or "").split())
    query_tokens = tokenize_search_text(query)
    matched_tokens = [token for token in query_tokens if token in search_tokens]
    exact_query_hit = int(bool(normalize_search_text(query) and normalize_search_text(query) in normalized_text))
    return (
        exact_query_hit,
        len(matched_primary_terms),
        len(matched_fallback_keywords),
        len(matched_tokens),
        len(text),
    )


def search_keyword_documents(
    query: str,
    *,
    thread_id: str | None,
    user_id: str | None,
    doc_ids: list[str],
    top_k: int,
) -> list[dict[str, Any]]:
    from src.community.knowledge_base.paragraph_store import (
        get_global_doc_ids_in_db,
        search_fts as _search_paragraph_fts,
    )

    clean_ids = [d for d in doc_ids if d and d.strip()]
    if not clean_ids:
        return []

    # Global docs already in paragraphs.db go through the fast DB path.
    # Everything else (thread/user docs, or global docs not yet ingested to DB)
    # goes through the existing lazy-index flow.
    db_global_ids = get_global_doc_ids_in_db(clean_ids)
    remaining_ids = [d for d in clean_ids if d not in db_global_ids]

    results: list[dict[str, Any]] = []

    if db_global_ids:
        db_results = _search_paragraph_fts(query, doc_ids=list(db_global_ids), top_k=top_k)
        results.extend(db_results)

    if remaining_ids:
        documents = resolve_documents_for_doc_ids(
            thread_id=thread_id,
            user_id=user_id,
            doc_ids=remaining_ids,
        )
        if documents:
            ensure_documents_indexed(documents)
            connection = _connect()
            try:
                _ensure_schema(connection)
                rows = _search_rows(connection, documents=documents, query=query, top_k=top_k)
            finally:
                connection.close()

            minimum_primary_matches = _minimum_primary_match_count(query)
            primary_terms = _extract_primary_terms(query)
            if minimum_primary_matches > 0:
                filtered_rows = [
                    row for row in rows if _score_row(query, row)[1] >= minimum_primary_matches
                ]
                if filtered_rows:
                    rows = filtered_rows

            scored_rows = sorted(rows, key=lambda row: _score_row(query, row), reverse=True)
            for row in scored_rows[:top_k]:
                text = str(row["text"] or "").strip()
                normalized_text = normalize_search_text(text).replace(" ", "")
                matched_keywords = [keyword for keyword in primary_terms if keyword in normalized_text]
                metadata: dict[str, Any] = {
                    "title": row["title"],
                    "doc_id": row["doc_id"],
                    "page_no": row["page_no"],
                    "pdf_page_no": row["pdf_page_no"],
                    "paragraph_no": row["paragraph_no"],
                    "paragraph_no_in_doc": row["paragraph_no_in_doc"],
                    "line_start": row["line_start"],
                    "line_end": row["line_end"],
                    "scope": row["scope"],
                    "filename": row["filename"],
                    "source": row["source_path"],
                    "source_kind": row["source_kind"],
                }
                if row["origin_doc_id"]:
                    metadata["origin_doc_id"] = row["origin_doc_id"]
                if row["scope"] == "thread" and thread_id:
                    metadata["thread_id"] = thread_id
                    metadata["source_virtual_path"] = f"/mnt/user-data/uploads/{row['filename']}"
                if row["scope"] == "user" and user_id:
                    metadata["user_id"] = user_id
                results.append({
                    "content": text,
                    "metadata": metadata,
                    "score": float(sum(_score_row(query, row)[:4])),
                    "matched_keywords": matched_keywords,
                    "match_type": "keyword_fts",
                    "source": row["source_path"],
                    "filename": row["filename"],
                    "collection_name": "keyword_fts",
                })

    results.sort(key=lambda r: r["score"], reverse=True)
    results = results[:top_k]

    logger.info(
        "Keyword FTS search complete: query=%r doc_ids=%s db_global=%s remaining=%s returned=%s",
        query,
        len(doc_ids),
        len(db_global_ids),
        len(remaining_ids),
        len(results),
    )
    return results
