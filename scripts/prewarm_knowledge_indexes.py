#!/usr/bin/env python3
"""Pre-warm SQLite indexes after redeployment.

Run this script once after deploying to ensure the book catalog and keyword
FTS index are already populated in SQLite, so the first knowledge_locate call
returns quickly instead of triggering an expensive cold-build.

Usage (from project root):
    cd backend && uv run python ../scripts/prewarm_knowledge_indexes.py

Or with explicit config:
    DEER_FLOW_CONFIG_PATH=/path/to/config.yaml \\
        cd backend && uv run python ../scripts/prewarm_knowledge_indexes.py
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _warmup_book_catalog() -> int:
    """Build global book catalog and persist it synchronously to SQLite."""
    from src.community.knowledge_base.book_catalog_index import save_catalog_to_db
    from src.community.knowledge_base.catalog import list_book_catalog
    from src.community.knowledge_base.common import resolve_project_path
    from src.config.knowledge_base_config import get_knowledge_base_config

    docs_root = resolve_project_path(get_knowledge_base_config().docs_path)

    logger.info("[catalog] Building global book catalog from files...")
    t0 = time.perf_counter()
    # thread_id=None, user_id=None → global scope only.
    # list_book_catalog already writes to SQLite in a daemon background thread;
    # we call save_catalog_to_db synchronously below so the script doesn't exit
    # before the write completes.
    entries = list_book_catalog(
        thread_id=None, user_id=None, include_search_content=True, caller="prewarm"
    )
    elapsed = time.perf_counter() - t0
    logger.info("[catalog] Catalog built: %d entries in %.1fs", len(entries), elapsed)

    # Recompute mtime signature (same logic as catalog.py) so the saved record
    # matches what the runtime will see on next startup.
    total_mtime = 0.0
    try:
        total_mtime += docs_root.stat().st_mtime
    except OSError as exc:
        logger.debug("Cannot stat knowledge directory: %s", exc)

    logger.info("[catalog] Persisting to SQLite (synchronous)...")
    t0 = time.perf_counter()
    save_catalog_to_db(None, None, total_mtime, entries)
    elapsed = time.perf_counter() - t0
    logger.info("[catalog] SQLite write done in %.1fs", elapsed)

    return len(entries)


def _warmup_keyword_fts_index() -> int:
    """Index all global document paragraphs into the SQLite FTS table."""
    from src.community.knowledge_base.common import (
        derive_global_doc_id,
        resolve_project_path,
    )
    from src.community.knowledge_base.keyword_search_index import (
        ensure_documents_indexed,
        resolve_documents_for_doc_ids,
    )
    from src.config.knowledge_base_config import get_knowledge_base_config

    docs_root = resolve_project_path(get_knowledge_base_config().docs_path)
    ingestion_dir = docs_root / ".ingestion"
    if not ingestion_dir.exists():
        logger.warning(
            "[fts] Ingestion dir not found: %s — skipping FTS warmup", ingestion_dir
        )
        return 0

    logger.info("[fts] Scanning ingestion records in %s...", ingestion_dir)
    doc_ids: list[str] = []
    for record_path in sorted(ingestion_dir.glob("*.json")):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.debug("[fts] Skipping unreadable record: %s", record_path.name)
            continue
        if record.get("schema_version") == 1:
            continue
        source_filename = str(record.get("source_filename") or "")
        if not source_filename or not record.get("indexable"):
            continue
        doc_ids.append(derive_global_doc_id(docs_root, docs_root / source_filename))

    if not doc_ids:
        logger.info("[fts] No indexable global documents found.")
        return 0

    logger.info(
        "[fts] Found %d indexable documents, resolving structured paths...",
        len(doc_ids),
    )
    documents = resolve_documents_for_doc_ids(
        thread_id=None, user_id=None, doc_ids=doc_ids
    )
    logger.info(
        "[fts] Resolved %d documents. Building FTS index (this may take a while)...",
        len(documents),
    )

    t0 = time.perf_counter()
    ensure_documents_indexed(documents)
    elapsed = time.perf_counter() - t0
    logger.info(
        "[fts] FTS index built for %d documents in %.1fs", len(documents), elapsed
    )

    return len(documents)


def main() -> int:
    from src.config.app_config import get_app_config

    get_app_config()  # Load config.yaml before using any src modules.

    logger.info("=== Pre-warming SQLite knowledge indexes ===")
    overall_t0 = time.perf_counter()

    catalog_count = _warmup_book_catalog()
    fts_count = _warmup_keyword_fts_index()

    total_elapsed = time.perf_counter() - overall_t0
    logger.info(
        "=== Done in %.1fs — catalog: %d entries, fts: %d documents indexed ===",
        total_elapsed,
        catalog_count,
        fts_count,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
