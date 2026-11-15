"""Catalog routing uses the shared SQLite cache and keeps dynamic scopes fresh."""

from types import SimpleNamespace

from src.community.knowledge_base import book_catalog_index, catalog


def test_sqlite_catalog_hit_avoids_source_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "get_knowledge_base_config", lambda: SimpleNamespace(docs_path=str(tmp_path)))
    cached = [SimpleNamespace(doc_id="persisted")]
    monkeypatch.setattr(book_catalog_index, "load_global_entries_from_db", lambda: cached)
    monkeypatch.setattr(catalog, "_build_global_entries", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("unexpected scan")))
    assert catalog.list_book_catalog() == cached


def test_empty_sqlite_catalog_falls_back_to_current_files(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "get_knowledge_base_config", lambda: SimpleNamespace(docs_path=str(tmp_path)))
    monkeypatch.setattr(book_catalog_index, "load_global_entries_from_db", lambda: None)
    first = tmp_path / "one.txt"
    first.write_text("First document")
    assert [entry.doc_id for entry in catalog.list_book_catalog()] == ["one.txt"]
    (tmp_path / "two.txt").write_text("Second document")
    assert [entry.doc_id for entry in catalog.list_book_catalog()] == ["one.txt", "two.txt"]


def test_dynamic_user_entries_do_not_leak_into_global_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "get_knowledge_base_config", lambda: SimpleNamespace(docs_path=str(tmp_path)))
    global_entries = [SimpleNamespace(doc_id="global")]
    monkeypatch.setattr(book_catalog_index, "load_global_entries_from_db", lambda: global_entries)
    monkeypatch.setattr(catalog, "get_paths", lambda: SimpleNamespace(user_knowledge_docs_dir=lambda uid: tmp_path))
    monkeypatch.setattr(catalog, "_build_user_entries", lambda uid, *a, **kw: [SimpleNamespace(doc_id=uid)])
    assert [e.doc_id for e in catalog.list_book_catalog(user_id="alice")] == ["alice", "global"]
    assert [e.doc_id for e in catalog.list_book_catalog(user_id="bob")] == ["bob", "global"]
    assert [e.doc_id for e in catalog.list_book_catalog()] == ["global"]
