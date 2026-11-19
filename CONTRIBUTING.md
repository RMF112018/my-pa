# Contributing

`my-pa` is in Minimum Viable Candidate development. Keep changes small, explicit, and reviewable.

## Before coding

1. Read `AGENTS.md` and the nearest owning README or index.
2. Confirm one objective, acceptance criteria, in-scope behavior or paths, and explicit out-of-scope items.
3. Update local `main`, create a short-lived branch, and record the base SHA in the pull request.
4. Do not implement a scaffold directory or deferred feature without a current objective.

## Implementation

- Build the smallest correct solution. Do not add speculative abstractions, dependencies, infrastructure, compatibility layers, or unrelated cleanup.
- Preserve the domain/application/infrastructure dependency direction and the read-only source boundary.
- Keep current product names neutral: repository `my-pa`, Python namespace `my_pa`, configuration prefix `MY_PA_`.
- Use synthetic test data and isolated test stores by default. Routine development and correction proceed within an approved objective; live personal sources, credentials, the existing physical/production database, or production actions require a verified explicit authorization or separately adopted standing envelope.

## Validation

Run the narrowest applicable command first, then the required tier:

- **FAST:** lint, format, type, unit, and contract tests; target ≤60 seconds.
- **PR:** FAST plus affected schema, migration, provider, security, and isolated integration tests; target ≤5 minutes.
- **FULL/SPECIALIZED:** run when the change or release decision requires them; see `AGENTS.md`.

Disclose every failure, skipped applicable test, unavailable dependency, and known limitation. Do not conceal instability with retries.

## Pull request

Use the pull-request template. Explain the objective, acceptance criteria, scope, smallest correct implementation, applied checks, known limitations and any real deployment or privacy impact.

GitHub issues, commits, PR conversations and checks are the **routine** coordination record. An authorized delivery agent can carry out ordinary planning, coding and corrections without repeated operator callbacks. Independent exact-head review is required only when the applicable branch rules, accepted objective or evidenced risk requires it; self-review must never be presented as independent.

Routine noncritical findings can become explicit follow-up Issues after two focused correction cycles, but mandatory CI, confirmed critical exposure and authorization gaps remain blockers. No PR, tag or merge grants production or secret access. The operator retains the critical actions in `AGENTS.md` section 8.2.

## Documentation and decisions

Update documentation only for material behavior, contract, architecture, operations, security, or workflow changes. Add an ADR only for a durable cross-cutting decision that is costly to reverse. Issues, pull requests, tests, and Git history are the primary engineering record. After separately activated SDCR cutover and publisher qualification, all session deliverables and material evidence must also be automatically archived in MY-PA with stable manifest links; do not ask the operator to download/re-upload packages. Existing Workspace publication requirements remain until then.
