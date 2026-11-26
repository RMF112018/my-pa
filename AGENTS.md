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

Every change must state one objective, acceptance criteria, in-scope paths or behavior, and explicit out-of-scope items. A discovered feature goes to the backlog unless it is essential to the accepted objective. A scaffold directory is not implementation authority. Once a bounded objective is authorized, routine planning, edits, tests, GitHub coordination, and in-scope corrections proceed without repeat operator checkpoints. Neither a draft policy nor an agent's own plan creates authority.

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
- Any mutation of an authoritative original source system, including a reversible write or destructive action, requires separate, exact operator authorization naming the source, operation and real target. Neither a routine code-work objective nor a standing release envelope grants a source write.

Do not turn these boundaries into additional layers or interfaces before a concrete use requires them.

## 5. Security, privacy, and data handling

Use automatic security handling rather than per-task security approval. These classes describe **handling**, not a requirement to manually label every file:

- **S0 — standard:** ordinary code, nonsecret technical documents, synthetic fixtures, and redacted diagnostics. Normal repository and CI workflow; no security approval ceremony.
- **S1 — private:** nonpublic project/business records, ordinary personal data, and proprietary source inputs. Authenticated handling is permitted **within an already authorized client, source, and storage boundary**; no repeat operator approval for each in-boundary read, revision, test, or publication. Never place S1 payloads in public GitHub, public CI logs, or unauthorized third-party services.
- **S2 — critical:** live credentials, private keys, privilege grants, confirmed critically exploitable access/exfiltration defects, unauthorized external release of protected data, or irreversible loss of canonical/production data. Isolate the affected operation and obtain exact authority when its risk or access is not already covered. Never commit or archive raw secrets; retain a safe redacted reference and record the withheld artifact.

Retain ordinary automatic safeguards: no live secrets in the repository/logs, bounded authenticated access, least-privilege operational identities, redaction before public disclosure, version/provenance checks, focused security tests, and adherence to applicable legal/contractual duties. Suspected secret-bearing material is handled in isolation, not used to stop unrelated authorized development. Authentication or database **code changes with synthetic fixtures are not automatically S2**.

Before cloud or external-model processing or disclosure of S1/protected source material, verify a documented, data-specific eligibility decision covering the source/data class, processing recipient and purpose. A standing decision may cover repeated in-boundary uses, but connector availability or general provider authorization is not consent. Logs exclude message bodies, source-document contents, contact details, access tokens and sensitive queries by default; prefer redacted metadata. Record proportionate payload-free audit events for security-relevant actions and denied destructive attempts. Operational scripts require explicit verified targets, fail closed when targets or authority are ambiguous, support dry-run where meaningful, and never infer destructive intent.

Development tests use synthetic fixtures and isolated test stores by default. Initial or expanded access to live personal sources, production credentials or databases, any authoritative source-system write, credential/grant mutation, unauthorized external disclosure, destructive operations, or production actions outside a separately approved release envelope are not authorized by ordinary code-work scope. Repeated S1 reads remain permissible only inside an existing, verifiable operator-approved source/data boundary. A standing release envelope covers only its exact reversible deployment target and cannot authorize live-source access or writes, protected-database access, secret/grant mutation or risk acceptance. This document itself grants no such envelope.

Report confirmed critical vulnerabilities privately. Disclose failed mandatory checks and record noncritical security findings for bounded correction or tracked follow-up; do not misrepresent an unmitigated critical issue as a routine defect. Apply `SECURITY.md` when reporting vulnerabilities.

## 6. Dependencies, database changes, and operations

- Keep runtime and development dependencies in one `pyproject.toml` when package implementation begins. Pin direct application dependencies to compatible ranges and use a reproducible lock or constraints strategy selected in that implementation PR.
- Explain the current use, maintenance cost, security surface, and removal path for every new dependency.
- Add weekly Dependabot updates for Python only after a Python manifest exists; GitHub Actions updates may run immediately.
- Use Alembic for schema changes once database implementation exists. Test migrations against an isolated database from an empty schema to head and, when relevant, from the preceding supported revision.
- Migrations must be forward-safe, reviewable, and free of implicit destructive behavior. Never target an unknown or unverified existing physical database.
- Configuration changes must document defaults, validation, secret status, and backward-compatibility impact.
- Background jobs must be idempotent, observable, bounded, and safe to retry when implemented.
- Release readiness requires passing the applicable test tier, documented known limitations, a verified target, an observable release health signal, feasible rollback or containment, recorded post-release observation and explicit failure-stop/rollback criteria. It also requires either an exact operator release decision or a separately adopted standing release envelope covering that verified target and these controls. A tag, CI success or release alone does not authorize deployment.

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
- security and policy regression tests relevant to the change;
- automatic, proportionate secret screening of changed code, documents and configuration and of publication candidates before public disclosure. The required check, coverage and result must be evidenced; absent or unverified coverage blocks the affected public publication/merge until qualified, rather than being inferred from unrelated web-security tests.

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

For repository work, use **GitHub Issue/objective → bounded branch/commits → PR/review comments and CI → eligible merge → follow-up Issues**. GitHub is the engineering collaboration and code-evidence record; do not require separate external coordination packages for each routine code exchange.

A normal change uses a short-lived branch from the verified base, a focused PR, applicable automated checks, and review proportionate to risk and applicable branch rules. The reviewed identity must be explicit whenever independent review is required. Do not push directly to protected `main`, bypass mandatory checks, or infer permission for production activity from a merge.

After the SDCR MY-PA publisher is qualified and the authority cutover is explicitly activated, session-generated deliverables and material evidence must also be archived through the approved automated publisher with a session manifest and concise locator handoff. Before then, GitHub remains the routine repository channel and existing Workspace publication instructions remain in force. Publication or bridge failure must be reported truthfully; do not ask the operator to carry ZIPs between agents.

### 8.1 Standing bounded delivery authority

The operator may approve a bounded objective or an explicit standing class of routine work. Inside that authorization, an authorized delivery agent may plan, edit code, run tests, create/maintain branches and PRs, respond to CI and review, and perform routine correction **without per-step operator permission**. Routine branch and worktree housekeeping is allowed when reversible and in scope. The approved authorization and actual repository/branch rules determine whether merge is permitted; a PR or plan cannot self-authorize it.

**Merged-work cleanup (mandatory).** When a PR has merged and its branch or worktree is no longer needed, the delivery agent that owns the merge deletes, in the same working session, the local worktree and local branch created for that PR's work (by it or by agents acting under its direction), and the remote branch if the merge did not delete it. Before deleting, it verifies that the PR is merged, that the worktree has no uncommitted, untracked or ignored-but-unique files, and that nothing is unpushed; after a squash merge it verifies by PR state and tree contents, not by ancestry, and expects `git branch -D` to be required. It never force-deletes a branch whose PR is not merged, never deletes `main` or a protected branch, never removes a worktree or branch created for other work or by another session, and never removes one holding uncommitted or unpushed work; it lists those for the operator instead. If the environment denies a deletion, it reports the exact commands and does not work around the denial. An agent that does not own the merge does not delete worktrees.

- **R — routine:** targeted checks and branch rules govern. An additional independent-review context is not required solely because an AI wrote the code; follow whatever review rules GitHub actually enforces. Do not claim independent approval of one's own work.
- **C — controlled:** focused checks and proportionate technical review for evidenced material access/data/migration impact. Independent review is required when repository rules, the accepted objective or material risk demands it, with findings bound to the reviewed head.
- **H — exceptional:** only the affected genuinely critical action or risk is escalated under section 8.2; unrelated authorized work can continue.

A substantive change to normative repository governance is operator-only under section 8.2 and requires a distinct, blocking-capable independent review of the exact current head before merge, even if GitHub branch protection does not enforce that review. Routine R/C handling does not waive this policy-amendment gate.

Use **at most two focused corrective-review cycles by default**. Consolidate open findings after that; distinguish true blockers from safely deferrable issues and track the latter in GitHub. The iteration limit never permits bypassing a failed mandatory check, unmitigated critical vulnerability, or missing required authorization. If a change invalidates a required exact-head review, re-review the affected current head before merge.

No agent may widen authorization, accept material operator risk, overrule branch protection, or merge an objective that still fails applicable mandatory gates.

### 8.2 Extreme-risk actions reserved to the operator

Only the operator can authorize actions outside an existing and verifiable approval boundary that involve:

- creation, disclosure, rotation, or mutation of live credentials, keys, authorization grants, or privileged production access;
- initial or expanded live personal-source/data access, or any write to an authoritative original source system, even if reversible. An earlier exact operator decision may authorize only its specified source, operation, recipient and real target; a code-work class or release envelope is not a substitute;
- external disclosure of protected/private/regulated material to a recipient or processing service not already authorized for that material;
- irreversible destruction or corruption of canonical/production data, or migrations with materially unbounded loss risk;
- production activation, externally consequential cutover, or deployment **outside** a separately adopted standing release envelope;
- acceptance of material security, privacy, legal, financial, contractual or operational risk; procurement outside approved limits;
- deliberate disabling of mandatory security checks, branch protections, or critical acceptance criteria; a substantive policy amendment;
- material scope/product-outcome changes not resolved by the approved objective, or high-impact action with an unverified real target.

Ordinary S0/S1 handling **inside an already authorized boundary**, reversible code changes, synthetic testing, branch operations and corrections are not escalated just because a tool labels them `write`, `security`, or `production-related`. Valid standing release authority must be documented separately before it is used; this governance change does not grant production deployment, live access or secret mutation.

Nothing in this section delegates operator risk acceptance or overrides platform, law, project-level restrictions or repository branch settings.

### 8.3 Proportionate agent execution

Use the smallest reliable agent configuration for the accepted objective: one bounded agent, an orchestrator with specialists, or independent reviewers when actually useful. A fixed manager → orchestrator → worker hierarchy is **not mandatory**. Do not stop merely because a tool lacks multi-agent delegation.

For concurrent edits, designate a single integration owner and nonoverlapping paths; verify the exact repository/branch/base/head and applicable tests. When an independent review is required, the reviewer must be distinct from the author and have authority to block; bind the result to the exact reviewed head. Additional changes invalidate only approval that depended on the old head, not the whole objective.

Keep GitHub issues, commits, PR threads, checks and reviews as the routine handoff. After qualified MY-PA activation, archive session deliverables and evidence via the automatic publisher; do not impose duplicate per-message request/response/receipt documents.

### 8.4 Repeatable NAS build and deployment

For any request to build the `my-pa` NAS package or deploy it to the NAS, use
[`$my-pa-nas-build-deploy`](.codex/skills/my-pa-nas-build-deploy/SKILL.md)
before planning or action. The skill routes the current repository runbooks and
scripts; it does not grant deployment authority, credential access, firewall
mutation, service interruption, destructive restore, or risk acceptance.
Sections 8.1–8.3 and every operator-only gate and mandatory stop in sections
8.2 and 9 continue to apply.

## 9. Mandatory stops

Stop the **affected action** and report an actionable blocker when:

- verified base/head or real target identity cannot be established and a wrong-target action could be consequential;
- a material scope or acceptance conflict requires a new operator decision;
- an unmitigated confirmed critical security or unauthorized-disclosure exposure would be introduced;
- an irreversible/destructive production or canonical-data action, live credential/grant mutation, or external disclosure needs authority not already supplied;
- an applicable mandatory test/check fails and cannot be corrected within scope;
- required secret-screening coverage for public submission/publication is absent, unsuccessful or not verifiable;
- a proposed external-model use or live-source access/write lacks a verified, data-specific eligibility decision or exact operator authority;
- deployment, merge or release is outside actual permission, repository rules or approved release envelope.

Do not stop unrelated authorized work merely because routine findings, advisory warnings, noncritical technical debt or a missing agent-topology role exist. Track nonblocking defects for follow-up; preserve the failure evidence and state the final disposition.

