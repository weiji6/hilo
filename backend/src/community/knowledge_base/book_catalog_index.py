"""SQLite-backed persistent catalog store for book-level discovery.

Stores BookCatalogEntry objects in the shared knowledge-search SQLite database
so cold-start catalog builds don't require reading 1774+ individual preview files.

Global entries are cached per process behind one lock. A read connection's
SQLite data_version invalidates the cache on commits from any other connection,
including WAL writers. Database replacement is detected by device/inode identity.
User and thread entries are never stored in this shared cache.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from src.community.knowledge_base.common import tokenize_search_text
from src.config.paths import get_paths

if TYPE_CHECKING:
    from src.community.knowledge_base.catalog import BookCatalogEntry

logger = logging.getLogger(__name__)

# Bump this when the schema or serialization format changes — forces a full rebuild.
CATALOG_SCHEMA_VERSION = 3

_WRITE_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


def _db_path() -> Path:
    paths = get_paths()
    paths.ensure_knowledge_search_dirs()
    return paths.knowledge_search_db_path()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS book_catalog (
    doc_id          TEXT    NOT NULL,
    cache_thread_id TEXT    NOT NULL DEFAULT '',
    cache_user_id   TEXT    NOT NULL DEFAULT '',
    full_content    INTEGER NOT NULL DEFAULT 1,
    scope           TEXT    NOT NULL DEFAULT 'global',
    title           TEXT    NOT NULL DEFAULT '',
    filename        TEXT    NOT NULL DEFAULT '',
    source_path     TEXT    NOT NULL DEFAULT '',
    source_url      TEXT    NOT NULL DEFAULT '',
    original_url    TEXT,
    preview         TEXT    NOT NULL DEFAULT '',
    search_text     TEXT    NOT NULL DEFAULT '',
    type            TEXT    NOT NULL DEFAULT 'unknown',
    categories      TEXT    NOT NULL DEFAULT '[]',
    eras            TEXT    NOT NULL DEFAULT '[]',
    regions         TEXT    NOT NULL DEFAULT '[]',
    keywords        TEXT    NOT NULL DEFAULT '[]',
    summary         TEXT    NOT NULL DEFAULT '',
    author          TEXT    NOT NULL DEFAULT '',
    publisher       TEXT    NOT NULL DEFAULT '',
    priority        INTEGER,
    folder_path     TEXT,
    language_hint   TEXT,
    page_count      INTEGER NOT NULL DEFAULT 0,
    structured_path TEXT,
    indexed_at      TEXT    NOT NULL,
    PRIMARY KEY (doc_id, scope, cache_thread_id, cache_user_id, full_content)
);

CREATE TABLE IF NOT EXISTS book_catalog_build_state (
    cache_thread_id TEXT    NOT NULL DEFAULT '',
    cache_user_id   TEXT    NOT NULL DEFAULT '',
    full_content    INTEGER NOT NULL DEFAULT 1,
    mtime_sig       REAL    NOT NULL,
    schema_ver      INTEGER NOT NULL,
    entry_count     INTEGER NOT NULL DEFAULT 0,
    built_at        TEXT    NOT NULL,
    PRIMARY KEY (cache_thread_id, cache_user_id, full_content)
);
"""


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)


# ---------------------------------------------------------------------------
# Build-state helpers
# ---------------------------------------------------------------------------


def _is_cache_valid(
    conn: sqlite3.Connection,
    thread_id: str | None,
    user_id: str | None,
    mtime_sig: float,
) -> bool:
    row = conn.execute(
        """
        SELECT mtime_sig, schema_ver
        FROM book_catalog_build_state
        WHERE cache_thread_id = ? AND cache_user_id = ?
        """,
        (thread_id or "", user_id or ""),
    ).fetchone()
    if row is None:
        return False
    return (
        float(row["mtime_sig"]) == mtime_sig
        and int(row["schema_ver"]) == CATALOG_SCHEMA_VERSION
    )


def _write_build_state(
    conn: sqlite3.Connection,
    thread_id: str | None,
    user_id: str | None,
    mtime_sig: float,
    entry_count: int,
) -> None:
    conn.execute(
        """
        INSERT INTO book_catalog_build_state
            (cache_thread_id, cache_user_id, mtime_sig, schema_ver, entry_count, built_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(cache_thread_id, cache_user_id, full_content) DO UPDATE SET
            mtime_sig   = excluded.mtime_sig,
            schema_ver  = excluded.schema_ver,
            entry_count = excluded.entry_count,
            built_at    = excluded.built_at
        """,
        (
            thread_id or "",
            user_id or "",
            mtime_sig,
            CATALOG_SCHEMA_VERSION,
            entry_count,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

_SCOPE_ORDER = {"thread": 0, "user": 1, "global": 2}

_INSERT_SQL = """
INSERT OR REPLACE INTO book_catalog (
    doc_id, cache_thread_id, cache_user_id, scope,
    title, filename, source_path, source_url, original_url,
    preview, search_text,
    type, categories, eras, regions, keywords,
    summary, author, publisher, priority,
    folder_path, language_hint, page_count, structured_path, indexed_at
) VALUES (
    ?, ?, ?, ?,
    ?, ?, ?, ?, ?,
    ?, ?,
    ?, ?, ?, ?, ?,
    ?, ?, ?, ?,
    ?, ?, ?, ?, ?
)
"""


def _entry_to_row(
    entry: BookCatalogEntry,
    cache_thread_id: str,
    cache_user_id: str,
    now: str,
) -> tuple:
    return (
        entry.doc_id,
        cache_thread_id,
        cache_user_id,
        entry.scope,
        entry.title or "",
        entry.filename or "",
        entry.source_path or "",
        entry.source_url or "",
        entry.original_url,
        entry.preview or "",
        entry.search_text or "",
        entry.type or "unknown",
        json.dumps(entry.categories or [], ensure_ascii=False),
        json.dumps(entry.eras or [], ensure_ascii=False),
        json.dumps(entry.regions or [], ensure_ascii=False),
        json.dumps(entry.keywords or [], ensure_ascii=False),
        entry.summary or "",
        entry.author or "",
        entry.publisher or "",
        entry.priority,
        entry.folder_path,
        entry.language_hint,
        entry.page_count or 0,
        entry.structured_path,
        now,
    )


def _row_to_entry(row: sqlite3.Row) -> BookCatalogEntry:
    # Deferred import to avoid circular dependency (catalog → book_catalog_index → catalog).
    from src.community.knowledge_base.catalog import BookCatalogEntry  # noqa: PLC0415

    search_text = str(row["search_text"] or "")
    return BookCatalogEntry(
        doc_id=str(row["doc_id"]),
        title=str(row["title"] or ""),
        filename=str(row["filename"] or ""),
        scope=str(row["scope"]),
        source_path=str(row["source_path"] or ""),
        source_url=str(row["source_url"] or ""),
        original_url=row["original_url"],
        preview=str(row["preview"] or ""),
        search_text=search_text,
        search_tokens=tokenize_search_text(search_text),
        type=str(row["type"] or "unknown"),
        categories=json.loads(str(row["categories"] or "[]")),
        eras=json.loads(str(row["eras"] or "[]")),
        regions=json.loads(str(row["regions"] or "[]")),
        keywords=json.loads(str(row["keywords"] or "[]")),
        summary=str(row["summary"] or ""),
        author=str(row["author"] or ""),
        publisher=str(row["publisher"] or ""),
        priority=row["priority"],
        folder_path=row["folder_path"],
        language_hint=row["language_hint"],
        page_count=int(row["page_count"] or 0),
        structured_path=row["structured_path"],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_catalog_from_db(
    thread_id: str | None,
    user_id: str | None,
    mtime_sig: float,
) -> list[BookCatalogEntry] | None:
    """Return cached entries if the DB is valid for this mtime signature, else None.

    Returns entries in scope order: thread → user → global (same as list_book_catalog).
    """
    try:
        conn = _connect()
        try:
            _ensure_schema(conn)
            if not _is_cache_valid(conn, thread_id, user_id, mtime_sig):
                return None
            rows = conn.execute(
                """
                SELECT *
                FROM book_catalog
                WHERE cache_thread_id = ? AND cache_user_id = ?
                ORDER BY
                    CASE scope WHEN 'thread' THEN 0 WHEN 'user' THEN 1 ELSE 2 END
                """,
                (thread_id or "", user_id or ""),
            ).fetchall()
            if not rows:
                return None
            entries = [_row_to_entry(row) for row in rows]
            logger.info(
                "Book catalog loaded from SQLite: thread_id=%s user_id=%s entries=%s",
                thread_id,
                user_id,
                len(entries),
            )
            return entries
        finally:
            conn.close()
    except Exception:
        logger.warning("Failed to load book catalog from SQLite — will rebuild from files", exc_info=True)
        return None


def save_catalog_to_db(
    thread_id: str | None,
    user_id: str | None,
    mtime_sig: float,
    entries: list[BookCatalogEntry],
) -> None:
    """Persist catalog entries to SQLite atomically.

    On failure (e.g. disk full, DB locked) the error is logged and swallowed so
    the caller always gets results — SQLite is a cache, not the source of truth.
    """
    if not entries:
        return
    try:
        tid = thread_id or ""
        uid = user_id or ""
        now = datetime.now(timezone.utc).isoformat()
        rows = [_entry_to_row(entry, tid, uid, now) for entry in entries]

        conn = _connect()
        try:
            _ensure_schema(conn)
            with _WRITE_LOCK:
                with conn:
                    conn.execute(
                        "DELETE FROM book_catalog WHERE cache_thread_id = ? AND cache_user_id = ?",
                        (tid, uid),
                    )
                    conn.executemany(_INSERT_SQL, rows)
                    _write_build_state(conn, thread_id, user_id, mtime_sig, len(entries))
        finally:
            conn.close()

        logger.info(
            "Book catalog saved to SQLite: thread_id=%s user_id=%s entries=%s",
            thread_id,
            user_id,
            len(entries),
        )
    except Exception:
        logger.warning("Failed to save book catalog to SQLite", exc_info=True)


_GLOBAL_CACHE_LOCK = threading.Lock()
_GLOBAL_CACHE = None


def _copy_global_entries(entries):
    # Lists and records belong to the caller; ranking/filtering must not poison
    # a subsequent request or another user's view of the global catalog.
    return [replace(entry, search_tokens=list(entry.search_tokens),
                    categories=list(entry.categories), eras=list(entry.eras),
                    regions=list(entry.regions), keywords=list(entry.keywords))
            for entry in entries]


def clear_global_catalog_cache() -> None:
    """Release the retained read connection (also useful for isolated tests)."""
    global _GLOBAL_CACHE
    with _GLOBAL_CACHE_LOCK:
        if _GLOBAL_CACHE is not None:
            _GLOBAL_CACHE[1].close()
            _GLOBAL_CACHE = None


def load_global_entries_from_db() -> "list[BookCatalogEntry] | None":
    """Load global entries, coalescing cold reads and detecting external commits."""
    global _GLOBAL_CACHE
    with _GLOBAL_CACHE_LOCK:
        try:
            path = _db_path().resolve()
            if not path.exists():
                return None
            stat = path.stat()
            identity = (str(path), stat.st_dev, stat.st_ino)
            if _GLOBAL_CACHE is None or _GLOBAL_CACHE[0] != identity:
                if _GLOBAL_CACHE is not None:
                    _GLOBAL_CACHE[1].close()
                conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                _GLOBAL_CACHE = (identity, conn, None, None)
            identity, conn, cached_version, entries = _GLOBAL_CACHE
            version = conn.execute("PRAGMA data_version").fetchone()[0]
            if entries is not None and version == cached_version:
                return _copy_global_entries(entries)
            # Hold a consistent snapshot while serializing; do not associate a
            # concurrent writer's newer data_version with this older snapshot.
            conn.execute("BEGIN")
            try:
                version = conn.execute("PRAGMA data_version").fetchone()[0]
                rows = conn.execute(
                    "SELECT * FROM book_catalog WHERE scope = 'global' AND cache_thread_id = '' AND cache_user_id = ''"
                ).fetchall()
                entries = [_row_to_entry(row) for row in rows]
            finally:
                conn.rollback()
            after = conn.execute("PRAGMA data_version").fetchone()[0]
            _GLOBAL_CACHE = (identity, conn, version, entries if version == after else None)
            return _copy_global_entries(entries) if entries else None
        except Exception:
            if _GLOBAL_CACHE is not None:
                _GLOBAL_CACHE[1].close()
                _GLOBAL_CACHE = None
            logger.warning("load_global_entries_from_db failed", exc_info=True)
            return None


def bulk_update_catalog_folder(updates: list[tuple[str, "str | None"]]) -> None:
    """Bulk update ``folder_path`` for a list of ``(filename, new_folder)`` pairs.

    Only touches global-scope entries (``cache_thread_id=''``, ``cache_user_id=''``).
    Pass ``None`` as ``new_folder`` to clear the folder assignment.

    On failure the error is logged and swallowed — SQLite is a cache, not the
    source of truth, so callers always get a result even if persistence fails.
    """
    if not updates:
        return
    try:
        conn = _connect()
        try:
            _ensure_schema(conn)
            with _WRITE_LOCK:
                with conn:
                    for filename, folder_path in updates:
                        conn.execute(
                            "UPDATE book_catalog SET folder_path = ? "
                            "WHERE filename = ? AND scope = 'global' "
                            "AND cache_thread_id = '' AND cache_user_id = ''",
                            (folder_path, filename),
                        )
        finally:
            conn.close()
        logger.info("bulk_update_catalog_folder: applied %d folder update(s)", len(updates))
    except Exception:
        logger.warning("bulk_update_catalog_folder failed", exc_info=True)


