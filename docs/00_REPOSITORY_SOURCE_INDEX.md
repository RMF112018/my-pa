# Repository Source Index

This is the current technical documentation router for `RMF112018/my-pa`.

## Start here

Normal development path:

1. [`../README.md`](../README.md) — repository orientation.
2. [`../AGENTS.md`](../AGENTS.md) — principal repository policy.
3. [`../AI_OPERATING_MANUAL.md`](../AI_OPERATING_MANUAL.md) — agent execution guidance.
4. this index.
5. the applicable current references below.

Accepted product and UX intent is owned by the cleaned MY-PA Drive library. Use the [current product-definition index](https://docs.google.com/document/d/1PAT3Vc6Y2POeqy5d9yHnnZLD5OWppsEw6Mwpv9UesNs/edit) when product intent is needed. Repository code/tests/current docs remain authoritative for executable technical truth.

## Development

- [`development/getting-started.md`](development/getting-started.md)
- [`development/development-workflow.md`](development/development-workflow.md)
- [`development/feature-development-playbook.md`](development/feature-development-playbook.md)
- [`development/testing-and-review.md`](development/testing-and-review.md)
- [`development/documentation-standards.md`](development/documentation-standards.md)

## Architecture

- [`architecture/00_ARCHITECTURE_INDEX.md`](architecture/00_ARCHITECTURE_INDEX.md)
- [`architecture/system-overview.md`](architecture/system-overview.md)
- [`architecture/backend-domain.md`](architecture/backend-domain.md)
- [`architecture/frontend-bff-pwa.md`](architecture/frontend-bff-pwa.md)
- [`architecture/data-and-storage.md`](architecture/data-and-storage.md)
- [`architecture/mcp-and-agent-integration.md`](architecture/mcp-and-agent-integration.md)
- [`architecture/authentication-security.md`](architecture/authentication-security.md)
- [`architecture/deployment-runtime.md`](architecture/deployment-runtime.md)

## Domains

- [`domains/tasks-and-commitments.md`](domains/tasks-and-commitments.md)
- [`domains/relationship-intelligence.md`](domains/relationship-intelligence.md)
- [`domains/constraint-management.md`](domains/constraint-management.md)
- [`domains/goodnotes-gsqs.md`](domains/goodnotes-gsqs.md)
- [`domains/quick-capture.md`](domains/quick-capture.md)
- [`domains/intelligence-and-reporting.md`](domains/intelligence-and-reporting.md)

## Operations

- [`operations/deployment.md`](operations/deployment.md)
- [`operations/observability.md`](operations/observability.md)
- [`operations/troubleshooting.md`](operations/troubleshooting.md)
- [`operations/recovery.md`](operations/recovery.md)
- [`operations/mcv-limitations.md`](operations/mcv-limitations.md) — evidence-bound current MCV limitations and the repository evidence that bounds them.

Detailed executed procedures remain under [`../ops/runbooks/`](../ops/runbooks/README.md).

## Platform mechanisms

- [`../native/apple-source-host/README.md`](../native/apple-source-host/README.md) — current read-only Apple host transport, including the Swift/AppleScript mechanism and TCC/activation boundary.

## Reference

- [`reference/database-migrations.md`](reference/database-migrations.md)
- [`reference/api-bff-contracts.md`](reference/api-bff-contracts.md)
- [`reference/mcp-capabilities.md`](reference/mcp-capabilities.md)
- [`reference/configuration.md`](reference/configuration.md)
- [`reference/glossary.md`](reference/glossary.md)

## Architectural decisions

Use [`decisions/00_ADR_INDEX.md`](decisions/00_ADR_INDEX.md). ADRs capture durable, cross-cutting, difficult-to-reverse choices. Ordinary implementation choices belong in code/tests/PRs.

## Security and contribution policy

- [`../SECURITY.md`](../SECURITY.md)
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md)
- [`security/threat-model.md`](security/threat-model.md)

## Retained material that is not normal current navigation

The following areas may contain valuable evidence or historical rationale but do not define current executable behavior merely because they are present:

- `docs/campaign/`
- `docs/plans/`
- `docs/migration/` campaign/cutover records
- `docs/testing/` completion/evidence reports
- `docs/governance/` historical audits
- `docs/specs/` mirrored product packages and control records
- `.ai/goals/`, evidence/review/findings folders
- generic scaffold READMEs

Use these only for an explicit historical/evidence question or when a current reference intentionally links to one.

## Current-source rule

When prose conflicts with code, schema, tests or authenticated runtime/repository evidence, follow the authority rules in `AGENTS.md` and correct the prose. Durable guides avoid embedding volatile branch names, commit SHAs, migration heads, capability counts and runtime status unless the value itself is the subject of a reference/evidence record.
