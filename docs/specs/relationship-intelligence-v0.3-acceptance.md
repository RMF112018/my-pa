# Relationship Intelligence v0.3 — acceptance matrix


> **DEMOTED 2026-08-20 — this is not a compliance ledger.**
>
> It scores `relationship-intelligence-v0.3.md`, which governs nothing: the
> operator has stated they do not know where that document came from, it carries
> no publisher receipt, and an agent wrote it into the repository outside any
> instruction. A disposition against an ungoverning document is a record of what
> was checked, not a statement of what the campaign owes.
>
> The campaign's own acceptance ledger is section 3 of
> [`docs/plans/relationship-intelligence-implementation-plan.md`](../plans/relationship-intelligence-implementation-plan.md),
> scored against `relationship-intelligence-v0.2.md`. Where the two disagree,
> that one is the ledger.
>
> Retained because the work it records is real — the program-scale fixture and
> its acceptance suite exist, run, and are mutation-checked — and deleting the
> scoring would lose the evidence along with the authority it never had.

Disposition of `RI-AC-001` through `RI-AC-040` from
`FEATURE-MYPA-RELATIONSHIP-INTELLIGENCE-001 v0.3`, mirrored at
[`relationship-intelligence-v0.3.md`](relationship-intelligence-v0.3.md).

## Where these dispositions come from, and how far to trust them

The baseline is **not** this repository's self-assessment. It is
`AUDIT-MYPA-RELATIONSHIP-INTELLIGENCE-PR135-20260819-001`, an independent
exact-head audit bound to head `d5861e928b0f6da48cf32f0445292b694879aaac`,
disposition `CORRECTIONS_REQUIRED`. That matters because the audit's headline
finding was that the repository had been marking work complete against a
*substituted* ledger: PR #135 named `relationship-intelligence-v0.2.md` as its
requirements source and evaluated a different first-forty. A matrix that
re-derived its own dispositions from the same code that produced the drift would
reproduce the drift. So the independent dispositions are inherited, and this
document records only what has **changed since that head**, with the artifact.

Rows marked `[revised]` departed from the audit and say why. Every other row is
the auditor's finding carried forward unchanged.

**A later commit invalidates the exact-head review.** The corrections recorded
here already do that: this tree is no longer `d5861e92…`. A fresh independent
review of the corrected head is required before merge eligibility, and nothing
in this document supplies it.

## Status vocabulary

`MET` — satisfied, with evidence at the required proof tier.
`PARTIAL` — some of the criterion holds; the remainder is named.
`UNMET` — not satisfied.
`NOT_YET_PROVEN` — may hold, but the evidence required to say so does not exist.

## Proof tiers

`UNIT`, `DATABASE`, `CONTRACT`, `INTEGRATION`, `SYNTHETIC_E2E`, `REMOTE_CANARY`,
`LIVE_OPERATOR_PILOT`. Per the controlling plan, a criterion requiring remote or
live evidence **may not** be marked satisfied by source inspection or unit tests.
No `REMOTE_CANARY` or `LIVE_OPERATOR_PILOT` evidence exists for any row below,
and none is claimed.

## Matrix

| Criterion | Status | Tier reached | Evidence / what remains |
|---|---|---|---|
| RI-AC-001 durable opaque ID | MET | UNIT, DATABASE | `IdKind.ENTITY`; `entities.entity_id` independent of name. |
| RI-AC-002 same-name entities stay distinct | MET | UNIT | Collision families in the labelled corpus; no false join observed. |
| RI-AC-003 verified unique identifiers resolve | MET | UNIT | `EntityResolutionService._by_identifier`, temporally filtered. |
| RI-AC-004 ambiguous references return AMBIGUOUS | MET | UNIT | `ResolutionOutcome.AMBIGUOUS` is structural; `resolved_entity_id` is derived and `None`. |
| RI-AC-005 alternatives and explainable features | MET | UNIT | `ResolutionCandidate.evidence` / `ResolutionBasis`; see the ranking note below. |
| RI-AC-006 historical evidence resolves without reading as current | MET | UNIT | `HISTORICAL_MATCH` plus currency warnings. |
| RI-AC-007 scoped manual clarification persists | UNMET | — | No scoped resolution binding exists. The controlling plan names an `entity_resolution_bindings` table; nothing implements it. A local clarification would have to become a global alias, which the criterion forbids. |
| RI-AC-008 employment changes preserve prior assignments | PARTIAL | UNIT, DATABASE | The temporal model preserves history. The governed update workflow that would exercise it does not exist. |
| RI-AC-009 effective-dated assignments queryable | MET | UNIT, DATABASE | `entity_assignments` with effective dating. |
| RI-AC-010 current role is a derived view | UNMET | — | No derived current-role/title projection. |
| RI-AC-011 multiple concurrent scoped roles | MET | UNIT, DATABASE | Representable and queryable. |
| RI-AC-012 material facts carry provenance | UNMET | — | Observations carry source identity; aliases, identifiers, assignments and relationships carry no evidence link. This is the keystone gap — four further criteria sit downstream of it. |
| RI-AC-013 inferred facts stay labelled until promoted | UNMET | — | No epistemic state on the fact records (`CONFIRMED` / `SOURCE_OBSERVED` / `DERIVED` / `INFERRED` / `PROPOSED` / `REJECTED` / `SUPERSEDED` / `CONFLICTED` or a bounded equivalent). |
| RI-AC-014 conflicting evidence preserved and surfaced | PARTIAL | UNIT | Conflicting *identifier* ownership is surfaced as `CONFLICTED_IDENTIFIER`. Contradictory role/company observations have no conflict state. |
| RI-AC-015 summaries cannot self-corroborate | NOT_YET_PROVEN | — | No generated-summary integration exists to prove this end to end. Not provable by source inspection. |
| RI-AC-016 rejected proposals stay auditable, out of canonical views | MET | UNIT, DATABASE | Proposal state machine retains rejections. |
| RI-AC-017 duplicates proposed without merging | MET | UNIT | Proposal kind exists; no automatic merge. |
| RI-AC-018 merge requires preview, authorization, idempotency, audit | UNMET | — | No non-mutating merge preview. Authority is a caller-supplied `has_operator_authority: bool` rather than derived from authenticated context. |
| RI-AC-019 merged IDs resolve through a redirect | MET | UNIT, DATABASE | `redirect_entity`, cycle- and chain-guarded. |
| RI-AC-020 erroneous merge can be split/corrected | UNMET | — | No split or correction path. |
| RI-AC-021 authorized client can search | MET | CONTRACT | `entities.search` behind capability + feature gate. |
| RI-AC-022 ambiguous resolve returns alternatives | MET | CONTRACT | Alternatives preserved through serialization. |
| RI-AC-023 bounded context card | MET | CONTRACT | `[revised]` Strengthened this cycle: card collections are now bounded **at the query** rather than fetched whole and sliced, and truncation is disclosed with a stated reason (`tests/contract/test_entity_read_bounds.py`). Audit finding MAJOR-001 addressed. |
| RI-AC-024 capability/grant/feature gating | MET | CONTRACT | Default-off; MCP publication tracks the capability set. |
| RI-AC-025 scheduled profile has no merge/split authority | MET | CONTRACT | Read-only dormant task profile. |
| RI-AC-026 entity tools share application services | MET | CONTRACT | Shared handlers across transports. |
| RI-AC-027 no cross-Principal leakage | MET | DATABASE, CONTRACT | Per-statement partitioning; isolation suite. |
| RI-AC-028 caller Principal impersonation rejected | MET | CONTRACT | Principal never caller-supplied. |
| RI-AC-029 no unnecessary PII disclosure | MET | CONTRACT | Observed values omitted from tool output. |
| RI-AC-030 consequential writes produce audit/receipt | PARTIAL | DATABASE | Proposal and merge lineage are durable. A common receipt path across consequential writes is incomplete. |
| RI-AC-031 program-scale fixture (500 persons / 100 orgs) | MET | DATABASE | `[revised]` Audit found this absent. A seeded synthetic fixture now exists at `tests/evaluation/fixtures/program_scale_corpus.py`, verified at **565 persons, 105 organizations, 6 programs, 24 projects, 48 work packages, 5,262 combined alias/identifier/assignment/relationship/observation records, 60 collision groups, 80 historical employment changes**, plus recycled mailboxes, conflicted addresses, merge redirects and stale roles. Every stated minimum is exceeded. **Tier corrected 2026-08-19 from `UNIT` to none.** No test of any tier imports either fixture module — `grep -rn "program_scale" tests/ src/ scripts/ apps/` returns only the two files themselves, and `fixtures/__init__.py` does not export them — so there is no unit-tier evidence to cite. The disposition rests on loading the module and counting, which is why the criterion is `MET` and the tier is blank; **Tier restored to `DATABASE` 2026-08-20**, when `tests/database/test_program_scale_acceptance.py` was written: the floors are now asserted against the built rows, not the builder's constants. |
| RI-AC-032 acceptance suite passes against that fixture | MET | DATABASE | **Met 2026-08-20.** `tests/database/test_program_scale_acceptance.py` loads all 5,262 records into a disposable PostgreSQL database and answers all 1,090 labelled cases through `SqlEntityRepository` — not through the in-memory double the small corpus uses, because this criterion is about scale and about SQL. Zero wrong outcomes, zero wrong entities, zero forbidden candidates, zero omissions. Mutation-checked: disabling the conflicted-identifier refusal fails it by case name. |
| RI-AC-033 search/resolution/context benchmarked | UNMET | — | No p50/p95 measurement for any of the six required operations. |
| RI-AC-034 Meeting Intelligence attaches entity IDs | UNMET | — | No integration seam or contract test. |
| RI-AC-035 Action/Commitment counterparty linkage | UNMET | — | No integration seam or contract test. |
| RI-AC-036 `context.prepare` includes entity context | UNMET | — | `EntityContextService` exists but no changed source file integrates it into the `context.prepare` path. |
| RI-AC-037 scheduled discoveries enter observation/proposal paths | UNMET | — | Only a read profile exists; no contribution path. |
| RI-AC-038 search distinguishes same-name by org/project/role | UNMET | — | `entities.search` returns ID/type/canonical/display/status only — no disambiguators (audit MAJOR-003). |
| RI-AC-039 conversational identity correction | UNMET | — | `EntityGovernanceService` has no production caller or operator surface. |
| RI-AC-040 inspect why a role/relationship is believed | UNMET | — | Blocked on RI-AC-012. The card can list nearby observations but cannot show which observation supports a specific fact. |

## Tally

| Status | Count |
|---|---|
| MET | 22 |
| PARTIAL | 3 |
| NOT_YET_PROVEN | 1 |
| UNMET | 14 |

Two rows have moved since the audited head. `RI-AC-031` went UNMET to MET when
the fixture was built, and its evidence tier has moved twice since: to none, when
a reviewer established that no test of any tier read the fixture, and back to
`DATABASE` on 2026-08-20 when one was written. `RI-AC-032` went UNMET to MET on
the same day and for the same reason — the acceptance suite now runs against the
fixture under PostgreSQL, which is what that criterion asks for. `RI-AC-023` was
already satisfied and was strengthened rather than changed.

`RI-AC-033` remains UNMET and is the last of this group: no p50/p95 measurement
exists for any of the six required operations, and the new suite deliberately
does not time anything — a wall-clock assertion on a shared, contended database
measures the machine.

## A conflict between the v0.3 spec and a repository rule

The v0.3 spec asks for "ranked alternatives" (`RI-AC-005`) and describes a
"contextual ranking" stage. `tests/architecture/test_relationship_scoring_surface_is_denied.py`
denies the token `rank` — along with `score`, `confidence`, `weight`, `priority`
and `tier` — anywhere on the durable relationship surface, because the operating
brief forbids a hidden relationship score or a ranking of people.

These are reconcilable and are reconciled: the repository satisfies the spec's
*intent* by ordering candidates over a closed `ResolutionBasis` vocabulary — an
order over **kinds of evidence**, which is explainable and carries no per-person
number — rather than by storing a rank or a confidence. Any future work here must
satisfy `RI-AC-005` without introducing a scoring field; adding one would redden
the architecture guard, and correctly so. Recorded so the tension is a decision
rather than a surprise.
