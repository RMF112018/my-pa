# Repository Governance

`AGENTS.md` is the principal normative policy for `RMF112018/my-pa`. `CONTRIBUTING.md` governs the human contribution workflow and `SECURITY.md` governs security reporting and data handling. Tool-specific files are routers only.

## 1. Authority and current stage

Use this precedence when facts conflict:

1. authenticated runtime evidence;
2. authenticated repository and GitHub state;
3. accepted repository specifications, ADRs, and this policy;
4. indexed Workspace publications;
5. conversations, reports, and legacy repositories as claims or historical evidence.

The product is in **Minimum Viable Candidate (MCV)** development through August 2, 2026. The objective is one complete, read-only vertical slice—not a broad platform.

Every change must state one objective, acceptance criteria, in-scope paths or behavior, and explicit out-of-scope items. A discovered feature goes to the backlog unless it is essential to the accepted objective. A scaffold directory is not implementation authority.

## 2. Minimum correct implementation

Prefer the smallest correct implementation that satisfies the accepted objective and tests.

- Apply YAGNI. Do not add speculative abstractions, frameworks, plugin systems, extension points, factories, registries, service layers, compatibility layers, or interfaces without a current demonstrated need.
- A dependency must solve a current problem that cannot reasonably be solved with the standard library or an approved dependency. Avoid duplicate libraries for the same purpose.
- A new process, daemon, queue, cache, database technology, infrastructure service, or deployment component requires a durable architectural justification.
- During MCV, do not introduce microservices, Redis, Celery, a graph database, a dedicated vector database, Kubernetes, or equivalent infrastructure without a measured requirement and explicit scope change.
- Use async code only where real I/O concurrency justifies the additional lifecycle, testing, and debugging complexity.
- Limited duplication is preferable to a premature abstraction when shared behavior is not yet stable.
- Remove dead code, obsolete flags, abandoned experiments, and unused compatibility paths.
- Do not perform unrelated cleanup or “while we are here” refactors.
- The legacy repository may supply behavioral evidence, edge cases, and migration knowledge. Do not copy it wholesale or treat its architecture as authoritative.
- Each pull request must explain why its implementation is minimal and identify what was intentionally deferred.

## 3. MCV scope boundary

Unless the operator explicitly reprioritizes the objective, defer:

- multi-user operation, SaaS hosting, high availability, broad provider support, or production-scale orchestration;
- full NAS indexing or automatic traversal of unreferenced content;
- speculative AI automation, autonomous source mutation, or generalized agent frameworks;
- additional databases, caches, queues, worker types, or deployment environments;
- implementation merely because a scaffold path exists.

Pull requests are single-purpose, short-lived, and reviewable. State scope changes explicitly; never hide them in implementation details. Favor one end-to-end vertical slice over multiple partial systems.

## 4. Architecture boundaries

Preserve these boundaries unless an accepted ADR supersedes them:

- `domain` depends on neither application nor infrastructure code.
- `application` depends inward on domain contracts and ports.
- `infrastructure` implements ports; composition belongs in application entry points or bootstrap code.
- Source providers and managed-document stores are separate capabilities.
- Original source systems are authoritative and read-only by default.
- Managed-document writes occur only in designated managed storage.
- PostgreSQL is the canonical metadata and knowledge store. PostgreSQL full-text search and `pg_trgm` are the initial search mechanisms.
- `pgvector` or another semantic index remains behind an abstraction and a benchmark gate; it is not an MCV prerequisite.
- The logical database identity is `my_pa`. An existing physical compatibility alias does not authorize a rename, migration, connection, or mutation.
- Obsidian is a deterministic, rebuildable projection, not a canonical source.
- Provider-specific details do not leak into domain models.
- Model-generated content carries provenance and must not silently overwrite authoritative evidence.
- External API and MCP capability names remain neutral and contain no former-employer branding.
- Destructive source actions require separate, explicit operator authorization.

Do not turn these boundaries into additional layers or interfaces before a concrete use requires them.

## 5. Security, privacy, and data handling

The default is local-first, least-privilege, and fail-closed.

- Never commit credentials, tokens, private keys, connection strings, personal data, or unredacted source evidence.
- Use environment configuration for secrets. Provide only non-secret examples and safe defaults.
- Logs must exclude message bodies, document contents, contact details, access tokens, and sensitive query text by default. Prefer stable identifiers, event types, and redacted metadata.
- Tests use small synthetic fixtures. Live email, calendar, contacts, NAS content, or production credentials are prohibited.
- External model or cloud processing requires an explicit eligibility decision for the data involved. Local data is not implicitly eligible for disclosure.
- Source attribution and generated-content provenance are required wherever derived records may be mistaken for authoritative facts.
- Security-relevant actions and denied destructive attempts should produce proportionate audit events without storing sensitive payloads.
- Operational scripts must require explicit targets, fail closed, support dry-run where meaningful, and never infer destructive intent.
- Deployment, production activation, credential mutation, destructive data operations, and risk acceptance remain operator-gated.

Follow `SECURITY.md` for reporting and response handling.

## 6. Dependencies, database changes, and operations

- Keep runtime and development dependencies in one `pyproject.toml` when package implementation begins. Pin direct application dependencies to compatible ranges and use a reproducible lock or constraints strategy selected in that implementation PR.
- Explain the current use, maintenance cost, security surface, and removal path for every new dependency.
- Add weekly Dependabot updates for Python only after a Python manifest exists; GitHub Actions updates may run immediately.
- Use Alembic for schema changes once database implementation exists. Test migrations against an isolated database from an empty schema to head and, when relevant, from the preceding supported revision.
- Migrations must be forward-safe, reviewable, and free of implicit destructive behavior. Never target an unknown or unverified existing physical database.
- Configuration changes must document defaults, validation, secret status, and backward-compatibility impact.
- Background jobs must be idempotent, observable, bounded, and safe to retry when implemented.
- Release readiness requires passing the applicable test tier, documented known limitations, and an operator decision. A tag or release does not authorize deployment.

## 7. Testing policy

Tests prove behavior and contracts, not internal implementation shape.

### FAST

Default local loop. Target **60 seconds or less** during MCV.

- Ruff lint and format checks;
- targeted type checking;
- unit, domain, and application contract tests;
- no database, network, connector, model, or end-to-end access.

### PR

Required pull-request gate. Target **5 minutes or less** during MCV.

- FAST;
- changed schema and migration checks;
- provider/connector conformance tests using fakes or synthetic fixtures;
- focused isolated-database integration tests when the change affects persistence;
- security and policy regression tests relevant to the change.

Do not omit a critical contract merely to meet the target. Adjust the target from measured evidence rather than silently reducing coverage.

### FULL

Run on `main`, manually, or on a controlled schedule when it would make ordinary pull requests materially slower. Initial target: **15 minutes or less**.

- full isolated-database integration suite;
- end-to-end synthetic vertical slices;
- recovery and idempotency tests;
- broader provider conformance;
- packaging and migration-from-empty validation.

### SPECIALIZED

Run on demand or when directly affected:

- live-provider canaries with dedicated non-personal test accounts;
- extraction, embedding, search-quality, or model evaluations;
- performance, load, recovery, and runtime-attestation tests.

Specialized tests never use live personal data and do not enter the ordinary PR gate without evidence that the risk and runtime justify it.

### Test organization

Register and enforce markers: `slow`, `database`, `network`, `connector`, `evaluation`, `e2e`, and `recovery`. Use small explicit fixtures; share fixtures only when that reduces duplication without hiding setup. Tests must be deterministic and isolated.

Do not accept flaky tests, silent retries, or uncontrolled retry loops. A quarantined test requires an issue, owner, reason, replacement coverage where possible, and an expiry or exit condition. Coverage is supporting evidence, not the definition of quality.

Measure tier duration and expensive resource use. Cache dependencies and tool state where it reduces work. Cancel superseded CI runs. Parallelize only deterministic tests with a measured benefit. Do not run the same expensive suite in multiple jobs without a stated reason.

A test enters the PR gate when it protects a critical contract or has repeatedly caught material regressions at acceptable cost. It leaves the PR gate only when moved to FULL or SPECIALIZED with documented risk coverage.

## 8. Git and GitHub workflow

A normal MCV change uses:

1. one bounded issue or objective;
2. a short-lived branch from current `main`;
3. a focused pull request using the repository template;
4. proportionate automated checks;
5. review against the exact head;
6. squash merge and branch cleanup by the operator, or by a delegated orchestration agent under section 8.1.

Do not push directly to protected `main`. Do not self-approve, accept risk, deploy, or activate production. Merge only under section 8.1 or explicit operator instruction. Later commits invalidate prior exact-head review.

### 8.1 Delegated merge authority

The operator may delegate squash merge and branch cleanup to one orchestration agent. The delegation is bounded by the conditions that make it safe and confers nothing else. The current designation is recorded in the pull request that establishes it.

A delegated merge is permitted only when all of the following hold:

- the exact head has passed an independent review by a context that did not author the change, that had authority to block, and that was not instructed toward an outcome;
- that review is against the current head, since a later commit invalidates it and this permission with it;
- the applicable test tier passes, and its result is stated rather than assumed;
- the change carries no operator-only action.

The delegated agent may not approve its own change, act as its own reviewer, or widen this delegation. Risk acceptance, deployment, production activation, credential mutation, destructive data operations, live personal-data access, and amendment of this policy remain operator-only.

The operator may withdraw the delegation at any time, and it does not survive a change of objective. A merge performed under it names the reviewing context and the reviewed head, so the authority a merge rested on stays legible afterwards.

Use ADRs only for durable, cross-cutting, difficult-to-reverse decisions. Ordinary implementation choices belong in code, tests, issues, and pull requests. Update documentation only when behavior, contracts, architecture, operations, or developer workflow materially changes.

## 9. Mandatory stops

Stop and report the blocker when:

- repository or base identity has drifted;
- the objective, acceptance criteria, or path scope materially conflicts;
- credentials, production access, destructive data operations, or undisclosed irreversible actions become necessary;
- a security, privacy, or data-loss risk cannot be contained within the accepted scope;
- the change requires a new architecture component not covered by the accepted objective.
