# Repository Governance

`AGENTS.md` is the principal normative policy for `RMF112018/my-pa`. `CONTRIBUTING.md` governs the human contribution workflow and `SECURITY.md` governs security reporting and data handling. Tool-specific files are routers only.

## 1. Authority and current stage

Use this precedence when facts conflict:

1. authenticated runtime evidence;
2. authenticated repository and GitHub state;
3. accepted repository specifications, ADRs, and this policy;
4. indexed Workspace publications;
5. conversations, reports, and legacy repositories as claims or historical evidence.

The product is in **Minimum Viable Candidate (MCV)** development. The objective is one complete vertical slice—not a broad platform.

That slice was read-only until 2026-08-01, when the operator reprioritized the objective to admit Relationship Intelligence and Quick Capture. Quick Capture creates records the product itself owns, which section 4 bounds through ADR-003; it is not a source-system write and not a managed-document write. Everything else the slice excluded remained excluded at that point; section 3 records later bounded reprioritizations, and no broader promotion may be inferred from them.

This section previously ran the MCV "through August 2, 2026". That date has passed and no replacement is set, because choosing one is an operator decision rather than a drafting choice. Until it is set, the MCV runs until the operator declares it complete. The open decision is recorded in [`docs/plans/mcv-completion-plan.md`](docs/plans/mcv-completion-plan.md) section 14.

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

The operator first exercised that reprioritization on 2026-08-01, admitting **Relationship Intelligence** and **Quick Capture**. Both are recorded with the work packages that carry them in [`docs/plans/mcv-completion-plan.md`](docs/plans/mcv-completion-plan.md) sections 12 and 13. Managed documents, the Obsidian projection, live personal-data connector access, and public research remain deferred.

On 2026-08-21, the operator expressly admitted only **WP-FE-03 — Work: Tasks and Commitments** to bounded frontend implementation. This narrow promotion preserves the accepted ADR-004 synthetic-development identity, verified server session, and backend-for-frontend boundary. **WP-FE-02 — WebAuthn/passkey authentication replacement remains blocked**, and WP-FE-04 and later phases plus every other frontend surface remain deferred unless separately reprioritized. WP-FE-03 does not authorize auth replacement, WebAuthn/passkeys, credential persistence or recovery, Entra/MSAL removal, deployment or production activation, production or shared-database access, credentials or live personal data, new infrastructure, destructive action, or risk acceptance.

A promoted feature is still bound by everything else in this policy — admitting it to scope is not admitting its whole specification.

Pull requests are single-purpose, short-lived, and reviewable. State scope changes explicitly; never hide them in implementation details. Favor one end-to-end vertical slice over multiple partial systems.

## 4. Architecture boundaries

Preserve these boundaries unless an accepted ADR supersedes them:

- `domain` depends on neither application nor infrastructure code.
- `application` depends inward on domain contracts and ports.
- `infrastructure` implements ports; composition belongs in application entry points or bootstrap code.
- Source providers and managed-document stores are separate capabilities.
- Original source systems are authoritative and read-only by default.
- Managed-document writes occur only in designated managed storage.
- Records the user authors inside `my-pa` are a third authority class under [ADR-003](docs/decisions/ADR-003-product-owned-user-authored-source-records.md): product-owned, append-only, and held in PostgreSQL. They are neither source-system writes nor managed-document writes, and they grant the read-only source-provider port no write method.
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
6. squash merge and branch cleanup by the operator or the designated orchestration agent under section 8.1.

Do not push directly to protected `main`. Merge only under section 8.1 or explicit operator instruction. Later commits invalidate prior exact-head review.

### 8.1 Standing orchestration authority

The operator grants the single designated orchestration agent standing authority to act as the operator's delivery representative for routine, bounded repository and GitHub lifecycle work. This delegation exists to keep the operator out of ordinary execution loops and remains effective for the current MCV campaign until the operator withdraws it or the objective moves outside the accepted MCV scope.

Within an accepted objective, the designated orchestration agent may, without additional operator confirmation:

- create, switch, update, and remove bounded work branches and worktrees;
- stage files, create commits, amend unreviewed commits, rebase or synchronize a feature branch, and resolve routine conflicts;
- push feature branches and tags that do not publish a release or activate production;
- create, edit, label, and close issues and pull requests; request reviews; respond to findings; and manage ordinary repository metadata;
- instantiate, authorize, and direct specialized worker agents under section 8.3, including concurrent workers when the orchestration agent has established dependency independence and non-overlapping write ownership, and approve those workers' routine repository operations;
- run local and CI validation against synthetic or explicitly eligible data and use verified isolated test databases;
- decide routine technical, architectural, sequencing, corrective, and recovery matters within the accepted objective;
- accept bounded, reversible implementation risk that does not meet the extreme-risk definition in section 8.2;
- squash merge an eligible pull request and clean up its feature branch and worktree when every merge condition below is satisfied.

A delegated merge is permitted only when all of the following hold:

- the exact head has passed an independent review by a context that did not author the change, that had authority to block, and that was not instructed toward an outcome;
- that review is against the current head, since a later commit invalidates it and this permission with it;
- the applicable test tier passes, and its result is stated rather than assumed;
- the change carries no extreme-risk action reserved by section 8.2.

The designated orchestration agent may approve routine lifecycle actions and worker requests on the operator's behalf, but may not treat its own implementation review as the required independent exact-head review. It may not widen this delegation or delegate final campaign accountability.

The operator may withdraw the delegation at any time. A merge performed under it names the reviewing context and reviewed head, so the authority supporting the merge remains legible.

### 8.2 Extreme-risk actions reserved to the operator

Only the operator may authorize:

- irreversible destruction, deletion, retirement, or corruption of canonical or irreplaceable data;
- disclosure or external transfer of personal, confidential, privileged, regulated, or credential-bearing data outside an already authorized boundary;
- production deployment or activation, destructive production migration, or externally consequential cutover;
- acceptance of material security, privacy, legal, compliance, financial, contractual, or operational risk;
- expenditure, procurement, subscription, or financial commitment outside an already approved mechanism and amount;
- bypassing or weakening repository governance, acceptance criteria, security controls, or independent-review requirements;
- action when exact repository, branch, commit, environment, target-system, or data-source identity cannot be established;
- a choice between materially different product outcomes when evidence cannot establish operator intent;
- an irreversible action whose blast radius cannot be reliably bounded or recovered;
- credential creation, disclosure, rotation, or mutation; live personal-data access; source-system mutation; or amendment of this policy.

Absence of an item from this reserved list does not by itself authorize work outside the accepted objective. Conversely, routine Git and GitHub lifecycle operations listed in section 8.1 are expressly authorized and must not be escalated merely because a tool classifies them as state-changing.

Use ADRs only for durable, cross-cutting, difficult-to-reverse decisions. Ordinary implementation choices belong in code, tests, issues, and pull requests. Update documentation only when behavior, contracts, architecture, operations, or developer workflow materially changes.

### 8.3 Mandatory tiered agent execution

Substantive AI-assisted repository work MUST use the following three-tier execution topology:

**Manager → Orchestrator → Specialized Workers**

This is a repository execution-control requirement. It applies whether the accepted objective is governed through AEOS, another durable workflow, or a direct bounded/non-AEOS operator instruction. The topology does not itself create implementation authority, widen scope, authorize merge or deployment, or add a generalized agent framework to the `my-pa` product architecture.

A task is substantive for this section when it includes implementation, schema or migration work, security/privacy changes, cross-layer or multi-file changes, review/audit/corrective cycles, deployment/readiness work, or two or more separable technical specialties. Such work MUST NOT be collapsed into one monolithic authoring context.

#### Manager

The Manager is the top-level controlling context for the accepted objective. The Manager MUST:

- establish and preserve operator intent, objective, acceptance criteria, exact repository/base identity, in-scope behavior, prohibitions, and stop conditions;
- instantiate one dedicated Orchestrator for technical execution;
- retain final campaign accountability and resolve material scope or contract conflicts surfaced by the Orchestrator;
- keep implementation, review, and operator-only authority distinctions explicit;
- avoid becoming the routine feature-implementation worker except for a small integration correction that cannot reasonably be delegated without adding risk.

The Manager may not delegate final accountability or treat worker output as self-validating evidence.

#### Orchestrator

The Orchestrator is a dedicated context separate from the Manager and routine feature workers. It owns the execution graph and MUST:

- reauthenticate the current repository/base before execution and read the governing repository sources for the paths in scope;
- decompose the objective into bounded tasks and dispatch specialized workers for distinct domains or technical concerns;
- assign explicit worker file/path ownership, dependencies, acceptance criteria, and prohibitions before parallel work begins;
- serialize dependent work and shared-file edits; concurrent workers are permitted only when dependencies are satisfied and write ownership does not overlap;
- prefer isolated worker branches/worktrees for concurrent write tasks where the harness supports them;
- assign a single integration owner for shared dispatcher, registry, migration-chain, or other contention-prone files rather than allowing competing edits;
- collect worker handoffs, integrate the resulting changes, run the applicable test tiers, and coordinate corrective cycles;
- preserve exact commit/tree identity through integration and review;
- never substitute its own review for the independent exact-head review required for merge.

The Orchestrator is the designated orchestration agent referenced by section 8.1 when standing orchestration authority is being exercised.

#### Specialized workers

Workers MUST be specialized to a bounded, unique task rather than given the entire objective. Examples include persistence/migrations, domain/application behavior, transport/policy integration, security/privacy validation, testing/evaluation, documentation, or independent review.

Every worker assignment MUST specify:

- worker role and objective;
- exact base commit/tree or worktree identity;
- in-scope files/behavior and explicit out-of-scope items;
- dependencies and owned write paths;
- acceptance criteria and required tests/evidence;
- authority ceiling and prohibited actions;
- required handoff fields.

Every worker handoff MUST report:

- exact base and resulting commit/tree when it performed writes;
- files changed;
- requirement/work-item IDs addressed when they exist;
- tests/evidence produced and exact results;
- assumptions, limitations, blockers, and intentionally unperformed work.

Workers MUST NOT widen scope, redesign accepted contracts, merge to `main`, deploy, accept risk, or claim final objective completion unless the governing operator instruction independently grants that authority.

#### Specialized independent reviewer

When independent review is required, the Orchestrator MUST commission a fresh specialized reviewer context that did not author the change, has authority to block, and is not instructed toward an approval outcome. The reviewer binds its verdict to the exact reviewed head. Any later commit invalidates that verdict and requires a new exact-head review.

#### Harness limitation

If a substantive task requires this topology but the available execution harness cannot instantiate the necessary separate Manager, Orchestrator, and worker contexts, stop and report the limitation. Do not silently collapse the work into a single context unless the operator explicitly authorizes that exception for the exact task.

A truly atomic, low-risk task that does not meet the substantive criteria above may use direct bounded execution; do not manufacture meaningless subagents for a trivial read or isolated mechanical edit. The controlling context must be able to explain why the task was classified as atomic if challenged.

### 8.4 Repeatable NAS build and deployment

For any request to build the `my-pa` NAS package or deploy it to the NAS, use
[`$my-pa-nas-build-deploy`](.codex/skills/my-pa-nas-build-deploy/SKILL.md)
before planning or action. The skill routes the current repository runbooks and
scripts; it does not grant deployment authority, credential access, firewall
mutation, service interruption, destructive restore, or risk acceptance.
Sections 8.1–8.3 and every operator-only gate and mandatory stop in sections
8.2 and 9 continue to apply.

## 9. Mandatory stops

Stop and report the blocker when:

- repository or base identity has drifted;
- the objective, acceptance criteria, or path scope materially conflicts;
- credentials, production access, destructive data operations, or undisclosed irreversible actions become necessary;
- a security, privacy, or data-loss risk cannot be contained within the accepted scope;
- the change requires a new architecture component not covered by the accepted objective;
- substantive agent-assisted work cannot satisfy section 8.3 role separation because the execution harness lacks the required contexts and the operator has not authorized an exception.
