from types import SimpleNamespace

from src.community.knowledge_base.citations import (
    KNOWLEDGE_CITATION_REGISTRY_KEY,
    build_citation_stable_key,
    merge_citation_registries,
    merge_citation_registry,
    resolve_result_citation_context,
    rewrite_numbered_citations,
)
from src.community.knowledge_base.tools import _build_citation


def test_user_note_citation_prefers_user_document_and_current_location(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.community.knowledge_base.citations.locate_document",
        lambda **kwargs: SimpleNamespace(
            source_url="/api/knowledge/docs/original-book.pdf",
            title="原书",
        ),
    )

    result = {
        "filename": "my-note.md",
        "source_type": "structured",
        "page": None,
        "metadata": {
            "scope": "user",
            "source_kind": "excerpt",
            "title": "我的摘录",
            "filename": "my-note.md",
            "page_no": 1,
            "pdf_page_no": 1,
            "paragraph_no": 3,
            "origin_scope": "global",
            "origin_filename": "original-book.pdf",
            "origin_anchor": {
                "page_no": 88,
                "pdf_page_no": 90,
                "paragraph_no": 2,
            },
        },
    }

    context = resolve_result_citation_context(
        result,
        thread_id="thread-1",
        user_id="user-1",
    )

    assert context["citation_title"] == "你的笔记：我的摘录"
    assert context["citation_page_no"] == 1
    assert context["citation_pdf_page_no"] == 1
    assert context["citation_paragraph_no"] == 3
    assert context["source_label"] == "你的笔记"
    assert context["citation_url"].startswith(
        "/api/secure-knowledge/users/me/knowledge/docs/my-note.md?"
    )
    assert "citation_source_label=%E4%BD%A0%E7%9A%84%E7%AC%94%E8%AE%B0" in context["citation_url"]
    assert "citation_origin_title=%E5%8E%9F%E4%B9%A6" in context["citation_url"]


def test_user_upload_citation_uses_uploaded_document_url(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.community.knowledge_base.citations.locate_document",
        lambda **kwargs: None,
    )

    result = {
        "filename": "user-upload.pdf",
        "source_type": "pdf",
        "page": 4,
        "metadata": {
            "scope": "user",
            "source_kind": "upload",
            "title": "用户上传文档",
            "filename": "user-upload.pdf",
        },
    }

    context = resolve_result_citation_context(
        result,
        thread_id="thread-1",
        user_id="user-1",
    )

    assert context["citation_title"] == "你上传的文档：用户上传文档"
    assert context["source_label"] == "你上传的文档"
    assert context["citation_url"].startswith(
        "/api/secure-knowledge/users/me/knowledge/docs/user-upload.pdf?"
    )
    assert "page=4" in context["citation_url"]


def test_build_citation_requires_state_for_numbered_marker() -> None:
    citation = _build_citation(
        "民国财政史 (杨荫溥) 原书第10页第1段",
        "/api/knowledge/docs/%E6%B0%91%E5%9B%BD%E8%B4%A2%E6%94%BF%E5%8F%B2%20%28%E6%9D%A8%E8%8D%AB%E6%BA%A5%29.pdf?page_no=10&paragraph_no=1",
    )

    assert citation is None


def test_build_citation_registers_numbered_marker_when_state_is_available() -> None:
    state = {}
    label = "民国财政史 (杨荫溥) 原书第10页第1段"
    url = "/api/knowledge/docs/book.pdf?page_no=10&paragraph_no=1"
    citation = _build_citation(
        label,
        url,
        state=state,
    )

    assert citation == "[citation:1]"
    assert state[KNOWLEDGE_CITATION_REGISTRY_KEY] == [
        {
            "id": "1",
            "label": label,
            "url": url,
            "stable_key": build_citation_stable_key(citation_label=label, citation_link=url),
        }
    ]


def test_merge_citation_registry_returns_mapping_for_global_renumbering() -> None:
    existing_label = "既有书 原书第1页第1段"
    existing_url = "/api/knowledge/docs/existing.pdf?page_no=1&paragraph_no=1"
    new_label = "甲书 原书第12页第3段"
    new_url = "/api/knowledge/docs/a.pdf?page_no=12&paragraph_no=3"
    state = {}
    assert _build_citation(existing_label, existing_url, state=state) == "[citation:1]"

    mapping = merge_citation_registry(
        state,
        [
            {
                "id": "1",
                "label": new_label,
                "url": new_url,
                "stable_key": build_citation_stable_key(citation_label=new_label, citation_link=new_url),
            },
            {
                "id": "2",
                "label": existing_label,
                "url": existing_url,
                "stable_key": build_citation_stable_key(citation_label=existing_label, citation_link=existing_url),
            },
        ],
    )

    assert mapping == {"1": "2", "2": "1"}
    assert rewrite_numbered_citations("A[citation:1] B[citation:2]", mapping) == "A[citation:2] B[citation:1]"
    assert state[KNOWLEDGE_CITATION_REGISTRY_KEY] == [
        {
            "id": "1",
            "label": existing_label,
            "url": existing_url,
            "stable_key": build_citation_stable_key(citation_label=existing_label, citation_link=existing_url),
        },
        {
            "id": "2",
            "label": new_label,
            "url": new_url,
            "stable_key": build_citation_stable_key(citation_label=new_label, citation_link=new_url),
        },
    ]


def test_merge_citation_registries_unions_overlapping_branches_by_stable_key() -> None:
    """Reducer for the LangGraph channel.

    Regression: ``knowledge_citation_registry`` had no Annotated reducer, so
    when the LLM emitted parallel tool calls in one step (e.g. two
    ``knowledge_search`` calls or ``knowledge_search`` alongside a finishing
    subagent) LangGraph raised INVALID_CONCURRENT_GRAPH_UPDATE because two
    Commands wrote the same channel. The reducer must dedupe by stable_key
    so overlapping shared entries collapse into one.
    """

    shared_label = "共享档案 第1页第1段"
    shared_url = "/api/knowledge/docs/shared.pdf?page_no=1&paragraph_no=1"
    branch_a_label = "甲分支档案 第2页第1段"
    branch_a_url = "/api/knowledge/docs/a.pdf?page_no=2&paragraph_no=1"
    branch_b_label = "乙分支档案 第3页第1段"
    branch_b_url = "/api/knowledge/docs/b.pdf?page_no=3&paragraph_no=1"

    shared_entry = {
        "id": "1",
        "label": shared_label,
        "url": shared_url,
        "stable_key": build_citation_stable_key(citation_label=shared_label, citation_link=shared_url),
    }
    branch_a_new = {
        "id": "2",
        "label": branch_a_label,
        "url": branch_a_url,
        "stable_key": build_citation_stable_key(citation_label=branch_a_label, citation_link=branch_a_url),
    }
    branch_b_new = {
        "id": "2",
        "label": branch_b_label,
        "url": branch_b_url,
        "stable_key": build_citation_stable_key(citation_label=branch_b_label, citation_link=branch_b_url),
    }

    # Branch A: existing shared + its new entry. Branch B: same shared entry +
    # a different new entry. The reducer applies branch B on top of branch A.
    branch_a_registry = [shared_entry, branch_a_new]
    branch_b_registry = [shared_entry, branch_b_new]

    merged = merge_citation_registries(branch_a_registry, branch_b_registry)

    assert merged == [shared_entry, branch_a_new, branch_b_new]


def test_merge_citation_registries_handles_none_branches() -> None:
    sample = {
        "id": "1",
        "label": "档案",
        "url": "/api/knowledge/docs/x.pdf",
        "stable_key": build_citation_stable_key(citation_label="档案", citation_link="/api/knowledge/docs/x.pdf"),
    }
    assert merge_citation_registries(None, [sample]) == [sample]
    assert merge_citation_registries([sample], None) == [sample]
    assert merge_citation_registries(None, None) == []
