"""Tests for list_book_catalog() process-level caching."""
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_fake_entries(n: int = 3):
    """Return a list of simple mock BookCatalogEntry objects."""
    from src.community.knowledge_base.catalog import BookCatalogEntry

    return [
        BookCatalogEntry(
            doc_id=f"doc_{i}",
            title=f"Book {i}",
            filename=f"book_{i}.json",
            scope="global",
            source_path=f"/fake/book_{i}.json",
            source_url=f"http://example.com/book_{i}",
            original_url=None,
            preview="",
            search_text="",
            search_tokens=[],
        )
        for i in range(n)
    ]


def test_catalog_cache_hit_on_second_call(tmp_path: Path) -> None:
    """Second call with identical args should return cached result without rebuilding."""
    import src.community.knowledge_base.catalog as catalog_mod

    # Clear module-level cache before test
    with catalog_mod._catalog_cache_lock:
        catalog_mod._catalog_cache.clear()

    fake_entries = _make_fake_entries(3)
    build_call_count = {"n": 0}

    def fake_build_global(*args, **kwargs):
        build_call_count["n"] += 1
        return fake_entries[:]

    with (
        patch.object(catalog_mod, "_build_global_entries", side_effect=fake_build_global),
        patch.object(catalog_mod, "_load_book_metadata_index", return_value={}),
        patch.object(catalog_mod, "get_knowledge_base_config", return_value=MagicMock(docs_path=str(tmp_path))),
        patch.object(catalog_mod, "resolve_project_path", return_value=tmp_path),
        patch.object(catalog_mod, "get_paths", return_value=MagicMock()),
    ):
        result1 = catalog_mod.list_book_catalog(thread_id=None, user_id=None)
        result2 = catalog_mod.list_book_catalog(thread_id=None, user_id=None)

    # Only one build should have happened; second call served from cache
    assert build_call_count["n"] == 1
    assert len(result1) == len(result2) == 3


def test_catalog_cache_invalidated_by_mtime_change(tmp_path: Path) -> None:
    """Cache is bypassed when _catalog_mtime_signature returns a different value."""
    import src.community.knowledge_base.catalog as catalog_mod

    with catalog_mod._catalog_cache_lock:
        catalog_mod._catalog_cache.clear()

    call_count = {"n": 0}

    def fake_build_global(*args, **kwargs):
        call_count["n"] += 1
        return _make_fake_entries(1)

    # Sequence: store(1000) → get-check(2000) → store(2000)
    # _store_catalog_cache is called once per build; _get_cached_catalog checks once per cached call.
    mtime_values = iter([1000.0, 2000.0, 2000.0])

    def fake_mtime_sig(*args, **kwargs):
        return next(mtime_values, 2000.0)

    with (
        patch.object(catalog_mod, "_build_global_entries", side_effect=fake_build_global),
        patch.object(catalog_mod, "_load_book_metadata_index", return_value={}),
        patch.object(catalog_mod, "get_knowledge_base_config", return_value=MagicMock(docs_path=str(tmp_path))),
        patch.object(catalog_mod, "resolve_project_path", return_value=tmp_path),
        patch.object(catalog_mod, "get_paths", return_value=MagicMock()),
        patch.object(catalog_mod, "_catalog_mtime_signature", side_effect=fake_mtime_sig),
    ):
        catalog_mod.list_book_catalog()
        catalog_mod.list_book_catalog()

    # Mtime changed between calls → cache miss → two builds
    assert call_count["n"] == 2


def test_catalog_cache_thread_safety(tmp_path: Path) -> None:
    """Multiple threads calling simultaneously must not corrupt the cache.

    Patches are applied ONCE before threads start and restored ONCE after
    they all finish — using ``patch.object`` inside individual threads is not
    thread-safe and causes unpredictable restoration ordering.
    """
    import src.community.knowledge_base.catalog as catalog_mod

    with catalog_mod._catalog_cache_lock:
        catalog_mod._catalog_cache.clear()

    def fake_build_global(*args, **kwargs):
        time.sleep(0.01)  # simulate a tiny bit of I/O
        return _make_fake_entries(2)

    results: list = []
    errors: list = []

    def worker():
        try:
            results.append(catalog_mod.list_book_catalog())
        except Exception as exc:
            errors.append(exc)

    # Apply all patches once, outside threads, to avoid concurrent setattr races
    with (
        patch.object(catalog_mod, "_build_global_entries", side_effect=fake_build_global),
        patch.object(catalog_mod, "_load_book_metadata_index", return_value={}),
        patch.object(catalog_mod, "get_knowledge_base_config", return_value=MagicMock(docs_path=str(tmp_path))),
        patch.object(catalog_mod, "resolve_project_path", return_value=tmp_path),
        patch.object(catalog_mod, "get_paths", return_value=MagicMock()),
    ):
        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert not errors, f"Thread errors: {errors}"
    assert all(len(r) == 2 for r in results)
