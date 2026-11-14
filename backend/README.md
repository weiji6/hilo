# Hilo backend

LangGraph runs the lead agent and research children; FastAPI serves knowledge,
uploads, artifacts, models, memory, and extension configuration. See the root
[quick start](../README.md), [architecture](../docs/architecture.md), and
[domain profile guide](../docs/domain-profiles.md).

Use Python 3.12+ and `uv sync --group dev`. Backend development commands:

```bash
uv run langgraph dev --no-browser --allow-blocking
uv run uvicorn src.gateway.app:app --port 8001
```

Run these in separate terminals with local `backend/.env` and root `config.yaml`.
The full-stack Docker template also provides authentication storage and Qdrant.

Core modules: `src/config/domain_config.py` (domain schema/lifecycle),
`src/community/knowledge_base/query_expansion.py` (profile-driven expansion),
`catalog.py` (visible source routing), `source_evidence.py` (body evidence),
`tools.py` (source tools), `citations.py` (citation registry), and
`src/agents/retrieval_policy.py` (ordinary vs explicit research routing).

`HILO_*` settings take precedence; `DEER_FLOW_*` environment aliases and internal
storage paths remain supported. Prior-task memory can be disabled with
`TASK_MEMORY_ENABLED=false` independently of source retrieval.

Run `make test` from the project root for framework regressions. The inherited
suite also includes provider/parser and historical application tests.
