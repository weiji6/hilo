"""Exercise restored source-export, SQLite ingestion, and portable agent tools."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from src.config.app_config import AppConfig

ROOT = Path(__file__).resolve().parents[2]


def load_script(relative):
    spec = importlib.util.spec_from_file_location("publication_helper", ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_export_preserves_runtime_and_supported_entrypoints(tmp_path):
    exporter = load_script("scripts/export_open_source.py")
    output = tmp_path / "release"
    exporter.export(output)
    for folder in ("backend/src", "frontend/src", "backend/protos", "backend/services", "skills/public"):
        original = {p.relative_to(ROOT) for p in (ROOT / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
        assert original <= {p.relative_to(output) for p in (output / folder).rglob("*") if p.is_file()}
    for relative in exporter.SCRIPT_FILES | exporter.DOCKER_FILES | {"README.md", "README.en.md"}:
        assert (output / relative).is_file(), relative
    assert not (output / "config.yaml").exists()
    assert not (output / ".git").exists()


def test_default_tools_resolve_to_real_implementations(monkeypatch):
    from langchain.tools import BaseTool

    from src.reflection import resolve_variable

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    config = AppConfig.from_file(str(ROOT / "config.example.yaml"))
    names = {resolve_variable(tool.use, BaseTool).name for tool in config.tools}
    assert {"book_search", "knowledge_locate", "knowledge_search", "read_file", "ls", "bash", "web_fetch", "image_search"} <= names
    assert "write_file" not in names


def test_local_shell_executes_when_zsh_is_absent(monkeypatch):
    import shutil

    import src.sandbox.local.local_sandbox as local

    real_which = shutil.which
    monkeypatch.setattr(local.shutil, "which", lambda name: None if name == "zsh" else real_which(name))
    sandbox = local.LocalSandbox("portable-test")
    assert sandbox.execute_command("printf hilo-portable-shell") == "hilo-portable-shell"
    assert "Exit Code: 7" in sandbox.execute_command("exit 7")


def test_structured_ingestion_round_trip_into_actual_locator_and_fts(tmp_path, monkeypatch):
    from src.community.knowledge_base import locator, paragraph_store

    ingest = load_script("scripts/ingest_structured_docs_to_db.py")
    docs = tmp_path / "knowledge/docs"
    staging = docs / ".ingestion"
    staging.mkdir(parents=True)
    source = staging / "worker.pdf.structured.json"
    source.write_text(
        json.dumps(
            {
                "title": "Worker operations",
                "source_filename": "worker.pdf",
                "pages": [
                    {
                        "page_no": 2,
                        "pdf_page_no": 3,
                        "book_page_no": 2,
                        "paragraphs": [{"paragraph_no": 1, "paragraph_no_in_doc": 1, "paragraph_id": "page-3-p1", "text": "Retry limit is five attempts.", "position": [1, 2, 3, 4], "layout_type": "text"}],
                    }
                ],
            }
        )
    )
    monkeypatch.setattr(ingest, "_prewarm_indexes", lambda: None)
    # --docs-dir determines the DB default even without a project config.
    assert ingest.main(["--docs-dir", str(docs)]) == 0
    assert (docs.parent / "paragraphs.db").exists()
    monkeypatch.setattr(paragraph_store, "get_knowledge_base_config", lambda: SimpleNamespace(docs_path=str(docs)))
    monkeypatch.setattr(locator, "get_knowledge_base_config", lambda: SimpleNamespace(docs_path=str(docs)))
    found = locator.locate_document(None, doc_id="worker.pdf")
    assert found.doc_id == "worker.pdf"
    page = found.payload["pages"][0]
    assert (page["pdf_page_no"], page["book_page_no"]) == (3, 2)
    assert page["paragraphs"][0]["position"] == [1, 2, 3, 4]
    hits = paragraph_store.search_fts("Retry", doc_ids=["worker.pdf"], top_k=3)
    assert hits and "five attempts" in hits[0]["content"]
    # A fresh DB must be rebuildable even when old .resolved markers remain.
    replacement = tmp_path / "replacement.db"
    assert ingest.main(["--docs-dir", str(docs), "--db", str(replacement)]) == 0
    conn = ingest._connect(replacement)
    try:
        assert conn.execute("SELECT COUNT(*) FROM paragraphs").fetchone()[0] == 1
    finally:
        conn.close()


def test_ingestion_helper_obeys_hilo_config_precedence(tmp_path, monkeypatch):
    ingest = load_script("scripts/ingest_structured_docs_to_db.py")
    first, second = tmp_path / "first.yaml", tmp_path / "second.yaml"
    first.write_text(f"knowledge_base:\n  docs_path: {tmp_path / 'first'}\n")
    second.write_text(f"knowledge_base:\n  docs_path: {tmp_path / 'second'}\n")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(first))
    monkeypatch.setenv("HILO_CONFIG_PATH", str(second))
    assert ingest._docs_path_from_config() == tmp_path / "second"
    monkeypatch.delenv("HILO_CONFIG_PATH")
    assert ingest._docs_path_from_config() == tmp_path / "first"
