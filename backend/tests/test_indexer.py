from pathlib import Path
from threading import Lock
from time import sleep
from types import SimpleNamespace

import httpx
from langchain_core.documents import Document

from src.community.knowledge_base import indexer


def _set_chunking_config(monkeypatch, chunk_size: int, chunk_overlap: int) -> None:
    monkeypatch.setattr(
        indexer,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(
            chunking=SimpleNamespace(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
        ),
    )


def test_build_chunks_keeps_structured_paragraph_as_single_chunk_when_short(monkeypatch) -> None:
    _set_chunking_config(monkeypatch, chunk_size=80, chunk_overlap=10)

    document = Document(
        page_content="这是一个较短的结构化段落。",
        metadata={
            "source": "/tmp/demo.structured.json",
            "source_type": "structured",
            "page_no": 12,
            "pdf_page_no": 12,
            "paragraph_id": "page-12-p3",
            "paragraph_no": 3,
            "paragraph_no_in_doc": 27,
            "line_start": 101,
            "line_end": 102,
            "bbox": {"x": 1.0, "y": 2.0, "width": 3.0, "height": 4.0},
            "bbox_source": "mineru_grpc",
        },
    )

    chunks = indexer._build_chunks([document], scope="global", thread_id=None)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.page_content == document.page_content
    assert chunk.metadata["paragraph_id"] == "page-12-p3"
    assert chunk.metadata["paragraph_no"] == 3
    assert chunk.metadata["paragraph_no_in_doc"] == 27
    assert chunk.metadata["line_start"] == 101
    assert chunk.metadata["line_end"] == 102
    assert chunk.metadata["paragraph_chunk_index"] is None
    assert chunk.metadata["paragraph_chunk_count"] is None


def test_build_chunks_splits_long_structured_paragraph_but_preserves_metadata(monkeypatch) -> None:
    _set_chunking_config(monkeypatch, chunk_size=20, chunk_overlap=5)

    document = Document(
        page_content="第一部分内容需要被拆分。第二部分内容也需要被拆分。第三部分继续延续。第四部分仍然要保留定位。",
        metadata={
            "source": "/tmp/demo.structured.json",
            "source_type": "structured",
            "page_no": 4,
            "pdf_page_no": 4,
            "paragraph_id": "page-4-p1",
            "paragraph_no": 1,
            "paragraph_no_in_doc": 8,
            "line_start": 31,
            "line_end": 34,
            "bbox_source": "mineru_grpc",
        },
    )

    chunks = indexer._build_chunks([document], scope="global", thread_id=None)

    assert len(chunks) > 1
    assert [chunk.metadata["paragraph_chunk_index"] for chunk in chunks] == list(
        range(1, len(chunks) + 1)
    )
    assert [chunk.metadata["paragraph_chunk_count"] for chunk in chunks] == [len(chunks)] * len(chunks)
    for chunk in chunks:
        assert chunk.metadata["source_type"] == "structured"
        assert chunk.metadata["paragraph_id"] == "page-4-p1"
        assert chunk.metadata["paragraph_no"] == 1
        assert chunk.metadata["paragraph_no_in_doc"] == 8
        assert chunk.metadata["line_start"] == 31
        assert chunk.metadata["line_end"] == 34
        assert len(chunk.page_content) <= 20


def test_build_chunks_merges_adjacent_short_structured_paragraphs_to_reach_min_chars(monkeypatch) -> None:
    _set_chunking_config(monkeypatch, chunk_size=500, chunk_overlap=0)

    documents = [
        Document(
            page_content="盛宣怀早年参与洋务事务。",
            metadata={
                "source": "/tmp/demo.structured.json",
                "source_type": "structured",
                "page_no": 2,
                "pdf_page_no": 2,
                "paragraph_id": "page-2-p1",
                "paragraph_no": 1,
                "paragraph_no_in_doc": 11,
                "line_start": 1,
                "line_end": 2,
                "bbox": {"x": 1.0, "y": 1.0, "width": 10.0, "height": 5.0},
                "bbox_source": "mineru_grpc",
            },
        ),
        Document(
            page_content="随后主持招商局、电报局等实业筹办，并与晚清财政和交通体系改革持续发生联系。",
            metadata={
                "source": "/tmp/demo.structured.json",
                "source_type": "structured",
                "page_no": 2,
                "pdf_page_no": 2,
                "paragraph_id": "page-2-p2",
                "paragraph_no": 2,
                "paragraph_no_in_doc": 12,
                "line_start": 3,
                "line_end": 5,
                "bbox": {"x": 2.0, "y": 2.0, "width": 11.0, "height": 6.0},
                "bbox_source": "mineru_grpc",
            },
        ),
        Document(
            page_content="相关奏议也常围绕商办、路矿和电政展开。",
            metadata={
                "source": "/tmp/demo.structured.json",
                "source_type": "structured",
                "page_no": 2,
                "pdf_page_no": 2,
                "paragraph_id": "page-2-p3",
                "paragraph_no": 3,
                "paragraph_no_in_doc": 13,
                "line_start": 6,
                "line_end": 7,
                "bbox": {"x": 3.0, "y": 3.0, "width": 12.0, "height": 7.0},
                "bbox_source": "mineru_grpc",
            },
        ),
    ]

    chunks = indexer._build_chunks(documents, scope="global", thread_id=None)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.page_content == "\n".join(document.page_content for document in documents)
    assert chunk.metadata["paragraph_no"] == 1
    assert chunk.metadata["paragraph_no_in_doc"] == 11
    assert chunk.metadata["paragraph_end_no"] == 3
    assert chunk.metadata["paragraph_end_no_in_doc"] == 13
    assert chunk.metadata["merged_paragraph_count"] == 3
    assert chunk.metadata["line_start"] == 1
    assert chunk.metadata["line_end"] == 7
    assert chunk.metadata["bbox"] is None
    assert chunk.metadata["bbox_source"] == "paragraph_merge"


def test_build_chunks_does_not_merge_structured_paragraphs_across_pages(monkeypatch) -> None:
    _set_chunking_config(monkeypatch, chunk_size=500, chunk_overlap=0)

    documents = [
        Document(
            page_content="第一页短段。",
            metadata={
                "source": "/tmp/demo.structured.json",
                "source_type": "structured",
                "page_no": 1,
                "pdf_page_no": 1,
                "paragraph_id": "page-1-p1",
                "paragraph_no": 1,
                "paragraph_no_in_doc": 1,
                "line_start": 1,
                "line_end": 1,
            },
        ),
        Document(
            page_content="第二页短段。",
            metadata={
                "source": "/tmp/demo.structured.json",
                "source_type": "structured",
                "page_no": 2,
                "pdf_page_no": 2,
                "paragraph_id": "page-2-p1",
                "paragraph_no": 1,
                "paragraph_no_in_doc": 2,
                "line_start": 1,
                "line_end": 1,
            },
        ),
    ]

    chunks = indexer._build_chunks(documents, scope="global", thread_id=None)

    assert len(chunks) == 2
    assert [chunk.page_content for chunk in chunks] == ["第一页短段。", "第二页短段。"]


def test_build_chunks_merges_vertical_structured_sentences_in_groups_of_five_when_still_short(monkeypatch) -> None:
    _set_chunking_config(monkeypatch, chunk_size=500, chunk_overlap=0)

    documents = [
        Document(
            page_content=f"第{i}句",
            metadata={
                "source": "/tmp/vertical.structured.json",
                "source_type": "structured",
                "layout_hint": "vertical",
                "page_no": 3,
                "pdf_page_no": 3,
                "paragraph_id": f"page-3-p{i}",
                "paragraph_no": i,
                "paragraph_no_in_doc": i,
                "line_start": i,
                "line_end": i,
            },
        )
        for i in range(1, 8)
    ]

    chunks = indexer._build_chunks(documents, scope="global", thread_id=None)

    assert len(chunks) == 2
    assert chunks[0].page_content == "第1句\n第2句\n第3句\n第4句\n第5句"
    assert chunks[1].page_content == "第6句\n第7句"
    assert chunks[0].metadata["paragraph_no"] == 1
    assert chunks[0].metadata["paragraph_end_no"] == 5
    assert chunks[0].metadata["merged_paragraph_count"] == 5
    assert chunks[0].metadata["line_start"] == 1
    assert chunks[0].metadata["line_end"] == 5
    assert chunks[0].metadata["bbox"] is None
    assert chunks[1].metadata["paragraph_no"] == 6
    assert chunks[1].metadata["paragraph_end_no"] == 7
    assert chunks[1].metadata["merged_paragraph_count"] == 2


def test_build_chunks_merges_vertical_structured_sentences_until_min_chars(monkeypatch) -> None:
    _set_chunking_config(monkeypatch, chunk_size=500, chunk_overlap=0)

    documents = [
        Document(
            page_content=content,
            metadata={
                "source": "/tmp/vertical.structured.json",
                "source_type": "structured",
                "layout_hint": "vertical",
                "page_no": 3,
                "pdf_page_no": 3,
                "paragraph_id": f"page-3-p{i}",
                "paragraph_no": i,
                "paragraph_no_in_doc": i,
                "line_start": i,
                "line_end": i,
            },
        )
        for i, content in enumerate(["甲" * 35, "乙" * 35, "丙" * 35], start=1)
    ]

    chunks = indexer._build_chunks(documents, scope="global", thread_id=None)

    assert len(chunks) == 1
    assert chunks[0].page_content == "\n".join(document.page_content for document in documents)
    assert chunks[0].metadata["paragraph_no"] == 1
    assert chunks[0].metadata["paragraph_end_no"] == 3
    assert chunks[0].metadata["merged_paragraph_count"] == 3
    assert chunks[0].metadata["bbox_source"] == "vertical_sentence_merge"


def test_build_chunks_does_not_merge_long_vertical_structured_sentence(monkeypatch) -> None:
    _set_chunking_config(monkeypatch, chunk_size=500, chunk_overlap=0)

    documents = [
        Document(
            page_content="甲" * 120,
            metadata={
                "source": "/tmp/vertical.structured.json",
                "source_type": "structured",
                "layout_hint": "vertical",
                "page_no": 3,
                "pdf_page_no": 3,
                "paragraph_id": "page-3-p1",
                "paragraph_no": 1,
                "paragraph_no_in_doc": 1,
                "line_start": 1,
                "line_end": 1,
            },
        ),
        Document(
            page_content="乙" * 10,
            metadata={
                "source": "/tmp/vertical.structured.json",
                "source_type": "structured",
                "layout_hint": "vertical",
                "page_no": 3,
                "pdf_page_no": 3,
                "paragraph_id": "page-3-p2",
                "paragraph_no": 2,
                "paragraph_no_in_doc": 2,
                "line_start": 2,
                "line_end": 2,
            },
        ),
    ]

    chunks = indexer._build_chunks(documents, scope="global", thread_id=None)

    assert len(chunks) == 2
    assert chunks[0].page_content == "甲" * 120
    assert chunks[0].metadata.get("merged_paragraph_count") is None
    assert chunks[1].page_content == "乙" * 10
    assert chunks[1].metadata.get("merged_paragraph_count") is None


def test_build_chunks_keeps_horizontal_structured_sentences_unmerged(monkeypatch) -> None:
    _set_chunking_config(monkeypatch, chunk_size=500, chunk_overlap=0)

    documents = [
        Document(
            page_content=f"第{i}句",
            metadata={
                "source": "/tmp/horizontal.structured.json",
                "source_type": "structured",
                "layout_hint": "horizontal",
                "page_no": 1,
                "pdf_page_no": 1,
                "paragraph_id": f"page-1-p{i}",
                "paragraph_no": i,
                "paragraph_no_in_doc": i,
                "line_start": i,
                "line_end": i,
            },
        )
        for i in range(1, 4)
    ]

    chunks = indexer._build_chunks(documents, scope="global", thread_id=None)

    assert len(chunks) == 3
    assert [chunk.page_content for chunk in chunks] == ["第1句", "第2句", "第3句"]


def test_upsert_documents_replaces_doc_ids_without_replacing_collection(monkeypatch) -> None:
    _set_chunking_config(monkeypatch, chunk_size=80, chunk_overlap=0)

    original_document = Document(
        page_content="新的个人知识内容",
        metadata={"source": "/tmp/demo.md", "source_type": "text", "doc_id": "uk_1"},
    )

    monkeypatch.setattr(indexer, "_build_chunks", lambda documents, scope, thread_id: documents)
    monkeypatch.setattr(indexer, "get_embedding_model", lambda: SimpleNamespace(embed_query=lambda text: [0.1, 0.2]))

    deleted_doc_ids: list[list[str]] = []
    ensured_collections: list[str] = []
    added_documents: list[Document] = []

    class _Client:
        def delete_collection(self, *args, **kwargs):
            raise AssertionError("upsert should not replace the full collection")

    class _VectorStore:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def add_documents(self, documents, **kwargs):
            assert kwargs["batch_size"] == indexer.UPSERT_BATCH_SIZE
            added_documents.extend(documents)
            return ["p1"]

    monkeypatch.setattr(indexer, "get_qdrant_client", lambda: _Client())
    monkeypatch.setattr(indexer, "_ensure_collection", lambda client, collection_name, embeddings: ensured_collections.append(collection_name))
    monkeypatch.setattr(indexer, "_delete_points_by_doc_ids", lambda client, collection_name, doc_ids: deleted_doc_ids.append(doc_ids))
    monkeypatch.setattr(indexer, "QdrantVectorStore", _VectorStore)

    result = indexer.upsert_documents(
        [original_document],
        collection_name="knowledge_base__user__u1",
        scope="user",
        replace_doc_ids=["uk_1"],
    )

    assert result == 1
    assert ensured_collections == ["knowledge_base__user__u1"]
    assert deleted_doc_ids == [["uk_1"]]
    assert added_documents == [original_document]


def test_upsert_documents_retries_transient_qdrant_disconnect(monkeypatch) -> None:
    _set_chunking_config(monkeypatch, chunk_size=80, chunk_overlap=0)

    original_document = Document(
        page_content="新的个人知识内容",
        metadata={"source": "/tmp/demo.md", "source_type": "text", "doc_id": "uk_1"},
    )

    monkeypatch.setattr(indexer, "_build_chunks", lambda documents, scope, thread_id: documents)
    monkeypatch.setattr(indexer, "get_embedding_model", lambda: SimpleNamespace(embed_query=lambda text: [0.1, 0.2]))
    sleep_calls: list[float] = []
    monkeypatch.setattr(indexer, "sleep", lambda seconds: sleep_calls.append(seconds))

    deleted_doc_ids: list[list[str]] = []
    ensured_collections: list[str] = []
    attempts: list[list[str]] = []

    class _Client:
        def delete_collection(self, *args, **kwargs):
            raise AssertionError("upsert should not replace the full collection")

    class _VectorStore:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def add_documents(self, documents, **kwargs):
            assert kwargs["batch_size"] == indexer.UPSERT_BATCH_SIZE
            attempts.append(list(kwargs.get("ids") or []))
            if len(attempts) == 1:
                raise indexer.ResponseHandlingException(
                    httpx.RemoteProtocolError("Server disconnected without sending a response.")
                )
            return ["p1"]

    monkeypatch.setattr(indexer, "get_qdrant_client", lambda: _Client())
    monkeypatch.setattr(indexer, "_ensure_collection", lambda client, collection_name, embeddings: ensured_collections.append(collection_name))
    monkeypatch.setattr(indexer, "_delete_points_by_doc_ids", lambda client, collection_name, doc_ids: deleted_doc_ids.append(doc_ids))
    monkeypatch.setattr(indexer, "QdrantVectorStore", _VectorStore)

    result = indexer.upsert_documents(
        [original_document],
        collection_name="knowledge_base__user__u1",
        scope="user",
        replace_doc_ids=["uk_1"],
    )

    assert result == 1
    assert ensured_collections == ["knowledge_base__user__u1"]
    assert deleted_doc_ids == [["uk_1"]]
    assert len(attempts) == 2
    assert attempts[0] == attempts[1]
    assert len(attempts[0]) == 1
    assert sleep_calls == [5.0]


def test_upsert_documents_retries_no_embedding_data(monkeypatch) -> None:
    _set_chunking_config(monkeypatch, chunk_size=80, chunk_overlap=0)

    original_document = Document(
        page_content="新的个人知识内容",
        metadata={"source": "/tmp/demo.md", "source_type": "text", "doc_id": "uk_1"},
    )

    monkeypatch.setattr(indexer, "_build_chunks", lambda documents, scope, thread_id: documents)
    monkeypatch.setattr(indexer, "get_embedding_model", lambda: SimpleNamespace(embed_query=lambda text: [0.1, 0.2]))
    sleep_calls: list[float] = []
    monkeypatch.setattr(indexer, "sleep", lambda seconds: sleep_calls.append(seconds))

    attempts: list[list[str]] = []

    class _Client:
        def delete_collection(self, *args, **kwargs):
            raise AssertionError("upsert should not replace the full collection")

    class _VectorStore:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def add_documents(self, documents, **kwargs):
            attempts.append(list(kwargs.get("ids") or []))
            if len(attempts) < 3:
                raise ValueError("No embedding data received")
            return ["p1"]

    monkeypatch.setattr(indexer, "get_qdrant_client", lambda: _Client())
    monkeypatch.setattr(indexer, "_ensure_collection", lambda client, collection_name, embeddings: None)
    monkeypatch.setattr(indexer, "_delete_points_by_doc_ids", lambda client, collection_name, doc_ids: None)
    monkeypatch.setattr(indexer, "QdrantVectorStore", _VectorStore)

    result = indexer.upsert_documents(
        [original_document],
        collection_name="knowledge_base__user__u1",
        scope="user",
        replace_doc_ids=["uk_1"],
    )

    assert result == 1
    assert len(attempts) == 3
    assert attempts[0] == attempts[1] == attempts[2]
    assert sleep_calls == [5.0, 10.0]


def test_upsert_documents_does_not_retry_non_retryable_error(monkeypatch) -> None:
    _set_chunking_config(monkeypatch, chunk_size=80, chunk_overlap=0)

    original_document = Document(
        page_content="新的个人知识内容",
        metadata={"source": "/tmp/demo.md", "source_type": "text", "doc_id": "uk_1"},
    )

    monkeypatch.setattr(indexer, "_build_chunks", lambda documents, scope, thread_id: documents)
    monkeypatch.setattr(indexer, "get_embedding_model", lambda: SimpleNamespace(embed_query=lambda text: [0.1, 0.2]))
    sleep_calls: list[float] = []
    monkeypatch.setattr(indexer, "sleep", lambda seconds: sleep_calls.append(seconds))

    class _Client:
        def delete_collection(self, *args, **kwargs):
            raise AssertionError("upsert should not replace the full collection")

    class _VectorStore:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def add_documents(self, documents, **kwargs):
            raise ValueError("invalid payload")

    monkeypatch.setattr(indexer, "get_qdrant_client", lambda: _Client())
    monkeypatch.setattr(indexer, "_ensure_collection", lambda client, collection_name, embeddings: None)
    monkeypatch.setattr(indexer, "_delete_points_by_doc_ids", lambda client, collection_name, doc_ids: None)
    monkeypatch.setattr(indexer, "QdrantVectorStore", _VectorStore)

    try:
        indexer.upsert_documents(
            [original_document],
            collection_name="knowledge_base__user__u1",
            scope="user",
            replace_doc_ids=["uk_1"],
        )
    except ValueError as exc:
        assert str(exc) == "invalid payload"
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected invalid payload error to bubble up")

    assert sleep_calls == []


def test_delete_documents_by_doc_ids_uses_filtered_delete(monkeypatch) -> None:
    captured = {}

    class _Client:
        def delete(self, *, collection_name, points_selector, wait):
            captured["collection_name"] = collection_name
            captured["points_selector"] = points_selector
            captured["wait"] = wait

    monkeypatch.setattr(indexer, "get_qdrant_client", lambda: _Client())

    indexer.delete_documents_by_doc_ids("knowledge_base__user__u1", ["uk_1", "uk_2"])

    assert captured["collection_name"] == "knowledge_base__user__u1"
    assert captured["wait"] is True


def test_upsert_global_knowledge_record_resumes_from_checkpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        indexer,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(
            docs_path="/tmp/knowledge/docs",
            qdrant=SimpleNamespace(
                collection_name="knowledge_base",
                upsert_batch_size=64,
                upsert_parallelism=2,
            ),
            chunking=SimpleNamespace(chunk_size=80, chunk_overlap=0),
        ),
    )

    original_document = Document(
        page_content="全局知识内容",
        metadata={"source": "/tmp/demo.structured.json", "source_type": "structured", "doc_id": "gk_1"},
    )
    chunks = [
        Document(page_content=f"chunk-{index}", metadata={"source": "/tmp/demo.structured.json", "doc_id": "gk_1"})
        for index in range(5)
    ]

    monkeypatch.setattr(indexer, "resolve_project_path", lambda path: Path("/tmp/knowledge/docs"))
    monkeypatch.setattr(
        indexer,
        "_load_global_documents_for_sources",
        lambda source_filenames, docs_root, records_by_source_filename: ([original_document], ["doc-1"]),
    )
    monkeypatch.setattr(indexer, "_load_global_records_by_source_filename", lambda docs_root: {"a.pdf": {}})
    monkeypatch.setattr(indexer, "_build_chunks", lambda documents, scope, thread_id: chunks)
    monkeypatch.setattr(indexer, "get_embedding_model", lambda: SimpleNamespace(embed_query=lambda text: [0.1, 0.2]))

    deleted_doc_ids: list[list[str]] = []
    progress: list[tuple[int, int, str]] = []
    added_payloads: list[list[str]] = []

    class _Client:
        pass

    class _VectorStore:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def add_documents(self, documents, **kwargs):
            added_payloads.append([document.page_content for document in documents])
            return ["p1"]

    fingerprint = indexer._chunk_fingerprint(chunks)

    monkeypatch.setattr(indexer, "get_qdrant_client", lambda: _Client())
    monkeypatch.setattr(indexer, "_ensure_collection", lambda client, collection_name, embeddings: None)
    monkeypatch.setattr(indexer, "_delete_points_by_doc_ids", lambda client, collection_name, doc_ids: deleted_doc_ids.append(doc_ids))
    monkeypatch.setattr(indexer, "QdrantVectorStore", _VectorStore)

    total_chunks, returned_fingerprint = indexer.upsert_global_knowledge_record(
        "a.pdf",
        resume_chunk_index=2,
        expected_fingerprint=fingerprint,
        on_batch_complete=lambda next_chunk_index, total, content_fingerprint: progress.append(
            (next_chunk_index, total, content_fingerprint)
        ),
    )

    assert total_chunks == 5
    assert returned_fingerprint == fingerprint
    assert deleted_doc_ids == []
    assert added_payloads == [["chunk-2", "chunk-3", "chunk-4"]]
    assert progress == [(5, 5, fingerprint)]


def test_upsert_global_knowledge_record_parallelizes_batches_and_tracks_prefix_progress(monkeypatch) -> None:
    monkeypatch.setattr(
        indexer,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(
            docs_path="/tmp/knowledge/docs",
            qdrant=SimpleNamespace(
                collection_name="knowledge_base",
                upsert_batch_size=2,
                upsert_parallelism=2,
            ),
            chunking=SimpleNamespace(chunk_size=80, chunk_overlap=0),
        ),
    )

    original_document = Document(
        page_content="全局知识内容",
        metadata={"source": "/tmp/demo.structured.json", "source_type": "structured", "doc_id": "gk_1"},
    )
    chunks = [
        Document(page_content=f"chunk-{index}", metadata={"source": "/tmp/demo.structured.json", "doc_id": "gk_1"})
        for index in range(6)
    ]

    monkeypatch.setattr(indexer, "resolve_project_path", lambda path: Path("/tmp/knowledge/docs"))
    monkeypatch.setattr(
        indexer,
        "_load_global_documents_for_sources",
        lambda source_filenames, docs_root, records_by_source_filename: ([original_document], ["doc-1"]),
    )
    monkeypatch.setattr(indexer, "_load_global_records_by_source_filename", lambda docs_root: {"a.pdf": {}})
    monkeypatch.setattr(indexer, "_build_chunks", lambda documents, scope, thread_id: chunks)
    monkeypatch.setattr(indexer, "get_embedding_model", lambda: SimpleNamespace(embed_query=lambda text: [0.1, 0.2]))

    deleted_doc_ids: list[list[str]] = []
    added_payloads: list[list[str]] = []
    progress: list[tuple[int, int, str]] = []
    payload_lock = Lock()

    class _Client:
        pass

    class _VectorStore:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def add_documents(self, documents, **kwargs):
            payload = [document.page_content for document in documents]
            if payload == ["chunk-0", "chunk-1"]:
                sleep(0.05)
            with payload_lock:
                added_payloads.append(payload)
            return ["p1"]

    monkeypatch.setattr(indexer, "get_qdrant_client", lambda: _Client())
    monkeypatch.setattr(indexer, "_ensure_collection", lambda client, collection_name, embeddings: None)
    monkeypatch.setattr(indexer, "_delete_points_by_doc_ids", lambda client, collection_name, doc_ids: deleted_doc_ids.append(doc_ids))
    monkeypatch.setattr(indexer, "QdrantVectorStore", _VectorStore)

    total_chunks, fingerprint = indexer.upsert_global_knowledge_record(
        "a.pdf",
        on_batch_complete=lambda next_chunk_index, total, content_fingerprint: progress.append(
            (next_chunk_index, total, content_fingerprint)
        ),
    )

    assert total_chunks == 6
    assert fingerprint == indexer._chunk_fingerprint(chunks)
    assert deleted_doc_ids == [["doc-1"]]
    assert sorted(added_payloads) == [["chunk-0", "chunk-1"], ["chunk-2", "chunk-3"], ["chunk-4", "chunk-5"]]
    assert progress == [(2, 6, fingerprint), (4, 6, fingerprint), (6, 6, fingerprint)]


def test_retryable_upsert_exception_treats_qdrant_408_as_retryable() -> None:
    exc = Exception("Unexpected Response: 408 (Request Timeout)\nRaw response content:\nb''")

    assert indexer._retryable_upsert_exception(exc) is True
