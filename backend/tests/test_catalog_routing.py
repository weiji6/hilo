import sys
from types import ModuleType, SimpleNamespace

import src.community.knowledge_base.catalog as catalog_module
import src.community.knowledge_base.tools as tools_module
from src.community.knowledge_base.book_metadata import build_book_metadata_record, save_book_metadata
from src.community.knowledge_base.catalog import BookCatalogEntry, list_book_catalog, search_book_catalog


def _write_metadata_sidecar(docs_root, records) -> None:
    sidecar = docs_root / ".book_metadata.jsonl"
    sidecar.write_text(
        "\n".join(records) + "\n",
        encoding="utf-8",
    )


def test_search_book_catalog_uses_layered_metadata_for_specific_query(tmp_path, monkeypatch) -> None:
    docs_root = tmp_path / "knowledge" / "docs"
    docs_root.mkdir(parents=True)
    (docs_root / "general_history.md").write_text("# 总论\n中国历史概述", encoding="utf-8")
    (docs_root / "finance_history.md").write_text("# 财政史\n财政制度演变", encoding="utf-8")
    _write_metadata_sidecar(
        docs_root,
        [
            '{"source_filename":"general_history.md","type":"core","categories":["通史"],"eras":["先秦-民国"],"summary":"中国历史通论"}',
            '{"source_filename":"finance_history.md","type":"specialized","categories":["财政史","税制"],"eras":["明清"],"summary":"财政制度演变"}',
        ],
    )

    monkeypatch.setattr(
        catalog_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(docs_path=str(docs_root)),
    )

    results = search_book_catalog("财政制度演变", top_k=2)

    assert [item.title for item in results][0] == "finance_history"
    assert results[0].type == "specialized"
    assert results[0].score is not None
    assert "财政史" in results[0].categories


def test_search_book_catalog_uses_layered_metadata_for_broad_query(tmp_path, monkeypatch) -> None:
    docs_root = tmp_path / "knowledge" / "docs"
    docs_root.mkdir(parents=True)
    (docs_root / "general_history.md").write_text("# 总论\n中国历史概述", encoding="utf-8")
    (docs_root / "finance_history.md").write_text("# 财政史\n财政制度演变", encoding="utf-8")
    _write_metadata_sidecar(
        docs_root,
        [
            '{"source_filename":"general_history.md","type":"core","categories":["通史"],"eras":["先秦-民国"],"summary":"中国历史通论"}',
            '{"source_filename":"finance_history.md","type":"specialized","categories":["财政史","税制"],"eras":["明清"],"summary":"财政制度演变"}',
        ],
    )

    monkeypatch.setattr(
        catalog_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(docs_path=str(docs_root)),
    )

    results = search_book_catalog("中国历史通史概述", top_k=2)

    assert [item.title for item in results][0] == "general_history"
    assert results[0].type == "core"
    assert results[0].score is not None


def test_search_book_catalog_reads_generated_sidecar_metadata(tmp_path, monkeypatch) -> None:
    docs_root = tmp_path / "knowledge" / "docs"
    docs_root.mkdir(parents=True)
    (docs_root / "finance_history.md").write_text("# 财政史\n财政制度演变", encoding="utf-8")
    record = build_book_metadata_record(
        source_filename="finance_history.md",
        source_title="finance_history",
        page_count=12,
        prompt_input={
            "source_filename": "finance_history.md",
            "title": "finance_history",
            "page_count": 12,
            "selected_pages": [],
            "selection_notes": [],
        },
        suggestion={
            "title": "finance_history",
            "type": {"value": "specialized", "confidence": 0.92, "evidence": "目录"},
            "categories": [{"value": "财政史", "confidence": 0.9, "evidence": "标题"}],
            "summary": {"value": "财政制度演变专题。", "confidence": 0.8, "evidence": "样本"},
        },
    )
    save_book_metadata(docs_root, "finance_history.md", record)

    monkeypatch.setattr(
        catalog_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(docs_path=str(docs_root)),
    )

    results = search_book_catalog("财政制度演变", top_k=1)

    assert results[0].type == "specialized"
    assert "财政史" in results[0].categories
    assert results[0].metadata_source is not None


def test_search_book_catalog_can_route_by_folder_path(tmp_path, monkeypatch) -> None:
    docs_root = tmp_path / "knowledge" / "docs"
    docs_root.mkdir(parents=True)
    (docs_root / "late_qing_finance.md").write_text("# 晚清财政\n厘金与关税", encoding="utf-8")
    record = build_book_metadata_record(
        source_filename="late_qing_finance.md",
        source_title="late_qing_finance",
        page_count=12,
        prompt_input={
            "source_filename": "late_qing_finance.md",
            "title": "late_qing_finance",
            "page_count": 12,
            "selected_pages": [],
            "selection_notes": [],
        },
        suggestion={
            "title": "晚清财政史料",
            "type": {"value": "specialized", "confidence": 0.92, "evidence": "目录"},
            "folder": {"value": "财政史/清代/晚清", "confidence": 0.91, "evidence": "目录"},
            "summary": {"value": "晚清厘金与关税专题。", "confidence": 0.8, "evidence": "样本"},
        },
    )
    save_book_metadata(docs_root, "late_qing_finance.md", record)

    monkeypatch.setattr(
        catalog_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(docs_path=str(docs_root)),
    )

    results = search_book_catalog("晚清 财政史 清代", top_k=1)

    assert results[0].folder_path == "财政史/清代/晚清"
    assert results[0].filename == "late_qing_finance.md"
    assert results[0].type == "specialized"


def test_search_book_catalog_folder_paths_hard_filter(tmp_path, monkeypatch) -> None:
    docs_root = tmp_path / "knowledge" / "docs"
    docs_root.mkdir(parents=True)
    (docs_root / "qing_finance.md").write_text("# 清代财政\n", encoding="utf-8")
    (docs_root / "song_finance.md").write_text("# 宋代财政\n", encoding="utf-8")
    save_book_metadata(
        docs_root,
        "qing_finance.md",
        build_book_metadata_record(
            source_filename="qing_finance.md",
            source_title="qing_finance",
            page_count=10,
            prompt_input={
                "source_filename": "qing_finance.md",
                "title": "qing_finance",
                "page_count": 10,
                "selected_pages": [],
                "selection_notes": [],
            },
            suggestion={
                "folder": {"value": "财政史/清代", "confidence": 0.9, "evidence": "目录"},
                "type": {"value": "specialized", "confidence": 0.9, "evidence": "目录"},
            },
        ),
    )
    save_book_metadata(
        docs_root,
        "song_finance.md",
        build_book_metadata_record(
            source_filename="song_finance.md",
            source_title="song_finance",
            page_count=10,
            prompt_input={
                "source_filename": "song_finance.md",
                "title": "song_finance",
                "page_count": 10,
                "selected_pages": [],
                "selection_notes": [],
            },
            suggestion={
                "folder": {"value": "财政史/宋代", "confidence": 0.9, "evidence": "目录"},
                "type": {"value": "specialized", "confidence": 0.9, "evidence": "目录"},
            },
        ),
    )

    monkeypatch.setattr(
        catalog_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(docs_path=str(docs_root)),
    )

    results = search_book_catalog(
        "财政史",
        top_k=5,
        folder_paths=["财政史/清代"],
    )

    assert [item.filename for item in results] == ["qing_finance.md"]


def test_filter_book_catalog_entries_matches_uncategorized_entries() -> None:
    entries = [
        BookCatalogEntry(
            doc_id="uncategorized-doc",
            title="人物档案：刘恺卿",
            filename="人物档案：刘恺卿 (1905–1952).pdf",
            scope="global",
            source_path="/tmp/liu.pdf",
            source_url="/api/knowledge/docs/liu.pdf",
            original_url=None,
            preview="",
            search_text="人物档案 刘恺卿",
            search_tokens=["人物档案", "刘恺卿"],
            type="unknown",
            folder_path=None,
        )
    ]

    filtered = catalog_module.filter_book_catalog_entries(
        entries,
        folder_paths=["未分类"],
    )

    assert [entry.doc_id for entry in filtered] == ["uncategorized-doc"]


def test_book_search_tool_accepts_uncategorized_folder(monkeypatch) -> None:
    entry = BookCatalogEntry(
        doc_id="uncategorized-doc",
        title="人物档案：刘恺卿",
        filename="人物档案：刘恺卿 (1905–1952).pdf",
        scope="global",
        source_path="/tmp/liu.pdf",
        source_url="/api/knowledge/docs/liu.pdf",
        original_url=None,
        preview="",
        search_text="人物档案 刘恺卿",
        search_tokens=["人物档案", "刘恺卿"],
        type="unknown",
        folder_path=None,
        score=0.91,
    )
    monkeypatch.setattr(
        tools_module,
        "list_book_catalog",
        lambda thread_id=None, user_id=None: [entry],
    )
    monkeypatch.setattr(
        tools_module,
        "search_book_catalog",
        lambda *args, **kwargs: [entry],
    )

    output = tools_module.book_search_tool.func(
        SimpleNamespace(context={}),
        "刘恺卿是谁",
        knowledge_folders=["未归档"],
    )

    assert "Error:" not in output
    assert "doc_id=uncategorized-doc" in output
    assert 'next: knowledge_locate(doc_id="uncategorized-doc")' in output


def test_search_book_catalog_broad_query_keeps_core_and_specialized_books(tmp_path, monkeypatch) -> None:
    docs_root = tmp_path / "knowledge" / "docs"
    docs_root.mkdir(parents=True)
    (docs_root / "qing_general.md").write_text("# 清代财政总论\n清代财政总体变迁", encoding="utf-8")
    (docs_root / "qing_tax.md").write_text("# 清代税制\n田赋与厘金改革", encoding="utf-8")
    (docs_root / "qing_salt.md").write_text("# 清代盐政\n盐课与专卖财政", encoding="utf-8")
    _write_metadata_sidecar(
        docs_root,
        [
            '{"source_filename":"qing_general.md","type":"core","categories":["财政史","清史"],"eras":["清代"],"summary":"清代财政通论"}',
            '{"source_filename":"qing_tax.md","type":"specialized","categories":["税制","财政史"],"eras":["清代"],"summary":"清代税制演变"}',
            '{"source_filename":"qing_salt.md","type":"reference","categories":["盐政","财政史"],"eras":["清代"],"summary":"清代盐课资料"}',
        ],
    )

    monkeypatch.setattr(
        catalog_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(docs_path=str(docs_root)),
    )

    results = search_book_catalog("清代中国财政情况变迁", top_k=3)

    result_types = {item.type for item in results}
    assert "core" in result_types
    assert "specialized" in result_types or "reference" in result_types
    assert len(results) >= 3


def test_list_book_catalog_reads_global_ingestion_preview_filename(tmp_path, monkeypatch) -> None:
    docs_root = tmp_path / "knowledge" / "docs"
    ingestion_dir = docs_root / ".ingestion"
    docs_root.mkdir(parents=True)
    ingestion_dir.mkdir(parents=True)
    (docs_root / "finance_history.preview.md").write_text("# 财政史\n财政制度演变", encoding="utf-8")
    (ingestion_dir / "finance_history.pdf.json").write_text(
        """
        {
          "source_filename": "finance_history.pdf",
          "preview_filename": "finance_history.preview.md",
          "display_title": "finance_history",
          "indexable": true,
          "preview_artifact_url": "/api/knowledge/docs/finance_history.preview.md"
        }
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        catalog_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(docs_path=str(docs_root)),
    )

    entries = list_book_catalog()

    assert len(entries) == 1
    assert entries[0].filename == "finance_history.pdf"
    assert entries[0].source_path.endswith("finance_history.preview.md")
    assert entries[0].preview.startswith("# 财政史")


def test_book_search_tool_groups_candidates_by_layer(monkeypatch) -> None:
    candidates = [
        BookCatalogEntry(
            doc_id="user-1",
            title="User Book",
            filename="user.md",
            scope="user",
            source_path="/tmp/user.md",
            source_url="/api/secure-knowledge/users/me/knowledge/docs/user.md",
            original_url=None,
            preview="",
            search_text="user",
            search_tokens=["user"],
            type="user",
            categories=["摘录"],
            eras=["民国"],
            regions=["全国"],
            keywords=[],
            summary="用户材料",
            priority=0,
            score=5.0,
            folder_path="人物传记/晚清",
        ),
        BookCatalogEntry(
            doc_id="core-1",
            title="Core Book",
            filename="core.md",
            scope="global",
            source_path="/tmp/core.md",
            source_url="/api/knowledge/docs/core.md",
            original_url=None,
            preview="",
            search_text="core",
            search_tokens=["core"],
            type="core",
            categories=["通史"],
            eras=["明清"],
            regions=["全国"],
            keywords=[],
            summary="核心通史",
            priority=1,
            score=4.0,
            folder_path="人物传记/晚清",
            language_hint="zh-Hant",
        ),
        BookCatalogEntry(
            doc_id="spec-1",
            title="Spec Book",
            filename="spec.md",
            scope="global",
            source_path="/tmp/spec.md",
            source_url="/api/knowledge/docs/spec.md",
            original_url=None,
            preview="",
            search_text="spec",
            search_tokens=["spec"],
            type="specialized",
            categories=["财政史"],
            eras=["明清"],
            regions=["全国"],
            keywords=[],
            summary="专题支撑",
            priority=2,
            score=3.0,
            folder_path="人物传记/晚清",
        ),
        BookCatalogEntry(
            doc_id="ref-1",
            title="Ref Book",
            filename="ref.md",
            scope="global",
            source_path="/tmp/ref.md",
            source_url="/api/knowledge/docs/ref.md",
            original_url=None,
            preview="",
            search_text="ref",
            search_tokens=["ref"],
            type="reference",
            categories=["工具书"],
            eras=[],
            regions=[],
            keywords=[],
            summary="参考资料",
            priority=3,
            score=2.0,
            folder_path="人物传记/晚清",
        ),
    ]
    monkeypatch.setattr(
        tools_module,
        "search_book_catalog",
        lambda query, thread_id=None, user_id=None, top_k=8, doc_ids=None, scopes=None, folder_paths=None, entries=None: candidates,
    )
    monkeypatch.setattr(tools_module, "list_book_catalog", lambda thread_id=None, user_id=None: candidates)

    output = tools_module.book_search_tool.func(
        SimpleNamespace(context={}),
        "任意问题",
        knowledge_folders=["人物传记/晚清"],
    )

    assert "### 用户书籍" in output
    assert "### 核心通用书" in output
    assert "### 专题支撑书" in output
    assert "### 补充材料 / 参考工具书" in output
    assert "- User Book | doc_id=user-1 | 相关度=5.00" in output
    assert 'next: knowledge_locate(doc_id="user-1")' in output
    assert 'next: knowledge_locate(doc_id="core-1")' in output
    assert 'next: knowledge_locate(doc_id="spec-1")' in output
    assert 'next: knowledge_locate(doc_id="ref-1")' in output
    assert "语言=繁体中文 (zh-Hant)" in output
    assert 'user doc_ids: ["user-1"]' in output
    assert 'core doc_ids: ["core-1"]' in output
    assert 'specialized doc_ids: ["spec-1"]' in output
    assert 'reference doc_ids: ["ref-1"]' in output
    assert "`knowledge_search` 只检索历史主任务/子任务结果" in output
    assert "调用 `knowledge_locate`" in output
    assert "判断候选书与任务目标是否适配" in output
    assert "默认顺序：用户书籍 -> 当前线程书籍 -> 核心通用书 -> 专题支撑书 -> 补充材料" in output
    assert "检索前先看每本候选书的 metadata" in output
    assert "就用繁体检索词" in output


def test_book_search_tool_lists_catalog_once_and_reuses_entries(monkeypatch) -> None:
    list_calls = 0
    captured: dict[str, object] = {}

    def fake_list_book_catalog(thread_id=None, user_id=None):
        nonlocal list_calls
        list_calls += 1
        return [
            BookCatalogEntry(
                doc_id="global-doc",
                title="Global Book",
                filename="global.md",
                scope="global",
                source_path="/tmp/global.md",
                source_url="/api/knowledge/docs/global.md",
                original_url=None,
                preview="",
                search_text="global",
                search_tokens=["global"],
                type="core",
                folder_path="人物传记/晚清",
            )
        ]

    def fake_search(query, thread_id=None, user_id=None, top_k=8, doc_ids=None, scopes=None, folder_paths=None, entries=None):
        captured["entries"] = entries
        return []

    monkeypatch.setattr(tools_module, "list_book_catalog", fake_list_book_catalog)
    monkeypatch.setattr(tools_module, "search_book_catalog", fake_search)

    output = tools_module.book_search_tool.func(
        SimpleNamespace(context={}),
        "任意问题",
        knowledge_folders=["人物传记/晚清"],
    )

    assert output == "No likely books found for this query."
    assert list_calls == 1
    assert captured["entries"] is not None


def test_book_search_tool_uses_larger_top_k(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_search(query, thread_id=None, user_id=None, top_k=8, doc_ids=None, scopes=None, folder_paths=None, entries=None):
        captured["top_k"] = top_k
        return []

    monkeypatch.setattr(
        tools_module,
        "list_book_catalog",
        lambda thread_id=None, user_id=None: [
            BookCatalogEntry(
                doc_id="global-doc",
                title="Global Book",
                filename="global.md",
                scope="global",
                source_path="/tmp/global.md",
                source_url="/api/knowledge/docs/global.md",
                original_url=None,
                preview="",
                search_text="global",
                search_tokens=["global"],
                type="core",
                folder_path="人物传记/晚清",
            )
        ],
    )
    monkeypatch.setattr(tools_module, "search_book_catalog", fake_search)

    tools_module.book_search_tool.func(
        SimpleNamespace(context={}),
        "任意问题",
        knowledge_folders=["人物传记/晚清"],
    )

    assert captured["top_k"] == 20


def test_book_search_tool_requires_knowledge_folders(monkeypatch) -> None:
    monkeypatch.setattr(
        tools_module,
        "list_book_catalog",
        lambda thread_id=None, user_id=None: [
            BookCatalogEntry(
                doc_id="global-doc",
                title="Global Book",
                filename="global.md",
                scope="global",
                source_path="/tmp/global.md",
                source_url="/api/knowledge/docs/global.md",
                original_url=None,
                preview="",
                search_text="global",
                search_tokens=["global"],
                type="core",
                folder_path="人物传记/晚清",
            )
        ],
    )

    output = tools_module.book_search_tool.func(
        SimpleNamespace(context={}),
        "任意问题",
        knowledge_folders=None,
    )

    assert "Error: `book_search` 禁止整库全量搜索" in output
    assert "`knowledge_folders`" in output
    assert "## 可见知识库目录树" in output


def test_book_search_tool_rejects_local_filesystem_knowledge_folders(monkeypatch) -> None:
    monkeypatch.setattr(
        tools_module,
        "list_book_catalog",
        lambda thread_id=None, user_id=None: [
            BookCatalogEntry(
                doc_id="global-doc",
                title="Global Book",
                filename="global.md",
                scope="global",
                source_path="/tmp/global.md",
                source_url="/api/knowledge/docs/global.md",
                original_url=None,
                preview="",
                search_text="global",
                search_tokens=["global"],
                type="core",
                folder_path="人物传记/晚清",
            )
        ],
    )

    output = tools_module.book_search_tool.func(
        SimpleNamespace(context={}),
        "任意问题",
        knowledge_folders=["/mnt/user-data/uploads"],
    )

    assert "看起来像本地 sandbox 路径或文件名" in output
    assert "## 可见知识库目录树" in output


def test_book_search_tool_rejects_virtual_layer_labels_as_knowledge_folders(monkeypatch) -> None:
    monkeypatch.setattr(
        tools_module,
        "list_book_catalog",
        lambda thread_id=None, user_id=None: [
            BookCatalogEntry(
                doc_id="global-doc",
                title="Global Book",
                filename="global.md",
                scope="global",
                source_path="/tmp/global.md",
                source_url="/api/knowledge/docs/global.md",
                original_url=None,
                preview="",
                search_text="global",
                search_tokens=["global"],
                type="core",
                folder_path="人物传记/晚清",
            )
        ],
    )

    output = tools_module.book_search_tool.func(
        SimpleNamespace(context={}),
        "任意问题",
        knowledge_folders=["核心通用书", "专题支撑书"],
    )

    assert "层级标签" in output
    assert "不是知识库逻辑目录" in output
    assert "人物传记/" in output


def test_book_search_tool_accepts_trailing_slash_on_real_knowledge_folder(monkeypatch) -> None:
    captured: dict[str, object] = {}

    entry = BookCatalogEntry(
        doc_id="global-doc",
        title="Global Book",
        filename="global.md",
        scope="global",
        source_path="/tmp/global.md",
        source_url="/api/knowledge/docs/global.md",
        original_url=None,
        preview="",
        search_text="global",
        search_tokens=["global"],
        type="core",
        folder_path="人物传记/晚清",
        score=0.88,
    )

    monkeypatch.setattr(
        tools_module,
        "list_book_catalog",
        lambda thread_id=None, user_id=None: [entry],
    )

    def fake_search(query, thread_id=None, user_id=None, top_k=8, doc_ids=None, scopes=None, folder_paths=None, entries=None):
        captured["folder_paths"] = folder_paths
        return [entry]

    monkeypatch.setattr(tools_module, "search_book_catalog", fake_search)

    output = tools_module.book_search_tool.func(
        SimpleNamespace(context={}),
        "任意问题",
        knowledge_folders=["人物传记/晚清/"],
    )

    assert "Error:" not in output
    assert captured["folder_paths"] == ["人物传记/晚清"]


def test_book_search_tool_rejects_virtual_layer_labels_with_trailing_slash(monkeypatch) -> None:
    monkeypatch.setattr(
        tools_module,
        "list_book_catalog",
        lambda thread_id=None, user_id=None: [
            BookCatalogEntry(
                doc_id="global-doc",
                title="Global Book",
                filename="global.md",
                scope="global",
                source_path="/tmp/global.md",
                source_url="/api/knowledge/docs/global.md",
                original_url=None,
                preview="",
                search_text="global",
                search_tokens=["global"],
                type="core",
                folder_path="人物传记/晚清",
            )
        ],
    )

    output = tools_module.book_search_tool.func(
        SimpleNamespace(context={}),
        "任意问题",
        knowledge_folders=["核心通用书/", "global/"],
    )

    assert "层级标签" in output
    assert "不是知识库逻辑目录" in output


def test_search_book_catalog_can_reuse_prelisted_entries(monkeypatch) -> None:
    entries = [
        BookCatalogEntry(
            doc_id="core-1",
            title="Core Book",
            filename="core.md",
            scope="global",
            source_path="/tmp/core.md",
            source_url="/api/knowledge/docs/core.md",
            original_url=None,
            preview="",
            search_text="财政制度演变 通史",
            search_tokens=["财政制度演变", "通史"],
            type="core",
        )
    ]

    monkeypatch.setattr(
        catalog_module,
        "list_book_catalog",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("search_book_catalog should reuse provided entries")),
    )

    results = search_book_catalog("财政制度演变", top_k=1, entries=entries)

    assert [item.doc_id for item in results] == ["core-1"]


def test_knowledge_search_tool_rejects_scopes_with_doc_ids(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _DummyRetriever:
        def search(self, query, thread_id=None, user_id=None, doc_ids=None, scopes=None, folder_paths=None):
            captured["query"] = query
            captured["thread_id"] = thread_id
            captured["user_id"] = user_id
            captured["doc_ids"] = doc_ids
            captured["scopes"] = scopes
            captured["folder_paths"] = folder_paths
            return []

    retriever_stub = ModuleType("src.community.knowledge_base.retriever")
    retriever_stub.get_retriever = lambda: _DummyRetriever()
    monkeypatch.setitem(sys.modules, "src.community.knowledge_base.retriever", retriever_stub)
    monkeypatch.setattr(
        tools_module,
        "list_book_catalog",
        lambda thread_id=None, user_id=None: [
            BookCatalogEntry(
                doc_id="global-doc",
                title="Global Book 1",
                filename="global-1.md",
                scope="global",
                source_path="/tmp/global-1.md",
                source_url="/api/knowledge/docs/global-1.md",
                original_url=None,
                preview="",
                search_text="global",
                search_tokens=["global"],
                folder_path="财政史/清代",
            ),
            BookCatalogEntry(
                doc_id="global-doc-2",
                title="Global Book 2",
                filename="global-2.md",
                scope="global",
                source_path="/tmp/global-2.md",
                source_url="/api/knowledge/docs/global-2.md",
                original_url=None,
                preview="",
                search_text="global",
                search_tokens=["global"],
                folder_path="财政史/清代",
            ),
        ],
    )

    tools_module.knowledge_search_tool.func(
        SimpleNamespace(context={"thread_id": "thread-1", "user_id": "user-1"}),
        "民国时期财政情况",
        doc_ids=["global-doc", "global-doc-2"],
        scopes="global",
        knowledge_folders=["财政史/清代"],
    )

    assert captured == {}


def test_knowledge_search_tool_accepts_json_doc_id_string(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _DummyRetriever:
        def search(self, query, thread_id=None, user_id=None, doc_ids=None, scopes=None, folder_paths=None):
            captured["doc_ids"] = doc_ids
            return []

    retriever_stub = ModuleType("src.community.knowledge_base.retriever")
    retriever_stub.get_retriever = lambda: _DummyRetriever()
    monkeypatch.setitem(sys.modules, "src.community.knowledge_base.retriever", retriever_stub)
    monkeypatch.setattr(
        tools_module,
        "list_book_catalog",
        lambda thread_id=None, user_id=None: [
            BookCatalogEntry(
                doc_id="global-doc-1",
                title="Global Book 1",
                filename="global-1.md",
                scope="global",
                source_path="/tmp/global-1.md",
                source_url="/api/knowledge/docs/global-1.md",
                original_url=None,
                preview="",
                search_text="global",
                search_tokens=["global"],
                folder_path="财政史/清代",
            ),
            BookCatalogEntry(
                doc_id="global-doc-2",
                title="Global Book 2",
                filename="global-2.md",
                scope="global",
                source_path="/tmp/global-2.md",
                source_url="/api/knowledge/docs/global-2.md",
                original_url=None,
                preview="",
                search_text="global",
                search_tokens=["global"],
                folder_path="财政史/清代",
            ),
            BookCatalogEntry(
                doc_id="global-doc-3",
                title="Global Book 3",
                filename="global-3.md",
                scope="global",
                source_path="/tmp/global-3.md",
                source_url="/api/knowledge/docs/global-3.md",
                original_url=None,
                preview="",
                search_text="global",
                search_tokens=["global"],
                folder_path="财政史/清代",
            ),
        ],
    )

    tools_module.knowledge_search_tool.func(
        SimpleNamespace(context={}),
        "任意问题",
        doc_ids='["global-doc-1", "global-doc-2", "global-doc-3"]',
        knowledge_folders=["财政史/清代"],
    )

    assert captured == {}


def test_knowledge_search_tool_schema_exposes_doc_ids_as_array() -> None:
    schema = tools_module.knowledge_search_tool.args_schema.model_json_schema()
    doc_ids_schema = schema["properties"]["doc_ids"]
    assert "anyOf" in doc_ids_schema
    array_schema = next(item for item in doc_ids_schema["anyOf"] if item.get("type") == "array")
    assert array_schema["items"]["type"] == "string"
    assert not any(item.get("type") == "string" for item in doc_ids_schema["anyOf"])


def test_knowledge_search_tool_invoke_does_not_require_runtime(monkeypatch) -> None:
    task_memory_stub = ModuleType("src.community.knowledge_base.task_memory")
    task_memory_stub.search_and_prepare_task_memory = (
        lambda *, query, title=None, target_state=None, top_k=None, task_level=None: [
            {"content": "命中", "metadata": {}, "score": 1.0}
        ]
    )
    task_memory_stub.render_task_memory_matches = lambda results, *, heading: f"{heading}\n\nok"
    monkeypatch.setitem(sys.modules, "src.community.knowledge_base.task_memory", task_memory_stub)

    output = tools_module.knowledge_search_tool.invoke({"query": "任意问题"})

    assert "## 检索结果" in output
    assert "ok" in output


def test_knowledge_search_tool_no_result_stops_task_memory_loop(monkeypatch) -> None:
    task_memory_stub = ModuleType("src.community.knowledge_base.task_memory")
    task_memory_stub.search_and_prepare_task_memory = (
        lambda *, query, title=None, target_state=None, top_k=None, task_level=None: []
    )
    task_memory_stub.render_task_memory_matches = (
        lambda results, *, heading: f"{heading}\n\n本轮没有命中可直接复用的历史主任务/子任务结果。"
    )
    monkeypatch.setitem(sys.modules, "src.community.knowledge_base.task_memory", task_memory_stub)

    output = tools_module.knowledge_search_tool.invoke({"query": "任意问题"})

    assert "没有可复用历史结果" in output
    assert "不要继续改写 query 反复调用 `knowledge_search`" in output
    assert "knowledge_locate" in output


def test_knowledge_search_tool_rejects_raw_doc_filters(monkeypatch) -> None:
    task_memory_stub = ModuleType("src.community.knowledge_base.task_memory")
    task_memory_stub.search_task_memory = lambda query, *, title=None, top_k=None: []
    task_memory_stub.render_task_memory_matches = lambda results, *, heading: f"{heading}\n\nunexpected"
    monkeypatch.setitem(sys.modules, "src.community.knowledge_base.task_memory", task_memory_stub)

    output = tools_module.knowledge_search_tool.func(
        SimpleNamespace(context={}),
        "任意问题",
        doc_ids=["doc-1"],
    )

    assert "`knowledge_search` 现在只检索历史主任务/子任务结果" in output
    assert "`doc_ids`、`scopes`、`knowledge_folders` 在这里都是误用参数" in output
    assert "knowledge_locate(doc_id=...)" in output


def test_knowledge_search_tool_accepts_doc_id_arrays(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _DummyRetriever:
        def search(self, query, thread_id=None, user_id=None, doc_ids=None, scopes=None, folder_paths=None):
            captured["doc_ids"] = doc_ids
            return []

    retriever_stub = ModuleType("src.community.knowledge_base.retriever")
    retriever_stub.get_retriever = lambda: _DummyRetriever()
    monkeypatch.setitem(sys.modules, "src.community.knowledge_base.retriever", retriever_stub)
    monkeypatch.setattr(
        tools_module,
        "list_book_catalog",
        lambda thread_id=None, user_id=None: [
            BookCatalogEntry(
                doc_id="global-doc-1",
                title="Global Book 1",
                filename="global-1.md",
                scope="global",
                source_path="/tmp/global-1.md",
                source_url="/api/knowledge/docs/global-1.md",
                original_url=None,
                preview="",
                search_text="global",
                search_tokens=["global"],
                folder_path="财政史/清代",
            ),
            BookCatalogEntry(
                doc_id="global-doc-2",
                title="Global Book 2",
                filename="global-2.md",
                scope="global",
                source_path="/tmp/global-2.md",
                source_url="/api/knowledge/docs/global-2.md",
                original_url=None,
                preview="",
                search_text="global",
                search_tokens=["global"],
                folder_path="财政史/清代",
            ),
        ],
    )

    tools_module.knowledge_search_tool.func(
        SimpleNamespace(context={}),
        "任意问题",
        doc_ids=["global-doc-1", "global-doc-2"],
        knowledge_folders=["财政史/清代"],
    )

    assert captured == {}


def test_knowledge_search_tool_forwards_knowledge_folders(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _DummyRetriever:
        def search(self, query, thread_id=None, user_id=None, doc_ids=None, scopes=None, folder_paths=None):
            captured["folder_paths"] = folder_paths
            return []

    retriever_stub = ModuleType("src.community.knowledge_base.retriever")
    retriever_stub.get_retriever = lambda: _DummyRetriever()
    monkeypatch.setitem(sys.modules, "src.community.knowledge_base.retriever", retriever_stub)
    monkeypatch.setattr(
        tools_module,
        "list_book_catalog",
        lambda thread_id=None, user_id=None: [
            BookCatalogEntry(
                doc_id="global-doc",
                title="Global Book",
                filename="global.md",
                scope="global",
                source_path="/tmp/global.md",
                source_url="/api/knowledge/docs/global.md",
                original_url=None,
                preview="",
                search_text="global",
                search_tokens=["global"],
                type="core",
                folder_path="财政史/清代",
            ),
            BookCatalogEntry(
                doc_id="global-doc-2",
                title="Global Book 2",
                filename="global-2.md",
                scope="global",
                source_path="/tmp/global-2.md",
                source_url="/api/knowledge/docs/global-2.md",
                original_url=None,
                preview="",
                search_text="global",
                search_tokens=["global"],
                type="specialized",
                folder_path="财政史/晚清",
            ),
        ],
    )

    tools_module.knowledge_search_tool.func(
        SimpleNamespace(context={}),
        "晚清财政情况",
        knowledge_folders=["财政史/清代", "财政史/晚清"],
    )

    assert captured == {}


def test_knowledge_search_tool_requires_knowledge_folders(monkeypatch) -> None:
    monkeypatch.setattr(
        tools_module,
        "list_book_catalog",
        lambda thread_id=None, user_id=None: [
            BookCatalogEntry(
                doc_id="global-doc",
                title="Global Book",
                filename="global.md",
                scope="global",
                source_path="/tmp/global.md",
                source_url="/api/knowledge/docs/global.md",
                original_url=None,
                preview="",
                search_text="global",
                search_tokens=["global"],
                type="core",
                folder_path="财政史/清代",
            )
        ],
    )

    output = tools_module.knowledge_search_tool.func(
        SimpleNamespace(context={}),
        "晚清财政情况",
        knowledge_folders=None,
    )

    assert "本轮没有命中可直接复用的历史主任务/子任务结果" in output
    assert "不要继续改写 query 反复调用 `knowledge_search`" in output


def test_knowledge_search_tool_rejects_virtual_layer_labels_as_knowledge_folders(monkeypatch) -> None:
    monkeypatch.setattr(
        tools_module,
        "list_book_catalog",
        lambda thread_id=None, user_id=None: [
            BookCatalogEntry(
                doc_id="global-doc",
                title="Global Book",
                filename="global.md",
                scope="global",
                source_path="/tmp/global.md",
                source_url="/api/knowledge/docs/global.md",
                original_url=None,
                preview="",
                search_text="global",
                search_tokens=["global"],
                type="core",
                folder_path="人物传记/晚清",
            )
        ],
    )

    output = tools_module.knowledge_search_tool.func(
        SimpleNamespace(context={}),
        "晚清财政情况",
        knowledge_folders=["用户书籍", "核心通用书"],
    )

    assert "`knowledge_search` 现在只检索历史主任务/子任务结果" in output
    assert "`doc_ids`、`scopes`、`knowledge_folders` 在这里都是误用参数" in output
    assert "knowledge_locate(doc_id=...)" in output


def test_tool_schema_marks_knowledge_folders_as_required() -> None:
    assert tools_module.book_search_tool.args_schema.model_fields["knowledge_folders"].is_required()
    assert not tools_module.knowledge_search_tool.args_schema.model_fields["knowledge_folders"].is_required()


def test_knowledge_locate_tool_schema_requires_non_nullable_doc_id() -> None:
    doc_id_field = tools_module.knowledge_locate_tool.args_schema.model_fields["doc_id"]
    assert doc_id_field.is_required()
    assert doc_id_field.annotation is str
    assert "filename" not in tools_module.knowledge_locate_tool.args_schema.model_fields


def test_knowledge_search_tool_allows_mixed_layer_doc_ids(monkeypatch) -> None:
    class _DummyRetriever:
        def search(self, query, thread_id=None, user_id=None, doc_ids=None, scopes=None, folder_paths=None):
            return [
                {
                    "content": "混层检索命中结果，这是一段足够长的正文，用来验证跨层 doc_ids 联合检索仍然能够正常返回结果。",
                    "score": 0.91,
                    "filename": "ref.md",
                    "metadata": {
                        "title": "Reference Book",
                        "doc_id": "reference-doc",
                        "scope": "global",
                        "page_no": 3,
                    },
                }
            ]

    retriever_stub = ModuleType("src.community.knowledge_base.retriever")
    retriever_stub.get_retriever = lambda: _DummyRetriever()
    monkeypatch.setitem(sys.modules, "src.community.knowledge_base.retriever", retriever_stub)
    monkeypatch.setattr(
        tools_module,
        "list_book_catalog",
        lambda thread_id=None, user_id=None: [
            BookCatalogEntry(
                doc_id="user-doc",
                title="User Book",
                filename="user.md",
                scope="user",
                source_path="/tmp/user.md",
                source_url="/api/secure-knowledge/users/me/knowledge/docs/user.md",
                original_url=None,
                preview="",
                search_text="user",
                search_tokens=["user"],
                type="user",
                folder_path="用户资料/人物",
            ),
            BookCatalogEntry(
                doc_id="reference-doc",
                title="Reference Book",
                filename="ref.md",
                scope="global",
                source_path="/tmp/ref.md",
                source_url="/api/knowledge/docs/ref.md",
                original_url=None,
                preview="",
                search_text="ref",
                search_tokens=["ref"],
                type="reference",
                folder_path="参考资料/工具书",
            ),
        ],
    )

    output = tools_module.knowledge_search_tool.func(
        SimpleNamespace(context={"thread_id": "thread-1", "user_id": "user-1"}),
        "任意问题",
        doc_ids=["user-doc", "reference-doc"],
        knowledge_folders=["用户资料/人物", "参考资料/工具书"],
    )

    assert "## 检索结果" in output
    assert "`knowledge_search` 现在只检索历史主任务/子任务结果" in output
    assert "`doc_ids`、`scopes`、`knowledge_folders` 在这里都是误用参数" in output
    assert "按证据缺口或探索方向派发子任务" in output


def test_knowledge_search_tool_footer_warns_scope_and_query_misuse(monkeypatch) -> None:
    class _DummyRetriever:
        def search(self, query, thread_id=None, user_id=None, doc_ids=None, scopes=None, folder_paths=None):
            return [
                {
                    "content": "民国财政以税收、公债与币制调整为主要线索，这段正文足够长，可用于验证工具尾部提示是否按新的关键词检索模式输出。",
                    "score": 0.91,
                    "filename": "finance.md",
                    "metadata": {
                        "title": "财政史",
                        "doc_id": "global-doc",
                        "scope": "global",
                        "page_no": 12,
                        "pdf_page_no": 12,
                        "paragraph_no": 3,
                    },
                }
            ]

    retriever_stub = ModuleType("src.community.knowledge_base.retriever")
    retriever_stub.get_retriever = lambda: _DummyRetriever()
    monkeypatch.setitem(sys.modules, "src.community.knowledge_base.retriever", retriever_stub)
    monkeypatch.setattr(
        tools_module,
        "list_book_catalog",
        lambda thread_id=None, user_id=None: [
            BookCatalogEntry(
                doc_id="global-doc",
                title="Global Book",
                filename="finance.md",
                scope="global",
                source_path="/tmp/finance.md",
                source_url="/api/knowledge/docs/finance.md",
                original_url=None,
                preview="",
                search_text="finance",
                search_tokens=["finance"],
                type="core",
                folder_path="财政史/民国",
            )
        ],
    )
    monkeypatch.setattr(
        tools_module,
        "resolve_result_citation_context",
        lambda result, thread_id=None, user_id=None: {
            "source_url": "/api/knowledge/docs/finance.md",
            "citation_url": "/api/knowledge/docs/finance.md?citation=1",
            "citation_title": "财政史",
            "citation_page_no": 12,
            "citation_pdf_page_no": 12,
            "citation_paragraph_no": 3,
            "citation_page": None,
            "source_label": None,
            "source_scope": "global",
            "original_title": None,
        },
    )

    output = tools_module.knowledge_search_tool.func(
        SimpleNamespace(context={}),
        "民国时期财政情况",
        doc_ids=["global-doc"],
        scopes="global",
        knowledge_folders=["财政史/民国"],
    )

    assert "`knowledge_search` 现在只检索历史主任务/子任务结果" in output
    assert "`doc_ids`、`scopes`、`knowledge_folders` 在这里都是误用参数" in output
    assert "knowledge_locate(doc_id=...)" in output


def test_knowledge_search_tool_no_result_guides_grounded_retries_before_web(monkeypatch) -> None:
    class _DummyRetriever:
        def search(self, query, thread_id=None, user_id=None, doc_ids=None, scopes=None, folder_paths=None):
            return []

    retriever_stub = ModuleType("src.community.knowledge_base.retriever")
    retriever_stub.get_retriever = lambda: _DummyRetriever()
    monkeypatch.setitem(sys.modules, "src.community.knowledge_base.retriever", retriever_stub)
    monkeypatch.setattr(
        tools_module,
        "list_book_catalog",
        lambda thread_id=None, user_id=None: [
            BookCatalogEntry(
                doc_id="core-doc",
                title="Core Book",
                filename="core.md",
                scope="global",
                source_path="/tmp/core.md",
                source_url="/api/knowledge/docs/core.md",
                original_url=None,
                preview="",
                search_text="core",
                search_tokens=["core"],
                type="core",
                folder_path="财政史/清代",
            )
        ],
    )

    output = tools_module.knowledge_search_tool.func(
        SimpleNamespace(context={}),
        "清代末期财政情况",
        doc_ids=["core-doc"],
        scopes="global",
        knowledge_folders=["财政史/清代"],
    )

    assert "`knowledge_search` 现在只检索历史主任务/子任务结果" in output
    assert "`doc_ids`、`scopes`、`knowledge_folders` 在这里都是误用参数" in output
    assert "不要继续改写 query 反复调用 `knowledge_search`" in output


def test_knowledge_locate_tool_emits_citations_and_page_level_followup_guidance(monkeypatch) -> None:
    monkeypatch.setattr(tools_module, "_visible_catalog_entries", lambda **kwargs: [])
    monkeypatch.setattr(
        tools_module,
        "_resolve_requested_doc_ids",
        lambda doc_ids, visible_entries: (doc_ids, [], {}),
    )
    monkeypatch.setattr(
        tools_module,
        "locate_document",
        lambda thread_id, user_id=None, doc_id=None, filename=None: SimpleNamespace(
            doc_id=doc_id or "global-doc",
            title="财政史",
            filename="finance.pdf",
            scope="global",
            source_url="/api/knowledge/docs/finance.pdf",
            original_url=None,
            payload={"pages": []},
        ),
    )
    monkeypatch.setattr(
        tools_module,
        "extract_document_context",
        lambda **kwargs: [
            {
                "page_no": 12,
                "pdf_page_no": 12,
                "paragraph_no": 3,
                "text": "这是第 3 段。",
            },
            {
                "page_no": 12,
                "pdf_page_no": 12,
                "paragraph_no": 4,
                "text": "这是第 4 段。",
            },
        ],
    )
    monkeypatch.setattr(
        tools_module,
        "resolve_result_citation_context",
        lambda result, thread_id=None, user_id=None: {
            "source_url": "/api/knowledge/docs/finance.pdf",
            "citation_url": "/api/knowledge/docs/finance.pdf?pdf_page_no=12&paragraph_no="
            f"{result['metadata']['paragraph_no']}",
            "citation_title": "财政史",
            "citation_page_no": None,
            "citation_pdf_page_no": 12,
            "citation_paragraph_no": result["metadata"]["paragraph_no"],
            "citation_page": None,
        },
    )

    state = {}
    output = tools_module.knowledge_locate_tool.func(
        SimpleNamespace(context={}, state=state),
        doc_id="global-doc",
        pdf_page_no=12,
    )

    registry = state["knowledge_citation_registry"]
    assert len(registry) == 2 and registry[0]["id"] != registry[1]["id"]
    for entry, paragraph in zip(registry, [3, 4], strict=True):
        assert f"citation: [citation:{entry['id']}]" in output
        assert entry["label"] == f"财政史 PDF第12页第{paragraph}段"
        assert "pdf_page_no=12" in entry["url"]
        assert f"paragraph_no={paragraph}" in entry["url"]
    assert "如果同一主题明显跨相邻多页" in output
    assert "`page_no_end` / `pdf_page_no_end`" in output


def test_knowledge_locate_tool_supports_multi_page_ranges(monkeypatch) -> None:
    monkeypatch.setattr(tools_module, "_visible_catalog_entries", lambda **kwargs: [])
    monkeypatch.setattr(
        tools_module,
        "_resolve_requested_doc_ids",
        lambda doc_ids, visible_entries: (doc_ids, [], {}),
    )
    monkeypatch.setattr(
        tools_module,
        "locate_document",
        lambda thread_id, user_id=None, doc_id=None, filename=None: SimpleNamespace(
            doc_id=doc_id or "global-doc",
            title="财政史",
            filename="finance.pdf",
            scope="global",
            source_url="/api/knowledge/docs/finance.pdf",
            original_url=None,
            payload={"pages": []},
        ),
    )
    captured: dict[str, int | None] = {}

    def fake_extract_document_context(**kwargs):
        captured["pdf_page_no"] = kwargs.get("pdf_page_no")
        captured["pdf_page_no_end"] = kwargs.get("pdf_page_no_end")
        return [
            {
                "page_no": 12,
                "pdf_page_no": 12,
                "paragraph_no": 1,
                "text": "第 12 页片段。",
            },
            {
                "page_no": 13,
                "pdf_page_no": 13,
                "paragraph_no": 2,
                "text": "第 13 页片段。",
            },
        ]

    monkeypatch.setattr(tools_module, "extract_document_context", fake_extract_document_context)
    monkeypatch.setattr(
        tools_module,
        "resolve_result_citation_context",
        lambda result, thread_id=None, user_id=None: {
            "source_url": "/api/knowledge/docs/finance.pdf",
            "citation_url": "/api/knowledge/docs/finance.pdf?page_no=12",
            "citation_title": "财政史",
            "citation_page_no": result["metadata"]["page_no"],
            "citation_pdf_page_no": result["metadata"]["pdf_page_no"],
            "citation_paragraph_no": result["metadata"]["paragraph_no"],
            "citation_page": None,
        },
    )

    output = tools_module.knowledge_locate_tool.func(
        SimpleNamespace(context={}),
        doc_id="global-doc",
        pdf_page_no=12,
        pdf_page_no_end=13,
    )

    assert captured == {"pdf_page_no": 12, "pdf_page_no_end": 13}
    assert "第 12 页片段。" in output
    assert "第 13 页片段。" in output
    assert "连续页范围展开" in output


def _make_entry(*, doc_id: str, title: str, scope: str, folder: str, pages: int, book_type: str = "unknown") -> BookCatalogEntry:
    return BookCatalogEntry(
        doc_id=doc_id,
        title=title,
        filename=f"{doc_id}.pdf",
        scope=scope,
        source_path=f"/tmp/{doc_id}.pdf",
        source_url=f"/api/knowledge/docs/{doc_id}.pdf",
        original_url=None,
        preview="",
        search_text=title,
        search_tokens=[title],
        type=book_type if scope == "global" else scope,
        folder_path=folder,
        page_count=pages,
    )


def test_render_directory_tree_rolls_up_page_counts() -> None:
    from src.community.knowledge_base.catalog import render_book_catalog_directory_tree

    entries = [
        _make_entry(doc_id="a", title="清史稿", scope="global", folder="清史/晚清", pages=15000, book_type="core"),
        _make_entry(doc_id="b", title="财政通史", scope="global", folder="财政史/民国", pages=3000, book_type="specialized"),
        _make_entry(doc_id="c", title="财政小册", scope="global", folder="财政史/民国", pages=500, book_type="specialized"),
    ]

    tree = render_book_catalog_directory_tree(entries)

    assert tree is not None
    # Folder names appear, book titles do not.
    assert "清史/" in tree
    assert "财政史/" in tree
    assert "清史稿" not in tree
    assert "doc_id=" not in tree
    # 财政史/ rolls up 3000 + 500 = 3500, formatted without 万 suffix.
    assert "财政史/ (3500页)" in tree
    # 清史/ rolls up 15000 → "1.5万页".
    assert "清史/ (1.5万页)" in tree


def test_render_directory_tree_groups_scopes_as_sections_in_priority_order() -> None:
    from src.community.knowledge_base.catalog import render_book_catalog_directory_tree

    entries = [
        _make_entry(doc_id="g1", title="清史稿", scope="global", folder="清史/晚清", pages=15000, book_type="core"),
        _make_entry(doc_id="u1", title="个人笔记", scope="user", folder="笔记/日记", pages=120),
        _make_entry(doc_id="t1", title="本轮上传", scope="thread", folder="临时材料", pages=80),
    ]

    tree = render_book_catalog_directory_tree(entries, include_scope_roots=True)

    assert tree is not None
    # All three scope sections render with full-width bracket headers.
    assert "【当前线程书籍】" in tree
    assert "【用户书籍】" in tree
    assert "【系统知识库】" in tree
    # Ordered: thread → user → system.
    thread_idx = tree.index("【当前线程书籍】")
    user_idx = tree.index("【用户书籍】")
    system_idx = tree.index("【系统知识库】")
    assert thread_idx < user_idx < system_idx
    # Section headers carry a rollup page count in full-width parentheses.
    assert "【系统知识库】（1.5万页）" in tree
    assert "【用户书籍】（120页）" in tree
    # Folder names INSIDE a section never include the section label as a path
    # segment (that would mislead the agent into copying it into knowledge_folders).
    assert "用户书籍/" not in tree
    assert "系统知识库/" not in tree


def test_render_directory_tree_omits_suffix_when_no_page_counts_known() -> None:
    from src.community.knowledge_base.catalog import render_book_catalog_directory_tree

    entries = [
        _make_entry(doc_id="x", title="未解析的书", scope="global", folder="待整理", pages=0, book_type="unknown"),
    ]

    tree = render_book_catalog_directory_tree(entries)

    assert tree is not None
    assert "待整理/" in tree
    # No "(0页)" noise when we genuinely don't know the size yet.
    assert "(0页)" not in tree
    assert "页)" not in tree
