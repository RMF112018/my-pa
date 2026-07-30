# ADR-002: Database Identity and Existing-Database Compatibility Alias

- **Status:** Accepted with deferred physical alias value
- **Decision ID:** `PKL-MYPA-D-003`
- **Repository:** `RMF112018/my-pa`
- **Scope:** Naming and compatibility contract only

## Context

The new repository requires neutral product naming, but an existing database must remain addressable during transition. Renaming or migrating that database is outside the scaffold scope.

## Decision

- The canonical logical database identity is `my_pa`.
- New roles, schemas, code, documentation, and configuration use `my_pa` / `MY_PA_`.
- Runtime configuration will support an explicit compatibility alias that maps the canonical logical identity to the existing physical database.
- The physical alias value is intentionally not embedded in this scaffold. It must be supplied and verified during the separately authorized database-foundation goal.
- The canonical connection variable remains `MY_PA_DATABASE_URL`; any compatibility metadata must be non-secret and must not replace the connection authority.
- This exception is limited to database compatibility. It does not permit legacy aliases in external APIs, MCP capabilities, package names, service names, or new repository paths.

## Consequences

- Existing data can be addressed without prematurely renaming the physical database.
- No schema migration, connection attempt, credential change, or data mutation occurs in this goal.
- The alias must fail closed when absent, ambiguous, or inconsistent with the approved database identity.
