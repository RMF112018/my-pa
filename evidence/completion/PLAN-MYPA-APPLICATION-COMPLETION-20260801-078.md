\---  
plan\_id: PLAN-MYPA-APPLICATION-COMPLETION-20260801-078  
coordination\_request\_id: REQ-MYPA-APPLICATION-COMPLETION-ORCHESTRATION-20260801-078  
artifact\_type: TERMINAL\_APPLICATION\_COMPLETION\_PLAN\_AND\_LOCAL\_CODEX\_ORCHESTRATION\_PROMPT  
status: READY\_FOR\_LOCAL\_CODEX\_DISPATCH  
repository: RMF112018/my-pa  
default\_branch: main  
observed\_main\_sha: e773e6f2285da9e453a8ca7e11bdac23619aaf22  
observed\_at\_local: 2026-08-01T13:12:00-04:00  
execution\_environment: Codex app on operator local machine  
implementation\_agent\_channel: tmux session claude-code  
operator\_delegation: BOUNDED\_STANDING\_AUTHORITY\_WITH\_NONDELEGABLE\_SAFETY\_BOUNDARIES  
terminal\_disposition: MYPA\_CURRENT\_PRODUCT\_SCOPE\_COMPLETE\_LOCAL\_CANDIDATE\_READY\_FOR\_OPERATOR\_ACTIVATION\_DECISION  
publication\_operation: CREATE  
representation: native\_google\_doc\_from\_source\_markdown  
\---

\# \`my-pa\` Remaining Application — Terminal Completion Plan

\#\# 1\. Mission

Act as the single continuing implementation orchestrator for the remaining current product scope of \`RMF112018/my-pa\`.

The objective is to take the repository from its current post-migration foundation to a complete, locally operable, independently reviewed application candidate implementing the current accepted product scope across:

1\. the Personal Knowledge Layer implementation roadmap;  
2\. the read-only MCV vertical slice;  
3\. the migrated PostgreSQL knowledge/data foundation;  
4\. the interactive frontend MVP;  
5\. the GoodNotes handwriting-to-knowledge MVP;  
6\. operations, resilience, documentation, packaging, final integration, post-merge verification, and repository cleanup.

This is one terminal delivery objective. Manage it through bounded work packages and pull requests where necessary, but do not fragment the objective into disconnected orchestration sessions or return for routine approvals. Continue until all currently authorized product scope is complete or a mandatory safety stop is reached.

The terminal target is:

\`\`\`text  
MYPA\_CURRENT\_PRODUCT\_SCOPE\_COMPLETE\_LOCAL\_CANDIDATE\_READY\_FOR\_OPERATOR\_ACTIVATION\_DECISION  
\`\`\`

“Complete” means the current accepted repository and indexed Drive specifications have been implemented, tested, reviewed, merged, reconciled, and cleaned up. It does not include speculative future features, production deployment, risk acceptance, or irreversible external actions.

\#\# 2\. Current authenticated starting point

Authenticate all values locally before relying on them. The dispatch-time GitHub basis is:

\`\`\`yaml  
repository: RMF112018/my-pa  
default\_branch: main  
observed\_main\_sha: e773e6f2285da9e453a8ca7e11bdac23619aaf22  
observed\_main\_status: current GitHub main at dispatch  
repository\_visibility: private  
squash\_merge\_supported: true  
\`\`\`

Recent merged work visible at dispatch includes:

\- \`6057d1180949f4c01defdea07dcc9ea1fefa5b18\` — PostgreSQL foundation and target schemas;  
\- \`f34eb966dac439af59d6335441685e628bd90770\` — legacy corpus migration into PostgreSQL;  
\- \`dd66840db0309b26876ac69349e5ba68c10596c1\` — database CI tier and architecture-boundary cleanup;  
\- \`e773e6f2285da9e453a8ca7e11bdac23619aaf22\` — infrastructure-boundary and privacy-evidence enforcement.

The merged migration record reports a canonical PostgreSQL corpus of 3,263,870 rows across 484 domain tables. Treat that as a repository claim until reverified from the local runtime and repository evidence. Do not rerun, redesign, or duplicate the migration merely because older planning documents predate it.

Known current-state reconciliation issue: repository \`README.md\` still describes a documentation-only scaffold even though substantial package, PostgreSQL, migration, tests, and CI behavior now exists. Correct stale orientation and routing as part of the first bounded work package.

\#\# 3\. Authority and role

You are the operator’s delegated implementation orchestrator for this objective. You may act as the operator’s proxy for routine, bounded decisions required to finish the accepted plan.

Within the exact objective and safety boundaries below, you have standing authority to:

\- inspect local repository, GitHub, Drive, PostgreSQL, Docker, tmux, and existing non-production configuration;  
\- direct and interact with the existing Claude Code session through tmux session \`claude-code\`;  
\- require Claude Code to use fresh subagents or isolated contexts for planning, implementation, review, testing, security review, and cleanup verification;  
\- answer implementation questions and select among technically equivalent options;  
\- approve a repository-truth implementation plan with \`PLAN\_APPROVED\` when it satisfies this plan;  
\- require consolidated plan revisions, up to three plan-review iterations;  
\- issue bounded work-package authorizations under the approved plan;  
\- authorize repository edits, tests, isolated database migrations, local non-production services, commits, pushes, pull requests, CI corrections, and documentation updates;  
\- approve exact-head implementation work after evidence-based review performed separately from the implementing context;  
\- authorize squash merge when all required gates pass;  
\- perform post-merge validation;  
\- authorize deletion of merged implementation branches and associated disposable worktrees after exact verification;  
\- resolve ordinary implementation ambiguities without returning to the user;  
\- publish the final state and unresolved findings.

Do not claim that delegated authority makes you the legal or risk-bearing operator. The following remain nondelegable and require a mandatory stop unless separately and explicitly authorized by the human operator:

\- acceptance of business, privacy, security, legal, financial, or operational risk;  
\- production deployment or production activation;  
\- credential creation, rotation, revocation, disclosure, or destructive secret-store changes;  
\- destructive source-system mutation;  
\- irreversible deletion of source data, canonical database data, backups, or managed user content;  
\- external communications, financial transactions, contractual actions, or third-party system mutations;  
\- material expansion beyond the current accepted product scope;  
\- automatic model promotion to production authority;  
\- disabling or weakening acceptance criteria, auditability, provenance, privacy controls, or test coverage merely to finish.

You may use already configured local credentials and aliases for authorized non-production validation when repository policy permits. Never print, copy into prompts, commit, or publish secret values.

\#\# 4\. Execution channel: Claude Code through tmux

Use the existing tmux session named:

\`\`\`text  
claude-code  
\`\`\`

Resolve its actual panes before dispatch:

\`\`\`bash  
tmux has-session \-t claude-code  
tmux list-windows \-t claude-code  
tmux list-panes \-a \-F '\#{session\_name}:\#{window\_index}.\#{pane\_index} \#{pane\_active} \#{pane\_current\_command} \#{pane\_current\_path}' | grep '^claude-code:'  
\`\`\`

Capture semantic state before sending work:

\`\`\`bash  
tmux capture-pane \-p \-t \<resolved-pane\> \-S \-300  
\`\`\`

Send complete, self-contained instructions. Do not require Claude Code to scrape the Codex UI, inspect browser source, use OCR, or recover missing context from screenshots. The repository, local filesystem, authenticated Drive artifacts, and complete tmux messages are the handoff channels.

Use tmux interaction iteratively:

1\. dispatch one complete work request;  
2\. inspect Claude’s response and repository evidence;  
3\. approve, revise, or reject the plan/review;  
4\. direct implementation without routine checkpoint returns;  
5\. inspect terminal completion evidence;  
6\. require corrections or approve exact-head integration;  
7\. continue through merge, post-merge validation, and cleanup.

Do not type passwords, tokens, or private keys into tmux prompts.

\#\# 5\. Required authority sources

\#\#\# 5.1 Workspace controls

Retrieve current versions by exact Drive ID:

| Artifact | Drive ID |  
|---|---|  
| \`00\_WORKSPACE\_BOOTSTRAP.md\` | \`1byJ8ndafXP1\_yrRmvzIlIwKP-F6rPcj8d-AYYLPIzW4\` |  
| \`01\_WORKSPACE\_MANIFEST.yaml\` | \`11Mtd1w9TNeIAn6PWJ6xbfHeU4piLkEft9m-HpB88Eo8\` |  
| \`02\_WORKSPACE\_SOURCE\_INDEX.md\` | \`1xI1wO0eUUAGmH1P4-oVx2e-ZLQQXTN-p783pJKi-Wf8\` |  
| \`03\_WORKSPACE\_OPERATING\_INSTRUCTIONS.md\` | \`1SabLXhGXhxXZ0j\_Lazy7MyHve008P-SklcyZOK1xNNc\` |

Repository governance and runtime truth control implementation over older Drive planning assumptions.

\#\#\# 5.2 Current MY-PA owning index

\`\`\`yaml  
title: 00\_MYPA\_INDEX.md  
drive\_id: 1i9r6pDI8jZQnD526\_o\_aFl8WWUliWX0h1ANLh\_gtelE  
parent\_folder\_id: 1kjmdqVYc1txLadCVzsxpq7ParUrc\_Yhm  
\`\`\`

Use this index to locate current product and feature publications. Update it only when publication rules and actual final state require it.

\#\#\# 5.3 Knowledge-layer implementation package

\`\`\`yaml  
folder\_title: MYPA-KNOWLEDGE-LAYER-IMPLEMENTATION-PLAN  
folder\_id: 1vCyRphoyo3U-K-ULPp3APycdNW0J5Nv2  
master\_readme\_id: 15C1kI-xpcHcKIY50Dm0dIw5SlvR\_\_BRM  
master\_readme\_title: README-MYPA-KNOWLEDGE-LAYER-IMPLEMENTATION-PLAN.md  
\`\`\`

Phase artifacts:

| Historical plan phase | Drive ID |  
|---|---|  
| Phase 00 — repository truth and MCV contract freeze | \`1SvVLqvyY1e\_2m4JA-ntVpwcw8E3EZcvY\` |  
| Phase 01 — package contracts and policy kernel | \`1wNh5c\_unYLYpm7um9gJievb21uPnQtqw\` |  
| Phase 02 — PostgreSQL source registry and jobs | \`1Jt\_-gMqfSWkj9bu2c0l743h894yabYdm\` |  
| Phase 03 — read-only NAS source provider | \`1DBzmzyBg6-adzJkb1HseDlIdV60iwDPH\` |  
| Phase 04 — progressive indexing, extraction, and search | \`1Vd5TPlyKkKTSYO4leMcMgKS0X61rw4Ss\` |  
| Phase 05 — read-only knowledge gateway MCV | \`1QI6owsIiPYBICUZh6a2SMjiuxok-euFm\` |  
| Phase 06 — managed documents, versions, and recovery | \`1sbeCZ7\_Bzvcq3iF\_xA5h8KyJqQ6RDvR0\` |  
| Phase 07 — structured knowledge context | \`1P3Nm3yqftowZH0ZK5ANwRN-IOaMyJ5LD\` |  
| Phase 08 — neutral personal-data connectors | \`1HzZlltktr7VriGX7z2ctzumWVSKF8pTT\` |  
| Phase 09 — relationship intelligence | \`18\_DQ8W02iF-hi2AaR-UTQoG1CPMH1YCW\` |  
| Phase 10 — Obsidian human projection | \`17nmEgLr659AxHfqcfJztKEVPxd\_x9fpU\` |  
| Phase 11 — operations, resilience, bounded activation | \`1DC0XUQeL0tjRLWHAAAya3ruqY8\_Nr-A\_\` |

These documents are planning inputs, not current repository truth. For every requirement, classify it as already implemented, partially implemented, superseded, still required, deferred by current MCV policy, or contradicted by later accepted specifications.

\#\#\# 5.4 Interactive frontend product package

\`\`\`yaml  
package\_folder\_id: 1wHrFrc6\_WXhCQVr5fcKvDvrcPrrJpgd0  
package\_readme\_id: 1YBesWXDyNIqqhoudygjZBO5SnG1JFpbfvO7-lZTXvLs  
product\_ux\_spec\_id: 17mrP2WHNCMLpCgUbE-x9NJ4dD1CCe07eZUuKd6iCQMs  
information\_architecture\_id: 1p6GdUDvGWAKKA5iPO8p\_cJoqVzMn9wWXI53gBoroHhk  
screen\_workflow\_inventory\_id: 1LhszqbGZKETpqe80ouKPP8iqarhXILuNv8LAosV4fXk  
technical\_architecture\_id: 1y\_Or3N7\_-TjVFkn\_KdhY45GhR9lzqKIUurUkzITs828  
roadmap\_id: 1V\_SZsUuB9vpEx8qJ76Z6h-O55EVXTYzKo\_cJhzHUI9Y  
structured\_wireframes\_id: 1AxYpV1eqe-CMRrCZpzyzgCsMz9lpmnZ87gJ866iV\_vE  
decision\_log\_id: 101Bds8kqz4RFaETuXfTGdj9135atLYy0qD69jBKj5u0  
\`\`\`

Implement the frontend MVP defined by the package, reconciled against actual backend capabilities. Do not implement speculative roadmap items merely because they are described.

\#\#\# 5.5 GoodNotes MVP

\`\`\`yaml  
feature\_description\_id: 16eP6nvZAuXEnWVthfBFu242FvA0TUQyg1yvQAlwmnfg  
implementation\_spec\_id: 111zA3Osva\_tdi7oW-8TIBcC0uS9\_cQ6VZ-w3pqmGhCA  
feature: GoodNotes handwriting-to-knowledge ingestion  
configured\_source\_root\_claim: [REDACTED — personal NAS path; see evidence/completion/README.md]  
\`\`\`

Authenticate the local source path and permissions before using it. The source must remain read-only. Inventory-first behavior is mandatory. Historical OCR is not authorized by default.

\#\#\# 5.6 Repository controls

Before planning, read current versions from the checked-out repository:

\- \`AGENTS.md\`;  
\- \`AI\_OPERATING\_MANUAL.md\`;  
\- \`CLAUDE.md\`;  
\- \`.ai/project-sources/00\_AEOS\_MASTER\_INDEX.md\`;  
\- \`CONTRIBUTING.md\`;  
\- \`SECURITY.md\`;  
\- \`README.md\`;  
\- \`docs/00\_REPOSITORY\_SOURCE\_INDEX.md\`;  
\- architecture, ADR, specification, migration, security, operations, and evidence indexes nearest the affected work.

\`AGENTS.md\` is the principal repository policy. Preserve its minimum-correct-implementation, architecture, privacy, test-tier, and short-lived-branch rules.

\#\# 6\. Mandatory first deliverable: current-state gap audit and integrated execution plan

Do not begin broad implementation from the old phase sequence. First instruct Claude Code to conduct an exhaustive but bounded reconciliation of:

\- current local \`main\` and GitHub \`main\`;  
\- all merged PRs and current CI;  
\- local PostgreSQL schema/data/runtime state;  
\- current package and test inventory;  
\- current product and feature specifications listed above;  
\- the historical knowledge-layer phase plan;  
\- stale or contradictory repository documentation;  
\- open issues, branches, worktrees, TODOs, and unresolved findings.

The output must be one integrated implementation plan containing:

1\. exact repository, main SHA, tree, local worktree, and runtime identities;  
2\. a requirements traceability matrix mapping every current product requirement to:  
   \- implemented and verified;  
   \- implemented but insufficiently verified;  
   \- partially implemented;  
   \- missing and required;  
   \- superseded;  
   \- deliberately deferred;  
3\. the smallest complete set of remaining work packages;  
4\. dependency order and merge sequence;  
5\. exact path/behavior scope for each work package;  
6\. acceptance criteria mapped to tests and evidence;  
7\. database migration and compatibility approach;  
8\. source/provider and credential boundaries;  
9\. frontend/backend contract plan;  
10\. GoodNotes model and review strategy;  
11\. rollback and recovery strategy;  
12\. CI and local test-tier plan;  
13\. local activation and smoke-test plan;  
14\. PR, exact-head review, merge, post-merge validation, and cleanup approach;  
15\. risks, assumptions, unavailable evidence, and mandatory stops;  
16\. explicitly deferred speculative enhancements.

The plan must ask: \`Is this plan approved?\`

Review it as the operator’s delegated orchestrator. Return exactly one of:

\`\`\`text  
PLAN\_APPROVED  
PLAN\_REVISION\_REQUIRED  
PLAN\_BLOCKED  
\`\`\`

Use at most three plan-review iterations. Consolidate all findings in each review. \`PLAN\_APPROVED\` grants standing authority to execute the approved plan through all included work packages, tests, PRs, merges, post-merge validation, and cleanup, subject to the mandatory stops in this document.

\#\# 7\. Required product completion scope

The gap audit may combine or reorder work, but terminal completion must cover the following current capabilities unless repository truth proves that a requirement is superseded or already complete.

\#\#\# Workstream A — Repository and product truth reconciliation

\- Correct stale \`README.md\`, source indexes, architecture indexes, and current-state claims.  
\- Record the actual implemented PostgreSQL and migration state without overstating production readiness.  
\- Close or explicitly carry forward stale migration/phase lifecycle records.  
\- Remove dead scaffolds and obsolete compatibility paths only when proven unused.  
\- Preserve neutral naming and zero former-employer product branding.  
\- Ensure all current accepted Drive specifications are routed or mirrored appropriately without treating Drive as repository authority.

Acceptance outcomes:

\- a new developer can identify what actually exists and what remains deferred;  
\- repository indexes route to current specifications and operations;  
\- no current document still claims the repository is documentation-only;  
\- historical plans are clearly classified as historical/reconciled.

\#\#\# Workstream B — Application runtime, registry, jobs, and canonical knowledge services

Complete the minimal application capabilities needed above the migrated database:

\- source registry and enrollment;  
\- bounded job/control-plane services suitable for product work, reusing existing migration-control patterns where appropriate without conflating migration and application jobs;  
\- stable opaque identities, provenance, classification, coverage, freshness, confidence, and disclosure contracts;  
\- idempotent command handling and expected-version concurrency where required;  
\- canonical source assertions separated from canonical facts;  
\- typed response/capability envelopes;  
\- audit events that exclude sensitive payloads;  
\- PostgreSQL-backed persistence and migrations from empty to head;  
\- health/readiness and operational status surfaces.

Do not build a generalized framework. Implement only what the current product workflows use.

\#\#\# Workstream C — Read-only NAS source provider and progressive indexing

Implement the read-only MCV source path:

\- explicit source-root registration; no broad discovery;  
\- opaque source identities;  
\- bounded list, inspect, and fetch operations;  
\- traversal denial and root-containment enforcement;  
\- read-only \`ssh bf-nas\` or directly mounted authorized access as locally configured;  
\- no former-employer NAS alias;  
\- enrollment of selected objects/subtrees only;  
\- deterministic extraction for supported file types;  
\- quarantine and truthful unsupported-format behavior;  
\- incremental hashing/version detection;  
\- PostgreSQL full-text search and \`pg\_trgm\` first;  
\- coverage, freshness, truncation, and authority disclosure;  
\- source-to-search-to-evidence roundtrip;  
\- no source mutation.

Use small synthetic fixtures in tests. Live NAS canaries must be read-only, bounded, explicitly identified, and must not expose contents in logs or evidence.

\#\#\# Workstream D — HTTP/MCP gateway and operator CLI

Complete one stable semantic interface exposed through the architecture chosen by current repository ADRs:

\- capability discovery;  
\- readiness and health;  
\- source registration/enrollment where authorized;  
\- source list/inspect/fetch;  
\- search and evidence retrieval;  
\- knowledge/context retrieval;  
\- review and proposal commands;  
\- operations/status surfaces;  
\- transport-neutral domain/application contracts;  
\- HTTP and MCP parity where the accepted spec requires it;  
\- CLI for bootstrap, diagnostics, scans, backfills, repair, migration, and operator review.

Authentication and session handling must be appropriate for local-first operation. Bind local services to loopback by default. Do not claim multi-user or internet-exposed security readiness.

\#\#\# Workstream E — Managed documents, structured knowledge, and recovery

Implement managed outputs as a capability separate from read-only sources:

\- managed-document creation only in designated managed storage;  
\- version history, content hashes, provenance, expected-version writes, and immutable audit trail;  
\- rollback/recovery and deterministic rebuild where specified;  
\- structured knowledge records for tasks, commitments, decisions, follow-ups, questions, risks, issues, projects, people, organizations, documents, and observations as required by current product workflows;  
\- source assertions and canonical records with contradiction/supersession lifecycle;  
\- safe manual proposals and reviewed acceptance;  
\- no silent overwrite of authoritative source evidence.

\#\#\# Workstream F — Personal-data domain access and relationship intelligence

Build the product-facing read and correlation services over the migrated PostgreSQL domains required by current specifications:

\- Procore;  
\- email;  
\- calendar;  
\- contacts;  
\- financial;  
\- schedule;  
\- construction/project records;  
\- relationship timelines and evidence-backed briefings;  
\- project chronology and decision provenance;  
\- tasks and commitments linked to source evidence;  
\- entity resolution using reviewed aliases and cross-source evidence.

Do not reimport or mutate third-party systems unless a separately accepted connector objective requires it. The existing migrated database may be used as the local canonical read source after identity verification. Personal data must not enter logs, fixtures, commits, screenshots, or Drive evidence.

\#\#\# Workstream G — GoodNotes handwriting-to-knowledge MVP

Implement the complete accepted GoodNotes MVP, including:

\- authenticated read-only source root;  
\- periodic authoritative reconciliation with optional event acceleration;  
\- file settling and PDF integrity checks;  
\- inventory-only initial baseline;  
\- new-content-only default after baseline;  
\- notebook, artifact, page, page-version, region, job, attempt, candidate, proposal, assertion, review, dataset, and model identities;  
\- page-level fingerprinting and change detection;  
\- immutable page and review version history;  
\- rendering, preprocessing, segmentation, and region provenance;  
\- PaddleOCR baseline;  
\- TrOCR escalation for handwriting regions;  
\- calibrated confidence and candidate reconciliation;  
\- structured extraction and risk classification;  
\- review-required handling for people, commitments, financial facts, critical dates, and ambiguous identity;  
\- transactional acceptance into source assertions and search;  
\- reviewed-correction capture;  
\- Kraken retained disabled by default, with data-collection/evaluation lifecycle only unless exact promotion evidence and separate authority exist;  
\- bounded reprocessing and selective backfill;  
\- operational metrics, receipts, retries, recovery, and rollback.

Do not perform full historical OCR unless the user has separately and explicitly selected a bounded backfill. Do not mutate, rename, move, or delete GoodNotes source files.

\#\#\# Workstream H — Interactive frontend MVP

Implement the current frontend MVP as an actual polished product surface, aligned with verified backend capabilities:

\- responsive application shell;  
\- navigation, command palette, recents, favorites, notifications, theme, density, and accessibility primitives;  
\- capability discovery and truthful unavailable-state handling;  
\- provenance, coverage, freshness, confidence, risk, authority, and partial-coverage components;  
\- Today view with agenda, actions, commitments, project watchlist, review exceptions, and system exceptions;  
\- search with lexical/metadata queries, facets, saved searches, evidence preview, deep links, and partial-coverage disclosure;  
\- projects, people, organizations, knowledge overview, source-backed timelines, and action records;  
\- GoodNotes source dashboard, notebook browser, page viewer, region overlays, OCR candidates, review, correction, reprocessing, and backfill controls;  
\- unified review queues and history;  
\- entity-resolution, duplicate, contradiction, and source-change review where backend support exists;  
\- connector, job, index, model, storage, and database health;  
\- event updates through SSE or bounded polling as justified;  
\- keyboard-first operation and common mobile review workflows;  
\- secure errors, recovery states, audit/receipt visibility, and no hidden AI authority;  
\- accessibility, security, and performance budgets;  
\- an application useful without chat.

Do not invent backend behavior to make a screen look complete. Every action must bind to a real contract or render an explicit unavailable/deferred state.

\#\#\# Workstream I — Obsidian projection

Implement the deterministic human-readable projection required by the accepted knowledge-layer plan:

\- generated from canonical PostgreSQL knowledge, never treated as authority;  
\- stable paths and IDs;  
\- provenance and source links;  
\- deterministic rebuild;  
\- no manual edits silently imported as canonical truth unless a separate reviewed workflow exists;  
\- safe recovery and stale-file cleanup within the designated projection root only.

\#\#\# Workstream J — Operations, resilience, packaging, and local candidate activation

Complete local candidate operations:

\- bounded process startup/shutdown;  
\- loopback-only default services;  
\- database, queue, worker, gateway, frontend, source, GoodNotes, index, model, and storage health;  
\- retries, leases, idempotency, recovery, and restart tests;  
\- backup/recovery documentation and non-destructive validation;  
\- configuration examples without secrets;  
\- Docker or local-process orchestration consistent with accepted architecture;  
\- reproducible dependency and build strategy;  
\- migrations from empty to head;  
\- package/build validation;  
\- local smoke test of the full vertical slice;  
\- final operator runbook;  
\- honest limitations and activation requirements.

Local candidate activation is allowed only on the operator’s machine, bound to loopback or otherwise constrained by existing accepted configuration. Production deployment remains prohibited.

\#\# 8\. Explicitly deferred or prohibited scope

Do not implement these merely to satisfy “complete application”:

\- public SaaS or multi-tenant hosting;  
\- autonomous external actions;  
\- source-system mutation;  
\- broad recursive indexing of unreferenced NAS content;  
\- Redis, Celery, Kafka, a graph database, a dedicated vector database, Kubernetes, or microservices without measured necessity and accepted scope change;  
\- automatic model self-training or promotion;  
\- universal graph visualization;  
\- claims/dispute automation or legal strategy;  
\- voice/wearable/location surveillance;  
\- public-person surveillance or moral/reputational scoring;  
\- native \`.goodnotes\` parsing unless required to satisfy the accepted MVP after PDF-based implementation proves insufficient;  
\- full historical GoodNotes OCR without a separately selected bounded backfill;  
\- pgvector or semantic indexing without benchmark evidence and an accepted gate;  
\- production deployment, internet exposure, or risk acceptance.

Near-term and later enhancement items in the frontend roadmap are backlog unless they are indispensable to an accepted MVP exit outcome or explicitly promoted by repository truth.

\#\# 9\. Implementation and review rules

\#\#\# 9.1 Work-package strategy

Use the smallest number of coherent, reviewable work packages. Each must have:

\- one objective;  
\- exact base, branch, and path/behavior scope;  
\- acceptance criteria;  
\- test plan;  
\- data/privacy statement;  
\- rollback plan;  
\- explicit exclusions;  
\- merge and cleanup plan.

Prefer vertical slices over layer-only scaffolds. Do not create placeholders for later phases unless immediately required by the slice.

\#\#\# 9.2 Implementation context separation

Claude Code may implement, but exact-head review must be performed by a fresh subagent/context that did not author the candidate. The orchestrator reviews both evidence sets and issues the disposition.

Accepted review dispositions:

\`\`\`text  
IMPLEMENTATION\_ACCEPTED  
CORRECTIONS\_REQUIRED  
COMPLETE\_WITH\_UNRESOLVED\_FINDINGS  
IMPLEMENTATION\_BLOCKED  
\`\`\`

Use at most three correction/review iterations per work package. Later commits invalidate prior exact-head review for changed content.

\#\#\# 9.3 Testing

At minimum preserve repository test tiers:

\- FAST: Ruff, format, targeted strict typing, unit/domain/application contracts, no DB/network/live connectors;  
\- PR: FAST plus isolated PostgreSQL, migrations, provider conformance with synthetic fixtures, security/policy regressions, frontend unit/component/accessibility tests, and affected integration paths;  
\- FULL: end-to-end synthetic vertical slices, recovery/idempotency, complete isolated database, packaging, and migration-from-empty;  
\- SPECIALIZED: bounded read-only NAS/GoodNotes canaries, OCR/model evaluation, performance, recovery, and runtime attestation.

Critical contracts must not be omitted to meet a time target. No live personal data in tests or recorded evidence.

Frontend validation must include:

\- component and contract tests;  
\- keyboard navigation;  
\- automated accessibility checks;  
\- responsive behavior at agreed breakpoints;  
\- loading, empty, error, stale, partial, denied, and unavailable states;  
\- evidence/deep-link roundtrip;  
\- visual regression or equivalent controlled UI review where practical;  
\- measured bundle and interaction performance budgets.

GoodNotes validation must include synthetic notebook fixtures, interrupted-write settling, page insert/reorder/change cases, idempotency, lease recovery, review transactions, and OCR adapter fakes. Live OCR evaluation must use bounded authorized samples and must not publish source images or transcriptions.

\#\#\# 9.4 Database safety

\- Verify logical database identity \`my\_pa\` and exact target before every mutation.  
\- Use Alembic for schema changes.  
\- Test from empty to head and from supported prior revision.  
\- Back up or otherwise establish rollback capability before material local canonical schema/data changes.  
\- Never connect to an unknown physical database.  
\- Never modify the legacy SQLite source.  
\- Avoid destructive migrations; when unavoidable, stop unless the exact operation was disclosed and separately authorized.

\#\#\# 9.5 Pull requests and merges

For each PR:

1\. authenticate base and head;  
2\. confirm path and behavior containment;  
3\. run applicable tests;  
4\. obtain fresh exact-head review;  
5\. require required GitHub checks to pass;  
6\. ensure no unresolved blocking finding;  
7\. approve squash merge as the delegated operator only when all gates pass;  
8\. verify resulting \`main\` contains the reviewed contribution;  
9\. observe resulting-main CI where available;  
10\. delete the merged remote branch and disposable local worktree only after verified integration.

Do not delete unrelated branches or worktrees. Never use force push on shared or protected branches.

\#\# 10\. Mandatory stops

Stop and return one consolidated exception report only when:

\- repository or runtime identity materially drifts and cannot be safely reconciled;  
\- current specifications conflict in a way that changes product intent rather than implementation detail;  
\- completing a requirement would require production deployment, risk acceptance, secret mutation, destructive source/data action, or undisclosed irreversible work;  
\- a privacy or security issue cannot be contained within the approved scope;  
\- required credentials or external systems are unavailable and no truthful synthetic/local acceptance path exists;  
\- a new infrastructure component is materially required but not covered by accepted architecture;  
\- acceptance criteria cannot be satisfied without weakening them;  
\- permissions prevent merge, verification, or cleanup;  
\- the local Claude Code session cannot be reached or is irrecoverably inconsistent.

Do not stop for routine choices, ordinary test failures, implementation corrections, PR updates, merge conflicts within scope, or ordinary cleanup.

\#\# 11\. Terminal acceptance criteria

Do not declare terminal completion until all are true:

\#\#\# Repository and lifecycle

\- current GitHub \`main\` contains all accepted work;  
\- no open application-completion PR remains;  
\- all implementation branches and disposable worktrees created for this objective are cleaned up;  
\- no unrelated branch/worktree was removed;  
\- repository documentation and indexes describe current truth;  
\- final lifecycle record lists all unresolved findings.

\#\#\# Backend and data

\- PostgreSQL schema migrates from empty to head;  
\- canonical local database identity is verified;  
\- migrated domains are accessible through product services without leaking personal data;  
\- source registry, jobs, provenance, knowledge, review, and operations services pass their acceptance tests;  
\- read-only NAS source-to-search-to-evidence vertical slice passes;  
\- managed writes are confined to designated storage and recoverable;  
\- relationship/project/context services are evidence-backed.

\#\#\# GoodNotes

\- inventory baseline works without OCR of historical content;  
\- new or changed page versions process idempotently;  
\- source remains read-only;  
\- page/region provenance is inspectable;  
\- OCR candidate and review workflow works;  
\- accepted correction becomes an immutable assertion and searchable record;  
\- Kraken remains non-production unless separately authorized.

\#\#\# Frontend

\- application shell, Today, Search, Projects/People/Actions, GoodNotes, Review, and Operations are usable;  
\- search-to-source and review-to-source roundtrips pass;  
\- common mobile review and keyboard workflows pass;  
\- coverage/freshness/trust/provenance/authority are visible;  
\- unavailable backend capabilities are represented truthfully;  
\- accessibility, security, and performance budgets pass;  
\- the application is useful without chat.

\#\#\# Operations

\- startup, shutdown, restart, and recovery are documented and tested locally;  
\- loopback/local security assumptions are explicit;  
\- health and readiness surfaces reflect reality;  
\- FULL synthetic end-to-end suite passes;  
\- specialized canaries are either PASS or honestly recorded as unavailable/nonblocking where the product can still be accepted locally;  
\- no production deployment is claimed.

\#\#\# Final disposition

Publish and report exactly one terminal disposition:

\`\`\`text  
MYPA\_CURRENT\_PRODUCT\_SCOPE\_COMPLETE\_LOCAL\_CANDIDATE\_READY\_FOR\_OPERATOR\_ACTIVATION\_DECISION  
\`\`\`

or, if terminal completion is impossible:

\`\`\`text  
MYPA\_APPLICATION\_COMPLETION\_BLOCKED  
\`\`\`

A blocked result must identify exact completed work, exact repository state, the minimal unresolved blocker, unavailable evidence, affected acceptance criteria, and the operator-only decision needed.

\#\# 12\. Final report and durable publication

At completion, publish one complete final-state artifact in the current MY-PA Drive hierarchy containing:

\- objective and approved plan revision;  
\- exact final repository/main SHA and tree;  
\- all PRs and merge SHAs;  
\- implemented capability matrix;  
\- acceptance-criteria results;  
\- test, CI, database, frontend, GoodNotes, operations, and runtime evidence;  
\- data-access and privacy attestation;  
\- local activation status;  
\- cleanup inventory;  
\- deviations and superseded assumptions;  
\- unresolved findings and recommended future backlog;  
\- production/risk/secret boundaries still requiring the human operator.

Update the MY-PA owning index if required. Do not publish personal content, credentials, OCR samples, email/contact data, or unredacted runtime evidence.

\#\# 13\. Initial instruction to the local Claude Code session

After authenticating this plan, current repository state, and tmux pane, send Claude Code a complete first request substantially equivalent to:

\`\`\`text  
Act as the lead implementation agent for terminal completion of the remaining current product scope of RMF112018/my-pa.

Read current repository governance and repository truth first. Retrieve the current MY-PA owning index and the exact Drive source IDs listed in PLAN-MYPA-APPLICATION-COMPLETION-20260801-078. Reconcile those requirements against current main rather than replaying historical phases.

Your first deliverable is a current-state gap audit and one integrated implementation plan. Map every requirement to implemented/verified, insufficiently verified, partial, missing, superseded, or deferred. Propose the smallest coherent set of remaining work packages through final merge, post-merge validation, and local/remote cleanup. Include exact repository identity, paths, tests, database and privacy boundaries, frontend/backend contracts, GoodNotes strategy, rollback, mandatory stops, and terminal acceptance mapping.

Do not implement until I return PLAN\_APPROVED. Ask: Is this plan approved?  
\`\`\`

Once the plan is approved, direct Claude Code to execute continuously without routine checkpoint returns. Require one consolidated completion report per work package and continue immediately through review, correction, merge, post-merge validation, and cleanup.

\#\# 14\. Stop condition for the orchestrator

Stop only after:

1\. all current accepted product scope is complete or one mandatory blocker is proven;  
2\. final \`main\` and runtime evidence are authenticated;  
3\. all accepted work is merged;  
4\. post-merge verification passes;  
5\. objective-created branches and worktrees are cleaned up;  
6\. final state is durably published;  
7\. production activation, risk acceptance, and speculative future features remain unclaimed.

Do not activate production. Do not silently broaden the objective. Do not return to the user for routine implementation authorization.  
