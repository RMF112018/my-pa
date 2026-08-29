# Relationship Intelligence — implementation plan and acceptance ledger

**Objective.** Build the Relationship Intelligence entity plane admitted to MCV
scope by the operator's 2026-08-01 reprioritization (`AGENTS.md` sections 1 and
3).

**Specification.** [`docs/specs/relationship-intelligence-v0.2.md`](../specs/relationship-intelligence-v0.2.md)
remains this plan's requirements source.
[`docs/specs/relationship-intelligence-v0.3.md`](../specs/relationship-intelligence-v0.3.md)
is **DEMOTED as of 2026-08-20 and governs nothing.**

**The operator's decision, recorded.** Asked what v0.3 was, the operator answered
that they do not know where it came from, and directed that it be demoted. That
settles a question three review rounds had circled: the document has no publisher
receipt (unlike v0.2, which was fetched by `rclone` and hashed against one), its
`governing_plan` and `governing_audit` identifiers appear nowhere in this
repository, and an agent wrote it into the tree and rewrote this plan to cite it
— outside any instruction the operator or the session had given. Its own front
matter already read `status: PROPOSED_SUCCESSOR_READY_FOR_OPERATOR_REVIEW` and
`implementation_authority: false`, so no operator decision to supersede v0.2 had
ever been recorded; none is coming.

**What that changes here.** Nothing below is scored against v0.3. Section 3 is
this campaign's ledger and is scored against v0.2. Where a work-package number
in section 0.1 quotes a v0.3 requirement, it quotes a document that governs
nothing and is retained only so the reader can see what was compared.

**What it does not change.** The program-scale fixture and
`tests/database/test_program_scale_acceptance.py` stay. They were built to
requirements v0.3 stated, and they earn their place on evidence rather than on
authority: they prove the resolver holds at 748 entities against real SQL, where
the hand-labelled corpus proves it at 23 against an in-memory double. A test is
worth what it demonstrates, not what commissioned it. Neither document carries implementation authority;
the authorization for the work recorded below is the operator's 2026-08-01 scope
reprioritization in `AGENTS.md`, and nothing else.

**Corrected 2026-08-19.** This paragraph read "v0.3 … is the controlling
requirements source" and called v0.2 "superseded lineage evidence … **no longer
this plan's requirements source**", citing the successor notice at the top of
v0.2 as its support. The notice says the opposite, and the notice is right: it
states in terms that "v0.3 is not yet controlling, and this notice does not make
it so", and records that an earlier draft of itself made exactly the claim this
paragraph then repeated. Citing a document as authority for the reverse of what
it says is the same defect as a stale count, one layer up. The same paragraph
also quoted v0.3's field as `implementation_authority: NOT_GRANTED`; the file
reads `false`.

**What this does not change.** Section 0 below still reads the repository
against v0.3's `WP-RI-00 … WP-RI-13` map, and that reading is still worth having
— a proposed successor is the best available statement of where this plane is
going, and measuring against it is how the gap gets known before an operator is
asked to decide. Section 0 is a *gap analysis against a proposal*, not a
compliance ledger against a controlling document, and it is labelled that way
throughout.

**Out of scope for every work package here**, and a mandatory stop if
approached: production deployment or activation, shared or production database
operations, live personal-data traversal, credential or OAuth mutation, live
Abacus/ChatLLM Task changes, destructive actions, and operator risk acceptance
(`AGENTS.md` sections 5, 8.2 and 9).

---

## 0. Gap analysis against the proposed v0.3 work-package map (`RI-PR135-BLOCKER-001`)

Independent audit `AUDIT-MYPA-RELATIONSHIP-INTELLIGENCE-PR135-20260819-001`
(disposition `CORRECTIONS_REQUIRED`, bound to head
`d5861e928b0f6da48cf32f0445292b694879aaac`) found that this campaign — the one
recorded in sections 1 through 5 below — cited
[`relationship-intelligence-v0.2.md`](../specs/relationship-intelligence-v0.2.md)
as its requirements source and then defined its *own* `WP-RI-01 … WP-RI-13`
work-package map and its *own* first-forty acceptance ledger against that
citation, rather than against the numbering v0.2 itself carries. Meanwhile
[`relationship-intelligence-v0.3.md`](../specs/relationship-intelligence-v0.3.md)
— a materially different program-scale specification with its own
`WP-RI-00 … WP-RI-13` and its own `RI-AC-001..040` (section 21 there) — was
being prepared as v0.2's successor. Several work packages that v0.3 defines were
substituted with narrower tasks bearing the same numbers and then marked
`complete`. That is `RI-PR135-BLOCKER-001`, and this section addresses it by
reading the repository against v0.3's map.

**Corrected 2026-08-19: this paragraph said v0.3 was "the plan that was actually
controlling at the time".** It was not, and it is not now. v0.3 was created
2026-08-17, after the campaign below was largely built, and it has carried
`status: PROPOSED_SUCCESSOR_READY_FOR_OPERATOR_REVIEW` from its creation until
the operator demoted it on 2026-08-20, since when its own banner has read
"DEMOTED 2026-08-20 — not a requirements source". A specification cannot have been retroactively controlling over work that
predates it, and a proposal the operator has since demoted is not controlling over
anything. What the audit legitimately found is the substitution — a campaign
that invented its own numbering and its own forty criteria and then reported
against those — and that finding stands on its own without the retroactive
claim. The word "controlling" is used below only where this document is quoting
what v0.3 requires *of a future implementation*; it is not a statement that v0.3
governs the record now.

**What this section does not do.** Sections 1 through 5 below are **not
renumbered in place.** Every `WP-RI-NN` and every `D-RI-NN` from here to the end
of this document refers to the numbering this campaign invented against v0.2 —
call it the *legacy numbering* — and every cross-reference between those
decisions is still internally consistent under it. Renumbering those sections
to match v0.3's map would silently rewrite what the campaign actually
believed it was building at the time and would break every `D-RI-NN` citation
below without changing a single line of `src/`. What this section is: a reading
of the same repository against v0.3's map, with the legacy numbering cited
wherever the two overlap so a reader can find the evidence either way.

**Reading rule for the rest of this document.** Wherever section 3's ledger,
section 4's decision log, or section 5's gap list say a criterion or a decision
belongs to "`WP-RI-08`" or any other legacy number, that is the legacy
numbering's own package, not v0.3's package of the same number. The table
below is the map to use going forward if and when v0.3 is accepted;
[`relationship-intelligence-v0.3-acceptance.md`](../specs/relationship-intelligence-v0.3-acceptance.md)
carries the disposition against v0.3's `RI-AC-001..040`, and section 3 of this
document carries this campaign's own substituted forty.

**"Controlling" as this section uses the word.** In the table below,
"controlling WP-RI-NN" names *the requirement v0.3 states under that number* —
the thing a future implementation would have to satisfy — and never asserts that
v0.3 governs this repository today. It does not; see the correction above and
the successor notice at the top of v0.2. Read every row as "what v0.3 would ask
for, and what is actually here", which is what each row is.

### 0.1 v0.3's `WP-RI-00 … WP-RI-13`, read against the repository as it stands today

| v0.3 WP | Requires | What the repository actually has | What remains |
|---|---|---|---|
| **WP-RI-00** — reauthentication, lineage reconciliation, contract freeze | A repo-truth note bound to exact head/tree, a v0.2→v0.3 lineage matrix, an existing-primitive reuse map, an exact migration baseline, a file/module impact map | Nothing filed under this label anywhere in the repository. This T1 remediation cycle — this section, [`relationship-intelligence-v0.3.md`](../specs/relationship-intelligence-v0.3.md), and [`relationship-intelligence-v0.3-acceptance.md`](../specs/relationship-intelligence-v0.3-acceptance.md) — is the closest thing to it that exists, produced after the fact rather than before implementation | The forward-looking half: an exact migration baseline and file/module impact map stated *before* further work, not reconstructed *after* it. Outstanding |
| **WP-RI-01** — domain model and additive migration | `Entity`, `ExternalIdentifier`, `Assignment`, `EntityRelationship` (or equivalent) as an additive schema change | Delivered, and a close match. `src/my_pa/domain/relationship/entity.py` (`Entity`, `ExternalIdentifier`, `EntityAlias`, `Assignment`, `EntityRelationship` dataclasses; closed `EntityType`/`EntityStatus`/`AliasType`/`AssignmentType`/`EntityRelationshipType` enums) against migration `9def3c2e63bb`. This is legacy `WP-RI-01` and the two maps agree here | Nothing controlling-specific outstanding at the domain-model layer itself; see WP-RI-02 for what sits on top of it |
| **WP-RI-02** — repository/service layer and typed contracts; principal-derived, centrally authorized, idempotent writes, expected-version concurrency, deterministic receipts, audit events | A repository port and implementation with those five properties on every write | Partially delivered, filed under legacy `WP-RI-01`/`WP-RI-02` together. `EntitiesRepository` port, `SqlEntityRepository` (`src/my_pa/infrastructure/persistence/entity.py`), the `UnitOfWork.entities` seat, and a Principal-partitioned in-memory fake exist, and every method takes `principal_id` first. Idempotency is real for `bind_identifier` and `record_alias` against a natural key | Idempotency is **not** general: `create`, `record_assignment`, and `record_relationship` are idempotent only against an identifier the caller already minted, so a retry that mints a fresh one double-writes (`RI-AC-036`, and the legacy document's own section 5 names the `record_assignment`/`record_relationship` half of this). There is **no `update` method on the repository at all**, so `version` is stored on `Entity` and `EntityRelationship` but nothing checks an expected version against it — expected-version concurrency has nothing to guard yet. No receipt is emitted by any write path, and no audit event is emitted outside the security/isolation tests that assert its *absence* of leakage rather than its presence as a record. All four are outstanding |
| **WP-RI-03** — exact identity and alias resolution | Stage 1 of the resolution contract: exact stable-identifier and verified-alias matching, effective-date filtering, same-name protection | Delivered, close match. `src/my_pa/application/entity_resolution.py` Stage 1/Stage 2; `tests/unit/test_entity_resolution.py`, `tests/database/test_entity_repository.py`. This is legacy `WP-RI-03` and the two maps agree | Nothing controlling-specific outstanding |
| **WP-RI-04** — contextual resolution and explainability; false resolution is release-blocking | Stage 3/4 of the resolution contract: ranked candidates, explainable evidence, a measured false-resolution rate | Delivered, close match, and strengthened by the currency fix recorded in section 4a — which is committed at this head, not uncommitted as this cell said until 2026-08-19. Contextual ranking is ordinal — `ResolutionBasis` ordering, not a numeric score — and calibration is published in `tests/evaluation/RESOLUTION_CALIBRATION.md`, which reports 35 cases in 20 families. This is legacy `WP-RI-04` and the two maps agree. See section 0.2 below for the tension between this design and v0.3's word "ranked" | The corpus this is measured against is far below controlling WP-RI-12 scale; see that row. The false-resolution rate is real evidence over a small, synthetic, collision-biased corpus — not yet evidence at program scale |
| **WP-RI-05** — MCP read/resolve/context surface with bounded output and pagination | Six read capabilities, each bounded and paginated | Delivered in full. **Superseded 2026-08-20:** this cell said pagination was delivered for one of the two capabilities that need it, and both halves of that are now out of date — `entities.search` is paged, and a third read needs paging because `entities.unresolved_mentions` exists. Six `Capability` members (`ENTITIES_SEARCH/GET/RESOLVE/CONTEXT/RELATIONSHIPS/UNRESOLVED_MENTIONS`), the `entity_read` purpose, the composition gate, remote-exposure withholding (`tests/contract/test_entity_remote_exposure.py`). `entities.relationships` is now genuinely paginated: `GetEntityRelationships` takes `page_size` **and `after`**, `SqlEntityRepository.relationships` takes `after_relationship_id` and keysets on `relationship_id >`, and the disclosure issues `next_cursor` only when the page was truncated (`src/my_pa/application/commands.py`, `application/service.py`, `infrastructure/persistence/entity.py`; `tests/contract/test_entity_read_bounds.py`). `SearchEntities` takes `page_size` **and `after`**, keyset on `(canonical_name, entity_id)`, and `ListUnresolvedMentions` the same on `observation_id`. All three paged reads **refuse a cursor naming a record the caller cannot read** rather than answering an empty page, which is the shape of wrong answer this plane refuses elsewhere; that rule reached `search` first and its two siblings on 2026-08-20, after an independent reviewer found the commit claiming it without qualification had applied it once | Nothing for this work package. The three reads that page do; the three that do not need none — `entities.get` and `entities.context` each answer about one named entity, and `entities.resolve` returns a candidate set bounded by design that would be wrong to page through. Corrected 2026-08-19: this row read "**No pagination**: there is no cursor or offset parameter anywhere in the search contract", which was true when written and was left standing after the sibling track landed the `entities.relationships` cursor it told the reader to watch for |
| **WP-RI-06** — observation, proposal, review, and merge workflows; review integrated into the *existing* review plane; merge preview; transactional redirect; audit and receipt; replay protection; expected-version checks; scheduled agents excluded from merge apply | A governance service reachable by some caller, whose review path is the repository's one review mechanism | **Completed by Phase B and RI final completion.** Entity and Relationship Memory candidates appear on canonical `review.list` and all governed dispositions run through `review.decide`; ordinary accepted proposals promote through canonical services, while accepting an identity-correction proposal produces a handoff and does not mutate identity. Operator-only merge and split preview/apply paths are composed; split consumes the exact recorded inverse of one completed merge, including Relationship Memory effects. All nine v0.2 re-enrichment triggers have production registration paths. Remote identity correction remains off by default and requires global remote writes plus an exact server-resolved `remote.operator` durable capability set and all ordinary gates | The broader `WP-10` discovery/backfill framework, frontend, live grants/flags, production/runtime commissioning, WP-08/WP-09 execution, deployment, and live data remain outside this completed work package |
| **WP-RI-07** — context-card and managed-context integration; `context.prepare` exposes an entity/relationship retrieval plane, Principal-scoped, bounded, provenance-referenced, no promotion side effects | The context card composed into `context.prepare`'s actual retrieval path | The card itself is delivered and well-tested standalone (`src/my_pa/application/entity_context.py`, `domain/relationship/context_card.py`; `tests/unit/test_entity_context.py`, 9 tests). **It is not wired into `context.prepare`.** Confirmed directly: `src/my_pa/application/context/providers.py` declares `ContextPlane.RELATIONSHIP` as a plane, and both `_PLANE_GRANT_CAPABILITIES[ContextPlane.RELATIONSHIP]` (an empty `frozenset`) and `search_plane` return `_relationship_unavailable()` unconditionally for it, reporting `CoverageState.NOT_ADMITTED`. The module's own comment states the reason: *"Relationship has no read capability in this work package and stays omitted under a remote grant set rather than reported as denied."* `context.prepare` therefore never calls the entity plane at all, in any mode | The actual composition: a `context.prepare` path that calls `EntityContextService` when the query names a person/company/project/entity, subject to the same bounds and provenance rules the card already enforces standalone. Outstanding in full |
| **WP-RI-08** — discovery and backfill framework: deterministic, resumable, idempotent, proposal-first; synthetic adapters only; enumerate authorized evidence, extract stable identifiers and candidate names/orgs, resolve against the registry, record occurrence observations, generate proposals, maintain a run ledger with cursor/checkpoint/idempotency/failures/coverage, produce review-backlog metrics | The final-completion campaign superseded the former two ad-hoc `after_merge`/`after_alias` passes with a durable invalidation queue. Seven v0.2 triggers are registered from truthful authorized mutation paths; source-version and model/rule-version changes are registered only by exact version-observation hooks after a verified source fetch or a newly created authenticated proposal. That mechanism deliberately does not enumerate sources, extract candidates, or implement a discovery/backfill run ledger. | The discovery/backfill framework remains outstanding. Durable re-enrichment invalidation is complete supporting infrastructure, not evidence that this separate framework exists. |
| **WP-RI-09** — Bobby-facing management experience: global entity search, entity detail with disambiguators, current/historical assignments, evidence/provenance inspection, review of proposals/conflicts, alias/identity correction, merge preview (CLI/conversational/operator-API acceptable; a broad CRM UI is not required) | Any one authorized surface covering that minimum capability list | What legacy section 1 calls "`WP-RI-09` — Read-only operator inspection" is `scripts/inspect_entity_plane.py`: a read-only reporting CLI over row counts, grouped counts, an unresolved-mentions count, and a listing of open proposals (with `proposed_by` deliberately not selected, per legacy adversarial finding 10). It takes a required `--principal` argument and prints counts and closed-set names. It has **no search-by-text function, no entity-detail view, no assignment listing, no alias/identity-correction path, and no merge preview** — it is a monitoring report, not a management surface, and does not cover the controlling minimum. It is correctly filed here as read-only inspection tooling in support of an operator, not as WP-RI-09's deliverable | Every item in the controlling minimum capability list except aggregate counting. Effectively fully outstanding — this needs a real (even minimal, CLI- or conversational-only) management surface, which section 25 item 5 of the controlling spec leaves open as an operator decision |
| **WP-RI-10** — intelligence-task integration: Meeting Intelligence attendee/mention resolution, Action & Commitment counterparties, Watch List, Morning Brief; canonical entity IDs attach without those tasks becoming alternate identity authorities | Canonical entity IDs actually attached to at least one of those four intelligence tasks | Nothing. What legacy section 1 calls "`WP-RI-10` — Dormant intelligence-Task profile" is `src/my_pa/bootstrap/relationship_intelligence_task.py`: a capability-grant *profile* for a hypothetical future scheduled Task, `DRAFT_NOT_ACTIVATED`, granting the same five reads and nothing else. It is correctly filed under controlling **WP-RI-11** (security/authorization posture for a not-yet-existing task identity) rather than under WP-RI-10, because it integrates with nothing — there is no Meeting Intelligence, Action & Commitment Intelligence, Watch List Intelligence, or Morning Brief module anywhere in `src/my_pa/` for it to attach an entity ID to. `application/commitments.py` exists and has zero references to `entity` anywhere in it | All four integrations, in full. There is currently no attachment point in this repository for any of them — this is not a partially-done integration, it is an absent one |
| **WP-RI-11** — security, privacy, authorization, adversarial testing | Principal isolation, impersonation rejection, minimal-disclosure, adversarial coverage | Delivered, and substantive. `tests/security/test_entity_privacy_regression.py` (96 tests — corrected 2026-08-19 from 11, again 2026-08-20 from 19, again from 26, again 2026-08-23 from 40 when `WP-RI-A-02` widened the derived sweep to the plane's writes, again from 64 when Phase A's other two write packages joined the same derived sweep, again 2026-08-24 from 84 when `WP-RI-B-05` and `WP-RI-B-06` added three more names, and now for final completion's three names, each time by `--collect-only -q` on the file: cross-Principal disclosure denial, name-as-instruction injection resistance, judgement-free answers, task-profile draft/gating checks, a derived completeness guard over the plane, and the alias non-disclosure rule on both the plain and paginated search paths) and `tests/security/test_cross_principal_relationship_isolation.py` (8 tests: foreign-read-as-absent, cross-Principal merge/decide refusal, caller-supplied-Principal rejection, partition non-mutation). This is legacy `WP-RI-11`, and the two maps agree here | Adversarial coverage for the write paths that do not yet have a caller (WP-RI-06) has nothing to exercise yet; revisit once WP-RI-06's caller exists |
| **WP-RI-12** — program-scale synthetic acceptance and performance: ≥500 persons, ≥100 organizations, several programs/projects/work packages, ≥5,000 combined aliases/identifiers/assignments/relationships/observations, ≥50 collision groups, ≥50 historical assignment changes; p50/p95 benchmarks for exact resolve, candidate search, contextual resolution, entity search, context-card assembly, bounded relationship traversal | A fixture and benchmark record at that floor | **The fixture exists, a suite now runs it, and no benchmark exists.** `tests/evaluation/fixtures/program_scale_corpus.py` and `program_scale_cases.py` build 748 entities — **565 persons and 105 organizations**, 6 programs, 24 projects, 48 work packages, which sum to 748 — with 5,262 combined alias/identifier/assignment/relationship/observation records (680 + 910 + 1,250 + 922 + 1,500), 60 collision groups, 80 historical employment changes and 1,090 labelled cases. **Corrected 2026-08-19:** this cell said 500 persons and 100 organizations, which are the lengths of the builder's helper collections rather than entity counts and sum to 678 — in a sentence claiming the figures were derived by loading rather than by reading constants. **Superseded 2026-08-20:** this cell also said, correctly at the time, that the fixture was inert — no test imported either module and no tier executed them, so it proved the same amount as no fixture. `tests/database/test_program_scale_acceptance.py` now asserts the floors against the built rows and answers every labelled case through `SqlEntityRepository` on a disposable PostgreSQL database: zero wrong outcomes, zero wrong entities, zero forbidden candidates, zero omissions, and disabling the conflicted-identifier refusal fails it by case name. The database tier rather than the evaluation tier, because this criterion is about scale and about SQL, and the small corpus's in-memory double exercises neither. `RI-AC-031` and `RI-AC-032` are `MET` accordingly. The hand-labelled corpus is unchanged and still measured separately by `RESOLUTION_CALIBRATION.md` — thirty-five labelled cases over twenty-three entities, collision-biased by construction — and the two answer different questions: that one asks whether the stated refusals hold, this one asks whether they still hold at scale and against SQL. **What remains outstanding is the benchmark half**: `RI-AC-033` asks for p50/p95 across six operations and none exists. The new suite times nothing deliberately — a wall-clock assertion against a shared, contended database measures the machine rather than the code | Every p50/p95 benchmark this work package requires. The fixture is built and now exercised; the benchmark half does not exist |
| **WP-RI-13** — documentation, independent review, rollout package, handoff: current `docs/specs/` RI spec, `docs/planning/` implementation/rollout record, MCP tool documentation, schema/data lifecycle, threat/privacy notes, backfill operator procedure, feature-flag/grant matrix, benchmark results, acceptance matrix, rollback/recovery procedure | Each of the ten named documents, current | Mixed. `docs/specs/` RI spec: v0.2 is the current requirements source and remains so; [`relationship-intelligence-v0.3.md`](../specs/relationship-intelligence-v0.3.md) is mirrored beside it as a proposed successor that the operator reviewed and **demoted on 2026-08-20**, so the "current spec" item is met by v0.2 and the successor governs nothing. Corrected 2026-08-20: this cell said the successor was "awaiting operator review", which had been true and stopped being true when the demotion was recorded in this document's own header. Corrected 2026-08-19: this cell said v0.3 "is now current" and called v0.2 "wrong lineage", which asserted an acceptance v0.3's own front matter says has not happened. Implementation/rollout record: this document, under `docs/plans/` rather than a `docs/planning/` directory — present, but see the reading rule above for what in it is legacy-numbered. MCP tool documentation: no standalone doc; tool semantics are described in prose in this document and in `ops/runbooks/relationship-intelligence.md`. Schema/data lifecycle: no dedicated doc; described piecemeal across this document and the runbook. Threat/privacy notes: `docs/security/threat-model.md` exists and names relationship identity (e.g. `ABUSE-PKL-019`), but is scoped to the original MCV read-only slice and has not been revisited for the entity plane specifically. Backfill operator procedure: does not exist, because there is no backfill framework to operate (see WP-RI-08). Feature-flag/grant matrix: reasonably covered informally by `ops/runbooks/relationship-intelligence.md` sections 1–2. Benchmark results: do not exist (see WP-RI-12). Acceptance matrix: **added by this remediation cycle** — [`relationship-intelligence-v0.3-acceptance.md`](../specs/relationship-intelligence-v0.3-acceptance.md) scores v0.3's `RI-AC-001..040`; section 3 below scores this campaign's own substituted forty and is the record of what the campaign believed it was proving. Neither supersedes the other: the two answer different documents, and v0.3 is not one this repository builds to. Rollback/recovery procedure: not present as a named section; the runbook covers disabling the feature flag but not recovering from a bad migration or a bad merge decision | A standalone MCP tool doc, a schema/data-lifecycle doc, a refreshed threat-model pass scoped to the entity plane, a backfill operator procedure (once WP-RI-08 exists), benchmark results (once WP-RI-12 exists), and a rollback/recovery procedure. Six of ten items outstanding in some form — the six named in this cell's remaining column; two corrected by this cycle |

### 0.2 A tension v0.3 and this repository resolve differently, on purpose

v0.3 section 9.2 asks contextual resolution to perform "Stage 3 —
contextual ranking," and `RI-AC-005` asks it to return "ranked alternatives."
`tests/architecture/test_relationship_scoring_surface_is_denied.py` denies the
token `rank` (along with `score`, `percentile`, `priority`, `influence`, and a
closed list of similar stems) anywhere on the relationship/entity surface —
table columns, dataclass fields, and enum members alike, matched whole-token
against live schema and source, not just against a hand-maintained list. Both
sides are real and neither was weakened to accommodate the other. The resolver
satisfies "ranked" and "contextual ranking" through `ResolutionBasis` ordinal
ordering instead of a `rank` or `score` field: `_BASIS_ORDER` fixes
`VERIFIED_EXTERNAL_IDENTIFIER < EXTERNAL_IDENTIFIER < ALIAS < CANONICAL_NAME`
as a closed evidence-type ordering, and candidates sort on that ordinal with a
stable `entity_id` tiebreak (`src/my_pa/domain/relationship/resolution.py`).
That produces a deterministic, explainable order over alternatives — which is
what both the spec's plain-language "ranked" and `RI-AC-005`'s "explainable
match features" actually ask for — without a numeric likelihood the scoring
prohibition exists to keep off this surface (legacy `D-RI-02`, `D-RI-14`). This
is a considered substitution, not an oversight, and is recorded here so a
future reader does not "fix" one side by breaking the other.

---

## 1. Work packages (legacy numbering — see section 0)

**This table uses the numbering this campaign invented against v0.2, not v0.3's
map.** Read section 0.1 above first.

| WP | Scope | State |
|---|---|---|
| WP-RI-01 | Domain model (`Entity`, `ExternalIdentifier`, `Assignment`, `EntityRelationship`), four identifier prefixes, four tables, Alembic revision `9def3c2e63bb` | **complete** |
| WP-RI-02 | `EntitiesRepository` port, `SqlEntityRepository`, the `UnitOfWork.entities` seat, the in-memory fake, FAST-tier tests | **complete** |
| WP-RI-03 | Exact resolution: alias table, namespace and alias normalization, effective-date filtering, entity-type and scope filtering, conflicting-identifier handling, historical resolution, same-name protection | **complete** |
| WP-RI-04 | Contextual resolution: bounded candidate ranking, calibration, explainable evidence, collision-biased safety, false-resolution evaluation | **complete** |
| WP-RI-05 | The capability and MCP surface: six `Capability` members, the `entity_read` purpose, the forward `ALTER`, commands, handlers, transport builders, scope policy, the composition gate, and a minimal context card | **complete** |
| WP-RI-06 | Observation, proposal, and governed merge/split with lineage | **complete** |
| WP-RI-07 | Context card enrichment: coverage, freshness, and generation identity | **complete** |
| WP-RI-08 | Legacy two-pass re-enrichment | **superseded** by the final-completion durable exact-nine-trigger invalidation mechanism; discovery/backfill scope remains separate and outstanding |
| WP-RI-09 | Read-only operator inspection (`scripts/inspect_entity_plane.py`) | **complete** |
| WP-RI-10 | Dormant intelligence-Task profile, read-only and default-off | **complete** (draft, not activated) |
| WP-RI-11 | Security and privacy regression for the entity plane | **complete** |
| WP-RI-12 | Acceptance evidence against the ledger in section 3 | **complete** |
| WP-RI-13 | Operator runbook (`ops/runbooks/relationship-intelligence.md`) | **complete** |

WP-RI-06 … WP-RI-09 are parallelizable once WP-RI-05 lands. WP-RI-03 must
precede WP-RI-04, and both must precede WP-RI-05.

---

## 2. The core safety rule

> **Ambiguity is preferable to a wrong entity match.**

The specification states this five separate times and never as a single named
rule. Section 15.2: *"Ambiguous mentions remain unresolved rather than forced
into the nearest person."* Section 10.3: *"Ambiguous identity matches remain
unresolved."* Section 15.2 again: *"Names alone are insufficient for automatic
merge"* and *"Conflicting immutable identifiers prevent automatic merge."*
`RI-RISK-001` names a false identity merge as contaminating *"profile,
timeline, commitments, and briefings"* and asks for **precision-first
metrics**.

Two consequences bind WP-RI-03 and WP-RI-04:

* Resolution must return a **typed outcome** with ordered alternatives,
  warnings, and explainable evidence. It must never collapse an ambiguous or
  conflicted result into a generic `NotFoundError`, because "I could not find
  them" and "I found four of them" are different answers and only one of them is
  safe to act on. WP-RI-03 delivers this: `EntityResolution.resolved_entity_id`
  is a derived property that exists only for the two resolved outcomes, so an
  `AMBIGUOUS` answer has no identifier for any caller to read. Calibration — a
  numeric a caller can threshold on — is deliberately *not* part of it, for the
  reason `D-RI-02` gives, and is WP-RI-04's to design with its exemption.
* The false-resolution evaluation in WP-RI-04 is **collision-biased**: the
  fixture is built to make wrong joins likely (same surname, shared employer,
  recycled email local-parts), because a corpus of easy cases measures nothing.
  Delivered as `tests/evaluation/fixtures/resolution_corpus.py` and measured by
  `tests/evaluation/resolution_harness.py`; the frozen result is
  [`tests/evaluation/RESOLUTION_CALIBRATION.md`](../../tests/evaluation/RESOLUTION_CALIBRATION.md).

---

## 3. Acceptance-criteria ledger — RI-AC-001 … RI-AC-040 (legacy numbering — see section 0)

**This ledger scores this campaign's own substituted first-forty criteria,
defined against v0.2, not the `RI-AC-001..040` from
[`relationship-intelligence-v0.3.md`](../specs/relationship-intelligence-v0.3.md)
section 21.** It is preserved below as the record of what this campaign believed
it was proving. The disposition against v0.3's criteria is
[`relationship-intelligence-v0.3-acceptance.md`](../specs/relationship-intelligence-v0.3-acceptance.md).
A reviewer should cite both and neither alone: this section answers the document
that is currently the requirements source under a numbering the campaign
invented, and that document answers a proposed successor that never came into
force. Corrected 2026-08-19: this heading said "superseded" and this paragraph
called v0.3's ledger "the current disposition", which asserted a supersession
that has not been decided.

The specification — v0.2, then and still — declares
seventy criteria (`grep -oE "RI-AC-[0-9]{3}" docs/specs/relationship-intelligence-v0.2.md | sort -u | wc -l` → 70;
the same command over v0.3 returns 40); this campaign tracked the first forty of that document — a
different forty, sharing only their `RI-AC-NNN` numbering with v0.3's
ledger, and answering different questions under most of those numbers.

**The gap, stated rather than left to subtraction (added 2026-08-29).** This
ledger scores `RI-AC-001` … `RI-AC-040`. It does **not** score `RI-AC-041` …
`RI-AC-070` — thirty of v0.2's seventy criteria, and the whole of its upper
half. They carry no status here, not even `OPEN`: nothing in this plan has
assessed them, no work package in this campaign was written against them, and no
statement anywhere in this repository should be read as disposing of them. A
reader taking "forty scored" for "forty of forty complete" would be reading a
completion claim this document does not make and cannot support. Closing that
gap needs a scoring pass against `RI-AC-041` … `RI-AC-070`, which is separate
work and is not authorized here. **A note
that must not be lost:** a substantial share of the v0.2-anchored RI-AC-001 …
RI-AC-040 are product- and interface-level criteria that cannot be satisfied
while frontend implementation remains held by the operator's `D-09`
instruction (`AGENTS.md` section 3, specification section 2.3). They are
carried here as `BLOCKED_BY_D09` rather than quietly recast as backend
criteria — a backend that makes a criterion *possible* has not satisfied a
criterion about what a user sees.

Status vocabulary: `MET` (evidence exists), `PARTIAL` (some evidence, gap
named), `OPEN` (in a work package this campaign has not yet delivered),
`UNMET` (the work package that was to carry it has shipped, and shipped without
it), `BLOCKED_BY_D09` (needs the held frontend),
`NOT_APPLICABLE_TO_THIS_CAMPAIGN` (belongs to another plane).

`UNMET` exists because `OPEN` stopped being true. Nine criteria were routed to
WP-RI-06, WP-RI-07 and WP-RI-10; all three have now landed, and a criterion
still reading "in a planned work package" against a delivered package is a
ledger that quietly converts an unmet criterion into a scheduled one. Each is
restated below against what actually shipped, with the specific missing thing
named rather than a package number. Phase B subsequently moved `RI-AC-008` to
`MET`; the other rows retain their evidence-backed status and named gap.

| ID | Criterion (abridged) | Status | Where |
|---|---|---|---|
| RI-AC-001 | Public language is Relationships / Relationship Intelligence; PRIE historical only | `MET` (backend) | No `src/`, runbook or capability name produced here uses "PRIE"; `ops/runbooks/relationship-intelligence.md` and the capability names use the current label. Corrected 2026-08-19: the universal previously read "no source, doc or runbook", which is false — `mcv-completion-plan.md` uses it and so does this row. Every such use is historical, which the criterion permits, but "no doc" was not the claim to make. User-facing copy is `BLOCKED_BY_D09` |
| RI-AC-002 | Integrated into `my-pa`, not a standalone engine | `MET` | No new process, database, or service; `tests/architecture/test_dependency_direction.py` |
| RI-AC-003 | The product states relationships are not scores | `PARTIAL` | Enforced structurally by `tests/architecture/test_relationship_scoring_surface_is_denied.py`, widened to the entity plane; no numeric reaches the durable surface (`D-RI-14`). The *statement* is WP-RI-13 |
| RI-AC-004 | Value without starting a chat | `BLOCKED_BY_D09` | — |
| RI-AC-005 | Contact/source rows stay observations, not automatic canonical people | `MET` | `EntityGovernanceService.observe` records an observation and can do nothing else; `tests/unit/test_entity_governance.py` asserts no entity appears |
| RI-AC-006 | Unresolved mentions are first-class and searchable | `MET` (backend) | An unlinked `entity_observations` row *is* the unresolved mention, listable via `unresolved_mentions`; resolution answers `AMBIGUOUS`/`NOT_FOUND` over the wire. Surfacing it to a user is `BLOCKED_BY_D09` |
| RI-AC-007 | No identity merge without governed policy | `MET` | `ReviewRequirement.REQUIRES_OPERATOR` refuses an unauthorised accept; the server refuses a decided proposal with no actor (`tests/database/test_entity_governance.py`) |
| RI-AC-008 | Merge preview shows all materially affected records | `MET` | Canonical Review case details expose the proposal and evidence needed for the pre-decision review; accepting an identity-correction proposal still does not merge. Separately, operator-only `entities.merge.preview` computes and persists an exact-version-bound, expiring merge plan and returns affected family/count groups, blockers, conflicts, required choices, and projected effects. `entities.merge` must consume that exact preview and revalidates it before atomic apply. Split is a separate exact-inverse preview/apply protocol, not a hidden merge side effect. Local and gated `remote.operator` MCP callers are composed; remote writes remain off by default |
| RI-AC-009 | Merge and split history preserved and correctable | `PARTIAL` | Final completion adds `entities.identity_history` plus operator-only `entities.split.preview`/`entities.split`. Split preserves the completed merge and appends a semantic inverse operation/effect ledger with fresh monotonic concurrency tokens; it does not erase lineage. The criterion remains `PARTIAL` because broader user-facing/history outcomes remain outside this backend completion, not because split is absent |
| RI-AC-010 | Negative identity evidence prevents repeated false matches | `UNMET` | WP-RI-06 brought the record it needed — a rejected proposal persists as `EntityProposalState.REJECTED` — but nothing reads it back. `EntityResolutionService` consults entities, aliases and identifiers and never proposals, so a rejected merge does not stop the same pairing being proposed again. The gap is a read, not a table |
| RI-AC-011 | Every material profile statement links to evidence or is marked | `PARTIAL` | The context card carries its observations and per-source `coverage`, and marks what it left out (`ContextCardLimitation`, including `COVERAGE_COUNTED_A_BOUNDED_SAMPLE`). But an alias, an identifier and an assignment on that card carry no link to the observation that evidenced them — no column relates them — so those statements are neither linked nor marked |
| RI-AC-012 | Source facts / notes / assertions / inferences structurally distinct | `PARTIAL` | `ObservationKind` distinguishes kinds of *source record* (contact row, message participant, calendar attendee, document mention, user statement). It does not distinguish a source fact from an assertion or an inference: nothing in this plane records an inference at all, so the distinction is unmade rather than made wrongly |
| RI-AC-013 | Coverage, freshness, exclusions appear before synthesis | `MET` (backend) | The card carries `coverage` per source, `most_recent_observation_at`, `assembled_at`, and `limitations`, ordered before the records. Presentation is `BLOCKED_BY_D09` |
| RI-AC-014 | Stale evidence never presented as current | `PARTIAL` | Resolution answers `HISTORICAL_MATCH` with `ENTITY_IS_NOT_CURRENT`/`ENTITY_HAS_BEEN_MERGED_AWAY`, and filters evidence by effective date under `as_of` (WP-RI-03). Briefing-level staleness is WP-RI-07; presentation is `BLOCKED_BY_D09` |
| RI-AC-015 | Contradictory evidence preserved, not collapsed | `PARTIAL` | Preserved, and one contradiction is surfaced: an identifier claimed by two entities answers `CONFLICTED_IDENTIFIER` rather than picking one (`tests/unit/test_entity_resolution.py`). Nothing is ever deleted or merged away silently. But contradiction *between observations* — two sources disagreeing about a name or an affiliation — is stored and never detected or presented as a contradiction |
| RI-AC-016 | Briefings retain evidence scope and model identity | `PARTIAL` | The context card carries `assembled_at` and per-source `coverage`. No briefing and no model exist to attribute — `NOT_APPLICABLE` until one does |
| RI-AC-017 | Person profile exposes the full record set | `BLOCKED_BY_D09` | — |
| RI-AC-018 | Timeline distinguishes event / effective / observed / recorded times | `PARTIAL` | `effective_from`/`effective_to` and `created_at`/`updated_at` exist; the four-clock model is WP-RI-06 |
| RI-AC-019 | Profile navigation preserves context and return state | `BLOCKED_BY_D09` | — |
| RI-AC-020 | Organization profiles support time-aware associations | `PARTIAL` | The schema is time-aware; the profile is `BLOCKED_BY_D09` |
| RI-AC-021 | Commitments retain obligor, beneficiary, outcome, source, lifecycle | `NOT_APPLICABLE_TO_THIS_CAMPAIGN` | The commitment plane already exists (WP-TM-05) |
| RI-AC-022 | Commitments and tasks remain distinct | `NOT_APPLICABLE_TO_THIS_CAMPAIGN` | Existing planes |
| RI-AC-023 | Extracted commitments require review initially | `NOT_APPLICABLE_TO_THIS_CAMPAIGN` | Existing review plane |
| RI-AC-024 | Fulfillment retains evidence or explicit confirmation | `NOT_APPLICABLE_TO_THIS_CAMPAIGN` | Existing planes |
| RI-AC-025 | Commitments by and to a person separately visible | `UNMET` | WP-RI-10 delivered the dormant Task profile and the privacy regression suite; neither touches commitments. No column, query or capability relates an entity to a `commitments` row in either direction. This is a join this campaign did not build |
| RI-AC-026 | Follow-ups distinct from commitments | `NOT_APPLICABLE_TO_THIS_CAMPAIGN` | Existing planes |
| RI-AC-027 | Meeting briefing identifies attendee ambiguity and unavailable evidence | `UNMET` | WP-RI-07 delivered both halves *as parts*: `entities.resolve` names attendee ambiguity (`AMBIGUOUS`, ranked alternatives, warnings) and the card names unavailable evidence (`NO_SOURCE_HAS_BEEN_OBSERVED` and the other limitations). There is no meeting briefing to assemble them into, and nothing reads a calendar event |
| RI-AC-028 | Deterministic meeting context usable when AI is unavailable | `PARTIAL` | The determinism half holds: `EntityContextService` calls no model, takes its clock as an argument, and returns the same card for the same rows — so the context that exists is fully usable with AI unavailable. The *meeting* half does not exist; the card is assembled per entity, not per event |
| RI-AC-029 | Briefing claims navigate to source evidence | `BLOCKED_BY_D09` | — |
| RI-AC-030 | Post-meeting capture creates proposals without changing source events | `PARTIAL` | The proposal plane exists and writes no source; no capture pipeline feeds it yet |
| RI-AC-031 | Quick Note / Call launchable in-app and from device shortcuts | `BLOCKED_BY_D09` | — |
| RI-AC-032 | One general input field required before save | `BLOCKED_BY_D09` | — |
| RI-AC-033 | Original input durably stored before enrichment | `NOT_APPLICABLE_TO_THIS_CAMPAIGN` | Quick Capture plane (ADR-003) |
| RI-AC-034 | Enrichment failure does not lose or block the capture | `NOT_APPLICABLE_TO_THIS_CAMPAIGN` | Quick Capture plane |
| RI-AC-035 | Participants, commitments, sensitive facts, dates follow review policy | `PARTIAL` | Identity proposals require review and merges require an operator; commitments and sensitive facts belong to their own planes |
| RI-AC-036 | Repeated processing does not duplicate structured records | `PARTIAL` | `bind_identifier` and `record_alias` are idempotent against a natural key; re-enrichment passes are idempotent and tested twice-run. `record_assignment`/`record_relationship` remain idempotent only against their own identifier — a retry minting a fresh one still writes a second row |
| RI-AC-037 | Capture corrections retain immutable before/after evidence | `NOT_APPLICABLE_TO_THIS_CAMPAIGN` | Quick Capture plane |
| RI-AC-038 | AI output carries an authority class | `UNMET` | Nothing in this plane produces AI output — every capability is a deterministic read — so there is no output here to class. The criterion becomes live for whatever first generates a statement about an entity, and this campaign built no such generator. Recorded as unmet rather than not-applicable: the plane is what such a generator would read from |
| RI-AC-039 | Models cannot merge identities or promote inferences autonomously | `MET` | `propose` cannot apply; `accept` refuses a merge without declared operator authority; both mutations were mutation-tested |
| RI-AC-040 | No external action occurs through a relationship knowledge write | `MET` | The plane's writes (`WP-RI-A-02`) reach `knowledge.entities` and nothing outside it, and there is no connector; the Task profile grants a subset of the reads, withholding the unresolved-mention queue deliberately. `tests/security/test_entity_privacy_regression.py` asserts a name that reads as an instruction reaches no tool description and gains no capability |

**Tier discipline.** A criterion requiring MCP, integration, canary, or live
evidence is not satisfied by a FAST-tier unit test. RI-AC-036 in particular is
a database-tier claim about what the server refuses.

Corrected 2026-08-19: this paragraph said RI-AC-036 was `PARTIAL` "precisely
because no such test exists yet". Database-tier idempotency tests exist and
always have — `test_binding_the_same_external_identity_twice_writes_one_row`,
`test_creating_the_same_entity_twice_writes_one_row`,
`test_recording_the_same_relationship_twice_writes_one_row` — and `git log -S`
puts the tests and that sentence in the *same commit*. It was false the day it
was written and survived three reviews. The criterion is `PARTIAL` for the
reason its own ledger row gives, which is the true one: `record_assignment` and
`record_relationship` are idempotent only against an identifier the caller
minted, so a retry with a fresh one still writes a second row.

---

## 4. Decisions taken, and where they depart from the specification (legacy — see section 0)

Recorded here because each one is a choice a reviewer would otherwise have to
reconstruct from a diff. **"The specification" throughout this section is v0.2,
this campaign's citation and still the requirements source, under a work-package
numbering the campaign invented rather than v0.2's own** — these are genuine
engineering decisions taken while building the code that exists today, and are
preserved verbatim because the code still works this way. Section 0 above reads
the same decisions against v0.3's map, which is where a reader should go to see
what a proposed successor would additionally ask for.

**D-RI-24 — the intelligence Task profile is read-only and dormant.**
`bootstrap/relationship_intelligence_task.py` states which capabilities a
proposed Task may reach: the five reads and nothing else, `DRAFT_NOT_ACTIVATED`,
and empty until the process gate is on. It creates, edits and enables nothing —
live Abacus/ChatLLM Task changes are out of scope for this campaign by explicit
instruction and reserved by `AGENTS.md` section 8.2 regardless. The profile
exists so the answer to "what would such a Task be allowed" is in the repository
before anyone is in a position to grant it.

**D-RI-25 — exact nine-trigger durable invalidation (supersedes the former
two-trigger decision).** Specification section 27.4 lists nine. The
final-completion campaign registers seven from closed, existing authorized
mutation paths and the remaining two from exact source/producer version
observations into Principal-scoped durable work in the same transaction. It
does not reimplement those mutations or grant an invalidation worker identity
authority. Bindings carry exact bounded subject/input/producer/policy versions
and a stable cause identity; retry dedupes on the canonical binding digest.

**D-RI-26 — historical two-pass safety constraints (superseded implementation).**
Two decisions taken after adversarial review, both of the same kind:
a background pass with nobody watching may not make an identity join a watched
one would have refused.

* `after_merge` requires a **recorded merge in that direction and that
  Principal's partition** before it moves a single observation. Its authority to
  re-point someone's evidence at another person comes from an operator's
  decision (section 8.4) and from nothing else; called with two identifiers no
  decision connects, it performed exactly the false join `RI-RISK-001` names —
  silently, with no proposal, no actor, and no lineage row to find it by.
* `after_alias` carries each mention's kind into resolution as an `entity_type`
  constraint where the kind settles it (`KIND_IMPLIES_ENTITY_TYPE`). A contact
  row, a message participant and a calendar attendee are records *of a person*.
  Without the constraint the pass asked only "who is called this", and a
  calendar attendee linked to a project of the same name. `DOCUMENT_MENTION`
  and `USER_STATEMENT` are deliberately unconstrained — a document can name
  anything, and inventing a constraint there would be this module guessing.

Both were mutation-tested while that implementation governed. The durable
exact-nine-trigger mechanism removed those mutation methods; application is now
transactionally fenced by Principal/work locks, database-time lease validation,
pre/post currency checks, savepoint rollback, and binding-digest idempotency.

**D-RI-27 — coverage is computed to a stated ceiling, not from the displayed
page and not without limit.** The context card carries at most
`CONTEXT_CARD_COLLECTION_LIMIT` observations and computes `coverage` from up to
`CONTEXT_CARD_COVERAGE_LIMIT` of them. Both halves matter. Computing coverage
from the twenty-five shown would report "one source" for an entity with four,
which is the claim the card exists to make trustworthy. Computing it from all of
them makes a single read pull an unbounded result set, because observations are
the one collection here that grows with every source record that ever mentioned
someone. When the ceiling bites the card says so
(`COVERAGE_COUNTED_A_BOUNDED_SAMPLE`), so a partial count is never presented as
a complete one.

**D-RI-28 — a decision is a one-time act, enforced by the write predicate.**
`decide_proposal` carries `state = 'proposed'` in its own `UPDATE` predicate
rather than checking before writing. `EntityGovernanceService` already refuses a
decided proposal, but that check reads and then writes — two statements, so two
callers can both read "open". Without the predicate, the second write replaced
`decided_by`, `decided_at` and the reason: the record of who decided and why
became whoever called last, and a *rejected* merge could be re-accepted with
nothing left to show it had ever been refused. A merge record's `proposal_id` is
partition-checked for the same reason — a row citing another Principal's
proposal presents their decision as this Principal's own.

**D-RI-21 — WP-RI-06 registers no capability, and that is the gate.** The
governance plane writes: it links observations, decides proposals, and redirects
merged entities. Specification section 21.4 forbids a model merging identities;
`RI-AC-039` says the same; the carry-forward gate on this campaign says write
methods must not become remote before their authorization gate. So observation,
proposal and merge are reachable in-process — by `WP-RI-08`'s re-enrichment and
by a future review surface — and reachable over no transport at all. A write
capability would need a write purpose, which would put it in
`adapters/mcp/remote._WRITE_PURPOSES` and on the remote surface the moment
writes were enabled, and that is a decision for the work package that has a
reviewer to grant it.

**D-RI-22 — `ReviewRequirement`, not a risk band.** Specification section 12.18
asks a review case for a "risk class"; the scoring prohibition refuses the token
`risk` on this surface. Naming the concept for what it *does* —
`MAY_BE_ACCEPTED_AUTOMATICALLY`, `REQUIRES_REVIEW`, `REQUIRES_OPERATOR` — keeps
the guard intact and is more useful besides: "this needs an operator" is
actionable, where "high risk" is a label somebody still has to translate. It is
derived from the proposal kind rather than stored on the proposal, so a proposer
cannot name its own weakest requirement.

**D-RI-23 — a merge redirects; it never deletes.** Accepting a merge sets the
merged-away entity to `merged_redirect`, points it at the survivor, and writes an
`entity_merge_records` row naming the actor, the reason and the moment. It does
not delete the entity, rewrite its identifiers, or move its observations.
Section 15.3 asks a merge to preserve prior identifiers as lineage and to support
a governed correction path, and an entity that still resolves as a
`HISTORICAL_MATCH` is how both are true at once. Re-pointing the records that
referred to it is `WP-RI-08`.

**D-RI-18 — WP-RI-05 registered all five capabilities at once, including
`entities.context`.** Registering one costs a forward `ALTER` on
`capability_is_known`/`purpose_is_known` plus roughly fifty test registries and
prose counts; splitting the family across two work packages would pay that
twice. So WP-RI-05 delivered a minimal-but-real context card — the records
around an entity, bounded per collection, with every bound that bit named — and
WP-RI-07 enriches it without touching the capability registry. The alternative,
registering four now and one later, would have re-run the whole registration
dance for one name.

**D-RI-19 — one purpose, `entity_read`, for all five.** A purpose of its own
rather than a reuse, on the `TASK_READ` argument: no existing purpose reaches
`knowledge.entities`, and a grant issued to search extracted text has no
occasion to also return who a person is. *One* rather than five, on the
`capture.search` argument (`D-91`): all five read the same rows under the same
authority, so a second read purpose would map to exactly one capability and
separate nothing. There is deliberately no write purpose — this plane has no
write capability, and a purpose no capability permits is denied for everything
and reads as a mistake rather than as a decision.

**D-RI-20 — the plane is off by default, and that is the remote-exposure
gate.** `Settings.relationship_intelligence_enabled` defaults `False`, and
`ApplicationService.available_capabilities` subtracts `_ENTITY_CAPABILITIES`
from what the build serves when it is. This is the mechanism `D-RI-01`
promised, and it is the only one that works: `adapters.mcp.remote.remote_tool_names`
derives the remote profile from `Capability` with no per-capability exclusion
list, so "this build serves it" and "a remote client can reach it" are one
decision. `tests/contract/test_mcp_transport.py` proves the withholding against
a real child process; `tests/contract/test_entity_remote_exposure.py` proves it
about the remote profile specifically, which no existing test reached — the
existing remote test asserts membership by name and so could never have noticed
an *addition*.

**D-RI-01 — WP-RI-02 registers no capability.** The five `entities.*`
capabilities move to WP-RI-05. `adapters/mcp/remote.py::remote_tool_names`
derives the remote profile from `Capability` directly: any non-operator-only
read with a handler and a command **joins the remote MCP surface
automatically**, and there is no per-capability exclusion list to withhold it.
Registering `entities.resolve` before WP-RI-03 and WP-RI-04 exist would put an
unfinished resolution surface on the remote transport, which is exactly what
the carry-forward gate on this campaign forbids. Registering also costs a
forward `ALTER` on `capability_is_known`/`purpose_is_known` plus roughly thirty
test and prose updates, which would then land a second time when the surface
actually changed. Withholding is achieved through the composition gate
`_MANAGED_CAPABILITIES` already proves end-to-end, and WP-RI-05 owns that
decision.

**D-RI-02 — no `confidence` field on this plane.**
`tests/architecture/test_relationship_scoring_surface_is_denied.py` denies the
token outright as "a model likelihood", and specification section 22.3 admits a
numeric *"only when calibrated and explained"*. Sections 12.5 and 12.15 do ask
for confidence on these records, so this is a real departure — but nothing in
WP-RI-01 or WP-RI-02 produces, calibrates, or explains a confidence value, and
weakening a repository-wide prohibition to admit a field no writer fills is the
wrong trade. The work package that first has an evidential confidence to record
makes the argument, adds the exemption, and tests it.

**D-RI-03 — no `provenance` or `observation_id` yet.** Specification section
22.2 requires provenance on every observed and derived record and section 12.2
requires an observation behind every source-bound claim. Neither is modelled
here because neither has anything to bind to: nothing in these work packages
observes a source. The prior draft typed `provenance` as `str` against a `jsonb`
column, which would have stored a bare JSON scalar and made the column
unqueryable; `observation_id` named a table that does not exist. Both arrive
with the observation record in WP-RI-06, bound to the repository's existing
`Provenance` type.

**D-RI-04 — four identifier prefixes at WP-RI-01, not eight.** `ent`, `xid`,
`asn`, `erel`. The prefixes for observations, proposals, and merge lineage are
declared by the work packages that create their tables. A prefix in `IdKind` is
a stability promise, and promising one for a record nothing issues is a promise
about nothing.

**Read as a decision about sequencing, not about the plane's shape.** Those work
packages landed inside this same campaign, so the branch as a whole adds
**eight** — `eals` at WP-RI-03 and `eobs`, `eprp`, `emrg` at WP-RI-06. The title
above says "not eight" about WP-RI-01's diff and would be false as a statement
about the branch; the independent review read it the second way, which is reason
enough to say which is meant.

**D-RI-05 — the alias table arrived with the code that uses it.** WP-RI-02
removed `AliasType` and the port's alias methods rather than leaving them
raising `NotImplementedError`; WP-RI-03 added `entity_aliases`, `EntityAlias`,
`record_alias`/`aliases`, and the resolution that reads them, together. The
unique constraint is `(entity_id, alias_type, normalized_value)` and
deliberately **not** global on `normalized_value`: two real people share a name,
and a schema that made that a conflict would force one of them to be merged into
the other.

**D-RI-06 — `superseded_by_entity_id` is not unique.** The prior draft declared
it `UNIQUE`, which forbids merging two entities into the same survivor — the
ordinary case. Replaced with two named CHECKs: an entity redirects **exactly**
when its status is `merged_redirect`, and it does not supersede itself.

**D-RI-14 — the calibration is a measured table, not a number on a record.**
Specification section 22.3 admits a numeric "only when calibrated and
explained", and `D-RI-02` removed `confidence` from the durable surface because
nothing calibrated it. WP-RI-04 resolves that tension without weakening either
constraint: an answer carries the *basis* it rests on, and
`RESOLUTION_CALIBRATION.md` publishes the observed precision of each
`outcome:basis` pair over the labelled corpus. The number is a counted frequency
rather than a chosen weight, it lives in the evaluation rather than on a record
about a person, and a reader who wants to know what a `RESOLVED_EXACT` on a
verified identifier is worth looks it up. The table is keyed by outcome *and*
basis deliberately: keyed by basis alone it would report `canonical_name: 1.0`,
which would read as though a bare name were sufficient — the exact claim the
plane refuses. `exact_resolutions_on_a_bare_name` is asserted to stay zero.

**D-RI-15 — the safety evaluation runs in the FAST tier, not as a SPECIALIZED
suite.** `tests/evaluation`'s existing harness is `evaluation`-marked, which no
CI job selects. That is right for a suite that exercises a whole retrieval
pipeline and wrong for this one: it is microseconds of pure Python over an
in-memory corpus, and what it protects is the plane's central claim.
`AGENTS.md` section 7 admits a test to the PR gate when it protects a critical
contract at acceptable cost. The frozen record is checked in the same run, so
the published calibration cannot rot.

**D-RI-16 — a recall floor, because "never resolve" would otherwise pass.** Zero
false joins is trivially achievable by answering nothing, so
`resolution_recall` is measured over `MUST_RESOLVE_FAMILIES` and floored at
0.9. Both failure modes are measured, because only measuring both distinguishes
a careful resolver from a useless one. The corpus therefore contains cases that
*must* resolve — a married name, a diacritic variant, a reissued mailbox at two
different moments — and refusing those is as much a failure as joining the two
Alices.

**D-RI-17 — no signal that nothing can reach.** A `SHARES_THE_REFERENCE_IDENTIFIER_DOMAIN`
signal was drafted and removed: contextual signals are computed only on the name
path, which runs only when the identifier lookup found nothing, so a
domain-corroboration signal would have required a person whose *name* is an
email address. Section 15.1 does list "email addresses and domains" as
resolution evidence, and it becomes reachable when observations arrive; it is
not modelled before then. The discriminating/corroborating split went with it,
for the same reason — a classification with one empty half classifies nothing.

**D-RI-11 — a lone name match is `AMBIGUOUS`, not resolved.** The single most
consequential call in WP-RI-03. One entity carries a name and no other does, and
that is still not evidence that a reference means that entity: uniqueness is a
fact about the database, not about the person. So `ResolutionOutcome.AMBIGUOUS`
admits one candidate as well as several, and `EntityResolution` refuses by
construction to report `RESOLVED_EXACT` for a candidate whose strongest evidence
is a canonical name. An alias *does* resolve, because an alias is a recorded
fact about the entity rather than an incidental collision.

**D-RI-12 — email local-parts are not rewritten.** Dot and `+tag` folding is one
provider's rule; applying it everywhere merges two distinct mailboxes at every
other provider. The domain is lowercased (DNS is case-insensitive by
specification) and the local-part is lowercased (universal in this product's
reach), and nothing else is touched. Opaque `vendor_system_id` and
`source_participant_id` values are compared exactly, because their issuers' case
rules are unknown and folding could collide two distinct records. Recorded
because the specification defines no normalization algorithm at all.

**D-RI-13 — `Entity.canonical_name` is expected to hold a normalized name, and
nothing yet enforces it.** Resolution compares a normalized query against that
column by equality, so a writer that stored an unnormalized name would make its
entity unresolvable. The invariant is not in the dataclass because
`domain/relationship/entity.py` and `domain/relationship/normalization.py` would
import each other. It belongs on the write path, and the write path arrives in
WP-RI-06. Carried in section 5 as a known gap rather than assumed.

**D-RI-07 — the resolution outcome vocabulary is an addition, not a
requirement.** The specification contains no per-query resolution outcome enum.
It has a record lifecycle state machine (section 13.1: `unresolved_mention`,
`candidate_match`, `provisionally_linked`, `confirmed_person`,
`duplicate_candidate`, `merge_proposed`, `merged`, `split_proposed`, `split`,
`disputed`, `superseded`). A typed outcome such as `RESOLVED_EXACT` /
`RESOLVED_CONTEXTUAL` / `AMBIGUOUS` / `NOT_FOUND` / `CONFLICTED_IDENTIFIER` /
`HISTORICAL_MATCH` is compatible with the specification and required by its
honesty rules (sections 26.4 and 30.4 both list "unresolved identity" as a state
that must be disclosed distinctly), but it is a design decision this campaign
makes rather than one the specification hands down. WP-RI-03 states the final
vocabulary and its relationship to the section 13.1 states.

**D-RI-08 — capability naming is deferred with its surface.** Specification
section 25 proposes a `relationships.*` family and explicitly calls it *"a
proposed future semantic capability family, not an accepted public API"* that
*"must not be forced into those contracts without a versioned decision."* It
contains no read `resolve` capability at all. WP-RI-05 makes and records that
versioned decision.

**D-RI-09 — the scoring and closed-vocabulary guards now reach this plane.**
Both `tests/architecture/test_relationship_scoring_surface_is_denied.py` and
`tests/relationship/test_relationship_domain.py` selected their population by
the `relationship_` table-name prefix, so the four new tables escaped both. A
plane that stores people, organizations, their assignments and their typed edges
is the relationship surface whatever its tables are called; both now scan
`relationship_`, `entities`, and `entity_`.

**D-RI-10 — `updated_at` is carried.** Specification section 12.1 asks for
"created and updated times". Nothing updates an entity yet, so the column has a
server default and no trigger; the work package that first mutates an entity
sets it.

---

## 4a. Evidence, as executed

Current combined-tree figures below are identified as execution or collection
evidence. Pre-rebase execution evidence is retained only where it is labelled as
such; it is not presented as execution of this rebased tree.

| Claim | Evidence |
|---|---|
| FAST tier validation | `pytest -m "not slow and not database and not network and not connector and not evaluation and not e2e and not recovery"` — this selection collects 14,429 on this tree, so a green run is **14,429 passed**, 0 skipped, 1,601 deselected. Corrected again 2026-08-29 from 14,427 to 14,429: WP-01's family-coverage closure (RI-P2-BLK-001) added two tests beside the ones already counted here. The deselected count moved separately, from 1,597 to 1,601, when WP-01's discovery-side closure (`ef54106`) added four `database`-marked tests, which this selection excludes -- the passed figure this row's own equality checks is unaffected, since `deselected` sits outside `claimed + skipped == collected`. Earlier that same day it read 14,243, measured on the final proposal-token corrective tree before the RI remediation campaign added tests on both sides; the run that found that stale figure also found `tests/jobs/test_extraction_executor.py::test_the_executor_is_the_handler_the_worker_process_wires` failing on `apps.worker._PLANES`, since renamed to `_JOB_PLANES` for the plane-to-handler pairing — the test has been realigned to the renamed symbol and is green in this figure. A full re-run against the head this correction is bound to reported `1 failed, 14,428 passed, 1,597 deselected in 585.60s`, the one failure being this row's own claim before this edit; the count is green once corrected. |
| Architecture tier | Architecture tier **4,722 passed** on the RI remediation tree. This path-selected figure is stated separately so its checked claim cannot be mistaken for the FAST marker result. Corrected 2026-08-29 from 4,712, which was measured on the integrated corrective tree before this campaign's architecture tests were added. |
| Lint and format | `ruff check .` — "All checks passed!"; `ruff format --check .` — clean, no file would be reformatted. **No file count is stated, and one was until CI disproved it.** This cell said "clean over 925 files", measured locally; CI reported 927 at the same commit and the run failed on the guard binding the figure. `ruff` walks the working directory, not the index — 683 Python files are tracked and it formats 950 here — so the number is a property of whatever happens to be on disk and differs between a developer checkout and a runner. Cleanliness is the repository fact; the corpus size is not one. `mypy`'s count below stays bound because it is derived from configured targets rather than from a directory walk |
| Types | `mypy` (configured targets: `src`, `migrations`, `apps`, `ops`) — clean over 426 files: `Success: no issues found in 426 source files`. Corrected 2026-08-29 from 424, which was the corpus at the audited base; the RI remediation campaign added source modules on top of it. The figure is bound to `[tool.mypy] files` by `tests/architecture/test_claimed_test_counts_match_collection.py`, which counts the declaration rather than re-running the type check. |
| Full database tier disposition | **FULL_DB_TIER_NOT_RUN_TARGETED_EVIDENCE_SUFFICIENT.** The immutable-origin correction used a separately verified, localhost-only, auto-removed PostgreSQL 17.10 container for 82 focused tests; the proposal-token correction recreated the same bounded target pattern for five unequal-version cases. Neither authorized or ran the full database tier. The `database or recovery or e2e` selection collects 1,551 tests on this tree; collection is not execution evidence for the unselected tests. Targeted schema, migration, SQL-structure, concurrency, and database execution evidence is recorded in the campaign completion report. |
| Claimed suite sizes are checked | `tests/architecture/test_claimed_test_counts_match_collection.py` parses every `` `tests/….py` — N tests `` claim in this table and compares it against `--collect-only`. Added because both figures above were wrong at the head that wrote them: one cell was rewritten as a dated correction to 19 by the same commit that took the file to 25, and printed the command that disproves it. The spelled-count sweep reads words and is blind to digits, so the evidence table was the one place bound to nothing |
| Evaluation tier | `pytest -m evaluation` — 2 passed, and the same selection written the way the tier guard reads it, `pytest -m "evaluation"` — **2 passed**. Stated in both spellings deliberately: the quoted form is the shape the tier guard binds to collection, and it is carried here because it is the one selection this head can claim green — the two rows above are red on a dependency neither of them owns, and a guard that requires *some* checked pass figure must be given a true one rather than a convenient one. Selected by no CI job by design; the frozen record is what CI checks |
| The frontend package is aligned with this plane | The production frontend package's contract-map set reserved a named artifact for this workstream — `FRONTEND-FEATURE-CONTRACT-MAP-INDEX` recorded People / Relationship / Entity Intelligence as `EXCLUDED — OWNED BY CONCURRENT RELATIONSHIP WORKSTREAM` and that no `FEATURE-CONTRACT-MAP-RELATIONSHIPS.md` existed, and all fifteen sibling maps deferred person semantics to it. That artifact was written on 2026-08-20 and published to Drive `17_FhWTDO35-9o-NHLsaNtJyGtqAFQH57/FEATURE-CONTRACT-MAPS`, with the index, the gap register (`FBCG-015`, `FBCG-016`, `FBCG-017`), the acceptance traceability (`PFE-AC-071..076`, previously six `EXCLUDED` rows) and the readiness classification updated to match, and the change recorded in that folder's own source manifest. **The numbered package artifacts 00–11 were not touched, so every `source_bytes` hash in `11_PACKAGE_PUBLICATION_MANIFEST` remains valid.** Both directions were carried: `entities.search` gained pagination, `entities.unresolved_mentions` was added for the People landing, `is_current` was added so no surface re-derives currency, and an unreadable cursor now refuses rather than answering an empty page. Readback verified against Drive after publication |
| Migrations apply and reverse | `tests/schema/test_entity_schema_migration.py` derives the current inventory. Phase B owns seven tables across six revisions (`c7a1f04b9e63`, `d38e6b2fa715`, `e5b0c94d7182`, `a1f7d3c85e40`, `b64e29a0f7c1`, `3d07af4dc513`): the prior five proposal/review/identity tables plus `relationship_write_requests` and its evidence child. The cumulative head revision also carries the B1/B4/B5 column, constraint, backfill and trigger deltas. The merged linear chain admits GSQS at `c4b0a1d9e827` immediately before Phase B begins at `c7a1f04b9e63`; `b727e870d45e` is the single head, additive on `8e1c4a7b2d90`, and carries this campaign's merge-preview ambiguity and settlement tables, the `partial` re-enrichment state with its `limitations` column, the `reenrichment` heartbeat plane and the append-only trigger on `entity_proposal_review_decisions`. Corrected 2026-08-29 from `8e1c4a7b2d90`. Database execution still requires the disposable PostgreSQL fixture; collection is not execution evidence. |
| Partition holds at the server | `tests/database/test_entity_repository.py` — 60 tests: cross-Principal isolation on every read and every write, including the joined resolution lookups and the redirect refusals (cycle, chain in **both** orders, absent survivor, cross-partition). Four were added by the WP-RI-A-01 corrective: the two joined lookups now assert the *child* record's `version` and `updated_at` against an entity holding deliberately different ones, and against an unrevised child whose `updated_at` is `None`, because both reads answered with the entity's column and nothing caught it; plus the refusal of an address another entity currently holds, and the retire-and-rebind on one entity that the dropped total unique made impossible. Six were added after the independent review: the second-side partition predicate on each joined lookup, isolated by a child row whose partition disagrees with its parent's — the case the previous test could not reach, so both predicates were deletable with the suite green — plus `record_alias`'s write refusal, the `aliases` enumeration, `record_relationship`'s scope check, and the reverse-order chain. One more was added by the WP-RI-A-01c corrective: the concurrent-retirement race in `bind_identifier`'s read-back window, produced with a SQLAlchemy `after_execute` listener that commits the retirement in a separate transaction between the refused insert and the read that names the holder. `scalar_one` answered that interleaving with `sqlalchemy.exc.NoResultFound` — a driver exception crossing a port whose contract is `ValueError`, on a bind that was correct — and the test fails at `bd5b8be` with exactly that exception |
| Governance holds at the server | `tests/database/test_entity_governance.py` — 51 tests: a proposal cannot be accepted without an actor in either direction; a decided proposal cannot be decided again (asserted at the repository, below the service's own check); a merge record cannot cite another Principal's proposal |
| The context card is honest about its own bounds | `tests/unit/test_entity_context.py` — 9 tests: coverage counts past the page the card displays, discloses when the read ceiling bit, holds at the off-by-one, never counts another Principal's observation, and asks the repository for a bounded read. `tests/database/test_entity_governance.py` captures the SQL actually issued and asserts a `LIMIT` clause reaches the server. It previously counted only the rows returned, which is equally true of a slice of a full fetch — so the guard on the one property the cap exists for was inert until the independent review mutated it. Before this the module had no direct test at all |
| The plane refuses when it is off | `tests/contract/test_entity_capabilities.py` — every one of the thirty-four `entities.` names, parameterized, answers `unsupported` on a build that never enabled the relationship plane. Parameterized deliberately: the floor was missing from all five, so a test covering one would have gone green over four open holes. `tests/contract/test_http_transport.py` composes the plane explicitly, having previously asserted `200` for capabilities the same process reported `not_implemented` |
| MCP surface | `tests/contract/test_mcp_transport.py` — a real child process composed for the plane and its write half publishes all 104 tools, and an unconfigured one publishes 55, withholding the thirty-four `entities.` names along with the six `documents.` names and the nine `relationship_memory.` names. Corrected 2026-08-23: this cell said 54, which was the whole capability set before the Intelligence Artifact and Relationship Memory planes and is now neither of the two figures this test asserts. Neither number is written into the test — both are derived from `Capability` there, which is why the test stayed green while the cell describing it went stale |
| Remote exposure | `tests/contract/test_entity_remote_exposure.py` and `tests/contract/test_remote_mcp_transport.py` — no `entities.` name reaches the remote profile with the plane off. With it on, the eleven reads remain reads and all twenty-three writes require `remote_writes_enabled`. The ordinary profile and a raw capability allowlist still exclude `entities.merge.preview`, `entities.merge`, `entities.split.preview`, and `entities.split`; they join only when the server-resolved durable capability set exactly equals frozen `remote.operator`, and invocation still intersects allowed capabilities and exact purpose grants before application feature, Principal, policy, and audit checks. Writes disabled, an absent/mismatched/subset/superset/non-operator profile, an empty grant, or a missing purpose each refuses causatively. No live profile, grant, or flag is activated |
| The write half refuses when *it* is off | `tests/contract/test_entity_write_gate.py` — a build with `MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED` and without `MY_PA_RELATIONSHIP_INTELLIGENCE_WRITES_ENABLED` serves the eleven reads and answers `unsupported` to every one of the twenty-three writes called by its known tool name, over the application entry point the HTTP transport reaches after routing by path segment. Withheld from `available_capabilities`, from the local tool list and from the remote profile under both settings of `MY_PA_REMOTE_WRITES_ENABLED`, because that is a different switch. `bootstrap.settings` refuses to start a process that sets the write switch without the plane |
| Evidence scope is one decision | `tests/contract/test_entity_evidence_scope.py` — the four directed writes admit `eobs_…` only, the four identifier and alias writes admit `span_…` only, no capability admits a knowledge record, and `entities.unresolved_mentions.resolve` names no caller-supplied evidence at all. Derived by constructing each command with one identifier of each kind, and the citing population is read off the `Command` union so a ninth citing write reddens |
| False-resolution rate | [`tests/evaluation/RESOLUTION_CALIBRATION.md`](../../tests/evaluation/RESOLUTION_CALIBRATION.md) — 0 false resolutions, 0 cross-Principal leaks, 0 forbidden candidates, recall 1.0 over **35** labelled collision-biased cases in 20 families (14 must-resolve, 20 must-not). Corrected 2026-08-19: this row read 27/12/15, which matched no head — the published record has said 31/14/17 since the currency fix in section 4a. Re-derived rather than restated, by `compute_calibration_record()` itself: `PYTHONPATH=src:. python -c "from tests.evaluation.resolution_harness import compute_calibration_record as c; r=c(); print(r['cases'], r['must_resolve_cases'], r['must_not_resolve_cases'])"` → `35 14 20` |
| The safety rules bite | Mutation-tested: resolving a lone name, choosing a claimant of a conflicted identifier, ignoring effective dates, dropping the partition, dropping the operator gate, letting `propose` apply its own merge, dropping the observation-kind entity-type constraint, dropping the recorded-merge precondition, dropping the still-open predicate, dropping the merge record's proposal partition check — each reddened the suite |

**Phase B replay and producer semantics.** Proposal writes and `review.decide`
use a Principal-and-capability-scoped server request ledger. The remote boundary
refuses caller `request_id` and idempotency fields, derives a deterministic
`corr_…` identity for those replay-backed writes, returns the original typed
logical receipt for the same material digest, and refuses reuse with changed
material. The ledger stores typed identifiers, versions, states, digests and
evidence references only; it stores no RM statement, correction, reason, or
generic response JSON. A completed receipt and its evidence cannot be updated
or deleted. A reservation is also transaction-bounded at the database: an
initially deferred constraint trigger refuses commit while it is still pending,
while permitting the intended reserve-then-complete transition in the same
transaction. Rollback therefore leaves no claimed identity.

Producer provenance is resolved through an immutable server-injected
`ProducerOriginRegistry` keyed by the authenticated Principal. The local
operator composition has one explicit `rule` registration; an unregistered
Principal fails closed. Entra mode currently has no trusted producer identity
configuration, so it withholds both proposal capabilities instead of publishing
a surface every authenticated caller would be denied. Named local and remote
standard/producer/reviewer/operator ceilings are declarations only and activate
no grants. Equivalent open RM claims are first-origin-wins: later equivalent
submissions merge new exact evidence into the stored candidate and return that
candidate's original provenance, rather than laundering it through the later
producer. Open equivalence is the Principal, subject, kind, exact statement
digest and canonical structured value. The subject's expected version is an
independent optimistic-promotion guard, not claim identity: version-only drift
therefore finds the same open claim. Reprocess refreshes that expected version
and recomputes the canonical semantic digest for the successor.

**Migration limitations.** Historical RM proposals had no stored subject
version. `3d07af4dc513` approximates that legacy-only value from the subject's
current entity version; it never overwrites a value already written by the new
contract. If legacy version-scoped digests collapse multiple still-open RM
proposals onto one semantic claim, the migration retains the earliest
`(proposed_at, proposal_id)` origin as the open winner, moves only evidence not
already represented in its exact role/source union, and marks every losing row
superseded with lineage to that winner. Exact duplicate evidence, proposal rows,
provenance, and review history are not deleted. Historical identity previews
cannot prove the new full projected-plan
digest, so the migration writes a deterministic legacy sentinel that will fail
apply-time recomputation as stale. Operators must generate a new preview rather
than applying a pre-migration approval.

**What no evidence here covers.** Nothing has been run against a shared or
production database; every database figure comes from a disposable database
created and dropped by its own fixture. No connector, source, or live personal
data was touched.

**Independent exact-head review, and what it cost.** Section 8.1 requires one,
and eleven rounds have now run — dispatched to reviewers holding no part of this
campaign's context, each bound to a named commit, each working read-only in its
own worktree. **Every round found real defects**, including the rounds that
reviewed the previous round's remediation, and the recurring finding was always
the same shape: a rule applied where a reviewer had pointed and not to its
siblings. The adversarial pass recorded in section 4b was run by this campaign
against its own work and never substituted for that review; it is kept because
what it missed is part of the record.

Two things the panel found are worth carrying past the merge, because they say
what this evidence is worth. First, a cell in this table once claimed 1,926
tests passed for a selection that collects 951 — the commands had run, but they
were whole directories with no marker filter, described as partitioning the
marker selection. Nothing in the repository read a bare number until a guard was
added for it. Second, guards on this plane were repeatedly correct and untested:
deliberate breaks in them survived the suite, and twice a rule was proved only
against the in-memory double rather than against the server. Neither is a defect
in the plane's behaviour. Both are defects in what this document claimed about
it, which is the reason to read any remaining sentence here as a claim rather
than as a fact.

---

## 4b. Adversarial review, and what it found

An adversarial pass was run over the whole branch after WP-RI-13. It raised
thirteen findings. Recording them here because the interesting ones are the
three that were **confirmed by execution rather than accepted on argument** —
each was reproduced as a failing assertion before anything was changed, and each
had made the resolver answer confidently and wrongly.

| # | Severity | What it was | Disposition |
|---|---|---|---|
| 1 | HIGH | The `entity_type` filter ran *before* the conflicted-identifier check, so an identifier claimed by a person and a project answered `RESOLVED_EXACT` — a different entity per caller, with no warning | Fixed: the conflict is computed on the unfiltered effective set |
| 2 | HIGH | One unnormalized `canonical_name` flipped `AMBIGUOUS` to `RESOLVED_EXACT` naming the *neighbouring* entity. The same hole existed, undocumented, on `EntityAlias.normalized_value` and `ExternalIdentifier.normalized_value` | Fixed: `is_normalized_name` / `is_normalized_identifier` are enforced by all three records at construction. `ExternalIdentifierNamespace` moved to `normalization.py` so the dependency runs one way |
| 3 | MED-HIGH | `RESOLVED_CONTEXTUAL` required a rival, so adding a duplicate row *upgraded a refusal into a resolution*. Separately, a scope true of nobody was silent | Fixed: corroboration resolves without a rival. The scope half was **overstated here and has been narrowed**: a scope that distinguishes nothing warns only when there is more than one candidate, so a lone candidate no scope reaches still answers `AMBIGUOUS` silently. Carried as a residual in section 5 |
| 4 | MED | `redirect_entity` permitted a merge cycle and a merge chain, making `superseded_by_entity_id` a pointer that never arrives | Fixed, but **only half**, which the independent review caught (section 4c): the survivor check closes cycles and closes chains written in one order. `redirect(BOB, ALICE)` then `redirect(ALICE, CARLA)` passed it and left `BOB -> ALICE -> CARLA`. Now also refused, both in SQL and in the fake, with a database regression in the previously open order |
| 5 | MED | `EntitiesRepository.create` took no `principal_id`, contradicting the port's own universal invariant | Fixed: `create(principal_id, entity)`, 130 call sites updated |
| 6 | MED | `after_merge` moved observations between any two entities named together — no merge record required. `after_alias` discarded the observation's kind, so a calendar attendee could link to a project of the same name | Fixed: a recorded merge in that direction and partition is a precondition; `KIND_IMPLIES_ENTITY_TYPE` constrains the re-offer. Both mutation-tested |
| 7 | MED | The runbook instructed operators to run `EntityGovernanceService` and `EntityReenrichmentService`, which **nothing in `src/` composed at that head** | Corrected at the time by stating the gap; the final-completion campaign now composes durable registration through the production gateway and unit of work. Runtime worker commissioning remains operator-only procedure, not silently activated. |
| 8 | MED | Nine acceptance criteria read `OPEN` — "in a planned work package" — against WP-RI-06/07/10, all of which had shipped | Fixed by re-dispositioning each against what actually shipped, with an `UNMET` status added for exactly this. **None moved to `MET`** |
| 9 | LOW | `cross_principal_leakage` in the calibration record actually counted all forbidden candidates | Fixed: split into two metrics |
| 10 | LOW | The inspection script emitted free-text `proposed_by` while claiming it printed no personal data | Fixed: the column is not selected, and the docstring says why |
| 11 | LOW | The end-to-end scoring scan covered four of the five capabilities | Fixed: `ENTITIES_RELATIONSHIPS` added |
| 12 | LOW | `ports.py` said "no alias table exists yet" — stale since WP-RI-03 | Fixed: the claim (aliases are not searched) is now stated as the decision it is, with the disclosure reason |
| 13 | LOW | Six smaller items: an unbounded observation read in the context card (and, once looked for, the same slice-after-fetch in both re-enrichment passes); `record_merge` not partition-checking `proposal_id`; `decide_proposal` not asserting the proposal was still open; `reached_the_bound` naming; a stale file count; two must-resolve cases filed under a "must not resolve" banner | All fixed. The two persistence ones carry mutation-tested database regressions; the card now reads at a disclosed ceiling and says when it bit. The observation cap's own guard was **inert** until the independent review mutated it (section 4c): counting the rows returned cannot tell a `LIMIT` from a slice, so the SQL issued is now captured and asserted |

Four schema-suite failures surfaced alongside these, all of the same kind:
accumulation sets in `test_audit_schema_migration.py`,
`test_enrollment_objects_migration.py`, `test_capture_schema_migration.py` and
`test_entity_schema_migration.py` that name what the revisions above them create,
and which the entity plane's eight tables and five capabilities had outgrown.
Each was corrected as bookkeeping.

### 4b-i. What the independent merge review then found

A second pass, by a reviewer who had not written any of it, was run over the
same head. It confirmed the thirteen dispositions above and found that the fix
for finding 3 had opened a hole of its own — which is the useful thing about a
reviewer who did not make the first repair.

| # | Severity | What it was | Disposition |
|---|---|---|---|
| A | BLOCKING | Making corroboration sufficient (finding 3) left nothing requiring the corroborating record to be **current**. `relationships()` takes no `active_only`, so an edge recorded `state="ended"` corroborated exactly as strongly as a live one — while an ended *assignment* did not, so the answer depended on which of two tables the same fact had been written to. `_is_effective` also stops filtering when `as_of` is `None`, which is the default request, so an expired tie counted too. A contractor who left in 2024 still lifted a bare canonical name to `RESOLVED_CONTEXTUAL` in 2026, carrying an entity identifier, with **no warning at all** | Fixed: `_is_in_force` is the stricter currency rule signals are held to — an ended record corroborates only at a moment the caller named that it covers — and the edge state is filtered on the same terms `active_only` filters assignments. A tie that was passed over as stale now raises `EVIDENCE_WAS_NOT_EFFECTIVE_AT_THAT_MOMENT` |
| B | SHOULD-FIX | The lone-corroborated answer carried no warning whatever. `NARROWED_BY_SUPPLIED_SCOPE` is defined as "the answer would have been `AMBIGUOUS` without it", and the one outcome that fits that definition exactly was the one that said nothing | Fixed: the disclosure is raised when the scope did the deciding, and withheld when an alias resolved it and the scope merely agreed |
| C | SHOULD-FIX | The identifier→name fall-through fired when the identifier **matched** and the caller's `entity_type` excluded the holder — not only when it matched nothing. An email lookup constrained to a project answered `RESOLVED_EXACT` naming a project whose alias happened to be spelled the way `normalize_name` spells that address, discarding identifier evidence that pointed at a person | Fixed: that case is `NOT_FOUND`. The genuine fall-through — an identifier matching nothing — is unchanged |
| D | SHOULD-FIX | The corpus was collision-biased on names and identifiers and not hostile at all on the axis A breaks: every assignment and edge in it was undated and active, and the lone-candidate-plus-signal path had no case. `RESOLUTION_PRECISION_HELD` was measured over a corpus that could not have caught A | Fixed: three entities and four cases whose ties differ only in how current they are, including the two that must still resolve. `resolved_contextual:canonical_name` now rests on three measured resolutions rather than one |

Every guard behind A, B, C and D survived deletion against the whole suite
before this pass; each is now killed by a named test. That is the finding under
the findings — the checks existed and nothing was holding them.

---

## 4c. Independent merge review, and what it found

**Eleven rounds so far, not one.** Each is four reviewers, one per lens, run by
contexts that did not author the change and were not instructed toward an
outcome. Every round found something, and every round's findings were answered
by a commit — which is what invalidates that round and requires the next.

| Round | Head | Verdict | What it found |
|---|---|---|---|
| 1 | `d5861e9` | 3 of 4 blocked | A confident answer resting on expired evidence; an off-switch that withheld publication but not execution; false current-state counts. Nine guards were correct and untested |
| 2 | `d4d6d40` | 3 of 4 blocked | An identifier matching only expired rows re-read as a name and resolving to a *different* person; currency inferred from a missing end date; `CONFLICTED_IDENTIFIER` crashing past ten claimants; **eleven more** untested guards, including the two `UPDATE` predicates whose absence let one Principal re-point another's observation and accept another's merge |
| 3 | `04a48ae` | 2 of 4 blocked | A sentinel window that was not before any moment, so a *cancelled* assignment corroborated at `as_of=datetime.min`; the currency clock unpinned at the capability; the evaluation corpus blind to the axis it was cited for; a concurrency race in `redirect_entity`; two false citations naming test files that have never existed; a partition walk whose anti-vacuity floor sat at nine against thirty-one statements present; and a personal-data scan planting `proposed_by="resolver"`, a value that is not personal, so re-adding the column it exists to keep out would have stayed green |
| 4 | `271e949` | 2 of 4 blocked | The frontend contract package read against the plane: a People landing needing an unresolved-mentions list the plane did not serve, and a search that could truncate without a cursor |
| 5 | `8b12610` | 3 blocked | The cursor rule reached one of three paged reads while the commit message stated it without qualification; `_entity_translated` naming `enrollment_id`, a field this plane does not model; a docstring calling normalization redaction, when `normalize_name` removes no content |
| 6 | `e679ffb` | blocked | The round-5 fixes were each one sibling short — the same shape, inside the commit written to close it |
| 7 | `ef652de` | 1 of 2 blocked | The disclosure narrowing silently retired the privacy sweep for the capability it was about: the fixture set no `mention_display_name`, so the only field the queue could leak was `None` and a removed partition stayed green. And the bound claimed to be enforced in two places was two different bounds — `str.strip()` against `trim()` |
| 8 | `4542109` | blocked | "Removed the difference" was false: moving the CHECK to `[[:space:]]` closed the two values the previous reviewer named and left the class open, and `[[:space:]]` is decided by the server's collation |
| 9 | `95017d9` | 3 of 4 blocked | A caller-supplied field read before its type was checked, so `{"query": 123}` on `entities.search` raised `AttributeError` and escaped the HTTP transport as a **bare 500 with no envelope** — on the default, plane-off build. Two reviewers independently found the alias and identifier child-side partitions vacuous: `entities_by_alias` and `entities_by_identifier` each carry two `_mine` calls in one statement, so the statement-level guard stayed green with either deleted. Plus a stale FAST figure in this very table, a README count that said five where the set holds six, a runbook capability table listing five of six, a continuation-cursor count that said two where four is derived, and a module docstring disclaiming the contextual ranking that module performs |
| 10 | `f91f328` | 3 of 3 blocked | The ninth round's remediation reproduced the pattern it was written to end. The new command guard excluded `str \| None` fields, justified by a claim — that helpers type-check them — which is false of the three that carry the defect; `tasks.update`, `tasks.transition` and `review.decide` answered `500` over HTTP while the guard reported the codebase compliant. Three ways past it were planted and all three worked: extract the read into a helper, put check and read in one statement, shadow a helper name locally. The per-table partition rule was applied to `entity.py` and not to `relationships.py`, and a module-level `Table.alias()` defeated both walks. **Two regressions were introduced**: `_bounded_query` restated the search bound instead of using it and so refused `"Alice\tChen"`, which `knowledge.search` accepts; and `record_merge`'s collision read was partitioned "for parity" with a server read that does not exist, narrowing a global `UNIQUE` and letting the double accept a merge the database refuses. Four of the five collision reads the commit claimed to have armed were still deletable with the fast tier green. Plus `tests/unit/test_policy.py:259` spelling a count of five above six enumerated pairs, hidden by an `EXCUSED` entry written for a different line; four more v0.3 residues; a miscount in the commit message; and a `submit` route that did not get the terminal catch the message attributed to "the transport" |
| 11 | `ebecec4` | 3 of 3 blocked | **No disclosure defect and no behaviour regression** — both regressions the previous commit reverted are genuinely reverted, and `_bounded_query`'s delegation survived 3.3 million codepoints and 100,000 fuzz cases against `knowledge.search` with zero disagreements. What it found was the pattern again, in the guards: the per-table partition walk excluded `select(*_ENTITY_COLUMNS)` — this module's *dominant* query idiom, which compiles to `FROM knowledge.entities` — so a whole-plane read of every Principal's rows passed 252/252, and the exclusion's stated reason ("a binding that merely selects columns is not a second way to query it") was false. Eight ways past the command guard, including a field bound to a local and a helper credited as type-checking because it happened to raise `InvalidRequestError` for an unrelated reason. Four global-key rules and three terminal catches shipped with no test — blanking all four keys, or either catch, left the entire fast tier green. The `tables.py` CHECK comparison passed `AND`→`OR` and an unsatisfiable `BETWEEN 200 AND 1`. Plus a `from None` comment claiming to clear `__context__` when it does not, a walk floor five under its real figure, a miscount inside the sentence recording a miscount, and this section's own count of how many commands accept a non-string |

**Twenty-two guards across the first three rounds were correct and untested**, not
nine across one. An earlier version of this section recorded only round 1 and
reported the nine — while the commit that added this section's own corrections
was titled for round 2. A section whose purpose is to record independent review
is the worst place to omit one.

It then omitted five. Corrected 2026-08-20: this section carried three rows and
the words "three rounds so far" while section 4a, seventy-six lines above, said
seven had run and the commit messages documented eight. Rounds 4 through 8
appeared nowhere in it — including round 8, whose `DO NOT MERGE` verdict the
commit immediately below this table was written to answer. The same section, the
same failure, one round after recording it. Both spellings are now checked against the
rows themselves by
[`tests/architecture/test_review_rounds_recorded_match_the_count_claimed.py`](../../tests/architecture/test_review_rounds_recorded_match_the_count_claimed.py),
which also reddens on a gap in the numbering — the shape a skipped round takes.

Recorded at this length because the pattern across the rounds matters more than
any single defect, and because the pattern did not stop: see "what kept
recurring" below.

**This is not the review `AGENTS.md` section 8.1 requires, and this section said
it was.** Corrected 2026-08-19. Section 8.1 requires an independent review of
the head being merged; every finding below was answered by a commit, so the tree
those four reviewers read is no longer this tree — `d5861e9` is an ancestor, not
this head. Section 4a above says the same thing in the other direction ("**No
independent exact-head review has occurred**, so nothing here is merge-eligible
under `AGENTS.md` section 8.1"), and
[`relationship-intelligence-v0.3-acceptance.md`](../specs/relationship-intelligence-v0.3-acceptance.md)
states plainly that "a later commit invalidates the exact-head review". Two
sections of one document disagreeing about whether the merge gate is satisfied
is the defect, and the conservative reading is the correct one: what follows is
a real independent review whose findings were acted on, and it does not make
anything merge-eligible. A fresh review of the corrected head is still owed.

Round 1's lenses, in full:

| Lens | Verdict at `d5861e9` |
|---|---|
| Resolution safety | BLOCK |
| Partition and capability exposure | BLOCK |
| Truthfulness of the record | BLOCK |
| Migrations and rebase reconciliation | no blocking findings |

**The two blocking defects.**

* A confident `RESOLVED_CONTEXTUAL` could rest entirely on a *dead* signal. The
  corroboration rule added in section 4b's own pass never required the
  corroborating record to be current: `relationships()` applied no state filter
  while assignments were filtered, `_is_effective` declines to filter at
  `as_of=None` — the default — and the "a name alone does not resolve" guard
  exempted `RESOLVED_CONTEXTUAL`. A contractor who left in 2025 lifted a bare
  canonical name to a resolved answer in 2026 with an **empty warnings array**.
  Fixed by `_is_in_force`, a stricter currency rule for signals than for the
  evidence a reference itself matched, plus edge-state filtering and the two
  missing disclosures.
* **The off-switch withheld publication and not execution.**
  `available_capabilities` subtracts the thirty-four `entities.` names, and its two
  readers are `capabilities.get` and the MCP tool list. The HTTP transport is
  neither: `/v1/{capability}` routes by path segment and dispatch goes straight
  to `_HANDLERS`, so every one of the five answered with real entity rows on a
  build reporting them as `not_implemented` — against what
  `ops/runbooks/relationship-intelligence.md` told the operator. Fixed with
  `_entity_plane()`, the floor `documents.` already had in `_managed_store`.

**What kept recurring, across all three rounds: guards that were correct and
untested.** Twenty-two separate mutations survived the full suite — nine, then
eleven, then two, which is the enumeration below and not the twenty an earlier
version of this sentence reported — round 1 found
nine (the redirect chain in one ordering, both joined lookups' second-side
partition predicate, `record_relationship`'s scope check, the observation
`LIMIT`, and four on the contextual-signal path); round 2 found eleven more
(three enumeration reads whose test asserted `== []` against tables its fixture
never populated, four write-idempotency reads, the `link_observation` and
`decide_proposal` `UPDATE`s, the keyset predicate, and one that turned out to be
unreachable rather than untested); round 3 found the currency clock unpinned at
the capability and the `as_of`/`at` precedence unpinned anywhere. Every one is
now killed by a named test.

The section 4b pass missed this because it checked whether the code was right
and not whether the tests could hold it right. A guard nothing exercises is a
comment.

**And the second pattern, which is the one worth carrying forward: a fix that
closes the reported instance and not its siblings.** The redirect chain was
closed in one ordering and not the other. The identifier fall-through was closed
for the caller's `entity_type` filter and not for effective dates, where it
resolved to a *different person*. A partition test was written for `aliases`
while the three reads its own docstring named as covered stayed vacuous. The
v0.2 successor notice was corrected while three documents repeating what it
contradicts were not. Each was found by the round after the fix. Where a finding
now names one instance, this campaign states the rule the instance belongs to
and checks the rule — `_by_identifier` says once that every exit past a matched
row is an answer, and `redirect_entity`'s guard was checked by an independent
reviewer over every two- and three-step arrangement rather than the two that
were reported. That enumeration lives in the review, not here: no test in this
repository walks 252 arrangements, and stating it as though it did would be the
false-citation defect this campaign has now committed three times.

**And a stale-count guard that could not see emphasis.** Two runbooks read
`**forty-eight** capabilities` against a set of fifty-four, and
`test_spelled_counts_match_the_sets_they_name.py` found no claim there at all,
because its pattern allowed only whitespace or a hyphen between the number and
the noun. Those two counts were corrected and the pattern now reads across
emphasis — verified by restoring a stale count and watching the sweep fail.

**Corrected 2026-08-19: this paragraph said "the counts are corrected", and two
were not.** Widening the pattern to read across emphasis fixed the two claims
that carried a noun and left the shape beside them untouched: `ops/runbooks/
mcp-and-cli-operations.md` said "A default process publishes **twenty**" and
"(unset: twenty, …)" of a set that publishes forty-two by default, under a
heading reading "Measured at this head". Neither was read by any rule, because a
number with *no noun after it* matches nothing the guard looked for. Both are
corrected now, and `BARE_EMPHASIS` reads the shape. The lesson is the section's
own: a guard widened to catch the instance that was found is a guard shaped by
the instance that was found. What actually let all four survive is that the
guard read `apps/`, `ops/`, `src/`, `tests/` and `README.md` and did not read
`docs/` at all — so this document, which makes more derivable claims than any
other in the repository, was bound to nothing. It is in `SWEPT_FILES` now, and
adding it is what surfaced the three false claims corrected in section 0.1 and
section 4a above.

---

## 5. Known gaps carried forward

* **Carried — four fidelity gaps in the in-memory double.** None is reachable
  through a transport, and each is the kind of divergence that lets a unit test
  prove something the server does not do.
  First, `search` in `tests/conftest.py` runs its normalization refusal over
  *every* entity in the partition while `SqlEntityRepository.search` reaches
  `_row_to_summary` only for rows the page returns, so the fake is strictly
  stricter than the comment beside it claims — the comment now says so.
  Second, four malformed-identifier refusals answer `UnknownScopeError` in the
  double where the server answers `InvalidIdentifierError`, which map to
  `not_found` and `invalid_request` respectively; unreachable because the
  commands validate before the repository is called. Third, the `proposals`
  listing and `link_observation`'s target partition are partitioned correctly
  and covered nowhere in the fast tier — their SQL equivalents are covered in
  the database tier, so the production rule is proved and the double's is not.
  Fourth, every global-key collision the double now models raises `ValueError`
  where the server raises `IntegrityError`. No transport distinguishes them —
  both become an `internal_error` envelope — so this is a fidelity note rather
  than a behavioural gap, and it is written down because the tenth review had
  to measure it to find that out.
* **Closed 2026-08-21 — a command checks the type of every string field it
  reads, and `CARRIED_FROM_THE_MERGE_BASE` is empty.** The entry this replaces
  recorded 9 offending pairs and a wider class of 19. Both counts were built by
  sweeping, and measuring the class directly before fixing it found the record
  wrong in two directions at once.
  `UpdateTask.title`, `TransitionTask.closure_evidence_ref` and
  `DecideReviewCase.corrected_value` did dereference an optional string behind
  an `is not None` test and did answer `500 internal_error` over HTTP; each now
  routes through `_text` before `.strip()` is reached, and
  `tests/unit/test_command_input_types.py` states that as behaviour.
  `_idempotency_key` did test truthiness and never the type, so a non-string key
  was *accepted* into a handler that assumes a string; it now checks the type,
  and its parameter is annotated `object` rather than `str` so the check is not
  dead code to a type checker — the shape `_bounded_token` already used.
  **The hole was wider than the allowlist, not narrower.** 5 commands called
  that helper; 10 more spelled the same emptiness test inline, outside the
  guard's stated rule and so never on the list. Fixing the helper would have
  reached 5 of 15. All 10 now call it, and
  `tests/architecture/test_every_write_validates_its_idempotency_key.py` derives
  the population from the dataclass fields and requires it, so a command added
  tomorrow is covered without anyone remembering to add it.
  **And one entry was never a defect.** `PrepareContext.conversation_context`
  validated through `validate_conversation_context`, which refuses a non-string,
  and converted the domain error inline — correct behaviour that the guard could
  not see, because it measures type-checking by helper and the conversion was
  not in one. Extracting `_conversation_context`, the shape `_alias` already
  used for the same job, made the existing guarantee visible. A guard that
  cannot see a correct answer records it as an offence, and this one did for 9
  review rounds: the allowlist was 8 real defects and 1 false positive, and
  nothing distinguished them.
  Not touched: `CreateManagedDocumentCommand` and `ReviseManagedDocumentCommand`
  raise `ValueError` on an empty key, carry no `capability`, and are internal
  service objects rather than caller-facing commands — a programming-error
  assertion, not a transport refusal. Also not touched: `client_context`,
  `description`, `namespace` and `entity_type`, which no `__post_init__` reads
  at all. Whether a handler downstream assumes a string of them is a separate
  question this change did not answer.

* **Carried, and NOT this branch's — the Apple machine routes answer a bare
  `500`.** `adapters/http/app.py`'s `apple_request` catches
  `AppleMachineCredentialError`, `AdmissionDeniedError`, `ValueError` and
  `LookupError`, and nothing else; a `SQLAlchemyError` from either of the two
  untranslated reads in `SqlAppleMachineControl` escapes to Starlette as
  `500 Internal Server Error` with no envelope, no typed code and no correlation
  identifier. Present at the merge base, and behind `apple_ingress_enabled`,
  which is off by default. Every block of both capability-serving routes
  now all carry the terminal catch; these two do not, and widening further was
  the same declined decision as the entries above.
* **Carried — three limits of the guards in `tests/architecture/`, measured
  rather than assumed.** `TIER_CLAIM` reads a **bolded** figure following a
  `pytest -m "…"` command, so un-bolding a figure removes it from the population
  rather than reddening; and because that module's own parametrized tests live
  in `tests/architecture`, editing the plan's claim set changes the architecture
  and FAST counts the same module checks, so a correct edit can redden two
  correct figures. Separately, the borrowed-noun rule in the spelled-count sweep
  fires on ordinary English — a bare count of anything, written as a spelled
  number before a plural noun, inside any block that
  mentions capabilities — and `_own_source` includes string literals, so a
  partitioned table's name inside a `raise ValueError("…")` message reddens the
  partition walk. Both are false-positive modes, which is how a guard gets
  deleted; neither is triggered at this head.
* **Carried, and NOT this branch's — `tasks.search` bounds neither the length
  nor the character class of its query.** It reaches the same `ILIKE` parameter
  on the same driver as `entities.search`, which this branch bounded, but it
  routes through no equivalent of `domain.search.query`. Same provenance and
  same reasoning as the entry above.
* **Carried, and NOT this branch's — the WP-9 substrate's partition guard is
  per statement, not per table.** `test_every_relationship_statement_reaches_the_partition`
  passes a statement that names `_mine` once, and
  `infrastructure/persistence/relationships.py` has eleven statements naming two
  or three partitioned tables. The entity plane's equivalent was strengthened to
  per-table by this branch; carrying that to `relationships.py` is the same
  widening declined above.
* **Carried — `RI-AC-033` has no benchmark.** p50/p95 across the six named
  operations does not exist, and correctness at program scale is not latency at
  program scale. `tests/database/test_program_scale_acceptance.py` times nothing
  deliberately: a wall-clock assertion against a shared, contended database
  measures the machine.

* **Closed 2026-08-20 — the queue no longer discloses a matched form.**
  `entities.unresolved_mentions` published `normalized_value`, and that is not
  the boundary it reads as: `normalize_name` casefolds and unpunctuates and
  removes no content, so a writer deriving it from raw text published the
  envelope with its dots turned into spaces, `is_normalized_name`-true and
  indistinguishable by any predicate from a long real name. The first mitigation
  was a sentence on the port asking writers to supply an extracted name — a
  privacy invariant carried by prose, on a plane whose documented history is
  prose drifting inside a single commit. `f3a8c1d7e592` replaced it with a
  column: `mention_display_name`, nullable, read by the queue and by nothing
  else. Forgetting now fails closed, disclosure is an affirmative write, and an
  auditor greps one column's writers. Taken while the table held zero rows,
  which is why it cost no backfill and would not have been free after ingestion.
* **`entities.resolve` fans out one unbounded read per candidate.**
  `_assigned_to` and `_related_to` call `assignments` and `relationships` with
  no `limit`, once per candidate, and the candidate set is materialized in full
  before `RESOLUTION_CANDIDATE_LIMIT` cuts it to ten. Measured against the
  in-memory plane: 400 same-named entities produced 800 unbounded queries and
  1,600 rows to return a ten-candidate refusal. The port added `limit` to those
  two reads for this hazard and names the resolver's pattern in its own
  docstrings; the resolver is the one consumer passing neither. Same class as
  `RI-PR135-MAJOR-001`, which this branch fixed for the context card and left
  here. Correctness is unaffected — the answer is right, the cost is not.
* **`bind_identifier` and `record_alias` silently discard a differing write.**
  Both use `on_conflict_do_nothing` against a natural key, so a repeat carrying
  the same key with a different `verified`, `display_value` or effective window
  is a no-op with no error and no signal — while `create`, `record_assignment`
  and `record_relationship` all *refuse* the analogous rebind. No update path
  exists on the port. Closing an identifier's effective window, or promoting an
  unverified one, is therefore impossible through this repository. Latent: the
  plane publishes no write capability on any transport.
* **`create` can build the redirect chain `redirect_entity` refuses.** It
  accepts `status=MERGED_REDIRECT` with a `superseded_by_entity_id` and checks
  only that the target is the caller's, never that it is current — so `A → B`
  written while `B → C` exists produces the two-hop chain the runbook tells an
  operator not to expect. It also sits outside `redirect_entity`'s row locks.
  Latent for the same reason, and untested.
* **The context card's freshness figure is a floor and the disclosure does not
  say so.** Coverage reads a bounded page ordered by `observation_id`, whose
  suffixes are opaque and carry no relation to `observed_at`, so past the
  coverage limit `most_recent_observation_at` is computed from an arbitrary
  sample. `COVERAGE_COUNTED_A_BOUNDED_SAMPLE` is set, but its own wording scopes
  the caveat to *counts*. An entity past the limit can report a freshness months
  stale while the card reads as current.

* **A scope that reaches no candidate is disclosed only when there is more than
  one.** `CONTEXT_DID_NOT_DISTINGUISH_THE_CANDIDATES` requires a rival, so a
  lone candidate the named scope says nothing about answers `AMBIGUOUS` with no
  word about the scope. Nothing unsafe follows — the answer is a refusal either
  way — but a caller cannot tell "the context was consulted and did not help"
  from "no context was consulted".
* **`_is_in_force` does not exclude a record whose `effective_from` is in the
  future.** Detecting that needs a clock, and the resolver deliberately has
  none: `as_of` is the only moment it knows. A caller that cares passes one.

* **`Entity.canonical_name` normalization is unenforced at the schema level**
  (`D-RI-13`). The domain records now refuse an unnormalized canonical name,
  alias value or identifier value at construction, so nothing routed through
  `Entity`, `EntityAlias` or `ExternalIdentifier` can store one — that was
  adversarial finding 2, and it had made a refusal resolve to a *neighbouring*
  entity. A migration, a backfill or a direct `INSERT` still can: the CHECK
  would have to reimplement `normalize_name` in SQL, which would then be a
  second implementation to keep in step with the first.
* **The evaluation measures the service against a double, not against SQL.**
  `_CorpusRepository` subclasses the real port, so the service cannot pass
  against a shape production could not supply — but the production partition,
  the joins, and the constraints are proved in `tests/database` and
  `tests/schema`, not here. Neither suite alone is sufficient.
* **The corpus is small and synthetic.** Thirty-five labelled cases over twenty-three
  entities is evidence that the stated refusals hold and that the resolver still
  answers what it should. It is not a population estimate, and no number in
  `RESOLUTION_CALIBRATION.md` should be read as a probability about a real
  person. That limitation is stated in the report itself.
* **Only two contextual signals exist** — assignment to a named scope, and a
  typed relationship reaching it. Section 15.1's calendar attendees, email
  participants, introduction chains, and negative evidence all need the
  observation record. WP-RI-06 has since delivered that record, and the
  resolver still does not read it: `EntityResolutionService` consults entities,
  aliases and identifiers only. `RI-AC-010` is therefore `UNMET` rather than
  `OPEN` — the table it was waiting for exists, and the read was never written.
* **The MCP surface exists and is off by default** (`D-RI-20`). A process that
  has not set `MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED` publishes none of the
  family, locally or remotely, and one that has not also set
  `MY_PA_RELATIONSHIP_INTELLIGENCE_WRITES_ENABLED` publishes none of its writes.
* **`record_assignment` and `record_relationship` have no natural key**, so a
  retry that mints a fresh identifier writes a second row (RI-AC-036).
* **Proposal review and governed identity correction now have callers.** Entity and
  Relationship Memory cases use canonical `review.list`/`review.decide`;
  `entities.merge.preview`, `entities.merge`, `entities.split.preview`, and
  `entities.split` are the separate operator-only identity-correction entry
  points. Split restores the recorded inverse effects of one completed merge,
  including Relationship Memory redistribution; Review acceptance returns the
  preview handoff and never applies it. Remote publication is not implied by a raw
  allowlist: it additionally requires global remote writes and an exact
  server-resolved `remote.operator` durable capability set, then preserves the
  allowed-capability, purpose, feature, Principal, policy, and audit gates. This
  change activates no live profile or flag. Split and the bounded nine-trigger
  re-enrichment contract are implemented in repository code. WP-08 commissioning
  and WP-09 synthetic canary execution remain explicit operator-only actions;
  their repository procedures are documentation, not activation evidence. The
  broader `WP-10` discovery,
  backfill, and complete cross-plane re-enrichment framework remains an explicit
  gap.
* **The context card counts coverage from at most
  `CONTEXT_CARD_COVERAGE_LIMIT` observations**, and says so
  (`COVERAGE_COUNTED_A_BOUNDED_SAMPLE`) when the ceiling bites. Beyond it the
  per-source counts are floors and a source may be missing entirely.
* **The specification is silent** on identifier namespaces, the normalization
  algorithm, `effective_from`/`effective_to` null and overlap semantics, as-of
  queries, merge-redirect read behaviour, person lifecycle values, and
  organization resolution. WP-RI-03 and WP-RI-04 must decide each explicitly
  rather than inherit an assumption.
