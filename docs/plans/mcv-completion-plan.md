Warning: truncated output (original token count: 60029)
Total output lines: 2431

Warning: truncated output (original token count: 60031)
Total output lines: 2429

Warning: truncated output (original token count: 89439)
Total output lines: 2548

# MCV Completion — Gap Audit and Integrated Implementation Plan

Plan basis: `PLAN-MYPA-APPLICATION-COMPLETION-20260801-078` (Drive `1-jfuAm3p1bQSC3l-37rFw6wk82HFQ9MKalR-LZm_U3Q`).
Audit basis: `main@e773e6f2285da9e453a8ca7e11bdac23619aaf22`, audited 2026-08-01.
Revalidated against `main@8274d88a6211c417c43d2d937edfe2c8ccc369be` on 2026-08-02, after
work packages WP-2 and WP-3 merged and the operator reprioritized the objective.
Section 1 records the current identities; the sections below it were corrected
in place rather than left to be read as current. Its five repository-state rows
— the local head, the worktree, the branches, the worktrees, and the open pull
requests — are the exception and are the state at the dispatch basis, named as
such rather than restated, because no document holds them current between two
commits. Its container, database, extension and Alembic rows are current, and
the Alembic row is derived rather than written down:
`../../tests/architecture/test_spelled_counts_match_the_sets_they_name.py` reads
this section and section 3 and fails when either disagrees with the chain.

This document is the current-state gap audit and the integrated work-package plan
required before implementation resumes. It records what the repository actually
contains, what repository policy and specification require, and where the
dispatched plan and repository policy disagree.

The dispatched plan is mirrored at `evidence/completion/PLAN-MYPA-APPLICATION-COMPLETION-20260801-078.md`
so that every section cited below can be checked against a file in this
repository rather than a link a reviewer cannot open. That mirror is evidence of
what was dispatched, not repository authority; `CONTRIBUTING.md` governs, and
Drive mirrors are review surfaces rather than a competing ledger.

## 1. Authenticated identities

| Fact | Value | How verified |
|---|---|---|
| Repository | `RMF112018/my-pa` | `git remote -v` |
| Local `main` head | `8274d88a6211c417c43d2d937edfe2c8ccc369be` | `git rev-parse HEAD` |
| Dispatch basis | identical to local head | comparison |
| Worktree | clean, no untracked files | `git status --porcelain` empty |
| Branches | `main` only; no stale feature branches | `git branch -a` |
| Worktrees | one, the primary checkout | `git worktree list` |
| Open pull requests | none; #1–#22 all merged | `gh pr list --state all` |
| Database container | `my-pa-postgres`, `postgres:17.10`, healthy | `docker ps` |
| Database binding | `127.0.0.1:5433 -> 5432`, loopback only | `docker ps` port map |
| Logical database | `my_pa` | `select current_database()` |
| Alembic head | `d4e8b1c7a902` in the repository, ninety-three revisions; re-measured 2026-09-05 after UI-IMP-WP17 re-parent onto R8: ninety-three files and single head `d4e8b1c7a902`; `d4e8b1c7a902` is additive on `6a2f9d1c4b80` and adds the immutable GoodNotes semantic promotion receipt; `6a2f9d1c4b80` is additive on `c3f8a1d07e94` and adds the GoodNotes pull ledger; `c3f8a1d07e94` admits `entities.graph` on `b8e4d1a6c073`. The prior merge of `origin/main` `455a3671` held eighty-nine files with `b8e4d1a6c073` as its Alembic tip (`origin/main` held eighty-eight at `16f05c46b8c3`; WP-13 added no revision); `b8e4d1a6c073` is additive on `16f05c46b8c3` and backfills one `display`-typed `entity_names` row per active `entities` row (`display_value` from `entities.display_name`, `normalized_value` from `entities.canonical_name`, never a `legal` name), writing no `entity_project_participations` row -- no legacy row is directly representable, since `project_display_name` is `NOT NULL` and the legacy plane carries no project-facing name, `RULING-M10` -- no `entity_addresses` and no `entity_communication_methods` row, and leaving `entity_aliases`, `entity_assignments` and `entity_external_identifiers` untouched (RI-ENT-WP-12; written against `c99cd8ed8d1c` and re-parented onto `16f05c46b8c3` once RI-ENT-WP-10/11 merged so the chain holds one head, `RULING-M11`; eighty-nine counted on the merged tree 2026-09-03 rather than derived from either side, eighty-eight having been counted on the merged tree 2026-09-02: UI-IMP-WP02 corrected eighty-six at `c99cd8ed8d1c` to eighty-seven at `2c00c9ac64bc` on 2026-09-01, RI-ENT-WP-10/11 corrected that same eighty-six to its own eighty-seven at `16f05c46b8c3` on 2026-09-02, and neither figure is true of a tree carrying both); `16f05c46b8c3` is additive on `2c00c9ac64bc` -- onto which it was re-parented at the base merge, both revisions having been written against `c99cd8ed8d1c` -- and widens three closed CHECK sets -- `audit_events.capability_is_known` from 115 to 135 values, `entity_mutation_events.a_mutated_record_family_is_known` from six to eleven, and `entity_proposals.an_accepted_proposal_record_family_is_known` from six to eleven for metadata parity with the shared `_one_of(..., MutationRecordFamily, ...)` declaration -- so the capability names RI-ENT-WP-10 and RI-ENT-WP-11 published, twenty in all, and their five new record families can be recorded at all; `purpose_is_known` is deliberately not widened, because neither work package adds a `Purpose`; `2c00c9ac64bc` is additive on `c99cd8ed8d1c` adding WebAuthn credential, challenge, recovery-code, and opaque session tables (UI-IMP-WP02); `c99cd8ed8d1c` is additive on `1cda4d536268` and renames the seeded `entity_relationship_types` row `design_coordinates_with` to `design_coordination_with` (every other column unchanged), closing `EntityRelationshipType` to 35-of-35 parity with the taxonomy table (the WP-08 blocker-clearing rename); `1cda4d536268` is additive on `9a3f6c1e8d24` adding the `entity_assertions`/`entity_assertion_evidence` tables, binding fact-level `assertion_status` and evidence to the six Entity-bound record families RI-ENT-WP-02 through RI-ENT-WP-06 added (RI-ENT-WP-07, closes `ENTITY-PROVENANCE-001`); `9a3f6c1e8d24` is additive on `8dc3619891bb` and widens the `entity_identity_effects`/`entity_identity_preview_ambiguities`/`entity_identity_ambiguity_settlements` `record_family` CHECKs to admit six new Entity-bound families (RI-ENT-WP-06b); `8dc3619891bb` is additive on `17149a48fa30` adding the `entity_relationship_types` table and re-pointing `entity_relationships.relationship_type` at it by foreign key (RI-ENT-WP-06a); the chain admits GSQS at `c4b0a1d9e827` immediately before Phase B continues at `c7a1f04b9e63`, `b727e870d45e` is additive on `8e1c4a7b2d90`, `7e114f822af2` is additive on `b727e870d45e` adding the `entity_names`/`entity_organization_profiles` tables (RI-ENT-WP-02), `441b071bf37b` is additive on `7e114f822af2` adding the `entity_addresses`/`entity_communication_methods` tables (RI-ENT-WP-03), `f5b06925857e` is additive on `441b071bf37b` adding the `entity_project_participations`/`entity_role_types`/`entity_discipline_types` tables (RI-ENT-WP-04), `17149a48fa30` is additive on `f5b06925857e` adding the `entity_person_organization_affiliations` table (RI-ENT-WP-05); local validation targets disposable databases only. Counted on the merged tree 2026-09-02, both branches having corrected `c99cd8ed8d1c`/eighty-six to an eighty-seven of their own (prior correction, from `1cda4d536268`/eighty-five, itself from `9a3f6c1e8d24`/eighty-four) | `migrations/versions/*.py`, `alembic heads` |
| Extensions | `pg_trgm`, `unaccent`, `plpgsql` | `select extname from pg_extension` |

## 2. Verified corpus claim

Commit `f34eb96` claims a migrated corpus of 3,263,870 rows across 484 domain
tables. That claim was **recomputed, not restated**, by counting live rows across
the seven domain schemas:

```
total_rows       3263870
domain_tables    484
tables_with_rows 286
```

Per-schema table counts: `core` 161, `procore` 150, `financial` 67,
`schedule` 43, `construction` 26, `email` 26, `calendar` 11. An eighth domain
schema, `contacts`, exists and holds zero base tables, so it changes no count.
Plus `migration_control` 9 and `public` 1, which are not domain tables.

The claim is **exact**. 198 of the 484 tables are empty, which
`migrations/data/disposition_registry.json` already accounts for; an empty table
is not a defect.

## 3. What is implemented

Three hundred and twenty-seven Python modules under `src/my_pa` and four hundred and seventy-six test modules —
`find src/my_pa -name "*.py"` and `find tests -name "test_*.py"`. Corrected on 2026-09-04 to **three hundred and eighteen and four hundred and fifty-nine** by merging `origin/main` `455a3671` (PR #181, RI-ENT-WP-13, whose merge already carried PR #186) into `ri-ent/wp12-backfill`: `origin/main` recorded three hundred and eighteen and four hundred and fifty-seven, true of *its* tree at `12d6c698`; this branch recorded three hundred and eighteen and four hundred and fifty-two at `92bb5e56`, true of *its*; neither is true of the merge. Re-measured by running the two commands above against the merged tree with every conflict marker gone, never by summing the two deltas (RULING-M2, FINDING-M1). The WP-13 closeout that produced four hundred and fifty-seven itself recorded: Corrected on 2026-09-04 to **three hundred and eighteen and four hundred and fifty-seven** by merging `origin/main` `37f767b8` (PR #186) into `ri-ent/wp13-fixture`: `origin/main` recorded three hundred and eighteen and four hundred and fifty-four, true of *its* tree; that branch recorded three hundred and eighteen and four hundred and fifty-three at `62ff47f5`, true of *its*; neither was true of that merge. PR #186 adds four test modules under `tests/db/` — `test_provisioning.py`, `test_provisioning_guards.py`, `test_provisioning_unit.py`, `test_transactional.py` — and no source module. The figures
published here have now gone stale three times: sixty-eight and forty were true at the
2026-08-02 revalidation basis `main@8274d88`, ninety-three and sixty-nine were
true at WP-4B3 `main@6660dbb`, and each was carried through the packages that
followed. Three hundred and four and four hundred and four were true at
`main@8d5e1d0` and were corrected to three hundred and five and four hundred
and seven on 2026-08-29, this campaign having added modules on both sides;
the test-module figure was corrected again on 2026-08-30 to four hundred and
ten, when RI-ENT-WP-02 added `tests/unit/test_entity_name_and_organization_profile_domain.py`,
`tests/schema/test_entity_names_and_organization_profile_migration.py`, and
`tests/database/test_entity_names_tbr_gs4_studios_fixture.py` without adding a
source module, corrected again on 2026-08-30 to four hundred and
thirteen, when RI-ENT-WP-03 added
`tests/unit/test_entity_address_and_communication_method_domain.py`,
`tests/schema/test_entity_addresses_and_communication_methods_migration.py`,
and `tests/database/test_entity_addresses_and_communication_tbr_fixture.py`,
likewise without adding a source module, and corrected again on 2026-08-30 to
four hundred and seventeen, when RI-ENT-WP-04 added
`tests/unit/test_project_entity_participation_domain.py`,
`tests/schema/test_entity_project_participations_migration.py`,
`tests/database/test_project_entity_participation_isolation.py`, and
`tests/database/test_project_participation_synthetic_multi_project_fixture.py`,
likewise without adding a source module, and corrected again on 2026-08-30 to
four hundred and twenty, when RI-ENT-WP-05 added
`tests/unit/test_person_organization_affiliation_domain.py`,
`tests/schema/test_person_organization_affiliations_migration.py`, and
`tests/database/test_person_organization_affiliations_tbr_fixture.py`,
likewise without adding a source module, and corrected again on 2026-08-31 to
four hundred and twenty-six, when the WP-08 blocker-clearing pass widening
`EntityRelationshipType` to all thirty-five `entity_relationship_types`
codes added `tests/database/test_entity_relationship_type_widened_read_path.py`,
likewise without adding a source module, and corrected again on 2026-09-01 to
three hundred and six and four hundred and thirty-two, when RI-ENT-WP-08 added
one source module and three test modules: `1b2dd18` added
`src/my_pa/application/entity_record_families.py`, and `ed6e057` added
`tests/database/test_entity_record_family_write_path.py`, `31cc7bf` added
`tests/unit/test_entity_record_family_service.py`, and `499a7c1` added
`tests/database/test_entity_record_family_service_write_path.py` — the first
time the source-module figure has moved since the 2026-08-29 correction, every
step between it and this one having been test-side only. `95b16cf` and
`34367b4` changed the contents of those files without adding a module on either
side, so neither moves either figure. Corrected again on 2026-09-02, on the
test side only, from four hundred and thirty-two to four hundred and
thirty-four: RI-ENT-WP-13 added two test modules and no source module —
`tests/database/test_tbr_completeness_fixture.py`, the synthetic TBR
completeness fixture, and
`tests/unit/test_entity_record_family_security_matrix.py`, the structural half
of the audit's security matrix. That accounts for the movement in full, with no
residual, and the source-module figure is unmoved because RI-ENT-WP-13 adds
nothing under `src/my_pa`. Both figures were recomputed by running
the two commands above against this tree rather than by adding an assumed delta
to the stated pair, and corrected again on 2026-09-01 to three hundred and six
and four hundred and thirty-eight, when RI-ENT-WP-09 added six test modules and
no source module: `bb3bf22` added
`tests/unit/test_entity_resolution_vocabulary.py`, `8f6c576` added
`tests/database/test_entity_resolution_value_reads.py`, `1062251` added
`tests/unit/test_entity_search_reaches_context.py` and
`tests/database/test_entity_search_reaches_context.py`, and `5700c37` added
`tests/contract/test_entity_search_disambiguators.py` and
`tests/unit/test_entity_search_disambiguators.py`, and corrected again on
2026-09-01 to three hundred and six and four hundred and thirty-nine, when
RI-ENT-WP-10 added one test module and no source module:
`tests/contract/test_entity_record_family_reads.py`, and corrected again on
2026-09-01 to three hundred and seven and four hundred and forty, when
RI-ENT-WP-11 added one source module and one test module:
`src/my_pa/application/entity_family_writes.py`, the record families' ledger
bridge, and `tests/database/test_entity_family_write_ledger.py`, which was
committed unexecuted and has since passed in the green database tier, and
corrected again on 2026-09-02 to three hundred and seven and four hundred and
forty-one, when `bcd2048` added
`tests/database/test_ri_ent_wp_10_11_vocabulary_migration.py` -- the
database-tier binding for the phase's migration `16f05c46b8c3`, also committed
unexecuted and since executed and green in the same tier -- and no source module. Both figures were recomputed by running the two
commands above against this tree rather than by adding an assumed delta. That work package's five
`entities.` record-family reads were added to `application/service.py`,
`application/commands.py`, `adapters/normalization.py`, `contracts/ports.py`,
`domain/identity/operation.py`, `domain/policy/decision.py`,
`domain/relationship/entity.py`, `application/authorization.py` and
`infrastructure/persistence/entity.py` in place, so the source-module figure
does not move. The source-module figure is
unmoved because RI-ENT-WP-09 added no module under `src/my_pa` — it changed
`domain/relationship/resolution.py`, `contracts/ports.py`,
`application/entity_resolution.py`, `application/service.py` and
`infrastructure/persistence/entity.py` in place. `dcae6bd`, `c0e36d7` and
`2534a22` changed `tests/conftest.py` and the evaluation fixtures without
adding a module on either side, so none of the three moves either figure. Both
figures were recomputed by running the two commands above against this tree
rather than by adding an assumed delta. **UI-IMP-WP02 corrected this same
paragraph, from this same baseline, to three hundred and eleven and four
hundred and thirty-five**, when it added five source modules and three test
modules: `src/my_pa/domain/identity/secret_digests.py`,
`src/my_pa/domain/identity/webauthn_credentials.py`,
`src/my_pa/domain/identity/recovery_codes.py`,
`src/my_pa/domain/identity/auth_sessions.py`,
`src/my_pa/infrastructure/persistence/webauthn_auth.py`,
`tests/database/test_webauthn_auth_persistence.py`,
`tests/schema/test_webauthn_auth_persistence_migration.py`, and
`tests/unit/test_webauthn_auth_persistence.py`. 
Corrected again on 2026-09-04 to **three hundred and eighteen and four hundred and fifty-seven** by merging `origin/main` `37f767b8` (PR #186) onto the tree that had already integrated `25301329`; that tree's pair was three hundred and eighteen and four hundred and fifty-three, true of `62ff47f5`, and `origin/main`'s pair at `37f767b8` was three hundred and eighteen and four hundred and fifty-four, true of *its* tree. Corrected on 2026-09-03 to **three hundred and eighteen and four hundred and fifty-three** by the base integration of `origin/main` into `ri-ent/wp13-fixture`, in two steps: `8f0e4779` (PR #177, RI-ENT-WP-10/11, at `e004942b`, and PR #182, UI-IMP-WP07 through WP10, on top of it) and then `1bb7c3cf` (PR #183, UI-IMP-WP11, which modified `tests/contract/test_bff_success_decoder_parity.py` and `tests/unit/test_intelligence_artifact_pipeline.py` in place and added no module under either `find` -- the pair was re-measured after that step and did not move). `origin/main` recorded three hundred and eighteen and four hundred and fifty, true of *its* tree; this branch recorded three hundred and seventeen and four hundred and forty-nine, true of *its*; neither is true of the merge, which is the seventh consecutive integration in this campaign where that held. Re-measured by running the two commands above against the merged tree with every conflict marker gone, and again after this paragraph had itself been rewritten -- never by summing the two deltas (RULING-M2). The movement is nameable from the shared base `1055e5bc` (317/446): this branch adds no source module and three test modules (`tests/architecture/test_a_project_name_is_never_a_global_identity.py`, `tests/database/test_tbr_completeness_fixture.py`, `tests/unit/test_entity_record_family_security_matrix.py`); `origin/main` adds one source module (`src/my_pa/application/entity_family_writes.py`) and four test modules (`tests/architecture/test_entity_plane_prose_matches_the_capability_sets.py`, `tests/contract/test_entity_record_family_reads.py`, `tests/database/test_entity_family_write_ledger.py`, `tests/database/test_ri_ent_wp_10_11_vocabulary_migration.py`). No file was added on both sides this time, so the two sets happen to be disjoint -- measured, not relied on. PR #182's `tests/end_to_end/seed_review.py` is not a `test_*.py` and moves neither figure. **The dated entries `origin/main` carried at `1055e5bc` for the 317/445 (UI-IMP-WP04) and 317/446 (UI-IMP-WP06) steps, which this branch's earlier resolution at `e94dd4b3` had collapsed into a single summary clause, are restored here verbatim and in the order that file held them; each "this tree" inside them is the tree that wrote it:** Corrected again on 2026-09-03 to **three hundred and seventeen and four hundred and forty-six**, when UI-IMP-WP06 added `tests/contract/test_bff_success_decoder_parity.py` without adding a source module. The pair `find` reports on this tree is 317/446. Corrected again on 2026-09-02 to **three hundred and seventeen and four hundred and forty-five**, when this tree's `find src/my_pa -name "*.py"` and `find tests -name "test_*.py"` were run after UI-IMP-WP04 added two source modules (`src/my_pa/application/session_service_auth.py`, `src/my_pa/adapters/http/auth_sessions.py`) and two test modules (`tests/unit/test_session_service_auth.py`, `tests/unit/test_session_service_isolation.py`). The pair `find` reports on this tree is 317/445. Prior correction the same day to three hundred and fifteen and four hundred and forty-three recorded the tree after merging `ri-ent/wp09-resolution` with `origin/main` and landing UI-IMP-WP03. The merge of WP-09's six test modules onto WP-02's five source and three test modules produced 311/441; WP-03 then added four source modules (`src/my_pa/application/webauthn_bff_attestation.py`, `src/my_pa/domain/identity/webauthn_relying_party.py`, `src/my_pa/infrastructure/security/webauthn_ceremony.py`, `src/my_pa/adapters/http/webauthn.py`) and two test modules (`tests/unit/test_webauthn_ceremony.py`, `tests/database/test_webauthn_ceremony.py`). Isolation (`7452cc6`) moved ceremony execute into the existing `bootstrap.gateway` composition root and added neither a source module nor a test module. 311+4=315 and 441+2=443, which was the pair `find` reported on that tree. Prior correction the same day to three hundred and eleven and four hundred and forty-one recorded the merge of `ri-ent/wp09-resolution` (306/438) with `origin/main` (311/435) before ceremony landed; that pair was a scaffold for the merge, not this tree. **Re-measured by running the two commands above -- never by summing the two deltas**, which is the trap an independent reviewer named when it found this exact conflict before the merge was attempted. `95b16cf` and `34367b4` changed the contents of the WP-08 files without adding a module on either side, so neither moves either figure. **This branch's own history of this paragraph, as it stood at `e94dd4b3`, preserved:** Corrected again on 2026-09-02 to **three hundred and eleven and four hundred and forty-one**, when `ri-ent/wp09-resolution` and `origin/main` were merged and NEITHER side's pair was true of the result: this branch had corrected the pair to 306/438 for RI-ENT-WP-09's six test modules, `origin/main` had corrected the same pair to 311/435 for UI-IMP-WP02's five source and three test modules, and both corrections were made from the same baseline. The merged tree carries both sets of modules, so the true pair is neither. **Re-measured on the merged tree by running the two commands above -- never by summing the two deltas**, which is the trap an independent reviewer named when it found this exact conflict before the merge was attempted. `95b16cf` and `34367b4` changed the contents of the WP-08 files without adding a module on either side, so neither moves either figure. **Moved on 2026-09-03 by integrating `origin/main` at `1055e5bc`** (UI-IMP-WP03 through WP-06, five bases' worth of frontend and auth work). `origin/main` recorded the pair as three hundred and seventeen and four hundred and forty-six, true of *its* tree; this branch recorded three hundred and eleven and four hundred and forty-four, true of *its*. Re-measured on the merged tree with every conflict marker gone: **three hundred and seventeen and four hundred and forty-nine** — RI-ENT-WP-13 adds no source module and three test modules that `origin/main` does not carry. Neither side's pair was true of the result, which is now the sixth consecutive integration in this campaign where that held. **`origin/main` also still carries the FINDING-M3 prose corruption at this paragraph** — the sentence that opens "The source-module" and runs straight into the fused pair "f" + "five and four hundred and twenty-nine", eleven words dropped by a programmatic splice in the controlling context's own conflict resolution at `9943aa11`. This branch's repaired text is what survives the merge, and this integration is how the repair reaches `main`. **`origin/main`'s history of this same paragraph, as it stood at `e004942b`, preserved -- it continues from the UI-IMP-WP02 module list above:** `tests/unit/test_webauthn_auth_persistence.py`; that correction also records
that `95b16cf` and `34367b4` changed the contents of the WP-08 files without
adding a module on either side, so neither moves either figure. **Neither
branch's pair is true of the merged tree, and the two corrections do not
compose (RULING-M2).** Adding the deltas would give three hundred and thirteen
and four hundred and forty-seven, and that is wrong:
`src/my_pa/application/entity_record_families.py`,
`tests/database/test_entity_record_family_write_path.py`,
`tests/database/test_entity_record_family_service_write_path.py` and
`tests/unit/test_entity_record_family_service.py` were added independently on
both branches and the merged tree counts each once. Corrected on 2026-09-02 by
the base merge to three hundred and twelve and four hundred and forty-four, by
running the two commands above against the merged tree once the conflict
markers were gone -- a figure read while they were still present counts both
branches' prose and is void -- and again after this paragraph had itself been
rewritten, to prove the pair stable across its own edit. **Unmoved on 2026-09-02
by the RI-ENT-WP-09 integration** (`origin/main` at `6db2a203`, PR #175), which
this branch merged after that base merge: the pair stays three hundred and
twelve and four hundred and forty-four, re-measured by running the two commands
above against the merged tree with every conflict marker gone, not carried
forward on the assumption that a merge which adds no file cannot move it.
`origin/main` corrected this same paragraph to three hundred and eleven and
four hundred and forty-one, true of *its* tree, and that figure is not true
here: `ri-ent/wp09-resolution` and this branch carry RI-ENT-WP-09's six test
modules as the same commits, so the two trees share them and the merge adds no
module on either side. It brings content changes to two files only --
`tests/database/test_entity_resolution_value_reads.py` (the `NameTypeCode`
member that never existed) and `tests/database/test_entity_search_reaches_context.py`
(two further tests for the widened search's active-state filter) -- both of
which already existed here. **Moved on 2026-09-02 by the UI-IMP-WP03
integration** (`origin/main` at `20638373`), which added four source modules --
`src/my_pa/adapters/http/webauthn.py`,
`src/my_pa/application/webauthn_bff_attestation.py`,
`src/my_pa/domain/identity/webauthn_relying_party.py` and
`src/my_pa/infrastructure/security/webauthn_ceremony.py` -- and two test
modules, `tests/unit/test_webauthn_ceremony.py` and
`tests/database/test_webauthn_ceremony.py`. Its isolation commit moved ceremony
execution into the existing `bootstrap.gateway` composition root and added a
module on neither side. `origin/main` recorded the resulting pair as three
hundred and fifteen and four hundred and forty-three, true of *its* tree and
not of this one, which also carries RI-ENT-WP-10/11's source and test modules.
The pair stated at the head of this section was re-measured by running the two
commands above against the merged tree once every conflict marker was gone --
never by adding this integration's four and two to the previous pair, which is
the arithmetic RULING-M2 forbids and which would have been wrong here for the
third consecutive integration. **Moved again on 2026-09-03 by the UI-IMP-WP04
integration** (`origin/main` at `cac110ad`), which added two source modules --
`src/my_pa/adapters/http/auth_sessions.py` and
`src/my_pa/application/session_service_auth.py` -- and two test modules,
`tests/unit/test_session_service_auth.py` and
`tests/unit/test_session_service_isolation.py`. That base also deletes ten
`web/` files as it retires the legacy browser auth path, and adds several more,
none of which either `find` above reaches: both are scoped to `src/my_pa` and
`tests`, so a large `web/` churn moves neither figure. `origin/main` recorded
the resulting pair as three hundred and seventeen and four hundred and
forty-five, true of *its* tree and not of this one, which also carries
RI-ENT-WP-10/11's modules and the entity-plane prose guard. Re-measured on the
merged tree with every conflict marker gone -- **for the fourth consecutive
integration neither side's pair was true of the result**, which is now less a
caution than a description of what merging two active branches does to a
derived count. **Moved again on 2026-09-03 by the UI-IMP-WP05/WP-06 integration** (`origin/main` at `1055e5bc`), which added one test module — `tests/contract/test_bff_success_decoder_parity.py` — and no source module. `origin/main` recorded the resulting pair as three hundred and seventeen and four hundred and forty-six, true of *its* tree and not of this one, which also carries RI-ENT-WP-10/11's source and test modules and the entity-plane prose guard. Re-measured on the merged tree with every conflict marker gone: **three hundred and eighteen and four hundred and fifty**. **For the fifth consecutive integration neither side's pair was true of the result** — ours read 318/449 and `origin/main`'s 317/446, and the truth is neither. Note the shape this time: the source figure happens to equal ours because this base adds no source module, and the test figure happens to equal ours plus one. Both coincidences were measured rather than relied on; an identity that holds by luck on one integration is not a method. **Moved again on 2026-09-03 by the RI-ENT-WP-12 integration** (`origin/main` at `e004942b`, then `8f0e4779` and `25301329`, merged into `ri-ent/wp12-backfill`; the later two add `tests/end_to_end/seed_*.py` helpers and no `test_*.py` module, so the pair below was re-measured unchanged after each), which carries two test modules -- `tests/contract/test_entity_read_shape_compatibility.py` and `tests/database/test_legacy_entity_backfill_migration.py` -- and no source module. `origin/main` recorded the pair as three hundred and eighteen and four hundred and fifty, true of *its* tree and not of this one; this branch had recorded three hundred and six and four hundred and thirty-four against its own pre-merge base, true of neither. Re-measured on the merged tree with every conflict marker gone: **three hundred and eighteen and four hundred and fifty-two**, the sixth consecutive integration on which neither side's pair was true of the result. The pair standing before this correction, three hundred and
five and four hundred and twenty-nine, was true at `f4eaa4f`; the chain above
therefore skips from four hundred and twenty-six to four hundred and
twenty-nine, because `f4eaa4f` moved the sentence without extending this note,
and the skipped step is recorded here rather than reconstructed. (The audit basis `main@e773e6f` was fifty-six and twenty-seven; the
pair recorded against it here was the revalidation's, one basis out.)
Corrected again on 2026-09-02 at RI-ENT-WP-13 closeout to **three hundred and
eleven and four hundred and forty-four**: the source figure is unmoved, and the
test figure moves by exactly one, `tests/architecture/test_a_project_name_is_never_a_global_identity.py`,
the guard that makes the `project_display_name` boundary mechanical. Re-measured
by running the two commands above against the tree that carries it, not by
adding one to the stated pair. The `441` recorded in the entry above is **not**
superseded and must not be "corrected": it is the pair as it stood at the
`ri-ent/wp09-resolution`/`origin/main` merge, and it was right for that tree.

**Prose repair, 2026-09-02, RI-ENT-WP-13 closeout (`FINDING-M3`).** The
sentence beginning "The pair standing before this correction" read, between
`9943aa11` and this correction, as "The source-module" run directly into the
fused pair "f" + "five and four hundred and twenty-nine" — eleven words gone
and two sentences fused into one token.

**Git did not do this, and this record must not say it did.** `9943aa11` is the
controlling context's own merge commit resolving the RI-ENT-WP-09 count
conflict, and it resolved that conflict **programmatically, by splitting and
concatenating the file as a Python string** rather than by editing it. The
split anchor, `"The source-module f"`, was not unique in the document, so the
trailing fragment ran straight into the surviving tail. No conflict marker
survived because none was ever written: the corruption was introduced by the
resolution, not by the merge. Attributing it to git would teach a future reader
that merges silently mangle prose; the real lesson is narrower and far more
actionable — **never resolve a text conflict by string concatenation, and read
the affected paragraph after any programmatic edit to a document.**

The damage travelled onto `main` at `6db2a203`. The restored wording is
`717e1d15`'s, the last uncorrupted version, and its figures were re-derived
rather than trusted: `git ls-tree -r --name-only f4eaa4f` gives three hundred
and five modules under `src/my_pa` and four hundred and twenty-nine `test_*.py`
under `tests`. `ri-ent/wp10-11-mcp` reached the identical restoration
independently during its own base integration, so two contexts converged on the
same eleven words from the same evidence.

It is recorded at length because **every mechanical check passed over it**: the
figures around the sentence were all correct, `ruff` and `mypy` do not read
prose, and the count guards compare a figure to the tree rather than a sentence
to grammar. It reached `main` through an independent review that PASSED. A
count guard proves a figure; nothing in this repository proves a sentence, and
the only thing that could have found this is someone reading it. **"Nothing checks them" was the
diagnosis and it is now wrong**:
`../../tests/architecture/test_spelled_counts_match_the_sets_they_name.py` runs
both commands above, and the revision count and head below, and fails when an
exact current claim disagrees with the tree.

| Area | State |
|---|---|
| `contracts/v1` — envelope, disclosure, errors, capabilities, base | Implemented and tested |
| `domain/identity` — capability, purpose, principal, operation binding | Implemented and tested |
| `domain/common` — identifiers, provenance, classification, time | Implemented and tested |
| `domain/policy`, `domain/audit` | Implemented and tested |
| `bootstrap/settings` — strict `MY_PA_` configuration, fail-closed | Implemented and tested |
| `infrastructure/database/engine` | Implemented |
| `infrastructure/migration/*` — legacy ETL, control plane, redaction | Implemented and tested |
| `domain/source`, `domain/extraction`, `domain/search` — registry, bounded enrollment, provider port, extraction outcomes, quarantine, coverage, search query | Implemented and tested |
| `infrastructure/persistence` — registry, enrollment, jobs, extraction, quarantine, coverage, lexical search | Implemented; covered by the database tier |
| `infrastructure/providers/fixture.py` — read-only fixture source provider | Implemented and tested |
| Alembic revisions — schemas and extensions, target tables, control plane, indexes, foreign keys, views, `knowledge` schema, extraction tables, audit events, enrolled objects, continuity, native sources, managed documents, GoodNotes, operations, task management, context prepare/feedback, OAuth refresh-token families, GoodNotes notebook lineage, GoodNotes NOTE_UNIT occurrence persistence, GoodNotes semantic work/proposal receipts, GoodNotes entity associations with NEW-only delivery receipts, and additive GoodNotes exact visual render digests, additive `goodnotes.content` vocabulary, additive durable-note stage ledger and Principal-bound page rasters, additive GoodNotes server-grounded NOTE_UNIT crop identity with immutable revision provenance, additive GoodNotes Meeting/Agenda association kinds, and an additive dormant GoodNotes delivery-attempt ledger, and the relationship-intelligence entity plane — `entities`, `entity_external_identifiers`, `entity_assignments`, `entity_relationships`, the additive `entity_aliases` table, and the `entities.*` capability family with the `entity_read` purpose, and the entity observation, proposal, and merge-lineage tables, and the additive `entity_names`/`entity_organization_profiles` tables (RI-ENT-WP-02), and the additive `entity_addresses`/`entity_communication_methods` tables (RI-ENT-WP-03), and the additive `entity_project_participations`/`entity_role_types`/`entity_discipline_types` tables (RI-ENT-WP-04), and the additive `entity_person_organization_affiliations` table (RI-ENT-WP-05), and the additive `entity_relationship_types` table with `entity_relationships.relationship_type` re-pointed at it by foreign key (RI-ENT-WP-06a), and the Intelligence Artifact report plane — cycle runs, producer runs, immutable artifacts, commit receipts, pipeline dependencies, and external provenance, with the eight `reports.*` capabilities and the `report_authoring`/`report_read` purposes, and the Work Task/Commitment contract, history digests, and bounded bulk ledger with the three further `commitments.` capabilities, and the Relationship Memory plane — the memory pointer, its immutable version ledger, submissions, context and evidence links, proposals with their evidence, and the append-only review-decision ledger, with the nine `relationship_memory.` capabilities and the `relationship_memory_read`/`relationship_memory_authoring` purposes | Implemented, ninety-three revisions, head `d4e8b1c7a902`; `d4e8b1c7a902` is additive on `6a2f9d1c4b80` and adds the immutable GoodNotes semantic promotion receipt; `6a2f9d1c4b80` is additive on `c3f8a1d07e94` and adds the GoodNotes pull ledger; `c3f8a1d07e94` admits `entities.graph` on `b8e4d1a6c073`; `b8e4d1a6c073` is additive on `16f05c46b8c3` and backfills one `display`-typed `entity_names` row per active `entities` row (never a `legal` name), writing no `entity_project_participations`, `entity_addresses` or `entity_communication_methods` row and leaving `entity_aliases`, `entity_assignments` and `entity_external_identifiers` untouched (RI-ENT-WP-12; written against `c99cd8ed8d1c` and re-parented onto `16f05c46b8c3` once RI-ENT-WP-10/11 merged so the chain holds one head, `RULING-M11`; eighty-nine counted on the merged tree 2026-09-03 rather than derived from either side); `16f05c46b8c3` is additive on `2c00c9ac64bc` -- onto which it was re-parented at the base merge, both revisions having been written against `c99cd8ed8d1c` -- and widens three closed CHECK sets -- `audit_events.capability_is_known` from 115 to 135 values, `entity_mutation_events.a_mutated_record_family_is_known` from six to eleven, and `entity_proposals.an_accepted_proposal_record_family_is_known` from six to eleven for metadata parity with the shared `_one_of(..., MutationRecordFamily, ...)` declaration -- so the capability names RI-ENT-WP-10 and RI-ENT-WP-11 published, twenty in all, and their five new record families can be recorded at all; `purpose_is_known` is deliberately not widened, because neither work package adds a `Purpose`; `2c00c9ac64bc` is additive on `c99cd8ed8d1c` and adds WebAuthn credential, challenge, recovery-code, and opaque session tables (UI-IMP-WP02); `c99cd8ed8d1c` is additive on `1cda4d536268` and renames the seeded `entity_relationship_types` row `design_coordinates_with` to `design_coordination_with` (every other column unchanged), closing `EntityRelationshipType` to 35-of-35 parity with the taxonomy table (the WP-08 blocker-clearing rename); `1cda4d536268` is additive on `9a3f6c1e8d24` and adds the `entity_assertions`/`entity_assertion_evidence` tables, binding fact-level `assertion_status` and evidence to the six Entity-bound record families RI-ENT-WP-02 through RI-ENT-WP-06 added (RI-ENT-WP-07, closes `ENTITY-PROVENANCE-001`); `9a3f6c1e8d24` is additive on `8dc3619891bb` and widens the `entity_identity_effects`/`entity_identity_preview_ambiguities`/`entity_identity_ambiguity_settlements` `record_family` CHECKs to admit six new Entity-bound families (RI-ENT-WP-06b); `8dc3619891bb` is additive on `17149a48fa30` and adds the `entity_relationship_types` table, re-pointing `entity_relationships.relationship_type` at it by foreign key (RI-ENT-WP-06a); GSQS `c4b0a1d9e827` precedes Phase B `c7a1f04b9e63`; `b727e870d45e` is additive on `8e1c4a7b2d90` and carries the merge-preview ambiguity and settlement tables, the `partial` re-enrichment state with its `limitations` column, the `reenrichment` heartbeat plane, and the append-only trigger on `entity_proposal_review_decisions`; `7e114f822af2` is additive on `b727e870d45e` and adds the `entity_names`/`entity_organization_profiles` tables; `441b071bf37b` is additive on `7e114f822af2` and adds the `entity_addresses`/`entity_communication_methods` tables; `f5b06925857e` is additive on `441b071bf37b` and adds the `entity_project_participations`/`entity_role_types`/`entity_discipline_types` tables; `17149a48fa30` is additive on `f5b06925857e` and adds the `entity_person_organization_affiliations` table. Counted on the merged tree 2026-09-02, both branches having corrected eighty-six/`c99cd8ed8d1c` to an eighty-seven of their own (prior correction, from eighty-five/`1cda4d536268`, itself from eighty-four/`9a3f6c1e8d24`) |
| CI — `repository-checks.yml` including the database tier | Implemented |

All one hundred and thirty capability names, their operator-only flags, and their permitted
purposes exist in `domain/identity/operation.py`, alongside 38 purposes. The v1 request,
response, disclosure, and error shapes already exist and are contract-tested.

## 4. What is not implemented

Nothing below `contracts` and `domain` executes a product workflow. Specifically
absent, with no code beyond a README:

*The list that follows is state at the audit basis and is deliberately not
updated, in the same way and for the same reason as the sentence in section 12
below. Five of its entries have since been built: WP-4A wired the application
services, WP-4B1 made the worker a process, WP-4B2a made the gateway one and
built the HTTP transport, and WP-4B2b built the MCP adapter and the operator
CLI beyond `apps/cli/migration.py` — so `apps/worker/` and `apps/gateway/` are
both gone, `apps/worker.py` and `apps/gateway.py` are real composition roots,
and all three transports exist with `SPEC-AC-001` parity proven across them. It
is left standing because what this section is for is recording what the audit
found, and rewriting it clause by clause would leave a record of nothing.*

- application services binding the eight capabilities to the persistence and provider behavior that now exists;
- HTTP transport (`apps/gateway` is a README);
- MCP adapter;
- worker process (`apps/worker` is a README);
- operator CLI beyond `apps/cli/migration.py`;
- managed documents, structured knowledge records, relationship services,
  GoodNotes ingestion, Obsidian projection, and any frontend. There is no
  JavaScript toolchain in the repository at all — no `package.json` exists.

At the audit basis `e773e6f`, `README.md` said "This branch contains a
documentation-only repository scaffold... does not implement runtime behavior."
That was false, and WP-1 corrects it in the same change that publishes this
document.

## 5. Specification conflict, and how it resolves

The dispatched plan requires ten workstreams, A through J, including a full
frontend MVP (H), a PaddleOCR/TrOCR handwriting pipeline (G), relationship
intelligence (F), managed documents (E), and an Obsidian projection (I).

Repository policy says the opposite, in terms that are not ambiguous.

`AGENTS.md` is the load-bearing authority here, because it is unambiguously
accepted policy — `AGENTS.md` §1 places "accepted repository specifications,
ADRs, and this policy" above "indexed Workspace publications" in its own
precedence list, and `AGENTS.md` is itself that policy. §1: "The objective is one
complete, read-only vertical slice—not a broad platform." §3 defers
implementation "merely because a scaffold path exists" and directs "one
end-to-end vertical slice over multiple partial systems."

`docs/specs/mcv-read-only-vertical-slice.md` agrees and is more specific, but it
carries `status: PROPOSED_FOR_REPOSITORY_REVIEW` and describes itself as a
candidate. It is therefore corroborating detail, not the authority the deferral
rests on. Accepting it is an operator act that has not happened. §2:

> The MCV therefore proves one complete, bounded, read-only vertical slice. It
> does not attempt to build a broad personal-assistant platform.

The same specification, §5.2, lists as **explicitly excluded**: personal email,
calendar, contact, and relationship connectors; managed-document writes and
version/recovery workflows; and "vector search, graph infrastructure,
relationship intelligence, and projection implementation."

The dispatched plan does not override this, and does not claim to. Its §5.1 says
"Repository governance and runtime truth control implementation over older Drive
planning assumptions." Its §5.6 says "`AGENTS.md` is the principal repository
policy. Preserve its minimum-correct-implementation... rules." Its §7 preamble
qualifies the whole workstream list with "unless repository truth proves that a
requirement is superseded or already complete," and its §6 requires every
requirement to be classified, including as "superseded" or "deliberately
deferred."

So the conflict resolves inside the plan's own rules rather than against them.
Workstreams E, F, and I are classified **deferred — outside the vertical slice
`AGENTS.md` defines, and named as excluded by the proposed specification**. They
are not silently dropped; they are named here, and they remain available scope.
Promoting them takes an explicit operator reprioritisation of the objective
under `AGENTS.md` §3; amending the proposed specification alone would not do it,
because `AGENTS.md` is what currently carries the deferral.

Workstreams G and H are not excluded by the specification — they are absent from
it, arriving from Drive feature packages. They are classified **deferred —
dependency-blocked**: both consume backend contracts that do not yet exist. The
plan itself forbids building H ahead of them ("Do not invent backend behavior to
make a screen look complete," §7-H), and G's live source root is gated by
`P00-OD-009`, which is an operator-only open decision.

## 6. Requirements traceability

*The classifications below are state at the audit basis and are deliberately not
updated, in the same way and for the same reason as the lists in sections 4 and
12. Several are now false — A was built by WP-1, B and C by WP-2 and WP-3, and
**D by WP-4A, WP-4B1, WP-4B2a and WP-4B2b**, so "transport does not [exist]" is
no longer true of any of the three: HTTP, MCP and the operator CLI all exist and
`SPEC-AC-001` parity is proven over them. The **Disposition** column stays
correct, which is what this table is for; the split of WP-4 into WP-4A and WP-4B
is recorded by `D-28` in the register, and the split of WP-4B again by `D-36` —
which had no row until WP-0R2 added one; see the note under the register in
section 13. This table
had carried no marker until WP-4B2b added one, which is why row A has read
"Missing and required" since the day WP-1 merged.*

| Workstream | Classification | Disposition |
|---|---|---|
| A — repository and product truth | Missing and required | WP-1 |
| B — registry, jobs, canonical services | Partially implemented (contracts and audit exist; persistence and services do not) | WP-2, WP-3 |
| C — read-only source provider, indexing, search | Missing and required | WP-2, WP-3 |
| D — gateway, MCP parity, operator CLI | Partially implemented (contracts exist; transport does not) | WP-4 |
| E — managed documents, recovery | Deferred — outside the `AGENTS.md` slice; named as excluded by spec §5.2 | Deferred, disclosed |
| F — personal-data domains, relationship intelligence | Deferred — outside the `AGENTS.md` slice; named as excluded by spec §5.2 | Deferred, disclosed |
| G — GoodNotes handwriting MVP | Deferred — dependency-blocked and `P00-OD-009` operator-gated | Deferred, disclosed |
| H — interactive frontend MVP | Deferred — dependency-blocked on B/C/D | Deferred, disclosed |
| I — Obsidian projection | Deferred — outside the `AGENTS.md` slice; named as excluded by spec §5.2 ("projection implementation") | Deferred, disclosed |
| J — operations, packaging, local activation | Missing and required | WP-5 |

The migrated PostgreSQL corpus is retained and verified but is **not** exposed
through product services in this scope, because doing so is Workstream F.

## 7. Work packages and merge order

Each is one branch, one pull request, squash-merged, implemented by a delegated
agent with disjoint file ownership and reviewed at exact head by a separate
agent that did not author it.

1. **WP-1 — repository and product truth.** This document; corrected `README.md`;
   source-index routing; Phase 00 ledger dispositions the migration superseded;
   spec status reconciliation. Documentation only, no behavior change.
2. **WP-2 — registry, enrollment, jobs, fixture provider.** New `knowledge`
   schema by Alembic, empty-to-head. Source registry, bounded enrollment with
   idempotency keys, job lease/retry, opaque ID issuance. Read-only fixture
   provider proving root containment and traversal denial.
3. **WP-3 — extraction, quarantine, coverage, search.** Text and Markdown
   extraction; PDF reported `unsupported` because `P00-OD-003` is open;
   quarantine triggers; coverage states; version-fingerprint binding;
   PostgreSQL FTS with `pg_trgm`.
4. **WP-0R — canonical re-mirror and reconciliation.** Refreshes the mirrored
   canonical product definition against the 2026-08-02 Remote Quick Capture
   revision and reconciles this plan against it. Documentation only, no behavior
   change. Out of numeric order because it was raised after WP-4 was planned and
   depends on nothing.
5. **WP-4A — application services.** Use cases for the eight capabilities, ports,
   the shared policy and disclosure path, and the derived capability manifest,
   behind the existing v1 contracts.
6. **WP-4B — transports.** HTTP gateway on loopback, MCP adapter with proven
   transport parity, operator CLI, both composition roots, the worker lease loop,
   and the parity and negative-evidence matrices.
7. **WP-5 — operations and local candidate.** Startup, shutdown, health,
   readiness, recovery and idempotency tests, empty-to-head validation, the
   end-to-end synthetic slice, operator runbook, honest limitations.
8. **WP-6 — capture domain and durable-first persistence.** Capture contracts,
   `capture.create`, submission, receipt, and outbox, committed in one
   transaction — **the redacted audit event excepted**, which commits first and
   separately on the audit connection per `D-34`. *Corrected 2026-08-03
   (`D-75`): this item said "all committed in one transaction" and named a
   registered client. The audit was never in that transaction and cannot be
   without overturning `D-34`; `RegisteredCaptureClient` is deferred by `D-74`
   because `D-30`, `O-21` and `P00-OD-010` leave it unpopulatable. Section 559's
   objective carries the corrected sentence in full.*
9. **WP-7 — capture processing.** Proposals, evidence spans, deterministic
   classification and domain assignment, exact search.
10. **WP-8 — review and promotion.** Review cases, promotion, conversation
    events, corrections.
11. **WP-9 — relationship identity and read-only profiles.**
12. **WP-10 — PWA capture surface and offline recovery.** **Deferred until after
    MCV completion by direct operator instruction on 2026-08-04 (`D-104`).** It
    remained the only frontend package here until the narrow WP-FE-03 exception
    in `D-108`; active gates `D-09`, `O-04`, and `O-20` otherwise remain unresolved.
13. **WP-11 — Native Apple Reminders execution projection.** Internal sequence
    `NAR-00` canonical policy amendment, `NAR-01` target-Mac EventKit
    feasibility proof, `NAR-02` provider-neutral domain and contracts, `NAR-03`
    backend application services, `NAR-04` signed native bridge, `NAR-05`
    one-way creation and updates, `NAR-06` completion roundtrip, `NAR-07`
    conflicts and recovery, `NAR-08` security and operational proof.
    `D-39` records the historical sequencing provenance; WP-11 remains dependent
    on WP-10, and nothing in it is built. `D-104` keeps WP-10 deferred until MCV
    completion, so WP-11 remains dependency-blocked and its own pre-completion or
    post-completion placement is unresolved. `D-104` does not answer its active
    gates `NAR-OP-001` through `NAR-OP-009` or authorize any part of it.
14. **WP-12 — Apple Mail, Calendar & Contacts.** **Promoted ahead of deferred
    WP-10 and WP-11 for bounded pre-completion implementation by direct operator
    authorization `AUTH-WP12-20260804-OPERATOR-001` (`D-106`).** Its internal
    dependency order is A, B, D, C, E, F, G, H. Slice A freezes repository truth,
    the exact acceptance map, and source-built protocol-v1 feasibility contracts;
    live Apple access, TCC, signing, activation, deployment, source mutation, and
    risk acceptance remain prohibited.

Items 4 through 14 restate section 12's sequence table, which is the authoritative
one; `D-28` split WP-4, the Remote Quick Capture revision added WP-0R and
WP-10, the Native Apple Reminders revision added WP-11, `D-105` records the
historical provisional WP-12 state, and `D-106` records its later promotion.
Section 7 originally stopped at WP-5, and listing only half
the merge order was how a reader ended up consulting two tables that disagreed.

## 8. Boundaries held throughout

- No source mutation. The fixture root and any later NAS root are opened
  read-only, and containment is revalidated immediately before read.
- No live personal data in tests, fixtures, logs, or evidence. Fixtures are
  synthetic.
- No connection to an unverified physical database. Today the only guard is
  configuration-level: settings reject an unknown `MY_PA_` name, an unparseable
  value, or a URL that is not `postgresql+psycopg` naming a host and a database.
  There is no runtime `current_database()` check. An absent `MY_PA_DATABASE_URL`
  no longer defaults: `P00-OD-008` was resolved by the operator and the setting
  is required, so an unconfigured process refuses to start rather than choosing a
  target. The legacy SQLite source is never written.
- Services bind to loopback. No internet exposure, no multi-user claim.
- PDF stays `unsupported` rather than silently skipped, until `P00-OD-003` is
  resolved by the operator.
- Live NAS and GoodNotes roots stay unused; `P00-OD-009` requires separate
  operator authorization naming an exact root.

## 9. Decision register

Corrections to entries here are made in place, in public, with the original
claim left visible.

| ID | Decision | Basis | State |
|---|---|---|---|
| D-01 | Plan accepted on identity, not on byte-exact hash | The dispatch declared both `representation: native_google_doc` and a source SHA-256 of the pre-conversion Markdown. A native Google Doc does not preserve source bytes, so the two are not jointly satisfiable. File ID, title, parent, owner, and native type all verified; every export format was hashed and none matched, as expected. | Departure, disclosed |
| D-02 | tmux channel replaced by subagent delegation | `tmux` is not installed on this machine and no `claude-code` session exists. The dispatched plan assumed a separate orchestrator driving this session through tmux; this session is itself the implementation agent. Plan §3 and §9.2 independently require fresh subagents for implementation and exact-head review, which is the substituted mechanism. | Departure, disclosed |
| D-03 | Workstreams E, F, I deferred | Outside the single read-only vertical slice `AGENTS.md` §1 and §3 define, and named as excluded by `docs/specs/mcv-read-only-vertical-slice.md` §5.2. The specification is `PROPOSED_FOR_REPOSITORY_REVIEW`, so `AGENTS.md` carries the argument and the specification corroborates it. | Deferred |
| D-04 | Workstreams G, H deferred | Dependency-blocked on B/C/D, which do not exist. The specification is silent on both, so nothing excludes them; they are sequenced, not ruled out. Plan §7-H forbids fabricating backend behavior; `P00-OD-009` gates G's source root to the operator. | Deferred |
| D-09 | Workstream H additionally held by operator instruction | The operator directed on 2026-08-01 that no frontend implementation was in scope until they said otherwise. `D-108` partially supersedes this hold only for WP-FE-03 — Work: Tasks and Commitments. Every other frontend package and surface remains held unless separately reprioritized, so satisfying a dependency still does not read as authorization to start it. | Partially superseded by D-108; otherwise operator-directed |
| D-05 | Corpus claim accepted | Recomputed from the live database, not restated. Exact match. | Verified |
| D-06 | PDF remains `unsupported` | `P00-OD-003` is `OPEN_OPERATOR`. Reporting `unsupported` is the specified behavior; silently skipping is forbidden. | Accepted |
| D-07 | Corrected in place: this document first said "five revisions" | The count came from a truncated directory listing. Recounted from `migrations/versions/*.py`: six, chained `5d75f23847c9 → 1e6c0a94f3b7 → 4b9f0d27ac31 → 2f7d1ba05c48 → 3a8e2cb16d59 → 6c4d3ea82f10`, the last creating target views, and the head matching `alembic_version` in the live database. The mechanism, not just the number, is fixed: the count is now stated with the head revision beside it, so a future drift between the files and the database is visible rather than latent. | Corrected |
| D-08 | Terminal disposition cannot be reached in this scope | Plan §11 requires GoodNotes, frontend, and relationship acceptance criteria that D-03 and D-04 defer. The eventual terminal disposition must name the deferred set and must not assert `MYPA_CURRENT_PRODUCT_SCOPE_COMPLETE`. **Updated 2026-08-04:** the operator explicitly confirmed the MCV is not complete. `D-104` defers WP-10 until completion. `D-105`'s provisional WP-12 sequence is historical and superseded by `D-106`, which promotes WP-12 ahead of WP-10/WP-11 without declaring MCV complete. `D-107` defines the future full-MVP handoff only after independent completion verification. | MCV not complete; WP-12 active; terminal declaration still reserved |

## 10. Carried forward

### Closed by WP-3

Both items this section carried out of WP-2's review were closed in WP-3 and are
left here rather than deleted, so the ledger reads as a sequence rather than as a
list of open things. Descriptor exhaustion and six other errno conditions now
report `unavailable` rather than `denied`, by allowlist so an unrecognised errno
stays denied. The refused hard link that vanished from listings now surfaces
through the aggregate coverage limitation WP-3 built.

### Carried into WP-4

WP-3 took seven independent reviews and five correction commits. What follows is
what those reviews found and the change deliberately did not fix, disclosed in
the code that carries it and repeated here so it is scheduled rather than
rediscovered.

- **A live snapshot race in search.** The page read and the coverage read take
  separate `READ COMMITTED` snapshots, so a quarantine committed between them
  yields a page of extracted text beside `no_extracted_text_in_scope` — the
  section 9.7 collapse the module exists to prevent. The claims about it are
  qualified rather than absolute. Reading coverage before the page is one line
  and moves the failure to the understating direction; it was not taken, and the
  operator accepted shipping it deferred.
- **Root containment and the unmeasured denominator are one missing fact.** A
  root-selector enrollment authorizes its whole source rather than the subtree
  under its root, because nothing persists which objects lie under a root — the
  same absence that leaves its coverage denominator unmeasured. Persisting the
  enumerated set once at enrollment closes both. Fix them together.
- **`record_outcome`'s persisted provenance payload has no round-trip
  assertion** — extractor identity, extractor version, the truncation flag, and
  `observed_at` against `processed_at` can each be corrupted with both test tiers
  green. WP-4 is what builds on those columns, so this belongs first in that
  package rather than in the middle of its list. *Corrected 2026-08-08: **closed,
  and the four fields were not in the same state**, which is why the bullet
  reading them as one item understated part of it and overstated the rest.
  Measured field by field before anything was written. `observed_at` was already
  pinned end to end, against the fixture file's modification time — an
  independent fact, not another read of the row — so nothing was added to it.
  `extractor` had assertions, and they were **self-referential**: both sides were
  fed from the same read, so renaming the extractor left them green. That was
  measured rather than argued — with the constant renamed, the pre-existing
  assertions passed and only the new one failed. `extractor_version` and
  `is_truncated` had **no read-back assertion anywhere in the suite**; the three
  existing `is_truncated` assertions concern disclosure truncation, which is a
  different thing wearing the same name. Each field is now pinned against an
  independently known expected value rather than against whatever the row holds,
  and each was proven non-vacuous by planting a corruption and reading the
  failure. The truncation flag is parametrised over both values with the
  known-caught case beside the plant in the same parametrisation, because a
  boolean pinned only at `False` is satisfied by a column that is always `False`.
  These land across the FAST, `database` and `e2e` tiers, and only the contract
  assertions run in FAST — the PostgreSQL round trip is `database`-tier and is
  not FAST coverage.*
- **`coverage_for` runs outside `persistence.search`'s redaction path**, so a
  `SQLAlchemyError` from the coverage read escapes carrying SQL and a bound
  identifier. Not the query-leak path, since nothing there binds query text, but
  the same class of hole. **Closed** — after WP-4 shipped rather than in it,
  which is the whole finding. `_coverage` now classifies the delegated failure
  with `_execute`'s handler set, and
  `tests/architecture/test_search_reads_leave_through_the_redaction_path.py`
  derives the rule from the module's own syntax tree, so the next read written
  outside the redaction path fails a test rather than being disclosed in a
  paragraph and scheduled here again.
- **No `statement_timeout` is configured anywhere.** The functional index removes
  the sequential scan as the only possibility without bounding what a query can
  cost. WP-4 owns process and connection configuration. *Corrected 2026-08-08:
  **this bullet is false at `6e491c2`.** `statement_timeout` is configured, on
  the connection rather than in the server, and it cannot be configured away.
  `src/my_pa/bootstrap/settings.py:244` carries `statement_timeout_ms` as a
  validated `MY_PA_` field with `gt=0` and a `DEFAULT_STATEMENT_TIMEOUT_MS`
  default (`:109`); `src/my_pa/bootstrap/gateway.py:163` and `:166` pass it to
  **both** engines as a libpq `options` connection parameter. A `database_url`
  smuggling its own `options=-c statement_timeout=0` is refused rather than
  honoured — the four cases are pinned in `tests/unit/test_settings.py`
  (`test_the_statement_timeout_cannot_be_configured_away`,
  `test_a_misspelled_statement_timeout_is_not_silently_ignored`) and the
  both-engines property in `tests/unit/test_gateway_composition.py:160`. Closed
  by #52 at `6e491c2`, which is the change that also wrote this correction's
  subject into existence. The superseded wording is kept and negated rather than
  deleted, per the `D-78`/`D-81` shape. No new `D-` identifier is minted — see
  the identifier-reservation note under section 13's decision table.*
- **`eligible` is a required integer in the `v1` disclosure** and no integer is
  true for an unmeasured scope. Making it absent is a contract change gated by
  `P00-OD-004`.
- Smaller, and named so they are not rediscovered: the `extractions` check
  constraint admits a status no counting query matches; `record_object` in
  `infrastructure/persistence/registry.py` names a function that does not exist
  (it is `observe_object`); `INDEXED_CONFIGURATIONS` is read as a rebindable
  module global; the offline DDL test asserts constraint names but not index
  names; and `mypy` is configured over a wider tree than the gate runs.
  *Corrected 2026-08-08: **three of these five are closed at `6e491c2` and this
  bullet still asserts all five.** Taken in the order written. **(1) The
  `extractions` check constraint — open**, and the only one of the five whose
  wording still holds exactly as written. **(2) `record_object`
  — closed.** No `record_object` symbol occurs anywhere in the repository; the
  function is `observe_object` at
  `src/my_pa/infrastructure/persistence/registry.py:246`, and the comment that
  named the wrong one is gone. Closed by #52 at `6e491c2`. **(3)
  `INDEXED_CONFIGURATIONS` — closed, and closed more strongly than this bullet
  asked.** Rebindability was the wrong property to chase: the value is resolved
  once at import into the `literal_column` every statement in the module holds,
  so rebinding the global after import changes no statement, and the guard in
  `_configuration` (`src/my_pa/infrastructure/persistence/search.py:330`) refuses
  any name outside the closed set before it can reach SQL interpolation.
  `src/my_pa/infrastructure/persistence/capture_search.py:186` carries the same
  guard for the second plane. Closed by #52 at `6e491c2`. **(4) The offline DDL
  test — open, and narrower than this bullet says.** The bullet reads as though
  index names are unpinned; they are not. Both functional GIN indexes are pinned
  online by `EXPLAIN`-plan assertion —
  `tests/search_quality/test_lexical_search.py:3710` for `extractions_full_text`
  and `tests/search_quality/test_capture_search.py:285` for
  `capture_versions_full_text`, with the index *definition* additionally checked
  at `tests/schema/test_capture_schema_migration.py:781`. The residue is the
  **offline `--sql` review artifact alone**:
  `test_offline_mode_emits_the_knowledge_ddl_without_connecting`
  (`tests/schema/test_knowledge_schema_migration.py:182`) asserts the schema, the
  tables, the unique constraints and the check constraints, and asserts nothing
  about indexes — so the artifact a reviewer reads without a server does not
  attest them. That is a disclosure gap in one artifact, not an unpinned index,
  and it should be stated that way rather than as a wider hole. **It was open
  when this correction was written and is closed by the change carrying it**:
  the offline test now asserts three whole `CREATE INDEX` statements rather than
  three names, because a name alone is satisfied by the same name over a plain
  btree — the expression and the access method are the part worth attesting. It
  is a subset assertion and says so, since the chain emits further indexes into
  `knowledge` that it does not attest. **(5) `mypy` —
  closed, and closed before either of the two pull requests that have since
  restated it as open.** `D-64` widened both workflow jobs to a bare
  `python -m mypy` at `08e7c81` (#33); `pyproject.toml:204` holds
  `files = ["src", "migrations", "apps"]` and
  `.github/workflows/repository-checks.yml:101` and `:248` invoke `mypy` with no
  path argument, so the configured tree and the gated tree agree by construction
  rather than by a maintained number. **#51's body restated this item as
  remaining, and #52 did not correct it** — in both cases the list was inherited
  from this bullet rather than recomputed, which is the defect this correction
  exists to stop propagating. Neither pull request's history is rewritten; the
  correction is recorded here, where the list they inherited from lives, and as a
  comment on #51. **`D-64`'s invariant was held by three prose comments and
  nothing else until the change carrying this correction, and is now
  mechanized**: `tests/architecture/test_ci_invokes_mypy_over_the_declared_tree.py`
  parses the workflow and fails on any `mypy` invocation in any job that carries
  a path argument, and separately asserts that every repository root holding
  Python is either in `[tool.mypy] files` or named as deliberately unchecked. It
  is a parse and not a text search, and the reason is measured: a search for the
  string `mypy src` in that workflow matches four times, and all four are the
  prose comments explaining why it must not be written. The parser is
  hand-written over the block-YAML subset the workflows use, because no YAML
  library is available to this repository. **Its first version claimed to raise
  on any construct it did not understand, and that claim was false** — an
  independent review at `f44f45d` put the `D-64` defect back into the real
  workflow behind a folded `>` scalar and behind a `.yaml` suffix, and watched
  the guard stay green both times. A guard that advertises fail-closed and
  fails open is worse than no guard, because the disclosure buys confidence the
  mechanism has not earned. The parser now folds `>` per YAML's rules, reads
  both suffixes GitHub honours, and unquotes only simple quoting while raising
  on the rest; its docstring is a four-way ledger — what it reads, what it
  reads without interpreting, what it raises on, and what it ignores — rather
  than a single claim of totality. The superseded wording is kept and
  negated rather than deleted,
  per the `D-78`/`D-81` shape. No new `D-` identifier is minted — see the
  identifier-reservation note under section 13's decision table.*

### What the WP-3 reviews cost, and what they bought

Seven reviews, seven blocks, and CI green on all three jobs for every head every
one of them examined.

The first found a coverage crash that killed an enrollment's entire read path, a
search result claiming `processed` coverage over a denominator it never measured,
a module docstring that told a reviewer the opposite of what its own commit did,
and a test cited in two source comments as proof of a property it did not test —
which stayed green when that property was deliberately broken.

The rest found one pattern six more times: **a correction closes exactly the case
its finding named and leaves the adjacent one open.** The clamp covered one
coverage state and not its two siblings. The crash was fixed for one cause of
three. An authorization boundary was added for cross-source objects but not
same-source ones. Both halves of that boundary were violated at once in every
test, so neither was pinned. An entire dimension of the grant — the enrollment's
content-type allowlist, stored and validated and read by nothing — was enforced
nowhere at all, and survived five reviews because each sweep was built from what
the branch had changed rather than from what the code enforced.

Three of the findings were reachable only by planting a violation. The clearest
is the vacuous index test: correct rows come back whether or not the index is
used, so no result-comparing test could ever have caught it, and only breaking it
on purpose showed that nothing was watching.

Twice the false claim was introduced by the correction itself. That is the part
worth carrying into WP-4 as method rather than as history: brief a fix against
the assumption underneath a finding rather than against the finding, build a
mutation sweep from the code rather than from the diff, and treat every sentence
written beside the code as a claim a reviewer will check.


Findings from WP-2's review that were deliberately not fixed there, recorded so
they are scheduled rather than forgotten.

- **Not every unavailability is a denial.** `fetch` now reports a read timeout
  as `unavailable` rather than `denied`, but `EMFILE`, `ENFILE`, `ENOMEM`,
  `EIO`, and `ESTALE` still fall into the blanket `except OSError` and become a
  non-retryable refusal. Proven with `RLIMIT_NOFILE` clamped: descriptor
  exhaustion tells the caller to stop retrying something that is merely
  unavailable, which `INV-PKL-007` forbids. WP-2 established the principle on
  one errno; WP-3 should finish applying it.
- **A refused hard link vanishes from listings with no signal.** A root holding
  two names for one legitimate in-root file lists neither. That converts present
  evidence into "not there". Spec section 9.2 permits the remedy — "safe
  aggregate limitations may be disclosed" — but this layer has no coverage
  plumbing until WP-3 builds it. Hard links are not exotic on a backup-derived
  NAS root, so this matters before `P00-OD-009` is answered.

## 11. Operator decisions this plan does not make

- Whether to promote E, F, G, or I into current scope. That takes an explicit
  reprioritisation of the objective under `AGENTS.md` §3, not an implementation
  choice, and not a specification amendment alone.
- Except for WP-FE-03 — Work: Tasks and Commitments, which `D-108` narrowly
  admits, H is held by direct operator instruction (`D-09`) and resumes only
  when the operator lifts it, independently of whether its backend dependencies
  exist. WP-FE-02 and WP-FE-04 onward remain held.
- Note that the `AGENTS.md` basis is strongest for E and F, which a read-only
  slice excludes directly, and weakest for I, where the deferral leans on §3's
  preference for one slice over partial systems and on the proposed
  specification. An operator weighing I should know it rests on thinner ground
  than E or F.
- `P00-OD-003` — selecting a reviewed PDF extractor.
- `P00-OD-009` — authorizing a live NAS or GoodNotes source root by exact path.
- Production deployment, risk acceptance, and credential mutation, all of which
  remain outside every work package here.

## 12. Promoted scope: work packages WP-4 through WP-9

The operator reprioritised two features into scope on 2026-08-01: Relationship
Intelligence and Quick Capture. Section 13 records the instruments that admitted
them. This section is the resulting work-package plan. It replaces nothing in
section 7; WP-1 through WP-3 are merged, and WP-4 and WP-5 keep the objectives
section 7 gave them.

On 2026-08-21 the operator separately and narrowly admitted WP-FE-03 — Work:
Tasks and Commitments — to bounded frontend implementation (`D-108`). That
exception does not activate WP-10, WP-FE-02, WP-FE-04 or any later phase, or any
other frontend surface, and it grants no authority for authentication
replacement, deployment, production or shared-database access, credentials,
live personal data, new infrastructure, destructive action, or risk acceptance.

Two facts constrain the sequence more than anything in the feature packages.

First, **neither feature has a surface**. Both are specified against an HTTP
gateway, a worker process, and application services wired to the eight
capabilities. *The sentence that follows is state at time of writing
(2026-08-01) and is deliberately not updated: WP-4A wired the application
services, WP-4B1 made the worker a process, WP-4B2a made the gateway one, and
WP-4B2b added the MCP and CLI surfaces — so `apps/worker/` and `apps/gateway/`
are both gone, `apps/worker.py` and `apps/gateway.py` are real composition
roots, and both features now have the surface this paragraph says neither has. It is left standing because the
argument it supports is about the sequence, not about the tree today.* None of
those exist: `apps/gateway/` and `apps/worker/` hold a
README each, and `application/` holds one module that derives the capability
manifest. Quick Capture's own architecture file says so, and the Relationship
Intelligence specification makes "current MCV substrate completed" the first
prerequisite of its R1 stage. Building either feature before WP-4 would mean
inventing the transport it is supposed to travel over.

Second, **the read-only slice is two packages from complete**. WP-4 and WP-5 are
the last of it. Finishing them first yields the thing `AGENTS.md` section 1 asks
for — one complete vertical slice — and gives both features a substrate that has
been proven end to end rather than one assembled underneath them. The
alternative, interleaving feature work, leaves the slice permanently at ninety
percent while the surface area grows. The recommendation is therefore to finish
the slice first. The operator may reorder; see `D-12`.

### Sequence

**This table was superseded on 2026-08-02 and is kept for the shape it records.**
`D-28` split WP-4 into two pull requests, the Remote Quick Capture revision
added WP-0R and a conditional WP-10, and the Native Apple Reminders revision
added a conditional WP-11. The sequence the campaign is executing is below; the
original rows above are what section 15's divergence 2 corrected.

| WP | Objective | Depends on | Frontend? |
|---|---|---|---|
| WP-0R | Canonical re-mirror and reconciliation against the Remote Quick Capture revision | — | No |
| WP-4A | Application services: use cases, ports, shared policy and disclosure path, derived manifest | WP-3 | No |
| WP-4B | Transports: HTTP gateway, MCP adapter, operator CLI, composition roots, worker lease loop, parity matrices | WP-4A | No |
| WP-5 | Operations and local candidate | WP-4B | No |
| WP-6 | Capture domain, contracts, durable-first persistence, `capture.create`, registered client, submission, receipt, outbox | WP-5 | No |
| WP-7 | Capture processing, proposals, evidence spans, deterministic classification, restricted entity mentions, exact search | WP-6 | No |
| WP-8 | Review cases, promotion, conversation events, corrections | WP-7 | No |
| WP-9 | Relationship identity and read-only profiles | WP-4B, WP-8 | No |
| WP-10 | PWA capture surface and offline recovery — **deferred until after MCV completion by `D-104`; active gates `D-09`, `O-04`, and `O-20` remain** | WP-8 | **Yes** |
| WP-11 | Native Apple Reminders execution projection, internal sequence `NAR-00` policy amendment, `NAR-01` EventKit feasibility proof, `NAR-02` domain and contracts, `NAR-03` application services, `NAR-04` signed native bridge, `NAR-05` creation and updates, `NAR-06` completion roundtrip, `NAR-07` conflicts and recovery, `NAR-08` security and operational proof — **dependency-blocked by deferred WP-10; its completion-boundary placement is unresolved; active gates `NAR-OP-001`–`NAR-OP-009` remain** | WP-10 | No |
| WP-12 | Apple Mail, Calendar & Contacts — **authorized before MCV completion under `AUTH-WP12-20260804-OPERATOR-001`; internal order A, B, D, C, E, F, G, H; live and extreme-risk actions remain excluded** | WP-9; WP-10/WP-11 remain deferred, not prerequisites | Slice G only |

Two things about that table are worth stating rather than leaving to be inferred.

`D-28` split WP-4 because WP-4 as section 7 and this section specified it is
application services plus three transports plus two composition roots plus a
worker loop, which is more than one review can hold at the quality this campaign
requires. The split is a packaging decision and changes no objective: WP-4A and
WP-4B together are exactly the old WP-4, and every dependency that named WP-4
now names whichever half it actually needs — WP-9 needs the transports, so it
names WP-4B.

**WP-6 through WP-8 absorb the six new Remote Quick Capture record types rather
than growing a new package.** The revision added `CaptureSubmission`,
`RegisteredCaptureClient`, `CaptureDeliveryAttempt`, `CaptureClassification` and
`CaptureDomainAssignment`, `CaptureEntityMention`, and `CaptureCorrection` to the
canonical object model. None of them needs a package of its own: the durable-first
transaction, immutability, idempotency, evidence spans, and proportional review
they depend on are already the acceptance criteria of WP-6, WP-7, and WP-8. Adding
a package would duplicate those criteria; section 16 maps each type onto the
package that already carries them.

WP-0R through WP-9 are frontend-free and proceeded under `D-09`. **WP-10 is
not**, and the operator directly deferred it until after MCV completion on
2026-08-04 (`D-104`), superseding `D-32`'s assumed pre-completion sequencing.
WP-11 remains frontend-free — its surface is a signed macOS bridge, not a web
surface, so `D-09` does not reach it — but its declared WP-10 dependency makes
its placement conflict with that deferral rather than proving a post-completion
disposition. It also remains held by nine open operator decisions
`NAR-OP-001` through `NAR-OP-009`, one of which is the EventKit permission grant
and another the code-signing identity. `AUTH-WP12-20260804-OPERATOR-001` and
`D-106` expressly promote WP-12 ahead of WP-10/WP-11 for bounded synthetic-only
repository implementation; this reorders only WP-12 and does not reactivate the
two deferred packages. The remaining
frontend stages — Quick Capture `QC-05` through `QC-08`, and every responsive
surface in the Relationship Intelligence specification — are not planned here
and remain held, except only for the bounded WP-FE-03 Work: Tasks and
Commitments surface admitted by `D-108`. That exception does not reactivate
WP-10, WP-FE-02, WP-FE-04, or any later phase.

`D-107` records the next-campaign handoff without starting it: only after MCV
completion is independently verified, a fresh orchestrator defines a
comprehensive MVP `CAMPAIGN-BRIEF` and executes the full MVP, including WP-10
and WP-11. That future instruction supplies no present authority to implement
either package, declare MCV complete, deploy, or cross an operator-only gate.

### WP-4 — application services and transports

**Objective.** Wire the eight existing `v1` capabilities to the behavior WP-2
and WP-3 built, and expose them over HTTP, MCP, and the operator CLI with proven
transport parity.

**In scope.** `src/my_pa/application/` use cases for the eight capabilities;
policy evaluation on one path shared by all three transports;
`src/my_pa/adapters/http/`, `adapters/mcp/`, `adapters/cli/` (or the equivalent
paths the implementing PR names, reconciled with `module-boundaries.md` section
3 — see the note below); `apps/gateway.py` and `apps/worker.py` composition
roots; the worker lease loop over the job plane WP-2 built; disclosure envelope
assembly from real coverage rather than constants.

**Out of scope.** Any capture or relationship behavior. Authentication mechanism
selection beyond a local principal (`P00-OD-010` stays open). Network exposure
beyond loopback. PDF (`P00-OD-003` stays open).

**Acceptance criteria mapped to tests.**

- `SPEC-AC-001` transport parity — a conformance matrix asserting HTTP and MCP
  produce byte-equivalent normalized requests and semantically identical
  responses and errors for all eight capabilities.
- `P05-SPEC-AC-002` negative evidence — traversal, source mutation, unknown
  scope, purpose escalation, and prompt-injection denial, each proven through
  every transport, not only one.
- `MB-AC-002` — architecture tests extended so `application` imports no
  transport, ORM, SQL, or provider module, and only composition roots
  instantiate concrete implementations.
- Capability manifest and readiness stop reporting `not_implemented` and
  `contracts_only` **because the manifest is derived**, not because a constant
  changed. `tests/contract/test_capabilities_and_readiness.py` already asserts
  derivation; extend it to assert the derived value tracks real availability.

**Note on path drift.** `module-boundaries.md` section 3 proposes
`src/my_pa/adapters/…` and `src/my_pa/apps/…`. The implementation instead uses
`infrastructure/providers/` and `infrastructure/persistence/`, and `apps/` is a
sibling of `src/`. Section 3 permits refinement, but the document and the tree
should stop disagreeing. WP-4 reconciles them in the same change that creates
the transports, and states which way it reconciled.

### WP-5 — operations and local candidate

**Objective.** Make the read-only slice runnable, observable, and recoverable by
one operator on one machine, and state its limitations honestly.

**In scope.** Startup and shutdown for gateway and worker; health and readiness
endpoints; empty-to-head migration validation as a gate rather than a test;
recovery and idempotency tests for interrupted extraction; the end-to-end
synthetic vertical slice from enrollment to `knowledge.read`; an operator
runbook; a limitations document that names what the slice does not do.

**Out of scope.** Deployment, production activation, packaging for distribution,
multi-user operation, and risk acceptance. All operator-gated.

**Acceptance criteria mapped to tests.** The seven numbered conditions in spec
section 3 each demonstrated by one synthetic end-to-end test; recovery tests
that kill a worker mid-extraction and prove no duplicate and no lost coverage;
a migration test that runs empty-to-head and head-to-empty against a disposable
database.

### WP-6 — capture domain, contracts, and durable persistence

**Objective.** Persist a user-authored capture durably, immutably, and
idempotently, and read it back with its provenance. Nothing derived.

Delivers the **durable-capture portion** of Quick Capture stages `QC-01` and
`QC-02`. *Corrected 2026-08-03 (`D-79`): this line read "Corresponds to Quick
Capture stages `QC-01` and `QC-02`", which overclaims. Read at
`../specs/quick-capture/19_MVP_DEFERRED_CAPABILITIES_AND_ROADMAP.md:143` and
`:152`, `QC-01` also requires "proposal/span schemas" and `QC-02` an
"original-text read/search stub" — both outside WP-6's seven acceptance criteria
and both assigned by this plan to WP-7. A sentence claiming WP-6 corresponds to
those stages whole would be a claim no criterion here supports.*

**In scope.** `domain/capture/` — capture and version entities, lifecycle
states, authority states, the immutability invariant, typed errors;
`contracts/v1/` additions for capture create, version create, read, and list;
new capability names and purposes added to `domain/identity/operation.py`;
one Alembic revision creating capture tables in the `knowledge` schema (or a new
schema the PR names and justifies); `infrastructure/persistence/capture.py`;
**`CaptureSubmission`, its `NOT NULL UNIQUE` idempotency key, and the capture
outbox**; the save transaction, as corrected below.

*Corrected 2026-08-03 (`D-73`): the in-scope list above omitted
`CaptureSubmission` and the outbox. It was written by `9096fa4` (#23), **before**
the Remote Quick Capture revision existed, and was not revisited when `c60f5cc`
(#25) extended WP-6 in three other places — section 7's merge order, section 12's
sequence table, and section 16's record-type mapping. It is an omission rather
than a narrowing, because it cannot have narrowed material that did not yet
exist, and section 7's closing precedence sentence settles it: "Items 4 through 13
restate section 12's sequence table, which is the authoritative one." The two remaining Remote
Quick Capture record types are deferred rather than in scope — see `D-74`.*

**The save transaction, corrected 2026-08-03 (`D-75`).** This paragraph read
"capture, version, receipt, **redacted audit**, and enqueued processing job
committed together or not at all", and the audit clause was false:
`SqlAlchemyAuditSink.record` takes its **own** connection and commits before
returning (`../../src/my_pa/infrastructure/persistence/audit.py`,
`../../src/my_pa/infrastructure/persistence/unit_of_work.py`), which is `D-34`
and cannot be undone without overturning it. The true statement is:

> capture + version + submission + receipt + enqueued capture job commit
> together or not at all, on the work connection. The redacted audit event
> commits **first and separately**, on the audit connection, per `D-34`; the
> version stores the audit **reference**. A failed audit fails the request closed
> and no capture exists afterwards. A failed work transaction leaves an audit
> event describing an authorization whose work never landed, which `D-34` records
> as the correct direction of the trade.

**Out of scope.** Extraction of any kind. Proposals, spans, review, conversation
events. Offline queue. Any frontend. Attachments. Model calls.

**Acceptance criteria mapped to tests.**

**Five of these were wrong or narrowed against the spec and are corrected in
place, 2026-08-03 (`D-75`).** Where a paraphrase here disagreed with
`../specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md`, the spec
governs. Each correction is marked so a reader can see what moved.

**Two of those five are not plan errors, and calling them that was itself wrong
(`D-82`, `D-84`).** The idempotency code and the atomicity sentence were both
taken faithfully from the spec package; the disagreement is between the spec and
this repository's `v1` contracts, and between the spec and `D-34`. The
dispositions stand and the classifications are corrected — a conflict between two
instruments is recorded as open, where a plan error is closed by fixing the plan.
**And `QC-AC-034`, which `D-75` pronounced correct, is filed under the wrong
criterion (`D-85`).**

- `QC-AC-010` immutability **and independent retrievability** — a domain test
  proving no code path updates stored text, a database test proving the
  constraint holds under concurrent write, **and a test proving a superseded
  version is retrievable at its own identifier**. *Corrected: the paraphrase
  covered immutability only; spec
  `../specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md:189` also requires "and independently
  retrievable", and a build resolving every read to the head of the chain would
  have satisfied the old wording.*
- `QC-AC-012` distinct timestamps — **five**, not three: `client_created_at`
  (device), `server_received_at` (server), `occurred_at`, `recorded_at`, and
  `accepted_at`, separately stored and never substituted for one another, with a
  genuinely absent client time stored as `NULL` rather than invented. *Corrected:
  this named three and silently dropped **occurred** and **accepted**. Spec
  `../specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md:191` requires all five to remain distinct, so the paraphrase narrowed the
  criterion by two columns. Corrected a second time, 2026-08-03: the first
  correction glossed `recorded_at` as the criterion's "processed", which
  `../specs/quick-capture/10_SOURCE_AUTHORITY_AND_PROVENANCE_MODEL.md` forbids —
  `:49` makes `recorded_at` "product event representing capture recording",
  `:51` makes `processed_at` "when a processing stage ran", and `:56` says "do
  not substitute one for another". WP-6 runs no processing stage, so it stores no
  `processed_at`; the five columns above are what WP-6 keeps distinct and the
  criterion's fifth slot is **`recorded_at` in its own right**, with
  `processed_at` arriving with WP-7's worker. A correction that fixed a count by
  mis-binding a name is the same class of defect as the one it fixed.*
- `QC-AC-013` editing appends — an edit creates a successor version, the
  predecessor stays retrievable, and the supersession chain is unbroken.
- `QC-AC-031`/`QC-AC-032` idempotency — replaying an identical request returns
  the stored receipt; reusing the key with different content returns **`conflict`
  with `safe_details: ["idempotency_key"]`** and stores nothing. *Corrected: this
  said `idempotency_conflict`. `../../src/my_pa/contracts/v1/errors.py` is a
  closed set of **eleven** public codes and that is not one of them, so the `v1`
  answer is `conflict`. Corrected a second time, 2026-08-03 (`D-82`): the first
  correction called this a plan error and said a twelfth code "would have been an
  unauthorised `v1` expansion" — as though the plan had invented the name. **It
  did not.** `idempotency_conflict` is the spec package's own word, at
  `../specs/quick-capture/18_PROPOSED_API_AND_CONTRACT_PACKAGE.md:255` and `:316`
  and `../specs/quick-capture/09_LOGICAL_DATA_MODEL.md:296`. Under `D-75`'s own
  rule that the spec governs, this is an **unresolved conflict between the spec
  and the `v1` contract**, not a corrected plan error. The disposition is
  unchanged and `18:14` is why: the proposed contracts "do not authorize
  implementation or change the repository's current `v1` capability set".*
- `QC-AC-034` — an induced audit or receipt failure fails the whole transaction
  closed, and no capture exists afterwards. Prove by planting the failure.
  *Unchanged, and deliberately so: this is right even though the mechanism
  sentence above it was wrong. Note what "afterwards" means at each end — an
  induced **audit** failure leaves nothing at all, while an induced **receipt**
  failure leaves no capture **and an audit row that survives**, because `D-34`
  makes the audit outlive the work it describes. A test asserting both absent
  would be asserting `D-34` is false.* **Corrected 2026-08-03 (`D-85`): the test
  is right and the criterion label is wrong.** Spec
  `../specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md:208` reads "`QC-AC-034`:
  Processing failure never loses the source capture" — a *post-save* failure,
  requiring the capture to **survive**. The bullet above describes a *save-time*
  audit or receipt failure requiring **no capture to exist**, which is a real
  requirement with its own spec ground at
  `../specs/quick-capture/11_EXTRACTION_AND_PROPOSAL_PIPELINE.md:37` — "if
  audit/receipt persistence required by policy fails, the server fails closed" —
  but is not `QC-AC-034`. Spec `QC-AC-034` is **not exercisable in WP-6**: nothing
  consumes `knowledge.capture_jobs` until WP-7, so there is no processing stage
  whose failure could lose a capture. `D-75` read this bullet as "true as worded"
  and did not compare it to the criterion it names.
- `QC-AC-041` — a redaction test asserting no capture text reaches logs, audit
  rows, **event payloads, or URL parameters**, and that the text **is**
  retrievable through `capture.read`. *Corrected: this named three sinks. Spec
  `../specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md:214` names five — "logs, telemetry, event payloads, URL parameters, or
  lock-screen notifications" — and URL parameters is live here, because
  `capture.create` over HTTP must not accept text in a query string. The
  retrievability clause is what stops a build that stored nothing from passing.
  Corrected a second time, 2026-08-03: the first correction quoted the criterion
  as "error payloads" where the spec says the wider **"event payloads"**, and
  quietly kept "audit rows", which the spec does not name at all. Both are now as
  the spec has them, with audit rows kept as an addition this repository makes
  rather than as a quotation. **The two sinks still not covered by a test are
  telemetry and lock-screen notifications, and both are verified absent rather
  than assumed**: no telemetry emitter exists anywhere in `../../src/` or
  `../../apps/`, and there is no frontend, so neither sink is reachable. Head is
  strictly wider than base — three sinks became four — so nothing was narrowed;
  what is open is a criterion whose full sink list cannot be exercised until those
  sinks exist.*
- ADR-003 clause 5 — an architecture test asserting the source-provider port
  still exposes no write method and that capture persistence does not import it.

### WP-7 — capture processing, proposals, evidence spans, exact search

**Objective.** Turn a stored capture version into typed, span-bound, explicitly
noncanonical proposals, and make the original text searchable — without a model.

Corresponds to Quick Capture stage `QC-03`, restricted.

**In scope.** Worker stages `P-01` validate — which includes **loading the
processing-policy snapshot recorded at save** and branching on it (`11:46`,
`D-95`) and **denying prohibited destinations** — `P-02` normalise with a
reversible offset mapping **and identify quoted or pasted regions** (`11:55`),
`P-03` language detection allowing `unknown` and translating nothing silently,
`P-04` segmentation **including quoted and pasted regions** (`11:69`), `P-05`
deterministic extraction (dates, amounts, identifiers, URLs, explicit commitment
cues, **and known aliases where an alias table exists**) **each carrying an
authority classification** (`11:81`), `P-08` date normalisation **preserving the
raw phrase and identifying ambiguity rather than resolving it**, `P-09`
work-object proposals from deterministic cues only **recording the required
fields they could not fill** (`11:131`), `P-15` transactional proposal
persistence, `P-16` indexing of original text **immediately** (`11:191`).
Evidence spans on `unicode_code_point_v1` with quoted-text hashes re-validated
against the immutable version.

**Six stage deltas, admitted rather than left to a reviewer** (`D-89`). The
sentence above previously dropped: `P-01`'s policy-snapshot load and destination
denial; `P-02`'s and `P-04`'s quoted-and-pasted-region identification, which is
the *structural* half of `QC-AC-042` — marking pasted regions is how captured
content is made recognisable as data rather than as instruction; `P-05`'s known
aliases and its authority classification; `P-09`'s missing-required-fields, which
is what keeps a partial proposal honest instead of invented; and `P-16`'s
"immediately", which is what forbids indexing from sitting behind extraction.
Three of the six are implemented as written. `P-05`'s **known aliases** is in
scope and unreachable — it needs an alias table `Person`/`Organization` will
bring in WP-9 — and `P-05`'s **phone- and email-like strings** stay out, because
`11:78` permits them only "where policy permits" and the one policy this build
stores says nothing about contact detail. `P-08` resolves **no relative phrase**:
resolving one needs a clock, and a stage that reads a clock cannot satisfy
`QC-AC-035`'s replay clause, so ambiguity is recorded instead.

**`P-13` is in scope**, and this plan previously placed it neither in nor out —
a gap rather than a decision (`D-89`). It carries `QC-AC-042`'s retrieval
sentence (`11:177`: "Retrieval scope is explicit and recorded. Pasted/captured
text cannot expand tool authority"), so leaving it unruled would have left the
criterion's first half with no stage to live in. It is discharged **structurally**
rather than by a stage of its own: the pipeline resolves no source provider,
imports no network module, and takes every record's `version_id` from the job's
subject, so there is no retrieval for captured text to widen.
`tests/architecture/test_capture_reaches_no_source.py` is the static form and
`tests/pipeline/test_injection_corpus.py` the runtime one.

**Out of scope, and why — the exclusion stands and its stated reason did not.**
`P-06` named-entity extraction, `P-07` identity resolution, `P-12` contradiction
detection, and `P-14` summary generation are excluded because **each requires a
resolver or a generator this repository has not built and `P00-OD-006` is open**.
The previous wording called all four "model-assisted", and measured against
`11_EXTRACTION_AND_PROPOSAL_PIPELINE.md` that is **not what the specification
says** for three of them: `11` never uses the word "model" for `P-06`, `P-07` or
`P-12`, and `P-07`'s candidate ranking explicitly permits deterministic inputs
(`11:100` exact aliases, `11:107` chronology). Only `P-14` is tied to AI, and
indirectly. A reviewer checking the old reason against the spec would not have
found it there; the new one is checkable (`D-89`). Excluding them costs recall,
not correctness: a deterministic-only pipeline proposes less but proposes nothing
it cannot cite. **`P-06`'s output object is partly in scope even though the stage
is not** — `CaptureEntityMention` is built for the deterministic subset under
`D-93`.

**Acceptance criteria mapped to tests.** There are **six**, not five: `D-85`
carried `QC-AC-034` here, and `D-89` corrects five of the six statements below to
their spec strength. The binding text of each is
`../specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md`, not this plan's
paraphrase.

- `QC-AC-011` — spec `20:190`: "Every proposal / **accepted derived record**
  points to **exact validated** source spans." Two corrections. "At least one
  span" is a *cardinality* and the spec asks for a *validation*, so the test
  asserts **re-derivation** of each cited span's digest from
  `capture_versions.content`, not a count. And the plan's stated proof —
  "mutating a version and re-running" — **cannot be executed on this schema**:
  merged revision `1a4c9e77b2d5` installs `capture_versions_are_append_only`, a
  `BEFORE UPDATE OR DELETE` trigger raising `restrict_violation`, so no writer
  including a test can update a version. The proof is **persistence-layer span
  injection** instead. **The accepted-derived-record half is out of WP-7's reach
  and is disclosed as half-discharged here**, to be re-proved by WP-8; it is not
  claimed. Tests: `tests/pipeline/test_proposal_spans.py`.
- `QC-AC-050` — spec `20:221`: "**Exact** original text is searchable
  independently of enrichment success." The word *Exact* was dropped and it is
  load-bearing (`D-89`, `D-90`): measured, `to_tsvector('english','…running…')`
  stores `run`, so a query for `run` matches text that never contains the word,
  and `to_tsvector('english','a the of and')` is **empty**, so a stop-word-only
  capture is saved, valid, and unfindable with no exception anywhere. The plane
  is therefore `simple` with an exact-substring confirmation, and **which queries
  that confirmation applies to is read from the server rather than decided in
  Python** — deciding it in Python falsified this criterion twice. The
  `P-16`-before-`P-15` ordering asserted in `test_save_does_not_wait.py` belongs
  to **this** criterion and not to `QC-AC-002`: a searchability confirmation
  sequenced behind proposal persistence never runs for the capture whose
  enrichment failed, which is the capture this criterion is about. Tests:
  `tests/search_quality/test_capture_search.py`,
  `tests/search_quality/test_exact_confirmation_matrix.py`.
- `QC-AC-035` — replaying a completed stage returns the prior output and creates
  no duplicate proposal; a lost lease cannot commit. Both additions are grounded
  (`11:212`, `D-45`(e)). **`capture_stage_results` stores no output blob**, so
  "returns the prior output" holds only while every stage is deterministically
  re-derivable from the immutable version plus the recorded pipeline version;
  that is proved per stage for all nine and the comparison is shown able to fail.
  The lost-lease proof is the **narrow** one — the lease is stolen from a second
  connection between two stages, and the test asserts both that the later stage
  committed nothing and that the earlier ones remain. **The spec's "or accepted
  objects" clause is discharged vacuously here** — no accepted object exists
  until WP-8 — and is stated as such rather than recorded as proven. Tests:
  `tests/pipeline/test_stage_replay.py`,
  `tests/jobs/test_capture_pipeline_recovery.py`.
- `QC-AC-042` — spec `20:215`: "Captured/pasted instructions cannot invoke tools
  or broaden **retrieval/disclosure**." "Widened scope" is not "retrieval and
  disclosure" (`D-89`): **disclosure is a first-class object here** —
  `application/disclosure.py`, canonical `09:130`'s `DisclosureEnvelope` — so the
  criterion also requires that captured text cannot suppress a limitation,
  inflate a coverage count, or alter a freshness label, which is the half least
  like a tool call and most easily missed. **The injection corpus's synthetic
  requirement is grounded in `QC-AC-073` (`20:239`) and `AGENTS.md` section 5,
  not in `QC-AC-042`**, which says nothing about where a corpus comes from. Tests:
  `tests/architecture/test_capture_reaches_no_source.py`,
  `tests/pipeline/test_injection_corpus.py`.
- `QC-AC-002` — spec `20:182`: "Save acknowledgment does not wait for
  AI/extraction/indexing." The stated proof is insufficient (`D-89`): "the
  committed set contains no proposal row" is about *membership* and the criterion
  is about *ordering*, so a save could commit no proposal while blocking on a
  synchronous index write and pass it. The test asserts the **whole** committed
  set. **One thing is disclosed rather than claimed**: WP-7 built the capture
  plane as a **functional GIN index over `capture_versions.content`**, not as an
  index table, so there is no index row for a committed set to contain and that
  half is structurally true rather than measured — and structurally true in the
  stronger direction, because a searchability the pipeline never wrote is one it
  cannot discard. What is measured for **this** criterion instead is the whole
  committed set, and that the saved capture is searchable **before any worker
  runs**. The `P-16`-before-`P-15` ordering the same module also asserts is a
  **`QC-AC-050`** property and not this one — a confirmation sequenced behind
  `P-15` never runs for the capture whose enrichment failed, which is the capture
  `QC-AC-050` is about — and the test's own docstring attributes it that way.
  Tests: `tests/pipeline/test_save_does_not_wait.py`.
- `QC-AC-034` — spec `20:208`: "Processing failure never loses the source
  capture." **The sixth criterion**, carried here by `D-85`, which ruled it not
  exercisable in WP-6 because nothing consumed `knowledge.capture_jobs` yet. WP-7
  is the package that consumes it. A second, independent ground `D-85` does not
  cite: canonical `09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md:108`, invariant 7 —
  "No processing failure hides Capture." Tests:
  `tests/jobs/test_capture_pipeline_recovery.py`.

**Processing-state vocabulary — ruled, because two instruments disagree.**
`../specs/quick-capture/11_EXTRACTION_AND_PROPOSAL_PIPELINE.md:224-234` gives
nine aggregate processing states (`pending`, `processing`, `complete`, `partial`,
`needs_review`, `failed_retryable`, `failed_terminal`, `policy_denied`,
`superseded`); canonical
`../specs/canonical-product-definition/09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md:98`
gives a **different seven** (`waiting`, `running`, `partial`,
`retryable_failure`, `permanent_failure`, `policy_denied`, `complete`). **WP-7
takes the canonical seven**, on the same ruling section 12 already makes for the
proposal states — canonical governs where the two disagree — and because `D-19`
ratified that document. **Neither is mapped onto `JobState`**, which is four
because four is what a worker needs: a job says whether a worker holds work and a
processing state says how far the pipeline got, and `partial` and `policy_denied`
have no job meaning at all. Implementing both vocabularies would give one fact two
names and no way to tell which a stored row meant. The instrument the ruling came
from is the canonical product definition; `domain/capture/pipeline.py` records the
same choice at the code.

### WP-8 — review cases, promotion, and conversation events

**Objective.** Give consequential proposals a governed path to canonical, and
give an explicit Conversation Log its skeletal event.

Corresponds to Quick Capture stage `QC-04`.

**In scope.** Review case model binding exact capture, version, proposal, spans,
target object, and expected version; all seven dispositions, five reachable in
this build; promotion receipts;
`domain/conversation/` skeletal, proposed, accepted, superseded states;
conversation participants including unresolved mention text; capture context
links with deterministic, user-confirmed, and proposed authority states;
re-validation of accepted downstream records when a source edit materially
changes a cited span.

**Out of scope.** Identity merge and split. External actions of any kind.
Notifications. Pulse or Today eligibility. Automatic promotion of anything.

**Acceptance criteria mapped to tests.**

- `QC-AC-020` — commitments, decisions, amounts, critical dates, and sensitive
  relationship conclusions cannot reach canonical without a review disposition.
  Prove the closed consequential-class policy exhaustively, then call the only
  canonical promotion writer without a decision and require denial before it
  reads persistence. The writer accepts only a proposal identifier, not a
  duplicated consequential-class input, so its no-decision guard is global.
- `QC-AC-021` — no code path executes an external action from an accepted
  record. An architecture test, not a runtime one.
- `QC-AC-022` — rejected and corrected proposals retain lineage; nothing is
  deleted.
- ADR-003 clause 8 — editing a capture whose span supports an accepted record
  moves that record to `revalidation_required` rather than silently rewriting or
  silently keeping it.

### WP-9 — relationship identity and read-only profiles

**Objective.** Person and organisation identity, unresolved mentions, duplicate
review, and source-backed profiles and timelines — over synthetic fixtures only.

Corresponds to Relationship Intelligence stage `R1`, restricted.

**The restriction comes from the specification, not from this plan.** `R1` as
specified reads contacts, email, and calendar. Section 38 item 5 of that
specification makes "personal-source access separately authorized by exact
connector, account, and scope" a precondition of any implementation, and section
33 lists "personal-source contracts approved" among R1's own prerequisites. No
such authorization exists, and `AGENTS.md` section 5 prohibits live email,
calendar, and contacts. Because the specification is `my-pa`-native rather than
an outside proposal, those gates are product intent and bind harder, not softer.

WP-9 therefore builds the identity and read-model layer against a **fixture
personal-source provider**, exactly as WP-2 built the read-only fixture source
provider. When the operator authorizes a real connector, it implements the same
port. Until then nothing in WP-9 touches personal data, and the package makes no
claim that it has.

**In scope.** `domain/relationship/` — person, organisation, identity
observation, alias, affiliation, unresolved mention; the duplicate-candidate
model with explicit candidate sets; profile and timeline read models assembled
from observations with coverage and freshness disclosure; a fixture
personal-source provider behind a read-only port with the same containment
conformance the file provider passes.

**Out of scope.** Live contacts, email, or calendar. Automatic identity merge.
Relationship scores. Sensitive-trait inference. Public research. Commitments and
briefings (they depend on WP-8 and on a model boundary). Pulse. Any frontend.

**Acceptance criteria mapped to tests.**

- Identity merge is impossible without a governed review disposition. Prove by
  attempting a direct merge and requiring denial.
- A profile discloses coverage and freshness for its exact observation set and
  never implies completeness. An absent observation is `unavailable`, never
  empty.
- Specification invariant 6.4 holds structurally: no composite relationship
  score field exists anywhere in the schema or contracts, no protected- or
  sensitive-trait field exists at all, and every permitted indicator carries its
  calculation basis and time window. A static test, so none of it can be added
  quietly.
- Specification invariant 6.1 holds: a contact-row observation cannot become a
  canonical person without a governed resolution, and identity merge is
  reversible and review-required.
- Specification invariant 6.3 holds: source observation, accepted assertion,
  user-authored private note, model inference, unresolved claim, contradiction,
  and stale assertion are distinguishable in the contract, not only in the UI.
  Private observations are the ADR-003 authority class, not a new one.
- The fixture personal-source provider passes the same containment and
  read-only conformance suite as the file provider, including the three exploit
  classes WP-2 closed.

### Mapping onto the canonical object model

`D-19` supersedes `D-17`: the canonical product direction is ratified as of
2026-08-02. Nothing above builds toward the canonical model beyond what the
operator promoted, because ratification granted no implementation authority
(`implementation_authority: NOT_GRANTED`) and the canonical roadmap's own first
step is to finish WP-4 and WP-5. No abstraction is created for it; this table is
documentation, not a design.

**This table was re-derived on 2026-08-02 and most of it was wrong.** It was
originally written against `my-pa vNext`. When ratification superseded that
document, the first version of this change relabelled the column from "vNext
object" to "Canonical object" and left every target unchanged — which assumed a
mapping stays valid when the document it maps onto is replaced. Independent
review caught it. The targets below are now derived from
[`../specs/canonical-product-definition/09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md`](../specs/canonical-product-definition/09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md),
sections *Definitions*, *Supporting records*, and *State patterns*, with two
exceptions stated where they occur. `09` lists `SourceSpan` and `SourceRegion` as
bare names without definitions, so the basis for choosing between them is
[`10_SOURCE_AUTHORITY_AND_PROVENANCE_MODEL.md`](../specs/canonical-product-definition/10_SOURCE_AUTHORITY_AND_PROVENANCE_MODEL.md)
sections *Text spans* and *Page regions*. `Affiliation` is in that same bare-name
list, and the name occurs exactly once in the whole package — nowhere else, and
under no definition — so its row claims name-identity and nothing more, and says
so.

A name appearing in `09`'s *Supporting records* list is **not** on its own a
derivation. That list is bare names with no definitions, and a second draft of
this table used one of them, `ContextLink`, as a mapping target on that basis
alone. It was removed. Two rows below do still map onto names from that list,
`SourceSpan` and `Affiliation`, and neither is offered as a derivation: each
discloses in its note that `09` does not define the name, and states what its row
actually rests on instead. Every other target below is a name `09` defines under
*Definitions*. Where a target rests on a definition, the note says what the
definition is.

The result is better news than the old table carried. The ratified model uses
this repository's own names for most of these objects, so the majority of rows
are identity rather than translation, and the "foreseeable rework" the previous
draft warned about largely does not exist. One row was actively misleading and
is corrected.

| Built here | Canonical object | Note |
|---|---|---|
| Capture, CaptureVersion (WP-6) | `Capture`, `CaptureVersion` | **Identity.** Defined under those exact names. `Capture` is a "product-owned Source envelope created through explicit authoring"; `CaptureVersion` is the immutable committed text and hash, and drafts are not versions until Save — which is ADR-003's shape |
| EvidenceSpan (WP-7) | `SourceSpan` | Both names appear in `09`'s *Supporting records* without definitions. `10` supplies the distinction: *Text spans* are UTF-8 code-point offsets under a versioned scheme with a quote hash, *Page regions* are a coordinate system with polygon or bounding box and a transcription candidate. WP-7 handles text, so `SourceSpan` |
| ExtractionProposal (WP-7) | `Proposal`, supporting an `Assertion` | The ratified model keeps **both** as distinct objects: `Proposal` is "candidate record/link/classification/transition before promotion", `Assertion` is the structured claim carrying authority state. See the note below |
| ReviewCase (WP-8) | `ReviewCase` | **Identity**, including the spelling |
| Promotion receipt (WP-8) | `Receipt` | **Identity.** "Immutable evidence of source acceptance or transition under exact identity/policy/authority/time" |
| Conversation (WP-8) | `Conversation` | **Identity.** A specialized `Interaction`/`Event` aggregate, not a generic Event. `Interaction` is the *supertype* — "meaningful exchange/contact", of which `Conversation` and `Meeting` are the specialized forms — and neither the supertype nor the `Meeting` sibling is built here |
| Person, Organization (WP-9) | `Person`, `Organization` | **Identity.** The previous draft mapped these to `Entity`, generalised across person, organisation, project, location, topic and document. **`Entity` does not exist in the ratified model** — `Person` and `Organization` are first-class, and that claim came from the superseded document |
| Affiliation, project association (WP-9) | `Affiliation`; project association has no distinct target | `Affiliation` is **name-identity only**, and rests on weaker footing than the rows above: `09` carries it in the same *Supporting records* line of bare names as `SourceSpan`, without definitions, and the name occurs nowhere else in the package. So this row discloses, as the `SourceSpan` row does, that its target is undefined in `09` rather than claiming a definition it does not have — what the name matches is a concept `09` does define elsewhere, `Person` carrying "aliases, affiliations" and `Organization` carrying "temporal affiliations and project relationships". Project association is *not* a separate object in the ratified model for that same second reason: `Organization` is defined as carrying "temporal affiliations and project relationships" directly. An earlier draft of this row named `ContextLink` — which exists only as a bare name in *Supporting records*, is defined nowhere, and was asserted rather than derived. Removed for the same reason `Entity` was. `Relationship` is a separate first-class object, the time and context-aware association domain explicitly "not a score", and is broader than what WP-9 builds |
| — | `Situation`, `Frame`, `Trace` | Still not built by any package here. The reason has changed: ratification satisfied the condition this row used to name, so what defers them now is that they are canonical stage `R1` scope, arriving after `R0` — which is WP-4 and WP-5 — and they carry no implementation authority |

The one place to be careful is still the proposal-to-accepted lifecycle, but not
for the reason the previous draft gave. It claimed a single Assertion carries a
trust state through "Confirmed, Strongly Supported, Probable, Possible,
Unverified, Contradicted, Stale, and Unknown", and told WP-7 to adopt that
ladder. **None of those values appear in the ratified model.** The ratified state
sets are:

- `Proposal`: `proposed`, `needs_review`, `accepted`, `corrected_accepted`,
  `rejected`, `deferred`, `unresolved`, `superseded`, `invalidated`;
- `Assertion`: `proposed`, `accepted`, `contradicted`, `stale`, `superseded`,
  `withdrawn`, `revalidation_required`.

The underlying guidance survives, because `Assertion` spans `proposed` through
`accepted` in one object: modelling a proposal and its accepted record as two
unrelated tables is still the rework to avoid. What changes is the vocabulary.
**WP-7 must take its state values from the two sets above, not from the ladder
the previous draft named**, and it should expect to carry a `Proposal` state and
an `Assertion` state rather than one blended trust score.

### Method for every package above

Unchanged from section 7. One branch, one pull request, squash-merged,
implemented by a delegated agent with disjoint file ownership, reviewed at exact
head by a separate agent that did not author it, with every test proven
non-vacuous by planting the violation and watching it go red.

## 13. The scope promotion, and the two instruments that made it

Section 5 said promoting the deferred workstreams "takes an explicit operator
reprioritisation of the objective under `AGENTS.md` section 3, not an
implementation choice, and not a specification amendment alone." On 2026-08-01
the operator issued that reprioritisation, naming two features …29 tokens truncated…1683 lines to 1780**. Nothing was fabricated; every one had rotted before it shipped. This is the citation-integrity class this campaign has recorded five times, now inside the register itself, and it is *structurally* guaranteed: a line-number citation into the file a commit edits cannot survive that commit. Fixing the eight numbers would have left the mechanism intact and the next package would repeat it. **The rule is therefore about form, not about arithmetic**: within this file, cite the section heading or the register row ID; outside it, cite `file:line` and check it at head. **Scope, stated because the first statement of it understated it**: that correction edited **five** register rows — `D-73`, `D-74`, `D-75`, `D-76` and `D-78` — not the one `D-78` its summary named. **And the rule did not hold**: the same commit gave `D-85` a bare `:NNN` for an external spec, in a row naming no file, so it pointed at this plan; four more sat in `D-75` and four in section 12's WP-6 criterion bullets. Prose was not enough, and the rule is now a control — `../../tests/architecture/test_citations_resolve_at_head.py` reads every citation in repository-authored `.md` and `.py`, requires each cited path to name exactly one file and each cited line to exist in it, and requires a bare `:NNN` to have a path in its own block, which is the rule this row wrote and the one it broke. A whole-repository sweep of every citation this package added found **154 checked across four locations, 12 defective in six classes** — one wrong *file* (`D-78`, corrected here), one ambiguous shorthand in the pull-request body, four stale intra-file line numbers, one body-prose citation six lines off the sentence it quotes verbatim, one "in the same sentence" claim about two lines seventeen apart, and one path containing a literal ellipsis. **The six `capture.create` shorthand citations `D-68` rests on are all correct**, and resolve in `../specs/canonical-product-definition/`. **Amended by WP-6's third correction cycle, because the rule stopped one step short and the guard says so.** A line number that *resolves* is not a line number that is *right*: `../../tests/architecture/test_citations_resolve_at_head.py` decides that a citation lands, never that it lands on what the sentence claims about it, so a pointer into a file the same change lengthens rots silently while every rule in that guard stays green. **Measured at `862846e` over the class the reviewer named — every citation into a file this branch modifies — ten pointers had moved, across five files, of which the review named three; three of the ten were written by this branch and were already wrong when they shipped, one of them inside a guard module.** The form rule therefore reaches outside this file as well as inside it: **cite a function, a test, or a constant by name whenever the target is a file the change touches**, because a symbol does not move when a file grows, and reserve `file:line` for a file the change leaves alone. One pointer is deliberately left as a line number — `commands.py:230-238` in the `D-37` row — because that row is quoting the citation it is correcting, and rewriting a quotation to be accurate destroys the record it exists to keep | Standing form rule, now covering the symbol form as well as the bare-line form. Invalidated by a mechanism that makes intra-file line numbers survive an edit to the same file |
| D-84 | The save transaction's atomicity is an **open spec-versus-`D-34` conflict**, not a plan error. `D-34` stands and the implementation is unchanged | `D-75` recorded that this plan's "capture, version, receipt, **redacted audit**, and job commit together or not at all" was **false**. The sentence is faithfully copied from the spec package, which states it in five places — `../specs/quick-capture/05_END_TO_END_WORKFLOW_INVENTORY.md:20` ("Server transaction persists capture, version, receipt, audit event, and processing job/outbox"), `../specs/quick-capture/11_EXTRACTION_AND_PROPOSAL_PIPELINE.md:33` (which is where the word *redacted* comes from), `../specs/quick-capture/02_COMPREHENSIVE_IMPLEMENTATION_SPECIFICATION.md:260`, `../specs/quick-capture/17_TECHNICAL_ARCHITECTURE_RECOMMENDATION.md:124`, and `../specs/canonical-product-definition/12_MVP_DEFINITION.md:115`. **The spec package also contradicts itself**: `../specs/quick-capture/13_OFFLINE_AND_SYNCHRONIZATION_SPECIFICATION.md:106` and `20_TESTING_EVALUATION_AND_ACCEPTANCE.md:47` both list the atomic set **without** the audit, and `20_…` is the file `D-75` names as governing. The repository sides with the two that omit it, on `D-34`'s ground that a security-relevant decision must outlive the work it authorized. **So the correction is right and its label was wrong**, and the same reasoning that produced `D-82` produces this: the plan was restating an instrument, not misreading one | Open. Invalidated by a spec revision resolving its own contradiction, or by a decision overturning `D-34` |
| D-85 | The `QC-AC-034` bullet is a **correct test filed under the wrong criterion**, and spec `QC-AC-034` is **not exercisable in WP-6** | `D-75` reviewed six of this plan's criterion statements, found five wrong or narrowed, and pronounced `QC-AC-034` **"TRUE — keep exactly as worded"**. It did not compare the bullet to the criterion it names. Spec `../specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md:208` reads "`QC-AC-034`: Processing failure never loses the source capture" — a failure *after* the save, requiring the capture to **survive**, corroborated by `../specs/quick-capture/05_END_TO_END_WORKFLOW_INVENTORY.md:124`. The bullet describes a *save-time* audit or receipt failure requiring **no capture to exist afterwards** — the opposite direction, about a different failure. The bullet's requirement is real and has its own spec ground at `../specs/quick-capture/11_EXTRACTION_AND_PROPOSAL_PIPELINE.md:37`; what it is not is `QC-AC-034`. **Spec `QC-AC-034` cannot be proven here at all**: nothing consumes `knowledge.capture_jobs` until WP-7, so no processing stage exists whose failure could lose a capture. The test is kept, the label is disclosed as wrong, and the criterion is carried to the package that builds the worker. **The finding that matters beyond this row is that a verdict of "correct" received no sweep** — five statements were checked against the spec and the sixth was checked against itself | **Closed by WP-7**, which is the package that consumes the capture outbox: `infrastructure/jobs/capture_pipeline.py` is the processing stage whose failure could lose a capture, and `tests/jobs/test_capture_pipeline_recovery.py` proves it does not — the failure injected inside `P-15`'s transaction after the proposal `INSERT` and before the commit, with the version's content and digest re-read and compared afterwards, a clean re-run producing proposals as the control, and `UPDATE` and `DELETE` on the version both refused with `SQLSTATE 23001`, which is what makes "never loses" a property of the schema rather than of the code that happened to be running. Invalidated by a package that removes the append-only trigger |
| D-86 | The six **single-value-embedding** constraints are **ledger, not blocker**, and the guard must state that it does not cover them | Six constraints embed a single enum *value* rather than a closed set — one on `audit_events` and three on `extractions`, plus the `jobs` and `capture_jobs` lease checks. **WP-7 added a seventh and named it rather than letting it pass**: `capture_proposals`' `(state = 'invalidated') = (quarantine_reason IS NOT NULL)` embeds the single value `'invalidated'`, and it is the honest posture — the alternative was a proposal that records evidence failed without recording how, or a reason attached to a state that was not refused. It is implemented in the guard's ledger and named in its docstring, which is what this row's second half requires. Note that `capture_spans.offset_basis` is **not** an eighth: `D-97` writes `'unicode_code_point_v1'` as a literal inside the frozen revision precisely so that no new site of this class is created. The reviewer measured the gap rather than inferring it: renaming `AuditOutcome.DENIED` moves the DDL an already-merged revision emits and `../../tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py` **stays green**, so this is the same family as `D-69` and `D-81`. It is judged **materially weaker**, and the asymmetry is the whole reason: adding an enum member is **silent**, whereas renaming a value **breaks loudly** at every consumer of that string — the constant, the persistence mapping, every fixture, every assertion. `D-81`'s hazard is silent drift; this one announces itself. **The second half is not optional and is implemented, not promised**: that guard's docstring now states in terms that this class is outside its coverage, names all six sites, and says what would close it. A control described as closing a class it does not close is the overclaim this campaign has caught repeatedly — most recently `D-44`'s citation guard, whose universe admitted root directories but not root files while the document asserted every cited path was checked | Recorded as ledger; the guard names its own boundary. Invalidated by evidence that a value rename can drift silently — at which point it becomes `D-81`'s class and blocks |
| D-87 | The FAST budget is **accepted at ~38s of 60s**, and the growth model is **measured rather than feared** | The worry was that one package consumed a third of the remaining budget. Measured at `d2494cb`, the measurement says otherwise about *why*: **collection is 0.75s** of the run, so it is not the bottleneck; **no module is expensive**, the slowest being `../../tests/architecture/test_open_decision_counts.py` at **0.08s**, with the top twelve modules summing under 0.4s and **6756 of the durations each under 0.005s**. FAST is therefore **≈15.7 ms per test and roughly linear in test count** (base 2195 tests / 31.27s = 14.2 ms; head 2354 / 36.90s = 15.7 ms). **The useful consequence**: the ~22s of headroom is worth roughly **1400 more FAST tests** (*superseded 2026-08-03 by `D-100`, which re-measured this row's own model rather than restating it: the ≈15.7 ms per test below is replaced by a measured **≈42 ms**, and **≈1400 is wrong twice over** — once on that model, and once on the **60s** denominator it is drawn against while this same row names **55s** as the trigger. **The number a package plans against is ≈235**, and it re-measures before spending any of it*), not "a third of five packages", and the cartesian term everyone fears — `len(Capability) × len(Purpose)`, now 12 × 9 = 108 — costs about **1.7s** even if WP-7 and WP-8 take it to 18 × 13 = 234. There is no `slow`-test problem to solve; there is a test-count budget and it is generous. The next package **re-measures before adding capabilities**, and if a package would take FAST past **55s** the cartesian policy and parity matrices move off the FAST tier — **coverage is not trimmed to fit the budget** (`../../AGENTS.md` section 7: "Do not omit a critical contract merely to meet the target. Adjust the target from measured evidence rather than silently reducing coverage.") | Accepted, with a measured growth model rather than a worry. Invalidated by a package introducing a FAST test with a materially different cost profile, which the re-measurement requirement exists to catch — **and that condition has since fired**: WP-7 did, the re-measurement caught it, and this row's **arithmetic** is superseded by `D-100` while its conclusion survives. Preserved, not deleted |
| D-88 | The `AS head` guard's **alias pattern is widened to the spellings PostgreSQL actually accepts**, rather than disclosed as a gap | `_ALIAS` in `../../tests/architecture/test_no_stored_revision_is_labelled_head.py` matched only `AS <word>`, so two further spellings of the one thing that rule forbids each produced a column **literally named `head`** which it passed: `AS "head"`, where the quotes are not `\w`, and a **bare implicit** `head`, which has no `AS` to key on. **Measured, not argued**: each spelling was planted *in place* at `../../ops/runbooks/postgres-operations.md:187` against the unwidened rule and the rule reported **11 passed**, while the already-caught `AS head` planted at that same site reddened — so the site was live and the hole was demonstrated rather than asserted. **No live instance existed** — every revision-reading query in the corpus aliases `revision` — so this was a **future-miss, not a defect**. **Closed rather than disclosed, which is where this departs from `D-86`**: that row disclosed a gap because closing it meant a second derivation of a different class, whereas this is a widening of the pattern the guard already owns. The guard's whole reason to exist is that this class escaped **three consecutive human sweeps**, so a known hole in it is not something to carry. **The implicit branch is positional, not an optional `AS`** — the reviewer's suggested shape, taken as a suggestion rather than a measurement: making the keyword optional matches every word in the region, and the regions are not all SQL, since `database_revisions` in `../../apps/cli/health.py` qualifies as a revision-reading query while being English prose (cited by name rather than by line for the reason `D-83` gives; the package carrying this correction edits that file). Swept over all **14805** regions the rule reads, an optional-`AS` branch finds one such word — `head` in the prose of `../../tests/schema/test_head_round_trip.py`, a region one `SELECT` away from being read — and the positional branch finds **none** | Closed in WP-6. The widened pattern is pinned by five further cases in the guard's own table, and its one residual over-reach — a *table* aliased `head`, which names no column — is stated in the docstring and asserted rather than left to be found. Invalidated by a PostgreSQL alias form the widened pattern still does not reach |
| D-89 | WP-7's criteria are taken at **spec** strength. There are **six**, and **five** of this plan's statements were wrong | The binding text of each criterion is `../specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md`, not this plan's paraphrase; the WP-7 section is corrected in place. `QC-AC-050` **narrowed, load-bearing**: `20:221` says "**Exact** original text is searchable" and the plan dropped "Exact"; measured, `to_tsvector('english','…running…')` stores `run` so `run` matches text that never contains it, and `to_tsvector('english','a the of and')` is **empty**, so a stop-word-only capture is saved, valid, and unfindable **with no exception anywhere**. `QC-AC-011` **narrowed twice and its stated proof is impossible**: `20:190` says "exact **validated**" and covers "proposal/**accepted derived record**", the plan says "at least one" and drops the accepted half; and "prove by mutating a version and re-running" **cannot run** because merged `1a4c9e77b2d5` installs `capture_versions_are_append_only` (`BEFORE UPDATE OR DELETE`, `restrict_violation`), measured present at head — the proof is persistence-layer span injection instead. The accepted-record half is **half-discharged here** and re-proved by WP-8, disclosed rather than absorbed. `QC-AC-042` **narrowed**: `20:215` says "broaden retrieval/**disclosure**" and the plan says "widened scope"; disclosure is a first-class object here (`application/disclosure.py`, canonical `09:130`), so captured text must also not alter coverage, limitations, or freshness. The corpus's synthetic requirement is grounded in `QC-AC-073` (`20:239`) and `../../AGENTS.md` section 5, **not** in `QC-AC-042`. `QC-AC-002` **proof insufficient**: "no proposal row in the committed set" is membership and the criterion is ordering; WP-6 did not discharge it and WP-7 owes the indexing half. `QC-AC-035` **true**, with the "or accepted objects" clause disclosed as **vacuous** here. `QC-AC-034` is the **sixth**, carried by `D-85`. Six stage deltas are admitted into the in-scope sentence, `P-13` is ruled **in scope** and discharged structurally, and the out-of-scope **reason** is corrected — the exclusion survives, but "model-assisted" is absent from `11` for `P-06`, `P-07` and `P-12`, and `P-07` explicitly permits deterministic inputs. This is the `D-75` finding reproduced: the plan is a paraphrase and the spec is the instrument, and six of the last nine packages found a plan claim measurement contradicted | Adopted and corrected in place by WP-7. Invalidated by a spec revision |
| D-90 | Exact capture search is a **second** FTS plane over `capture_versions.content` using `simple`, not `english`, with exact-substring confirmation | One `capture_text_in_scope()` predicate **and** one statement builder parameterised over a `SearchPlane` — the shape `D-76`/`D-77` established for `JobPlane`, so the page and the totals agree **by construction** rather than by comparison. That control is the point: `coverage_for` and `match_statement` on the extraction plane were *asserted equal* for six review rounds and were false for two of six conditions. **Candidate (a) is refused** — routing captures through `knowledge.extractions` needs an `enrollment_id`, which is `NOT NULL` with a foreign key on a table merged revision `8b3f5c17d904` creates, and that is `D-76` on the identical column shape. **Why `simple`**: measured, it keeps stop words, does not stem, and matches `RFI-0421` and `$12,500.00` as adjacent lexemes; `english` fails `QC-AC-050` in two measured ways (`D-89`). **The cost is disclosed, not smoothed over**: no stemming, so a search for `meetings` will not find `meeting`. That is published as a `Limitation` through the disclosure envelope — `capture_search_matches_words_as_written` — rather than left for a caller to discover. Plus a larger index and a second predicate. **Two defects this decision's own implementation carried, both found after it was adopted, and both the same class — the confirmation and the predicate disagreeing about what the query text means**. (i) The confirmation compared bytes while the predicate compares lowercased lexemes, so a query for `buyout` silently removed a capture whose text says `Buyout`; both sides are now case-folded. (ii) The eligibility test read the **raw** query text while `websearch_to_tsquery` strips a double quote as syntax and a trailing full stop as nothing, so `"buyout"` and `buyout.` were confirmed against needles containing them and were removed after the index had matched. Measured over query forms generated from PostgreSQL's own character classification, **328 of 402** index-matching cells were dropped; the fix reads both the needle and the decision to use it from the server, and the class is guarded by a generated matrix rather than by a third list of cases. Fixing (i) and leaving (ii) open in the same cycle is why the guard is now mechanical | Adopted and implemented in WP-7. Invalidated by a measured need for stemming on capture text, which would need its own plane and its own disclosure rather than a configuration change to this one |
| D-91 | `capture.search` is the **thirteenth** `Capability`; reuse `Purpose.CAPTURE_REVIEW`; **write the freeze before the member** | `knowledge.search` does not serve both planes: `domain/identity/purpose.py` already argues that a single grant spanning two scopes is the escalation the purpose split exists to refuse, and a `knowledge.read` request returning raw user-authored capture text is that escalation by another route. **Add no `Purpose` member** — a new purpose costs another `ALTER` and would map to exactly one capability. The freeze is written **first**, not after the guard reddens: WP-7's revision carries a 13-value `_CAPABILITIES_AT_THIS_REVISION`, a 12-value before-literal, a `_restate()` in `1a4c9e77b2d5`'s shape, `_FROZEN` plus `_historical_wp7_tables()` for its own new tables, and the new callable's name in `_EMISSION_CALLABLES`. **Measured, and this is why the row exists**: on a disposable database with plants live, the still-derived `quarantine_reason_is_known` gained `'zz_wp7_probe'` and `jobs.state_is_known` gained a fifth value, while the frozen `capability_is_known` stayed at **12** with 13 members in code and `capture_job_state_is_known` stayed at **4** with 5. The freeze works — **which is exactly why adding `capture.search` without the `ALTER` passes every test and is refused in the field on the first audited search**, because every test builds its database from scratch. Green tests would not catch it. **Extend no other frozen enum**: `JobState`, `ErrorCode` and `QuarantineReason` each cost a still-derived *and* a frozen site, so processing state and proposal-quarantine reasons take **new** enums on **new** tables where `D-48`'s carve-out applies | Adopted and implemented in WP-7. Invalidated by a canonical revision renaming the capability, which is a `v1` break (`O-01`) |
| D-92 | `D-81`'s site count is corrected to **10 sites in 10 sources**, and plan section 16's classification row does **not** extend the `Classification` enum | Two corrections to inherited claims, both found by deriving the list from the code rather than restating it. **First**: `D-81` and the WP-7 brief both said "10 sites in **9** sources". The tenth source is **`my_pa.contracts.v1.errors.ErrorCode`**, at `jobs.last_error_code_is_a_public_error_code`, which the nine-name list omits. This is the same undercount `D-81`'s own text warns about — "the independent reviewer's list named nine sites and eight sources, both numbers were low" — repeated once more, one source higher, inside the row that warns about it. The list is **derived, not typed**: it is read out of `tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py`'s `ALLOWED` ledger rather than transcribed, which is what stops the count going stale a fourth time. **Second**: the classification row in section 16 assigns the **record types** `CaptureClassification`/`CaptureDomainAssignment` to WP-7. It does **not** assign `my_pa.domain.common.classification.Classification`, which is a **data-sensitivity** enum (`private_local`, `restricted_local`, `synthetic_test`) and a different subject with a similar name. Reading the row as an enum extension would have triggered a freeze nothing needed | Adopted in WP-7. Invalidated by a further derivation returning a different count, which must then correct this row rather than replace it silently |
| D-93 | `CaptureEntityMention` is **built, restricted to the deterministic subset**, and section 16's state ladder is misattributed and corrected | The conflict is real and this plan contains both sides: the WP-7 section excludes `P-06` named-entity extraction, while section 16 assigns `CaptureEntityMention` — the object `P-06` produces — to WP-7. Resolved by building the deterministic subset rather than by deferring the record type. **In**: document and project identifiers, and URLs, all already produced by `P-05` (`11:75-77`), each carrying a span and each always **`unresolved`**. **Out**: people and organisations, which need an alias table that does not exist; locations and topics, which have no deterministic source at all. `resolution_state_is_known` is frozen at the single value `('unresolved')` — the `D-78` and `QuarantineReviewState` one-value precedent this campaign has already accepted. **Why build rather than defer**: `D-74` defers a record type that is **permanently empty**, and this one is populatable on day one; and WP-8's `ConversationParticipant` binds an unresolved mention to a span (`09_LOGICAL_DATA_MODEL.md:236-237`), so deferring means building mention-to-span binding **twice**, which is the `D-41` objection in the direction that actually applies. **Correction to section 16's row**: it says the unresolved/candidate/resolved ladder is "the same shape as the `Proposal` states section 12 already directs WP-7 to use". **It is not.** That ladder is canonical `09:96`'s **`Identity`** state set (`resolved`, `candidate`, `unresolved`, `merge_proposed`, `split_proposed`, `superseded`); `09:94`'s `Proposal` set contains neither `candidate` nor `resolved`. The sentence is corrected; the row's assignment survives | Adopted and implemented in WP-7. Invalidated by an alias table arriving, which widens the subset rather than overturning it |
| D-94 | **One package.** `CaptureDomainAssignment` is deferred to WP-8; WP-7 is not split | The candidate boundary — pipeline, proposals and spans against exact search — **is not a partition**. `QC-AC-050` and `QC-AC-002` both straddle it: a search-only package can prove "searchable" but **not** "independently of enrichment success", because proving that needs an enrichment that **fails**, which is the other package's machinery. Shipping it split would therefore **narrow `QC-AC-050`** to its first clause, which is `D-52`'s exact refusal shape. `D-57` split WP-5 only because the partition was clean — three criteria against none — and this is not that. `D-74`'s README argument bites too: `capture.search` is a capability and `tests/architecture/test_readme_state_claims.py` derives README's readiness from `_HANDLERS`, so a package that named it without wiring it would falsify README between two merges. **`P-16` sits outside `P-15`'s transaction and must** — `11:191` "immediately" and `QC-AC-050` "independently of enrichment success" together require it — so the `D-41` "build that transaction twice" objection does **not** apply and is not used. **`D-74`'s other test fires instead**: `CaptureDomainAssignment` is **unpopulatable** in WP-7, its only deterministic input being a launch-context link that WP-8 owns, and a permanently-empty table is barred by `../../AGENTS.md` section 2. **The boundary between the two record types, which section 16 says outright it does not answer**: `CaptureClassification` is **evidence-bound and about the text** — one row per `(version, scheme, scheme_version, label)`, each carrying its deterministic rule, that rule's version, and **at least one span**; `CaptureDomainAssignment` is **interpretation and about placement** — one row per `(version, domain, assignment_version)`, superseded rather than updated, carrying **no span**, because it is a claim about the whole capture. The test that makes them two records: a classification can be *cited*; a domain assignment cannot, because no phrase means "this belongs to the Riverside project" | Adopted in WP-7. Invalidated by a design that leaves **no** criterion half-proven under a split |
| D-95 | **`O-19` is closed.** The processing-policy slot already exists; WP-7 adds no member | `O-19` asked whether "save without AI processing" appears in MVP, and ruled that it is a stored processing-policy value rather than a UI toggle, so it "must exist in the schema or not at all". **It exists**: `knowledge.capture_versions.processing_policy` is a real column, backed by `ProcessingPolicy` with one member `LOCAL_ONLY`, and `processing_policy_is_known` is frozen at `('local_only')` in `1a4c9e77b2d5`. WP-6 built it, so the "or not at all" branch is already closed. WP-7 adds **no** member: `P00-OD-006` is open and there is no model in the system, so every capture is already processed without AI and a `no_ai` member would change no behaviour and be distinguishable from `local_only` by nothing — which `../../AGENTS.md` section 2 bars. What WP-7 **does** owe is `P-01`'s dropped requirement (`11:46`): **load the processing-policy snapshot recorded at save and branch on it**, so the policy that governs is the one recorded when the capture was written rather than the one current at processing time, and the package that opens the model boundary adds its route by a forward `ALTER` and finds the branch already there. Implemented as an **allowlist** rather than an equality test, because an `is not` comparison against a single-member enum is statically constant and a build that grew a second policy would process it through a branch nobody wrote; a policy outside the allowlist stops at `P-01` as `policy_denied` | Closed in WP-7. Invalidated by a canonical revision defining a second policy value |
| D-96 | **No twelfth `v1` error code.** `D-82` stands undisturbed | `contracts/v1/errors.py` stays closed at **eleven**. WP-7 does not need a twelfth: the pipeline's idempotency is *stage replay returning prior output* (`11:212`), which is not a client-facing error at all, and `D-82`'s standing disposition — `conflict` with `safe_details: ["idempotency_key"]` — already serves the save path and WP-6 shipped it. **The cost is now measured rather than argued.** A twelfth member moves **two** already-merged constraint texts in opposite directions: `jobs.last_error_code_is_a_public_error_code` is **still derived** in `7e5a1fb93d62` and would move, reddening `test_no_revision_derives_a_closed_set_outside_the_allowlist` and forcing a freeze of a revision WP-7 has no other reason to touch; while `capture_job_error_code_is_a_public_error_code` is **frozen** in `1a4c9e77b2d5` and would *not* move, so head silently stops admitting the new code on the capture plane — the same failure shape `D-91` measured at the capability site. Plus `18_PROPOSED_API_AND_CONTRACT_PACKAGE.md:344`'s generated-client compatibility evidence and an operator-authorized scope change. If a later package wants it, **it needs its own decision row before implementation starts, not at review** | Adopted in WP-7. Invalidated by an operator-authorized `v1` scope change with compatibility evidence |
| D-97 | `unicode_code_point_v1` is written as a **literal inside the frozen revision**, not read from a Python constant, so `D-86`'s ledger gains no new site | `capture_spans.offset_basis` is constrained to the single value `'unicode_code_point_v1'`. Writing that literal in the revision keeps the value where the freeze mechanism already owns it; deriving it from a Python constant would create a **new** single-value-embedding site of exactly the class `D-86` records as its blind spot, and would oblige the guard's docstring to name it. Confirmed against the specification: **`unicode_code_point_v1` is the specification's own name, not this plan's invention** — `../specs/quick-capture/10_SOURCE_AUTHORITY_AND_PROVENANCE_MODEL.md:82`, again at `../specs/quick-capture/09_LOGICAL_DATA_MODEL.md:177`, and in the contract example at `18:293`. The hypothesis that the plan invented it is **refuted** | Adopted and implemented in WP-7. Invalidated by a second offset scheme, at which point the constraint becomes a closed set and takes the freeze mechanism proper |
| D-98 | "Every proposal carries at least one span" is a **`DEFERRABLE INITIALLY DEFERRED` constraint trigger**, not an application invariant | PostgreSQL cannot express a `[1..n]` cardinality across tables declaratively. The alternative — an application invariant plus a `database`-marked test — is "immutability as a property of the code that happens to be running", which `1a4c9e77b2d5`'s own docstring rejects for the same reason; and `QC-AC-011` is the criterion most likely to be violated by a future repair script, which does not run the application. Two triggers, not one: `AFTER INSERT` on `capture_proposals` and `AFTER DELETE` on `capture_proposal_spans`, so the rule cannot be evaded by writing the rows and then removing the link. **The `downgrade base` residue was measured, both directions**: `7e5a1fb93d62` drops the schema with `RESTRICT` and `1a4c9e77b2d5` had to drop its function explicitly, so this revision does too — measured, `downgrade base` leaves **only `public.alembic_version`**, and with the explicit `DROP FUNCTION` removed it fails with `DependentObjectsStillExist`. The revision's docstring says so | Adopted and implemented in WP-7. Invalidated by a measured inability to make the trigger's function reversible, which would need its own row rather than a silent fallback to the application invariant |
| D-99 | The `D-81` guard's blind spots are **disclosed in its own docstring** and **not fixed in WP-7** | Three findings sit outside WP-7's scope and are named rather than absorbed. **(1)** Revision `4b9f0d27ac31` is **structurally invisible** to the guard: it calls `METADATA.create_all(bind)` on `my_pa.infrastructure.migration.control_plane`'s **separate** `MetaData`, never imports `my_pa.infrastructure.persistence.tables`, and holds no `Table` in its namespace, so `test_every_revision_declares_its_emission_readably` `continue`s past it and `_emitted` returns `None` — and `control_plane.py` derives **five** further closed-set constraints from live enums (`RunStatus`, `PhaseStatus`, `TableState`, `QuarantineCode`, `AuditEvent`). This is a larger hole than the documented `D-86` class: not detected-and-allowlisted but structurally unreachable, because `DECLARATION` hard-codes one declaration module. **(2)** The guard's own docstring said "`ALLOWED` is the ten sites in the **three** revisions `D-81` deliberately does not edit" while its data and its own `test_the_allowlist_names_only_revisions_this_package_does_not_edit` both say **two** — a false statement inside the control WP-7 depends on. **(3)** `release_job` has no bounded exponential backoff or jitter against `11:216` — a released job returns to `queued` and is immediately reclaimable — and it is on the **shared** plane, so adding backoff would change enrollment-extraction retry behaviour. **What WP-7 does**: correct (2), and add (1) to the guard's docstring as a **named blind spot**. **What WP-7 does not do**: fix (1) or (3). A control that names its own blind spot beats one that implies totality; widening the guard to a second `MetaData` is its own package with its own review, and (3) is a change to merged behaviour WP-7 has no criterion for | Adopted in WP-7, with (1) and (3) left open and named. Invalidated by a package that widens the guard, which must then delete the disclosure rather than leave it stale. *Corrected 2026-08-08: **that invalidation condition has fired for (1), and this row is corrected rather than left standing.** The guard no longer holds a declaration-module name at all: `_declaration_modules()` discovers them by shape — a module-level `MetaData` plus at least one module-level `Table` bound to it — across a `pkgutil` walk of `my_pa`, so `control_plane` is found, and a third declaration module added tomorrow is covered with no edit to the guard. The blind-spot paragraph is gone from the docstring, as this row required. **(1) is closed and (3) remains open and deferred.** Finding (2) has not recurred: it was a docstring saying "three revisions" where the data said two, WP-7 corrected the word to "two", and the widening now makes three the correct answer again — so the docstring is true, for a different reason than when it was first written. Nothing about (2) is open. What the widening bought is narrower than "fixed" and is stated at that strength in the guard itself: `4b9f0d27ac31`'s five sites moved from **structurally unreachable** to **detected and vocabulary-pinned**, not to frozen. Freezing them means editing a merged revision, which `D-81` exists to avoid. Each allowlist row now records the exact vocabulary its site emits, so a member added to `RunStatus`, `PhaseStatus`, `TableState`, `QuarantineCode` or `AuditEvent` reddens the guard — none of which was true of any of them before. Two further findings came out of the measurement, and both say the hazard was undercounted rather than overcounted: **the independent reviewer's own list of this hole named nine sites and eight sources, and both figures were low** — `quarantine_review_state_is_known` derives from `QuarantineReviewState`, which that list omits, and `jobs.last_error_code_is_a_public_error_code` derives from the public error-code set rather than from a `StrEnum`, so a sweep looking for the declarative enum helper alone never sees it. No count of the allowlist is restated here on purpose; the guard asserts its own size and its own revision set, and a figure copied into this row would rot the way `D-21` describes. No new `D-` identifier is minted — see the identifier-reservation note below this table.* |
| D-100 | **`D-87`'s cost model is invalidated by measurement and replaced, and the replacement is independently recomputed and confirmed. The budget is accepted at 45.05s against a 60s hard limit, 9.95s under the 55s policy trigger that is the number a package plans against; the marginal cost of a FAST test is ≈42 ms, not ≈16 ms** | `D-87` accepted the FAST budget on a model of **≈16 ms per test, roughly linear in count**, and set its own invalidation condition: "a package introducing a FAST test with a materially different cost profile, **which the re-measurement requirement exists to catch**." **The re-measurement caught it, which is the control working rather than failing.** Measured by the orchestrator on one machine in one session, so the two figures are comparable rather than inherited from separate runs: `main` at `c0854b6` **2400 passed / 367 deselected of 2767 collected, 38.51s**; WP-7 at `61c178a` **2557 passed / 395 deselected of 2952 collected, 45.05s**. That is **+157 selected tests for +6.54 s**, and 6.54 s ÷ 157 = **≈41.7 ms per test**, or 41.7 ÷ 16 = about **2.6×** `D-87`'s figure. **Independently recomputed and confirmed, which is what separates a measurement from a claim.** The reviewer re-derived this row end to end, paired, on one machine in one session from a clean export, and reached the same place by a separate path: `main` at `c0854b6` **2400 passed / 367 deselected of 2767 collected, 38.16 s**; WP-7 at `a06bd95` **2557 passed / 395 deselected of 2952 collected, 44.91 s** — **+157 selected tests for +6.75 s**, and 6.75 s ÷ 157 = **≈43.0 ms per test**, 43.0 ÷ 16 = **≈2.69×**. Both universes are stated inline so either can be re-derived; the selected/deselected/collected counts are identical across the two, and the costs agree to within ≈3%. Wall-clock totals are machine- and session-dependent, so **the ratio is the portable figure and the seconds are not**. **Where it did *not* go, measured rather than assumed — and each percentage named to the measurement it comes from, because these are two different attributions and the narrower one sits inside the wider**: the transport-parity cartesian everyone watches grew `12 × 3` → `13 × 3` for **+2 tests and +0.61 s** (module total 66/8.89 s → 68/9.50 s), so the **cartesian term** is 0.61 ÷ 6.54 = **9.3% of the increase** and **≈91% falls outside it**; the whole `tests/contract` tier — which *contains* that cartesian module — grew **+6 tests and +0.92 s**, so **`tests/contract`** is 0.92 ÷ 6.54 = **14.1%** and **≈86% falls outside `tests/contract`**. **The 86% is the `tests/contract` attribution, not the cartesian one**; the reviewer reproduced the `tests/contract` term at **+6 tests / +0.97 s** = 0.97 ÷ 6.75 = 14.4%, ≈86% outside, in their own universe. The residue is 157 − 6 = ~151 new deterministic units for 6.54 − 0.92 = 5.62 s, and 5.62 s ÷ 151 = **≈37 ms** each, none individually slow enough to enter the slowest-twelve list (whose floor is 0.22 s and whose entries are all pre-existing transport tests). **The consequence for the packages that follow, stated against the denominator that binds — the 55 s policy trigger, not the 60 s hard budget**: headroom to **55 s** is 55 − 45.05 = **9.95 s**, and 9.95 ÷ 0.0417 = **≈239 more FAST tests** at the orchestrator's profile; in the reviewer's universe it is 55 − 44.91 = **10.09 s**, and 10.09 ÷ 0.0430 = **≈235**. **A package plans against ≈235**, the lower of the two, and re-measures before it spends any of it. The **60 s** figure is the hard budget and is kept in view rather than deleted, so a reader can see both denominators and which one binds: headroom to 60 s is **14.95 s ≈ 359 tests** (orchestrator) or **15.09 s ≈ 351** (reviewer), against the ≈930 that `D-87`'s ≈16 ms model predicts for that same 60 s. Crossing 55 s does not fail the build — it fires the standing policy below, which is why 55 s is the planning number and 60 s is only the wall. An earlier statement of this row gave the consequence as ≈360 against the 60 s budget while naming 55 s as the trigger in the same passage; the denominator is corrected here and a bare number whose denominator must be inferred is not left standing, since that inference is how the error arose. **`D-87`'s conclusion survives and only its arithmetic is replaced** — no WP-7 work needs re-marking, because every new behavioural test is already `database`-marked and FAST *selection* was unchanged across the correction cycle; and the standing policy is unchanged: a package that would take FAST past **55 s** moves the cartesian matrices and parity matrices off the FAST tier, and **coverage is not trimmed to fit** (`../../AGENTS.md` section 7). **The next package re-measures on its own machine in its own session before adding FAST tests, and compares against a base it measured itself** — comparing two numbers produced by different agents at different times is what made this figure look like drift until it was measured properly. **`D-87`'s own forward projection is superseded here rather than rewritten in place, because it carries the identical defect this row was corrected for**. **That defect was `MINOR-7`, raised as a MINOR finding against an already-approved head at `a06bd95` and fixed in cycle rather than ledgered — not a BLOCK. The only BLOCK this package has seen was `QC-AC-050` at `4fe30e8`, and it was unrelated. An earlier statement of this sentence called it "the identical defect this row was BLOCKed for", which was false, was written by the orchestrator, and is the stale-claim class landing inside the row that exists to correct a number**: `D-87` reads "the ~22 s of headroom is worth roughly **1400** more FAST tests" while naming **55 s** in the same row as the trigger for moving the matrices off FAST — the 60 s denominator again, against a 55 s policy. Both of `D-87`'s figures are superseded: **≈1400 is wrong twice over**, once on the ≈16 ms model this row replaces and once on the 60 s denominator, and the number a package plans against is **≈235** above. The original row's wording is left verbatim per this campaign's practice of preserving superseded decisions rather than rewriting their history, and `D-87` now carries a dated forward pointer to this row in the `D-78`/`D-81` shape — added beside the ≈1400, not substituted for it — so a reader who never reaches `D-100` is not left planning against a number that is wrong twice over; **the correction is that the defect was a class of two, not a case of one, and the second instance was found by the worker that fixed the first** | Accepted for WP-7 and carried forward. Invalidated by a further re-measurement returning a materially different marginal cost, which must then correct this row's arithmetic rather than restate its conclusion |
| D-101 | **Resolve WP-8's six overlapping operator decisions as one fail-closed policy** | `O-15` and `RI-OD-011`: deterministic launch context is the only automatically accepted link; inferred links stay proposed. `O-16` and `RI-OD-012`: commitments, decisions, financial facts or amounts, critical dates, contradictions, and sensitive relationship conclusions always require review, regardless of confidence; low-risk technical enrichment alone may avoid mandatory review. `O-17`: an accepted record grants no external-action authority. `O-18`: explicit Conversation Log creates one skeletal event, while a conversation inferred from a Quick Note remains proposed. These are the recommendations already carried by the blocking table, now adopted under the operator authority delegated for WP-8 rather than silently assumed in code | Adopted and implemented in WP-8. Invalidated only by a later explicit operator policy revision, which must change the decision register, code, and tests together |
| D-102 | **Conversation participants are deferred to WP-9; WP-8 does not add a permanently-empty participant table** | The WP-8 in-scope sentence named participant associations, but this build has no person/organization identity record and WP-7 deliberately restricted entity mentions to deterministic document/project identifiers and URLs. A participant row would therefore have no valid target or writer. Adding nullable free text would duplicate sensitive capture content and contradict the evidence-span rule; adding an unpopulatable table would violate `AGENTS.md` section 2. WP-8 still creates the explicit skeletal Conversation event required by `O-18`, with unknown participants represented by absence as the specification permits. WP-9 owns person identity and unresolved people mentions and is the first package able to populate participant associations honestly | Deferred, not implemented. Invalidated when WP-9 supplies the identity/mention target and a bounded writer. *Corrected 2026-08-08: **the invalidation condition fired and the row was not updated, so this state cell is false at `8dd4ef6`.** WP-9 supplied both halves it named. `migrations/versions/20260804_7f2a9d6c4e18_create_relationship_identity_profiles.py:181` creates `knowledge.relationship_conversation_participants` unconditionally, with `a_conversation_participant_names_one_identity_target` (`:188`) enforcing that exactly one of `person_id` or `unresolved_mention_id` is present — the identity target whose absence was this row's entire reason to defer — plus the two partial unique indexes at `:192` and `:195`, triggers, and a matching `DROP TABLE` in the downgrade. The table is declared in `infrastructure/persistence/tables.py:2209-2210` and read by `infrastructure/persistence/relationships.py:40, 343-344`. **The deferral was correct when it was taken**, and the reasoning that produced it — no identity record, no honest writer, and `AGENTS.md` section 2's bar on an unpopulatable table — is why WP-9 was the right package to own it. Only the terminal state is wrong: it is **implemented by WP-9**, not **deferred**. The superseded wording is kept and negated rather than replaced, per the `D-78`/`D-81` shape. No new `D-` identifier is minted — see the note on identifier reservation below this table.* |
| D-103 | **The campaign briefing file named by the WP-8 execution directive is absent from repository history; execution uses the pasted operator directive plus repository authority** | A bounded repository/ref search found no `CAMPAIGN-BRIEF.md`. Its absence is a plan/reality discrepancy, not permission to invent its contents. The pasted directive supplies the campaign objective, operator delegation, single-worker constraint, exact-head review/merge gates, and prohibition on deployment. `AGENTS.md`, this plan's WP-8 section, ADR-003, and the mirrored Quick Capture specifications supply the implementation and acceptance criteria. The missing file therefore weakens provenance convenience but does not prevent safe acceptance mapping; exact implementation and review evidence remain bound to Git/CI and the governed external audit artifact | Recorded by WP-8. Invalidated if an authenticated byte-exact campaign brief is later recovered, at which point it must be reconciled rather than silently substituted |
| D-104 | **WP-10 is deferred until MCV completion; WP-11 remains dependency-blocked on it** | Direct operator instruction on 2026-08-04: “defer wp-10 until mcv is complete.” This explicitly overturns `D-32`'s assumed placement of WP-10 inside the pre-completion sequence without lifting active WP-10 gates `D-09` and `O-04` or deciding `O-20`. WP-11's published sequence and this plan both make WP-10 its prerequisite, so WP-11 cannot run while WP-10 is deferred. The operator's later `D-105` clarification explicitly says the MCV is not complete and does not assign WP-11 to either side of the completion boundary. Its active gates `NAR-OP-001`–`NAR-OP-009` remain open. WP-0R through WP-9 are merged, but that fact is not a completion-readiness claim and does not resolve the sequence conflict, declare the MCV complete, assert `MYPA_CURRENT_PRODUCT_SCOPE_COMPLETE`, or authorize deployment. | Operator-directed; WP-10 deferred; WP-11 dependency-blocked; boundary unresolved |

| D-105 | **Canonical version 2.3 is re-mirrored; Apple Mail, Calendar & Contacts yields provisional WP-12 with planning reserved to the operator** | `REQ-MYPA-CANONICAL-PRODUCT-APPLE-MCC-MOSS-INTEGRATION-20260804T214700Z` revised 17 of the canonical package's 21 numbered artifacts in place, preserved all 21 Drive identities and parent bindings, and took the package from 2.2 to 2.3. The publisher labels the Native Apple Personal Data Capture Bridge as conditional MCV scope and calls its sequence WP-12. Authority evidence is layered rather than identical: the numbered canonical artifacts carry their own implementation-not-granted blocks; the disposition denies implementation, live access, source mutation, deployment, production, and risk acceptance; the readback asserts only that implementation authority was not granted; and the publication and roundtrip receipts carry the fuller denial list covering live personal data, TCC/credential mutation, source mutation, deployment/watchers, production activation, external-model disclosure, destructive retention, and risk acceptance. The operator then clarified that the MCV is explicitly not complete and that WP-12 is provisional after WP-10 and WP-11; separate operator authorization is required before WP-12 implementation planning. The operator assigned WP-12 no pre-MCV or post-MCV disposition. Because `D-104` still defers WP-10 until completion and WP-11 depends on WP-10, the resulting completion-boundary conflict is recorded rather than resolved by inference. Nothing in WP-12 is planned, implemented, or authorized. | Historical state, superseded by the later direct authorization in `D-106`; retained as provenance |
| D-106 | **WP-12 is promoted ahead of WP-10/WP-11 for bounded implementation before MCV completion** | Direct operator authorization `AUTH-WP12-20260804-OPERATOR-001` supersedes only WP-12's provisional sequencing and implementation hold. WP-10 remains deferred by `D-104`; WP-11 remains dependency-blocked on WP-10. WP-12 executes in reviewed slice order A, B, D, C, E, F, G, H against the exact 48-row `NAPDCB-AC-*` map. The authority permits repository planning and synthetic implementation but not live Apple or personal-data access, TCC/credential/entitlement changes, signing/notarization, installation or watcher activation, external-model disclosure, source mutation, destructive retention, deployment/production, or risk acceptance. Slice A freezes the map and protocol-v1 source boundary but discharges no final acceptance criterion. | Operator-directed; WP-12 active before MCV completion; WP-10/WP-11 remain deferred |
| D-107 | **After independently verified MCV completion, a fresh orchestrator owns a comprehensive full-MVP campaign** | Direct operator instruction establishes a future handoff, not present implementation scope. After MCV completion has been independently verified, a fresh orchestration context must define a comprehensive MVP `CAMPAIGN-BRIEF` and execute the full MVP, explicitly including WP-10 and WP-11. Until that condition is met, this row does not start MVP, reactivate either package, declare MCV complete, authorize deployment, resolve their open product/operator gates, or relax `AGENTS.md` section 8.2. | Durable future handoff; condition not yet met; no current MVP execution authority |
| D-108 | **WP-FE-03 — Work: Tasks and Commitments is narrowly admitted to bounded frontend implementation** | Direct operator instruction on 2026-08-21 partially supersedes `D-09` only for WP-FE-03. The promotion preserves ADR-004's synthetic-development identity, verified server session, and backend-for-frontend boundary. WP-FE-02 WebAuthn/passkey replacement, WP-FE-04 and later phases, WP-10, and every other frontend surface remain deferred unless separately reprioritized. This decision does not authorize authentication replacement, WebAuthn/passkeys, credential persistence or recovery, Entra/MSAL removal, deployment or production activation, production or shared-database access, credentials or live personal data, new infrastructure, destructive action, or risk acceptance. | Operator-directed; only WP-FE-03 active; all stated exclusions preserved |

**Identifier reservation: `D-106` and `D-107` are not available, and the two
corrections dated 2026-08-08 therefore mint no new row.** Parsed structurally at
`8dd4ef6` — every line whose stripped form begins `|`, outer pipes stripped,
split on `|`, first cell stripped of backticks and asterisks, kept when it
matches `^D-\d+$` — this table holds **105 rows, 105 distinct identifiers,
`D-1` through `D-105` with no gaps and no duplicates**. The next free number
looks like `D-106`. It is not free. The same parse over
`docs/plans/mcv-completion-plan.md` on `recovery/pre-20260805-utc-rollback-c9fb513`
and on the `custody/wp12-local-main-88e8d81` tag returns **107 rows through
`D-107`**: those two identifiers were minted on the WP-12 line that was removed
from `main` by a non-fast-forward move and preserved on those refs rather than
deleted. Reusing the numbers here would give one identifier two different
meanings across refs that are both retained on purpose, which is the failure the
register exists to prevent — and it would do so silently, because nothing parses
across refs. So the `D-24` and `D-102` corrections above are dated in place
against the claim they correct, in the `D-78`/`D-81` shape, and carry no new
identifier. **This is a deliberate departure from the register's usual habit of
naming a correcting decision, and the reason is recorded here rather than left
for a reader to infer.** Whether `D-106` and `D-107` are ever readmitted to
`main`, and under which meaning, is a question about the WP-12 line and is not
resolved by this note.

**`D-36`'s citation shipped ahead of its row, and that is recorded rather than
quietly closed.** WP-4B2b added the section 6 sentence attributing the second
split of WP-4B to `D-36`, but added no `D-36` row. Recomputed at `77ed807`, the
identifier appeared exactly once in this file — in that citation — and in no
commit before it, so the gap opened at `77ed807` (PR #29) itself and the register
cited a decision it did not carry from that merge until WP-0R2 closed it. WP-0R2 found it, declined
to invent the row, and the orchestrator supplied the authoritative text, which is
the row above. This is the `D-16` defect class: a claim routed to a source that
does not hold it. The campaign records the sequence because a register that
silently backfills a missing row teaches a reader nothing about how the gap
opened.

**What `D-54`'s four items resolved to.** They are recorded here because two of
the four were decided against the instruction that raised them, and a decision
that only exists in a worker's report is not a decision a later reader can find.

1. `README.md`'s two false claims — that nothing calls `register_source` and that
   no extraction executor is wired to the worker — are **corrected in place, with
   the superseded wording quoted** rather than deleted, because both were true of
   every commit before WP-4B3. A third clause in the same file, in the paragraph
   beginning "Accordingly", said the slice "still does not run end to end,
   because nothing registers a source for it to read". It was false for the same
   reason and was named by nothing; it is corrected too. Fixing two of three
   would have been the proven-in-one-shape-and-not-its-neighbours defect at the
   scale of a single file.
2. [`../architecture/module-boundaries.md`](../architecture/module-boundaries.md)'s
   "`apps/cli/` now holds two programs" is **corrected to three**, and so is the
   directory tree six paragraphs above it, which named the same two. The
   instruction named only the prose.
3. `all_sources` **was landed** in `infrastructure/persistence/registry.py` and
   the workaround it replaced was reverted. The operator-command guard's
   permitted-name allowlist had been widened to admit the `sources` **table
   declaration** so that the listing could select from it — and a `Table` is a
   write surface, since `insert()` and `update()` reach through it exactly as
   `select()` does. An allowlist whose purpose is to keep an operator command
   narrow had therefore been widened by a write in order to permit a read. The
   reader closes that; the allowlist is back to four functions and no table.
4. `tests/jobs/README.md` was **not** added, and the reason is that the premise
   for adding it is false. The claim was that every other test directory has one.
   Measured: `tests/architecture/` has none either, and has had none since it was
   created — all eighteen of the existing test-directory READMEs are byte
   identical and were created by one commit, `d534502` "chore: scaffold
   recommended repository architecture", on 2026-07-30. The file marks a
   directory that existed at that scaffold commit; `tests/architecture/` and
   `tests/jobs/` were both created later by implementation work and neither has
   one. Adding one would also assert `Status: SCAFFOLD_ONLY` and "Directory
   presence does not authorize runtime implementation" over a directory holding a
   working executor test suite, which is a false claim rather than a missing
   file.

## 14. Consolidated open decisions returned to the operator

Forty-one decisions are open: nine from the Phase 00 ledger, seventeen from Quick
Capture, and fifteen from Relationship Intelligence. Twenty-two of them block
a work package in section 12 — seven on ordinary grounds and fifteen more that
are reserved to the operator by policy and block for that reason. The remaining
nineteen do not block anything yet and are listed so they are not rediscovered
later as surprises.

**`O-19` was here until WP-7 and is recorded rather than deleted**, because it
was blocking in every earlier commit and a reader of one of those should be able
to find out when it stopped. It asked whether "save without AI processing"
appears in MVP, and ruled that the answer must be a stored processing-policy
value or nothing at all. `D-95` closes it by pointing at the mechanism that
already answers it: `knowledge.capture_versions.processing_policy` exists, WP-6
built it, and WP-7 adds no member to it — a value that changes no behaviour and
is distinguishable from `local_only` by nothing is what `AGENTS.md` section 2
bars. What WP-7 owed instead was `P-01` reading that snapshot and branching on
it, which it does.

**Six overlapping decisions were here until WP-8 and are recorded rather than
deleted.** `D-101` closes `O-15` through `O-18` plus `RI-OD-011` and
`RI-OD-012` as one fail-closed review policy. Their former blocking rows are
removed below so the open-decision counts remain statements about open decisions,
not a historical ledger; this paragraph and `D-101` preserve the history.

These numbers are derived from the three tables below, not maintained beside
them. `tests/architecture/test_open_decision_counts.py` recomputes them from this file
and fails if this paragraph and those tables disagree.

That test exists because this paragraph was wrong. It previously read "Forty-one
decisions are open … Sixteen of them block." Both figures were incorrect: at that
moment the tables held forty-six distinct IDs with no duplicates between them, and
the second table is itself headed *Blocking*, so counting only the first understated
the blocking total by thirteen. The correction is recorded as `D-21`, and the
mechanism was corrected alongside the number because a hand-maintained count
goes stale silently and this one already had.

The figures above have since moved twice, which is the mechanism working rather
than failing. Section 16 added two operator decisions to the reserved table, and
`D-24` moved `P00-OD-011` out of the blocking table into the non-blocking group.
Both times the paragraph was recomputed from the tables rather than edited to
taste, and the second move was found by the test rather than remembered. The
forty-six is left in the previous paragraph as the historical figure it is.

Nothing below is decided here. Where a recommendation exists it is named as a
recommendation.

**The third group is prose, deliberately, and that is not the `D-16`/`D-60`
defect.** The first two groups are tables whose first column is the ID; "Not
blocking any planned package" is a paragraph, and
`tests/architecture/test_open_decision_counts.py` reads **both** forms and says
so in its own docstring. A first-cell parse of this file therefore returns no row
for the nineteen IDs named only there, and that is the structure working rather
than a citation with nothing behind it. Recorded because the appearance is
convincing and the reading is prefix-dependent: looking at the `O-` family alone
shows seven orphans and reads like a finding, while a family-blind parse of the
same paragraph shows **nineteen** — seven `O-`, five `P00-OD-`, seven `RI-OD-` —
which is exactly the "remaining nineteen" the paragraph above counts. Every one
of the nineteen resolves in its own ledger: the seven `O-` at
[`../specs/quick-capture/21_RISKS_MITIGATIONS_AND_OPEN_OPERATOR_DECISIONS.md`](../specs/quick-capture/21_RISKS_MITIGATIONS_AND_OPEN_OPERATOR_DECISIONS.md),
which carries `O-01` through `O-20` as headed subsections. Verified 2026-08-03 by
first-cell parse rather than by `grep`.

### Blocking — a work package in section 12 cannot pass acceptance without these

| ID | Source | Question | Blocks |
|---|---|---|---|
| `P00-OD-003` | Phase 00 ledger | Which reviewed PDF extractor, if any | WP-5 acceptance; PDF stays `unsupported` until then, which is specified behavior, not a defect |
| `P00-OD-010` | Phase 00 ledger | HTTP/MCP authentication mechanism | WP-4 beyond loopback. WP-4 can be built and tested locally with a local principal; it cannot be exposed |
| `O-01` | Quick Capture | Final capability, action, and mode names | WP-6 — capability names enter `domain/identity/operation.py` and the public `v1` contract, where renaming later is a breaking change |
| `O-09` | Quick Capture | Private-note default classification | WP-6. Recommendation: `private_local`, no training, no lock-screen content |
| `O-14` | Quick Capture | Editing semantics | WP-6. ADR-003 assumes immutable versions with append-only edits; confirming `O-14` ratifies that assumption |
| `RI-OD-004` | Relationship Intelligence | First personal source set | WP-9. `D-13` builds against fixtures precisely so this can stay open |
| `RI-OD-005` | Relationship Intelligence | Authentication posture for relationship data | WP-9 beyond fixtures |

### Blocking, and reserved to the operator by policy

| ID | Source | Question |
|---|---|---|
| `P00-OD-006` | Phase 00 ledger | Whether any cloud model may receive `my-pa` content. Governs `D-14`; while it is open there is no model-assisted extraction |
| `P00-OD-009` | Phase 00 ledger | Whether a live NAS or GoodNotes root is authorized, by exact path |
| `O-03` | Quick Capture | Priority of Quick Capture against the active objective. Partly answered by the reprioritisation; the ordering question in `D-12` is what remains |
| `O-04` | Quick Capture | When to lift the frontend hold — and, per `D-15`, whether backend work on a held feature needs it lifted at all |
| `O-08` | Quick Capture | Cloud-model eligibility for capture content. Duplicates `P00-OD-006` for this feature |
| `O-10` | Quick Capture | Retention and deletion: active retention, archive duration, draft expiry, hard-delete authority, audit retention |
| `O-20` | Quick Capture | Device-local encryption posture, and whether restricted classifications may be captured offline |
| `RI-OD-002` | Relationship Intelligence | When Relationship Intelligence enters implementation relative to the MCV. Overlaps `D-12` |
| `RI-OD-003` | Relationship Intelligence | Whether and when to lift the `D-09` frontend hold. Duplicates `O-04` |
| `RI-OD-006` | Relationship Intelligence | Private-note classification and reveal behavior. Overlaps `O-09` |
| `RI-OD-007` | Relationship Intelligence | Cloud eligibility for relationship briefings. Overlaps `P00-OD-006` |
| `RI-OD-009` | Relationship Intelligence | Retention and deletion for captures and private notes. Overlaps `O-10` |
| `RI-OD-016` | Relationship Intelligence | External-action scope after the read-only stages. Overlaps `O-17` |
| `O-21` | Quick Capture — RQC amendment | Which credential issues the capture-only device/client grant, and who issues it. The revised canonical package requires "an authenticated HTTPS endpoint with a capture-only device/client grant" in the MCV, but `AGENTS.md` section 5 reserves credential creation to the operator and the package's own `MYPA-RQC-D-008` restates that MCV inclusion "does not itself authorize … credentials". `D-30` bounds the work to a local capture-only principal on loopback so the package can pass acceptance without it |
| `O-22` | Quick Capture — RQC amendment | Whether the capture endpoint may leave loopback, and under what authentication. This presses directly on `P00-OD-010`, which asks the same question for the gateway generally; this narrows it to an endpoint the revised MCV now requires by name, so resolving `P00-OD-010` resolves this one and not the reverse. Ingress activation is reserved by `AGENTS.md` section 5 and by `MYPA-RQC-D-008`. `D-30` builds the endpoint behind the gateway boundary and does not expose it |

The last two rows are opened by this plan rather than inherited from a ledger.
The 2026-08-02 Remote Quick Capture revision added the material that raises them
but did **not** revise `15_OPEN_OPERATOR_DECISIONS.md`, so the package that
created the questions tracks neither. Section 16 records that gap; these rows are
where it stops being untracked. They are placed here rather than in the ordinary
blocking table for the reason `P00-OD-006` is: the package is bounded so it can
pass acceptance without them, and what they block is the operator act on the far
side of that boundary.

### Not blocking any planned package

`RI-OD-001` public feature name, which ratification moved here out of the
blocking table. The ratified decision log records `CR-D-007` — "RI is integrated
domain; PRIE historical" — as `Canonical`, and the ratified executive
description makes Relationship Intelligence "the people-centered
continuity domain inside my-pa", with `PRIE` retained only for provenance. That
settles the name entering `v1` contracts, which was the whole of its claim on
WP-9. What is left is the final UI label set, tracked by the canonical package as
`OP-02` and gated on UI freeze: frontend scope, already held by `D-09`, and not a
contract input. See `D-20`, which also records that the ratified package
treats Relationships as a Library collection rather than a top-level
destination — a point the earlier `D-18` framing got wrong.

`P00-OD-011` numeric resource limits, which `D-24` moved here out of the blocking
table. It previously blocked WP-4 on the grounds that `capabilities.get`
publishes effective maxima and the values were Phase-01 placeholders. `D-24`
derives the published maximum from validated `MY_PA_` configuration rather than
from a module constant, keeping the current `PHASE_01_LIMITS` values as the
defaults. That removes the block without answering the question: the operator may
still set different numbers, but doing so is a configuration change rather than a
code change, which is precisely the outcome the decision was shaped to produce.
What is left is not blocking anything.

`P00-OD-004` contract freeze and `P00-OD-012` `pg_trgm` necessity, both
`OPEN_REVIEW`. `P00-OD-013` audit retention and `P00-OD-014` parser isolation,
both deferred to their phase gates. `O-02` formal product principle, `O-05`
initial platforms, `O-06` offline MVP, `O-07` PWA versus native wrapper, `O-11`
notifications, `O-12` audio scope, `O-13` attachments — every one of these is
frontend, platform, or media scope that section 12 does not plan. `RI-OD-008`
public research, `RI-OD-010` offline posture, `RI-OD-013` importance labels,
`RI-OD-014` device matrix, `RI-OD-015` voice capture, `RI-OD-017` independent
usability and privacy review gate before release.

### Six questions this plan raises that no ledger contains

Ratification on 2026-08-02 answered the third of these outright, changed the
footing of the first and the fourth, and added a fifth. The answered one is kept
and marked rather than deleted, because a list that quietly drops the question it
resolved teaches a reader nothing about how it was resolved. The sixth was opened
on 2026-08-08 by a gap #52 disclosed and deliberately left, and it is a contract
change rather than a repair, which is why it is a question here rather than work
in a package.

1. **The MCV completion declaration.** *Still reserved to the operator.* `AGENTS.md` section 1
   said the MCV ran "through August 2, 2026." When this was written that was
   tomorrow; it is now today, and section 12 plans six work packages that plainly
   do not fit behind it. `AGENTS.md` section 1 has since been amended to say the
   date passed and that the MCV runs until the operator declares it complete,
   which is honest but is not a date. On 2026-08-04 the operator directed that
   WP-10 be deferred until after MCV completion. The operator then explicitly
   confirmed the MCV is not complete and later authorized WP-12 ahead of
   deferred WP-10/WP-11 (`D-106`). WP-11 still depends on deferred WP-10.
   WP-0R through WP-9 being merged is not evidence that the repository is ready
   for a completion decision, and WP-12 authorization is not a completion
   declaration. No date or terminal disposition is inferred. `D-107` governs
   only the later handoff: after independent verification of MCV completion, a
   fresh orchestrator defines and executes the comprehensive full-MVP campaign.

2. **Whether promoted scope is still MCV.** `AGENTS.md` section 1 describes the
   objective as "one complete, read-only vertical slice." Quick Capture is not
   read-only — that is the whole point of ADR-003 — so the sentence no longer
   describes the objective. The amendment names the promoted features
   explicitly and keeps "not a broad platform." If the operator intends the
   features as a *successor* objective rather than an enlarged current one, the
   framing should change again.

3. **Whether to ratify the canonical product direction.** **Answered on
   2026-08-02. No operator action remains.** This was described here as the
   largest unasked question and the only one that could invalidate section 12's
   shapes rather than merely reorder them. It was asked, and answered, and the
   answer invalidated nothing.

   The operator ratified `MYPA-CANONICAL-PRODUCT-DEFINITION-20260802-006` by
   direct instruction on 2026-08-02, which supersedes `my-pa vNext` for current
   whole-product definition and preserves it as source history. The instrument is
   the instruction, not the package's own self-declared status — `D-19` records
   why that distinction matters, and section 15 records the reconciliation in
   full. Only this item is answered; the 58 operator decisions inside the
   package — `OP-01` through `OP-30`, `MCP-OP-001` through `MCP-OP-009`,
   `NAR-OP-001` through `NAR-OP-009`, and `NAPDCB-OP-001` through
   `NAPDCB-OP-010` — remain open and are not tracked here. The figure was 39
   before the 2026-08-02 Native Apple Reminders revision, 48 after it added nine,
   and 58 after the 2026-08-04 Apple Mail, Calendar & Contacts revision added ten;
   see the subsection below the five questions.

   The part worth keeping is why the fear did not materialise. The concern was
   that ratification would make a broad vision's acceptance criteria binding and
   re-shape WP-8 and WP-9. Instead the ratified package sequences *itself* behind
   this plan: its `OP-05` recommends completing the MCV before an explicit
   transition, and its roadmap step `R10.1` names finishing repository WP-4 and
   WP-5 as the first move. It also carries `implementation_authority:
   NOT_GRANTED` on every artifact. So the conservative path section 12 took —
   build only what was promoted, name the object mapping without creating the
   abstractions — turned out to be the path the ratified direction asks for.

   That is a good outcome and a slightly lucky one. Had ratification gone the
   other way, this plan would have been reconciled against it rather than
   confirmed by it, which is why section 15 records the comparison explicitly
   instead of asserting agreement.

4. **The GoodNotes and frontend workstreams (`D-04`).** Both were deferred as
   dependency-blocked on B, C, and D. WP-4 removes that dependency. `D-09`
   independently holds the frontend except for the operator's narrow WP-FE-03
   exception in `D-108`; nothing else changes there without an operator act.
   GoodNotes has no such second hold — only `P00-OD-009`, which
   gates its source root.

   Two things the operator should know. `D-04`'s argument for GoodNotes lapses
   when WP-4 lands, leaving only `P00-OD-009` between it and being plannable.
   And GoodNotes is further along than `D-04` implies: beyond the v0.1 feature
   description it now has a full implementation specification,
   `SPEC-MYPA-GOODNOTES-KNOWLEDGE-INGESTION-v1.0` (Drive
   `111zA3Osva_tdi7oW-8TIBcC0uS9_cQ6VZ-w3pqmGhCA`), and the ratified canonical
   definition strengthens this further: GoodNotes is now named in the ratified
   MVP as a required "GoodNotes proof" capability — one synthetic region, no live
   NAS — and carries its own roadmap stage `R6` and its own operator decision
   `OP-07`. It is not planned here — the operator promoted two features and
   GoodNotes was not one of them — but it is
   closer to plannable than the register currently suggests, and saying so is
   cheaper than having it surface as a surprise.

5. **A third feature package arrived with ratification, and nobody has been
   asked about it.** *New on 2026-08-02.* The ratified package incorporates the
   **Frontier NAS MCP Connector** (`MYPA-FRONTIER-NAS-MCP-CONNECTOR-FEATURE-PACKAGE-20260802-086`,
   Drive folder `1McYcZODHhUb2k-vOQJnkHVQyqHbWRuVa`) as canonical product scope:
   a governed external surface letting authorized frontier clients — ChatGPT,
   Claude, Grok — invoke the same use cases, policy decisions, and disclosure
   envelopes as first-party surfaces.

   This is the single largest scope addition ratification made, and it is worth
   being precise about what it does and does not do. It is canonical scope, and
   it is explicitly **not** inserted into the active repository MCV: the package
   says so directly, its `MCP-OP-001` recommends finishing the WP-4/WP-5 sequence
   first, and its own acceptance crosswalk marks most of its criteria
   `NOT IMPLEMENTED`. It carries nine operator decisions of its own,
   `MCP-OP-001` through `MCP-OP-009`, none of which is answered here and none of
   which blocks any package in section 12. Those nine are deliberately *not*
   added to the counts above, which cover the three ledgers this plan tracks;
   folding a package's internal decisions into this plan's totals would misstate
   what this plan is accountable for.

   `D-22` records why it is indexed by reference rather than mirrored. What the
   operator should know is that the connector's arrival does not change WP-4 —
   if anything it raises the value of WP-4's transport-parity work, since a thin
   MCP adapter over stable application contracts is exactly what the connector
   assumes. The decision that will eventually be needed is `MCP-OP-001`:
   whether the connector is sequenced after the MCV, as its own package
   recommends, or reprioritised ahead of it. Nothing needs deciding today.

6. **`_Captures.search` lets a `CaptureSearchInternalError` reach the application
   past the port's vocabulary, and closing it is a contract change.** *Opened
   2026-08-08.* #52 found this on the way to something else, deliberately did not
   fix it, and recorded it at the site in
   `src/my_pa/infrastructure/persistence/unit_of_work.py` — pinned by a test read
   from the `except` clauses themselves, so closing the gap without removing the
   note reddens rather than leaving a false sentence behind. That is disclosure
   done well, and it is why this entry is a question rather than a defect
   awaiting a worker.

   The reason it is listed here rather than fixed is that the two available
   repairs are not equivalent, and neither is the orchestrator's to choose.
   **Either** the port's error vocabulary widens to admit the internal-error
   case, which changes what every caller of the capture port must handle;
   **or** the adapter translates the internal error into an existing member of
   the vocabulary, which is the narrower change but discards the distinction
   between "the search plane failed" and whatever member it is folded into. The
   first is a contract change in the sense `P00-OD-004` uses for the `eligible`
   field; the second is a defect-laundering risk of exactly the kind section 10
   of `AGENTS.md` forbids, and it would have to be argued rather than assumed
   safe. Nothing in the repository establishes which the operator wants.

   No `D-` identifier is minted for it — `D-106` and `D-107` are reserved, for
   the reason recorded under section 13's decision table — and no ledger this
   plan tracks contains a question it fits, which is why it is here. It blocks no
   package in section 12 and is deliberately **not** added to the counts above,
   on the same grounds as the connector's nine: those counts cover the three
   ledgers this plan tracks, and this is not in one of them. It is direction-
   neutral: the gap and both repairs are identical under either product line.

### Nine more package decisions arrived with the v2.2 revision

The 2026-08-02 Native Apple Reminders revision added `NAR-OP-001` through
`NAR-OP-009` to the package's own
[`15_OPEN_OPERATOR_DECISIONS.md`](../specs/canonical-product-definition/15_OPEN_OPERATOR_DECISIONS.md),
which is where they are tracked. They are named here and not tabulated here, for
the same reason `MCP-OP-001` through `MCP-OP-009` are: they belong to the
package, the package tracks them, and reproducing the table in this plan would
create a second copy that drifts. They are excluded from the counts above on the
same grounds — those counts cover the three ledgers this plan is accountable
for, and `tests/architecture/test_open_decision_counts.py` reads only
`P00-OD-*`, `RI-OD-*`, and `O-nn`.

What the operator should know without opening the file: all nine are open, and
between them they gate every path into `WP-11`. `NAR-OP-007` is the
code-signing and notarization identity, `NAR-OP-008` is the EventKit permission
grant and live reminder access, `NAR-OP-001` is the reminders-only credential
and grant issuance, and `NAR-OP-009` is production activation and residual-risk
acceptance — four operator-only acts under `AGENTS.md` section 5. The other
five, `NAR-OP-002` list binding, `NAR-OP-003` undated reminder policy,
`NAR-OP-004` external edit policy, `NAR-OP-005` cancellation withdrawal, and
`NAR-OP-006` minimum macOS and hardware, are scope and behaviour questions that
`WP-11`'s own `NAR-00` policy amendment would otherwise have to assume. `D-39`
records that none of them is answered and that nothing in `WP-11` is built.

Unlike the RQC revision, which `D-33` records as having created operator
questions while revising no decisions artifact — the gap this plan carries as
`O-21` and `O-22` — the v2.2 revision **did** revise
`15_OPEN_OPERATOR_DECISIONS.md`. So this plan opens no row of its own for
Native Apple Reminders: the package that created the questions tracks them.

## 15. Reconciliation against the ratified canonical product definition

### 2026-08-12 remediation authority note

The operator has reprioritized the current remediation objective to include the
frontend and managed-document implementation necessary to close the six
pilot-readiness blockers. That objective-specific instruction is implementation
authority for this remediation only; it does not amend repository policy and it
does not make `PLAN_APPROVED` an authorization to amend `AGENTS.md`.

The resulting inconsistency with the older policy statements that defer
frontend and managed-document work was deliberately recorded in this plan, the
remediation pull request, and the final-state report. On 2026-08-21 the operator
separately authorized the policy amendment recorded by `D-108`, but only for
WP-FE-03 — Work: Tasks and Commitments. That later decision does not broaden the
2026-08-12 remediation authority or admit managed-document work, WP-FE-02,
WP-FE-04 or later phases, WP-10, or any other frontend surface. All other policy
boundaries, including live-data, deployment, destructive-action, credential,
and independent-review gates, continue to apply.

On 2026-08-02 the operator ratified `MYPA-CANONICAL-PRODUCT-DEFINITION-20260802-006`.
Section 14 item 3 anticipated that this could invalidate section 12's shapes. It
did not. This section is the evidence for that claim rather than the assertion of
it, because "the plan already agreed with it" is exactly the conclusion a
reconciliation is most likely to reach lazily.

The package is mirrored byte-exact at [`../specs/canonical-product-definition/`](../specs/canonical-product-definition/00_README.md);
its provenance, verification strength, and two disclosed defects are recorded in
[`../specs/README.md`](../specs/README.md).

### The instrument, and what it is not

Ratification rests on a **direct operator instruction of 2026-08-02**, recorded
at `D-19`. It does not rest on anything inside the package, and the distinction
is load-bearing.

The package never claims to be ratified. It carries a self-declared front-matter
status, `CURRENT_CANONICAL_PRODUCT_DEFINITION`; its publication receipt grants
`NOT_GRANTED` on implementation, deployment, production activation and risk
acceptance; and `15_OPEN_OPERATOR_DECISIONS.md` closes with "This package
performs none." A newer package asserting a stronger status about itself is
exactly the evidence `D-17` refused for the predecessor, and treating it as
sufficient here would have quietly lowered the standard this register set one
pull request earlier.

Two consequences follow. First, the 58 operator decisions inside the package
remain open — `OP-01` through `OP-30`, the connector's `MCP-OP-001` through
`MCP-OP-009`, Native Apple Reminders' `NAR-OP-001` through `NAR-OP-009`, and
Apple Mail, Calendar & Contacts' `NAPDCB-OP-001` through `NAPDCB-OP-010`.
Ratifying the definition did not answer any of them, and `OP-05` in particular
still carries only a recommended default. Section 14's counts exclude all 58,
for the reason given in item 5: they belong to the package, not to the three
ledgers this plan is accountable for.
Second, the only question section 14 marks answered is its own item 3, the
ratification question itself. Nothing else was removed from the operator's queue.

### What ratification binds, and what it does not

| Question | Answer | Evidence |
|---|---|---|
| Does it grant implementation authority? | No | `implementation_authority: NOT_GRANTED` in the YAML front matter of all 20 markdown artifacts, and under `authority` in the manifest, which is JSON and has no front matter; the publication receipt records `NOT_GRANTED` for implementation, deployment, production activation and risk acceptance |
| Does it outrank repository policy? | No | `AGENTS.md` section 1 places indexed Workspace publications at rank 4, below accepted specifications, ADRs, and policy at rank 3 |
| Does it change the active objective? | No | Its `OP-05` recommends "Complete MCV then explicit transition"; its `R10.1` names finishing repository WP-4 and WP-5 first |
| Does it supersede the two feature specifications? | No | "Owning Quick Capture, RI, and GoodNotes specs remain current where more detailed and not explicitly reconciled" |
| Does it lift the frontend hold? | No | Its `OP-06` states the hold "Remains until expressly lifted", matching `D-09` |
| Does it add scope? | Yes, one package | The Frontier NAS MCP Connector, canonical but explicitly outside the active MCV — section 14 item 5, `D-22` |

### Stage mapping

The canonical roadmap and this plan's work packages run in the same order, but
they are **not the same scope**. Every "planned" row below is a subset of the
canonical stage it sits under, because the canonical stages carry frontend and
continuity surface that section 12 excludes. Reading this table as equivalence
would overstate what the work packages deliver.

| Canonical stage | This plan | Status |
|---|---|---|
| `R0` complete active read-only MCV | WP-4 + WP-5 | Next, and unchanged by ratification. The closest to a true match |
| `R1` product contracts / frontend proof | WP-FE-03 only | **Split.** `D-108` admits only WP-FE-03; the rest of its frontend half remains held by `D-09` and `OP-06`. Its contracts half — canonical object, state, error, span, region, Situation, Frame, Trace, Review and Receipt contracts — is otherwise unplanned, and no hold explains that |
| `R2` product-owned Capture source | WP-6 | **Subset.** `R2` also requires responsive PWA, global and contextual launch, and capture modes; WP-6 is frontend-free and builds none of them |
| `R4` proposal / review / promotion | WP-7 + WP-8 | **Subset.** `D-14` excludes the model-assisted extraction stages `R4` assumes |
| `R5` relationship and project continuity | WP-9 | **Subset**, and the largest gap. `R5` adds commitments, briefings, Situations, Frame, Trace and Today/Pulse gates; WP-9 builds identity and read-only profiles over fixtures per `D-13` |
| `R3` offline Capture, `R6`–`R9` | Not planned | Beyond promoted scope |
| `R10` Frontier connector | Not planned | `D-22`; `MCP-OP-001` sequences it after `R0` |

### Five divergences, recorded rather than smoothed over

Agreement was close but not total. These are the places the two documents do not
say the same thing.

1. **The canonical MVP is deliberately larger than the repository MCV.** The
   canonical `12_MVP_DEFINITION.md` requires a GoodNotes proof, offline Capture,
   Situations, Frames, and a five-destination shell. The repository MCV requires
   none of these. This is not a conflict — the canonical document states in its
   own objective that it "is not the active repository MCV and is not
   implementation authority" — but the two must never be read as the same list.
   **Resolution: the repository MCV governs what gets built; the canonical MVP
   governs what the product eventually means.** No plan change.

2. **The sequence table understates `D-12`.** The table at section 12 lists WP-6
   as depending on WP-4 alone, while `D-12` states the read-only slice — WP-4
   *and* WP-5 — is finished before either feature is built. The canonical `R0`
   agrees with `D-12`, not with the table. **Resolution: `D-12` and canonical
   `R0` govern. WP-6 begins after WP-5, not after WP-4.** The table is corrected
   below.

3. **`RI-OD-001` was carried as blocking after it had been answered.** The
   ratified `CR-D-007` settles the domain name; only the UI label set remains,
   as `OP-02`, and that is frontend. **Resolution: reclassified — `D-20`.**

4. **The canonical package binds a stale head in one place.** Its `00_README.md`
   body cites `b48b1b1`, two merges behind the `9096fa4` its own front matter and
   manifest bind. **Resolution: the front matter and manifest binding is
   authoritative; the discrepancy is disclosed in `../specs/README.md` and
   mirrored as authored rather than silently corrected.**

5. **The section 12 object-model mapping did not survive the change of target
   document, and the first draft of this reconciliation missed it.** The mapping
   table was written against `my-pa vNext`. The first version of this change
   relabelled its column header and left every target unchanged, which asserted
   agreement that had not been checked — and did so in the one passage the same
   change had just described as consequential. Independent review caught it.

   Re-derived against `09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md`, three claims
   were false and one was misdirected. `Entity` does not exist in the ratified
   model; `Person` and `Organization` are first-class. `Capture` and
   `CaptureVersion` are defined under those exact names rather than as a generic
   "Source Record". `ReviewCase`, `Receipt`, `Conversation` and `Affiliation` are
   likewise identity mappings. And the Assertion trust ladder the table gave WP-7
   as an instruction — Confirmed, Strongly Supported, Probable, Possible,
   Unverified — appears nowhere in the ratified package.

   **Resolution: the table is re-derived in section 12, the corrections are
   stated in it rather than only here, and WP-7's state vocabulary is rebound to
   the ratified `Proposal` and `Assertion` state sets.** This is recorded as a
   divergence rather than quietly fixed because it is the exact failure this
   section warns about in its opening paragraph — reaching "the plan already
   agreed with it" without checking — and the warning is worth less if the
   instance is hidden.

### Correction to the section 12 sequence table

Per divergence 2, WP-6's dependency is corrected from WP-4 to WP-5. The original
row is left visible here rather than only in git history:

| WP | Objective | Depends on | Was | Frontend? |
|---|---|---|---|---|
| WP-6 | Capture domain, contracts, and durable persistence | **WP-5** | WP-4 | No |

Nothing else in that table changes.

### WP-4 as it now stands

Ratification did not change WP-4's objective, scope, or exclusions. It added two
acceptance criteria and confirmed the rest. The package definition at section 12
remains authoritative; this is the delta.

**Objective, in scope, and out of scope.** Unchanged. `P00-OD-010` still keeps
WP-4 at loopback, `P00-OD-003` still leaves PDF unsupported, and neither is
resolved by ratification.

**Added acceptance criteria.**

- `CPD-AC-01` **disclosure-envelope parity by field.** The canonical
  source-authority model and connector crosswalk row `MCP-AC-07` require scope,
  coverage, freshness, authority, and limitations to be disclosed identically
  across transports. `SPEC-AC-001` asserts transport parity generally; this
  narrows it to those five fields by name, so that a future MCP adapter inherits
  a proven envelope rather than reconstructing one.
- `CPD-AC-02` **`record_outcome` round-trip.** Carried forward from WP-3, not
  from ratification, and stated here because WP-4 is what builds on it. The
  extractor identity, extracted-at, and observed-at columns are written and read
  by nothing that asserts they survive the round trip. WP-4 pins them with an
  assertion before adding behavior on top.

**Confirmed unchanged.** `SPEC-AC-001` transport parity, `P05-SPEC-AC-002`
negative evidence through every transport, `MB-AC-002` layering, and the derived
capability manifest. The path-drift reconciliation between
`module-boundaries.md` section 3 and the actual tree stays WP-4's job.

**What WP-4 still may not do.** Network exposure beyond loopback, authentication
mechanism selection, any capture or relationship behavior, and any connector
work. Ratification widened none of these.

### Invalidation

This reconciliation binds `MYPA-CANONICAL-PRODUCT-DEFINITION-20260802-006`
version 2.1 at package folder `1Z8Aug1_3v6ILgvopY8XpjiNMBySZOCCq`, verified
on 2026-08-02 against three independent in-package hash sources (21/21,
21/21, and 20/20 — the manifest does not hash itself),
against this plan at the commit that introduces this
section. A new package version, a revision to any mirrored artifact, or an
operator decision on `MCP-OP-001` invalidates the affected rows above and
requires re-reconciliation. It does not invalidate WP-4, whose acceptance
criteria are bound to repository tests rather than to the package.

**That clause fired on 2026-08-02.** Eight mirrored artifacts were revised in
place later the same day. Section 16 is the re-reconciliation it requires.

## 16. Reconciliation against the Remote Quick Capture revision

Section 15's invalidation clause names "a revision to any mirrored artifact" as a
condition requiring re-reconciliation. On 2026-08-02 at approximately 11:49–11:50Z
a second coordination roundtrip,
`REQ-MYPA-CANONICAL-PRODUCT-RQC-INTEGRATION-20260802T114700Z`, revised eight of
the mirrored artifacts in place to fold **Remote Quick Capture** into the MCV.
This section is that re-reconciliation.

The thing worth saying first is how nearly this was missed. Every revised
artifact still declares `version: 2.1` — the same version section 15 bound — and
every one still names the *earlier* roundtrip in its `coordination_request_id`.
A reader checking the package's own version fields would have concluded that
nothing had changed. Only a hash comparison found it.

### What was re-mirrored, and how it was verified

Eight artifacts were refreshed from Drive folder `1Z8Aug1_3v6ILgvopY8XpjiNMBySZOCCq`
with `rclone`, which retrieves stored raw bytes; the Drive-reported byte count of
each matched the retrieved bytes exactly, so no conversion or normalisation
occurred on the read path.

Each was checked twice, against two independent properties.

| Artifact | Drive ID | Bytes | Receipt hash | Prefix-append |
|---|---|---|---|---|
| `00_README.md` | `1NKw2gDkl_C5iFRQqh2mRDxmSZtoZpDgQ` | 6,137 | match | holds |
| `01_EXECUTIVE_PRODUCT_DESCRIPTION.md` | `15Umcs2JBMdFvxfRgNaA-P-Nc_iC3jDHV` | 16,241 | match | holds |
| `02_CANONICAL_PRODUCT_SYNTHESIS_SPECIFICATION.md` | `18l1S2iz5v_qgKZg8iVBAw47xvuHkbOjI` | 28,118 | match | holds |
| `08_DEVICE_AND_PLATFORM_STRATEGY.md` | `1Y7dDra-1NlN5sTrbg4yBrdEeo1F8B6HA` | 5,218 | match | holds |
| `09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md` | `1xwJPqXyXR0UepmF_lmkrOspEX8Xosq_W` | 11,322 | match | holds |
| `12_MVP_DEFINITION.md` | `1CwOBwGsRuxF8O3tazLFK3UnW_I-5aSAq` | 8,524 | match | holds |
| `13_ROADMAP_AND_DEPENDENCY_SEQUENCE.md` | `12dfRuODgib94H53RWH1wWJcGUdDHYZ7Y` | 8,245 | match | holds |
| `14_DECISION_LOG.md` | `1ty-sjhwJ5q8-XpUqwKINh_WO61CXg7Um` | 6,447 | match | holds |

*Receipt hash* is the retrieved bytes re-hashed and compared against the SHA-256
published for that artifact in
`PUBLICATION-RECEIPT-REQ-MYPA-CANONICAL-PRODUCT-RQC-INTEGRATION-20260802T114700Z.json`:
eight of eight, zero mismatches, and the same eight verified again after being
written into this repository. The `CANONICAL-ARTIFACT-DISPOSITION` publishes the
same eight hashes, so the two agree — but they are not independent sources, since
the same roundtrip produced both.

*Prefix-append* is the independent property. Every revision is a pure byte-prefix
append: the new bytes begin with the previously mirrored bytes, verified against
the blobs committed at `ef08ddd`, with a new trailing section added. Nothing that
this repository had already reviewed was altered, so the reconciliation in section
15 remains valid for everything it covered and this section only has to account
for what was added.

The RQC control set lives in a new subfolder,
`RQC-INTEGRATION-20260802T114700Z` (`1t6fzDfHVrLQe6Wd2qjAtZ2ll--fYNPaF`). Three of
its members are mirrored beside the artifacts they attest, following the precedent
the MCP-integration control artifacts already set: the `CANONICAL-ARTIFACT-DISPOSITION`,
the `PUBLICATION-RECEIPT`, and the `COORDINATION-ROUNDTRIP-RECEIPT`. The
coordination request (`1yhkRgk6qcd2V-PWucS7WuRrbCO72FVAn`) and response
(`1qVhuUeeApFEGQQrq22lUzQwYhkQWyXN7`) are indexed by exact Drive ID and **not**
mirrored, following `D-22`: they are governance correspondence supporting no
citation in this repository, and mirroring material to support no citation is
scope `AGENTS.md` section 2 does not want. As with the MCP-integration control
artifacts, nothing in the package hashes these three, so they rest on the weaker
check of Drive-reported byte count matching the retrieved bytes — 3,356, 3,805,
and 786 respectively.

### What the revision changed in substance

**Remote Quick Capture is included in the MCV.** `12_MVP_DEFINITION.md` states it
directly and enumerates the slice; `13_ROADMAP_AND_DEPENDENCY_SEQUENCE.md` moves
it into the MCV delivery sequence "rather than treated as a post-MCV enhancement."
`D-29` records what that does to this campaign's objective.

**The Stage 1 transport is an iOS Shortcut posting one text field to
`capture.create`.** One unrestricted text field is stated to be sufficient;
prefixes such as Person, Project, or Task are "optional accelerators only". The
service is transport-neutral, which is what lets the endpoint and the client be
sequenced separately — as `D-30` and `D-31` do.

**The durable-first contract.** Successful capture requires *one committed
transaction* containing the stable Capture and CaptureVersion identities, the
exact original content, a content hash, the authenticated principal, the
registered client or device, the idempotency result, the classification and
processing policy, an audit reference, a processing outbox job, and the receipt.
Classification, model availability, entity resolution, domain routing, search
indexing, and downstream promotion "cannot block or redefine capture success."
This is a strong and welcome constraint: it is the same shape ADR-003 already
gives Capture, and it rules out the failure mode where a capture is acknowledged
and then lost because enrichment failed.

**Captured content is untrusted data and never authorization.** It "is
source-authoritative for what the operator wrote and for nothing else… It cannot
send messages, delete records, modify external systems, execute shell or code,
expand source scope, invoke unrestricted MCP tools, approve proposals, or accept
risk." This agrees with `AGENTS.md` and with the threat model, and it is worth
noting that the package states it rather than leaving it to the repository.

**A PWA capture surface and offline-recovery path are named inside the MCV.**
MCV item 6 and roadmap step 5. This is the one part of the revision that touches
a standing operator instruction, and `D-32` records it as an assumption rather
than as a finding.

**SMS, iMessage, and hosted messaging are excluded from the MCV baseline.**
`MYPA-RQC-D-004`, with `01_EXECUTIVE_PRODUCT_DESCRIPTION.md` giving the reason:
meeting the no-incremental-service-charge constraint would otherwise require an
already-paid receiving number and a relay device.

### Six new canonical record types, and which package would build each

`09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md` gained six record types under a
*Remote Quick Capture object-model amendment* heading. The table below maps each
onto the work package that would build it, in the same manner as section 12's
mapping table.

**A caution carried forward from that table.** It was corrected once for treating
a bare name in `09`'s *Supporting records* list as a derivation it did not have.
The same discipline applies here, and the honest report is that this amendment is
*better* documented than that list: all six arrive with at least a one-clause
gloss, so none is a bare name. Two rows are nonetheless weaker than the rest, and
say so.

| Built here | Canonical record type | Package | Note |
|---|---|---|---|
| Capture submission envelope | `CaptureSubmission` | **WP-6** | **Defined, and the most fully specified of the six.** `09` enumerates its fields: request, correlation, idempotency, principal, registered client/device or relay, transport, capture method, trust state, transport message identifier, client timestamps, server receipt time, payload hash, admission result, CaptureVersion, and receipt. WP-6 already owns idempotency, receipt, and the durable-first transaction, so this is the record that transaction writes |
| Registered capture client | `RegisteredCaptureClient` | **WP-6** | **Defined.** Principal binding, device/client type, revocable credential reference, permitted capability, rate and size limits, creation, last-seen, and revocation state. Note that WP-6 builds the *record*, not a credential: `D-30` issues none, and the "revocable credential reference" is a reference to something `O-21` has not yet decided how to issue |
| Delivery attempt log | `CaptureDeliveryAttempt` | **WP-6** | **Defined, but thinly.** `09` gives one clause — "bounded delivery attempts and safe error classification" — and no fields, unlike `CaptureSubmission` beside it. What "bounded" and the error taxonomy mean is not specified, so WP-6 derives them from the existing job lease/retry work in WP-2 rather than from `09`. Stated because the row rests on a gloss, not on a specification |
| Classification and domain assignment | `CaptureClassification`, `CaptureDomainAssignment` | **WP-7** | **One shared gloss covering two names.** `09` defines them jointly — "versioned multi-label interpretation without relocating or overwriting the Capture" — and gives `CaptureDomainAssignment` nothing that distinguishes it from `CaptureClassification`. So this row claims the pair, not each separately, and the boundary between them was a WP-7 design question this plan did not answer. **`D-94` answers it**: `CaptureClassification` is evidence-bound and about the text — one row per `(version, scheme, scheme_version, label)`, each carrying its rule, that rule's version, and at least one span, and each therefore *citable*; `CaptureDomainAssignment` is interpretation and about placement — one row per `(version, domain, assignment_version)`, superseded rather than updated, carrying no span, because no phrase means "this belongs to the Riverside project". **Only the first is built in WP-7**: the second's only deterministic input is a launch-context link and `capture_context_links` is WP-8's, so it would be a permanently-empty table, which `../../AGENTS.md` section 2 bars. **This row assigns record types and not the `Classification` enum** — `my_pa.domain.common.classification.Classification` is a data-sensitivity vocabulary (`private_local`, `restricted_local`, `synthetic_test`), a different subject with a similar name, and WP-7 does not extend it (`D-92`). The *versioned* and *without relocating or overwriting* clauses are the load-bearing part and are unambiguous |
| Entity mention | `CaptureEntityMention` | **WP-7** | **Defined.** Exact surface text, evidence span, entity type, unresolved/candidate/resolved state, and later resolution lineage. This lands squarely on WP-7's evidence-span work. ~~The unresolved/candidate/resolved ladder is the same shape as the `Proposal` states section 12 already directs WP-7 to use.~~ **That clause is struck rather than deleted, so the correction is legible: it is wrong** (`D-93`). The ladder is canonical `09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md`'s **`Identity`** state set — `resolved`, `candidate`, `unresolved`, `merge_proposed`, `split_proposed`, `superseded` — and the `Proposal` set it names contains **neither `candidate` nor `resolved`**. The row's assignment survives the correction: `D-93` builds `CaptureEntityMention` restricted to the deterministic subset — document and project identifiers and URLs, each with a span and each always `unresolved`, since resolution is `P-07` and `P-07` is out of scope — and freezes `resolution_state_is_known` at that single value on the `D-78` precedent. **Exact surface text is deliberately not stored**: the span already points at it in the immutable version and re-derives on read, and a second copy would be a further place capture content sits and would make the mention's "exact" a claim about the copy |
| Correction | `CaptureCorrection` | **WP-8** | **Defined.** Four kinds — source-text successor version, derived-value correction, identity correction, routing correction — "each with immutable lineage". WP-8 owns promotion and correction, and immutable lineage is the same append-only discipline ADR-003 gives CaptureVersion |

No new package is created for these. The durable-first transaction, immutability,
idempotency, evidence spans, and proportional review they depend on are already
the acceptance criteria of WP-6 through WP-8, and a seventh package would
duplicate them.

### The new prohibition

`09` closes the amendment with a prohibition this repository should adopt without
qualification:

> No transport-specific note store, SMS memory, PRIE memory database, second
> knowledge store, or model-specific memory is permitted.

This agrees with `docs/architecture/module-boundaries.md` and with `D-20`'s
disposal of the separate-PRIE-database framing. It is stated here because it is
the kind of constraint that is cheap to hold now and expensive to retrofit: every
one of the six record types above hangs off the single Capture chain, and the
prohibition is what keeps a second transport from growing its own.

### Eight new package decisions

`14_DECISION_LOG.md` gained `MYPA-RQC-D-001` through `-008`: RQC incorporated into
the MCV as an extension of Quick Capture (`-001`); iOS Shortcut over authenticated
HTTPS as the initial transport (`-002`); the first-party PWA as the canonical
cross-platform, offline-recovery, history, correction, and Review client (`-003`);
SMS, hosted messaging APIs, additional cellular service, and iMessage relays
excluded from the MCV baseline (`-004`); capture success meaning durable source
persistence and receipt before enrichment (`-005`); message content as evidence
data granting no external-action, deletion, command, policy, or unrestricted-tool
authority (`-006`); and the governing feature package
`MYPA-REMOTE-QUICK-CAPTURE-FEATURE-PACKAGE-20260802-001`, Drive folder
`1lDSkTldgSkaRfJ3v9h-U10lCe-Lmwzsv` (`-007`), which is neither mirrored nor
examined here.

`-008` is the one to read closely, because it is the package limiting itself:

> `MYPA-RQC-D-008`: MCV product inclusion does not itself authorize repository
> mutation, credentials, ingress activation, deployment, production, or risk
> acceptance.

`D-30` and `D-31` are bounded by that sentence rather than in spite of it. When a
publication and this repository's policy agree on a limit, the limit is not in
tension with anything and there is no judgement call to make.

### Authority did not change

`implementation_authority: NOT_GRANTED` survives the revision. It is present in
the front matter of all eight revised artifacts — the exact field, unchanged —
and the RQC disposition JSON carries the same in its authority block:

```json
"authority": {
  "implementation": "NOT_GRANTED",
  "deployment": "NOT_GRANTED",
  "production": "NOT_GRANTED",
  "risk_acceptance": "NONE"
}
```

The publication receipt independently lists `blocked_actions` covering repository
mutation, credential creation, ingress activation, deployment, production
activation, and risk acceptance. So the three limits section 15 recorded all
survive: no implementation authority, rank 4 under `AGENTS.md` section 1, and the
package sequencing itself behind the repository's own work. What authorises the
work packages is the operator's objective, exactly as before — see `D-29`.

### Three defects in the revised package

Each was verified against the retrieved bytes and the Drive listing rather than
inherited from a report.

**1. Stale front matter.** All eight revised artifacts still carry `version: 2.1`
and `prior_version: 2.0` — unchanged across a revision that added between 967 and
2,620 bytes of new normative content each. All eight still carry
`coordination_request_id: REQ-MYPA-CANONICAL-PRODUCT-MCP-INTEGRATION-20260802T095600Z`,
naming the *earlier* roundtrip rather than the one that revised them. And all
eight bind `repository_head: 9096fa4fbe64ff1cdabc07e53a3e68c52efc8575`, which is
one commit behind `main` at `ef08ddd` — the commit that mirrored the package in
the first place. The disposition JSON repeats the same stale head.

The consequence is the part worth recording. **A version-field check would not
have detected this revision at all**, because no version field moved. Only a hash
check did. A future reader deciding how to test this mirror for staleness should
trust the hash and not the version, and should treat `version: 2.1` in these eight
files as naming the package generation rather than the artifact revision.

**2. Unpublished readback evidence.** The RQC control folder contains three
subfolders — `revised-artifact-readbacks/` (`1YG4ibwYuWGaieCYhKlxggtaDEfDZZeEh`),
`publication-controls/` (`1V_6x0gaxULtU69HCrRS0A1elAjocmZof`), and `noop/`
(`1EYk2P5VEu_HtbymbXicX8YmODAUtSYu4`) — and a recursive listing returns no members
in any of them. They are empty. Meanwhile the publication receipt asserts
`"canonical_specification_readback_observed": true`. The assertion may well be
true; what is missing is the evidence that would let anyone check it. The claim
and its support were published to the same folder in the same roundtrip, and only
the claim arrived.

One correction to how this defect has been described elsewhere: the assertion is
in the **publication receipt**, not in the coordination roundtrip receipt. The
roundtrip receipt carries only `index_registration_verified: true` and the
identity bindings. The distinction matters because the two artifacts are attested
by different steps.

**3. No readback-verification artifact.** The MCP-integration control set
published `READBACK-VERIFICATION-REQ-MYPA-CANONICAL-PRODUCT-MCP-INTEGRATION-20260802T095600Z.json`,
which is one of the three independent hash sources section 15 relied on. The RQC
set publishes no equivalent.

So it is worth being exact about what carries the mirror's integrity claim here,
because it is weaker than what section 15 had. Section 15 verified 21 artifacts
against three in-package hash sources. This section has **one** hash source —
the publication receipt, with the disposition repeating it rather than
corroborating it — plus **one independent structural property**, the
prefix-append check against the bytes committed at `ef08ddd`. The prefix-append
check is what does the real work: it is the only check here not derived from the
RQC roundtrip's own output, and it independently establishes that the previously
verified content was not altered. There is no independent readback, and this
section does not claim one.

### `15_OPEN_OPERATOR_DECISIONS.md` was not revised

It is not among the eight revised artifacts; its Drive modification time is
2026-08-02T10:07:51Z, from the earlier roundtrip. The revision therefore created
operator decisions that the package's own ledger does not track — and, before
this section, that no ledger tracked at all.

Two of them are concrete enough to name:

- **Which credential issues the capture-only device/client grant.** MCV item 4
  requires the grant; `RegisteredCaptureClient` carries a "revocable credential
  reference"; nothing says who issues it or how. Now tracked as `O-21`.
- **Whether the capture endpoint may leave loopback.** Roadmap step 3 puts an
  authenticated endpoint on the gateway boundary; roadmap step 8 defers
  activation to the operator; neither says what the intermediate state is. Now
  tracked as `O-22`.

`O-22` presses directly on the already-open **`P00-OD-010`**, the HTTP/MCP
authentication mechanism. They are not duplicates and the relationship runs one
way: `P00-OD-010` asks the general question for the gateway, `O-22` narrows it to
an endpoint the revised MCV now requires by name. Resolving `P00-OD-010` resolves
`O-22`; resolving `O-22` alone would leave the gateway question open. Both are in
section 14, whose counts are derived from its tables and enforced by
`tests/architecture/test_open_decision_counts.py`, so adding them moved the
headline figures automatically rather than by hand.

### Invalidation

This reconciliation binds the eight artifacts revised by
`REQ-MYPA-CANONICAL-PRODUCT-RQC-INTEGRATION-20260802T114700Z`, at the SHA-256
values published in
`PUBLICATION-RECEIPT-REQ-MYPA-CANONICAL-PRODUCT-RQC-INTEGRATION-20260802T114700Z.json`
and re-verified here on 2026-08-02, against this plan at the commit that
introduces this section. Section 15 continues to bind everything it covered,
because the prefix-append property means none of it changed.

A further revision to any mirrored artifact invalidates the affected rows above
and requires re-reconciliation — and, given defect 1, **that condition must be
tested by hash rather than by version field**, since the last revision moved no
version. An operator decision on `D-32`, `O-21`, or `O-22` invalidates the rows
that depend on it. Publication of the missing readback evidence would strengthen
defects 2 and 3 rather than invalidate anything.

## 17. Reconciliation against canonical product definition version 2.3

The condition in sections 15 and 16 fired again on 2026-08-04.
`REQ-MYPA-CANONICAL-PRODUCT-APPLE-MCC-MOSS-INTEGRATION-20260804T214700Z`
revised the same canonical package in place from version 2.2 to 2.3. Direct raw
readback from canonical folder `1Z8Aug1_3v6ILgvopY8XpjiNMBySZOCCq` established
the exact revision:

- package `MYPA-CANONICAL-PRODUCT-DEFINITION-20260802-006`, 21 numbered
  artifacts, 17 revised and 4 unchanged;
- 21 of 21 Drive IDs preserved, 21 of 21 parent bindings verified, and 21 of 21
  stored-raw-byte readbacks matching;
- manifest `18_PACKAGE_SOURCE_MANIFEST.json`, Drive ID
  `1xxQG_fsUlTxX7VRXOCm8SSCjYF2xPV1j`, 13,899 bytes, SHA-256
  `d1b3f7a91fbe07d11f9100346f0ef65f0e3576d35dcf27708f585bb5e6ca038a`;
- publication repository basis `RMF112018/my-pa`, `main`,
  `195fa54206996dddd6c6e0b6da0872781aa4f5f0`; the re-mirror occurs after the
  documentation-only `D-104` merge at `7ae3917b7d95548883211aa64a12edf99351e59a`.

The control folder is `1PLw2r7MmNXKi2pZxaIRiXTNVg-itiZ99`. Following the
existing Native Reminders policy, four raw control records are mirrored and the
coordination request and response remain external:

| Control artifact | Drive ID | Bytes | SHA-256 |
|---|---|---:|---|
| Canonical artifact disposition | `1vCigEEP3Rmj60-ukkLze37pU0BXmj7Lg` | 12,568 | `08f62eec99e8ae8b369e248c2fa1efa451c3bb34a965316dc8d2670d9676e15f` |
| Publication receipt | `1N-Jduf-hXcpH-kugP9HsxnqVsau4QONU` | 5,309 | `b6dc9d02471407a53cd5308b67903677aeb500e7c516bde9c9f407946d2cedab` |
| Readback verification | `1qFk2KVI217QxIM5X7FwYD533g_VZSUX5` | 11,873 | `a1e193d36d9436f6b473924e6182c5351fba2698301b20875d81763471f70bc4` |
| Coordination roundtrip receipt | `15th9q7BiMQpzZqi5YKedadBbeBH33KoW` | 5,116 | `ce1b25b75d53cb355270c52011614233c5050ef501f9acc3cba2d221c9d6f8c0` |

### Scope disposition

Version 2.3 adds the Native Apple Personal Data Capture Bridge, user-facing
**Apple Mail, Calendar & Contacts**, feature package
`MYPA-NATIVE-APPLE-PERSONAL-DATA-CAPTURE-BRIDGE-FEATURE-PACKAGE-20260804-087`
at Drive folder `13jS8vmsWHvwQQqPksNlwW5r2whH8V8Z5` (manifest Drive ID
`1gBPfHAtPClqFoT7skQJlpp9Sf2L72q_J`, publication receipt Drive ID
`1ATS9ONwZmA9Ar1_-sHaxCKcRUUwvoOqT`). The canonical roadmap calls its sequence
WP-12 and the MVP definition calls it conditional MCV scope.

Those product statements do not grant repository implementation authority.
The authority evidence is precise but not uniform. The numbered canonical
artifacts carry their own implementation-not-granted blocks. The disposition's
narrower authority block denies implementation, live access, source mutation,
deployment, production, and risk acceptance. The readback asserts only
`implementation_authority_not_granted: true`. The publication and roundtrip
receipts carry the fuller denial list for implementation, live personal data,
TCC/credential mutation, source mutation, deployment/watchers, production
activation, external-model disclosure, destructive retention, and risk
acceptance. The operator first identified the feature as provisional WP-12
after WP-10 and WP-11, which `D-105` preserves as historical provenance. The
later direct authorization `AUTH-WP12-20260804-OPERATOR-001` resolves that
sequencing hold for WP-12 only: `D-106` promotes bounded synthetic repository
implementation ahead of WP-10/WP-11. `D-104` still defers WP-10 until MCV
completion, and WP-11 still depends on WP-10. Live Apple access,
TCC/credentials, signing, installation/watcher activation, external disclosure,
source mutation, destruction, deployment/production, and risk acceptance remain
unauthorized. `D-107` separately records the future full-MVP handoff after
independently verified MCV completion; it does not start that campaign now.

The ten `NAPDCB-OP-001` through `NAPDCB-OP-010` decisions remain in the
canonical package's own ledger. Like `NAR-OP-*`, they are excluded from section
14's three-ledger counts and none is answered here.

### WP-12C implementation checkpoint — 2026-08-05

Slice C now has a bounded synthetic-only application admission and control
implementation for its eleven final criteria. Its local PR-tier evidence is
complete: 467 database/recovery/e2e tests passed against a separate disposable
PostgreSQL 17 database, and 2,950 FAST tests passed. Slice C still requires a
green PR rerun and independent review of the corrected exact head, so this
checkpoint does not declare Slice C complete. The first independent review
returned `BLOCK` with six findings; a corrective rereview found one call-order
defect; the next precommit rereview passed pending database CI; and the PR source
review then found request-ID and composite-locator binding defects. All reports
remain preserved. A subsequent corrected-manifest review found that admission
status could commit before response acceptance and final current-scope
validation. The bounded correction now rejects response-identity mismatch
before any write, commits reachable status atomically with final locked
authority validation, consumption, and evidence, and records an operational
preflight denial only after the same current-scope validation without consuming
the authority. Focused unit and architecture regressions pass, the full Slice C
admission schema file passes ten tests, and the exact database/recovery/e2e tier
passes 467 tests against disposable PostgreSQL 17. A green PR-CI rerun remains
mandatory. The correction also binds preflight to the exact request and `(kind,
account, bucket)` locator, retains serialized scope/admission and durable exact
authority, and repairs historical migration and disposable-test isolation
without weakening the authority-to-audit foreign key. Native-host
operation, baseline execution, watchers, frontend routes, live Apple access,
and every other Slice E/F/G/H behavior remain absent or deferred. The
machine-readable disposition is
`.ai/goals/wp-12-apple-mcc/slice-c-implementation-checkpoint.json`.

### Invalidation

This reconciliation binds the 21 numbered artifacts and four selected controls
to the exact raw hashes above. Any later canonical artifact revision, Drive-ID
or parent change, manifest mismatch, superseding feature decision, or explicit
operator scope/authority decision invalidates the affected statements and
requires fresh raw readback and re-reconciliation. A green repository hash test
proves only that the mirror matches these receipts; it does not prove Drive has
not changed again.
