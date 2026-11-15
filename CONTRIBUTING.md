# Contributing to Hilo

Use Python 3.12+, Node.js 22+, pnpm 10.26.2, and uv.

```bash
make config
make install
make test
```

The Docker quick start in README.md includes Qdrant and the authentication
DB. Backend-only development uses `cd backend && uv run langgraph dev
--no-browser --allow-blocking` and, in another terminal, `uv run uvicorn
src.gateway.app:app --port 8001`. Set provider keys in `backend/.env`.

Keep domain rules in YAML profiles under `examples/`. Reusable retrieval and
citation code must remain independent of a particular subject. Preserve the
source document scope and exact citation registry entries when changing retrieval.
Tests should cover domain isolation, source visibility, or evidence correctness.

Run `make test` for the full backend suite and `cd frontend && pnpm typecheck`
for frontend edits. Run Ruff on changed Python files. Runtime workflow tests
use local deterministic model/embedding fixtures, real HTTP routes and embedded
Qdrant; no production credentials or OCR service are required.

After changing backend dependencies, regenerate the Docker manifest from
`backend/` with `uv export --frozen --no-dev --no-hashes --no-emit-project
--no-header --format requirements-txt --output-file requirements.txt`.
CI checks that it matches the lockfile.

The `stack` CI job builds and starts all Docker services in a fresh checkout,
using `docker/compose.smoke.yaml` and deterministic OpenAI-compatible HTTP
fixtures. It checks MariaDB authentication, uploads, Qdrant indexing, custom
Skills and the authenticated LangGraph SSE proxy. It does not assess model
quality. To reproduce, use a **disposable checkout** with no existing local
configuration and a free localhost port 2026:

```bash
python3 scripts/init_config.py --example technical-docs
python3 backend/tests/stack_smoke.py --prepare
docker compose -p hilo-smoke -f docker/compose.hilo.yaml -f docker/compose.smoke.yaml up --build -d
docker compose -p hilo-smoke -f docker/compose.hilo.yaml -f docker/compose.smoke.yaml exec -T gateway python -m src.community.knowledge_base.indexer
python3 backend/tests/stack_smoke.py
python3 backend/tests/stack_lifecycle.py --phase before --state-file /tmp/hilo-smoke-state.json
docker compose -p hilo-smoke -f docker/compose.hilo.yaml -f docker/compose.smoke.yaml down
docker compose -p hilo-smoke -f docker/compose.hilo.yaml -f docker/compose.smoke.yaml up -d
python3 backend/tests/stack_lifecycle.py --phase after --state-file /tmp/hilo-smoke-state.json
docker compose -p hilo-smoke -f docker/compose.hilo.yaml -f docker/compose.smoke.yaml down -v
rm -f /tmp/hilo-smoke-state.json
```

The preparation step replaces the disposable checkout's provider settings with
fixture endpoints. The verifier creates synthetic accounts and documents; never
run it against an existing deployment. The lifecycle verifier checks scope
binding, missing-evidence refusal, provider recovery, and retention across a
graceful container recreation. Its state file contains synthetic credentials and
must stay outside the repository. Default Docker builds use official
Debian, PyPI and npm registries; `PIP_INDEX_URL` and `NPM_REGISTRY` build arguments
can select alternative package mirrors.

Do not commit `.env` files, `config.yaml`, runtime data, uploaded documents,
or private deployment settings. Preserve upstream attribution and license
notices. PRs should describe the behavior change and its validation.
