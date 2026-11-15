"""Real gateway, parser, locator, and embedded Qdrant with synthetic sources.

External chat and embedding models are deterministic fixtures; parsing, HTTP
routes, indexing, vector storage and evidence tools use real implementations.
"""

import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient
from langchain_core.embeddings import Embeddings
from qdrant_client import QdrantClient

from src.config.app_config import reload_app_config, reset_app_config
from src.config.extensions_config import reset_extensions_config

ROOT = Path(__file__).resolve().parents[2]


class DeterministicEmbeddings(Embeddings):
    def embed_documents(self, texts):
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text):
        # A reproducible local embedding fixture, with no provider calls.
        digest = hashlib.sha256(text.encode()).digest()
        return [value / 255 for value in digest]


@pytest.fixture()
def runtime_environment(tmp_path, monkeypatch):
    from src.community.knowledge_base import indexer, retriever
    from src.gateway.routers import user_knowledge
    from src.sandbox import sandbox_provider
    from src.sandbox.local import local_sandbox_provider

    docs = tmp_path / "knowledge/docs"
    docs.mkdir(parents=True)
    for path in (ROOT / "examples/technical-docs/documents").glob("*.md"):
        shutil.copy2(path, docs / path.name)
    config = yaml.safe_load((ROOT / "config.example.yaml").read_text())
    config["knowledge_base"]["docs_path"] = str(docs)
    config["knowledge_base"]["qdrant"]["mode"] = "local"
    config["title"]["enabled"] = False
    config["summarization"]["enabled"] = False
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    extensions = tmp_path / "extensions_config.json"
    extensions.write_text('{"mcpServers": {}, "skills": {}}')
    monkeypatch.setenv("OPENAI_API_KEY", "local-fixture")
    monkeypatch.setenv("TASK_MEMORY_ENABLED", "false")
    monkeypatch.setenv("HILO_HOME", str(tmp_path / "runtime"))
    monkeypatch.setenv("HILO_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("HILO_EXTENSIONS_CONFIG_PATH", str(extensions))
    reset_extensions_config()
    reload_app_config()
    client = QdrantClient(":memory:")
    embeddings = DeterministicEmbeddings()
    for module in (indexer, retriever, user_knowledge):
        monkeypatch.setattr(module, "get_qdrant_client", lambda: client)
    for module in (indexer, retriever):
        monkeypatch.setattr(module, "get_embedding_model", lambda: embeddings)
    monkeypatch.setattr(local_sandbox_provider, "_singleton", None)
    monkeypatch.setattr(sandbox_provider, "_default_sandbox_provider", None)

    # Any text path reaching OCR is a real regression.
    def forbidden_ocr(*args, **kwargs):
        pytest.fail("Markdown/TXT must not invoke external OCR")

    from src.gateway.routers import knowledge, uploads

    for module in (knowledge, uploads, user_knowledge):
        monkeypatch.setattr(module, "build_structured_document_from_mineru_grpc", forbidden_ocr)
    yield SimpleNamespace(docs=docs, vector=client, root=tmp_path)
    client.close()
    reset_app_config()
    reset_extensions_config()


def test_quick_start_sources_reach_body_evidence_and_numbered_citations(runtime_environment):
    from src.community.knowledge_base import indexer, tools
    from src.community.knowledge_base.catalog import search_book_catalog

    assert indexer.rebuild_global_knowledge_index() > 0
    assert runtime_environment.vector.get_collection("hilo_knowledge").points_count > 0
    entry = search_book_catalog("retry", top_k=1)[0]
    assert entry.doc_id == "retry-policy.md"
    runtime = SimpleNamespace(context={"thread_id": "quick-start", "user_id": None}, state={}, config={})
    answer = tools.knowledge_locate_tool.func(runtime=runtime, doc_id=entry.doc_id, queries=["retry"])
    assert "at most four attempts" in answer
    assert "[citation:" in answer
    assert "No structured document" not in answer


def test_gateway_thread_and_personal_text_uploads_parse_and_index_without_ocr(runtime_environment):
    from src.community.knowledge_base.locator import locate_document
    from src.community.knowledge_base.user_store import list_user_records
    from src.gateway.app import create_app

    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200
        models = client.get("/api/models")
        assert models.status_code == 200
        response = client.post("/api/threads/audit-thread/uploads", files={"files": ("note.md", b"# Worker notes\n\nRetry four attempts.\n", "text/markdown")})
        assert response.status_code == 200, response.text
        assert response.json()["files"][0]["parse_status"] == "parsed"
        document = locate_document("audit-thread", doc_id="note.md")
        assert "Retry four attempts" in document.payload["pages"][0]["text"]
        text = "Local user guide: Retry transient requests up to four times. " * 8
        response = client.post("/api/users/audit-user/knowledge/upload", files={"files": ("personal.txt", text.encode(), "text/plain")})
        assert response.status_code == 200, response.text
        records = list_user_records("audit-user")
        assert len(records) == 1
        assert records[0]["parse_status"] == "indexed", records[0].get("error")
        doc_id = str(records[0]["id"])
        document = locate_document(None, user_id="audit-user", doc_id=doc_id)
        assert "Local user guide" in document.payload["pages"][0]["text"]
        # User vectors land in their own collection.
        names = [c.name for c in runtime_environment.vector.get_collections().collections]
        assert "hilo_knowledge__user__audit-user" in names


def test_scoped_source_never_reads_same_named_global_sqlite_payload(runtime_environment, monkeypatch):
    from src.community.knowledge_base import locator
    from src.community.knowledge_base.structured_document import build_structured_document, save_structured_document

    payload = build_structured_document(source_filename="same.txt", title="Thread source", text="Thread-only content", parser_name="local_text")
    structured = save_structured_document(runtime_environment.root, "same.txt", payload)
    monkeypatch.setattr(locator, "load_structured_payload_from_db", lambda doc_id: {"pages": [{"text": "WRONG GLOBAL BODY"}]})
    entry = SimpleNamespace(doc_id="same.txt", title="Thread source", filename="same.txt", scope="thread", source_url="/thread-source", original_url=None, structured_path=str(structured))
    document = locator.locate_document_from_entry(entry)
    assert document.payload["pages"][0]["text"] == "Thread-only content"


def test_executor_can_be_imported_first_in_a_fresh_process(tmp_path):
    import os
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", "from src.subagents.executor import SubagentExecutor; from src.agents import make_lead_agent; assert callable(make_lead_agent)"],
        cwd=ROOT / "backend",
        env={**os.environ, "HILO_HOME": str(tmp_path)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_rebuild_mixes_raw_and_ingested_text_without_duplicates(runtime_environment):
    from src.community.knowledge_base import indexer
    from src.community.knowledge_base.structured_document import build_structured_document, save_structured_document

    docs = runtime_environment.docs
    ingestion = docs / ".ingestion"
    ingestion.mkdir()
    (docs / "uploaded.txt").write_text("RAW SOURCE MUST NOT BE INDEXED")
    payload = build_structured_document(source_filename="uploaded.txt", title="Uploaded", text="Structured accepted body", parser_name="local_text")
    structured = save_structured_document(ingestion, "uploaded.txt", payload)
    (ingestion / "uploaded.json").write_text(json.dumps({"source_filename": "uploaded.txt", "indexable": True, "index_target_path": str(structured), "preview_filename": "uploaded.txt"}))
    (docs / "failed.txt").write_text("FAILED SOURCE MUST NOT BE INDEXED")
    (ingestion / "failed.json").write_text(json.dumps({"source_filename": "failed.txt", "indexable": False, "parse_status": "failed"}))
    first_count = indexer.rebuild_global_knowledge_index()
    assert first_count > 0
    points, _ = runtime_environment.vector.scroll("hilo_knowledge", limit=100, with_payload=True)
    bodies = "\n".join(point.payload["page_content"] for point in points)
    assert "Structured accepted body" in bodies
    assert "at most four attempts" in bodies
    assert "MUST NOT BE INDEXED" not in bodies
    assert indexer.rebuild_global_knowledge_index() == first_count
    assert runtime_environment.vector.get_collection("hilo_knowledge").points_count == len(points)


def test_gateway_global_text_upload_reaches_body_and_vector_index(runtime_environment, monkeypatch):
    from src.community.knowledge_base import indexer, locator
    from src.gateway.app import create_app
    from src.gateway.routers import knowledge

    # Execute the same queued worker synchronously to make completion observable.
    monkeypatch.setattr(knowledge, "_submit_global_ocr", knowledge._process_single_global_ocr)
    with TestClient(create_app()) as client:
        response = client.post("/api/knowledge/uploads", files={"files": ("global.txt", b"Global worker guide: Retry transient requests at most four times. " * 8, "text/plain")})
        assert response.status_code == 200, response.text
    record = knowledge._load_global_record("global.txt")
    assert record["parse_status"] == "parsed", record.get("error")
    assert record["parse_method"] == "local_text"
    assert "Global worker guide" in locator.locate_document(None, doc_id="global.txt").payload["pages"][0]["text"]
    assert indexer.rebuild_global_knowledge_index() > 0


def test_extensions_saved_by_gateway_are_readable_by_another_process(runtime_environment):
    import os
    import subprocess
    import sys

    from src.gateway.app import create_app

    with TestClient(create_app()) as client:
        response = client.put("/api/mcp/config", json={"mcp_servers": {"audit-disabled": {"enabled": False, "command": "echo", "args": ["fixture"]}}})
        assert response.status_code == 200, response.text
    result = subprocess.run(
        [sys.executable, "-c", "from src.config.extensions_config import ExtensionsConfig; c=ExtensionsConfig.from_file(); assert c.mcp_servers['audit-disabled'].args == ['fixture']; assert not c.get_enabled_mcp_servers()"],
        cwd=ROOT / "backend",
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_compose_shares_extensions_and_writable_custom_skills():
    compose = yaml.safe_load((ROOT / "docker/compose.hilo.yaml").read_text())
    for name in ("gateway", "langgraph"):
        service = compose["services"][name]
        assert service["environment"]["HILO_EXTENSIONS_CONFIG_PATH"] == "/app/extensions_config.json"
        assert "../extensions_config.json:/app/extensions_config.json" in service["volumes"]
        assert "custom-skills:/app/skills/custom" in service["volumes"]
        assert "../skills/public:/app/skills/public:ro" in service["volumes"]
        assert "../skills:/app/skills:ro" not in service["volumes"]


@pytest.mark.parametrize("async_stream", [False, True])
def test_agent_stream_routes_reads_and_cites_real_sources(runtime_environment, monkeypatch, async_stream):
    import asyncio
    import re

    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    from src.agents.lead_agent import agent as lead
    from src.agents.middlewares import overview_retrieval_middleware
    from src.community.knowledge_base.catalog import UNFILED_FOLDER_NAME

    class LocalResearchModel(BaseChatModel):
        @property
        def _llm_type(self):
            return "local-research-fixture"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            evidence = [m for m in messages if isinstance(m, ToolMessage)]
            if not evidence:
                message = AIMessage(content="", tool_calls=[{"id": "route", "name": "book_search", "args": {"query": "retry", "knowledge_folders": [UNFILED_FOLDER_NAME]}}])
            elif not any(m.name == "knowledge_locate" for m in evidence):
                assert "retry-policy.md" in str(evidence[-1].content)
                message = AIMessage(content="", tool_calls=[{"id": "read", "name": "knowledge_locate", "args": {"doc_id": "retry-policy.md", "queries": ["retry"]}}])
            else:
                body = str(next(m.content for m in evidence if m.name == "knowledge_locate"))
                assert "at most four attempts" in body
                marker = re.search(r"\[citation:\d+\]", body).group()
                message = AIMessage(content=f"The worker makes at most four attempts. {marker}")
            return ChatResult(generations=[ChatGeneration(message=message)])

    model = LocalResearchModel()
    monkeypatch.setattr(lead, "create_chat_model", lambda **kwargs: model)
    monkeypatch.setattr(overview_retrieval_middleware, "create_chat_model", lambda **kwargs: model)
    config = {"configurable": {"thread_id": "stream-audit", "thinking_enabled": False}, "recursion_limit": 40}
    graph = lead.make_lead_agent(config)
    inputs = {"messages": [("user", "What retry attempts does the worker allow?")]}
    context = {"thread_id": "stream-audit", "user_id": None}
    if async_stream:

        async def collect():
            return [state async for state in graph.astream(inputs, config, context=context, stream_mode="values")]

        states = asyncio.run(collect())
    else:
        states = list(graph.stream(inputs, config, context=context, stream_mode="values"))
    messages = states[-1]["messages"]
    assert [m.name for m in messages if isinstance(m, ToolMessage)] == ["book_search", "knowledge_locate"]
    assert "four attempts" in messages[-1].content
    registry = states[-1]["knowledge_citation_registry"]
    assert len(registry) == 1
    assert f"[citation:{registry[0]['id']}]" in messages[-1].content
    assert registry[0]["url"].startswith("/api/knowledge/docs/retry-policy.md?")
    assert "无法回答" not in messages[-1].content
