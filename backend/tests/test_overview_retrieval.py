"""Turn-local scope selection, bounded reading, and model-call regressions."""
import asyncio
from types import SimpleNamespace

import pytest
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.agents.retrieval_policy import is_overview_question, overview_from_messages
from src.agents.middlewares.overview_retrieval_middleware import OverviewRetrievalMiddleware
from src.agents.middlewares.subagent_tool_limit_middleware import SubagentToolLimitMiddleware
from src.community.knowledge_base.tools import _bounded_locate_range


@pytest.mark.parametrize('question', ['你知道民国时期财政史情况吗', '你了解清代财政吗？', '请简要介绍民国财政史', '介绍一下北洋财政的概况', '民国财政史情况如何', '民国财政史情况如何？', '民国财政史怎么样', '民国财政史的基本情况', '民国财政史概况', '请问民国财政史情况如何？'])
def test_intro_uses_small_scope(question):
    assert is_overview_question(question)


@pytest.mark.parametrize('question', ['详细介绍民国财政史', '你知道民国时期财政史情况吗，请给出原文和页码', '比较北洋与南京政府财政', '请介绍民国财政统计数据', '写一份民国财政报告', '请检索所有资料', '继续深入研究', '请全面概述民国财政', '详细说明民国财政史情况如何', '民国财政史情况如何？请给出页码', '民国财政史怎么样，比较各时期差异'])
def test_explicit_depth_or_other_intent_preserves_research(question):
    assert not is_overview_question(question)


def test_followup_does_not_inherit_intro_scope():
    assert not overview_from_messages([HumanMessage(content='你知道民国时期财政史情况吗'), AIMessage(content='...'), HumanMessage(content='请详细考证关税变化')])
    assert overview_from_messages([HumanMessage(content='你知道民国时期财政史情况吗'), ToolMessage(content='...', tool_call_id='x')])


@pytest.mark.parametrize('asynchronous', [False, True])
def test_model_switch_is_turn_local_and_cached(monkeypatch, asynchronous):
    import src.agents.middlewares.overview_retrieval_middleware as module
    calls = []
    fast = object()
    monkeypatch.setattr(module, 'create_chat_model', lambda **kw: calls.append(kw) or fast)
    middleware = OverviewRetrievalMiddleware('dsv4-0731')
    original_model = object()
    req = ModelRequest(model=original_model, messages=[HumanMessage(content='你知道民国时期财政史情况吗')], system_message=SystemMessage(content='base'), tools=[])
    seen = []
    def handler(request):
        seen.append(request)
        return ModelResponse(result=[AIMessage(content='ok')])
    async def async_handler(request):
        return handler(request)
    for _ in range(2):
        if asynchronous:
            asyncio.run(middleware.awrap_model_call(req, async_handler))
        else:
            middleware.wrap_model_call(req, handler)
    assert len(calls) == 1 and calls[0]['thinking_enabled'] is False
    assert 'max_tokens' not in calls[0], 'retrieval scope must not silently lower the configured generation limit'
    assert seen[0].model is fast and '整本书正文' in seen[0].system_message.content
    assert req.model is original_model and req.system_message.content == 'base'
    deep = req.override(messages=[HumanMessage(content='请详细研究')])
    assert middleware._scope_request(deep) is deep


@pytest.mark.parametrize('asynchronous', [False, True])
def test_small_budget_preserves_submission_tool(asynchronous):
    submit = SimpleNamespace(name='submit_task_result')
    locate = SimpleNamespace(name='knowledge_locate')
    messages = [ToolMessage(content='page', tool_call_id=str(i)) for i in range(6)]
    req = ModelRequest(model=object(), messages=messages, tools=[submit, locate])
    middleware = SubagentToolLimitMiddleware(tool_call_limit=6)
    seen = []
    def handler(request):
        seen.append(request)
        return ModelResponse(result=[AIMessage(content='done')])
    async def async_handler(request):
        return handler(request)
    if asynchronous:
        asyncio.run(middleware.awrap_model_call(req, async_handler))
    else:
        middleware.wrap_model_call(req, handler)
    assert seen[0].tools == [submit]
    assert '6 次' in seen[0].messages[-1].content


@pytest.mark.parametrize('start_key,end_key', [('page_no','page_no_end'), ('pdf_page_no','pdf_page_no_end')])
def test_large_ranges_report_exact_continuation(start_key, end_key):
    original = dict(page_no=None, page_no_end=None, pdf_page_no=None, pdf_page_no_end=None)
    original.update({start_key: 130, end_key: 175})
    args, notices = _bounded_locate_range('财政史.pdf', **original)
    assert args[start_key] == 130 and args[end_key] == 134
    assert f'{start_key}=135' in notices[0] and f'{end_key}=175' in notices[0]
    assert '尚未读取' in notices[0]


def test_small_and_invalid_ranges_retain_existing_validation():
    for start, end in [(12,13), (12,None), (12,11), (None,13)]:
        args, notices = _bounded_locate_range('doc', start, end, None, None)
        assert args['page_no'] == start and args['page_no_end'] == end
        assert not notices


def test_browser_text_blocks_are_classified_and_attachments_are_not():
    assert overview_from_messages([HumanMessage(content=[{'type': 'text', 'text': '你知道民国时期财政史情况吗'}])])
    assert not overview_from_messages([HumanMessage(content=[{'type': 'text', 'text': '你知道民国时期财政史情况吗'}, {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AA=='}}])])


@pytest.mark.parametrize('asynchronous', [False, True])
def test_overview_suggestions_do_not_add_model_roundtrip(asynchronous):
    from src.agents.middlewares.citation_enforcement_middleware import CitationEnforcementMiddleware
    class NoModelCalls:
        def invoke(self, *args, **kwargs):
            pytest.fail('overview must not make another LLM call for suggestions')
        async def ainvoke(self, *args, **kwargs):
            pytest.fail('overview must not make another LLM call for suggestions')
    req = ModelRequest(model=NoModelCalls(), messages=[], tools=[])
    kwargs = dict(request=req, user_question='你知道民国时期财政史情况吗', answer_body='概况', reference_section='')
    mw = CitationEnforcementMiddleware()
    result = asyncio.run(mw._generate_suggested_questions_async(**kwargs)) if asynchronous else mw._generate_suggested_questions_sync(**kwargs)
    assert isinstance(result, list)


def test_budget_exhaustion_forces_structured_submission():
    submit = SimpleNamespace(name='submit_task_result')
    req = ModelRequest(model=object(), messages=[ToolMessage(content='x', tool_call_id='x')], tools=[submit])
    scoped = SubagentToolLimitMiddleware(tool_call_limit=1)._build_stripped_request(req, 1)
    assert scoped.tool_choice == {'type': 'function', 'function': {'name': 'submit_task_result'}}


@pytest.mark.parametrize('pdf', [False, True])
def test_locate_bounds_before_extraction_and_keeps_page_citations(monkeypatch, pdf):
    from src.community.knowledge_base import tools as module
    monkeypatch.setattr(module, '_visible_catalog_entries', lambda **kw: [])
    monkeypatch.setattr(module, '_resolve_requested_doc_ids', lambda ids, **kw: (ids, [], {}))
    document = SimpleNamespace(doc_id='book', title='财政史', filename='book.pdf', scope='global', source_url='/book.pdf', original_url=None, payload={})
    monkeypatch.setattr(module, 'locate_document', lambda *a, **kw: document)
    captured = []
    def extract(**kwargs):
        captured.append(kwargs)
        return [{'page_no': 130, 'pdf_page_no': 142, 'paragraph_no': None, 'text': '财政收入和财政支出均受战争影响。' * 10}]
    monkeypatch.setattr(module, 'extract_document_context', extract)
    monkeypatch.setattr(module, '_build_locate_excerpt_citation', lambda **kw: '[citation:1]')
    key, end_key = ('pdf_page_no','pdf_page_no_end') if pdf else ('page_no','page_no_end')
    output = module.knowledge_locate_tool.func(SimpleNamespace(context={}, state={}), doc_id='book', **{key:130,end_key:175})
    assert captured[0][key] == 130 and captured[0][end_key] == 134
    assert '财政收入' in output and '[citation:1]' in output
    assert f'{key}=135' in output and '尚未读取' in output


@pytest.mark.parametrize('question_text', ['你知道民国时期财政史情况吗', '民国财政史情况如何', '民国财政史怎么样'])
def test_overview_direct_reading_tools_and_turn_budget(monkeypatch, question_text):
    import src.agents.middlewares.overview_retrieval_middleware as module
    monkeypatch.setattr(module, 'create_chat_model', lambda **kw: object())
    names = ['book_search', 'knowledge_locate', 'task', 'write_todos']
    tools = [SimpleNamespace(name=name) for name in names]
    mw = OverviewRetrievalMiddleware(orchestrator_only=True)
    question = HumanMessage(content=[{'type': 'text', 'text': question_text}])
    request = ModelRequest(model=object(), messages=[question], tools=tools)
    assert [t.name for t in mw._scope_request(request).tools] == ['book_search','knowledge_locate']
    after_route = request.override(messages=[question, ToolMessage(content='books', tool_call_id='b1', name='book_search'), ToolMessage(content='books', tool_call_id='b2', name='book_search')])
    assert [t.name for t in mw._scope_request(after_route).tools] == ['knowledge_locate']
    finished = after_route.override(messages=after_route.messages + [ToolMessage(content='pages', tool_call_id=str(i), name='knowledge_locate') for i in range(6)])
    assert not mw._scope_request(finished).tools
    assert '现在必须输出对用户原问题的完整回答' in mw._scope_request(finished).system_message.content
    research = request.override(messages=[HumanMessage(content='请详细考证民国财政制度')])
    assert [t.name for t in mw._scope_request(research).tools] == ['book_search','task','write_todos']


@pytest.mark.parametrize('question', [
    '民国财政情况概览', '概览一下民国财政收入结构', '民国财政史',
    '民国时期财政有什么特点？', '民国财政情况如何，主要有哪些阶段？',
    '财政制度是什么', '大致说说民国财政统计史', '民国财政史研究入门',
    '给我讲一下清末的关税制度', 'Republican China fiscal history overview',
    '请简单说说民国财政。\n我想先知道主要变化，不需要很多细节。',
])
def test_ordinary_questions_default_to_bounded_retrieval(question):
    assert is_overview_question(question)


@pytest.mark.parametrize('question', [
    '你好', '谢谢', '继续', '导出这段聊天为 PDF',
    '请详细比较北洋和南京政府财政', '请给出逐年财政统计数据',
    '核对这段引用的页码', '请写一份民国财政专题报告',
    'Research Republican fiscal history in depth with citations',
    '研究一下民国财政史', '我想研究民国中央地方财政关系',
])
def test_research_artifacts_and_controls_do_not_use_overview(question):
    assert not is_overview_question(question)


@pytest.mark.parametrize('asynchronous', [False, True])
@pytest.mark.parametrize('name', ['task', 'write_todos'])
def test_ordinary_question_cannot_dispatch_even_from_stale_tool_call(asynchronous, name):
    request = SimpleNamespace(
        tool_call={'name': name, 'id': 'stale-dispatch', 'args': {}},
        state={'messages': [HumanMessage(content=[{'type': 'text', 'text': '民国财政情况概览'}])]},
    )
    def forbidden_handler(request):
        pytest.fail('ordinary question must not reach dispatch/executor')
    async def forbidden_async_handler(request):
        return forbidden_handler(request)
    mw = OverviewRetrievalMiddleware()
    result = asyncio.run(mw.awrap_tool_call(request, forbidden_async_handler)) if asynchronous else mw.wrap_tool_call(request, forbidden_handler)
    assert isinstance(result, ToolMessage) and result.tool_call_id == 'stale-dispatch'
    assert result.status == 'error' and 'knowledge_locate' in result.content


@pytest.mark.parametrize('asynchronous', [False, True])
def test_explicit_research_dispatch_still_reaches_tool(asynchronous):
    request = SimpleNamespace(tool_call={'name': 'write_todos', 'id': 'research'}, state={'messages': [HumanMessage(content='请详细考证民国财政史')]})
    def handler(request):
        return 'dispatched'
    async def async_handler(request):
        return handler(request)
    mw = OverviewRetrievalMiddleware()
    result = asyncio.run(mw.awrap_tool_call(request, async_handler)) if asynchronous else mw.wrap_tool_call(request, handler)
    assert result == 'dispatched'


def test_overview_removes_conflicting_research_prompt_but_keeps_citations(monkeypatch):
    import src.agents.middlewares.overview_retrieval_middleware as module
    from src.agents.lead_agent.prompt import apply_prompt_template
    from src.agents.lead_agent.agent import _create_todo_list_middleware
    monkeypatch.setattr(module, 'create_chat_model', lambda **kw: object())
    original = apply_prompt_template(subagent_enabled=True, orchestrator_only=True)
    todo = _create_todo_list_middleware(True, subagent_enabled=True)
    request = ModelRequest(model=object(), messages=[HumanMessage(content='民国财政情况概览')], system_message=SystemMessage(content=original), tools=[])
    scoped = todo.wrap_model_call(request, OverviewRetrievalMiddleware(orchestrator_only=True)._scope_request)
    prompt = scoped.system_message.content
    assert '<subagent_system>' not in prompt and '<todo_list_system>' not in prompt
    assert 'Do not stop at overview' not in prompt and '拆成更多子任务' not in prompt
    assert '<citations>' in prompt and '<role>' in prompt and '不要派发子任务' in prompt
    assert request.system_message.content == original


@pytest.mark.parametrize('asynchronous', [False, True])
def test_bounded_answer_never_retries_with_dispatch_demands(asynchronous):
    from src.agents.middlewares.early_stop_detection_middleware import EarlyStopDetectionMiddleware
    request = ModelRequest(model=object(), messages=[HumanMessage(content='民国财政情况概览'), ToolMessage(content='books', name='book_search', tool_call_id='b')], tools=[])
    calls = []
    def handler(request):
        calls.append(request)
        return ModelResponse(result=[AIMessage(content='本次材料不覆盖此部分，若要核对需要进一步检索。')])
    async def async_handler(request):
        return handler(request)
    mw = EarlyStopDetectionMiddleware()
    if asynchronous:
        asyncio.run(mw.awrap_model_call(request, async_handler))
    else:
        mw.wrap_model_call(request, handler)
    assert len(calls) == 1
    research = request.override(messages=[HumanMessage(content='请深入考证民国财政'), request.messages[1]])
    assert mw._needs_enforcement(handler(research), research.messages)


def test_scope_wrapper_runs_after_todo_in_real_agent_chain(monkeypatch):
    from src.agents.lead_agent import agent as module
    monkeypatch.setattr(module, '_create_summarization_middleware', lambda: None)
    monkeypatch.setattr(module, 'get_app_config', lambda: SimpleNamespace(get_model_config=lambda name: None))
    chain = module._build_middlewares({'configurable': {'is_plan_mode': True, 'subagent_enabled': True}}, 'dsv4-0731')
    names = [type(m).__name__ for m in chain]
    assert names.index('OverviewRetrievalMiddleware') > names.index('TodoListMiddleware')
    assert names.index('OverviewRetrievalMiddleware') > names.index('EarlyStopDetectionMiddleware')
