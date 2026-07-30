# Governance Audit — `my-pa` Minimum Viable Candidate

**Audit date:** July 30, 2026  
**Repository:** `RMF112018/my-pa`  
**Verified base:** `main@cd6ac07143c2ebeb1f82c6a0bc6c5b5d9d58cd28`  
**Merged scaffold head/tree:** `72c43339103c0b2619dbaf779ae68a65fb1c4074` / `6da8c5c88e83b18972965320a7cb51349c83e232`  
**Stage:** `MINIMUM_VIABLE_CANDIDATE`  
**Delivery target:** August 2, 2026  
**Candidate status:** `CANDIDATE_PENDING_MERGE`

## 1. Conclusion

The repository needs less duplicated governance and more direct enforcement. The smallest effective candidate has three normative documents—`AGENTS.md`, `CONTRIBUTING.md`, and `SECURITY.md`—plus thin routers, one bounded issue form, one pull-request template, CODEOWNERS, one lightweight Actions workflow, and GitHub Actions Dependabot updates.

This set covers code simplicity, MCV scope, architecture, privacy, dependencies, migrations, testing, contribution workflow, and release/change management without reproducing the wider AEOS artifact hierarchy. The normal workflow remains: bounded objective, short-lived branch, focused PR, proportionate checks, review, operator merge, branch cleanup.

## 2. Repository truth

Authenticated GitHub evidence established:

- private repository, default branch `main`;
- current `main` head `cd6ac07143c2ebeb1f82c6a0bc6c5b5d9d58cd28`;
- PR #1 is the only prior PR and merged the documentation-only scaffold; it had no review submissions or discussion comments;
- the current tree contains the 122 paths introduced by PR #1 plus the pre-existing license;
- no open issue, open PR, `.github` workflow/template, or current commit status existed at audit time;
- merge commits, squash, and rebase are all currently enabled; squash-only remains an operator setting;
- complete ruleset, label, milestone, Projects, secret-scanning, push-protection, and security-setting state was not exposed by the connector and is therefore reported as unavailable—not inferred.

Current governance duplication:

| File | Finding | Candidate treatment |
|---|---|---|
| `AGENTS.md` | Correct entry point but incomplete for MCV controls. | Replace with the principal normative engineering policy. |
| `AI_OPERATING_MANUAL.md` | Repeats workflow, evidence, architecture, and prohibitions. | Reduce to compatibility router. |
| `CLAUDE.md` | Already a router. | Retain and simplify. |
| `CONTRIBUTING.md` | Useful human workflow but repeats policy and lacks tiered validation. | Retain as concise normative human workflow. |
| `SECURITY.md` | Correct baseline; incomplete for personal data, cloud disclosure, logging, and workflow supply chain. | Retain and expand proportionately. |
| `docs/00_REPOSITORY_SOURCE_INDEX.md` | Repeats governance sequence. | Reduce to a thin source map. |
| `.ai/project-sources/00_AEOS_MASTER_INDEX.md` | Recreates external governance routing. | Reduce to repository-local router. |

No current governance file requires deletion. Thin pointers preserve tool compatibility and historical links without retaining duplicate policy.

## 3. Drive authority and evidence inventory

Classifications: `CURRENT_AUTHORITY`, `CURRENT_SUPPORTING_EVIDENCE`, `PROPOSED_NOT_AUTHORIZED`, `HISTORICAL_REFERENCE`, `SUPERSEDED`, `DUPLICATE`, `UNVERIFIED`, or `IRRELEVANT_TO_GOVERNANCE`.

| Artifact | Drive ID | Classification | Material requirement / conflict | Read status |
|---|---|---|---|---|
| `00_PKL_FEATURE_INDEX` | `1kNi7DqjMApeSsSLuX0qelqy1B_bqjaHvevSaQOxw2Nc` | `CURRENT_AUTHORITY` | Routes current PKL, audit, plan, evidence, and archive state; identifies the older description as superseded. | Complete |
| Product audit/evidence README | `1bWbwzQhTDqcsSQOCn1E4i08mgvJqihA_` | `CURRENT_AUTHORITY` | Repository is the clean implementation surface; legacy material is evidence, not architecture authority. | Complete |
| Architecture review response | `1Sir5h2-zXLdnEXiw-vSuQLpY0lOXwzEbHugepguWIHc` | `CURRENT_SUPPORTING_EVIDENCE` | Supports modular monolith, gateway/worker/CLI, PostgreSQL search first, durable DB jobs, read-only providers, managed-store separation, and simpler governance. | Complete |
| `PLAN-PKL-ARCH-001-v0.2` | `1IxTM2KySz7WdMy1CMMRfT71DtAcgWvIehwwD5aJfQqA` | `PROPOSED_NOT_AUTHORIZED` | Useful sequencing; over-decomposed service planning is superseded by the simpler architecture review. | Complete |
| Repository evidence package index | `1nwlXLA_BDErTTBm0vswWbfKHfwLZ1F_i` | `CURRENT_SUPPORTING_EVIDENCE` | Inventories exact repository/legacy surfaces, schemas, tests, boundaries, and documented gaps. | Complete |
| Independent repository-truth audit | `1aImrRERQlTnTVkmOKTFHbV2E8ezfQkh-` | `CURRENT_SUPPORTING_EVIDENCE` | Confirms clean-repository need, progressive indexing, provider boundaries, and incomplete runtime implementation. | Complete |
| Scaffold implementation response | `1OJoKo6BKEqx8iJmegOTo7cESNZcwwuZoEQMJvGPapas` | `CURRENT_SUPPORTING_EVIDENCE` | Binds merged PR #1 and confirms documentation-only scaffold with neutral naming and no runtime/data action. | Complete |
| Scaffold manifest | `1HVeTDyIaDRzlfzen4DWo1Eykg-D9c_lkqBwnYjkjTyc` | `CURRENT_SUPPORTING_EVIDENCE` | Exact scaffold inventory and identity. | Routed through response/index |
| Scaffold index | `1CC2MIyN7BxUOad2380ctNTnEcTgZ0guo3ufy7FKVX1c` | `CURRENT_SUPPORTING_EVIDENCE` | Routes implementation evidence. | Routed through response/index |
| Scaffold receipt | `1dOUUP8lsFJuqf5mkdfwW4eSj1m2QCac9yZ_33GhZF2c` | `CURRENT_SUPPORTING_EVIDENCE` | Prior publication binding only; does not authorize current governance. | Routed through response/index |
| Personal Relationship Intelligence description | `1LukPPAU9-9BPINjXJNXYnuJhTZYDe_MSJficqxYxEg4` | `PROPOSED_NOT_AUTHORIZED` | Stable governance implications: fact/claim/inference separation, privacy, source attribution, no moral scoring, explicit action boundaries. | Complete |
| Superseded PKL product description | `1fWtzNE0a8OvC_N7Y6s2xv0dsWLx2WnNvNtce0HWdhT8` | `SUPERSEDED` | Historical intent only; corroborated progressive indexing, source authority, PostgreSQL, managed outputs, rebuildable Obsidian projection. | Complete |
| Source/NAS reconciliation map | `1T59_qw10qH5tL2h5K9iZMEeBvWAxtRVs` | `CURRENT_SUPPORTING_EVIDENCE` | Progressive, reference-driven indexing; NAS is read-only. | Indexed/material requirements read |
| Email/calendar/contacts boundary map | `1NdTEa5bfvq15_6thLFWKvqfQzf2FVNZf` | `CURRENT_SUPPORTING_EVIDENCE` | Personal-data connectors require strict privacy, provenance, and synthetic tests. | Indexed/material requirements read |
| Policy/security/trust/provenance map | `1_afgKd2YprHUyg4C-IdepZ-RTFmKM0JB` | `CURRENT_SUPPORTING_EVIDENCE` | Least privilege, provenance, and evidence separation. | Indexed/material requirements read |

The required Drive searches were completed and results deduplicated by Drive ID. Broad terms also returned unrelated construction files and legacy control artifacts; these were classified `IRRELEVANT_TO_GOVERNANCE` or historical and excluded from the material inventory. The 41-member evidence package was inventoried through its index; raw command logs and TSVs that added no independent governance requirement were not individually hydrated. This is a disclosed limitation, not a claim of byte-level review of every payload.

No current Drive artifact conflicts with accepted ADR-001 or ADR-002. The architecture review supersedes earlier over-decomposition. The archived product description remains superseded. Drive is a review mirror, not a competing engineering ledger.

## 4. Stack-specific findings

The proposed stack is proportionate when implemented as one modular monolith: Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL, and the official MCP Python SDK.

Primary-source conclusions:

- use one `pyproject.toml` for package metadata and tool configuration when code begins: <https://packaging.python.org/en/latest/guides/writing-pyproject-toml/>;
- register pytest markers and use marker selection for FAST/PR/FULL/SPECIALIZED tiers: <https://docs.pytest.org/en/stable/how-to/mark.html>;
- use Ruff as the unified formatter/linter with a small explicit rule set: <https://docs.astral.sh/ruff/configuration/>;
- use FastAPI dependency overrides and synthetic fakes for provider tests: <https://fastapi.tiangolo.com/advanced/testing-dependencies/>;
- isolate SQLAlchemy tests with controlled sessions/transactions: <https://docs.sqlalchemy.org/en/20/orm/session_transaction.html>;
- use Alembic once database implementation exists; never target an unknown physical database: <https://alembic.sqlalchemy.org/>;
- begin search with PostgreSQL full-text search and `pg_trgm`; semantic/vector infrastructure remains benchmark-gated: <https://www.postgresql.org/docs/current/textsearch.html> and <https://www.postgresql.org/docs/current/pgtrgm.html>.

No microservice, Redis, Celery, graph database, dedicated vector database, Kubernetes, plugin framework, or additional governance service is justified for the three-day MCV.

## 5. Governance friction test

Policies retained now prevent plausible near-term failures: scope expansion, accidental personal-data use, destructive source behavior, architecture drift, duplicate dependencies, untested migration behavior, flaky tests, and direct unreviewed changes to `main`.

Controls deferred because their current cost exceeds risk reduction:

- Python Dependabot, dependency review, and CodeQL until a Python manifest/source exists;
- scheduled FULL suites until runtime tests exist;
- path-filtered required checks because skipped required workflows can remain pending;
- a Project board, merge queue, changelog, signed release ceremony, and production controls;
- per-command evidence files, multi-stage AEOS records, and separate policy documents for ordinary MCV work.

## 6. GitHub repository management plan

| Feature | Benefit | Cost | Configuration | Decision | Operator-only |
|---|---|---|---|---|---|
| Short-lived branches | isolates one objective | low | workflow policy | Now | No |
| Main ruleset requiring PR | prevents direct changes | low | ruleset | Now | Yes |
| One approval, stale-review dismissal, resolved conversations | exact-head review | moderate for solo operator | ruleset | Now when independent reviewer available | Yes |
| Required `repository-checks` | links/config now; FAST later | low | workflow + ruleset | Now | Ruleset selection |
| Squash-only and auto-delete branches | concise history/cleanup | low | repository settings | Now | Yes |
| PR template and bounded issue form | scope/minimality/acceptance | low | `.github` | Now | No |
| CODEOWNERS | review routing | low | `.github/CODEOWNERS` | Now; required code-owner gate deferred for solo use | Gate setting |
| Labels and milestone | three-day work view | low | labels/milestone | Five labels + `MCV — 2026-08-02` now | Yes |
| Actions concurrency and least privilege | avoids duplicate runs/reduces token scope | low | workflow | Now | No |
| Immutable Action SHAs | supply-chain integrity | maintenance | workflow | Now | No |
| Dependabot for Actions | maintains pins | max two PRs | `.github/dependabot.yml` | Now | No |
| Secret scanning/push protection, alerts/security updates | prevents secrets and surfaces risk | low/plan-dependent | security settings | Now where available | Yes |
| Python Dependabot, dependency review, CodeQL | dependency/source risk | CI/setup cost | config/workflow/settings | First manifest/source PR | Mixed |
| GitHub Project / merge queue | richer coordination | unnecessary overhead | GitHub settings | Deferred | Yes |
| Releases | binds tested candidate identity | low | tag/release notes | At MCV disposition | Yes |

Recommended `main` ruleset: require PR; require one approval when a genuinely independent reviewer is available; dismiss stale approvals; require conversation resolution and `repository-checks`; block force pushes and branch deletion; use squash merge. Do not require strict up-to-date branches during the three-day MCV unless concurrency increases. GitHub documents rulesets, status checks, templates, and CODEOWNERS: <https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets>.

The candidate workflow grants `contents: read`, cancels superseded runs, and pins third-party Actions to immutable commit SHAs. Dependency caching should be added with the first `pyproject.toml` change, when a real cache key exists.

## 7. Testing policy and timing budgets

The normative policy is consolidated in `AGENTS.md`:

- **FAST:** lint, format, targeted type, unit, domain, and application contracts; target ≤60 seconds.
- **PR:** FAST plus affected schema/migration, synthetic provider conformance, isolated database integration, and security/policy tests; target ≤5 minutes.
- **FULL:** full isolated database integration, synthetic end-to-end, recovery/idempotency, broader conformance, package and migration-from-empty; target ≤15 minutes.
- **SPECIALIZED:** live non-personal canaries, extraction/embedding/search/model evaluation, performance/load/recovery/runtime attestation; on demand.

Markers: `slow`, `database`, `network`, `connector`, `evaluation`, `e2e`, and `recovery`. No live personal data, production credentials, silent retries, accepted flaky tests, or duplicated expensive jobs. Timing targets are adjustable operational budgets, not permanent gates. A test enters PR when it protects a critical contract at acceptable cost; it leaves only with documented replacement risk coverage in FULL or SPECIALIZED.

Because current `main` has no runtime package or tests, the workflow validates links and configuration now and conditionally runs Ruff, mypy, and pytest after `pyproject.toml` exists. The first code PR must provide the `dev` dependency group and registered markers.

## 8. Three-day MCV workflow

**Day 1 — July 30:** review and merge this governance PR; apply operator-only settings; open one bounded vertical-slice issue; add the minimum `pyproject.toml`, `src/my_pa`, Ruff, mypy, pytest, and synthetic fixtures in the implementation PR; make FAST green.

**Day 2 — July 31 / August 1:** implement one complete read-only slice from an explicitly selected source through normalized knowledge records to one retrieval/API or MCP response; add only the contracts and provider/persistence integration needed by that slice; defer additional providers, automation, projections, and scaling.

**Day 3 — August 2:** run the synthetic end-to-end slice, isolated migration checks, and applicable recovery/idempotency tests; document known limitations; operator reviews exact head and records accepted-for-local-development, revision-required, or blocked; if accepted, squash merge, delete branch, and optionally create a pre-release tied to the tested merge commit.

Governance is usable immediately and does not require another design cycle before coding.

## 9. Candidate set and acceptance

Normative documents: **3**.

1. `AGENTS.md` — principal engineering, architecture, scope, testing, dependency, migration, and operational policy.
2. `CONTRIBUTING.md` — concise human workflow.
3. `SECURITY.md` — conventional vulnerability and sensitive-data surface.

Thin routers/indexes: `AI_OPERATING_MANUAL.md`, `CLAUDE.md`, `.ai/project-sources/00_AEOS_MASTER_INDEX.md`, and `docs/00_REPOSITORY_SOURCE_INDEX.md`.

Machine configuration/templates: CODEOWNERS, PR template, bounded issue form, repository-checks workflow, and Actions Dependabot config.

Audit record: this file is rationale/evidence, not a fourth normative policy.

Total repository files changed or added: **13**. No runtime source, migration, connector, dependency manifest, credential, deployment asset, database operation, NAS action, or personal data is included.

Self-validation before PR:

- repository-relative links against the candidate plus authenticated base paths;
- issue-form, Dependabot, and workflow YAML parsing;
- immutable Action SHAs and least-privilege workflow permissions;
- exact changed-file path review;
- neutral current product naming;
- repository/Drive SHA-256 parity against the exact PR head.

Limitations:

- operator-only settings were not mutated and some could not be authenticated through the connector;
- raw nonmaterial evidence-package logs were inventoried but not individually hydrated;
- this audit is self-authored and self-validated, not independent approval;
- test timing budgets are initial because current `main` has no runtime tests.
