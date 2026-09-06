# Documentation standards

The goal is a small current technical knowledge base, not a transcript of delivery history.

## Authority split

- Repository: current executable technical truth and developer guidance.
- Cleaned MY-PA Drive library: accepted product/UX intent, planning context, reviews/audits/evidence, coordination and retained history.

Do not mirror a Drive product package into current technical docs as though it were executable truth.

## What belongs where

### Root README
Use for orientation, supported scope, architecture glance, bootstrap, common commands, major integrations, limitations and routing.

Do not put branch identities, closed remediation history, audit chronology, old migration counts or temporary work-package status in README.

### `docs/development/`
How to work on the system: setup, workflow, feature planning, testing/review, documentation practice.

### `docs/architecture/`
Durable cross-cutting structure and boundaries: dependency direction, authority classes, BFF/MCP/auth/runtime architecture.

### `docs/domains/`
Durable semantics and extension guidance for major capability areas. Describe implemented behavior; explicitly distinguish accepted-but-not-yet-implemented intent.

### `docs/operations/`
Developer/operator concepts and routing to detailed procedures. Executed command transcripts and volatile runtime proof belong in runbooks/evidence, not the conceptual guide.

### `docs/reference/`
Stable lookup material for migrations, contracts, MCP, configuration and terminology.

### ADRs
Use only for durable, cross-cutting, difficult-to-reverse decisions. Include context, decision, alternatives/consequences, status and supersession.

### Historical/evidence material
Campaign plans, reviews, audits, receipts, completion reports and superseded specifications may remain for traceability but are excluded from normal current navigation.

## Current vs historical language

A current guide says what the code/contracts do now without recounting how they arrived there.

Prefer:

> The browser derives the Principal from the opaque server session.

Avoid:

> Corrected in WP-X after PR-Y because the previous branch used...

Chronology belongs in PRs/evidence/history.

## Volatile identities

Do not embed these in durable guides unless the document's purpose is evidence/current-state reporting:

- commit SHA/tree;
- branch/worktree;
- PR head;
- migration head/count;
- capability/test count;
- exact runtime health/deployment state.

Reference the executable source/command that derives the value instead.

## Examples and commands

Examples must:

- match current executable CLI/config names;
- use synthetic/inert values;
- avoid credentials/personal paths;
- identify destructive/production-sensitive steps;
- link to the authoritative runbook when the procedure is operationally consequential.

## Links

Use repository-relative links for repository files. The repository CI validates relative Markdown links.

Drive links should point to the cleaned current owning index/package, not an old scattered topology.

## Documentation changes with code

Update docs in the same change when code alters:

- public contract/capability;
- architecture/dependency boundary;
- persistence/migration convention;
- auth/security/data authority;
- configuration;
- deployment/operations/recovery;
- developer/test workflow;
- major domain semantics.

A code change that only adjusts internal implementation shape does not require prose churn if no durable contract changed.

## Avoid duplication

One concept has one primary current owner. Secondary docs should link rather than restate large tables or policy.

Particularly avoid duplicating:

- AGENTS policy;
- capability catalogs;
- environment-variable catalogs;
- BFF route inventories;
- CI job definitions;
- migration/test counts.

Use current executable sources and targeted references.

## Review expectations

Documentation review should verify:

- statement matches code/tests/config;
- current vs intent vs historical status is explicit;
- links resolve;
- examples are safe and executable;
- no secrets/private values appear;
- no stale branch/head/status claim is presented as current;
- no policy is duplicated inconsistently;
- current developer path reaches the material needed for extension.

## Supersession

When a formerly current document must be retained for historical value, prepend a clear supersession banner and remove it from current navigation. Do not silently leave a stale `CURRENT` label on retained history.
