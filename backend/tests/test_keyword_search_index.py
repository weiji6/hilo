import json
import sqlite3
from types import SimpleNamespace

import src.community.knowledge_base.keyword_search_index as keyword_index_module
import src.config.paths as paths_module
from src.community.knowledge_base.structured_document import build_structured_document, save_structured_document
from src.config.paths import Paths


def test_search_keyword_documents_builds_missing_index_and_filters_short_paragraphs(tmp_path, monkeypatch) -> None:
    paths = Paths(tmp_path / ".deer-flow")
    monkeypatch.setattr(paths_module, "_paths", paths)

    docs_root = tmp_path / "knowledge" / "docs"
    docs_root.mkdir(parents=True)
    (docs_root / "sample.pdf").write_text("", encoding="utf-8")

    structured_payload = build_structured_document(
        source_filename="sample.pdf",
        title="Sample Book",
        text=(
            "短句\n\n"
            "这是一段足够长的正文，用来验证首次搜索时会自动建立 SQLite FTS 索引，"
            "并且检索结果会返回原书页码和段落信息。"
        ),
        parser_name="test",
    )
    structured_path = save_structured_document(docs_root, "sample.pdf", structured_payload)

    ingestion_dir = docs_root / ".ingestion"
    ingestion_dir.mkdir(parents=True)
    (ingestion_dir / "sample.pdf.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_filename": "sample.pdf",
                "display_title": "Sample Book",
                "indexable": True,
                "structured_path": str(structured_path),
                "source_path": str(docs_root / "sample.pdf"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        keyword_index_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(docs_path=str(docs_root)),
    )

    db_path = paths.knowledge_search_db_path()
    assert not db_path.exists()

    results = keyword_index_module.search_keyword_documents(
        "自动建立 SQLite FTS 索引",
        thread_id=None,
        user_id=None,
        doc_ids=["sample.pdf"],
        top_k=5,
    )

    assert db_path.exists()
    assert len(results) == 1
    assert "自动建立 SQLite FTS 索引" in results[0]["content"]
    assert results[0]["metadata"]["doc_id"] == "sample.pdf"
    assert results[0]["metadata"]["page_no"] == 1
    assert results[0]["metadata"]["paragraph_no"] == 2

    connection = sqlite3.connect(db_path)
    try:
        row_count = connection.execute(
            "SELECT COUNT(*) FROM paragraph_fts WHERE doc_id = ?",
            ("sample.pdf",),
        ).fetchone()[0]
    finally:
        connection.close()

    assert row_count == 1


def test_search_keyword_documents_prioritizes_multi_term_coverage_over_single_term_hits(
    tmp_path,
    monkeypatch,
) -> None:
    paths = Paths(tmp_path / ".deer-flow")
    monkeypatch.setattr(paths_module, "_paths", paths)

    docs_root = tmp_path / "knowledge" / "docs"
    docs_root.mkdir(parents=True)
    (docs_root / "zhang.pdf").write_text("", encoding="utf-8")

    structured_payload = build_structured_document(
        source_filename="zhang.pdf",
        title="张之洞文献",
        text=(
            "张之洞曾任湖广总督，相关生平与官职沿革在此段中有集中记载，"
            "能够同时覆盖张之洞、官职与总督等检索词。\n\n"
            "第十五条各征收官年满考核，依照比较额，短收二成以上者，褫革官职。\n\n"
            "故本部拟具税务处官制若干条，使内外之官，一气相承，实收纲举目张之效。"
        ),
        parser_name="test",
    )
    structured_path = save_structured_document(docs_root, "zhang.pdf", structured_payload)

    ingestion_dir = docs_root / ".ingestion"
    ingestion_dir.mkdir(parents=True)
    (ingestion_dir / "zhang.pdf.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_filename": "zhang.pdf",
                "display_title": "张之洞文献",
                "indexable": True,
                "structured_path": str(structured_path),
                "source_path": str(docs_root / "zhang.pdf"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        keyword_index_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(docs_path=str(docs_root)),
    )

    results = keyword_index_module.search_keyword_documents(
        "张之洞 生平 官职 总督",
        thread_id=None,
        user_id=None,
        doc_ids=["zhang.pdf"],
        top_k=5,
    )

    assert len(results) == 1
    assert "湖广总督" in results[0]["content"]
    assert results[0]["matched_keywords"] == ["张之洞", "生平", "官职", "总督"]
