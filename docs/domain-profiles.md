# Domain profiles

A profile is administrator-controlled YAML, not an executable plugin. Set
`domain.profile` in `config.yaml`; relative paths resolve from that file's directory.
Inline domain fields override whole fields loaded from the profile (not a deep merge).
Omit a profile to use the neutral `general` behavior.

```yaml
domain:
  profile: examples/technical-docs/domain.yaml
  name: my-technical-assistant
```

## Fields

| Field | Type | Purpose |
| --- | --- | --- |
| `name` | string | Human-readable domain identifier |
| `instructions` | string | Additional instructions for both lead and child agents |
| `query_aliases` | mapping of term to strings | Equivalent names for retrieval retries |
| `query_suffixes` | list of strings | Additional facets for broad unscoped retrieval |
| `query_facets` | mapping of trigger term to strings | Domain-specific decomposition facets |
| `rewrite_rules` | list of rules | Pattern-based focused queries |

A rewrite rule has `pattern`, nonempty `replacements`, and optional `when_contains`.
The latter limits activation to queries containing at least one trigger. Patterns
are Python regular expressions, validated at load; replacements are literal strings.
Use bounded, simple patterns from trusted administrators.

```yaml
name: technical-docs
instructions: |
  Cite version-specific behavior. Distinguish current behavior from proposals.
query_aliases:
  SSO: [single sign-on]
rewrite_rules:
  - pattern: '(?i)retry policy'
    replacements: [retry attempts, retry delay]
```

## Behavior and boundaries

- The original query is always first. Duplicate expansions are removed.
- General retrieval uses at most eight variants; document-scoped retrieval at most five.
- Retry suggestions use at most four expansions and remain local to the selected domain.
- ASCII aliases use word boundaries and case-insensitive matching. Overlapping names
  favor the longest match, avoiding repeated historical-period suffixes.
- A profile changes query text and agent guidance, not source visibility or document scope.
- Instructions apply to lead and child agents, including bounded research children.
- Unknown fields, empty alias keys, and malformed patterns fail validation.
- Profile changes require a backend restart or configuration reload in each process.
- Profiles are process-wide. Per-user/per-request profiles are not implemented.

## Adding a domain

Create a profile under `examples/`, add small original or redistributable documents,
and document questions with known and deliberately missing answers. Select the
profile, index the documents, and check source citations and refusal behavior.
Keep private books and business material out of the repository. Use custom Skills
for multi-step domain workflows and MCP for external tools; profile YAML is for
lightweight retrieval and reasoning adaptation.
