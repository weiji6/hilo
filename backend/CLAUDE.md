# Hilo backend development

Read ../AGENTS.md, ../docs/architecture.md and ../docs/domain-profiles.md.
Python 3.12+, LangGraph/LangChain, FastAPI, Qdrant and SQLite form the backend.

- Put domain-specific instructions and query rules in YAML profiles under examples/.
- AppConfig resolves profile paths relative to the configuration file, publishes the
  profile after validation, and resets it when resetting app configuration.
- Preserve source visibility, exact doc_ids, numbered citation registries and PDF
  physical page numbers. Navigation pages cannot support body factual claims.
- Ordinary questions use bounded direct retrieval; explicit deep research can
  delegate source-scoped lanes. Retrieval budgets must not truncate answer tokens.
- Both lead and child agents receive domain instructions. Profiles are process-wide.
- Keep HILO_* precedence and DEER_FLOW_* fallback behavior backward compatible.
- Run root make test and affected modules; use Ruff for changed Python files.
- Update README and architecture documentation with behavioral changes.

Hilo derives from DeerFlow. Preserve license notices and attribution. Do not export
local config, credentials, uploaded documents, private infrastructure or Git history.

Publication support: export the reviewed ingestion/maintenance/OCR helpers and
optional Kubernetes provisioner. Run test_publication_integrity.py when changing
source allowlists or default tool settings. LocalSandbox must work without zsh.
See ../CONTRIBUTING.md for reproducible tests and external-service validation limits.
