# Constraint Management

Project Controls Constraint Management is an accepted product/domain area whose **current repository implementation is only the pure-domain foundation**.

This distinction is mandatory for planning.

## Accepted intent

Drive owns the accepted Constraint Management product/domain guidance. Current lane:

- Drive folder: `1zFeyfSbtkMo4zvwXZW5ZFxgumgD-m_8k`
- accepted backend/domain guidance package: `MYPA-PROJECT-CONTROLS-CONSTRAINT-MANAGEMENT-BACKEND-PACKAGE-20260903-001`

Use the cleaned Drive product-definition index to resolve current package identity.

## Implemented technical truth

Current `main` contains `src/my_pa/domain/project_controls/` with:

- `ProjectConstraint` aggregate and lifecycle vocabulary;
- publish-completeness rules;
- attention/record-quality vocabulary;
- In My Court rule;
- Project-scoped Constraint Category and prefix rules;
- BIC/Responsible party-reference vocabulary;
- business-day/date/timezone rules including default due, Due Soon and Overdue calculations.

The module explicitly states that this foundation **does not**:

- persist constraints/categories;
- allocate public codes;
- synchronize external workbooks/systems;
- expose public capabilities;
- implement MCP/BFF/frontend behavior;
- reach the Task domain.

Do not plan as if those layers already exist.

## What a complete implementation will need

A future implementation plan must reconcile accepted Drive intent to current repository truth across:

1. persistence tables/constraints/version/history;
2. Alembic migrations and any existing-data migration;
3. repository/unit-of-work ports;
4. application commands/use cases and conflict/idempotency semantics;
5. canonical capabilities and purposes;
6. HTTP/MCP exposure;
7. BFF contract/decoder/routes;
8. frontend product surface;
9. Excel/synchronization behavior if still part of accepted intent;
10. Task/Commitment relationships without coupling domains accidentally;
11. security/Principal/project identity;
12. tests, operations and documentation.

## Domain-first extension rule

Keep business-time/lifecycle/category/party rules pure. Infrastructure may persist their values but must not reimplement them in SQL/BFF/frontend.

If implementation needs a semantic change to accepted Constraint behavior, resolve product intent before coding rather than encoding a new meaning in persistence.

## Testing

Current domain primitives have focused unit tests. Later persistence/transport/frontend work requires new database/contract/security/E2E coverage; existing domain tests do not prove those layers.
