"""Tests for the SQLite-backed book catalog persistent cache."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


def _make_entry(doc_id: str = "doc_1", scope: str = "global"):
    from src.community.knowledge_base.catalog import BookCatalogEntry

    return BookCatalogEntry(
        doc_id=doc_id,
        title="测试书目",
        filename=f"{doc_id}.txt",
        scope=scope,
        source_path=f"/fake/{doc_id}.txt",
        source_url=f"/api/knowledge/docs/{doc_id}.txt",
        original_url=None,
        preview="前八百字预览",
        search_text="测试书目 财政 历史",
        search_tokens=["测试", "书目", "财政", "历史"],
        type="core",
        categories=["财政史"],
        eras=["清代"],
        regions=["中国"],
        keywords=["税收"],
        summary="关于清代财政的研究",
        author="作者甲",
        publisher="出版社乙",
        priority=1,
        folder_path="财政/清代",
        language_hint="zh",
        page_count=350,
    )


@pytest.fixture()
def db_path(tmp_path: Path):
    """Patch get_paths() so the SQLite DB lands in a temp directory."""
    from unittest.mock import MagicMock

    paths_mock = MagicMock()
    paths_mock.knowledge_search_db_path.return_value = tmp_path / "test_catalog.sqlite3"
    paths_mock.ensure_knowledge_search_dirs.return_value = None

    with patch("src.community.knowledge_base.book_catalog_index.get_paths", return_value=paths_mock):
        yield tmp_path / "test_catalog.sqlite3"


class TestSaveAndLoad:
    def test_round_trip(self, db_path: Path) -> None:
        from src.community.knowledge_base.book_catalog_index import load_catalog_from_db, save_catalog_to_db

        entries = [_make_entry("a"), _make_entry("b", scope="thread")]
        save_catalog_to_db(thread_id="t1", user_id=None, mtime_sig=12345.0, entries=entries)
        loaded = load_catalog_from_db(thread_id="t1", user_id=None, mtime_sig=12345.0)

        assert loaded is not None
        assert len(loaded) == 2
        doc_ids = {e.doc_id for e in loaded}
        assert doc_ids == {"a", "b"}

    def test_metadata_survives_round_trip(self, db_path: Path) -> None:
        from src.community.knowledge_base.book_catalog_index import load_catalog_from_db, save_catalog_to_db

        original = _make_entry("meta_test")
        save_catalog_to_db(thread_id=None, user_id=None, mtime_sig=1.0, entries=[original])
        loaded = load_catalog_from_db(thread_id=None, user_id=None, mtime_sig=1.0)

        assert loaded is not None
        entry = loaded[0]
        assert entry.title == "测试书目"
        assert entry.categories == ["财政史"]
        assert entry.eras == ["清代"]
        assert entry.keywords == ["税收"]
        assert entry.author == "作者甲"
        assert entry.page_count == 350
        assert entry.folder_path == "财政/清代"
        assert entry.language_hint == "zh"
        # search_tokens are recomputed from search_text on load — just verify they're non-empty
        # and consistent with what tokenize_search_text would produce.
        from src.community.knowledge_base.common import tokenize_search_text
        assert entry.search_tokens == tokenize_search_text(entry.search_text)

    def test_miss_when_empty(self, db_path: Path) -> None:
        from src.community.knowledge_base.book_catalog_index import load_catalog_from_db

        result = load_catalog_from_db(thread_id=None, user_id=None, mtime_sig=99.0)
        assert result is None

    def test_miss_when_mtime_differs(self, db_path: Path) -> None:
        from src.community.knowledge_base.book_catalog_index import load_catalog_from_db, save_catalog_to_db

        save_catalog_to_db(thread_id=None, user_id=None, mtime_sig=100.0, entries=[_make_entry()])
        result = load_catalog_from_db(thread_id=None, user_id=None, mtime_sig=999.0)
        assert result is None

    def test_cache_keys_are_independent(self, db_path: Path) -> None:
        """Different (thread_id, user_id) pairs do not interfere."""
        from src.community.knowledge_base.book_catalog_index import load_catalog_from_db, save_catalog_to_db

        entries_a = [_make_entry("for_thread_a")]
        entries_b = [_make_entry("for_thread_b")]
        save_catalog_to_db(thread_id="t_a", user_id=None, mtime_sig=1.0, entries=entries_a)
        save_catalog_to_db(thread_id="t_b", user_id=None, mtime_sig=2.0, entries=entries_b)

        loaded_a = load_catalog_from_db(thread_id="t_a", user_id=None, mtime_sig=1.0)
        loaded_b = load_catalog_from_db(thread_id="t_b", user_id=None, mtime_sig=2.0)

        assert loaded_a is not None and loaded_b is not None
        assert loaded_a[0].doc_id == "for_thread_a"
        assert loaded_b[0].doc_id == "for_thread_b"

    def test_overwrite_on_save(self, db_path: Path) -> None:
        """Saving again with a new mtime replaces old entries."""
        from src.community.knowledge_base.book_catalog_index import load_catalog_from_db, save_catalog_to_db

        save_catalog_to_db(thread_id=None, user_id=None, mtime_sig=1.0, entries=[_make_entry("old")])
        save_catalog_to_db(thread_id=None, user_id=None, mtime_sig=2.0, entries=[_make_entry("new")])

        # Old mtime no longer valid
        old = load_catalog_from_db(thread_id=None, user_id=None, mtime_sig=1.0)
        assert old is None

        # New mtime returns new entry only
        new = load_catalog_from_db(thread_id=None, user_id=None, mtime_sig=2.0)
        assert new is not None
        assert len(new) == 1
        assert new[0].doc_id == "new"

    def test_scope_ordering(self, db_path: Path) -> None:
        """Loaded entries are ordered thread → user → global."""
        from src.community.knowledge_base.book_catalog_index import load_catalog_from_db, save_catalog_to_db

        entries = [
            _make_entry("g", scope="global"),
            _make_entry("u", scope="user"),
            _make_entry("t", scope="thread"),
        ]
        save_catalog_to_db(thread_id="x", user_id="y", mtime_sig=1.0, entries=entries)
        loaded = load_catalog_from_db(thread_id="x", user_id="y", mtime_sig=1.0)

        assert loaded is not None
        scopes = [e.scope for e in loaded]
        assert scopes == ["thread", "user", "global"]


class TestListBookCatalogIntegration:
    def test_sqlite_hit_avoids_file_rebuild(self, tmp_path: Path, db_path: Path, monkeypatch) -> None:
        from types import SimpleNamespace

        from src.community.knowledge_base import catalog
        from src.community.knowledge_base.book_catalog_index import save_catalog_to_db

        save_catalog_to_db(None, None, 0.0, [_make_entry("persisted")])
        monkeypatch.setattr(catalog, "get_knowledge_base_config", lambda: SimpleNamespace(docs_path=str(tmp_path)))
        monkeypatch.setattr(catalog, "_build_global_entries", lambda *a, **kw: pytest.fail("SQLite hit must not scan source files"))
        assert [entry.doc_id for entry in catalog.list_book_catalog()] == ["persisted"]


class TestSharedGlobalCache:
    def test_cached_entries_are_copied_and_scopes_excluded(self, db_path, monkeypatch):
        from src.community.knowledge_base import book_catalog_index as index
        index.clear_global_catalog_cache()
        index.save_catalog_to_db(thread_id=None, user_id=None, mtime_sig=1, entries=[_make_entry('global'), _make_entry('private', 'user')])
        original = index._row_to_entry
        calls = []
        monkeypatch.setattr(index, '_row_to_entry', lambda row: calls.append(row['doc_id']) or original(row))
        first = index.load_global_entries_from_db()
        first[0].title = 'changed'
        first[0].keywords.append('poison')
        first.clear()
        again = index.load_global_entries_from_db()
        assert [e.doc_id for e in again] == ['global']
        assert again[0].title == '测试书目' and 'poison' not in again[0].keywords
        assert calls == ['global']
        index.clear_global_catalog_cache()

    def test_external_wal_commit_and_folder_update_invalidate(self, db_path):
        from src.community.knowledge_base import book_catalog_index as index
        index.clear_global_catalog_cache()
        index.save_catalog_to_db(thread_id=None, user_id=None, mtime_sig=1, entries=[_make_entry('g')])
        assert index.load_global_entries_from_db()[0].title == '测试书目'
        # Keep a WAL writer open: main-file mtime alone cannot detect this commit.
        writer = index._connect()
        try:
            writer.execute("UPDATE book_catalog SET title='updated' WHERE doc_id='g'")
            writer.commit()
            assert index.load_global_entries_from_db()[0].title == 'updated'
            index.bulk_update_catalog_folder([('g.txt', 'new-folder')])
            assert index.load_global_entries_from_db()[0].folder_path == 'new-folder'
        finally:
            writer.close()
            index.clear_global_catalog_cache()

    def test_parallel_cold_loads_are_coalesced(self, db_path, monkeypatch):
        from concurrent.futures import ThreadPoolExecutor

        from src.community.knowledge_base import book_catalog_index as index
        index.clear_global_catalog_cache()
        index.save_catalog_to_db(thread_id=None, user_id=None, mtime_sig=1, entries=[_make_entry('g')])
        original = index._row_to_entry
        calls = []
        monkeypatch.setattr(index, '_row_to_entry', lambda row: calls.append(1) or original(row))
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: index.load_global_entries_from_db(), range(12)))
        assert all(items[0].doc_id == 'g' for items in results)
        assert len(calls) == 1
        index.clear_global_catalog_cache()

    def test_database_replacement_and_path_isolation(self, db_path, tmp_path, monkeypatch):
        from src.community.knowledge_base import book_catalog_index as index
        index.clear_global_catalog_cache()
        index.save_catalog_to_db(thread_id=None, user_id=None, mtime_sig=1, entries=[_make_entry('old')])
        assert index.load_global_entries_from_db()[0].doc_id == 'old'
        other = tmp_path / 'other.sqlite3'
        with monkeypatch.context() as m:
            m.setattr(index, '_db_path', lambda: other)
            index.save_catalog_to_db(thread_id=None, user_id=None, mtime_sig=1, entries=[_make_entry('new')])
            assert index.load_global_entries_from_db()[0].doc_id == 'new'
        index.clear_global_catalog_cache()
        other.replace(db_path)
        assert index.load_global_entries_from_db()[0].doc_id == 'new'
        index.clear_global_catalog_cache()
