from pathlib import Path

from src.config.app_config import AppConfig
from src.config.extensions_config import ExtensionsConfig


def test_repo_config_disables_file_write_tools(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        ExtensionsConfig,
        "from_file",
        classmethod(lambda cls, config_path=None: ExtensionsConfig()),
    )

    config_path = Path(__file__).resolve().parents[2] / "config.example.yaml"
    config = AppConfig.from_file(str(config_path))

    tool_names = [tool.name for tool in config.tools]

    assert "write_file" not in tool_names
    assert "str_replace" not in tool_names


def test_runtime_tool_registry_excludes_present_files(monkeypatch) -> None:
    tools_module = (Path(__file__).resolve().parents[1] / "src" / "tools" / "tools.py").read_text(encoding="utf-8")

    assert "present_file_tool" not in tools_module
    assert "present_files" not in tools_module


def test_runtime_tool_registry_exposes_knowledge_search() -> None:
    tools_module = (Path(__file__).resolve().parents[1] / "src" / "tools" / "tools.py").read_text(encoding="utf-8")

    assert "TEMPORARILY_DISABLED_TOOL_NAMES = set()" in tools_module
    assert "tool.name not in TEMPORARILY_DISABLED_TOOL_NAMES" in tools_module


def test_subtask_result_format_fully_replaces_summary_with_task_result() -> None:
    general_purpose = (Path(__file__).resolve().parents[1] / "src" / "subagents" / "builtins" / "general_purpose.py").read_text(encoding="utf-8")
    executor_source = (Path(__file__).resolve().parents[1] / "src" / "subagents" / "executor.py").read_text(encoding="utf-8")

    assert "## 任务结果" in general_purpose
    assert "## 摘要" not in general_purpose
    assert '"任务结果": "summary"' in executor_source
    assert '"摘要": "summary"' not in executor_source


def test_subagents_enable_checkpoint_middleware(monkeypatch) -> None:
    import importlib.util
    import sys
    from types import SimpleNamespace

    from src.agents.middlewares.knowledge_checkpoint_middleware import KnowledgeCheckpointMiddleware
    from src.agents.middlewares.subagent_tool_limit_middleware import SubagentToolLimitMiddleware
    from src.agents.retrieval_policy import OVERVIEW_SUBAGENT_PROMPT

    # conftest stubs the public executor import to break a circular dependency.
    # Load the real implementation separately and inspect actual agent construction.
    source = Path(__file__).resolve().parents[1] / "src" / "subagents" / "executor.py"
    spec = importlib.util.spec_from_file_location("_budget_executor_test", source)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_get_model_name", lambda *a: "test-model")
    models = []
    monkeypatch.setattr(module, "create_chat_model", lambda **kw: models.append(kw) or object())
    monkeypatch.setattr(module, "create_agent", lambda **kw: kw)
    for overview in (False, True):
        executor = object.__new__(module.SubagentExecutor)
        executor.overview = overview
        executor.config = SimpleNamespace(name="general-purpose", thinking_enabled=True, system_prompt="research")
        executor.parent_model = None
        executor.trace_id = "test"
        executor.tools = []
        agent = executor._create_agent()
        checkpoints = [m for m in agent["middleware"] if isinstance(m, KnowledgeCheckpointMiddleware)]
        budget = next(m for m in agent["middleware"] if isinstance(m, SubagentToolLimitMiddleware))
        assert bool(checkpoints) is (not overview)
        assert budget.tool_call_limit == (4 if overview else 20)
        assert models[-1]["thinking_enabled"] is (not overview)
        assert agent["system_prompt"] == (OVERVIEW_SUBAGENT_PROMPT if overview else "research")
        if overview:
            assert models[-1]["max_tokens"] == 768


def test_general_purpose_subagent_tool_allowlist() -> None:
    from src.subagents.builtins.general_purpose import GENERAL_PURPOSE_CONFIG

    allowed = set(GENERAL_PURPOSE_CONFIG.tools or [])
    assert allowed == {"knowledge_locate", "knowledge_checkpoint", "submit_task_result"}, (
        "general-purpose subagent must retain scoped retrieval and result submission; sandbox/bash/file tools must be handled by the lead agent before delegating"
    )
    assert "bash" not in allowed
    assert "read_file" not in allowed
    assert "ls" not in allowed


def test_general_purpose_subagent_no_sandbox_working_directory() -> None:
    from src.subagents.builtins.general_purpose import GENERAL_PURPOSE_CONFIG

    prompt = GENERAL_PURPOSE_CONFIG.system_prompt
    assert "/mnt/user-data/uploads" not in prompt, "subtask prompt must not reference sandbox upload paths; uploaded document content should be passed via task description from lead agent"
