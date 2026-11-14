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
