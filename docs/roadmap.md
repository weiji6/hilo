# Roadmap

This file describes planned work, not existing capabilities or performance claims.

- Extract a small reusable Python API around source routing, evidence retrieval,
  and citation assembly while keeping the web workspace as a reference application.
- Build reproducible evaluations for source recall, evidence coverage, citation
  correctness, unsupported claims, latency, and model/tool cost.
- Move process-wide domain configuration into an explicit request-scoped context.
- Add a documented ingestion-provider interface and smaller optional dependency groups.
- Define a production authentication and authorization boundary for all backend APIs.
- Add additional domain examples with original, licensed, or public-domain fixtures.

The initial version provides declarative domain profiles, generic research prompts,
a runnable source project, synthetic examples, and publication hygiene tooling.
