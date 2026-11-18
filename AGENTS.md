# Hilo development

Hilo is an LLM framework for Agentic Search, derived from DeerFlow. Its knowledge
layer provides Agentic RAG, evidence retrieval, citations, and research orchestration.
Keep upstream attribution and license notices. Domain-specific behavior belongs
in domain profiles and examples, not in reusable retrieval code.

- Backend instructions: `backend/AGENTS.md` and `backend/CLAUDE.md`.
- Frontend instructions: `frontend/AGENTS.md` and `frontend/CLAUDE.md`.
- Preserve compatibility with existing `DEER_FLOW_*` settings when adding Hilo settings.
- Keep README and architecture documentation synchronized with code changes.
- Never include local configuration, credentials, user documents, conversation
  data, or private deployment infrastructure in an open-source export.
