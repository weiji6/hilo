"""Index documents into the knowledge base."""

import json
import logging
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from hashlib import sha1
from pathlib import Path
from time import perf_counter, sleep
from uuid import NAMESPACE_URL, uuid5

import httpx
from langchain_community.document_loaders import PyMuPDFLoader, TextLoader
from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import models
from qdrant_client.http.exceptions import ResponseHandlingException
from qdrant_client.models import Distance, VectorParams

from src.community.knowledge_base.common import derive_global_doc_id, derive_thread_doc_id, derive_user_doc_id, extract_title_from_text, get_thread_collection_name, get_user_collection_name, resolve_project_path
from src.community.knowledge_base.ingestion import build_record_lookup, list_ingestion_records
from src.community.knowledge_base.retriever import get_embedding_model, get_qdrant_client
from src.community.knowledge_base.structured_document import build_bbox_from_position, load_structured_document
from src.community.knowledge_base.user_store import list_user_records
from src.config.knowledge_base_config import get_knowledge_base_config
from src.config.paths import get_paths

INDEXABLE_EXTENSIONS = {".md", ".txt", ".pdf"}
STRUCTURED_INDEXABLE_EXTENSIONS = INDEXABLE_EXTENSIONS | {".json"}
STRUCTURED_SOURCE_TYPE = "structured"
UPSERT_RETRY_ATTEMPTS = 4
UPSERT_RETRY_BASE_DELAY_SECONDS = 5.0
UPSERT_BATCH_SIZE = 64
UPSERT_PARALLELISM = 2
VERTICAL_STRUCTURED_MERGE_SIZE = 5
STRUCTURED_EMBED_MIN_CHARS = 100

logger = logging.getLogger(__name__)


def _get_upsert_batch_size() -> int:
    kb_config = get_knowledge_base_config()
    qdrant_config = getattr(kb_config, "qdrant", None)
    value = getattr(qdrant_config, "upsert_batch_size", None)
    if isinstance(value, int) and value > 0:
        return value
    return UPSERT_BATCH_SIZE


def _get_upsert_parallelism() -> int:
    kb_config = get_knowledge_base_config()
    qdrant_config = getattr(kb_config, "qdrant", None)
    value = getattr(qdrant_config, "upsert_parallelism", None)
    if isinstance(value, int) and value > 0:
        return value
    return UPSERT_PARALLELISM


def _build_vector_store(
    *,
    client,
    collection_name: str,
    embeddings,
) -> QdrantVectorStore:
    return QdrantVectorStore(
        client=client,
        collection_name=collection_name,
        embedding=embeddings,
    )


def _load_pdf_documents(path: Path) -> list[Document]:
    try:
        loader = PyMuPDFLoader(str(path))
        documents = loader.load()
    except Exception as exc:
        print(f"Warning: failed to load PDF '{path}': {exc}")
        return []

    for document in documents:
        document.metadata["filename"] = path.name
        document.metadata["source_type"] = "pdf"
        document.metadata["page"] = document.metadata.get("page", 0)
        document.metadata.setdefault("source", str(path))
    return documents


def _load_structured_documents(path: Path) -> list[Document]:
    payload = load_structured_document(path)
    if not payload:
        return []

    documents: list[Document] = []
    for page in payload.get("pages", []):
        page_no = page.get("page_no")
        pdf_page_no = page.get("pdf_page_no") or page_no
        book_page_no = page.get("book_page_no")
        page_number_source = page.get("page_number_source")
        for paragraph in page.get("paragraphs", []):
            paragraph_text = str(paragraph.get("text", "")).strip()
            if not paragraph_text:
                continue
            documents.append(
                Document(
                    page_content=paragraph_text,
                    metadata={
                        "source": str(path),
                        "page_no": page_no,
                        "pdf_page_no": pdf_page_no,
                        "book_page_no": book_page_no,
                        "page_number_source": page_number_source,
                        "page_meta": page.get("meta"),
                        "paragraph_id": paragraph.get("paragraph_id"),
                        "paragraph_no": paragraph.get("paragraph_no"),
                        "paragraph_no_in_doc": paragraph.get("paragraph_no_in_doc"),
                        "line_start": paragraph.get("line_start"),
                        "line_end": paragraph.get("line_end"),
                        "bbox": paragraph.get("bbox")
                        or build_bbox_from_position(paragraph.get("position")),
                        "bbox_source": paragraph.get("bbox_source"),
                        "structured_source_filename": payload.get("source_filename"),
                        "structured_title": payload.get("title"),
                        "parser_name": payload.get("parser_name"),
                        "source_type": "structured",
                    },
                )
            )
    return documents


def _load_documents_from_paths(paths: list[Path]) -> list[Document]:
    documents: list[Document] = []
    for path in sorted(paths):
        try:
            suffix = path.suffix.lower()
            if suffix == ".json":
                documents.extend(_load_structured_documents(path))
            elif suffix == ".md":
                loaded = TextLoader(str(path), encoding="utf-8-sig").load()
                for document in loaded:
                    document.metadata["source_type"] = "markdown"
                documents.extend(loaded)
            elif suffix == ".txt":
                loaded = TextLoader(str(path), encoding="utf-8").load()
                for document in loaded:
                    document.metadata["source_type"] = "text"
                documents.extend(loaded)
            elif suffix == ".pdf":
                documents.extend(_load_pdf_documents(path))
        except Exception as exc:
            print(f"Warning: failed to load '{path}': {exc}")
    return documents


def _ensure_collection(client, collection_name: str, embeddings) -> None:
    try:
        client.get_collection(collection_name=collection_name)
        return
    except Exception:
        pass

    sample_embedding = embeddings.embed_query("history-rag-collection-probe")
    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=len(sample_embedding), distance=Distance.COSINE),
    )


def _replace_collection(client, collection_name: str, embeddings) -> None:
    try:
        client.delete_collection(collection_name=collection_name)
    except Exception:
        pass
    _ensure_collection(client, collection_name, embeddings)


def _clear_collection_if_exists(client, collection_name: str) -> None:
    try:
        client.delete_collection(collection_name=collection_name)
    except Exception:
        pass


def _delete_points_by_doc_ids(client, collection_name: str, doc_ids: list[str]) -> None:
    if not doc_ids:
        return
    try:
        client.delete(
            collection_name=collection_name,
            points_selector=models.Filter(
                must=[
                    models.FieldCondition(
                        key="metadata.doc_id",
                        match=models.MatchAny(any=doc_ids),
                    )
                ]
            ),
            wait=True,
        )
    except Exception:
        pass


def _annotate_chunks(
    chunks: list[Document],
    source_text_by_path: dict[str, str],
    scope: str,
    thread_id: str | None,
) -> list[Document]:
    chunk_counts: dict[str, int] = {}

    for chunk in chunks:
        source = str(chunk.metadata.get("source", ""))
        source_text = source_text_by_path.get(source, "")
        start_index = int(chunk.metadata.get("start_index", 0) or 0)
        existing_line_start = chunk.metadata.get("line_start")
        existing_line_end = chunk.metadata.get("line_end")
        line_start = (
            existing_line_start
            if existing_line_start is not None
            else (source_text[:start_index].count("\n") + 1 if source_text else None)
        )
        line_end = (
            existing_line_end
            if existing_line_end is not None
            else (line_start + chunk.page_content.count("\n") if line_start is not None else None)
        )

        chunk_index = chunk_counts.get(source, 0)
        chunk_counts[source] = chunk_index + 1

        chunk.metadata.update(
            {
                "filename": chunk.metadata.get("filename") or (Path(source).name if source else "Unknown"),
                "source_path": source,
                "scope": scope,
                "thread_id": thread_id,
                "chunk_index": chunk_index,
                "line_start": line_start,
                "line_end": line_end,
                "page": chunk.metadata.get("page"),
                "page_no": chunk.metadata.get("page_no"),
                "pdf_page_no": chunk.metadata.get("pdf_page_no"),
                "book_page_no": chunk.metadata.get("book_page_no"),
                "page_number_source": chunk.metadata.get("page_number_source"),
                "page_meta": chunk.metadata.get("page_meta"),
                "paragraph_id": chunk.metadata.get("paragraph_id"),
                "paragraph_no": chunk.metadata.get("paragraph_no"),
                "paragraph_no_in_doc": chunk.metadata.get("paragraph_no_in_doc"),
                "paragraph_end_no": chunk.metadata.get("paragraph_end_no"),
                "paragraph_end_no_in_doc": chunk.metadata.get("paragraph_end_no_in_doc"),
                "merged_paragraph_count": chunk.metadata.get("merged_paragraph_count"),
                "paragraph_chunk_index": chunk.metadata.get("paragraph_chunk_index"),
                "paragraph_chunk_count": chunk.metadata.get("paragraph_chunk_count"),
                "bbox": chunk.metadata.get("bbox"),
                "bbox_source": chunk.metadata.get("bbox_source"),
                "source_type": chunk.metadata.get("source_type", "unknown"),
            }
        )

    return chunks


def _is_structured_document(document: Document) -> bool:
    return str(document.metadata.get("source_type", "")).lower() == STRUCTURED_SOURCE_TYPE


def _is_vertical_structured_document(document: Document) -> bool:
    return _is_structured_document(document) and str(document.metadata.get("layout_hint") or "").lower() == "vertical"


def _is_plain_structured_document(document: Document) -> bool:
    return _is_structured_document(document) and not str(document.metadata.get("layout_hint") or "").strip()


def _build_document_splitter(chunk_size: int, chunk_overlap: int) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        add_start_index=True,
    )


def _split_structured_document(
    document: Document,
    splitter: RecursiveCharacterTextSplitter,
    chunk_size: int,
) -> list[Document]:
    text = document.page_content.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [document]

    chunks = splitter.split_documents([document])
    if len(chunks) <= 1:
        return [document]

    total_chunks = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
        chunk.metadata["paragraph_chunk_index"] = index
        chunk.metadata["paragraph_chunk_count"] = total_chunks
    return chunks


def _split_regular_document(document: Document, splitter: RecursiveCharacterTextSplitter) -> list[Document]:
    chunks = splitter.split_documents([document])
    return chunks or [document]


def _merge_structured_documents_for_embedding(
    documents: list[Document],
    *,
    min_chars: int,
    max_group_size: int | None = None,
    bbox_source: str = "paragraph_merge",
) -> list[Document]:
    if not documents:
        return []

    merged_documents: list[Document] = []
    batch: list[Document] = []
    batch_char_count = 0

    def flush_batch() -> None:
        nonlocal batch, batch_char_count
        if not batch:
            return
        if len(batch) == 1:
            merged_documents.append(batch[0])
            batch = []
            batch_char_count = 0
            return

        first = batch[0]
        last = batch[-1]
        merged_documents.append(
            Document(
                page_content="\n".join(
                    document.page_content.strip()
                    for document in batch
                    if document.page_content.strip()
                ),
                metadata={
                    **first.metadata,
                    "line_start": first.metadata.get("line_start"),
                    "line_end": last.metadata.get("line_end"),
                    "paragraph_no": first.metadata.get("paragraph_no"),
                    "paragraph_no_in_doc": first.metadata.get("paragraph_no_in_doc"),
                    "paragraph_end_no": last.metadata.get("paragraph_no"),
                    "paragraph_end_no_in_doc": last.metadata.get("paragraph_no_in_doc"),
                    "merged_paragraph_count": len(batch),
                    "bbox": None,
                    "bbox_source": bbox_source,
                },
            )
        )
        batch = []
        batch_char_count = 0

    for document in documents:
        text = document.page_content.strip()
        if not text:
            continue

        if not batch and len(text) >= min_chars:
            merged_documents.append(document)
            continue

        batch.append(document)
        batch_char_count += len(text)
        if max_group_size is not None and len(batch) >= max_group_size:
            flush_batch()
            continue
        if batch_char_count >= min_chars:
            flush_batch()

    flush_batch()
    return merged_documents


def _split_vertical_structured_documents(
    documents: list[Document],
    *,
    splitter: RecursiveCharacterTextSplitter,
    chunk_size: int,
) -> list[Document]:
    chunks: list[Document] = []
    min_chars = min(STRUCTURED_EMBED_MIN_CHARS, chunk_size)
    for merged_document in _merge_structured_documents_for_embedding(
        documents,
        min_chars=min_chars,
        max_group_size=VERTICAL_STRUCTURED_MERGE_SIZE,
        bbox_source="vertical_sentence_merge",
    ):
        chunks.extend(_split_structured_document(merged_document, splitter, chunk_size))

    return chunks


def _build_chunks(documents: list[Document], scope: str, thread_id: str | None) -> list[Document]:
    kb_config = get_knowledge_base_config()
    splitter = _build_document_splitter(
        kb_config.chunking.chunk_size,
        kb_config.chunking.chunk_overlap,
    )
    chunk_size = kb_config.chunking.chunk_size
    source_text_by_path = {
        str(document.metadata.get("source", "")): document.page_content
        for document in documents
        if document.metadata.get("source")
    }
    chunks: list[Document] = []
    index = 0
    while index < len(documents):
        document = documents[index]
        if _is_vertical_structured_document(document):
            source = str(document.metadata.get("source", ""))
            pdf_page_no = document.metadata.get("pdf_page_no")
            grouped_documents: list[Document] = []
            while index < len(documents):
                candidate = documents[index]
                if not _is_vertical_structured_document(candidate):
                    break
                if str(candidate.metadata.get("source", "")) != source:
                    break
                if candidate.metadata.get("pdf_page_no") != pdf_page_no:
                    break
                grouped_documents.append(candidate)
                index += 1

            chunks.extend(
                _split_vertical_structured_documents(
                    grouped_documents,
                    splitter=splitter,
                    chunk_size=chunk_size,
                )
            )
            continue

        if _is_plain_structured_document(document):
            source = str(document.metadata.get("source", ""))
            pdf_page_no = document.metadata.get("pdf_page_no")
            grouped_documents: list[Document] = []
            while index < len(documents):
                candidate = documents[index]
                if not _is_plain_structured_document(candidate):
                    break
                if str(candidate.metadata.get("source", "")) != source:
                    break
                if candidate.metadata.get("pdf_page_no") != pdf_page_no:
                    break
                grouped_documents.append(candidate)
                index += 1

            for merged_document in _merge_structured_documents_for_embedding(
                grouped_documents,
                min_chars=min(STRUCTURED_EMBED_MIN_CHARS, chunk_size),
            ):
                chunks.extend(_split_structured_document(merged_document, splitter, chunk_size))
            continue

        if _is_structured_document(document):
            chunks.extend(_split_structured_document(document, splitter, chunk_size))
            index += 1
            continue

        chunks.extend(_split_regular_document(document, splitter))
        index += 1
    return _annotate_chunks(chunks, source_text_by_path, scope=scope, thread_id=thread_id)


def _stable_chunk_ids(chunks: list[Document]) -> list[str]:
    ids: list[str] = []
    for chunk in chunks:
        metadata = chunk.metadata
        identity = {
            "doc_id": metadata.get("doc_id"),
            "source_path": metadata.get("source_path") or metadata.get("source"),
            "scope": metadata.get("scope"),
            "thread_id": metadata.get("thread_id"),
            "chunk_index": metadata.get("chunk_index"),
            "paragraph_no_in_doc": metadata.get("paragraph_no_in_doc"),
            "paragraph_chunk_index": metadata.get("paragraph_chunk_index"),
            "line_start": metadata.get("line_start"),
            "line_end": metadata.get("line_end"),
            "page_no": metadata.get("page_no"),
            "pdf_page_no": metadata.get("pdf_page_no"),
            "book_page_no": metadata.get("book_page_no"),
            "content": chunk.page_content,
        }
        payload = json.dumps(identity, ensure_ascii=False, sort_keys=True)
        ids.append(str(uuid5(NAMESPACE_URL, payload)))
    return ids


def _chunk_fingerprint(chunks: list[Document]) -> str:
    digest = sha1()
    for chunk_id in _stable_chunk_ids(chunks):
        digest.update(chunk_id.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _retryable_upsert_exception(exc: Exception) -> bool:
    if isinstance(exc, (ResponseHandlingException, httpx.TransportError, httpx.TimeoutException)):
        return True

    error_name = exc.__class__.__name__
    if error_name in {"APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError"}:
        return True

    message = str(exc).lower()
    if "unexpected response:" in message:
        if "408" in message or "429" in message:
            return True
        for status_code in ("500", "502", "503", "504"):
            if status_code in message:
                return True
    if "no embedding data received" in message:
        return True
    if "rate limit" in message or "temporarily unavailable" in message:
        return True

    source = getattr(exc, "source", None)
    if isinstance(source, Exception) and source is not exc and _retryable_upsert_exception(source):
        return True

    cause = getattr(exc, "__cause__", None)
    if isinstance(cause, Exception) and cause is not exc and _retryable_upsert_exception(cause):
        return True

    return False


def _linear_retry_delay_seconds(attempt: int) -> float:
    return UPSERT_RETRY_BASE_DELAY_SECONDS * max(attempt, 1)


def _add_documents_with_retry(
    vector_store: QdrantVectorStore,
    chunks: list[Document],
    *,
    collection_name: str,
    retries: int = UPSERT_RETRY_ATTEMPTS,
) -> None:
    chunk_ids = _stable_chunk_ids(chunks)
    batch_size = _get_upsert_batch_size()
    for attempt in range(1, retries + 1):
        try:
            started_at = perf_counter()
            vector_store.add_documents(
                chunks,
                ids=chunk_ids,
                batch_size=batch_size,
            )
            elapsed = perf_counter() - started_at
            if elapsed >= 5:
                logger.info(
                    "Qdrant ingest batch for %s processed %s chunks in %.2fs",
                    collection_name,
                    len(chunks),
                    elapsed,
                )
            return
        except Exception as exc:
            if not _retryable_upsert_exception(exc) or attempt >= retries:
                raise
            delay_seconds = _linear_retry_delay_seconds(attempt)
            logger.warning(
                "Knowledge ingest transient failure for %s on attempt %s/%s (%s); retrying in %.1fs",
                collection_name,
                attempt,
                retries,
                exc,
                delay_seconds,
            )
            sleep(delay_seconds)


def _upsert_chunk_batches(
    vector_store: QdrantVectorStore,
    chunks: list[Document],
    *,
    collection_name: str,
    start_chunk_index: int = 0,
    on_batch_complete: Callable[[int, int], None] | None = None,
) -> int:
    total_chunks = len(chunks)
    next_chunk_index = max(0, min(start_chunk_index, total_chunks))
    batch_size = _get_upsert_batch_size()
    while next_chunk_index < total_chunks:
        batch_end = min(next_chunk_index + batch_size, total_chunks)
        _add_documents_with_retry(
            vector_store,
            chunks[next_chunk_index:batch_end],
            collection_name=collection_name,
        )
        next_chunk_index = batch_end
        if on_batch_complete is not None:
            on_batch_complete(next_chunk_index, total_chunks)
    return total_chunks


def _upsert_chunk_shards_parallel(
    *,
    client,
    embeddings,
    chunks: list[Document],
    collection_name: str,
    parallelism: int,
    start_chunk_index: int = 0,
    on_batch_complete: Callable[[int, int], None] | None = None,
) -> int:
    total_chunks = len(chunks)
    effective_start = max(0, min(start_chunk_index, total_chunks))
    batch_size = _get_upsert_batch_size()
    batch_ranges = [
        (batch_start, min(batch_start + batch_size, total_chunks))
        for batch_start in range(effective_start, total_chunks, batch_size)
    ]
    if len(batch_ranges) <= 1 or parallelism <= 1:
        vector_store = _build_vector_store(
            client=client,
            collection_name=collection_name,
            embeddings=embeddings,
        )
        return _upsert_chunk_batches(
            vector_store,
            chunks,
            collection_name=collection_name,
            start_chunk_index=effective_start,
            on_batch_complete=on_batch_complete,
        )

    logger.info(
        "Uploading %s chunks to %s using %s parallel batch workers from chunk %s",
        total_chunks,
        collection_name,
        min(parallelism, len(batch_ranges)),
        effective_start,
    )

    def _worker(batch_start: int, batch_end: int) -> tuple[int, int]:
        vector_store = _build_vector_store(
            client=client,
            collection_name=collection_name,
            embeddings=embeddings,
        )
        _add_documents_with_retry(
            vector_store,
            chunks[batch_start:batch_end],
            collection_name=collection_name,
        )
        return batch_start, batch_end

    next_batch_to_schedule = 0
    completed_batch_starts: set[int] = set()
    frontier_chunk_index = effective_start
    first_exception: Exception | None = None

    with ThreadPoolExecutor(
        max_workers=min(parallelism, len(batch_ranges)),
        thread_name_prefix="qdrant-upsert",
    ) as executor:
        in_flight: dict[Future[tuple[int, int]], tuple[int, int]] = {}

        def _schedule_next_batch() -> bool:
            nonlocal next_batch_to_schedule
            if next_batch_to_schedule >= len(batch_ranges) or first_exception is not None:
                return False
            batch_start, batch_end = batch_ranges[next_batch_to_schedule]
            future = executor.submit(_worker, batch_start, batch_end)
            in_flight[future] = (batch_start, batch_end)
            next_batch_to_schedule += 1
            return True

        while len(in_flight) < min(parallelism, len(batch_ranges)) and _schedule_next_batch():
            pass

        while in_flight:
            done, _pending = wait(in_flight, return_when=FIRST_COMPLETED)
            for future in done:
                batch_start, batch_end = in_flight.pop(future)
                try:
                    future.result()
                except Exception as exc:
                    if first_exception is None:
                        first_exception = exc
                    continue

                completed_batch_starts.add(batch_start)
                while frontier_chunk_index < total_chunks and frontier_chunk_index in completed_batch_starts:
                    frontier_chunk_index = min(frontier_chunk_index + batch_size, total_chunks)
                    if on_batch_complete is not None:
                        on_batch_complete(frontier_chunk_index, total_chunks)

                if first_exception is None:
                    _schedule_next_batch()

        if first_exception is not None:
            raise first_exception

    return total_chunks


def index_documents(
    documents: list[Document],
    collection_name: str,
    scope: str,
    thread_id: str | None = None,
) -> int:
    """Replace a collection with freshly indexed documents."""
    if not documents:
        return 0

    chunks = _build_chunks(documents, scope=scope, thread_id=thread_id)
    embeddings = get_embedding_model()
    client = get_qdrant_client()

    _replace_collection(client, collection_name, embeddings)

    vector_store = _build_vector_store(
        client=client,
        collection_name=collection_name,
        embeddings=embeddings,
    )
    _upsert_chunk_batches(
        vector_store,
        chunks,
        collection_name=collection_name,
    )
    return len(chunks)


def upsert_documents(
    documents: list[Document],
    collection_name: str,
    scope: str,
    thread_id: str | None = None,
    replace_doc_ids: list[str] | None = None,
) -> int:
    """Upsert documents by replacing only the specified doc IDs."""
    doc_ids = [doc_id for doc_id in (replace_doc_ids or []) if doc_id]
    client = get_qdrant_client()

    if not documents:
        _delete_points_by_doc_ids(client, collection_name, doc_ids)
        return 0

    chunks = _build_chunks(documents, scope=scope, thread_id=thread_id)
    embeddings = get_embedding_model()
    _ensure_collection(client, collection_name, embeddings)
    _delete_points_by_doc_ids(client, collection_name, doc_ids)

    vector_store = _build_vector_store(
        client=client,
        collection_name=collection_name,
        embeddings=embeddings,
    )
    _upsert_chunk_batches(
        vector_store,
        chunks,
        collection_name=collection_name,
    )
    return len(chunks)


def delete_documents_by_doc_ids(collection_name: str, doc_ids: list[str]) -> None:
    """Delete vectors for the given doc IDs from a collection."""
    client = get_qdrant_client()
    _delete_points_by_doc_ids(client, collection_name, [doc_id for doc_id in doc_ids if doc_id])


def rebuild_global_knowledge_index() -> int:
    """Rebuild the shared knowledge-base collection from repo docs."""
    kb_config = get_knowledge_base_config()
    docs_path = resolve_project_path(kb_config.docs_path)
    ingestion_dir = docs_path / ".ingestion"

    if not docs_path.exists():
        docs_path.mkdir(parents=True, exist_ok=True)
        sample_doc = docs_path / "welcome.md"
        sample_doc.write_text(
            "# Welcome to DeerFlow Knowledge Base\n\nThis is a sample document. Add your markdown files here to be indexed.",
            encoding="utf-8",
        )

    documents: list[Document] = []
    candidate_paths: list[Path] = []
    seen_paths: set[Path] = set()
    records_by_source_filename: dict[str, dict[str, object]] = {}

    if ingestion_dir.exists():
        for path in sorted(ingestion_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict) or payload.get("schema_version") == 1:
                continue
            source_filename = payload.get("source_filename")
            if source_filename:
                records_by_source_filename[str(source_filename)] = payload
            target_path = payload.get("index_target_path") or (
                str(ingestion_dir / payload["index_target_filename"])
                if payload.get("index_target_filename")
                else None
            )
            if not payload.get("indexable") or not target_path:
                continue
            candidate = Path(str(target_path))
            if not candidate.exists() or candidate in seen_paths:
                continue
            candidate_paths.append(candidate)
            seen_paths.add(candidate)

    # Files copied by `make config` have no ingestion record yet. Index local
    # text directly, but respect pending/failed ingestion records and do not
    # index the raw source a second time alongside its structured version.
    for candidate in sorted(docs_path.iterdir()):
        if (
            candidate.is_file()
            and not candidate.name.startswith(".")
            and candidate.suffix.lower() in {".md", ".txt"}
            and candidate.name not in records_by_source_filename
            and candidate not in seen_paths
        ):
            candidate_paths.append(candidate)
            seen_paths.add(candidate)

    if not candidate_paths:
        return 0

    documents.extend(_load_documents_from_paths(candidate_paths))

    if not documents:
        return 0

    for document in documents:
        source_path = Path(str(document.metadata.get("source", "")))
        if not source_path.name:
            continue
        source_filename = document.metadata.get("structured_source_filename") or source_path.name
        global_record = records_by_source_filename.get(str(source_filename), {})
        title = document.metadata.get("structured_title") or Path(str(source_filename)).stem
        document.metadata["doc_id"] = derive_global_doc_id(docs_path, Path(str(source_filename)))
        document.metadata["title"] = title
        document.metadata["filename"] = str(global_record.get("preview_filename") or source_filename)
        document.metadata["detected_title"] = extract_title_from_text(
            document.page_content[:800],
            source_path.stem,
        )
        if global_record.get("preview_filename"):
            document.metadata["preview_filename"] = global_record.get("preview_filename")
        if (
            global_record.get("source_filename")
            and global_record.get("source_filename") != global_record.get("preview_filename")
        ):
            document.metadata["origin_filename"] = global_record.get("source_filename")

    return index_documents(
        documents,
        collection_name=kb_config.qdrant.collection_name,
        scope="global",
        thread_id=None,
    )


def _load_global_records_by_source_filename(docs_root: Path) -> dict[str, dict[str, object]]:
    records_by_source_filename: dict[str, dict[str, object]] = {}
    ingestion_dir = docs_root / ".ingestion"
    if not ingestion_dir.exists():
        return records_by_source_filename

    for path in sorted(ingestion_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("schema_version") == 1:
            continue
        source_filename = payload.get("source_filename")
        if source_filename:
            records_by_source_filename[str(source_filename)] = payload
    return records_by_source_filename


def _load_global_documents_for_sources(
    source_filenames: list[str],
    *,
    docs_root: Path,
    records_by_source_filename: dict[str, dict[str, object]],
) -> tuple[list[Document], list[str]]:
    documents: list[Document] = []
    replace_doc_ids: list[str] = []

    for source_filename in source_filenames:
        record = records_by_source_filename.get(str(source_filename))
        if not record:
            continue

        doc_id = derive_global_doc_id(docs_root, docs_root / str(source_filename))
        replace_doc_ids.append(doc_id)

        if not record.get("indexable"):
            continue
        raw_target = record.get("index_target_path") or (
            str(docs_root / ".ingestion" / record["index_target_filename"])
            if record.get("index_target_filename")
            else None
        )
        if not raw_target:
            continue

        path = Path(str(raw_target))
        if not path.exists():
            continue

        for document in _load_documents_from_paths([path]):
            source_path = Path(str(document.metadata.get("source", "")))
            title = document.metadata.get("structured_title") or Path(str(source_filename)).stem
            document.metadata["doc_id"] = doc_id
            document.metadata["title"] = title
            document.metadata["filename"] = str(record.get("preview_filename") or source_filename)
            document.metadata["detected_title"] = extract_title_from_text(
                document.page_content[:800],
                source_path.stem,
            )
            if record.get("preview_filename"):
                document.metadata["preview_filename"] = record.get("preview_filename")
            if (
                record.get("source_filename")
                and record.get("source_filename") != record.get("preview_filename")
            ):
                document.metadata["origin_filename"] = record.get("source_filename")
            documents.append(document)

    return documents, replace_doc_ids


def upsert_global_knowledge_record(
    source_filename: str,
    *,
    resume_chunk_index: int = 0,
    expected_fingerprint: str | None = None,
    on_batch_complete: Callable[[int, int, str], None] | None = None,
) -> tuple[int, str]:
    kb_config = get_knowledge_base_config()
    docs_root = resolve_project_path(kb_config.docs_path)
    records_by_source_filename = _load_global_records_by_source_filename(docs_root)
    documents, replace_doc_ids = _load_global_documents_for_sources(
        [source_filename],
        docs_root=docs_root,
        records_by_source_filename=records_by_source_filename,
    )

    chunks = _build_chunks(documents, scope="global", thread_id=None)
    fingerprint = _chunk_fingerprint(chunks)
    effective_resume_chunk_index = (
        max(0, resume_chunk_index) if expected_fingerprint and expected_fingerprint == fingerprint else 0
    )

    client = get_qdrant_client()
    embeddings = get_embedding_model()
    _ensure_collection(client, kb_config.qdrant.collection_name, embeddings)

    if effective_resume_chunk_index == 0 and replace_doc_ids:
        _delete_points_by_doc_ids(client, kb_config.qdrant.collection_name, replace_doc_ids)

    if not chunks:
        return 0, fingerprint

    parallelism = _get_upsert_parallelism()
    use_parallel_upload = effective_resume_chunk_index == 0 and parallelism > 1

    if use_parallel_upload:
        _upsert_chunk_shards_parallel(
            client=client,
            embeddings=embeddings,
            chunks=chunks,
            collection_name=kb_config.qdrant.collection_name,
            parallelism=parallelism,
            start_chunk_index=effective_resume_chunk_index,
            on_batch_complete=(
                None
                if on_batch_complete is None
                else lambda next_chunk_index, total_chunks: on_batch_complete(
                    next_chunk_index,
                    total_chunks,
                    fingerprint,
                )
            ),
        )
    else:
        vector_store = _build_vector_store(
            client=client,
            collection_name=kb_config.qdrant.collection_name,
            embeddings=embeddings,
        )
        _upsert_chunk_batches(
            vector_store,
            chunks,
            collection_name=kb_config.qdrant.collection_name,
            start_chunk_index=effective_resume_chunk_index,
            on_batch_complete=(
                None
                if on_batch_complete is None
                else lambda next_chunk_index, total_chunks: on_batch_complete(
                    next_chunk_index,
                    total_chunks,
                    fingerprint,
                )
            ),
        )
    return len(chunks), fingerprint


def upsert_global_knowledge_records(source_filenames: list[str]) -> int:
    kb_config = get_knowledge_base_config()
    docs_root = resolve_project_path(kb_config.docs_path)
    records_by_source_filename = _load_global_records_by_source_filename(docs_root)
    documents, replace_doc_ids = _load_global_documents_for_sources(
        source_filenames,
        docs_root=docs_root,
        records_by_source_filename=records_by_source_filename,
    )

    return upsert_documents(
        documents,
        collection_name=kb_config.qdrant.collection_name,
        scope="global",
        thread_id=None,
        replace_doc_ids=replace_doc_ids,
    )


def delete_global_knowledge_documents(source_filenames: list[str]) -> None:
    kb_config = get_knowledge_base_config()
    docs_root = resolve_project_path(kb_config.docs_path)
    doc_ids = [
        derive_global_doc_id(docs_root, docs_root / str(source_filename))
        for source_filename in source_filenames
        if source_filename
    ]
    delete_documents_by_doc_ids(kb_config.qdrant.collection_name, doc_ids)


def rebuild_thread_upload_index(thread_id: str) -> int:
    """Rebuild the per-thread upload collection from indexed upload files."""
    kb_config = get_knowledge_base_config()
    uploads_dir = get_paths().sandbox_uploads_dir(thread_id)
    collection_name = get_thread_collection_name(kb_config.qdrant.collection_name, thread_id)

    if not uploads_dir.exists():
        _clear_collection_if_exists(get_qdrant_client(), collection_name)
        return 0

    _, records_by_index_target = build_record_lookup(thread_id)
    candidate_paths: list[Path] = []
    seen_paths: set[Path] = set()

    for record in list_ingestion_records(thread_id):
        target_filename = record.get("index_target_filename")
        target_path = record.get("index_target_path")
        if not record.get("indexable") or not target_filename or not target_path:
            continue
        path = Path(str(target_path))
        if not path.exists() or path in seen_paths:
            continue
        candidate_paths.append(path)
        seen_paths.add(path)

    if not candidate_paths:
        _clear_collection_if_exists(get_qdrant_client(), collection_name)
        return 0

    documents = _load_documents_from_paths(candidate_paths)
    if not documents:
        _clear_collection_if_exists(get_qdrant_client(), collection_name)
        return 0

    for document in documents:
        source_path = Path(str(document.metadata.get("source", "")))
        if not source_path.name:
            continue
        ingestion_record = records_by_index_target.get(source_path.name)

        document.metadata["scope"] = "thread"
        document.metadata["thread_id"] = thread_id
        document.metadata["filename"] = source_path.name
        if ingestion_record:
            source_filename = ingestion_record.get("source_filename", source_path.name)
            document.metadata["doc_id"] = derive_thread_doc_id(Path(source_filename))
            document.metadata["title"] = ingestion_record.get("display_title", Path(source_filename).stem)
            preview_filename = ingestion_record.get("preview_filename") or source_filename
            document.metadata["filename"] = preview_filename
            document.metadata["parse_method"] = ingestion_record.get("parse_method")
            document.metadata["parse_status"] = ingestion_record.get("parse_status")
            hints = ingestion_record.get("hints") or {}
            for key, value in hints.items():
                document.metadata[key] = value
            source_virtual_path = (
                ingestion_record.get("preview_virtual_path")
                or ingestion_record.get("source_virtual_path")
            )
            if source_virtual_path:
                document.metadata["source_virtual_path"] = source_virtual_path
            if source_filename != preview_filename:
                document.metadata["origin_filename"] = source_filename
                document.metadata["origin_virtual_path"] = ingestion_record.get("source_virtual_path")
        else:
            document.metadata["doc_id"] = derive_thread_doc_id(source_path)
            document.metadata["title"] = source_path.stem
        document.metadata["detected_title"] = extract_title_from_text(
            document.page_content[:800],
            source_path.stem,
        )

        if "origin_virtual_path" not in document.metadata and source_path.suffix.lower() == ".md":
            for sibling in uploads_dir.glob(f"{source_path.stem}.*"):
                if sibling == source_path:
                    continue
                if sibling.suffix.lower() in INDEXABLE_EXTENSIONS:
                    continue
                document.metadata["origin_filename"] = sibling.name
                document.metadata["origin_virtual_path"] = f"/mnt/user-data/uploads/{sibling.name}"
                break

        if "source_virtual_path" not in document.metadata:
            document.metadata["source_virtual_path"] = f"/mnt/user-data/uploads/{source_path.name}"

    return index_documents(
        documents,
        collection_name=collection_name,
        scope="thread",
        thread_id=thread_id,
    )


def upsert_thread_upload_records(thread_id: str, source_filenames: list[str]) -> int:
    kb_config = get_knowledge_base_config()
    collection_name = get_thread_collection_name(kb_config.qdrant.collection_name, thread_id)
    source_lookup = {
        str(record.get("source_filename")): record
        for record in list_ingestion_records(thread_id)
        if record.get("source_filename")
    }
    documents: list[Document] = []
    replace_doc_ids: list[str] = []
    for source_filename in source_filenames:
        record = source_lookup.get(str(source_filename))
        if not record:
            continue

        doc_id = derive_thread_doc_id(Path(str(source_filename)))
        replace_doc_ids.append(doc_id)

        if not record.get("indexable") or not record.get("index_target_path"):
            continue

        path = Path(str(record["index_target_path"]))
        if not path.exists():
            continue

        for document in _load_documents_from_paths([path]):
            source_path = Path(str(document.metadata.get("source", "")))
            preview_filename = record.get("preview_filename") or source_filename
            document.metadata["scope"] = "thread"
            document.metadata["thread_id"] = thread_id
            document.metadata["filename"] = preview_filename
            document.metadata["doc_id"] = doc_id
            document.metadata["title"] = record.get("display_title", Path(str(source_filename)).stem)
            document.metadata["parse_method"] = record.get("parse_method")
            document.metadata["parse_status"] = record.get("parse_status")
            hints = record.get("hints") or {}
            for key, value in hints.items():
                document.metadata[key] = value
            source_virtual_path = (
                record.get("preview_virtual_path")
                or record.get("source_virtual_path")
            )
            if source_virtual_path:
                document.metadata["source_virtual_path"] = source_virtual_path
            if source_filename != preview_filename:
                document.metadata["origin_filename"] = source_filename
                document.metadata["origin_virtual_path"] = record.get("source_virtual_path")
            if "source_virtual_path" not in document.metadata:
                document.metadata["source_virtual_path"] = f"/mnt/user-data/uploads/{preview_filename}"
            document.metadata["detected_title"] = extract_title_from_text(
                document.page_content[:800],
                source_path.stem,
            )
            documents.append(document)

    if not documents:
        delete_documents_by_doc_ids(collection_name, replace_doc_ids)
        return 0

    return upsert_documents(
        documents,
        collection_name=collection_name,
        scope="thread",
        thread_id=thread_id,
        replace_doc_ids=replace_doc_ids,
    )


def delete_thread_upload_records(thread_id: str, source_filenames: list[str]) -> None:
    kb_config = get_knowledge_base_config()
    collection_name = get_thread_collection_name(kb_config.qdrant.collection_name, thread_id)
    doc_ids = [
        derive_thread_doc_id(Path(str(source_filename)))
        for source_filename in source_filenames
        if source_filename
    ]
    delete_documents_by_doc_ids(collection_name, doc_ids)


def rebuild_user_knowledge_index(user_id: str) -> int:
    """Rebuild the per-user personal knowledge collection from indexed user files."""
    kb_config = get_knowledge_base_config()
    collection_name = get_user_collection_name(kb_config.qdrant.collection_name, user_id)

    try:
        get_paths().ensure_user_knowledge_dirs(user_id)
    except ValueError:
        _clear_collection_if_exists(get_qdrant_client(), collection_name)
        raise

    records = list_user_records(user_id)
    candidate_paths: list[Path] = []
    seen_paths: set[Path] = set()
    records_by_index_target: dict[str, dict[str, object]] = {}

    for record in records:
        target_filename = record.get("index_target_filename")
        target_path = record.get("index_target_path")
        if target_filename:
            records_by_index_target[str(target_filename)] = record
        if not record.get("retrieval_enabled") or not record.get("indexable"):
            continue
        if not target_filename or not target_path:
            continue
        path = Path(str(target_path))
        if not path.exists() or path in seen_paths:
            continue
        candidate_paths.append(path)
        seen_paths.add(path)

    if not candidate_paths:
        _clear_collection_if_exists(get_qdrant_client(), collection_name)
        return 0

    documents = _load_documents_from_paths(candidate_paths)
    if not documents:
        _clear_collection_if_exists(get_qdrant_client(), collection_name)
        return 0

    for document in documents:
        source_path = Path(str(document.metadata.get("source", "")))
        if not source_path.name:
            continue
        record = records_by_index_target.get(source_path.name)

        document.metadata["scope"] = "user"
        document.metadata["user_id"] = user_id
        document.metadata["filename"] = source_path.name
        if record:
            record_id = str(record.get("id") or source_path.stem)
            source_filename = str(record.get("source_filename") or source_path.name)
            preview_filename = str(record.get("preview_filename") or source_filename)
            document.metadata["doc_id"] = derive_user_doc_id(record_id)
            document.metadata["title"] = record.get("display_title", Path(source_filename).stem)
            document.metadata["filename"] = preview_filename
            document.metadata["parse_method"] = record.get("parse_method")
            document.metadata["parse_status"] = record.get("parse_status")
            document.metadata["source_kind"] = record.get("source_kind", "upload")
            document.metadata["origin_scope"] = record.get("origin_scope")
            document.metadata["origin_doc_id"] = record.get("origin_doc_id")
            document.metadata["origin_filename"] = record.get("origin_filename")
            document.metadata["origin_anchor"] = record.get("origin_anchor")
            hints = record.get("hints") or {}
            for key, value in hints.items():
                document.metadata[key] = value
            document.metadata["source_artifact_url"] = record.get("preview_artifact_url") or record.get("source_artifact_url")
        else:
            document.metadata["doc_id"] = derive_user_doc_id(source_path.name)
            document.metadata["title"] = source_path.stem
            document.metadata["source_kind"] = "upload"
            document.metadata["source_artifact_url"] = None
        document.metadata["detected_title"] = extract_title_from_text(
            document.page_content[:800],
            source_path.stem,
        )

    return index_documents(
        documents,
        collection_name=collection_name,
        scope="user",
        thread_id=None,
    )


def upsert_user_knowledge_records(user_id: str, record_ids: list[str]) -> int:
    kb_config = get_knowledge_base_config()
    collection_name = get_user_collection_name(kb_config.qdrant.collection_name, user_id)
    records_by_id = {
        str(record.get("id")): record
        for record in list_user_records(user_id)
        if record.get("id")
    }
    documents: list[Document] = []
    replace_doc_ids: list[str] = []

    for record_id in record_ids:
        record = records_by_id.get(str(record_id))
        if not record:
            continue

        doc_id = derive_user_doc_id(str(record_id))
        replace_doc_ids.append(doc_id)

        if not record.get("retrieval_enabled") or not record.get("indexable") or not record.get("index_target_path"):
            continue

        path = Path(str(record["index_target_path"]))
        if not path.exists():
            continue

        for document in _load_documents_from_paths([path]):
            source_path = Path(str(document.metadata.get("source", "")))
            source_filename = str(record.get("source_filename") or source_path.name)
            preview_filename = str(record.get("preview_filename") or source_filename)
            document.metadata["scope"] = "user"
            document.metadata["user_id"] = user_id
            document.metadata["filename"] = preview_filename
            document.metadata["doc_id"] = doc_id
            document.metadata["title"] = record.get("display_title", Path(source_filename).stem)
            document.metadata["parse_method"] = record.get("parse_method")
            document.metadata["parse_status"] = record.get("parse_status")
            document.metadata["source_kind"] = record.get("source_kind", "upload")
            document.metadata["origin_scope"] = record.get("origin_scope")
            document.metadata["origin_doc_id"] = record.get("origin_doc_id")
            document.metadata["origin_filename"] = record.get("origin_filename")
            document.metadata["origin_anchor"] = record.get("origin_anchor")
            hints = record.get("hints") or {}
            for key, value in hints.items():
                document.metadata[key] = value
            document.metadata["source_artifact_url"] = (
                record.get("preview_artifact_url") or record.get("source_artifact_url")
            )
            document.metadata["detected_title"] = extract_title_from_text(
                document.page_content[:800],
                source_path.stem,
            )
            documents.append(document)

    if not documents:
        delete_documents_by_doc_ids(collection_name, replace_doc_ids)
        return 0

    return upsert_documents(
        documents,
        collection_name=collection_name,
        scope="user",
        thread_id=None,
        replace_doc_ids=replace_doc_ids,
    )


def delete_user_knowledge_records(user_id: str, record_ids: list[str]) -> None:
    kb_config = get_knowledge_base_config()
    collection_name = get_user_collection_name(kb_config.qdrant.collection_name, user_id)
    doc_ids = [derive_user_doc_id(str(record_id)) for record_id in record_ids if record_id]
    delete_documents_by_doc_ids(collection_name, doc_ids)


def run_indexer() -> None:
    """CLI entrypoint for rebuilding the shared knowledge-base index."""
    print("Starting knowledge base indexer...")
    from src.config.app_config import get_app_config

    config = get_app_config()
    kb_config = config.knowledge_base
    if not kb_config.enabled:
        print("Knowledge base is disabled in config. Set knowledge_base.enabled=true to enable indexing.")
        return

    indexed_chunks = rebuild_global_knowledge_index()
    print(f"Indexing complete. Indexed {indexed_chunks} chunks into '{kb_config.qdrant.collection_name}'.")


if __name__ == "__main__":
    run_indexer()
