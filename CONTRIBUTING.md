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
- Use synthetic test data. Do not access personal sources, the existing physical database, credentials, deployment, or production unless a separate exact authorization explicitly permits it.

## Validation

Run the narrowest applicable command first, then the required tier:

- **FAST:** lint, format, type, unit, and contract tests; target ≤60 seconds.
- **PR:** FAST plus affected schema, migration, provider, security, and isolated integration tests; target ≤5 minutes.
- **FULL/SPECIALIZED:** run when the change or release decision requires them; see `AGENTS.md`.

Disclose every failure, skipped applicable test, unavailable dependency, and known limitation. Do not conceal instability with retries.

## Pull request

Use the pull-request template. Explain:

- objective and acceptance criteria;
- in scope and out of scope;
- why the implementation is minimal;
- tests run and results;
- architecture, privacy, dependency, migration, or operational impact;
- deferred work and operator-only actions.

Keep the PR single-purpose. Request review against the exact head. Under `AGENTS.md` section 8.1, the designated orchestration agent has standing operator-equivalent authority for routine branch, commit, push, pull-request, eligible squash-merge, and cleanup operations. Independent exact-head review remains mandatory. The operator retains only the extreme-risk actions enumerated in `AGENTS.md` section 8.2, including production activation, destructive or irreversible operations, credential mutation, live personal-data access, material risk acceptance, and policy amendment. Squash merge is the default.

## Documentation and decisions

Update documentation only for material behavior, contract, architecture, operations, security, or workflow changes. Add an ADR only for a durable cross-cutting decision that is costly to reverse. Issues, pull requests, tests, and Git history are the primary engineering record; Drive mirrors are review surfaces, not a competing ledger.
