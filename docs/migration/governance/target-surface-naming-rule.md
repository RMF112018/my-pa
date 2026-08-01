# Neutral Target-Surface Naming Rule

**Criterion:** `P00-AC-08`  
**Canonical product namespace:** `my-pa` / `my_pa` / `MY_PA_`

## Public target surfaces

New names must be neutral on:

- public APIs, routes, schemas, event types, error codes, and SDK names;
- Python modules, packages, import paths, entry points, command names, and service names;
- environment variables, configuration keys, database logical names, and deployment identifiers;
- MCP server, tool, resource, prompt, and capability names;
- user-facing product surfaces, documentation headings, screenshots, examples, and generated projections;
- new repository paths, branch names, issue titles, PR titles, labels, releases, and package metadata.

Use:

- repository/product: `my-pa`;
- Python/database logical namespace: `my_pa`;
- environment prefix: `MY_PA_`.

## Prohibited current naming

Do not introduce a former-employer name, initials, hostname alias, acronym-derived namespace, or compatibility label as a current public identity.

A neutral wrapper may not expose a prohibited current name in its path, environment variable, API operation, MCP capability, UI label, or emitted event type.

## Permitted exceptions

Exact legacy names may remain only when necessary and explicitly classified as one of:

- `HISTORICAL_EVIDENCE`;
- `READ_ONLY_SOURCE_IDENTITY`;
- `COMPATIBILITY_ALIAS`;
- `MIGRATION_PROVENANCE`;
- `QUOTED_FINDING_OR_TEST_FIXTURE`.

An exception must state why the exact string is necessary, must not create a new callable/public surface, and must not imply current ownership or authority.

## Validation boundary

The deterministic validator scans current public target surfaces for known legacy patterns while excluding governed migration evidence and explicitly classified historical/compatibility records. New exceptions require review and an allowlist entry tied to a durable reason.
