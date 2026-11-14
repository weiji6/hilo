# Hilo workspace

Next.js 16, React 19, TypeScript, LangGraph SDK, and Better Auth with MySQL.
The frontend provides streaming conversations, document and knowledge-space
management, citation display, and research progress.

Use the root [Docker quick start](../README.md) for a complete local environment.
For frontend development use Node.js 22+, pnpm 10.26.2, `pnpm install`, then
`pnpm dev`. Configure `frontend/.env` from the example. A running MySQL-compatible
DB and a migrated Better Auth schema are required for account-backed use.

Validation: `pnpm typecheck` and lint affected files. `pnpm check` runs lint and
type checking. The inherited UI has no automated browser test suite.

The Hilo brand is subject-neutral. Domain-specific UI demos and private recordings
are excluded from source releases. Source attribution remains in the About panel.
