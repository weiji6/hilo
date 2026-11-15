# Hilo architecture

## Framework boundary

Hilo is a source-based full-stack framework derived from DeerFlow. It currently
runs a LangGraph agent service and a separate FastAPI gateway behind a Next.js
workspace. It does not provide an independent, stable pip SDK.

The inherited runtime supplies agent execution, model integration, Skills, MCP,
sandbox abstractions, and memory infrastructure. Hilo's knowledge layer supplies
catalog routing, structured source location, body-page evidence, numbered citations,
and research orchestration around that evidence.

## Domain adaptations

`src/config/domain_config.py` validates a YAML domain profile when AppConfig loads.
A relative `domain.profile` path is resolved from the application YAML directory.
The profile is published to retrieval only after application model validation.
A default profile contains no fiscal-history assumptions. Resetting AppConfig
also resets the domain profile.

`query_expansion.py` shares alias and rewrite behavior between vector-retrieval
query variants and tool retry guidance. Original queries are preserved; expansion
is bounded and does not change the caller's authorized document identifiers.
Longer aliases win at overlapping positions. Rewrite replacements are literal,
not regular-expression backreferences.

The lead prompt and child-agent prompt both receive the administrator's domain
instructions. Universal source and citation constraints remain in core prompts.
Profiles are process-wide; changing profiles requires reloading configuration or
restarting backend processes. Request-level domain selection is future work.

## Source retrieval

1. `book_search` finds candidate documents in visible user, thread, or global scopes.
2. `knowledge_locate` resolves an exact document identifier and returns navigation,
   an explicit page range, or body-page search results for topic queries.
3. `source_evidence.py` excludes blank/navigation pages from body evidence and
   allocates complete pages across requested facets.
4. Citation records retain source identity and page/paragraph location.
5. The answer uses numbered registry entries. Missing evidence is surfaced.

`knowledge_search` is retained for prior-task results, not raw-document retrieval.
The quick-start configuration disables prior-task memory so first-time retrieval
does not depend on a populated memory collection.

UTF-8 Markdown/TXT uploads use the local text parser in all three knowledge scopes;
they do not require MinerU. Raw text files in the global docs root can also be
indexed and located without ingestion sidecars. Index rebuilds honor existing
ingestion records and exclude duplicate raw sources and records without an
indexable target. Structured payload JSON is not an ingestion record.
Thread and user locators read their scoped structured files rather than probing
the global SQLite corpus with a potentially colliding document identifier.

## Execution paths

Ordinary knowledge questions use direct bounded retrieval and non-thinking model
calls, preserving the configured generation allowance. Explicit deep-research
requests may route sources once, dispatch scoped research lanes, and synthesize
structured child results. The bounds limit orchestration work rather than truncate
answers. Child agents receive the same domain instructions.

## Runtime and deployment

`HILO_CONFIG_PATH`, `HILO_HOME`, and `HILO_EXTENSIONS_CONFIG_PATH` take precedence
when present. Existing `DEER_FLOW_*` aliases remain supported. Internal virtual
paths and persisted legacy data paths are retained for compatibility.

`docker/compose.hilo.yaml` provides a local development stack. Only nginx is
published, on localhost. Qdrant, auth database, runtime data, and LangGraph
checkpoints use named volumes. Public production API authorization is not provided
by this template; review SECURITY.md before exposing services.

Both backend services bind the same `extensions_config.json` and share a writable
`custom-skills` volume alongside the read-only public Skills mount. MCP tool loading checks
the shared configuration for changes. Docker's `backend/requirements.txt` is
exported from the frozen `uv.lock`; CI rejects dependency manifest drift.
Docker builds use official package registries by default, with configurable
Python/npm mirrors. The separate smoke Compose overlay uses deterministic HTTP
model fixtures and its own project volumes for complete stack acceptance.
Agent exports load the lead-agent factory lazily so a fresh process can import
the subagent executor without a circular import through the middleware chain.
The factory itself is a concrete module export because LangGraph discovers it
through the module dictionary. The proxy starts only after the gateway,
LangGraph API and frontend session endpoint pass their health checks.

## Source publication and supporting tools

The public repository starts from a reviewed source snapshot, with a new Git root;
this is not a transfer of the original private repository's commit graph. Upstream
license and attribution remain in LICENSE and NOTICE. Subsequent Hilo commits use
normal Git history. README.md is Chinese; README.en.md contains English documentation.

Default tools include knowledge retrieval, file/Skills reading, shell, web fetch,
and image search. LocalSandbox selects zsh when available, then bash, then /bin/sh,
so slim Linux images work without installing zsh. This executes in the backend
host/container; it is not an isolation boundary. Research subagents still receive
only scoped retrieval, checkpoint, and result-submission tools. Optional AIO and
Kubernetes sandbox providers require their own deployment and shared paths.

`scripts/ingest_structured_docs_to_db.py` restores the structured corpus → SQLite
paragraph/FTS workflow. `--docs-dir` determines the default adjacent paragraphs.db;
a missing database is rebuilt even if source files retain old .resolved markers.
`prewarm_knowledge_indexes.py`, `reindex_global_knowledge.py`, paragraph-ID
normalization, and `backend/scripts/local_ocr.py` provide optional maintenance/OCR
entrypoints. OCR requires an external MinerU gRPC service. Vector indexing remains
a separate operation from SQLite ingestion. HILO_CONFIG_PATH takes precedence over
the legacy alias in the restored ingestion and OCR helpers.

The exporter explicitly includes supported scripts and the generic provisioner,
while excluding private deployment/synchronization scripts. A regression exports
the real tree and checks runtime-source parity and supported entrypoints. See
[functionality audit](functionality-audit.md) for evidence and remaining limits.
