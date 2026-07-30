# AI Operating Manual

## Purpose

This manual governs model-assisted work in `RMF112018/my-pa`.

## Standard workflow

1. Establish objective, exact repository identity, scope, acceptance criteria, constraints, and prohibited actions.
2. Inspect repository truth and the nearest owning documentation.
3. Produce or confirm a bounded plan.
4. Obtain operator approval for implementation scope.
5. Execute on a dedicated branch, run proportional validation, and preserve evidence.
6. Request implementation review against the exact final head.
7. Merge, cleanup, deployment, production activation, destructive migration, secret mutation, and risk acceptance remain operator-gated unless exact authority explicitly covers the action.

## Evidence

The repository, pull request, CI, tests, and runtime are the primary engineering record. Durable Drive publications may supplement governance and handoff requirements but do not override repository truth.

Every claim must be labeled or supportable as fact, claim, assumption, inference, unknown, or unavailable evidence. Never claim independent verification without direct evidence.

## Architecture routing

- System and module decisions: `docs/architecture/`
- Accepted decisions: `docs/decisions/`
- Specifications: `docs/specs/`
- Security: `docs/security/`
- Testing: `docs/testing/`
- Operations: `docs/operations/`
- Findings and reviews: `docs/findings/`, `docs/reviews/`
- Goal lifecycle: `.ai/goals/`

## Prohibitions

Do not expose secrets, mutate authoritative sources, connect to the existing database, activate workers or schedules, deploy services, or represent scaffold files as implemented behavior without exact authorization and evidence.
