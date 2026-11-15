import importlib.util
from pathlib import Path
from types import SimpleNamespace

_KNOWLEDGE_ROUTER_SPEC = importlib.util.spec_from_file_location(
    "test_knowledge_router_module",
    Path(__file__).parent.parent / "src/gateway/routers/knowledge.py",
)
knowledge_router = importlib.util.module_from_spec(_KNOWLEDGE_ROUTER_SPEC)
assert _KNOWLEDGE_ROUTER_SPEC and _KNOWLEDGE_ROUTER_SPEC.loader
_KNOWLEDGE_ROUTER_SPEC.loader.exec_module(knowledge_router)


def test_retry_global_knowledge_file_requeues_document_for_ocr(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "indexed.pdf"
    source_path.write_text("pdf", encoding="utf-8")
    records = {
        "indexed.pdf": {
            "source_filename": "indexed.pdf",
            "indexable": True,
            "parse_status": "indexed",
            "index_target_path": "/tmp/indexed.structured.json",
            "error": None,
        },
    }
    enqueued: list[str] = []

    monkeypatch.setattr(
        knowledge_router,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(enabled=True),
    )
    monkeypatch.setattr(
        knowledge_router,
        "_find_global_record",
        lambda filename: dict(records[filename]) if filename in records else None,
    )
    monkeypatch.setattr(knowledge_router, "get_global_docs_dir", lambda: tmp_path)
    monkeypatch.setattr(
        knowledge_router,
        "_save_global_record",
        lambda filename, record: records.__setitem__(filename, dict(record)),
    )
    monkeypatch.setattr(knowledge_router, "_ensure_global_queue_workers_started", lambda: None)
    monkeypatch.setattr(knowledge_router, "_submit_global_ocr", enqueued.append)

    import asyncio

    result = asyncio.run(_call_retry_global_knowledge_file("indexed.pdf"))

    assert result["success"] is True
    assert "重新加入解析队列" in result["message"]
    assert records["indexed.pdf"]["parse_status"] == "queued_ocr"
    assert enqueued == ["indexed.pdf"]


async def _call_retry_global_knowledge_file(filename: str):
    return await knowledge_router.retry_global_knowledge_file(filename)


async def _call_reparse_global_knowledge_file(filename: str):
    return await knowledge_router.reparse_global_knowledge_file(filename)


def test_reparse_global_knowledge_file_requeues_indexed_document_for_ocr(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "indexed.pdf"
    source_path.write_text("pdf", encoding="utf-8")
    records = {
        "indexed.pdf": {
            "source_filename": "indexed.pdf",
            "indexable": True,
            "parse_status": "indexed",
            "index_target_path": "/tmp/indexed.structured.json",
            "error": "old error",
        },
    }
    enqueued: list[str] = []

    monkeypatch.setattr(
        knowledge_router,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(enabled=True),
    )
    monkeypatch.setattr(
        knowledge_router,
        "_find_global_record",
        lambda filename: dict(records[filename]) if filename in records else None,
    )
    monkeypatch.setattr(knowledge_router, "get_global_docs_dir", lambda: tmp_path)
    monkeypatch.setattr(
        knowledge_router,
        "_save_global_record",
        lambda filename, record: records.__setitem__(filename, dict(record)),
    )
    monkeypatch.setattr(knowledge_router, "_ensure_global_queue_workers_started", lambda: None)
    monkeypatch.setattr(knowledge_router, "_submit_global_ocr", enqueued.append)

    import asyncio

    result = asyncio.run(_call_reparse_global_knowledge_file("indexed.pdf"))

    assert result["success"] is True
    assert "重新加入解析队列" in result["message"]
    assert records["indexed.pdf"]["parse_status"] == "queued_ocr"
    assert records["indexed.pdf"]["error"] is None
    assert enqueued == ["indexed.pdf"]


def test_update_global_knowledge_metadata_updates_hints(monkeypatch) -> None:
    record = {
        "source_filename": "demo.pdf",
        "display_title": "演示文档",
        "hints": {
            "language_hint": "unknown",
            "layout_hint": "horizontal",
            "document_type_hint": "book",
        },
    }
    saved_records: list[dict] = []

    monkeypatch.setattr(
        knowledge_router,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(
            enabled=True,
            docs_path="knowledge/docs",
            book_metadata=SimpleNamespace(model_name="demo-model", front_page_limit=10, max_excerpt_chars=1200),
        ),
    )
    monkeypatch.setattr(
        knowledge_router,
        "_load_structured_payload_for_metadata",
        lambda filename: (
            {"pages": [{"paragraphs": []}]},
            record,
            Path("/tmp"),
        ),
    )
    monkeypatch.setattr(knowledge_router, "load_book_metadata_for_source", lambda docs_dir, filename: None)
    monkeypatch.setattr(
        knowledge_router,
        "build_book_metadata_prompt_input",
        lambda *args, **kwargs: {"title": "demo"},
    )
    monkeypatch.setattr(
        knowledge_router,
        "build_book_metadata_record",
        lambda **kwargs: SimpleNamespace(suggestion=None, prompt_input=kwargs.get("prompt_input"), model_name=kwargs.get("model_name")),
    )
    monkeypatch.setattr(knowledge_router, "save_book_metadata", lambda docs_dir, filename, book_metadata_record: None)
    monkeypatch.setattr(
        knowledge_router,
        "_save_global_record",
        lambda filename, payload: saved_records.append(dict(payload)),
    )
    monkeypatch.setattr(
        knowledge_router,
        "_load_global_book_metadata",
        lambda filename: {
            "type": None,
            "categories": [],
            "eras": [],
            "regions": [],
            "keywords": [],
            "summary": None,
            "tags": [],
            "language_hint": "zh-Hant",
            "layout_hint": "vertical",
            "document_type_hint": "ancient_book",
        },
    )

    import asyncio

    result = asyncio.run(
        knowledge_router.update_global_knowledge_metadata(
            "demo.pdf",
            knowledge_router.KnowledgeMetadataUpdateRequest(
                layout_hint="vertical",
                language_hint="zh-Hant",
                document_type_hint="ancient_book",
            ),
        )
    )

    assert result["metadata"]["layout_hint"] == "vertical"
    assert saved_records[-1]["hints"]["layout_hint"] == "vertical"
    assert saved_records[-1]["hints"]["language_hint"] == "zh-Hant"
    assert saved_records[-1]["hints"]["document_type_hint"] == "ancient_book"


def test_load_global_book_metadata_uses_explicit_folder(monkeypatch, tmp_path) -> None:
    suggestion = SimpleNamespace(
        type=knowledge_router.MetadataField(value="core", confidence=0.9, evidence="demo"),
        folder=knowledge_router.MetadataField(value="财政史/清代", confidence=0.8, evidence="demo"),
        categories=[knowledge_router.MetadataField(value="财政史", confidence=0.9, evidence="demo")],
        eras=[],
        regions=[],
        keywords=[],
        summary=None,
        author=None,
        publisher=None,
    )
    record = SimpleNamespace(suggestion=suggestion)

    monkeypatch.setattr(knowledge_router, "get_global_docs_dir", lambda: tmp_path)
    monkeypatch.setattr(knowledge_router, "load_book_metadata_for_source", lambda docs_dir, filename: record)
    monkeypatch.setattr(knowledge_router, "_find_global_record", lambda filename: {"hints": {}})

    result = knowledge_router._load_global_book_metadata("demo.pdf")

    assert result["folder"] == "财政史/清代"


def test_load_global_book_metadata_falls_back_to_first_tag_for_legacy_records(monkeypatch, tmp_path) -> None:
    suggestion = SimpleNamespace(
        type=None,
        folder=None,
        categories=[knowledge_router.MetadataField(value="制度史", confidence=0.9, evidence="demo")],
        eras=[knowledge_router.MetadataField(value="明清", confidence=0.8, evidence="demo")],
        regions=[],
        keywords=[],
        summary=None,
        author=None,
        publisher=None,
    )
    record = SimpleNamespace(suggestion=suggestion)

    monkeypatch.setattr(knowledge_router, "get_global_docs_dir", lambda: tmp_path)
    monkeypatch.setattr(knowledge_router, "load_book_metadata_for_source", lambda docs_dir, filename: record)
    monkeypatch.setattr(knowledge_router, "_find_global_record", lambda filename: {"hints": {}})

    result = knowledge_router._load_global_book_metadata("legacy.pdf")

    assert result["tags"] == ["制度史", "明清"]
    assert result["folder"] == "制度史"


def test_list_debug_search_books_returns_catalog_entries_with_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        knowledge_router,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(enabled=True),
    )
    monkeypatch.setattr(
        knowledge_router,
        "_list_global_knowledge_files_all",
        lambda: {
            "files": [
                {
                    "doc_id": "doc-1",
                    "parse_status": "indexed",
                    "indexable": True,
                    "modified": 123.0,
                }
            ]
        },
    )
    monkeypatch.setattr(
        knowledge_router,
        "list_book_catalog",
        lambda include_search_content=False, caller=None: [
            SimpleNamespace(
                doc_id="doc-1",
                title="中國財政通史 第8卷（上）",
                filename="中國財政通史 第8卷（上）.pdf",
                scope="global",
                folder_path="财政史/民国",
                summary="测试摘要",
                language_hint="zh-Hant",
            )
        ],
    )

    result = knowledge_router.list_debug_search_books()

    assert result.count == 1
    assert result.books[0].doc_id == "doc-1"
    assert result.books[0].language_hint == "zh-Hant"
    assert result.books[0].parse_status == "indexed"
    assert result.books[0].indexable is True


def test_debug_qdrant_search_returns_vector_results(monkeypatch) -> None:
    monkeypatch.setattr(
        knowledge_router,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(enabled=True),
    )

    class _DummyRetriever:
        def search_qdrant(self, query, *, doc_ids=None, top_k=None):
            assert query == "张之洞 洋务 实业"
            assert doc_ids == ["doc-1"]
            assert top_k == 5
            return [
                {
                    "content": "这是一段足够长的向量检索命中正文。",
                    "score": 0.87,
                    "filename": "book.pdf",
                    "source": "/api/knowledge/docs/book.pdf",
                    "metadata": {
                        "title": "测试书目",
                        "doc_id": "doc-1",
                        "scope": "global",
                        "page_no": 12,
                        "pdf_page_no": 12,
                        "paragraph_no": 3,
                        "source_kind": "global_document",
                    },
                }
            ]

    monkeypatch.setattr(knowledge_router, "get_retriever", lambda: _DummyRetriever())
    monkeypatch.setattr(
        knowledge_router,
        "resolve_result_citation_context",
        lambda result, thread_id=None, user_id=None: {
            "source_url": "/api/knowledge/docs/book.pdf?page_no=12",
            "original_url": None,
        },
    )

    result = knowledge_router.debug_qdrant_search(
        knowledge_router.KnowledgeDebugSearchRequest(
            query="张之洞 洋务 实业",
            doc_ids=["doc-1"],
            top_k=5,
        )
    )

    assert result.query == "张之洞 洋务 实业"
    assert result.results[0].doc_id == "doc-1"
    assert result.results[0].title == "测试书目"
    assert result.results[0].page_no == 12


def test_debug_knowledge_search_tool_returns_rendered_output(monkeypatch) -> None:
    monkeypatch.setattr(
        knowledge_router,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(enabled=True),
    )
    monkeypatch.setattr(
        knowledge_router,
        "knowledge_search_tool",
        SimpleNamespace(func=lambda runtime, query, doc_ids=None: f"## 检索结果\n\nquery={query}\ndoc_ids={doc_ids}"),
    )

    result = knowledge_router.debug_knowledge_search_tool(
        knowledge_router.KnowledgeDebugSearchRequest(
            query="張之洞 生平 官職",
            doc_ids=["doc-1", "doc-2"],
            top_k=8,
        )
    )

    assert "## 检索结果" in result.output
    assert "張之洞 生平 官職" in result.output
    assert "doc-1" in result.output


def test_submit_global_ocr_runs_inflight_jobs_concurrently(monkeypatch) -> None:
    """Concurrent submissions should all execute (no single-worker serialization)."""

    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    # Reset module state so the test does not depend on whatever previous tests
    # might have initialised on the executor singleton.
    monkeypatch.setattr(knowledge_router, "_global_ocr_executor", None)
    monkeypatch.setattr(knowledge_router, "_global_inflight_ocr", set())

    executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="test-ocr")
    monkeypatch.setattr(
        knowledge_router,
        "_ensure_global_queue_workers_started",
        lambda: setattr(knowledge_router, "_global_ocr_executor", executor),
    )

    started = threading.Event()
    release = threading.Event()
    processed: list[str] = []
    processed_lock = threading.Lock()

    def fake_process(filename: str) -> None:
        with processed_lock:
            processed.append(filename)
        if filename == "slow.pdf":
            started.set()
            assert release.wait(timeout=2), "fast job did not unblock the slow one in time"

    monkeypatch.setattr(knowledge_router, "_process_single_global_ocr", fake_process)

    try:
        knowledge_router._submit_global_ocr("slow.pdf")
        assert started.wait(timeout=2), "slow job never started"

        # While slow.pdf is still mid-flight, a second submission must not be
        # blocked behind it — it should run on another executor thread.
        knowledge_router._submit_global_ocr("fast.pdf")

        # Give the executor a moment to schedule the fast job.
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with processed_lock:
                if "fast.pdf" in processed:
                    break
            time.sleep(0.01)

        with processed_lock:
            assert "fast.pdf" in processed, "fast job did not run while slow job was inflight"
        release.set()
    finally:
        release.set()
        executor.shutdown(wait=True)


def test_submit_global_ocr_is_idempotent_for_inflight_filename(monkeypatch) -> None:
    """A duplicate submission for an already-inflight filename should be ignored."""

    monkeypatch.setattr(knowledge_router, "_global_inflight_ocr", set())
    monkeypatch.setattr(knowledge_router, "_ensure_global_queue_workers_started", lambda: None)

    submitted: list[str] = []

    class _RecordingExecutor:
        def submit(self, _fn, *args, **kwargs):  # noqa: ANN001 - test stub
            submitted.append(args[0])

    monkeypatch.setattr(knowledge_router, "_global_ocr_executor", _RecordingExecutor())

    knowledge_router._submit_global_ocr("dup.pdf")
    knowledge_router._submit_global_ocr("dup.pdf")
    knowledge_router._submit_global_ocr("other.pdf")

    assert submitted == ["dup.pdf", "other.pdf"]


def test_recover_pending_global_jobs_resubmits_parsing_and_failed(monkeypatch) -> None:
    """Restart recovery picks up everything left mid-flight, including parsing/failed."""

    records: dict[str, dict] = {
        "queued.pdf":        {"source_filename": "queued.pdf",        "indexable": True, "parse_status": "queued_ocr"},
        "pending.pdf":       {"source_filename": "pending.pdf",       "indexable": True, "parse_status": "pending_parse"},
        "crashed.pdf":       {"source_filename": "crashed.pdf",       "indexable": True, "parse_status": "parsing"},
        "failed_once.pdf":   {"source_filename": "failed_once.pdf",   "indexable": True, "parse_status": "failed", "retry_count": 1, "error": "boom"},
        "failed_capped.pdf": {"source_filename": "failed_capped.pdf", "indexable": True, "parse_status": "failed", "retry_count": 3},
        "done.pdf":          {"source_filename": "done.pdf",          "indexable": True, "parse_status": "parsed"},
        "untracked.pdf":     {"source_filename": "untracked.pdf",     "indexable": False, "parse_status": "uploaded"},
    }
    submitted: list[str] = []

    monkeypatch.setattr(knowledge_router, "_list_global_records", lambda: [dict(r) for r in records.values()])
    monkeypatch.setattr(
        knowledge_router,
        "_save_global_record",
        lambda filename, record: records.__setitem__(filename, dict(record)),
    )
    monkeypatch.setattr(knowledge_router, "_submit_global_ocr", submitted.append)

    knowledge_router._recover_pending_global_jobs()

    # Files that should be resubmitted.
    assert sorted(submitted) == ["crashed.pdf", "failed_once.pdf", "pending.pdf", "queued.pdf"]
    # Status normalisation: parsing/failed records must not still claim
    # "parsing" / "failed" — otherwise the UI lies about what is happening.
    assert records["crashed.pdf"]["parse_status"] == "queued_ocr"
    assert records["crashed.pdf"]["error"] is None
    assert records["failed_once.pdf"]["parse_status"] == "queued_ocr"
    assert records["failed_once.pdf"]["error"] is None
    # Failed-with-retries kept its retry_count — only manual user retry resets it.
    assert records["failed_once.pdf"]["retry_count"] == 1
    # The capped-out record is left untouched (still "failed", still retry_count=3).
    assert records["failed_capped.pdf"]["parse_status"] == "failed"
    assert records["failed_capped.pdf"]["retry_count"] == 3
    # Already-parsed / non-indexable files are untouched.
    assert records["done.pdf"]["parse_status"] == "parsed"
    assert records["untracked.pdf"]["parse_status"] == "uploaded"


def test_mark_global_record_failed_increments_retry_count() -> None:
    record = {"source_filename": "a.pdf", "parse_status": "parsing", "retry_count": 0}

    updated = knowledge_router._mark_global_record_failed(record, "ocr exploded")

    assert updated["parse_status"] == "failed"
    assert updated["retry_count"] == 1
    assert updated["error"] == "ocr exploded"

    # Second failure bumps it again.
    updated = knowledge_router._mark_global_record_failed(updated, "ocr exploded again")
    assert updated["retry_count"] == 2


def test_manual_retry_resets_failed_record_retry_count(monkeypatch, tmp_path) -> None:
    """A user clicking Retry signals 'try this fresh' — counter must reset."""

    import asyncio

    source_path = tmp_path / "bad.pdf"
    source_path.write_text("pdf", encoding="utf-8")
    records = {
        "bad.pdf": {
            "source_filename": "bad.pdf",
            "indexable": True,
            "parse_status": "failed",
            "retry_count": 3,
            "error": "auto-recovery gave up",
        }
    }
    submitted: list[str] = []

    monkeypatch.setattr(knowledge_router, "get_knowledge_base_config", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(
        knowledge_router,
        "_find_global_record",
        lambda filename: dict(records[filename]) if filename in records else None,
    )
    monkeypatch.setattr(knowledge_router, "get_global_docs_dir", lambda: tmp_path)
    monkeypatch.setattr(
        knowledge_router,
        "_save_global_record",
        lambda filename, record: records.__setitem__(filename, dict(record)),
    )
    monkeypatch.setattr(knowledge_router, "_ensure_global_queue_workers_started", lambda: None)
    monkeypatch.setattr(knowledge_router, "_submit_global_ocr", submitted.append)

    result = asyncio.run(_call_retry_global_knowledge_file("bad.pdf"))

    assert result["success"] is True
    assert records["bad.pdf"]["parse_status"] == "queued_ocr"
    assert records["bad.pdf"]["retry_count"] == 0
    assert records["bad.pdf"]["error"] is None
    assert submitted == ["bad.pdf"]


def test_bootstrap_global_ocr_recovery_no_ops_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(knowledge_router, "get_knowledge_base_config", lambda: SimpleNamespace(enabled=False))
    called: list[str] = []
    monkeypatch.setattr(
        knowledge_router,
        "_ensure_global_queue_workers_started",
        lambda: called.append("started"),
    )

    knowledge_router.bootstrap_global_ocr_recovery()

    assert called == []


def test_bootstrap_global_ocr_recovery_starts_workers_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(knowledge_router, "get_knowledge_base_config", lambda: SimpleNamespace(enabled=True))
    called: list[str] = []
    monkeypatch.setattr(
        knowledge_router,
        "_ensure_global_queue_workers_started",
        lambda: called.append("started"),
    )

    knowledge_router.bootstrap_global_ocr_recovery()

    assert called == ["started"]
