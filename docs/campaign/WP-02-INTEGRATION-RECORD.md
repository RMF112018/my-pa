# WP-02 — Selective branch reconciliation: integration record

Repo-local record of what WP-02 carried onto the operating lineage, what it
declined, and what it deferred. Every SHA below was re-derived with
`git rev-parse` in `/Users/bobbyfetting/mypa-wp01` at execution time.

## Lineage

| Fact | Value |
|---|---|
| Operating lineage | `recovery/pre-20260805-utc-rollback-c9fb513` |
| Target head before WP-02 | `49b6f03477fe91e4e3ef562b879b19d32511b38b` |
| Target tree before WP-02 | `6bd5da8292acfa62a503f90bb6b7e31217226b9f` |
| WP-02 branch | `bf/wp-02-selective-branch-reconciliation` |
| Resulting head | `cb3ab727301886412aec3e13dc6a60d405d46c86` |
| Resulting tree | `3362ac345151495a5b7a7b8b5033bc895649b1c7` |
| Alembic head (re-derived, unchanged) | `d2e3f4a5b6c7` across 21 revision files |

Source branch heads and merge-bases with the target, re-derived:

| Branch | Head | Merge-base with target |
|---|---|---|
| `origin/dependabot/github_actions/actions/checkout-7.0.1` | `73bed38b1a6459789ff443c1882e49de9da88041` | `c9fb513a2afadf98f29b6d5ec3ad69db69e5ec1a` |
| `origin/bf/wp-12e-frozen-baseline` | `6348b246f8be66f3db044d50a71b5d90aeeb3f57` | `88e8d8193095afa8d903db08324a588a5786908b` |
| `origin/bf/mcv-neutral-remainder` | `86f13426fab91b4711c5557b10113800ea90a68a` | `634890e0bc089294a242be176280c09766bac493` |
| `origin/bf/extractions-quarantined-debt` | `688cc5047a06f6c193468568765378f23055250b` | `634890e0bc089294a242be176280c09766bac493` |

No branch was merged. Every carried change was applied as a cherry-pick or a
path-filtered patch, each as its own commit.

**Migration impact for the whole of WP-02: none.** No file under `migrations/`
is touched by any commit below;
`git diff --name-only 49b6f034..cb3ab727 | grep '^migrations/'` returns nothing.
The Alembic chain and its head are byte-identical to the target's.

---

## Carried changes

### 1 — `4e8b58b40a189daf45a42f7a3833a6f289cee217`

- **Source:** `origin/dependabot/github_actions/actions/checkout-7.0.1`, commit `73bed38b1a6459789ff443c1882e49de9da88041`
- **Target head before application:** `49b6f03477fe91e4e3ef562b879b19d32511b38b`
- **Patch:** `actions/checkout` 6.0.2 → 7.0.1, SHA-pinned to `3d3c42e5aac5ba805825da76410c181273ba90b1`, at all three call sites.
- **Files / subsystem:** `.github/workflows/repository-checks.yml`. CI only.
- **Canonical-direction compatible because:** CI hygiene with no product surface; it asserts nothing about lineage, ingestion, or work-package order.
- **Migration impact:** none.
- **Dependency conflicts:** none. The target had not touched `.github/workflows/` since the merge-base.
- **Security/privacy:** positive — a SHA-pinned supply-chain bump.
- **Tests:** `tests/architecture` 1342 passed (unchanged at this commit); `ruff check .` clean.
- **Resulting head:** `4e8b58b40a189daf45a42f7a3833a6f289cee217`

### 2 — `f63df283aa860c1724cd5146ec39fc93e3aab06b`

- **Source:** `origin/bf/mcv-neutral-remainder`, commit `8dd4ef6c4f8df24681a1278e6aaf3b13532c9378` (#51), **partial**
- **Target head before application:** `4e8b58b40a189daf45a42f7a3833a6f289cee217`
- **Patch:** `_coverage` caught `ValueError` and nothing else, so a `ProgrammingError` raised inside `coverage_for` escaped `search_extractions` as a `SQLAlchemyError` whose message carried the SQL statement and the bound `enrollment_id`. It now classifies with `_execute`'s handler set — `OperationalError`/`InterfaceError` → `SearchUnavailableError`, everything else → `SearchInternalError` — and raises **outside** the `except` block so nothing is left on `__context__` for a traceback to render.
- **Files / subsystem:** `src/my_pa/infrastructure/persistence/search.py` (the only production source file WP-02 changes); new `tests/architecture/test_search_reads_leave_through_the_redaction_path.py`; `tests/security/test_query_is_data_not_sql.py`.
- **Dropped hunk:** `docs/plans/mcv-completion-plan.md` — it recounts test modules against a lineage this repository does not have.
- **Canonical-direction compatible because:** persistence-layer error redaction is independent of Apple-vs-Graph ingestion, of principal partitioning, and of work-package order.
- **Migration impact:** none.
- **Dependency conflicts:** the only conflicting path in the source commit was the dropped plan-doc hunk; the three carried paths applied cleanly by 3-way.
- **Security/privacy:** **the highest-value change in WP-02.** Closes a live information-disclosure defect confirmed present at the target head. Adds a syntax-tree-derived guard so the rule is mechanized rather than held in the module docstring — prose is what let this stay open for a whole work package.
- **Tests:** the new architecture guard (4 tests) passes. The two security tests that exercise the fix end-to-end — `test_no_database_failure_in_any_read_a_search_performs_discloses_a_statement[the delegated coverage read]` and `[this module's own page read]` — are **database-tier and were NOT run**; see "Tests not run" below.
- **Resulting head:** `f63df283aa860c1724cd5146ec39fc93e3aab06b`

### 3 — `67f469c383df3875e6cf5194a88989c2fcb3fcef`

- **Source:** `origin/bf/mcv-neutral-remainder`, commit `2710802e292e7e388e879473d8a8079592894536`, **partial**
- **Target head before application:** `f63df283aa860c1724cd5146ec39fc93e3aab06b`
- **Patch:** the section-14 scan terminated on the literal `"### Five questions"`. A renamed or inserted heading silently widened the sweep, and the guard then reported a wrong count and a spurious duplicate rather than "the boundary moved". The terminator is now any ATX heading that is not one of the three group headings.
- **Files:** `tests/architecture/test_open_decision_counts.py`.
- **Dropped hunk:** `docs/plans/mcv-completion-plan.md`.
- **Canonical-direction compatible because:** a guard-class fix; it makes no claim about product state.
- **Migration impact:** none. **Dependency conflicts:** none.
- **Security/privacy:** neutral.
- **Tests:** `tests/architecture` green; test count for this file unchanged at 11 (logic change, no new test function).
- **Resulting head:** `67f469c383df3875e6cf5194a88989c2fcb3fcef`

### 4 — `5f667a92c2238d6c2ec41d41e85f82ea39e8c00d`

- **Source:** `origin/bf/mcv-neutral-remainder`, commit `f44f45db3c6604083822c0d42e1f5502bf90dc4a`, **partial**
- **Target head before application:** `67f469c383df3875e6cf5194a88989c2fcb3fcef`
- **Patch:** adds `tests/architecture/test_ci_invokes_mypy_over_the_declared_tree.py`, mechanizing D-64. The target already invokes `python -m mypy` bare in both jobs and declares the tree in `[tool.mypy] files`, but that was held **only by prose comments in the workflow**: a third job written `mypy src` would silently reopen D-64 with every gate green. Also strengthens three provenance assertions that took their expected value off the object under test (`assert extractor` held for any non-empty string).
- **Files:** `tests/architecture/test_ci_invokes_mypy_over_the_declared_tree.py` (new), `tests/contract/test_application_capabilities.py`, `tests/end_to_end/test_vertical_slice.py`, `tests/schema/test_extraction_schema_migration.py`, `tests/schema/test_knowledge_schema_migration.py`.
- **Dropped hunks:** `docs/plans/mcv-completion-plan.md`; `tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py` (keyed to the extractions branch's 16-revision chain, which this lineage does not have — it conflicts and its measurement would be false here).
- **Note on a hunk the triage listed as droppable but which was carried:** `tests/schema/test_extraction_schema_migration.py`. Verified applicable — `ExtractionOutcome.is_truncated` exists at `src/my_pa/domain/extraction/text.py:130` on the target — and it is a strengthening (a parametrized round-trip where the `False` row is the control and the `True` row the measurement). It is database-tier and does not run here.
- **Canonical-direction compatible because:** mechanizes invariants the target already holds informally; adds no product claim.
- **Migration impact:** none. `tests/schema/test_extraction_schema_migration.py` is a test module, not a revision.
- **Dependency conflicts:** the two dropped paths were the only conflicting ones.
- **Security/privacy:** positive — closes a type-checking coverage gap that was reopenable without any gate reddening.
- **Tests:** `tests/architecture` green; the new guard contributes 34 tests.
- **Resulting head:** `5f667a92c2238d6c2ec41d41e85f82ea39e8c00d`

### 5 — `03a379aabdcb50c8b7e60e8608d11c7b5aa140e7`

- **Source:** `origin/bf/mcv-neutral-remainder`, commit `f4cafbf07473a62702b3490e0a9f76bedafd66e6`, **partial**
- **Target head before application:** `5f667a92c2238d6c2ec41d41e85f82ea39e8c00d`
- **Patch:** makes the CI-invocation guard fail closed (zero invocations found ⇒ red, not green), and takes the README/limitation section scans to the next Markdown heading rather than to a second literal a rename can detach.
- **Files:** `tests/architecture/test_ci_invokes_mypy_over_the_declared_tree.py`, `tests/architecture/test_limitations_cite_evidence.py`, `tests/architecture/test_readme_state_claims.py`.
- **Dropped hunks:** `docs/plans/mcv-completion-plan.md`; `tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py`.
- **WP-01 interaction — the flagged risk, and how it resolved.** The source hunk lands on `tests/architecture/test_readme_state_claims.py`, the file WP-01 extended by 73 lines at the target head. The two change sets were read against each other line by line: the imported hunk adds `_HEADING`, `section_of`, `readme_section` and one new test, and modifies two pre-existing tests. It touches **none** of WP-01's additions. `INGESTION_CLAIM`, `frontend_paragraph`, `test_readme_declares_the_operating_lineage_branch_and_denies_main_authority`, `test_readme_declares_apple_first_personal_data_ingestion` and `test_readme_declares_graph_off_by_default_and_entra_separate_from_activation` are byte-identical to the target head; a `git diff` of the commit filtered to those symbols is empty. **No WP-01 assertion is altered, weakened, or removed, and all remain green.**
- **One adaptation, recorded rather than silent.** The hunk's non-emptiness precondition on the README's not-implemented region arrived as `len(entries) >= 2`, a threshold keyed to the source branch's README. This repository's not-implemented list names exactly one item, so the imported guard went red on import. The threshold is now "at least one entry" (`assert entries`). This is not a weakening: the property the assertion exists to establish is that the region has not collapsed to empty, which would leave the following `not in` check passing on nothing; one entry establishes that completely. `>= 2` was itself a spelled count of a set that shrinks as packages land — the exact defect the sibling guards in this commit were being unkeyed from. The reasoning is written into the test's docstring.
- **Canonical-direction compatible because:** guard-class hardening only. A guard that cannot fire is this campaign's named failure mode.
- **Migration impact:** none.
- **Security/privacy:** positive, indirectly — fail-closed guards.
- **Tests:** `tests/architecture` 1382 passed.
- **Resulting head:** `03a379aabdcb50c8b7e60e8608d11c7b5aa140e7`

### 6 — `12cbe014bddfd47c90fa7115d0055e149bbc635c` (consequential, not a port)

- **Source:** none. Authored in WP-02 as a consequence of ports 2 and 4.
- **Target head before application:** `03a379aabdcb50c8b7e60e8608d11c7b5aa140e7`
- **Patch:** one word in `docs/plans/mcv-completion-plan.md` section 3: "one hundred and twenty-two test modules" → "one hundred and twenty-four".
- **Why it was necessary.** WP-02 planned to leave the plan document untouched. That turned out not to be free: the target ships a live guard, `test_section_3_states_the_module_counts_it_says_it_derives`, that binds that spelled figure to `find tests -name "test_*.py"`. Ports 2 and 4 each add one test module, so the tier went red on the count alone. This is exactly what the dropped plan-doc hunks were partly doing, and it is the one part of them that is true here.
- **Files:** `docs/plans/mcv-completion-plan.md`, one line.
- **Canonical-direction compatible because:** a figure re-derived from the tree. None of the document's superseded MCV work-package narrative, D-108/D-109 bookkeeping, or tier figures dated to foreign heads was imported.
- **Migration impact:** none. **Security/privacy:** nil.
- **Tests:** `tests/architecture` 1382 passed.
- **Resulting head:** `12cbe014bddfd47c90fa7115d0055e149bbc635c`

### 7 — `77c0d28973d52a0eaa2d0c8552fa9a422e8cbdeb`

- **Source:** `origin/bf/mcv-neutral-remainder`, commit `86f13426fab91b4711c5557b10113800ea90a68a` (branch head), cherry-picked whole
- **Target head before application:** `12cbe014bddfd47c90fa7115d0055e149bbc635c`
- **Patch:** derives the limitation and current-state scan boundaries from headings too — the final form of the guard trio.
- **Files:** `tests/architecture/test_ci_invokes_mypy_over_the_declared_tree.py`, `test_limitations_cite_evidence.py`, `test_spelled_counts_match_the_sets_they_name.py`.
- **Canonical-direction compatible because:** guard-class hardening only.
- **Migration impact:** none. **Dependency conflicts:** none once ports 4 and 5 were in; auto-merged.
- **Security/privacy:** neutral-positive.
- **Tests:** `tests/architecture` 1382 passed.
- **Resulting head:** `77c0d28973d52a0eaa2d0c8552fa9a422e8cbdeb`

### 8 — `234c44529a403c70eef557039cad4a6a00f771aa`

- **Source:** `origin/bf/extractions-quarantined-debt`, commit `c5556a17de60d4848ba895f8d7a6ca188f1c4f14`, cherry-picked whole
- **Target head before application:** `77c0d28973d52a0eaa2d0c8552fa9a422e8cbdeb`
- **Patch:** adds `SWEPT_FILES = ("README.md",)` so the repository-root README enters the spelled-count sweep, plus one documented excusal row. Brings the README's four "fifteen capabilit*" claims under mechanical check; `Capability` has exactly 15 members.
- **Files:** `tests/architecture/test_spelled_counts_match_the_sets_they_name.py`.
- **Canonical-direction compatible because:** pure guard widening over a file WP-01 just made canonical.
- **Migration impact:** none. **Security/privacy:** positive.
- **Tests:** that module 14 passed; tier green.
- **Resulting head:** `234c44529a403c70eef557039cad4a6a00f771aa`

### 9 — `7f25709c870ffb6bd208d40bb0eb466ff6f1bb22`

- **Source:** `origin/bf/extractions-quarantined-debt`, commit `688cc5047a06f6c193468568765378f23055250b` (branch head), cherry-picked whole
- **Target head before application:** `234c44529a403c70eef557039cad4a6a00f771aa`
- **Patch:** corrects a **false justification** on the excusal row the previous commit added. The row claimed "the size of the `capture.*` subset named in full"; `capture.*` has five members (`create`, `revise`, `read`, `list`, `search`), not four. Restated as the WP-6 delta. No behaviour change; the row stays load-bearing.
- **Files:** `tests/architecture/test_spelled_counts_match_the_sets_they_name.py`.
- **Sequencing:** applied immediately after commit 8, as required. Porting 8 without 9 would land a documented-false ground in the file whose job is recording true grounds.
- **Migration impact:** none. **Security/privacy:** positive.
- **Tests:** `tests/architecture` 1382 passed.
- **Resulting head:** `7f25709c870ffb6bd208d40bb0eb466ff6f1bb22`

### 10 — `cb3ab727301886412aec3e13dc6a60d405d46c86` (documentation follow-ups logged by WP-01)

- **Source:** none. Authored in WP-02 against two files outside WP-01's path list.
- **Target head before application:** `7f25709c870ffb6bd208d40bb0eb466ff6f1bb22`
- **`web/README.md`:** declared `Status: IMPLEMENTING (WP-02 / R1)` for a shell in fact built across WP-00 through WP-06 of the superseded Moss v4.0 campaign, and listed "the Microsoft Graph connector (WP-07)" among the things pending delivery — presenting the superseded Graph-primary sequencing as a live commitment. It now states the delivered-but-not-deployable status; warns explicitly that its `WP-nn`/`Rn` labels are the superseded campaign's numbering and not the current campaign's, which reuses the same numbers for different work; and carries the posture already canonical in the repository README — **Apple-first** personal-data ingestion (Apple Mail, Calendar, Contacts, Tasks/To-Do via the native Apple host), with **Microsoft Graph retained but off by default and not an active personal-data ingestion path**, a disabled connector never reported as a degraded active source, and Entra authentication a separate concern from Graph connector activation.
- **`docs/architecture/system-context.md`:** cited "Alembic owns the schema history at eleven revisions, head `1a4c9e77b2d5`". Re-derived from `migrations/versions/` on the operating lineage: **twenty-one revisions, head `d2e3f4a5b6c7`**. Both figures were derived here, not copied.
- **No new product claims.** Both corrections either restate truth already established in the repository README by WP-01, or re-derive a figure from the tree. `system-context.md` makes no Microsoft/Apple ingestion claims at all, so only its Alembic figure was stale there.
- **Migration impact:** none — `system-context.md` describes the chain, it does not participate in it.
- **Security/privacy:** nil.
- **Tests:** `tests/architecture` 1382 passed; `ruff check .` clean. No test guard references either file (`grep -rl` over `tests/` returns nothing), so these corrections are currently unmechanized — see backlog.
- **Resulting head:** `cb3ab727301886412aec3e13dc6a60d405d46c86`

---

## Declined

### Declined in WP-02 after evaluation

**`6e491c24db97bd1ff2c537be4fbb58ff75ed2b81`** (`origin/bf/mcv-neutral-remainder` / `origin/bf/extractions-quarantined-debt`, #52) — the authorized conditional split of the `src/my_pa/bootstrap/settings.py` validator-bypass fix. **Declined: not cleanly separable**, which was the stated condition.

- The `settings.py` hunk does not decompose. It imports `POOL_TIMEOUT_SECONDS` from `src/my_pa/infrastructure/database/engine.py`, defines `DEFAULT_STATEMENT_TIMEOUT_MS` from it, adds a `statement_timeout_ms` settings field, and adds a `_REFUSED_URL_PARAMETER = "options"` refusal whose message points the operator at `MY_PA_STATEMENT_TIMEOUT_MS`. The parser swap and the statement-timeout feature are one change.
- **Its tests are worse.** Every one of the five new test functions in `tests/unit/test_settings.py` asserts on machinery WP-02 is not authorized to port: four match on `"must not set the libpq options parameter"` or `MY_PA_STATEMENT_TIMEOUT_MS`, and the fifth — `test_the_validator_and_the_engine_read_the_same_url_the_same_way`, the one that actually states the parser-agreement rule — is a biconditional over "does this URL supply an `options` parameter", which is vacuously false without the refusal. There is **no test of the parser swap alone**. Porting the production hunk without the statement-timeout work would land a change to a production source file with zero accompanying tests; porting the tests would pull in `engine.py`, `gateway.py`, three CLIs, `apps/worker.py` and `migrations/env.py`, i.e. feature implementation plus the forbidden migration touch.
- Per instruction: declined, target left as-is, recorded here. Not forced.
- **21 files of this commit are not ported:** `apps/cli/health.py`, `apps/cli/migration.py`, `apps/cli/sources.py`, `apps/worker.py`, `docs/plans/mcv-completion-plan.md`, `migrations/env.py`, `ops/runbooks/postgres-operations.md`, `scripts/migration/reconcile.py`, `src/my_pa/bootstrap/gateway.py`, `src/my_pa/bootstrap/settings.py`, `src/my_pa/infrastructure/database/engine.py`, `src/my_pa/infrastructure/persistence/capture_search.py`, `src/my_pa/infrastructure/persistence/registry.py`, `src/my_pa/infrastructure/persistence/unit_of_work.py`, `tests/architecture/test_every_engine_is_bounded_or_exempt.py`, `tests/architecture/test_no_stored_revision_is_labelled_head.py`, `tests/end_to_end/test_vertical_slice.py`, `tests/search_quality/test_lexical_search.py`, `tests/unit/test_gateway_composition.py`, `tests/unit/test_settings.py`, and this commit's further changes to `tests/security/test_query_is_data_not_sql.py`. (Its `src/my_pa/infrastructure/persistence/search.py` and `tests/architecture/test_search_reads_leave_through_the_redaction_path.py` changes are *later* revisions of files WP-02 carried at their `8dd4ef6c` state; the `6e491c24` versions are not ported.)

> **Escalation — read this before deferring #52 further.** While testing separability, a **second and more consequential divergence** was measured, distinct from the `options` case named in the WP-02 brief and, unlike it, live at the target head today.
>
> `_validate_database_url` and `create_database_engine` do not use the same URL parser. For some inputs the two parsers disagree about which server and database a connection string designates, so the configuration the validator approves is not necessarily the configuration the engine connects to. The `options` case named in the WP-02 brief is a real parser divergence but has **no exploitable consequence at the target head**, because the target sets no `options` in `connect_args` and enforces no query-parameter rule; the framing should be corrected when this is next scheduled.
>
> **Reproduction detail is deliberately withheld from this public repository** under `SECURITY.md`, which prohibits publishing exploit details and reserves disclosure to the repository owner. It has been reported to the operator through the campaign report channel. Do not restate the crafted-input form here or in commit messages, issues, or pull requests.
>
> Exposure requires control of the deployment's database URL, so this is a configuration-integrity defect rather than a remotely reachable one. The remedy is small and does not require the statement-timeout feature: validate and connect through a single parser, reading `drivername` / `host` / `database` from it. It needs a test written for it, which is authoring beyond WP-02's mandate. **Recommend scheduling as its own bounded work package rather than leaving it inside the WP-03 migration backlog, which it does not belong to.**

### Declined by triage (6 commits, direction-incompatible or false-at-target)

| SHA | Subject | Reason |
|---|---|---|
| `316a4712a359fe9ffdbd0983fba6859952609a64` | docs(plan): supersede section 10's four now-false sentences in place | Documentation-only; records the old MCV work-package order as current, and asserts that #51/#52 landed — neither is in this lineage. |
| `0f046d05d1d1ef72afca67ffeaf329b9d2faf8e7` | docs(plan): close item (1) and record the disposition as D-108 | Old-MCV-order bookkeeping; the disposition has no referent here. |
| `b83328f3c265018177d184328cafc737f383280e` | docs(readme,plan): record the downgrade defect as D-109 | States DATABASE-tier pass/fail figures measured against a head that does not exist in this lineage. Re-measure, do not transcribe. |
| `e4050a436632ba7129fd0fd93987b5efc64418ab` | docs(readme,plan): reconcile the tier figures with the run that produced them | Restates figures that are not true of the target. |
| `f25d875a8555636aed44cefb5e65d164c6fbe628` | docs(plan): date the gate figures to the head that produced them | One-line edit dating figures to a foreign head. |
| `f21e2f6000016a4c973f219d10a267b07e990c2a` | docs(readme,tests): state the raw-SQL blind spot at its measured scope | Its measured scope is a 16-revision chain the target does not have; both the README sentence and the guard docstring would be false here. Conflicts on both files. |

---

## Deferred to WP-03 (15 commits)

WP-03 is **migration-chain only**. Every commit below either touches
`migrations/**` directly or is inseparable from one that does.

| SHA | Subject | Reason |
|---|---|---|
| `355a0f8b6fffe180823522df4345079eaaa7e117` | WP-12E: implement frozen native-source baselines | Adds revision `20260805_a7c3e8d1f642`. |
| `6348b246f8be66f3db044d50a71b5d90aeeb3f57` | WP-12E: bind baseline progress to admitted pages | Modifies the same revision; inseparable from the above — they move as one patch. |
| `8e7d6a32f6119212481eb9dc752fefa9bfd2443a` | feat(schema): narrow the extractions status vocabulary | ORM CHECK narrowing is only correct alongside revision `9d4e7a3b1c62`; alone it would make `tables.py` assert a constraint the database lacks. |
| `e37ee0533608c5039d535a5bd6567570f23dadb3` | test(schema): replace the lost derivation with a subset assertion | Strictly dependent on the above. |
| `0cf63f247c39ce882dbcc5fa0ce5b09f4983e593` | feat(migrations): converge an already-migrated database with a freshly built one | Adds revision `20260808_9d4e7a3b1c62`. The extraction-status cluster's anchor. |
| `e2127124177a91eaa90ec005cca177b41714822d` | test(search),docs(extraction): move the property from demonstration to refusal | Its replacement test's premise *is* the narrowed CHECK. Inspected and cleared: a strengthening (server-side refusal naming `extraction_status_is_known`), not a weakening. |
| `dac9c37573e91d8558b194c60ce6f752bc6b0ebe` | fix(migrations): restore the vocabulary the revision below denotes | Modifies a revision. |
| `6667d70ede7246621a20fa7dc9e6a47dbb8ed39a` | fix(tests,persistence,plan): remove three stale counts, state the D-81 raw-SQL limit | Cluster dependency; the docstring is only true once the vocabulary is narrowed. |
| `288bdb14aaaee209741c3211098b87a74d89e7f1` | fix(tests): key the downgrade guard on (table, constraint) | Hardens a file introduced by `dac9c375`, absent from the target. |
| `dcc9726637c3a35a85bbaf8465d4de654e37072f` | fix(tests): make the downgrade guard's reader fail closed instead of skipping | Modifies a revision. Genuine fail-closed improvement. |
| `c34d5f02b7da82b7008f1bb2ea25cf95036a3323` | fix(tests): measure downgrade convergence against a server, delete the parser | Modifies a revision. The test-file deletion was read on both sides and is a legitimate replacement by a stronger server-measured guard. **Redaction note for WP-03:** its new fixture calls `render_as_string(hide_password=False)` and writes the result into `os.environ[MY_PA_DATABASE_URL]` — not logged, but a rendered traceback over that local could disclose a DB password. |
| `8c94e6f24e3b55f00ed5e8f5266f4a8e10327dd1` | fix(tests): compare four kinds of schema fact, not constraints alone | Dependent on `c34d5f02`. |
| `91afbad529fd01250d5485779912fc32045587d3` | fix(tests): compare seven kinds of schema fact | Modifies a revision. |
| `cd80ae1c71412ce60dcdbf86a9a554bc5e596f80` | fix(tests,readme): state the snapshot's reach by enumeration | Dependent on a file the target does not have. |
| `6e491c24db97bd1ff2c537be4fbb58ff75ed2b81` | fix(persistence,db): discharge the direction-neutral MCV debt | Touches `migrations/env.py`. See the escalation above — the settings fix inside it should be scheduled separately, **not** carried as WP-03 migration work. |

### WP-03 acceptance conditions carried forward

1. **Principal partitioning.** WP-12E's baseline tables (`355a0f8b`, `6348b246`) were authored on WP-12C, *before* the WP-00…WP-06 principal-partitioning revisions existed. They carry **no `principal_id`**. Its revision must be re-chained onto head `d2e3f4a5b6c7`, and **the baseline tables must be principal-partitioned before admission.** This is an acceptance condition, not a note.
2. **Chain divergence.** The extractions branch holds 16 revisions and has none of the target's `20260804_8c4d1e7a2b90`, `20260805_9d5e2f7b4c61`, or the WP-00…WP-06 principal revisions. Every deferred revision needs re-chaining, not replaying.
3. **Re-measure, never transcribe.** Four of the six declined commits are declined solely because they transcribe tier figures, revision counts, or D-numbers measured against a foreign head. If the cluster lands, re-derive those figures at the resulting head.

---

## Backlog — not WP-02, and explicitly not WP-03

- **`docs/plans/mcv-completion-plan.md` wholesale reconciliation.** WP-02 dropped a plan-doc hunk from every partial port and changed exactly one word in the file (a count the tree forced, port 6). The document remains live authority — `README.md:107`, `docs/00_REPOSITORY_SOURCE_INDEX.md:54` — while narrating the superseded MCV work-package order, section 10 "carried into WP-4", and D-108/D-109 dispositions with no referent in this lineage. **This is a documentation-reconciliation item. WP-03 is migration-chain only and this is not in its scope.**
- **The `settings.py` validator/engine parser divergence.** See the escalation above. Live, exploitable, and orphaned between work packages.
- **`docs/architecture/system-context.md` residual staleness.** WP-02 corrected the Alembic figure it was asked to correct. The same paragraph still says "WP-6 brought the total to twelve" capability use cases where the repository README states fifteen and `Capability` has 15 members. Out of WP-02's named scope, deliberately not touched, and now inconsistent with a claim that *is* mechanically guarded.
- **Neither `web/README.md` nor `docs/architecture/system-context.md` is bound by any test.** `grep -rl` over `tests/` finds no guard referencing either path, so the corrections made in port 10 can drift again silently. The repository README's equivalent claims *are* guarded, by WP-01's additions to `tests/architecture/test_readme_state_claims.py`. Extending that mechanization to these two files is the obvious follow-up.

---

## Validation at `cb3ab727301886412aec3e13dc6a60d405d46c86`

Command used throughout, from `/Users/bobbyfetting/mypa-wp01`:

```
PYTHONPATH=/Users/bobbyfetting/mypa-wp01/src:/Users/bobbyfetting/mypa-wp01 \
  /Users/bobbyfetting/my-pa/.venv/bin/python -m pytest <paths> -q -p no:cacheprovider
```

| Check | Result |
|---|---|
| `tests/architecture` | **1382 passed**, 0 failed |
| `tests/architecture` at target head `49b6f034` | 1342 passed (baseline re-measured, confirms the brief) |
| `ruff check .` | **All checks passed!** |
| `migrations/` paths in `git diff --name-only 49b6f034..HEAD` | **none** |

Delta accounted exactly, +40:

| Source | Tests |
|---|---|
| `test_search_reads_leave_through_the_redaction_path.py` (new, port 2) | +4 |
| `test_ci_invokes_mypy_over_the_declared_tree.py` (new, ports 4/5/7) | +34 |
| `test_readme_state_claims.py` — `test_a_readme_section_stops_at_the_next_heading` (port 5) | +1 |
| `test_limitations_cite_evidence.py` (port 5) | +1 |
| **Total** | **+40** → 1342 + 40 = 1382 |

Nothing was skipped, xfailed, deleted, or weakened to reach this. The one
threshold adaptation is documented under port 5 and in the test's own docstring.

### Tests NOT run — stated plainly

**There is no PostgreSQL available in this environment.** `127.0.0.1:5432`
refuses connections and `MY_PA_DATABASE_URL` is unset. Every database-tier test
errors at fixture setup, at the target head and on this branch alike.

- `tests/security/test_query_is_data_not_sql.py`: **68 passed, 73 errors** here, against **64 passed, 71 errors** at the target head. The port added 4 passing non-database tests; the error count rose by exactly 2, both of them the new parametrizations of `test_no_database_failure_in_any_read_a_search_performs_discloses_a_statement` — the very tests that exercise port 2's redaction fix end-to-end. **They were not observed to pass. No claim is made that they do.** The fix is nonetheless covered here by the syntax-tree guard `tests/architecture/test_search_reads_leave_through_the_redaction_path.py` (4 tests, passing), which derives every connection-touching call from `search.py`'s AST and fails if a read is written outside the redacting shape or if a `raise` moves back inside an `except`.
- `tests/end_to_end/test_vertical_slice.py`: 9 errors, identical at the target head. Pre-existing and environmental.
- The database-tier hunks carried into `tests/schema/test_extraction_schema_migration.py` and `tests/schema/test_knowledge_schema_migration.py` were likewise **not executed**.

**Running the DATABASE tier against a live PostgreSQL is an outstanding
validation obligation for this branch.**
