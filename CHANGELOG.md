# Changelog

## Unreleased

Verify Hilo independently with a clean full-stack Docker acceptance job and
deterministic OpenAI-compatible HTTP fixtures. Cover MariaDB authentication,
text uploads, Qdrant indexing, custom Skills and cited answers over the
authenticated SSE proxy. Fix raw text indexing/location, text uploads requiring
OCR, scoped payload collisions, fresh Skills mounts, LangGraph factory discovery
and service startup readiness. Run all backend tests by default and enforce
Docker dependency parity with uv.lock. Make package mirrors configurable.

## 0.1.1 — 2026-11-15

Make Chinese the default README and retain a full English version. Restore
structured SQLite ingestion, OCR and knowledge maintenance entrypoints, and the
optional Kubernetes provisioner omitted from the initial source export. Restore
standard agent-tool configuration, support Linux shells without zsh, handle absent
static demo data, and add publication-integrity regressions. Document source-history
handling and the remaining external-service validation scope.

## 0.1.0 — 2026-11-14

Initial Hilo source release, derived from DeerFlow and the prior knowledge-research
application. Adds declarative domain profiles, shared configurable query expansion,
neutral default prompts with lead/child profile propagation, synthetic technical
documentation examples, a fiscal-history profile, portable local setup, and guarded
source-only publication. Existing source-location and citation work is preserved.
