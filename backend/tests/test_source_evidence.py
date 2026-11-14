"""Reject front matter as evidence and retrieve topic-matched body pages."""
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from src.community.knowledge_base import tools
from src.community.knowledge_base.source_evidence import page_kind, search_body_pages


def page(number, text):
    # This reproduces the broken imported book/PDF numbering, without trusting it.
    return dict(page_no=number, book_page_no=number, pdf_page_no=number, page_number_source='book', text=text)


def test_contents_and_copyright_are_not_body_but_intro_prose_is():
    assert page_kind('目 录\n第一章 北洋政府……1\n第二章 南京政府……39\n第三章 抗战财政……101') == 'toc'
    assert page_kind('第四章 财政崩溃……165\n第一节 收入……168\n第二节 支出……173') == 'toc'
    assert page_kind('民国财政史\n出版社出版\n1985年第一版\n统一书号：123 定价1元') == 'front_matter'
    assert page_kind('') == 'blank'
    assert page_kind('绪论\n' + '财政制度的变迁与战争筹款、税制调整和中央地方关系有关。' * 8) == 'body'
    assert page_kind('第一章\n本章的目录安排如下。\n' + '这一时期的财政收入主要来自关税、盐税和债务筹措。' * 8) == 'body'


def test_historical_contents_heading_and_merged_ocr_columns_are_navigation():
    assert page_kind('目次\n第一章 總論第一款 歷代財政概..·第一節 古代之財政..·\n第二款 國地收支之劃分..·') == 'toc'
    assert page_kind('第四款 財政方針之變遷..·第一節 財政方針..·第一目 周學熙..·第二目 熊希齡..·第三目 陳錦濤..·第四目 李思浩..·第二節 財政方針之現情..·第一目 古應芬..·第二目 孫科..·') == 'toc'
    assert page_kind('第一章 近代財政思潮之變遷 一 外力侵略之關係 四 學說灌輸之影響 民國續財政史 目次\n第一節 財政組織之變遷') == 'toc'


def test_each_query_finds_full_body_pages_not_the_keyword_dense_contents():
    payload = {'pages': [page(4, '目录\n北洋财政……1\n南京财政……39\n抗战财政……101\n战后财政……165'),
        page(7, '北洋政府财政收入不足，靠借债弥补赤字。' * 8),
        page(46, '南京政府财政关税、盐税和统税构成税收主要来源。' * 8),
        page(110, '抗战财政支出增加，田赋征实补充战时收入。' * 8),
        page(180, '战后财政赤字恶化，通货膨胀加剧。' * 8)]}
    results, missing = search_body_pages(payload, ['北洋政府财政', '南京政府财政', '抗战田赋征实', '战后财政通货膨胀'], pages_per_query=1)
    assert not missing
    assert {p['pdf_page_no'] for p in results} == {7, 46, 110, 180}
    assert all(p['evidence_kind'] == 'body' for p in results)
    assert results[0]['text'] == payload['pages'][1]['text']


def test_missing_body_match_is_disclosed_and_never_falls_back_to_contents():
    results, missing = search_body_pages({'pages': [page(4, '目录\n金圆券改革……209\n财政崩溃……210\n战后税收……211')]}, ['金圆券改革'])
    assert not results and missing == ['金圆券改革']


def patch_document(monkeypatch, pages):
    doc = SimpleNamespace(doc_id='book', title='民国财政史', filename='book.pdf', scope='global', source_url='/api/knowledge/docs/book.pdf', original_url=None, payload={'pages': pages})
    monkeypatch.setattr(tools, '_visible_catalog_entries', lambda **kw: [])
    monkeypatch.setattr(tools, '_resolve_requested_doc_ids', lambda ids, **kw: (ids, [], {}))
    monkeypatch.setattr(tools, 'locate_document', lambda *args, **kw: doc)
    return SimpleNamespace(context={}, state={})


def test_range_returns_contents_warning_but_only_body_can_register_citations(monkeypatch):
    runtime = patch_document(monkeypatch, [page(3, '民国财政史\n出版社出版\n1985年第一版\n统一书号：123'), page(4, '目录\n北洋……1\n南京……39\n抗战……101'), page(5, ''), page(6, '北洋财政收入不足，只得借债。' * 12)])
    result = tools.knowledge_locate_tool.func(runtime, doc_id='book', pdf_page_no=3, pdf_page_no_end=6)
    registry = runtime.state['knowledge_citation_registry']
    assert len(registry) == 1
    assert '目录' in result and '不能作为正文证据' in result
    assert 'PDF第6页' in registry[0]['label'] and '原书第6页' not in registry[0]['label']
    assert parse_qs(urlsplit(registry[0]['url']).query)['pdf_page_no'] == ['6']


def test_query_tool_cites_actual_body_pages_with_facet_labels(monkeypatch):
    runtime = patch_document(monkeypatch, [page(4, '目录\n北洋……1\n南京……39\n抗战……101'), page(7, '北洋财政收入不足，只得借债。' * 12), page(110, '抗战田赋征实，以实物征收补充收入。' * 12)])
    result = tools.knowledge_locate_tool.func(runtime, doc_id='book', queries=['北洋财政', '抗战田赋征实'])
    assert '主题: 北洋财政' in result and '主题: 抗战田赋征实' in result
    assert len(runtime.state['knowledge_citation_registry']) == 2
    assert all('原书' not in entry['label'] for entry in runtime.state['knowledge_citation_registry'])


def test_later_chapter_mentioning_earlier_period_does_not_displace_its_body():
    payload = {'pages': [page(6, '第一章 北洋政府时期的财政\n' + '财政短缺使中央长期依赖借债。' * 8), page(7, '北洋政府的财政收入不足，财政收入与借债共同支撑支出。' * 5), page(44, '第二章 南京政府时期的财政\n' + '财政制度开始调整。' * 8), page(64, '北洋政府的借债与南京政府的借债比较，财政收入与借债如何衔接。' * 12)]}
    results, _ = search_body_pages(payload, ['北洋政府 财政收入 借债'], pages_per_query=1)
    assert results[0]['pdf_page_no'] == 7
    assert '北洋' in results[0]['source_chapter']


def test_old_contents_marker_cannot_support_new_body_answer():
    from langchain_core.messages import HumanMessage, ToolMessage
    from src.agents.middlewares.citation_enforcement_middleware import _has_supported_body_citation
    messages = [HumanMessage(content='民国财政情况概览'), ToolMessage(name='knowledge_locate', tool_call_id='new-body', content='### 整页 1: PDF 第 44 页\n页面类型: body\ncitation: [citation:6]\n南京政府财政正文')]
    state = {'knowledge_citation_registry': [{'id': '2', 'label': '旧目录', 'url': '/book.pdf?pdf_page_no=4'}, {'id': '6', 'label': '正文', 'url': '/book.pdf?pdf_page_no=44'}]}
    assert not _has_supported_body_citation('南京时期的财政事实。[citation:2]', messages, state)
    assert not _has_supported_body_citation('财政事实。[citation:6] 另一事实。[citation:999]', messages, state)
    assert _has_supported_body_citation('南京时期的财政事实。[citation:6]', messages, state)
    assert not _has_supported_body_citation('未知事实。[citation:999]', [], None)


def test_parallel_page_tools_from_same_snapshot_keep_distinct_markers():
    from src.community.knowledge_base.citations import register_citation_marker, merge_citation_registries
    a, b = {}, {}
    first = register_citation_marker(a, citation_label='A PDF第7页', citation_link='/a.pdf?pdf_page_no=7', stable_ids=True)
    second = register_citation_marker(b, citation_label='B PDF第80页', citation_link='/b.pdf?pdf_page_no=80', stable_ids=True)
    merged = merge_citation_registries(a['knowledge_citation_registry'], b['knowledge_citation_registry'])
    assert first != second and len({x['id'] for x in merged}) == 2
    assert register_citation_marker({}, citation_label='A PDF第7页', citation_link='/a.pdf?pdf_page_no=7', stable_ids=True) == first
