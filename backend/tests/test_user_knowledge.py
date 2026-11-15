import importlib.util
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.documents import Document

import src.community.knowledge_base.indexer as indexer_module
import src.community.knowledge_base.lexical_search as lexical_search_module
import src.community.knowledge_base.retriever as retriever_module
import src.community.knowledge_base.user_spaces as user_spaces_module
import src.community.knowledge_base.user_store as user_store_module
import src.config.paths as paths_module
from src.community.knowledge_base.catalog import BookCatalogEntry
from src.config.paths import Paths


def _long_text(seed: str) -> str:
    return (seed * 80)[:240]

_USER_KNOWLEDGE_ROUTER_SPEC = importlib.util.spec_from_file_location(
    "test_user_knowledge_router_module",
    Path(__file__).parent.parent / "src/gateway/routers/user_knowledge.py",
)
user_knowledge_router = importlib.util.module_from_spec(_USER_KNOWLEDGE_ROUTER_SPEC)
assert _USER_KNOWLEDGE_ROUTER_SPEC and _USER_KNOWLEDGE_ROUTER_SPEC.loader
_USER_KNOWLEDGE_ROUTER_SPEC.loader.exec_module(user_knowledge_router)


def test_paths_create_user_knowledge_dirs_and_validate_user_id(tmp_path) -> None:
    paths = Paths(tmp_path)
    paths.ensure_user_knowledge_dirs("user_123")

    assert paths.user_knowledge_docs_dir("user_123").exists()
    assert paths.user_knowledge_ingestion_dir("user_123").exists()
    assert paths.user_knowledge_catalog_dir("user_123").exists()

    try:
        paths.user_dir("../bad")
    except ValueError as exc:
        assert "Invalid user_id" in str(exc)
    else:  # pragma: no cover - defensive failure
        raise AssertionError("expected invalid user_id to raise")


def test_rebuild_user_knowledge_index_indexes_upload_and_skips_import_ref(tmp_path, monkeypatch) -> None:
    paths = Paths(tmp_path)
    monkeypatch.setattr(paths_module, "_paths", paths)
    paths.ensure_user_knowledge_dirs("user_1")

    upload_path = paths.user_knowledge_ingestion_dir("user_1") / "notes.md.structured.json"
    upload_path.write_text("{}", encoding="utf-8")
    upload_record = user_store_module.build_user_upload_record(
        user_id="user_1",
        source_filename="notes.md",
        size=12,
        content_type="text/markdown",
    )
    upload_record["parse_status"] = "indexed"
    upload_record["indexable"] = True
    upload_record["index_target_filename"] = upload_path.name
    upload_record["index_target_path"] = str(upload_path)
    user_store_module.save_user_record("user_1", upload_record)

    import_record = user_store_module.build_user_import_ref_record(
        user_id="user_1",
        title="Global Book",
        origin_doc_id="global-book",
        origin_filename="global-book.pdf",
    )
    user_store_module.save_user_record("user_1", import_record)

    monkeypatch.setattr(
        indexer_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(
            qdrant=SimpleNamespace(collection_name="knowledge_base"),
            chunking=SimpleNamespace(chunk_size=128, chunk_overlap=0),
        ),
    )
    monkeypatch.setattr(indexer_module, "get_qdrant_client", lambda: SimpleNamespace(delete_collection=lambda **kwargs: None))

    def fake_load_documents(paths_to_load):
        return [
            Document(
                page_content="我的个人知识",
                metadata={
                    "source": str(upload_path),
                    "source_type": "structured",
                },
            )
        ] if paths_to_load else []

    captured = {}

    def fake_index_documents(documents, collection_name, scope, thread_id=None):
        captured["documents"] = documents
        return len(documents)

    monkeypatch.setattr(indexer_module, "_load_documents_from_paths", fake_load_documents)
    monkeypatch.setattr(indexer_module, "index_documents", fake_index_documents)

    result = indexer_module.rebuild_user_knowledge_index("user_1")

    assert result == 1
    assert len(captured["documents"]) == 1
    assert captured["documents"][0].metadata["scope"] == "user"
    assert captured["documents"][0].metadata["doc_id"] == upload_record["id"]
    assert captured["documents"][0].metadata["source_kind"] == "upload"


def test_user_records_without_space_are_migrated_to_default_space(tmp_path, monkeypatch) -> None:
    paths = Paths(tmp_path)
    monkeypatch.setattr(paths_module, "_paths", paths)
    paths.ensure_user_knowledge_dirs("user_1")

    legacy_record = user_store_module.build_user_upload_record(
        user_id="user_1",
        source_filename="legacy.md",
        size=12,
        content_type="text/markdown",
    )
    legacy_record.pop("knowledge_space_id", None)
    user_store_module.save_user_record("user_1", legacy_record)

    loaded = user_store_module.load_user_record("user_1", legacy_record["id"])

    assert loaded is not None
    assert loaded["knowledge_space_id"] == user_spaces_module.DEFAULT_KNOWLEDGE_SPACE_ID


def test_user_knowledge_spaces_endpoint_returns_default_and_public_spaces(tmp_path, monkeypatch) -> None:
    paths = Paths(tmp_path)
    monkeypatch.setattr(paths_module, "_paths", paths)
    paths.ensure_user_knowledge_dirs("user_1")

    created_space = user_spaces_module.create_user_knowledge_space(
        "user_1",
        name="晚清专题",
        description="用于归档晚清财政资料",
    )

    app = FastAPI()
    app.include_router(user_knowledge_router.router)
    client = TestClient(app)

    response = client.get("/api/users/user_1/knowledge/spaces")

    assert response.status_code == 200
    payload = response.json()
    assert [space["id"] for space in payload["spaces"]][:2] == [
        user_spaces_module.DEFAULT_KNOWLEDGE_SPACE_ID,
        created_space["id"],
    ]
    assert any(space["id"] == user_spaces_module.PUBLIC_KNOWLEDGE_SPACE_ID for space in payload["spaces"])


def test_move_user_knowledge_record_between_spaces(tmp_path, monkeypatch) -> None:
    paths = Paths(tmp_path)
    monkeypatch.setattr(paths_module, "_paths", paths)
    paths.ensure_user_knowledge_dirs("user_1")

    target_space = user_spaces_module.create_user_knowledge_space(
        "user_1",
        name="晚清专题",
        description="用于归档晚清财政资料",
    )
    record = user_store_module.build_user_upload_record(
        user_id="user_1",
        source_filename="notes.md",
        size=12,
        content_type="text/markdown",
    )
    user_store_module.save_user_record("user_1", record)

    app = FastAPI()
    app.include_router(user_knowledge_router.router)
    client = TestClient(app)

    response = client.post(
        f"/api/users/user_1/knowledge/{record['id']}/move",
        json={"knowledge_space_id": target_space["id"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["record"]["knowledge_space_id"] == target_space["id"]
    assert payload["record"]["knowledge_space_name"] == "晚清专题"


def test_delete_user_knowledge_space_moves_records_to_default(tmp_path, monkeypatch) -> None:
    paths = Paths(tmp_path)
    monkeypatch.setattr(paths_module, "_paths", paths)
    paths.ensure_user_knowledge_dirs("user_1")

    target_space = user_spaces_module.create_user_knowledge_space(
        "user_1",
        name="晚清专题",
        description="用于归档晚清财政资料",
    )
    record = user_store_module.build_user_upload_record(
        user_id="user_1",
        source_filename="notes.md",
        size=12,
        content_type="text/markdown",
        knowledge_space_id=target_space["id"],
    )
    user_store_module.save_user_record("user_1", record)

    app = FastAPI()
    app.include_router(user_knowledge_router.router)
    client = TestClient(app)

    response = client.delete(f"/api/users/user_1/knowledge/spaces/{target_space['id']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["fallback_space_id"] == user_spaces_module.DEFAULT_KNOWLEDGE_SPACE_ID
    moved = user_store_module.load_user_record("user_1", record["id"])
    assert moved is not None
    assert moved["knowledge_space_id"] == user_spaces_module.DEFAULT_KNOWLEDGE_SPACE_ID


def test_retriever_prioritizes_user_results_over_thread_and_global(monkeypatch) -> None:
    monkeypatch.setattr(
        retriever_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(
            qdrant=SimpleNamespace(collection_name="knowledge_base"),
            retrieval=SimpleNamespace(top_k=5, score_threshold=0.0),
        ),
    )
    monkeypatch.setattr(retriever_module, "get_qdrant_client", lambda: object())
    monkeypatch.setattr(retriever_module, "get_embedding_model", lambda: object())

    retriever = retriever_module.KnowledgeBaseRetriever()
    monkeypatch.setattr(
        retriever_module,
        "search_keyword_documents",
        lambda *args, **kwargs: [
            {
                "content": _long_text("公共知识"),
                "score": 1.0,
                "filename": "global.md",
                "source": "global",
                "metadata": {"scope": "global", "source_kind": "global_document", "doc_id": "global-doc"},
            },
            {
                "content": _long_text("会话知识"),
                "score": 1.0,
                "filename": "thread.md",
                "source": "thread",
                "metadata": {"scope": "thread", "source_kind": "thread_upload", "doc_id": "thread-doc"},
            },
            {
                "content": _long_text("用户知识"),
                "score": 1.0,
                "filename": "user.md",
                "source": "user",
                "metadata": {"scope": "user", "source_kind": "upload", "doc_id": "user-doc"},
            },
        ],
    )

    results = retriever.search("query", thread_id="thread-1", user_id="user-1")

    assert [result["metadata"]["scope"] for result in results[:3]] == ["user", "thread", "global"]


def test_retriever_keeps_keyword_query_and_marks_matched_queries(monkeypatch) -> None:
    monkeypatch.setattr(
        retriever_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(
            qdrant=SimpleNamespace(collection_name="knowledge_base"),
            retrieval=SimpleNamespace(top_k=3, score_threshold=0.0),
        ),
    )
    monkeypatch.setattr(retriever_module, "get_qdrant_client", lambda: object())
    monkeypatch.setattr(retriever_module, "get_embedding_model", lambda: object())

    retriever = retriever_module.KnowledgeBaseRetriever()
    seen_queries: list[tuple[str, list[str] | None, int | None]] = []
    monkeypatch.setattr(
        retriever_module,
        "search_keyword_documents",
        lambda query, thread_id=None, user_id=None, doc_ids=None, top_k=None: seen_queries.append((query, doc_ids, top_k))
        or [
            {
                "content": _long_text("民国财政史料"),
                "score": 1.0,
                "filename": "global.md",
                "source": "global.md",
                "metadata": {
                    "scope": "global",
                    "source_kind": "global_document",
                    "doc_id": "global-doc",
                    "title": "民国财政史料",
                },
            }
        ],
    )

    results = retriever.search("民国时期财政有什么变化", thread_id="thread-1", user_id="user-1")

    assert seen_queries == [("民国时期财政有什么变化", [], 3)]
    assert results[0]["matched_queries"] == ["关键词检索"]


def test_retriever_search_qdrant_filters_short_fragments(monkeypatch) -> None:
    monkeypatch.setattr(
        retriever_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(
            qdrant=SimpleNamespace(collection_name="knowledge_base"),
            retrieval=SimpleNamespace(top_k=3, score_threshold=0.0),
        ),
    )
    monkeypatch.setattr(retriever_module, "get_qdrant_client", lambda: object())
    monkeypatch.setattr(retriever_module, "get_embedding_model", lambda: object())

    retriever = retriever_module.KnowledgeBaseRetriever()
    monkeypatch.setattr(
        retriever,
        "_search_collection",
        lambda collection_name, query, doc_ids=None, top_k=None: [
            {
                "content": "張之洞全集+-",
                "score": 0.91,
                "filename": "bad.pdf",
                "source": "bad",
                "metadata": {
                    "scope": "global",
                    "doc_id": "bad-doc",
                    "title": "坏结果",
                    "line_start": 5,
                    "line_end": 5,
                },
            },
            {
                "content": _long_text("张之洞曾任湖广总督，此段包含较完整的人物经历与官职信息。"),
                "score": 0.75,
                "filename": "good.pdf",
                "source": "good",
                "metadata": {
                    "scope": "global",
                    "doc_id": "good-doc",
                    "title": "好结果",
                    "line_start": 100,
                    "line_end": 104,
                },
            },
        ],
    )

    results = retriever.search_qdrant("张之洞 生平 官职 总督", doc_ids=["good-doc"], top_k=3)

    assert len(results) == 1
    assert results[0]["metadata"]["doc_id"] == "good-doc"


def test_retriever_uses_keyword_search_with_doc_ids(monkeypatch) -> None:
    monkeypatch.setattr(
        retriever_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(
            qdrant=SimpleNamespace(collection_name="knowledge_base"),
            retrieval=SimpleNamespace(top_k=3, score_threshold=0.0),
        ),
    )
    monkeypatch.setattr(
        retriever_module,
        "get_qdrant_client",
        lambda: (_ for _ in ()).throw(AssertionError("vector runtime should stay lazy in keyword mode")),
    )
    monkeypatch.setattr(
        retriever_module,
        "get_embedding_model",
        lambda: (_ for _ in ()).throw(AssertionError("embeddings should stay lazy in keyword mode")),
    )

    retriever = retriever_module.KnowledgeBaseRetriever()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        retriever_module,
        "search_keyword_documents",
        lambda query, thread_id=None, user_id=None, doc_ids=None, top_k=None: captured.update(
            {
                "query": query,
                "thread_id": thread_id,
                "user_id": user_id,
                "doc_ids": doc_ids,
                "top_k": top_k,
            }
        )
        or [
            {
                "content": _long_text("结果"),
                "score": 3.0,
                "filename": "global.md",
                "source": "global",
                "metadata": {
                    "scope": "global",
                    "source_kind": "global_document",
                    "doc_id": "global-doc",
                },
            }
        ],
    )

    results = retriever.search("清代末期财政情况", user_id="user-1", doc_ids=["global-doc"], scopes=["global"])

    assert captured["query"] == "清代末期财政情况"
    assert captured["thread_id"] is None
    assert captured["user_id"] is None
    assert captured["doc_ids"] == ["global-doc"]
    assert captured["top_k"] == 6
    assert results[0]["matched_query"] == "关键词检索"
    assert results[0]["query_variant"] == "清代末期财政情况"


def test_retriever_keeps_minimum_keyword_limit_when_doc_ids_are_provided(monkeypatch) -> None:
    monkeypatch.setattr(
        retriever_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(
            qdrant=SimpleNamespace(collection_name="knowledge_base"),
            retrieval=SimpleNamespace(top_k=3, score_threshold=0.0),
        ),
    )
    monkeypatch.setattr(retriever_module, "get_qdrant_client", lambda: object())
    monkeypatch.setattr(retriever_module, "get_embedding_model", lambda: object())

    retriever = retriever_module.KnowledgeBaseRetriever()
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        retriever_module,
        "search_keyword_documents",
        lambda query, thread_id=None, user_id=None, doc_ids=None, top_k=None: captured.update(
            {"doc_ids": doc_ids, "top_k": top_k}
        )
        or [],
    )

    retriever.search(
        "清代财政变迁",
        thread_id="thread-1",
        user_id="user-1",
        doc_ids=["uk-1", "thread-book.pdf", "global/book.md"],
        scopes=["user", "thread", "global"],
    )

    assert captured["doc_ids"] == ["uk-1", "thread-book.pdf", "global/book.md"]
    assert captured["top_k"] == 6


def test_retriever_converts_folder_paths_to_doc_ids(monkeypatch) -> None:
    monkeypatch.setattr(
        retriever_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(
            qdrant=SimpleNamespace(collection_name="knowledge_base"),
            retrieval=SimpleNamespace(top_k=3, score_threshold=0.0),
        ),
    )
    monkeypatch.setattr(retriever_module, "get_qdrant_client", lambda: object())
    monkeypatch.setattr(retriever_module, "get_embedding_model", lambda: object())
    monkeypatch.setattr(
        retriever_module,
        "list_book_catalog",
        lambda thread_id=None, user_id=None, **kwargs: [
            BookCatalogEntry(
                doc_id="uk_qing",
                title="清代财政",
                filename="qing.md",
                scope="user",
                source_path="/tmp/qing.md",
                source_url="/tmp/qing.md",
                original_url=None,
                preview="",
                search_text="清代 财政",
                search_tokens=["清代", "财政"],
                type="user",
                folder_path="财政史/清代",
            ),
            BookCatalogEntry(
                doc_id="uk_song",
                title="宋代财政",
                filename="song.md",
                scope="user",
                source_path="/tmp/song.md",
                source_url="/tmp/song.md",
                original_url=None,
                preview="",
                search_text="宋代 财政",
                search_tokens=["宋代", "财政"],
                type="user",
                folder_path="财政史/宋代",
            ),
        ],
    )

    retriever = retriever_module.KnowledgeBaseRetriever()
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        retriever_module,
        "search_keyword_documents",
        lambda query, thread_id=None, user_id=None, doc_ids=None, top_k=None: captured.update(
            {
                "query": query,
                "thread_id": thread_id,
                "user_id": user_id,
                "doc_ids": doc_ids,
                "top_k": top_k,
            }
        )
        or [],
    )

    retriever.search(
        "财政史",
        user_id="user-1",
        scopes=["user"],
        folder_paths=["财政史/清代"],
    )

    assert captured["query"] == "财政史"
    assert captured["thread_id"] is None
    assert captured["user_id"] == "user-1"
    assert captured["doc_ids"] == ["uk_qing"]
    assert captured["top_k"] == 6


def test_retriever_filters_short_noise_for_broad_queries(monkeypatch) -> None:
    monkeypatch.setattr(
        retriever_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(
            qdrant=SimpleNamespace(collection_name="knowledge_base"),
            retrieval=SimpleNamespace(top_k=3, score_threshold=0.0),
        ),
    )
    monkeypatch.setattr(retriever_module, "get_qdrant_client", lambda: object())
    monkeypatch.setattr(retriever_module, "get_embedding_model", lambda: object())

    retriever = retriever_module.KnowledgeBaseRetriever()

    monkeypatch.setattr(
        retriever_module,
        "search_keyword_documents",
        lambda *args, **kwargs: [
            {
                "content": "[盛宣怀]",
                "score": 1.0,
                "filename": "global.md",
                "source": "global",
                "page": None,
                "source_type": "structured",
                "metadata": {"scope": "global", "source_kind": "global_document", "doc_id": "global-doc"},
            }
        ],
    )

    results = retriever.search("盛宣怀 生平", scopes=["global"])

    assert results == []


def test_retriever_keeps_query_unchanged_in_keyword_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        retriever_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(
            qdrant=SimpleNamespace(collection_name="knowledge_base"),
            retrieval=SimpleNamespace(top_k=3, score_threshold=0.0),
        ),
    )
    monkeypatch.setattr(retriever_module, "get_qdrant_client", lambda: object())
    monkeypatch.setattr(retriever_module, "get_embedding_model", lambda: object())

    retriever = retriever_module.KnowledgeBaseRetriever()
    seen_queries: list[str] = []
    monkeypatch.setattr(
        retriever_module,
        "search_keyword_documents",
        lambda query, **kwargs: seen_queries.append(query)
        or [
            {
                "content": _long_text("盛宣怀原文"),
                "score": 2.0,
                "filename": "global.md",
                "source": "global",
                "metadata": {"scope": "global", "source_kind": "global_document", "doc_id": "global-doc"},
            }
        ],
    )

    results = retriever.search("盛宣怀 第300页原文", scopes=["global"])

    assert len(results) == 1
    assert seen_queries == ["盛宣怀 第300页原文"]


def test_search_collection_retries_without_threshold_when_first_pass_is_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        retriever_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(
            qdrant=SimpleNamespace(collection_name="knowledge_base"),
            retrieval=SimpleNamespace(top_k=3, score_threshold=0.3),
        ),
    )
    monkeypatch.setattr(retriever_module, "get_qdrant_client", lambda: object())
    monkeypatch.setattr(retriever_module, "get_embedding_model", lambda: object())

    calls: list[dict[str, object]] = []

    class _Doc:
        def __init__(self) -> None:
            self.page_content = "找回来的结果"
            self.metadata = {"title": "史料", "doc_id": "global-doc", "source": "global.md"}

    class _Store:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def similarity_search_with_score(self, query, k, filter=None, score_threshold=None):
            calls.append({"query": query, "k": k, "score_threshold": score_threshold, "filter": filter})
            if score_threshold == 0.3:
                return []
            return [(_Doc(), 0.12)]

    monkeypatch.setattr(retriever_module, "QdrantVectorStore", _Store)

    retriever = retriever_module.KnowledgeBaseRetriever()
    results = retriever._search_collection("knowledge_base", "民国时期财政状况", doc_ids=["global-doc"], top_k=4)

    assert len(calls) == 2
    assert calls[0]["score_threshold"] == 0.3
    assert calls[1]["score_threshold"] == 0.0
    assert results[0]["content"] == "找回来的结果"


def test_lexical_candidate_documents_respect_doc_ids_for_user_and_thread(monkeypatch) -> None:
    user_docs = [
        {"doc_id": "uk_hit", "scope": "user"},
        {"doc_id": "uk_skip", "scope": "user"},
    ]
    thread_docs = [
        {"doc_id": "thread_hit.md", "scope": "thread"},
        {"doc_id": "thread_skip.md", "scope": "thread"},
    ]
    global_docs = [
        {"doc_id": "global-hit", "scope": "global"},
        {"doc_id": "global-skip", "scope": "global"},
    ]

    monkeypatch.setattr(
        "src.community.knowledge_base.lexical_search._iter_user_documents",
        lambda user_id, doc_ids=None: (doc for doc in user_docs if not doc_ids or doc["doc_id"] in doc_ids),
    )
    monkeypatch.setattr(
        "src.community.knowledge_base.lexical_search._iter_thread_documents",
        lambda thread_id, doc_ids=None: (doc for doc in thread_docs if not doc_ids or doc["doc_id"] in doc_ids),
    )
    monkeypatch.setattr(
        "src.community.knowledge_base.lexical_search._iter_global_documents",
        lambda doc_ids=None: (doc for doc in global_docs if not doc_ids or doc["doc_id"] in doc_ids),
    )

    from src.community.knowledge_base.lexical_search import _iter_candidate_documents

    documents = list(
        _iter_candidate_documents(
            thread_id="thread-1",
            user_id="user-1",
            doc_ids=["uk_hit", "thread_hit.md", "global-hit"],
            scopes=["user", "thread", "global"],
        )
    )

    assert [doc["doc_id"] for doc in documents] == ["uk_hit", "thread_hit.md", "global-hit"]


def test_lexical_search_documents_surfaces_exact_keywords_from_structured_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        lexical_search_module,
        "_iter_candidate_documents",
        lambda thread_id, user_id, doc_ids=None, scopes=None: iter(
            [
                {
                    "doc_id": "global-hit",
                    "title": "财政史",
                    "filename": "finance.md",
                    "scope": "global",
                    "source": "/tmp/finance.structured.json",
                    "payload": {
                        "pages": [
                            {
                                "page_no": 8,
                                "pdf_page_no": 10,
                                "book_page_no": 8,
                                "page_number_source": "book",
                                "paragraphs": [
                                    {
                                        "paragraph_no": 2,
                                        "paragraph_no_in_doc": 22,
                                        "line_start": 100,
                                        "line_end": 106,
                                        "text": "本页明确写到统税清册由财政部门统一造报。",
                                    }
                                ],
                            }
                        ]
                    },
                }
            ]
        ),
    )

    results = lexical_search_module.lexical_search_documents(
        "统税清册",
        scopes=["global"],
        top_k=3,
    )

    assert len(results) == 1
    assert results[0]["match_type"] == "exact_keyword"
    assert "统税清册" in results[0]["matched_keywords"]
    assert results[0]["metadata"]["page_no"] == 8


def test_retriever_preserves_matched_keywords_from_keyword_results(monkeypatch) -> None:
    monkeypatch.setattr(
        retriever_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(
            qdrant=SimpleNamespace(collection_name="knowledge_base"),
            retrieval=SimpleNamespace(top_k=3, score_threshold=0.0),
        ),
    )
    monkeypatch.setattr(retriever_module, "get_qdrant_client", lambda: object())
    monkeypatch.setattr(retriever_module, "get_embedding_model", lambda: object())

    retriever = retriever_module.KnowledgeBaseRetriever()
    monkeypatch.setattr(
        retriever_module,
        "search_keyword_documents",
        lambda *args, **kwargs: [
            {
                "content": "本页明确写到统税清册由财政部门统一造报。",
                "score": 0.88,
                "matched_keywords": ["统税清册"],
                "match_type": "exact_keyword",
                "filename": "finance.md",
                "source": "/tmp/finance.structured.json",
                "page": None,
                "source_type": "structured",
                "collection_name": "lexical_fallback",
                "metadata": {
                    "scope": "global",
                    "source_kind": "global_document",
                    "doc_id": "global-hit",
                    "title": "财政史",
                    "page_no": 8,
                    "pdf_page_no": 10,
                    "paragraph_no": 2,
                },
            }
        ],
    )

    results = retriever.search("统税清册", scopes=["global"])

    assert len(results) == 1
    assert results[0]["matched_keywords"] == ["统税清册"]


def test_get_qdrant_client_uses_configured_server_timeout(monkeypatch) -> None:
    captured = {}

    class _Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        retriever_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(
            qdrant=SimpleNamespace(
                mode="server",
                url="http://qdrant.internal:6333",
                api_key="secret",
                request_timeout=3600,
            )
        ),
    )
    monkeypatch.setattr(retriever_module, "QdrantClient", _Client)

    retriever_module.get_qdrant_client()

    assert captured == {
        "url": "http://qdrant.internal:6333",
        "api_key": "secret",
        "timeout": 3600,
    }


def test_user_knowledge_router_upload_and_import(tmp_path, monkeypatch) -> None:
    paths = Paths(tmp_path)
    monkeypatch.setattr(paths_module, "_paths", paths)
    paths.ensure_user_knowledge_dirs("user_1")

    global_docs_dir = tmp_path / "knowledge" / "docs"
    global_docs_dir.mkdir(parents=True)
    (global_docs_dir / "global-book.md").write_text("# Global\ncontent", encoding="utf-8")

    monkeypatch.setattr(
        user_knowledge_router,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(
            docs_path=str(global_docs_dir),
            qdrant=SimpleNamespace(collection_name="knowledge_base"),
        ),
    )
    monkeypatch.setattr(user_knowledge_router, "_process_user_record_ocr", lambda user_id, record_id: None)
    monkeypatch.setattr(user_knowledge_router, "mark_user_records_indexed", lambda user_id: None)
    monkeypatch.setattr(user_knowledge_router, "get_qdrant_client", lambda: SimpleNamespace(get_collection=lambda name: SimpleNamespace(points_count=1)))

    app = FastAPI()
    app.include_router(user_knowledge_router.router)
    client = TestClient(app)

    upload_response = client.post(
        "/api/users/user_1/knowledge/upload",
        files={"files": ("notes.md", b"# Notes\npersonal", "text/markdown")},
    )
    assert upload_response.status_code == 200
    assert upload_response.json()["records"][0]["filename"] == "notes.md"
    assert upload_response.json()["records"][0]["parse_status"] == "queued_ocr"

    import_response = client.post(
        "/api/users/user_1/knowledge/import-from-global",
        json={"filename": "global-book.md"},
    )
    assert import_response.status_code == 200
    assert import_response.json()["record"]["source_kind"] == "import_ref"

    list_response = client.get("/api/users/user_1/knowledge/list")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["count"] == 2


def test_user_knowledge_router_reindex_and_reparse_queue_background_jobs(tmp_path, monkeypatch) -> None:
    paths = Paths(tmp_path)
    monkeypatch.setattr(paths_module, "_paths", paths)
    paths.ensure_user_knowledge_dirs("user_1")

    source_path = paths.user_knowledge_docs_dir("user_1") / "notes.md"
    source_path.write_text("# Notes\ncontent", encoding="utf-8")
    structured_path = paths.user_knowledge_ingestion_dir("user_1") / "notes.md.structured.json"
    structured_path.write_text("{}", encoding="utf-8")

    record = user_store_module.build_user_upload_record(
        user_id="user_1",
        source_filename="notes.md",
        size=12,
        content_type="text/markdown",
    )
    record["parse_status"] = "indexed"
    record["structured_filename"] = structured_path.name
    record["structured_path"] = str(structured_path)
    record["index_target_filename"] = structured_path.name
    record["index_target_path"] = str(structured_path)
    user_store_module.save_user_record("user_1", record)

    embedding_calls: list[tuple[str, str]] = []
    ocr_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        user_knowledge_router,
        "_process_user_record_embedding",
        lambda user_id, record_id: embedding_calls.append((user_id, record_id)),
    )
    monkeypatch.setattr(
        user_knowledge_router,
        "_process_user_record_ocr",
        lambda user_id, record_id: ocr_calls.append((user_id, record_id)),
    )

    app = FastAPI()
    app.include_router(user_knowledge_router.router)
    client = TestClient(app)

    reindex_response = client.post(f"/api/users/user_1/knowledge/{record['id']}/reindex")
    assert reindex_response.status_code == 200
    assert embedding_calls == [("user_1", str(record["id"]))]

    queued_record = user_store_module.load_user_record("user_1", str(record["id"]))
    assert queued_record is not None
    assert queued_record["parse_status"] == "queued_embedding"

    reparse_response = client.post(f"/api/users/user_1/knowledge/{record['id']}/reparse")
    assert reparse_response.status_code == 409

    queued_record["parse_status"] = "indexed"
    user_store_module.save_user_record("user_1", queued_record)

    reparse_response = client.post(f"/api/users/user_1/knowledge/{record['id']}/reparse")
    assert reparse_response.status_code == 200
    assert ocr_calls == [("user_1", str(record["id"]))]

    reparsed_record = user_store_module.load_user_record("user_1", str(record["id"]))
    assert reparsed_record is not None
    assert reparsed_record["parse_status"] == "queued_ocr"


def test_user_knowledge_router_returns_derived_editor_content(tmp_path, monkeypatch) -> None:
    paths = Paths(tmp_path)
    monkeypatch.setattr(paths_module, "_paths", paths)
    paths.ensure_user_knowledge_dirs("user_1")

    record = user_store_module.build_user_derived_record(
        user_id="user_1",
        source_kind="excerpt",
        title="盐税摘录",
        source_filename="uk_excerpt.md",
        size=0,
        origin_scope="global",
        origin_doc_id="global-book",
        origin_filename="global-book.pdf",
        origin_anchor={
            "pdf_page_no": 12,
            "paragraph_no": 3,
            "text": "这是原文段落",
        },
    )
    user_store_module.persist_user_text_document(
        "user_1",
        "uk_excerpt.md",
        "# 盐税摘录\n\n来源：global-book.pdf\n定位：PDF 第 12 页 · 第 3 段\n\n## 原文摘录\n\n> 这是原文段落\n\n## 我的摘抄笔记\n\n这是我的笔记\n",
    )
    structured_path = paths.user_knowledge_ingestion_dir("user_1") / "uk_excerpt.md.structured.json"
    structured_path.write_text("{}", encoding="utf-8")
    record["parse_status"] = "indexed"
    record["structured_filename"] = structured_path.name
    record["structured_path"] = str(structured_path)
    record["index_target_filename"] = structured_path.name
    record["index_target_path"] = str(structured_path)
    user_store_module.save_user_record("user_1", record)

    app = FastAPI()
    app.include_router(user_knowledge_router.router)
    client = TestClient(app)

    response = client.get(f"/api/users/user_1/knowledge/{record['id']}/content")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "derived"
    assert payload["editable"] is True
    assert payload["locked_excerpt"] == "这是原文段落"
    assert payload["editable_content"] == "这是我的笔记"
    assert payload["location_label"] == "PDF 第 12 页 · 第 3 段"


def test_user_knowledge_router_updates_text_content_and_reindexes(tmp_path, monkeypatch) -> None:
    paths = Paths(tmp_path)
    monkeypatch.setattr(paths_module, "_paths", paths)
    paths.ensure_user_knowledge_dirs("user_1")

    record = user_store_module.build_user_derived_record(
        user_id="user_1",
        source_kind="excerpt",
        title="旧标题",
        source_filename="uk_excerpt.md",
        size=0,
        origin_scope="global",
        origin_doc_id="global-book",
        origin_filename="global-book.pdf",
        origin_anchor={
            "pdf_page_no": 9,
            "paragraph_no": 1,
            "text": "锁定原文",
        },
    )
    user_store_module.persist_user_text_document(
        "user_1",
        "uk_excerpt.md",
        "# 旧标题\n\n来源：global-book.pdf\n定位：PDF 第 9 页 · 第 1 段\n\n## 原文摘录\n\n> 锁定原文\n\n## 我的摘抄笔记\n\n旧内容\n",
    )
    structured_path = paths.user_knowledge_ingestion_dir("user_1") / "uk_excerpt.md.structured.json"
    structured_path.write_text("{}", encoding="utf-8")
    record["parse_status"] = "indexed"
    record["structured_filename"] = structured_path.name
    record["structured_path"] = str(structured_path)
    record["index_target_filename"] = structured_path.name
    record["index_target_path"] = str(structured_path)
    user_store_module.save_user_record("user_1", record)

    upsert_calls: list[tuple[str, list[str]]] = []
    indexed_calls: list[str] = []

    monkeypatch.setattr(
        user_knowledge_router,
        "upsert_user_knowledge_records",
        lambda user_id, record_ids: upsert_calls.append((user_id, record_ids)) or 1,
    )
    monkeypatch.setattr(
        user_knowledge_router,
        "mark_user_records_indexed",
        lambda user_id, record_ids=None: indexed_calls.append(user_id),
    )

    app = FastAPI()
    app.include_router(user_knowledge_router.router)
    client = TestClient(app)

    response = client.put(
        f"/api/users/user_1/knowledge/{record['id']}/content",
        json={"title": "新标题", "content": "新笔记"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "新标题"
    assert payload["editable_content"] == "新笔记"
    assert payload["locked_excerpt"] == "锁定原文"
    assert upsert_calls == [("user_1", [str(record["id"])])]
    assert indexed_calls == ["user_1"]

    updated_record = user_store_module.load_user_record("user_1", str(record["id"]))
    assert updated_record is not None
    assert updated_record["title"] == "新标题"

    saved_content = (paths.user_knowledge_docs_dir("user_1") / "uk_excerpt.md").read_text(encoding="utf-8")
    assert "## 原文摘录" in saved_content
    assert "> 锁定原文" in saved_content
    assert "## 我的摘抄笔记" in saved_content
    assert "新笔记" in saved_content


def test_user_knowledge_router_creates_plain_note_and_returns_text_editor(tmp_path, monkeypatch) -> None:
    paths = Paths(tmp_path)
    monkeypatch.setattr(paths_module, "_paths", paths)
    paths.ensure_user_knowledge_dirs("user_1")

    upsert_calls: list[tuple[str, list[str]]] = []
    indexed_calls: list[str] = []

    monkeypatch.setattr(
        user_knowledge_router,
        "upsert_user_knowledge_records",
        lambda user_id, record_ids: upsert_calls.append((user_id, record_ids)) or 1,
    )
    monkeypatch.setattr(
        user_knowledge_router,
        "mark_user_records_indexed",
        lambda user_id, record_ids=None: indexed_calls.append(user_id),
    )

    app = FastAPI()
    app.include_router(user_knowledge_router.router)
    client = TestClient(app)

    create_response = client.post(
        "/api/users/user_1/knowledge/derived",
        json={"title": "会议记录", "content": "", "source_kind": "note"},
    )

    assert create_response.status_code == 200
    payload = create_response.json()
    assert payload["record"]["source_kind"] == "note"
    assert upsert_calls == [("user_1", [payload["record"]["id"]])]
    assert indexed_calls == ["user_1"]

    record_id = payload["record"]["id"]
    content_response = client.get(f"/api/users/user_1/knowledge/{record_id}/content")

    assert content_response.status_code == 200
    content_payload = content_response.json()
    assert content_payload["mode"] == "text"
    assert content_payload["editable"] is True
    assert content_payload["title"] == "会议记录"
    assert content_payload["editable_content"] == ""

    saved_content = (paths.user_knowledge_docs_dir("user_1") / f"{record_id}.md").read_text(encoding="utf-8")
    assert saved_content == "# 会议记录\n"


def test_user_knowledge_router_appends_excerpt_to_existing_note(tmp_path, monkeypatch) -> None:
    paths = Paths(tmp_path)
    monkeypatch.setattr(paths_module, "_paths", paths)
    paths.ensure_user_knowledge_dirs("user_1")

    record = user_store_module.build_user_derived_record(
        user_id="user_1",
        source_kind="note",
        title="读书笔记",
        source_filename="uk_note.md",
        size=0,
        origin_scope=None,
        origin_doc_id=None,
        origin_filename=None,
    )
    user_store_module.persist_user_text_document(
        "user_1",
        "uk_note.md",
        "# 读书笔记\n\n已有内容\n",
    )
    structured_path = paths.user_knowledge_ingestion_dir("user_1") / "uk_note.md.structured.json"
    structured_path.write_text("{}", encoding="utf-8")
    record["parse_status"] = "indexed"
    record["structured_filename"] = structured_path.name
    record["structured_path"] = str(structured_path)
    record["index_target_filename"] = structured_path.name
    record["index_target_path"] = str(structured_path)
    user_store_module.save_user_record("user_1", record)

    upsert_calls: list[tuple[str, list[str]]] = []
    indexed_calls: list[str] = []

    monkeypatch.setattr(
        user_knowledge_router,
        "upsert_user_knowledge_records",
        lambda user_id, record_ids: upsert_calls.append((user_id, record_ids)) or 1,
    )
    monkeypatch.setattr(
        user_knowledge_router,
        "mark_user_records_indexed",
        lambda user_id, record_ids=None: indexed_calls.append(user_id),
    )

    app = FastAPI()
    app.include_router(user_knowledge_router.router)
    client = TestClient(app)

    response = client.post(
        f"/api/users/user_1/knowledge/{record['id']}/append-excerpt",
        json={
            "excerpt_text": "这是新摘录\n第二行",
            "origin_filename": "global-book.pdf",
            "origin_anchor": {
                "pdf_page_no": 12,
                "paragraph_no": 3,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["record"]["id"] == record["id"]
    assert upsert_calls == [("user_1", [str(record["id"])])]
    assert indexed_calls == ["user_1"]

    saved_content = (paths.user_knowledge_docs_dir("user_1") / "uk_note.md").read_text(encoding="utf-8")
    assert saved_content.startswith("# 读书笔记\n\n已有内容\n\n## 原文摘录\n")
    assert "来源：global-book.pdf" in saved_content
    assert "定位：PDF 第 12 页 · 第 3 段" in saved_content
    assert "> 这是新摘录\n> 第二行" in saved_content


def test_user_knowledge_router_appends_excerpt_to_existing_derived_note(tmp_path, monkeypatch) -> None:
    paths = Paths(tmp_path)
    monkeypatch.setattr(paths_module, "_paths", paths)
    paths.ensure_user_knowledge_dirs("user_1")

    record = user_store_module.build_user_derived_record(
        user_id="user_1",
        source_kind="excerpt",
        title="盐税摘录",
        source_filename="uk_excerpt.md",
        size=0,
        origin_scope="global",
        origin_doc_id="global-book",
        origin_filename="global-book.pdf",
        origin_anchor={
            "pdf_page_no": 9,
            "paragraph_no": 1,
            "text": "锁定原文",
        },
    )
    user_store_module.persist_user_text_document(
        "user_1",
        "uk_excerpt.md",
        "# 盐税摘录\n\n来源：global-book.pdf\n定位：PDF 第 9 页 · 第 1 段\n\n## 原文摘录\n\n> 锁定原文\n\n## 我的摘抄笔记\n\n旧内容\n",
    )
    structured_path = paths.user_knowledge_ingestion_dir("user_1") / "uk_excerpt.md.structured.json"
    structured_path.write_text("{}", encoding="utf-8")
    record["parse_status"] = "indexed"
    record["structured_filename"] = structured_path.name
    record["structured_path"] = str(structured_path)
    record["index_target_filename"] = structured_path.name
    record["index_target_path"] = str(structured_path)
    user_store_module.save_user_record("user_1", record)

    upsert_calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        user_knowledge_router,
        "upsert_user_knowledge_records",
        lambda user_id, record_ids: upsert_calls.append((user_id, record_ids)) or 1,
    )

    app = FastAPI()
    app.include_router(user_knowledge_router.router)
    client = TestClient(app)

    response = client.post(
        f"/api/users/user_1/knowledge/{record['id']}/append-excerpt",
        json={
            "excerpt_text": "追加摘录内容",
            "origin_filename": "another-book.pdf",
            "origin_anchor": {
                "pdf_page_no": 12,
                "paragraph_no": 3,
            },
        },
    )

    assert response.status_code == 200
    assert upsert_calls == [("user_1", [str(record["id"])])]

    saved_content = (paths.user_knowledge_docs_dir("user_1") / "uk_excerpt.md").read_text(encoding="utf-8")
    assert "## 原文摘录" in saved_content
    assert "> 锁定原文" in saved_content
    assert "## 我的摘抄笔记" in saved_content
    assert "旧内容" in saved_content
    assert "来源：another-book.pdf" in saved_content
    assert "定位：PDF 第 12 页 · 第 3 段" in saved_content
    assert "> 追加摘录内容" in saved_content


def test_user_knowledge_router_delete_tolerates_non_file_artifacts(tmp_path, monkeypatch) -> None:
    paths = Paths(tmp_path)
    monkeypatch.setattr(paths_module, "_paths", paths)
    paths.ensure_user_knowledge_dirs("user_1")

    record = user_store_module.build_user_derived_record(
        user_id="user_1",
        source_kind="note",
        title="待删除笔记",
        source_filename="uk_note.md",
        size=0,
        origin_scope=None,
        origin_doc_id=None,
        origin_filename=None,
    )
    record["source_path"] = str(paths.user_knowledge_docs_dir("user_1"))
    record["structured_path"] = str(paths.user_knowledge_ingestion_dir("user_1"))
    user_store_module.save_user_record("user_1", record)

    deleted_calls: list[tuple[str, list[str]]] = []
    indexed_calls: list[str] = []
    monkeypatch.setattr(
        user_knowledge_router,
        "delete_user_knowledge_records",
        lambda user_id, record_ids: deleted_calls.append((user_id, record_ids)),
    )
    monkeypatch.setattr(user_knowledge_router, "mark_user_records_indexed", lambda user_id: indexed_calls.append(user_id))

    app = FastAPI()
    app.include_router(user_knowledge_router.router)
    client = TestClient(app)

    response = client.delete(f"/api/users/user_1/knowledge/{record['id']}")

    assert response.status_code == 200
    assert user_store_module.load_user_record("user_1", str(record["id"])) is None
    assert deleted_calls == [("user_1", [str(record["id"])])]
    assert indexed_calls == ["user_1"]
