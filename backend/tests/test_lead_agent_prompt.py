import importlib.util
from pathlib import Path

_PROMPT_SPEC = importlib.util.spec_from_file_location(
    "test_lead_agent_prompt_module",
    Path(__file__).parent.parent / "src/agents/lead_agent/prompt.py",
)
prompt_module = importlib.util.module_from_spec(_PROMPT_SPEC)
assert _PROMPT_SPEC and _PROMPT_SPEC.loader
_PROMPT_SPEC.loader.exec_module(prompt_module)


def test_prompt_requires_joint_retrieval_and_historical_decomposition(monkeypatch) -> None:
    monkeypatch.setattr(prompt_module, "_get_memory_context", lambda: "")
    monkeypatch.setattr(prompt_module, "get_skills_prompt_section", lambda: "")

    prompt = prompt_module.apply_prompt_template()

    assert "Historical Reuse Before Dispatch Rule" in prompt
    assert "Book Search Routing Rule" in prompt
    assert "Subtask Source-Routing Rule" in prompt
    assert "runs exactly one `book_search` routing pass" in prompt
    assert "knowledge_folders" in prompt
    assert "Knowledge Folder Semantics Rule" in prompt
    assert "Scope Label Rule" in prompt
    assert "No Task-Memory Loop Rule" in prompt
    assert "Knowledge Search Is Not Raw Search Rule" in prompt
    assert "<knowledge_directory_tree>" not in prompt
    assert "Book Group Label Rule" in prompt
    assert "Layered Book Routing Rule" in prompt
    assert "Evidence-Gap Batch Rule" in prompt
    assert "Source Coverage Rule" in prompt
    assert "Todo Gate for Fresh Retrieval Rule" in prompt
    assert "Evidence-Sufficiency Exception Rule" in prompt
    assert "Todo Tracking Rule" in prompt
    assert "Cross-Book Synthesis Rule" in prompt
    assert "Evidence Sufficiency Rule" in prompt
    assert "Decomposition Workflow Rule" in prompt
    assert "Planning-With-Prior-Knowledge Rule" in prompt
    assert "One-Facet-Per-Query Rule" in prompt
    assert "Historical Person Rule" in prompt
    assert "Historical Period Rule" in prompt
    assert "Historical Question Types Rule" in prompt
    assert "Historical Analysis Core Rule" in prompt
    assert "Time-Span Closure Rule" in prompt
    assert "Canonical Node Check Rule" in prompt
    assert "Continuity-and-Rupture Rule" in prompt
    assert "Cause-Mechanism-Effect Rule" in prompt
    assert "Formal-Informal Institutions Rule" in prompt
    assert "Multi-Actor Perspective Rule" in prompt
    assert "Concept Hygiene Rule" in prompt
    assert "Historical Evaluation Rule" in prompt
    assert "北洋政府" in prompt
    assert "Distributed Evidence Rule" in prompt
    assert "Historical Report Rule" in prompt
    assert "Historical Answer Pattern Rule" in prompt
    assert "Historical Default Report Shape Rule" in prompt
    assert "Recommended Report Shape" in prompt
    assert "Suggested Questions Rule" in prompt
    assert "建议问题" in prompt
    assert "Task-Memory Gap Dispatch Rule" in prompt
    assert "下一步行动" in prompt
    assert "拟下发子任务" in prompt
    assert "Outputting a `建议问题` section signals that the answer is substantively complete" in prompt
    assert "Noise Filtering Rule" in prompt
    assert "Knowledge Checkpoint Rule" in prompt
    assert "knowledge_checkpoint` is mandatory" in prompt
    assert "Checkpoint Trigger Rule" in prompt
    assert "Checkpoint Cadence Rule" in prompt
    assert "High-Volume Context Rule" in prompt
    assert "Checkpoint Direction Rule" in prompt
    assert "Checkpoint Reading-Set Rule" in prompt
    assert "Checkpoint Next-Route Rule" in prompt
    assert "stop adding more raw retrieval and checkpoint first" in prompt
    assert "next investigation" in prompt
    assert "exact citation lines worth reusing" in prompt
    assert "knowledge_checkpoint" in prompt
    assert "Catalog Rescue Rule" in prompt
    assert "Query Formation Rule" in prompt
    assert "keyword pile-up" in prompt
    assert "vague" in prompt
    assert "Doc-ID Routing Rule" in prompt
    assert "Retry Discipline Rule" in prompt
    assert "Best-Match Source Rule" in prompt
    assert "Response Staging Rule" in prompt
    assert "回答正文" in prompt
    assert "Do not refuse after the first weak retrieval pass." in prompt
    assert "Return the answer directly in the conversation" in prompt
    assert "Direct Response Rule" in prompt
    assert "Table Citation Rule" in prompt
    assert "Data Coverage Rule" in prompt
    assert "Citation Offset Rule" in prompt
    assert "zero tolerated offset" in prompt
    assert "Strict Table/Data Citation Rule" in prompt
    assert "starts with `本表引文：`" in prompt
    assert "本表引文：" in prompt
    assert "All sources used for that table or data block must be listed there completely" in prompt
    assert "present_file" not in prompt
    assert "Final deliverables must be in `/mnt/user-data/outputs`" not in prompt
    assert "Final deliverables must be copied to `/mnt/user-data/outputs`" not in prompt
    assert "`核心通用书`" not in prompt
    assert "`专题支撑书`" not in prompt
    assert "`补充材料 / 参考工具书`" not in prompt


def test_prompt_supports_parallel_goal_subtasks_and_fiscal_historian_style(monkeypatch) -> None:
    monkeypatch.setattr(prompt_module, "_get_memory_context", lambda: "")
    monkeypatch.setattr(prompt_module, "get_skills_prompt_section", lambda: "")

    prompt = prompt_module.apply_prompt_template(
        subagent_enabled=True,
        qa_mode=True,
    )

    assert "History / Fiscal-History Orchestration Pattern" in prompt
    assert "任务目标 / 探索方向" in prompt
    assert "run ONE `book_search` pass for the question" in prompt
    assert "Each subtask receives a task goal AND the specific book(s) to read" in prompt
    assert "若已启用子代理且明显需要补充证据，可把检索拆成按 `任务目标 / 探索方向` 的并行子任务" in prompt
    assert "Todo Dispatch Rule" in prompt
    assert "Todo Gate for Fresh Retrieval Rule" in prompt
    assert "Evidence-Sufficiency Exception Rule" in prompt
    assert "let that call dispatch/wait for the subagent batch" in prompt
    assert "Auto-Drain Rule" in prompt
    assert "auto-drains the queued lanes" in prompt
    assert "Do not immediately duplicate the same batch with manual `task` calls" in prompt
    assert "Historian Voice Rule" in prompt
    assert "历史综合题默认补足这些维度" in prompt
    assert "Fiscal History Framing Rule" in prompt
    assert "Fiscal History Question Types Rule" in prompt
    assert "Fiscal History Answer Pattern Rule" in prompt
    assert "Fiscal History Report Shape Rule" in prompt
    assert "财政史问题要写得像历史学者" in prompt
