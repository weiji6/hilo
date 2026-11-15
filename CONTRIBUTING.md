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

Do not commit `.env` files, `config.yaml`, runtime data, uploaded documents,
or private deployment settings. Preserve upstream attribution and license
notices. PRs should describe the behavior change and its validation.
