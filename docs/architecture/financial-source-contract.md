# Financial controlled source — whole-slice contract (F-1 domain and parser, F-2 persistence and import, F-3 reads)

**Status:** proposed implementation contract for the financial controlled-source slice
(WP-05A, CR-011, AT-020) under
[`ADR-018`](../decisions/ADR-018-financial-controlled-source-model.md) (Proposed — **not
accepted**; design and synthetic proof undertaken under the operator's program directive of
2026-10-17 and the operator's 2026-11-12 discretion grant, with F-1 selected by the Manager,
inside OD-06's "theoretical schema/fixtures can be prepared" carve-out; the model decisions
are not operator-ratified). Revision R11-1 resolves design review R11 (section 15). It is the
single document the
F-1 (pure domain, synthetic interchange parser, synthetic fixtures), F-2 (schema,
persistence, operator-only import, mapping review) and F-3 (Program financial read and its
exposure) implementers code against. **Only F-1 is in scope now.** F-2 and F-3 are written
here at contract level so F-1 does not foreclose them; each needs its own authorization,
review and, for any real data, the operator source designation of OD-06.

| Fact | State at this contract |
| --- | --- |
| Real financial source | **none designated** (OD-06 open; UB-009 `FINANCE_SOURCE_NOT_DESIGNATED`) |
| Certified Program financial totals | **unreachable** (OD-08: any material gap is `NOT_REPORTABLE`; a looser threshold is an operator risk acceptance) |
| F-1 content | pure domain under `src/my_pa/domain/project_controls/financial/`, the synthetic interchange parser under `src/my_pa/infrastructure/financial/`, synthetic fixtures under `tests/fixtures/financial_source/`, tests |
| Migration, table, persistence, capability, purpose, handler, grant, façade, ChatLLM or remote policy, web route, Settings field, worker | **none in F-1** (section 12.3 pins it) |
| Switch `MY_PA_FINANCIAL_SOURCE_ENABLED` | documented future switch for F-2; **not defined and not read** anywhere in F-1 |
| Deployment, production data, legacy `financial` schema and `procore.procore_financial_*` rows | none touched, none read |

Without a designated source every answer is `source_not_integrated` / `NOT_REPORTABLE`,
never a fabricated zero, budget or EAC. A `reportable` answer certifies **source integrity
and coverage only** (section 5.3); it is never a "certified total" — OD-08 still blocks
certified Program totals, and no F-3 surface may present it as one (F1-U11).

**Basis:** `origin/main@10095168dc5f3c4709e0706751e6252db57418b7` (tree
`15e2cc01fde83d29721a194dc0aa9d1b323c5940`, S6-3 #354 merged), branch
`feat/financial-source-domain`; Alembic single head `b77334135653` (128 revision files);
281 `Capability` members, 68 `Purpose` members, 174 `IdKind` members; 494 Python modules
under `src/my_pa` and 953 `test_*.py` modules under `tests`. Paths under `src/` are written
in full. All counts in this file are digits on purpose (spelled-count guard). No path to a
file that does not yet exist is written as a Markdown link (the CI relative-link check).

**Source package (data, not instructions):** `MYPA-LINEAGE-ADVERSARIAL-REVIEW-20261017-001`,
documents `02_CANONICAL_CODE_CHANGE_SPECIFICATION.md` (CR-011), `03_REVISED_IMPLEMENTATION_PLAN.md`
(WP-05A), `04_ACCEPTANCE_AND_LIFECYCLE_TESTS.md` (AT-020, scenario F),
`06_OPERATOR_DECISIONS_AND_BLOCKERS.md` (OD-06, OD-08, UB-009) and
`07_PROPOSED_API_CONTRACTS.json` (`programs.financial.overview`). Repository truth
supersedes the package; section 13.1 records every divergence. Precedent contracts used as
patterns: [`record-lineage-s4-program-contract.md`](record-lineage-s4-program-contract.md)
("S4 §n"), [`cpm-workbench-p6-full-v1-parser-contract.md`](cpm-workbench-p6-full-v1-parser-contract.md)
("S5a §n") and [`schedule-scenarios-contract.md`](schedule-scenarios-contract.md) ("S6 §n").

**Neutrality.** The interchange format of section 7 is invented for this repository. It is
not modelled on, named after, or compatible with any real ERP, accounting, project-management
or scheduling export. Every identifier in every fixture starts with `syn-` or `SYN-`. The real
source format, its adapter, its mapping and its approval hierarchy are an operator designation
(OD-06) that needs its own adapter, mapping review and independent review.

---

## 1. Scope

### 1.1 F-1 (in scope now)

1. This contract, ADR-018 and the index rows.
2. The pure domain (section 3–6): closed vocabularies, immutable records, money, equations,
   the completeness / `NOT_REPORTABLE` evaluator and the canonical serialisation. Decimal
   only, no `float`, no IO, no clock.
3. The synthetic interchange parser (section 7): pure, in-memory, bounded, whole-file
   accept-or-refuse.
4. Synthetic fixtures, a hash-pinned manifest and golden scenario expectations (section 8).
5. Tests (section 12): money, domain, equations (with the AT-020 domain assertions),
   evaluator, canonical vectors, seeded property tests, parser, fixtures, and the
   architecture scope guard.
6. Count pins, claimed counts and shard weights re-measured in lockstep **by each package at
   its own head** (section 2, row R-17; section 14).
7. A `.gitattributes` rule keeping the byte-exact fixtures out of text and whitespace
   handling (section 8.1).

### 1.2 Not in F-1

Persistence, migrations, identifier kinds, import, mapping review writes, the switch,
capabilities, purposes, handlers, policy, grants, ChatLLM profiles, remote MCP, façade, web,
reports, any read of the legacy `financial` PostgreSQL schema, any real or personal data, and
any FX conversion. F-2 owns persistence and import (section 9); F-3 owns reads and exposure
(section 10).

### 1.3 What "done" means for F-1

Every section 12 test exists with the name given, passes in the FAST tier, and the section
12.4 prove-red table has been executed one mutation at a time. The scope guard is green and
proves nothing public or persistent exists.

---

## 2. Repository reauthentication at `10095168` and decisions

| # | Claim (package or brief) | Package value | Repository truth at the basis | Decision |
| --- | --- | --- | --- | --- |
| R-01 | Domain module | `domain/project_controls/financial.py` | `src/my_pa/domain/project_controls/` is the Constraint Management package (`business_time`, `category`, `constraint`, `history`, `party`, `read_models`, `relationship`, `revision`, `settings`, `sync`); its `__init__.py` re-exports the Constraint surface | **F1-D01:** a subpackage `src/my_pa/domain/project_controls/financial/` with 6 modules (section 3.1); **not** re-exported from `project_controls/__init__.py`, so the Constraint package surface and its importers are unchanged |
| R-02 | Program metric types | 07 `coverage_state` (8 values), `value` integer/number | S4 `src/my_pa/domain/program/vocabulary.py` defines `MetricValueState` (`reported`, `not_reportable`, `restricted`) and a closed `NotReportableReason` (9 Program-work reasons) pinned by the S4 scope guard | **Reuse** `MetricValueState` by import; **do not extend** `NotReportableReason`; define `FinancialNotReportableReason` (section 5.1). F1-D04, F1-D05 |
| R-03 | Money helpers | none named | No money type exists. `src/my_pa/domain/schedule/currency.py` (S6-1) is the *current standard update* of a schedule Series (publication freshness), not currency. `src/my_pa/domain/situation/situation.py::is_storable_project_value` checks `numeric(14, 2)` Project values (USD, non-negative) | **Not reused** (different meaning / different precision); new `money.py` (section 3.3). F1-D20 |
| R-04 | Canonical JSON / hash | "exact hash parity" | 5 encoders exist. The schedule idiom: `my_pa.domain.schedule.canonical.canonical_json_bytes` (sorted keys, `(",", ":")`, `ensure_ascii=True`, `allow_nan=False`) with digest `sha256(schema_ascii + b"\n" + canonical)` (`my_pa.domain.schedule.scenario.canonical._digest`). Lineage and knowledge encoders are NFC / non-ASCII | **Reuse** `my_pa.domain.schedule.canonical.canonical_json_bytes` by import and the `schema + "\n"` domain-prefix idiom (section 6). Finance content is ASCII-only, so the ASCII encoder is exact. F1-D21 |
| R-05 | Parser sandbox | "isolated format parsers" | S5a: pure parser, closed refusal codes, `PRODUCTION_LIMITS`, validation order, exception contract, goldens pinned by `GOLDEN_FILE_SHA256` in `tests/unit/test_schedule_full_goldens.py`, writer never called by a test. S5b-2 adds child-process containment in the worker (`tests/unit/test_schedule_parser_isolation.py`). `tests/parser_isolation/` is `SCAFFOLD_ONLY` | Same shape (section 7). F-1 parser is in-process and pure; child containment belongs to the F-2 import path (F1-U01). Parser tests live in `tests/unit/` (F1-D14) |
| R-06 | Property tests | not specified | `hypothesis` is **not** a dependency (`pyproject.toml`; `import hypothesis` fails in the repo venv). S6-1 precedent: `tests/unit/test_scenario_cpm_oracle.py` uses `random.Random(seed)` with `# noqa: S311` | Seeded deterministic generators (section 12.2) |
| R-07 | ADR number | — | `docs/decisions/` holds ADR-001 to ADR-017 | **ADR-018** allocated |
| R-08 | Capability naming | `programs.financial.overview` (07) | `programs.members.resolve`, `programs.overview` exist (S4), Purpose `program_reporting_read`, behind `MY_PA_PROGRAM_REPORTING_ENABLED` | F-3 adds `programs.financial.overview` in the same `programs.*` family with its own purpose (section 10). No capability in F-1 |
| R-09 | IdKind | finance identifiers implied | 174 members; none of `fdes`, `fsrun`, `fsver`, `fmap`, `fpsn`, `fline`, `fchg`, `fxfr`, `fleg` is used | F-1 adds **no** IdKind; F-2 adds the 9 planned prefixes (section 9.2) |
| R-10 | Tables | 8 `financial_*` tables | None of the 9 planned table names (section 9.1) exists in `src/my_pa/infrastructure/persistence/tables.py` (`METADATA` schema `knowledge`). A **migrated legacy** PostgreSQL schema named `financial` exists: created by revision `5d75f23847c9` (`SCHEMAS` tuple), its tables by the generated target DDL `migrations/sql/target_tables.up.sql` (e.g. `"financial"."aging_exposure_report_items"`, `"financial"."forecast_accuracy_results"`) under revision `1e6c0a94f3b7`. `migrations/data/disposition_registry.json` lists 67 objects with `target_schema = "financial"`: dispositions `MIGRATE_DATA` 28, `REBUILD_AND_VALIDATE` 20, `ARCHIVE_LEGACY_SOURCE_ONLY` 11, `REINITIALIZE_OPERATIONAL_STATE` 8; sensitivity `FINANCIAL_OPERATIONAL` 65, `PERSONAL_COMMUNICATION_OR_IDENTITY` 2; object families `forecast_*` (including `forecast_external_forecasts`, `forecast_cost_entries`, `forecast_monthly_actuals_by_budget_code`, `forecast_source_ingestions`, `forecast_budget_details`), `second_brain_financial_*` and `staffing_*`. `financial` is in `_SCHEMAS` of `src/my_pa/infrastructure/database/mcp_object_grants.py` and in `src/my_pa/infrastructure/migration/reconciliation.py`. Production row content is **unverified** (28 objects are data-migration targets, so real financial rows may exist) | F-2 tables are always schema-qualified `knowledge.financial_*`; never created in, granted through or read from schema `financial`. The legacy schema is unanalysed and **not** a designated source; it does not change UB-009. It is recorded as a possible OD-06 candidate needing its own analysis and designation (F1-O12, F1-D08, F1-U09) |
| R-10a | Procore financial tables | not mentioned | schema `procore` holds legacy `procore_financial_change_orders`, `procore_financial_change_order_line_items`, `procore_financial_change_events` (target DDL); the target DDL also names `second_brain_financial_source_coverage_snapshots` and the column `raw_financial_source_payload_persisted` | Not read, not mapped, not designated by any slice here; no F-2/F-3 code reads `procore.*` or `financial.*` (an F-2/F-3 obligation, section 9.1). Possible OD-06 candidate (F1-O12). The F-1 scope guard must not match these legacy names (section 12.3 positive control) |
| R-11 | Finance mentions in source | — | `financial_mention` (Capture classification), `financial_fact` (Knowledge consequential class), the legacy schema name; none is a finance ledger | Untouched; the scope guard matches only this slice's tokens (section 12.3) |
| R-12 | Operator-only source import | operator designation | S5b-2 precedent: `schedule_publications.import` is an operator-only, attested-local capability (ADR-016) | F-2 follows that precedent (section 9.4); OD for CLI vs capability recorded as F1-O09 |
| R-13 | Domain dependency rule | — | `tests/architecture/test_dependency_direction.py`: domain uses only the standard library and `my_pa.domain` / `my_pa.contracts`; domain may import other domain packages | Finance domain imports stdlib + `my_pa.domain.schedule.canonical` (`canonical_json_bytes` only) + `my_pa.domain.program.vocabulary` (`MetricValueState` only) |
| R-14 | Settings field | switch `MY_PA_FINANCIAL_SOURCE_ENABLED` | Switches live in `src/my_pa/bootstrap/settings.py` | **F1-D15:** F-1 adds no Settings field; the scope guard pins that the string has no consumer |
| R-15 | `programs.financial.overview` input | `program_entity_id`, `period`, `perspective`, `currency` | Variance is defined only within 1 cost basis | F-3 adds required `cost_basis` (F1-D11) |
| R-16 | AT-020 test | `tests/integration/test_financial_scope_transfer.py` (database+integration) | no finance persistence exists | AT-020 domain half in F-1 (`tests/unit/test_financial_equations.py`); the DB half keeps the package path and is **owned by F-2**, not added as a skipped test (F1-D13) |
| R-17 | Count pins F-1 trips | — | `tests/architecture/test_spelled_counts_match_the_sets_they_name.py::test_section_3_states_the_module_counts_it_says_it_derives` binds `docs/plans/mcv-completion-plan.md` section 3 to `find src/my_pa -name "*.py"` and `find tests -name "test_*.py"`; `tests/architecture/test_claimed_test_counts_match_collection.py` binds the mypy corpus, FAST and architecture tier figures in `docs/plans/relationship-intelligence-implementation-plan.md`; `tests/ci_shard_weights.json` and `python -m tests.ci_shard verify` | F-1 adds 8 source modules and 9 test modules: **I11-A** 494 → 500 source, 953 → 959 test; **I11-B** 500 → 502, 959 → 962. **Each package** re-measures every figure of both contended `docs/plans` files with the command its sentence names, in the file's own style (a dated current paragraph, the previous one demoted), and re-weighs `tests/ci_shard_weights.json` and runs `python -m tests.ci_shard verify` **at its own head**, so every package head is green. No Capability, Purpose, IdKind or revision count moves |

---

## 3. Domain model (CR-011)

### 3.1 Module layout (F1-D01)

| Path | Content |
| --- | --- |
| `src/my_pa/domain/project_controls/financial/__init__.py` | docstring only; no re-exports (keeps the import graph explicit for the scope guard) |
| `src/my_pa/domain/project_controls/financial/money.py` | currency table, amount grammar, `FINANCE_CONTEXT`, `parse_amount`, `format_amount`, `is_storable_amount`, `money_sum`, `presentation_amount`, `minor_units` |
| `src/my_pa/domain/project_controls/financial/model.py` | every closed vocabulary of section 3.2 and 5.1 and every record of section 3.4–3.9 with `__post_init__` invariants |
| `src/my_pa/domain/project_controls/financial/equations.py` | section 4: per-Project figures, reconciliation, Program consolidation, eliminations, double-count detection |
| `src/my_pa/domain/project_controls/financial/reportability.py` | section 3.10 run admission, section 3.7 version resolution, section 3.8 mapping resolution, section 5 evaluator `evaluate_financial_overview` |
| `src/my_pa/domain/project_controls/financial/canonical.py` | section 6: canonical objects, digests, strict decoder |
| `src/my_pa/infrastructure/financial/__init__.py` | docstring only |
| `src/my_pa/infrastructure/financial/synthetic_csv.py` | section 7: `parse_synthetic_finance` |

Every record is `@dataclass(frozen=True, slots=True)`; every invariant failure raises
`ValueError` (or `TypeError` for a wrong type) with a fixed message that carries no field
value.

### 3.2 Closed vocabularies (`StrEnum`, values exactly as written)

| Vocabulary | Members |
| --- | --- |
| `FinancialPerspective` | `owner_budget`, `construction_contract` |
| `CostBasis` | `gross`, `net` |
| `SourceVersionStatus` | `approved`, `proposed`, `withdrawn` |
| `AccountMeasure` | `original_budget`, `current_budget`, `original_contract`, `actual_cost`, `forecast_cost_to_complete`, `source_eac`, `committed_cost`, `contingency`, `allowance` |
| `ChangeStatus` | `approved`, `pending` |
| `LegSide` | `debit`, `credit` |
| `MappingState` | `proposed`, `accepted`, `rejected`, `quarantined` |
| `MatchBasis` | `operator_review` |
| `RunOutcome` | `admitted`, `refused` |
| `AdmissionRefusalCode` | `source_system_mismatch`, `perspective_not_designated` |
| `FinancialReportability` | `reportable`, `not_reportable`, `source_not_integrated` (07 enum verbatim) |
| `FinancialSourceState` | `effective`, `not_integrated`, `integrity_gap`, `mapping_gap`, `approval_gap`, `source_gap` |
| `FinancialMetric` | section 4.1 (17 members) |
| `FinancialNotReportableReason` | section 5.1 (29 members) |
| `FinanceParseRefusalCode` | section 7.8 (50 members) |

Measures valid per perspective (anything else is parser refusal `measure_perspective_mismatch`):

| Measure | `owner_budget` | `construction_contract` | Sign |
| --- | --- | --- | --- |
| `original_budget` | yes | no | ≥ 0 |
| `current_budget` | yes | no | ≥ 0 |
| `original_contract` | no | yes | ≥ 0 |
| `actual_cost` | yes | yes | ≥ 0 |
| `forecast_cost_to_complete` | yes | yes | ≥ 0 |
| `source_eac` | yes | yes | ≥ 0 |
| `committed_cost` (procurement financial commitment; distinct from the social `cmt_` Commitment) | yes | yes | ≥ 0 |
| `contingency` | yes | yes | ≥ 0 |
| `allowance` | yes | yes | ≥ 0 |

The sign column applies to `account_line` records only (parser code `amount_sign`). A change
order amount is any non-zero amount (deductive changes are negative; zero is
`change_order_zero`). A transfer leg is `debit` with amount < 0 and `credit` with amount > 0,
checked **only** by `transfer_leg_sign`, never by `amount_sign` (R11-F12).

### 3.3 Money (`money.py`)

| Item | Rule |
| --- | --- |
| Type | `decimal.Decimal` only. A `float` anywhere (construction, arithmetic, comparison) is refused: records raise `TypeError` on a `float` field; `FINANCE_CONTEXT` traps `FloatOperation` |
| Storage semantics | `NUMERIC(20,4)`: scale exactly 4, at most 16 integer digits, `-10^16 < amount < 10^16` (`AMOUNT_LIMIT = Decimal(10) ** 16`, exclusive) |
| Canonical value | every amount held by a record is `quantize(Decimal("0.0001"))` of its exact input and satisfies `is_storable_amount`; constructing a record with an exponent other than `-4` raises `ValueError` |
| `is_storable_amount(value: object) -> bool` | `type(value) is Decimal`, finite, exponent `-4`, `abs(value) < AMOUNT_LIMIT`, not negative zero |
| `parse_amount(text: str) -> Decimal` | section 7.5 grammar; raises `AmountError(code)` with `code` ∈ {`amount_grammar`, `amount_negative_zero`, `amount_scale`, `amount_range`}; scale > 4 is **refused, never rounded**. The scale-4 `quantize` runs under `FINANCE_CONTEXT`, whose `Inexact`/`Rounded` traps make a rounding quantize impossible by construction (it would raise, and the grammar has already refused every input that could) |
| `money_sum(values: Iterable[Decimal]) -> Decimal` | starts from `Decimal("0.0000")` (exponent −4), so an empty sum is the storable `0.0000`, never `Decimal(0)` |
| Negation / absolute value | no result is built by unary negation; `transfers_out` uses `copy_abs()`, differences use subtraction; every result passes through `_normalise_zero` (a zero result is `Decimal("0.0000")`, never `-0.0000`) before `is_storable_amount` |
| `format_amount(value: Decimal) -> str` | `format(value, "f")` of a storable amount: always exactly 4 decimals, `-` only when < 0, never an exponent, never `-0.0000` (e.g. `"-150000.0000"`, `"0.0000"`) |
| Arithmetic | `money_sum(values)` and every subtraction run under `FINANCE_CONTEXT = Context(prec=38, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999, traps=[InvalidOperation, DivisionByZero, Overflow, Underflow, Subnormal, Inexact, Rounded, FloatOperation])`. Sums of scale-4 values are exact, so `Inexact`/`Rounded` never fire on valid data; if they fire the computation raises (a bug, not a rounding). A result is then checked with `is_storable_amount`; `abs(result) ≥ AMOUNT_LIMIT` becomes metric reason `aggregate_out_of_range` (section 5), never a clamp |
| Rounding | **Forbidden** in parsing, storage, equations, consolidation, hashing and the overview. **Only** `presentation_amount(value, currency) -> str` rounds: `value.quantize(Decimal(1).scaleb(-minor_units(currency)), rounding=ROUND_HALF_EVEN)` under a context without the `Inexact`/`Rounded` traps; a negative zero result is written without sign. Presentation strings are never summed, stored, hashed or compared; F-1 uses it only in tests; F-3 may use it for display |
| Currency | ISO 4217 alphabetic code `^[A-Z]{3}$`. Closed table `CURRENCY_MINOR_UNITS = {"EUR": 2, "JPY": 0, "USD": 2}` (the currencies the fixtures use). A well-formed code not in the table is refused (`currency_unknown`) — minor units are never guessed. Adding a currency is a contract amendment (table row + test vector) |
| FX | **None.** No conversion function exists in F-1. A currency different from the request currency is `currency_mismatch` + `fx_missing` (section 5). An FX authority is operator decision F1-O04 |

### 3.4 Source designation (operator placeholder)

`SourceDesignation(source_system: str, perspectives: frozenset[FinancialPerspective],
approvers: frozenset[str])` — the operator's statement that `source_system` is the authority
for those perspectives and that `approvers` are the recognized approval actors.
`source_system` and each approver match the identifier grammar (section 7.5); `perspectives`
and `approvers` are non-empty. **F-1 has no production designation:** designations are an
evaluator input supplied by tests only; F-2 persists operator designations (section 9) and
until OD-06 none exists, so every F-3 answer is `source_not_integrated`. The evaluator
receives **active** designations only (F-2 filters revoked ones before calling it); 2
designations naming the same `source_system` in 1 call are an input-contract violation and
raise `ValueError` (F-2 keeps at most 1 active designation per system). Approver names and the
source system are self-asserted export content (section 11).

### 3.5 Source run and source version

| Record | Fields | Invariants |
| --- | --- | --- |
| `SourceVersion` | `source_system`, `source_version_ref`, `period` (`YYYY-MM`), `cutoff_at` (aware UTC `datetime`), `status`, `approved_by: str \| None`, `approved_at: datetime \| None`, `supersedes_ref: str \| None`, `perspective`, `currency`, `cost_basis`, `account_lines: tuple[AccountLine, ...]`, `change_orders: tuple[ChangeOrder, ...]`, `transfers: tuple[ScopeTransfer, ...]` | `approved_by`/`approved_at` both set when `status` ∈ {`approved`, `withdrawn`}, both `None` when `proposed`; `withdrawn` ⇒ `supersedes_ref` set and no lines/orders/transfers; `supersedes_ref != source_version_ref`; `cutoff_at ≥` first instant of `period` (UTC); every line measure valid for `perspective`; refs unique across lines, orders, legs and transfer refs; account-line identity unique (section 3.6); immutable (frozen, tuples) |
| `SourceRun` | `run_ref`, `run_sequence: int ≥ 1`, `designated_source_system`, `file_sha256`, `outcome`, `refusal_code: FinanceParseRefusalCode \| AdmissionRefusalCode \| None`, `refusal_line: int \| None`, `version: SourceVersion \| None`, `content_sha256: str \| None` | `admitted` ⇔ `version` and `content_sha256` set and no refusal; `refused` ⇔ `refusal_code` set and no version |

`content_sha256` is the section 6.2 digest of `version`, computed once at admission and
carried so the evaluator can recompute and compare it (hash parity, reason `hash_mismatch`).
The report period is **data**: it comes from the file's `period` cell only, never from
the run, the clock or the import time.

### 3.6 Lines, change orders, scope transfers

| Record | Fields | Notes |
| --- | --- | --- |
| `AccountLine` | `ref`, `external_project_id`, `external_contract_id: str \| None`, `cost_code`, `wbs_package`, `measure`, `amount` | identity within a version: `(external_project_id, external_contract_id or "", cost_code, wbs_package, measure)` |
| `ChangeOrder` | `ref`, `external_project_id`, `external_contract_id: str \| None`, `cost_code`, `wbs_package`, `change_status`, `amount ≠ 0` | `approved` enters approved figures; `pending` is reported separately only |
| `TransferLeg` | `ref`, `external_project_id`, `leg_side`, `amount` | `debit` < 0, `credit` > 0 |
| `ScopeTransfer` | `transfer_ref`, `cost_code`, `wbs_package`, `change_status`, `legs: tuple[TransferLeg, TransferLeg]` | exactly 2 legs, 1 `debit` + 1 `credit`, different `external_project_id`, `debit.amount + credit.amount == 0` exactly; legs ordered `(credit, debit)` (lexical) |

Full identity tuple of a reported amount (F1-D06): `(source_system, source_version_ref,
period, perspective, currency, cost_basis, external_project_id, external_contract_id,
cost_code, wbs_package, measure)` for account lines; change orders and transfers are
identified by `(source_system, source_version_ref, ref | transfer_ref)`.

### 3.7 Version resolution (immutability, supersession, spoofing)

Inputs: the admitted and refused runs of 1 designated system S, after the request's
`source_cutoff` filter (section 5.3 step 1). Definitions:

- A **version** is identified by its `content_sha256`; 2 or more admitted runs with equal
  `content_sha256` carry the **same** version (idempotent re-import, including a re-export
  whose rows differ only in order and so whose `file_sha256` differs).
- The **admitting run** of a version is the admitted run with the **greatest
  `run_sequence`** among the admitted runs carrying that `content_sha256` (R11-F05).
- The **scope key** is `(S, period, perspective, currency, cost_basis)`.

1. **Conflict (system-wide, terminal).** If 2 admitted versions of S have the same
   `source_version_ref` and different `content_sha256` — in **any** period, perspective,
   currency or basis — every Project mapped from S gets `source_version_conflict` for every
   request, and resolution for S stops (no effective version, no further version reason). A
   ref may never carry 2 contents. This detects an edited or spoofed re-export **only when
   the other content was imported too** (section 11, F1-U10).
2. **Supersession graph** over the versions of the scope key: an edge V → X when V is
   `approved` or `withdrawn` and `X.source_version_ref == V.supersedes_ref` with X in the same
   scope key. A `proposed` version **never** supersedes (F1-D18). A `supersedes_ref` naming no
   version of the scope key (dangling, or a version of another scope key) creates no edge: a
   dangling `approved` version stands on its own; a dangling `withdrawn` version withdraws
   nothing it can name and stays a `withdrawn` head (fail-closed).
3. **Heads** = versions of the scope key with no incoming edge. The table is exhaustive; `a`,
   `w`, `p` count `approved`, `withdrawn`, `proposed` heads:

   | Condition (checked in this order) | Outcome |
   | --- | --- |
   | no version of the scope key exists | 5.3 step 6 classification (the **only** route there) |
   | the supersession graph of the scope key has a cycle | `source_version_ambiguous` |
   | `a ≥ 2` | `source_version_ambiguous` |
   | `a = 1` and `w ≥ 1` | `source_version_ambiguous` (an approved and a withdrawn head disagree) |
   | `a = 1` and `w = 0` (any `p`) | that approved version is **effective** |
   | `a = 0` and `w ≥ 1` (any `p`; also several withdrawn heads) | `withdrawn_source` |
   | `a = 0`, `w = 0`, `p ≥ 1` | `approval_missing` |

   Versions exist in every row below the first, so "versions of the scope key exist" never
   produces a period/perspective/basis/currency mismatch or `source_version_missing`.
4. `proposed` versions of the scope key are disclosed as `pending_source_versions` (their
   `content_sha256`, sorted) and never feed a figure nor block one.
5. **Approval consistency checks** on the effective version: `approved_by ∉
   designation.approvers` ⇒ `approval_actor_unrecognized`; `approved_at < cutoff_at` ⇒
   `approval_stale` (an approval cannot cover data cut off after it — F1-D17). These check
   self-asserted export content against the designation; they do not authenticate it
   (section 11).
6. **Refused runs (poisoning).** A refused run of S whose `run_sequence` is greater than the
   admitting run's `run_sequence` of the effective version — or any refused run of S when the
   scope key has no effective version — adds its mapped reason to every Project mapped from S:
   parser `partial_export` ⇒ `partial_export`, parser `hash_mismatch` ⇒ `hash_mismatch`, every
   other parser or admission code ⇒ `source_refused`. A refused run cannot say which period,
   perspective, currency or basis it covered, so the effect is **cross-scope by design**: a
   refused file meant for `2026-11` blocks `2026-10` answers of S until recovery. **Recovery:**
   the operator imports a good export again; every import appends a new run (F-2 keeps no
   file-hash uniqueness, section 9.1), so re-importing the identical good file, or a
   re-export with the same content, makes a newer admitting run and clears the poison. Older
   refused runs are only counted (`denominator.refused_runs`). When the scope key has no
   version at all, both this step's reasons and the 5.3 step 6 classification reason apply.
7. **Hash parity.** For every admitted run carrying the effective version,
   `source_content_sha256(run.version) != run.content_sha256` ⇒ `hash_mismatch` (tamper or
   corruption after admission; in F-2 a row-to-object readback mismatch).

### 3.8 Project mapping (append-only review versions; never fuzzy)

`ProjectMappingRevision(source_system, external_project_id, revision: int ≥ 1, state:
MappingState, project_id: str | None, match_basis: MatchBasis, reviewed_by: str,
reviewed_at: datetime)`. `project_id` is a native Project id (`prj_` + 8–64
alphanumerics) and is set exactly when `state` ∈ {`proposed`, `accepted`, `quarantined`};
`None` when `rejected`. `match_basis` has the single member `operator_review`: there is no
fuzzy, name, alias, similarity or automatic basis, and constructing one is impossible (closed
enum). Revisions of one key are numbered 1..n without gaps; the **current** revision is the
highest. A mapping change is a new revision, never an edit. Revisions given to the evaluator
with a gap or a duplicate `(source_system, external_project_id, revision)` are an
input-contract violation and raise `ValueError` (never silently resolved; R11-F19).

Per native Project `P` and designated `source_system` S:

| Condition over current revisions of S | Project reason |
| --- | --- |
| exactly 1 key whose current revision is `accepted` with `project_id = P` | mapped (external id = that key) |
| more than 1 such key | `mapping_ambiguous` |
| none accepted, but a current `quarantined` names `P` | `mapping_quarantined` |
| none accepted, but a current `proposed` names `P` | `mapping_unreviewed` |
| otherwise | `mapping_missing` |

A Project mapped (accepted) from **more than 1** designated system covering the request
perspective is double coverage: project reason `double_count_detected`.

### 3.9 Period snapshot

`PeriodSnapshot(source_content_sha256, external_project_id, account_line_count,
change_order_count, transfer_leg_count, slice_sha256)` — the slice of one immutable version
for one external Project (section 6.3). It is derived, never authored; it is the unit F-2
persists per `(version, external project)` for coverage and parity.

### 3.10 Run admission (pure)

`admit_source_run(run_ref, run_sequence, designation, file_sha256, outcome) -> SourceRun`,
where `outcome` is the parser result (section 7.9). A parser refusal becomes a refused run
with that code and line. An admitted parse becomes a refused run with
`source_system_mismatch` when `version.source_system != designation.source_system` (a
spoofed or misfiled export), or `perspective_not_designated` when `version.perspective ∉
designation.perspectives`; otherwise an admitted run with `content_sha256` computed. The
file's `status = approved` is the **source's** assertion; nothing a client sends can make a
version approved (section 11).

---

## 4. Equations

All arithmetic is `money_sum` / exact subtraction under `FINANCE_CONTEXT` (section 3.3).
`E` = the Project's accepted external id in the effective version `V`; "lines of `m`" =
`V.account_lines` with `external_project_id == E` and `measure == m`.

### 4.1 Metric catalogue (closed; order is the canonical output order)

| # | `FinancialMetric` | Perspectives | Kind | Per-Project definition | Program aggregation | Eliminate internal transfers |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `original_budget` | owner_budget | balance | Σ lines of `original_budget` | Σ members | no |
| 2 | `current_budget` | owner_budget | balance | Σ lines of `current_budget` (source-reported approved current budget; already net of approved transfers) | Σ members | no (already net; adding `transfer_net` again is double counting) |
| 3 | `original_contract` | construction_contract | balance | Σ lines of `original_contract` | Σ members | no |
| 4 | `approved_changes` | both | event | Σ `approved` change orders of `E` | Σ members | no |
| 5 | `pending_changes` | both | event | Σ `pending` change orders of `E` | Σ members | no; never part of any approved figure |
| 6 | `revised_contract` | construction_contract | derived | `original_contract + approved_changes` | Σ members | no |
| 7 | `transfer_net` | both | event | Σ amounts of `approved` legs of `E` (credit +, debit −) | Σ members (internal transfers cancel arithmetically; asserted) | no explicit elimination needed |
| 8 | `transfers_in` | both | event | Σ `approved` credit legs of `E` | Σ only legs whose counterparty Project is **outside** the scope | **yes** |
| 9 | `transfers_out` | both | event | Σ `abs` of `approved` debit legs of `E` | Σ only legs whose counterparty Project is **outside** the scope | **yes** |
| 10 | `pending_transfer_net` | both | event | Σ `pending` legs of `E` | Σ members | no; never part of any approved figure |
| 11 | `actual_cost` | both | balance | Σ lines of `actual_cost` | Σ members | no |
| 12 | `forecast_cost_to_complete` | both | balance | Σ lines | Σ members | no |
| 13 | `eac` | both | derived | section 4.3 | Σ members | no |
| 14 | `variance` | both | derived | section 4.4 | Σ members | no |
| 15 | `committed_cost` | both | balance | Σ lines | Σ members | no |
| 16 | `contingency` | both | balance | Σ lines | Σ members | no |
| 17 | `allowance` | both | balance | Σ lines | Σ members | no |

An overview carries exactly the metrics of the request perspective, in this order
(owner_budget: 15 metrics, all but 3 and 6; construction_contract: 15 metrics, all but 1 and
2).

**No zero substitution.** A *balance* metric with no line of its measure for `E` is
`not_reportable` / `measure_not_reported` (absence is not zero). An *event* metric of a
Project present in an effective, complete, approved version is a **verified zero** when no
event exists (the export is complete — `partial_export` and hash checks passed — so absence
of a change order is evidence). A Project not present in `V` at all is `missing_project`.

### 4.2 Revised contract

`revised_contract = original_contract + Σ approved_changes` — preconditions: perspective
`construction_contract`, both terms from the same effective version, `original_contract`
reported. Pending changes never enter it.

### 4.3 EAC (exclusive bases)

Per Project, over the effective version: `S` = the set of measures among
{`actual_cost`, `forecast_cost_to_complete`, `source_eac`} present for `E`.

| `S` contains | `eac` |
| --- | --- |
| `source_eac` and `forecast_cost_to_complete` | `not_reportable` / `eac_basis_conflict` (both bases present: never choose, never add) |
| `source_eac`, not `forecast_cost_to_complete` | Σ lines of `source_eac` (accepted source EAC; `actual_cost` may also be present and is reported on its own) |
| `actual_cost` and `forecast_cost_to_complete`, not `source_eac` | `actual_cost + forecast_cost_to_complete` |
| anything else | `not_reportable` / `eac_incomplete` |

The basis used is disclosed per Project as `eac_basis` ∈ {`computed`, `source`, `null`}.

### 4.4 Variance

`variance = approved_current − eac`, where `approved_current` is `current_budget` for
`owner_budget` and `revised_contract` for `construction_contract` (F1-D10). Preconditions:
both terms reported and from the **same** effective version (hence the same period,
perspective, cost basis and currency). The function takes 1 version and refuses
(`ValueError`) 2 values whose `(period, perspective, cost_basis, currency)` differ; the
evaluator never calls it across versions. If either term is not reportable, `variance`
carries the union of their reasons.

### 4.5 Owner-budget reconciliation (double-count guard at Project grain)

For `owner_budget`, when `original_budget` and `current_budget` are both reported:
`current_budget == original_budget + approved_changes + transfer_net` must hold exactly, else
the Project has project reason `source_reconciliation_failed` (the source is internally
inconsistent, or a movement was counted twice). Pending changes and pending transfers are
excluded on both sides. **This identity is a synthetic-model assumption:** a real budget may
carry other adjustments (e.g. reallocations without a transfer record) and would then fail
every Project; whether the rule holds for a designated source is operator decision F1-O13
(model default: the identity applies).

### 4.6 Scope transfers

A transfer is admissible only as parsed (section 7.7): 1 `transfer_ref`, exactly 2 legs,
`debit` + `credit`, same `cost_code` and `wbs_package` (same scope), same version (hence
same currency and period), same `change_status`, different external Projects, Σ legs = 0.
Only `approved` transfers affect approved figures; `pending` ones appear only in
`pending_transfer_net`.

**Elimination.** In a Program answer, an `approved` transfer whose 2 legs both map to member
Projects is **internal**: it is listed once in `transfer_eliminations` (`transfer_ref`,
`source_project_id` = debit Project, `target_project_id` = credit Project, `cost_code`,
`wbs_package`, `amount` = credit amount, `currency`, `approved = true`,
`source_content_sha256`) and excluded from Program `transfers_in` / `transfers_out`. A
transfer with 1 leg outside the scope is external and is not eliminated. Program
`transfer_net` = Σ member nets, so internal transfers contribute 0; the evaluator asserts
`Σ internal legs == 0` (a violation is a bug, raised, not a reason).

### 4.7 Program consolidation and double counting

- Each member Project is counted once (members are a set of native ids, sorted, unique).
- Approved Project additions reach the Program only through their Project's figures: a change
  order counts once, in the Project that owns it; it is never re-added at Program grain.
- **Double-count detection** (`double_count_detected`):
  1. project reason: a Project with accepted mappings from more than 1 designated system for
     the request perspective (section 3.8);
  2. program reason: a change-order `ref` or a `transfer_ref` appearing in more than 1
     effective version entering the answer, or a `ref` used as both a change-order ref and a
     transfer ref across those versions. The versions **entering the answer** are the
     effective versions (section 3.7) of every designated system for the request scope key
     that supplied a figure to at least 1 member Project. Independent systems that
     legitimately reuse a ref give a fail-closed false positive, and the same change order
     under 2 different refs in 2 systems is not detected (F1-U12).
- Program identity, asserted in tests (not a reason): for `owner_budget`, when every term is
  reported, Σ `current_budget` = Σ `original_budget` + Σ `approved_changes` + Σ
  `transfer_net`.
- `abs(Program or Project value) ≥ 10^16` ⇒ that metric is `not_reportable` /
  `aggregate_out_of_range` (it cannot be represented in `NUMERIC(20,4)`).

---

## 5. Completeness and the `NOT_REPORTABLE` evaluator

### 5.1 `FinancialNotReportableReason` (closed, 29 members; sorted in every output)

| Reason | Level | Meaning |
| --- | --- | --- |
| `source_not_integrated` | program | no designation covers the request perspective |
| `membership_unresolved` | program | the Program member set has unresolved members (S4 resolver input) |
| `membership_truncated` | program | the S4 resolver reached a budget (`MAX_PROGRAM_PROJECTS = 100` or the edge budget), so `project_ids` is a partial set (R11-F06) |
| `mapping_missing` | project | no accepted or pending mapping for the Project |
| `mapping_unreviewed` | project | only a `proposed` mapping |
| `mapping_quarantined` | project | current mapping `quarantined` |
| `mapping_ambiguous` | project | more than 1 accepted external id for the Project |
| `source_version_missing` | project | no version of the designated system for the request at all |
| `missing_project` | project | effective version has no row for the Project's external id |
| `period_mismatch` | project | versions exist only for other periods |
| `perspective_mismatch` | project | versions exist for the period only in another perspective |
| `basis_mismatch` | project | versions exist for period+perspective only in another cost basis |
| `currency_mismatch` | project | versions exist for period+perspective+basis only in another currency |
| `fx_missing` | project | always paired with `currency_mismatch`: no FX authority exists |
| `approval_missing` | project | only `proposed` heads |
| `approval_stale` | project | `approved_at < cutoff_at` |
| `approval_actor_unrecognized` | project | approver not in the designation |
| `withdrawn_source` | project | head is a withdrawal |
| `source_version_ambiguous` | project | more than 1 approved head |
| `source_version_conflict` | project | same ref, 2 contents |
| `hash_mismatch` | project | refused run (`hash_mismatch`) or parity failure |
| `partial_export` | project | refused run (`partial_export`) |
| `source_refused` | project | any other refused run newer than the effective version |
| `source_reconciliation_failed` | project | section 4.5 identity fails |
| `double_count_detected` | project, program | section 4.7 |
| `measure_not_reported` | metric | balance measure absent |
| `eac_basis_conflict` | metric | `eac`, `variance` |
| `eac_incomplete` | metric | `eac`, `variance` |
| `aggregate_out_of_range` | metric | value outside `NUMERIC(20,4)` |

### 5.2 Source state per Project (`FinancialSourceState`)

`effective` when the Project has no project-level reason; otherwise the first of this
precedence that matches its reasons: `not_integrated` (`source_not_integrated`) >
`integrity_gap` (`hash_mismatch`, `partial_export`, `source_refused`,
`source_version_conflict`, `source_version_ambiguous`, `source_reconciliation_failed`,
`double_count_detected`) > `mapping_gap` (`mapping_missing`, `mapping_unreviewed`,
`mapping_quarantined`, `mapping_ambiguous`) > `approval_gap` (`approval_missing`,
`approval_stale`, `approval_actor_unrecognized`) > `source_gap` (`source_version_missing`,
`missing_project`, `period_mismatch`, `perspective_mismatch`, `basis_mismatch`,
`currency_mismatch`, `fx_missing`, `withdrawn_source`).

### 5.3 Algorithm (`evaluate_financial_overview`)

Signature (exact; **no threshold, tolerance or materiality parameter exists**):
`evaluate_financial_overview(request: FinancialScopeRequest, designations:
Sequence[SourceDesignation], runs: Sequence[SourceRun], mappings:
Sequence[ProjectMappingRevision]) -> FinancialOverview`.

`FinancialScopeRequest(project_ids: tuple[str, ...]` (sorted, unique, 1..100 — the S4
`MAX_PROGRAM_PROJECTS` cap; more raises `ValueError`), `unresolved_members: int ≥ 0,
membership_truncated: bool, period, perspective, currency, cost_basis, source_cutoff:
datetime | None)`. `source_cutoff` is an aware UTC instant (F-3 normalizes the 07 RFC3339
input to UTC) or `None` (R11-F07).

1. Input order never matters: designations, runs and mappings are sorted canonically first.
   Designations must be active and unique per system (section 3.4); mapping revisions must be
   gap-free (section 3.8); a violation raises `ValueError`. When `source_cutoff` is set, every
   admitted run whose version has `cutoff_at > source_cutoff` is removed **before** section
   3.7 ("the answer as of that source cutoff"); refused runs are kept (their cutoff is
   unknown, so the fail-closed poisoning of section 3.7 step 6 still applies).
2. If no designation lists `request.perspective`: reportability `source_not_integrated`;
   every Project state `not_integrated` with reason `source_not_integrated`; every value
   `null`, `not_reportable`; stop.
3. Admitted runs are grouped by designated system; version resolution (section 3.7) runs
   per scope key `(system, request.period, request.perspective, request.currency,
   request.cost_basis)`.
4. Per Project, mapping resolution (section 3.8) across designated systems for the
   perspective.
5. If mapped from exactly 1 system: take that system's resolution outcome; apply
   section 3.7 steps 1, 3, 5, 6, 7 reasons.
6. Only when the scope key has **no version at all** (section 3.7 step 3, first row), classify by the nearest existing versions of
   that system, in this order: same period+perspective+basis, other currency ⇒
   `currency_mismatch` + `fx_missing`; same period+perspective, other basis ⇒
   `basis_mismatch`; same period, other perspective ⇒ `perspective_mismatch`; other period
   only ⇒ `period_mismatch`; none ⇒ `source_version_missing`.
7. Effective version without a row (line, change order or leg) for `E` ⇒ `missing_project`.
8. Otherwise compute section 4 figures; then section 4.5; metric reasons per section 4.
9. A Project with any project-level reason has **every** metric `value = null`,
   `value_state = not_reportable`, `reasons` = its project reasons (no partial Project
   figure from a failed source).
10. Program metric: `reported` with the aggregate (section 4.1) when every member's metric is
    `reported` and no program reason applies to it; otherwise `null` / `not_reportable` with
    the sorted union of member metric reasons, member project reasons and program reasons
    (`membership_unresolved` when `unresolved_members > 0`, `membership_truncated` when
    `membership_truncated` is true, `double_count_detected`, `aggregate_out_of_range`).
11. Reportability: `not_reportable` when any project-level or program-level reason exists,
    else `reportable` (metric-level reasons leave it `reportable` and are visible per
    metric). `reportable` certifies **source integrity and coverage only** — it is never a
    certified total (OD-08 still blocks those; F1-U11).

**Materiality (OD-08 default).** Every gap is material. There is no threshold, no tolerance
and no percentage; a looser rule is an operator risk acceptance (F1-O03) and would be a
contract amendment adding a parameter that does not exist today (the scope guard pins the
signature).

### 5.4 Result shape and alignment with S4

| Field | Type | Notes |
| --- | --- | --- |
| `calculation_version` | `"my-pa-finance-calc-v1"` | |
| `request` | the request (period, perspective, currency, cost_basis, project_ids, unresolved_members, membership_truncated, source_cutoff) | |
| `reportability` | `FinancialReportability` | |
| `reasons` | sorted tuple of every program- and project-level reason present | |
| `program_metrics` | tuple of `FinancialMetricValue(metric, value: Decimal \| None, value_state: MetricValueState, reasons)` in catalogue order | `restricted` is never produced in F-1 (F-3 visibility) |
| `projects` | tuple of `ProjectFinancialFigures(project_id, source_state, reasons, source_content_sha256 \| None, external_project_id \| None, eac_basis, metrics)` sorted by `project_id` | per-Project partial figures stay visible when the Program total is not reportable |
| `transfer_eliminations` | tuple, sorted by `transfer_ref` | section 4.6 |
| `source_versions` | sorted `content_sha256` of effective versions used | |
| `pending_source_versions` | sorted `content_sha256` of proposed versions in scope | |
| `source_cutoff_at` | the **earliest** `cutoff_at` among effective versions used, or `null` | every figure is at least as current as this instant |
| `denominator` | `FinancialDenominator(member_projects, unresolved_members, projects_reportable, missing_source_count, refused_runs, projects_by_source_state: {6 states → int})` | integers; `missing_source_count` = members whose state ≠ `effective`; never hidden |

S4 alignment: same `MetricValueState`, same rule that a total is `null` with sorted `reasons`
rather than a substituted number, same denominator discipline. Divergences: a finance-own
reason enum (F1-D05) and decimal string values (F1-D03).

**Verified zero.** A `reported` value of `0.0000` is deliberately not flagged apart from any
other reported value: no zero is ever substituted, so every reported value — zero included —
is evidenced by a complete, approved, effective export (section 4.1). 07's `verified_zero`
`coverage_state` is therefore implied by `value_state = reported`, `value = "0.0000"`.

**07 output mapping (F1-D22).** Each field of 07 `programs.financial.overview` is mapped or
dropped:

| 07 field | This contract |
| --- | --- |
| `program_entity_id` | added by F-3 (F-1 takes `project_ids`) |
| `period`, `perspective`, `currency` | `request` echo; `cost_basis` added (F1-D11) |
| `reportability` | `reportability` (same 3 values) |
| `measures[].metric_id` | `program_metrics[].metric` |
| `measures[].grain` | dropped: Program grain is `program_metrics`, Project grain is `projects[].metrics` |
| `measures[].value` | `value`, decimal string or `null` (F1-D03) |
| `measures[].unit` | dropped: every money value is in the request `currency` |
| `measures[].coverage_state` | `value_state` + `reasons` (F1-D04); `verified_zero` as above |
| `measures[].dedupe_basis` | dropped: dedupe is fixed by section 4.7 (native Project id; change orders and transfers by ref) |
| `measures[].source_run_ids` | dropped in F-1 (no persisted ids); top-level `source_versions` carries content digests; F-3 may add `fsver_` ids |
| `measures[].as_of` | top-level `source_cutoff_at` |
| `measures[].excluded_project_count` | `denominator.missing_source_count` |
| `measures[].nonadditive_across_projects` | dropped: every catalogue metric is additive; gross transfers are handled by elimination (section 4.6) |
| `transfer_eliminations` | as F1-D12 |
| `source_versions` | content digests (F-3 may map to `fsver_` ids) |
| `source_cutoff` (input) | `request.source_cutoff` (step 1) |
| `source_cutoff` (output) | `source_cutoff_at` (earliest effective cutoff) |
| `missing_source_count` | `denominator.missing_source_count` |

---

## 6. Canonical serialisation and SHA-256

### 6.1 Encoder and digest rule

`canonical_json_bytes` is imported from `my_pa.domain.schedule.canonical` (sorted keys,
separators `(",", ":")`, `ensure_ascii=True`, `allow_nan=False`, no trailing newline).
Every digest is `hashlib.sha256(schema.encode("ascii") + b"\n" +
canonical_json_bytes(obj)).hexdigest()` (lowercase hex). Canonical objects contain only
`str`, `int` (counts only), `bool`, `None`, lists and dicts — **no number for money**: every
amount is its `format_amount` string; timestamps are `YYYY-MM-DDTHH:MM:SSZ`; enums are their
values. Key order is the encoder's sort; list order is defined below, never insertion order.

| Schema string | Digest of |
| --- | --- |
| `my-pa-finance-source-v1` | a source version (section 6.2) — `content_sha256` |
| `my-pa-finance-slice-v1` | a period snapshot (section 6.3) — `slice_sha256` |
| `my-pa-finance-overview-v1` | an overview (section 6.4) — `overview_sha256` |

The interchange format version is the separate string `my-pa-synthetic-finance-v1`
(section 7). A change to any object shape below requires a new schema string.

### 6.2 Source version object

```text
{"source_system", "source_version_ref", "period", "cutoff_at", "status",
 "approved_by" (str|null), "approved_at" (str|null), "supersedes_ref" (str|null),
 "perspective", "currency", "cost_basis",
 "account_lines": [{"ref","external_project_id","external_contract_id"(str|null),
                    "cost_code","wbs_package","measure","amount"}]   sorted by ref,
 "change_orders": [{"ref","external_project_id","external_contract_id"(str|null),
                    "cost_code","wbs_package","change_status","amount"}] sorted by ref,
 "transfers": [{"transfer_ref","cost_code","wbs_package","change_status",
                "legs":[{"ref","external_project_id","leg_side","amount"}]  credit then debit
               }] sorted by transfer_ref}
```

**In the hash:** exactly these keys. **Out of the hash:** the raw file bytes and
`file_sha256`, the declared `body_sha256` and `row_count`, physical row order and line
numbers, the per-line `currency` cell (it must equal the version currency), run ref and
sequence, designation, import actor and time, mappings. Consequently 2 files with the same
rows in a different order have different `file_sha256` and equal `content_sha256`.

`source_version_from_object(obj) -> SourceVersion` is the strict inverse: exact key sets,
closed values, amounts through `parse_amount`, every record rebuilt through its constructor;
any deviation (unknown/missing key, JSON number where a string is required, `float`) raises
`FinanceDecodeError` whose message carries nothing of the object. Counts and integers are
checked with `type(x) is int` (a `bool` is refused). Any JSON decoding of these objects (F-2
readback, manifest goldens) uses `json.loads` with `parse_float`, `parse_int` for non-count
positions and `parse_constant` hooks that refuse, because `json.loads` accepts `NaN` and
`Infinity` by default (R11-F14). **Hash parity rule:**
`source_content_sha256(source_version_from_object(source_version_object(v))) ==
source_content_sha256(v)` for every admitted `v`, and F-2's readback of persisted rows must
reproduce the stored `content_sha256` byte for byte.

### 6.3 Slice object

`{"source_content_sha256", "external_project_id", "account_lines": [...], "change_orders":
[...], "transfer_legs": [{"transfer_ref","change_status","cost_code","wbs_package","ref",
"leg_side","amount"}]}` — the same per-record shapes as section 6.2 filtered to one external
Project; `transfer_legs` sorted by `(transfer_ref, leg_side)`.

### 6.4 Overview object

Every section 5.4 field, with values as strings or `null`, reasons as sorted lists,
`projects` sorted by `project_id`, metrics in catalogue order, `denominator` as an object of
integers. `overview_sha256` is deterministic for a given input set in any order (property
test).

---

## 7. Synthetic interchange format `my-pa-synthetic-finance-v1`

### 7.1 Container decision

**CSV, a strict unquoted subset** — 1 file is 1 source version. Chosen over JSON because a
line-oriented record stream bounds by bytes and rows without a nesting depth, the standard
library splits it without a third-party parser, money cannot arrive as a JSON number (every
cell is text), and the formula-injection hazard of a spreadsheet-opened export is real and
explicit. JSON is not supported; 1 container is enough.

### 7.2 Byte-level grammar

- Encoding: ASCII only (every byte `0x20`–`0x7E` or `0x0A`). No byte-order mark (refused, not
  stripped). No Unicode normalisation is needed because non-ASCII is refused (F1-U03).
- Line terminator: LF only; the file ends with exactly 1 LF after the last line. CR anywhere
  is refused; TAB and every other control byte are refused file-wide.
- No quoting: the byte `"` is refused anywhere, so a cell can never contain `,` or LF.
- Cells are split on `,`; every record line has exactly 24 cells.

### 7.3 Lines

| Line | Content |
| --- | --- |
| 1 | exactly `my-pa-synthetic-finance-v1` |
| 2 | the frozen header (section 7.4), byte-exact |
| 3 | the single `source_version` record |
| 4 … n−1 | `account_line`, `change_order`, `transfer_leg` records, any order |
| n | the single `end` record |

**Body** = the bytes from the first byte of line 4 through the final LF inclusive (the
`end` line is in the body). `body_sha256` on line 3 is the lowercase hex SHA-256 of the body.
`row_count` on line 3 and on the `end` line both equal the number of lines strictly between
line 3 and line n.

### 7.4 Header (24 columns, in this order)

`record_type,ref,source_system,source_version_ref,period,cutoff_at,status,approved_by,approved_at,supersedes_ref,perspective,currency,cost_basis,external_project_id,external_contract_id,cost_code,wbs_package,measure,amount,change_status,transfer_ref,leg_side,row_count,body_sha256`

Column requirements per `record_type` (R required, O optional, — must be empty):

| Column | `source_version` | `account_line` | `change_order` | `transfer_leg` | `end` |
| --- | --- | --- | --- | --- | --- |
| `ref` | — | R | R | R | — |
| `source_system` | R | — | — | — | — |
| `source_version_ref` | R | — | — | — | — |
| `period` | R | — | — | — | — |
| `cutoff_at` | R | — | — | — | — |
| `status` | R | — | — | — | — |
| `approved_by` | R if `approved`/`withdrawn`, — if `proposed` | — | — | — | — |
| `approved_at` | as `approved_by` | — | — | — | — |
| `supersedes_ref` | O (R if `withdrawn`) | — | — | — | — |
| `perspective` | R | — | — | — | — |
| `currency` | R | R | R | R | — |
| `cost_basis` | R | — | — | — | — |
| `external_project_id` | — | R | R | R | — |
| `external_contract_id` | — | O | O | — | — |
| `cost_code` | — | R | R | R | — |
| `wbs_package` | — | R | R | R | — |
| `measure` | — | R | — | — | — |
| `amount` | — | R | R | R | — |
| `change_status` | — | — | R | R | — |
| `transfer_ref` | — | — | — | R | — |
| `leg_side` | — | — | — | R | — |
| `row_count` | R | — | — | — | R |
| `body_sha256` | R | — | — | — | — |

`record_type` is always required.

### 7.5 Cell grammars

| Cell kind | Grammar | Refusal |
| --- | --- | --- |
| identifier (`ref`, `source_system`, `source_version_ref`, `approved_by`, `supersedes_ref`, `external_project_id`, `external_contract_id`, `cost_code`, `wbs_package`, `transfer_ref`) | `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$` | `identifier_grammar` |
| enum (`record_type`, `status`, `perspective`, `cost_basis`, `measure`, `change_status`, `leg_side`) | exact member value | `record_type_unknown` for `record_type`, else `enum_value` |
| `amount` | broad `^-?[0-9]+(\.[0-9]+)?$` else `amount_grammar`; no leading zeros (`^-?(0\|[1-9][0-9]*)(\.[0-9]+)?$`) else `amount_grammar`; value 0 with a `-` ⇒ `amount_negative_zero`; more than 4 fraction digits ⇒ `amount_scale`; more than 16 integer digits ⇒ `amount_range` | (checked in that order) |
| `period` | `^[0-9]{4}-(0[1-9]\|1[0-2])$` | `period_grammar` |
| `cutoff_at`, `approved_at` | `^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$` and a valid UTC instant | `timestamp_grammar` |
| `currency` | `^[A-Z]{3}$` else `currency_grammar`; not in `CURRENCY_MINOR_UNITS` ⇒ `currency_unknown` | |
| `row_count` | `^(0\|[1-9][0-9]{0,5})$` | `count_grammar` |
| `body_sha256` | `^[0-9a-f]{64}$` | `digest_grammar` |

So: no exponent (`1e3`), no thousands separator (`1,000` splits the cell and fails
`field_count`), no locale decimal comma, no leading `+`, no `.5`, no `5.`, no spaces.

**Formula injection.** Before its grammar, every non-empty cell **except `amount`** is
refused with `formula_injection` if its first character is `=`, `+`, `-` or `@` (TAB and CR
are already refused file-wide, section 7.2). The `amount` cell is never a text cell: it is
validated only by the amount grammar, so `-150000.0000` there is a legitimate negative
amount, while `=1+1`, `+5`, `@SUM(A1)` in `amount` fail `amount_grammar`. A leading `-` in any
other column is `formula_injection`.

### 7.6 Bounds — `PRODUCTION_LIMITS`

`FinanceParseLimits(max_bytes, max_records, max_line_bytes, max_cell_chars)`; production
values: `max_bytes = 4194304` (4 MiB), `max_records = 20000` (lines after the header,
`source_version` and `end` included), `max_line_bytes = 1024` (excluding LF), `max_cell_chars
= 64`. Tests may inject tighter limits; a green production-limit test is not coverage of a
limit no fixture reaches.

### 7.7 Cross-record rules

- `currency` of every record equals the `source_version` currency ⇒ else
  `line_currency_mismatch`.
- `cutoff_at` ≥ first instant of `period` ⇒ else `cutoff_before_period`.
- `withdrawn` ⇒ `row_count` 0 ⇒ else `withdrawal_has_rows`; `supersedes_ref ==
  source_version_ref` ⇒ `supersedes_self`.
- `account_line` measure valid for the perspective ⇒ `measure_perspective_mismatch`; its sign
  per section 3.2 ⇒ `amount_sign` (account lines only); a change order amount of zero ⇒
  `change_order_zero`. Transfer-leg signs are checked only below (`transfer_leg_sign`).
- `ref` values unique across all records, and no `transfer_ref` equals any `ref` ⇒
  `duplicate_ref`.
- account-line identity (section 3.6) unique ⇒ `duplicate_identity`.
- grouping legs by `transfer_ref`: exactly 2 ⇒ `transfer_leg_count`; 1 `debit` + 1 `credit`
  ⇒ `transfer_leg_sides`; debit < 0 and credit > 0 ⇒ `transfer_leg_sign`; equal `cost_code`
  and `wbs_package` ⇒ `transfer_scope_mismatch`; different `external_project_id` ⇒
  `transfer_same_project`; equal `change_status` ⇒ `transfer_status_mismatch`; Σ = 0 ⇒
  `transfer_unbalanced`.

### 7.8 Refusal taxonomy (`FinanceParseRefusalCode`, 50 members, closed)

`empty_input`, `too_large`, `bom_present`, `non_ascii`, `carriage_return`,
`control_character`, `quote_character`, `partial_export`, `too_many_rows`, `line_too_long`,
`format_unrecognized`, `duplicate_column`, `header_mismatch`, `field_count`,
`cell_too_long`, `source_version_not_first`, `source_version_duplicate`,
`record_type_unknown`, `cell_missing`, `cell_not_empty`, `formula_injection`,
`identifier_grammar`, `amount_grammar`, `amount_scale`, `amount_range`,
`amount_negative_zero`, `amount_sign`, `period_grammar`, `timestamp_grammar`, `enum_value`,
`currency_grammar`, `currency_unknown`, `count_grammar`, `digest_grammar`, `hash_mismatch`,
`line_currency_mismatch`, `cutoff_before_period`, `measure_perspective_mismatch`,
`duplicate_ref`, `duplicate_identity`, `transfer_leg_count`, `transfer_leg_sides`,
`transfer_leg_sign`, `transfer_scope_mismatch`, `transfer_same_project`,
`transfer_status_mismatch`, `transfer_unbalanced`, `change_order_zero`,
`withdrawal_has_rows`, `supersedes_self`.

### 7.9 Validation order, outcome and isolation

`parse_synthetic_finance(data: bytes, *, limits: FinanceParseLimits = PRODUCTION_LIMITS) ->
FinanceParseOutcome`, where `FinanceParseOutcome(admitted: SourceVersion | None,
refusal_code: FinanceParseRefusalCode | None, refusal_line: int | None, file_sha256: str)`
holds exactly 1 of `admitted` / `refusal_code`. The first failing step decides; **whole-file
reject, no partial acceptance**, ever.

| Step | Check | Code (line) |
| --- | --- | --- |
| V1 | `type(data) is bytes` | raises `TypeError` (programming error) |
| V2 | `len == 0`; `len > max_bytes` (checked before any decoding or splitting) | `empty_input`, `too_large` (none) |
| V3 | BOM prefix | `bom_present` (1) |
| V4 | any byte ≥ `0x80` | `non_ascii` (its line) |
| V5 | `0x0D`; any other byte < `0x20` except LF, or `0x7F` | `carriage_return`, `control_character` (its line) |
| V6 | `0x22` | `quote_character` (its line) |
| V7 | does not end with LF | `partial_export` (last line) |
| V8 | line count − 2 > `max_records`; any line > `max_line_bytes` | `too_many_rows` (none), `line_too_long` (its line) |
| V9 | line 1 ≠ format name | `format_unrecognized` (1) |
| V10 | header: a repeated column name; header ≠ frozen | `duplicate_column`, `header_mismatch` (2) |
| V11 | every line ≥ 3: 24 cells; each cell ≤ `max_cell_chars` | `field_count`, `cell_too_long` |
| V12 | line 3 `record_type` is `source_version`; parse line 3 fully (requirements, formula, grammars) | `source_version_not_first` (3), line-3 codes |
| V13 | last line is an `end` record, no other `end`, both counts equal the actual count ⇒ else `partial_export` (last line or the early `end`); then the `end` line gets the full V15 treatment (requirements, formula, grammars), so a non-empty other cell is `cell_not_empty`, a formula `formula_injection`, each at line n (an `end` `row_count` outside the count grammar cannot equal the actual count and is `partial_export`) (R11-F13) | `partial_export`, then per-cell codes (n) |
| V14 | SHA-256(body) = `body_sha256` | `hash_mismatch` (3) |
| V15 | lines 4..n−1 in order: `record_type` (a second `source_version` ⇒ `source_version_duplicate`), requirements (`cell_missing`, `cell_not_empty`), formula, grammars | per cell (its line) |
| V16 | section 7.7 cross-record rules, in the listed order | per rule (first offending line; transfer rules: the later leg's line) |

Exception contract: returns an outcome for every `bytes` input; raises only `TypeError` (V1),
`MemoryError`, `KeyboardInterrupt`, `SystemExit`. Any other exception escaping V2–V16 is a
bug and fails the tests (no blanket `except`). A refusal carries the code and line only —
never cell text — and no exception chains input text (`raise … from None`).

**Isolation.** Pure function of its input: no file, network, environment, clock, subprocess,
`logging`, `print`, `eval`, `exec`, `pickle`, `csv` dialect sniffing, XML, entity expansion
or import-time state. Linear in input size. In-process only in F-1; F-2 decides whether the
import path runs it in the worker child (F1-U01).

---

## 8. Synthetic fixtures, manifest and goldens

### 8.1 Layout and pinning

- Files: `tests/fixtures/financial_source/*.csv` and
  `tests/fixtures/financial_source/malformed/*.csv`; manifest
  `tests/fixtures/financial_source/manifest.json` (pretty JSON `indent=2`, `sort_keys=True`,
  `ensure_ascii=True`, trailing LF).
- Writer: `tests/fixtures/financial_source_writer.py`; regeneration is explicit only:
  `PYTHONPATH=src python -m tests.fixtures.financial_source_writer write` (writes every file
  and the manifest, prints each path and digest). It computes each `body_sha256` and
  `row_count`, then applies the 1 named mutation for each refused/malformed case. **No test
  calls the writer.**
- Pins (S5a precedent): `manifest.json` records every file's `file_sha256` and size;
  `tests/unit/test_financial_source_fixtures.py` holds `FIXTURE_FILE_SHA256: Final[dict[str,
  str]]` (every fixture file and the manifest itself), asserts the directory file set equals
  it, and asserts by `ast` that no module under `tests/` other than the writer references
  the writer's `write` entry point. Tests read fixtures with `Path.read_bytes()` only.
- **Byte exactness (R11-F10).** I11-B adds to `.gitattributes` (an I11-B owned path) the line
  `tests/fixtures/financial_source/** -text whitespace=-blank-at-eol,-blank-at-eof,-space-before-tab,-indent-with-non-tab,-tab-in-indent`
  so no checkout, `core.autocrlf` or merge normalises line endings and `git diff --check`
  does not flag the deliberate CR, TAB, missing-final-LF and BOM cases. I11-B confirms with
  `git diff --check` over the fixture paths; if any warning remains, the rule becomes
  `tests/fixtures/financial_source/** binary` and the handoff records it.
- Synthetic rule: every identifier cell starts with `syn-` or `SYN-`; native ids are
  `prj_SYNTHETIC0000000001`, `prj_SYNTHETIC0000000002`, `prj_SYNTHETIC0000000003`
  (called P1, P2, P3 below).

Common values unless a row says otherwise: `source_system = syn-fin-a`, `period = 2026-10`,
`cutoff_at = 2026-10-31T23:59:59Z`, `status = approved`, `approved_by = syn-approver-1`,
`approved_at = 2026-11-05T15:00:00Z`, `perspective = owner_budget`, `currency = USD`,
`cost_basis = gross`, `cost_code = SYN-CC-03300`, `wbs_package = SYN-WBS-CONC`. External
Projects `SYN-P-100`, `SYN-P-200`, `SYN-P-300`.

Designations used by scenarios: `syn-fin-a` (perspectives `owner_budget`,
`construction_contract`; approvers {`syn-approver-1`}); `syn-fin-c` (`owner_budget`;
{`syn-approver-1`}). Default mappings (revision 1, `accepted`, `operator_review`, reviewer
`syn-operator`, `2026-11-01T00:00:00Z`): `syn-fin-a`/`SYN-P-100` → P1, `SYN-P-200` → P2,
`SYN-P-300` → P3.

### 8.2 The base file `syn_at020_owner_budget.csv` (AT-020 shape)

`source_version_ref = SYN-V-2026-10-A`, `row_count = 15`.

| ref | type | project | measure / status / side | amount |
| --- | --- | --- | --- | --- |
| `SYN-L-001` | account_line | SYN-P-100 | `original_budget` | `1000000.0000` |
| `SYN-L-002` | account_line | SYN-P-100 | `current_budget` | `875000.0000` |
| `SYN-L-003` | account_line | SYN-P-100 | `actual_cost` | `400000.0000` |
| `SYN-L-004` | account_line | SYN-P-100 | `forecast_cost_to_complete` | `450000.0000` |
| `SYN-L-005` | account_line | SYN-P-100 | `committed_cost` | `600000.0000` |
| `SYN-L-006` | account_line | SYN-P-100 | `contingency` | `50000.0000` |
| `SYN-L-007` | account_line | SYN-P-200 | `original_budget` | `500000.0000` |
| `SYN-L-008` | account_line | SYN-P-200 | `current_budget` | `650000.0000` |
| `SYN-L-009` | account_line | SYN-P-200 | `actual_cost` | `100000.0000` |
| `SYN-L-010` | account_line | SYN-P-200 | `forecast_cost_to_complete` | `560000.0000` |
| `SYN-L-011` | account_line | SYN-P-200 | `committed_cost` | `300000.0000` |
| `SYN-CO-1` | change_order | SYN-P-100 | `approved` | `25000.0000` |
| `SYN-CO-2` | change_order | SYN-P-100 | `pending` (same WBS package) | `40000.0000` |
| `SYN-TL-1D` | transfer_leg (`SYN-T-1`) | SYN-P-100 | `approved`, `debit` | `-150000.0000` |
| `SYN-TL-1C` | transfer_leg (`SYN-T-1`) | SYN-P-200 | `approved`, `credit` | `150000.0000` |

### 8.3 Files (one row per fixture)

| File | Purpose | Content (delta from the base) | Parser outcome |
| --- | --- | --- | --- |
| `syn_at020_owner_budget.csv` | AT-020: approved 2-leg transfer Σ=0 + separate pending change, same WBS package | section 8.2 | admitted |
| `syn_contract_perspective.csv` | revised contract, source EAC | ref `SYN-V-2026-10-K`, `construction_contract`; SYN-P-100 contract `SYN-K-1`: `original_contract 2000000.0000`, `actual_cost 800000.0000`, `source_eac 1900000.0000`; change orders `SYN-CO-K1` approved `30000.0000`, `SYN-CO-K2` approved `12500.5000`, `SYN-CO-K3` pending `7000.0000`; `row_count 6` | admitted |
| `syn_p200_eur.csv` | currency mismatch / missing FX | ref `SYN-V-2026-10-E`, `EUR`; SYN-P-200: `original_budget 400000.0000`, `current_budget 400000.0000`, `actual_cost 50000.0000`, `forecast_cost_to_complete 350000.0000`; `row_count 4` | admitted |
| `syn_stale_approval.csv` | stale approval | base rows; ref `SYN-V-2026-10-S`, `approved_at 2026-10-30T12:00:00Z` | admitted |
| `syn_proposed.csv` | approval missing; pending version | base rows; ref `SYN-V-2026-10-P`, `proposed`, approval cells empty, `supersedes_ref SYN-V-2026-10-A` | admitted |
| `syn_withdrawal.csv` | withdrawn source | ref `SYN-V-2026-10-W`, `withdrawn`, `supersedes_ref SYN-V-2026-10-A`, `approved_at 2026-11-07T09:00:00Z`, `row_count 0` | admitted |
| `syn_version_conflict.csv` | spoofed/edited re-export under an existing ref | base with ref `SYN-V-2026-10-A` and `SYN-L-003` = `400001.0000` (valid body hash) | admitted |
| `syn_spoofed_system.csv` | spoofed source system | base rows; `source_system syn-fin-b`, ref `SYN-V-2026-10-X` | admitted by the parser; refused at admission `source_system_mismatch` under `syn-fin-a` |
| `syn_unknown_actor.csv` | unrecognized approver | base rows; ref `SYN-V-2026-10-U`, `approved_by syn-approver-9` | admitted |
| `syn_eac_conflict.csv` | EAC bases | ref `SYN-V-2026-10-Q`; SYN-P-100: `original_budget 1000000.0000`, `current_budget 1000000.0000`, `actual_cost 400000.0000`, `forecast_cost_to_complete 450000.0000`, `source_eac 860000.0000`; SYN-P-200: `original_budget 500000.0000`, `current_budget 500000.0000`, `actual_cost 100000.0000`; `row_count 8` | admitted |
| `syn_reconciliation_failure.csv` | double count / inconsistent source | base rows; ref `SYN-V-2026-10-R`, `SYN-L-002` = `900000.0000` | admitted |
| `syn_second_system.csv` | double coverage, repeated change order | `source_system syn-fin-c`, ref `SYN-V-2026-10-C`; SYN-P-100: `original_budget 1000000.0000`, `current_budget 1025000.0000`, change order `SYN-CO-1` approved `25000.0000`; `row_count 3` | admitted |
| `syn_rounding_edges.csv` | half-way, max scale, max magnitude, overflow | ref `SYN-V-2026-10-Z`; SYN-P-300: `original_budget` `0.0050` × 3 (cost codes `SYN-CC-01001`, `SYN-CC-01002`, `SYN-CC-01003`), `current_budget` `0.0050` × 3 (same cost codes), `contingency` `9999999999999999.9999` (`SYN-CC-01001`) and `0.0001` (`SYN-CC-01002`); `row_count 8` | admitted |
| `syn_spoofed_system_b.csv` | 2nd spoof with different bytes (recovery golden) | as `syn_spoofed_system.csv` with ref `SYN-V-2026-10-Y` | admitted by the parser; refused at admission `source_system_mismatch` |
| `syn_cycle_a.csv` | supersession cycle | base rows; ref `SYN-V-2026-10-C1`, `supersedes_ref SYN-V-2026-10-C2` | admitted |
| `syn_cycle_b.csv` | supersession cycle | base rows; ref `SYN-V-2026-10-C2`, `supersedes_ref SYN-V-2026-10-C1` | admitted |
| `syn_withdrawal_dangling.csv` | withdrawal naming no version | as `syn_withdrawal.csv` with ref `SYN-V-2026-10-W2`, `supersedes_ref SYN-V-2026-10-NONE` | admitted |
| `syn_partial_export.csv` | truncated export | base with the `end` line removed (file still ends with LF) | refused `partial_export`, line 18 |
| `syn_tampered_body.csv` | body changed after its declared hash was written (accidental corruption; a deliberate forger recomputes the hash — section 11) | base, then `SYN-L-003` = `400000.0001` after `body_sha256` was computed | refused `hash_mismatch`, line 3 |
| `syn_duplicate_identity.csv` | duplicate identity | base plus `SYN-L-099` with the identity of `SYN-L-001` (amount `1.0000`), counts and hash updated | refused `duplicate_identity`, line of `SYN-L-099` |

### 8.4 Malformed parser cases (`malformed/<code>__<variant>.csv`)

Each is the base file with exactly 1 mutation, `body_sha256` and `row_count` recomputed after
the mutation unless the mutation targets them. Expected: refused with the code in the name
at the manifest's recorded line. The set is exactly these 52 files (so the fixture tree holds
20 named files, 52 malformed files and the manifest: 73 files):

| File | Mutation |
| --- | --- |
| `empty_input__base.csv` | zero bytes |
| `bom_present__base.csv` | BOM prefixed |
| `non_ascii__cell.csv` | `SYN-WBS-CONC` → `SYN-WBS-CÖNC` (UTF-8) on line 4 |
| `carriage_return__crlf.csv` | every LF → CRLF |
| `control_character__tab.csv` | a TAB before `SYN-L-001` |
| `quote_character__quoted.csv` | `"SYN-L-001"` |
| `partial_export__no_final_lf.csv` | final LF removed |
| `partial_export__count.csv` | `row_count` on line 3 = 14 (hash recomputed) |
| `format_unrecognized__base.csv` | line 1 `my-pa-synthetic-finance-v2` |
| `duplicate_column__base.csv` | header column 2 renamed `record_type` |
| `header_mismatch__order.csv` | header columns 2 and 3 swapped |
| `field_count__thousands.csv` | `SYN-L-001` amount `1,000,000.0000` |
| `cell_too_long__base.csv` | `SYN-L-001` `wbs_package` = `SYN-` + 61 `A` (65 chars) |
| `source_version_not_first__base.csv` | lines 3 and 4 swapped |
| `source_version_duplicate__base.csv` | a copy of line 3 inserted as line 4 |
| `record_type_unknown__base.csv` | `account_line` → `account_lines` on line 4 |
| `cell_missing__cost_code.csv` | `SYN-L-001` `cost_code` empty |
| `cell_not_empty__measure.csv` | `SYN-CO-1` `measure` = `actual_cost` |
| `formula_injection__equals.csv` | `SYN-L-001` `cost_code` = `=SYN-CC-1` |
| `formula_injection__plus.csv` | `cost_code` = `+SYN-CC-1` |
| `formula_injection__minus.csv` | `cost_code` = `-SYN-CC-1` |
| `formula_injection__at.csv` | `cost_code` = `@SYN-CC-1` |
| `identifier_grammar__space.csv` | `cost_code` = `SYN CC` |
| `amount_grammar__exponent.csv` | amount `1e6` |
| `amount_grammar__plus.csv` | amount `+1000000.0000` |
| `amount_grammar__leading_zero.csv` | amount `01000000.0000` |
| `amount_grammar__formula.csv` | amount `=1000000` |
| `amount_negative_zero__base.csv` | `SYN-CO-1` amount `-0.0000` |
| `amount_scale__base.csv` | amount `1000000.00001` |
| `amount_range__base.csv` | amount `10000000000000000.0000` |
| `amount_sign__base.csv` | `SYN-L-003` amount `-400000.0000` |
| `period_grammar__base.csv` | `period` `2026-13` |
| `timestamp_grammar__offset.csv` | `cutoff_at` `2026-10-31T23:59:59+00:00` |
| `enum_value__perspective.csv` | `perspective` `owner-budget` |
| `currency_grammar__lowercase.csv` | `currency` `usd` on line 3 |
| `currency_unknown__base.csv` | `currency` `XTS` on line 3 and every record |
| `count_grammar__base.csv` | `row_count` `015` |
| `digest_grammar__base.csv` | `body_sha256` uppercased |
| `line_currency_mismatch__base.csv` | `SYN-L-001` `currency` `EUR` |
| `cutoff_before_period__base.csv` | `cutoff_at` `2026-09-30T23:59:59Z` |
| `measure_perspective_mismatch__base.csv` | `SYN-L-001` measure `original_contract` |
| `duplicate_ref__base.csv` | `SYN-L-002` ref → `SYN-L-001` |
| `transfer_leg_count__base.csv` | `SYN-TL-1C` removed |
| `transfer_leg_sides__base.csv` | `SYN-TL-1C` side `debit` |
| `transfer_leg_sign__base.csv` | `SYN-TL-1D` amount `150000.0000`, `SYN-TL-1C` `-150000.0000` |
| `transfer_scope_mismatch__base.csv` | `SYN-TL-1C` `wbs_package` `SYN-WBS-STEEL` |
| `transfer_same_project__base.csv` | `SYN-TL-1C` project `SYN-P-100` |
| `transfer_status_mismatch__base.csv` | `SYN-TL-1C` `pending` |
| `transfer_unbalanced__base.csv` | `SYN-TL-1C` `149999.9999` |
| `change_order_zero__base.csv` | `SYN-CO-2` amount `0.0000` |
| `withdrawal_has_rows__base.csv` | line 3 `withdrawn`, `supersedes_ref SYN-V-2026-10-0` |
| `supersedes_self__base.csv` | `supersedes_ref SYN-V-2026-10-A` |

Generated in-test, not committed: `too_large` (`max_bytes + 1` bytes of a valid prefix),
`too_many_rows` and `line_too_long` under injected limits, the seeded body mutations of
section 12.2.

### 8.5 Golden scenarios (manifest `scenarios`; request `2026-10`, `owner_budget`, `USD`, `gross` unless stated)

The bracketed list after the reportability is the **complete sorted** overview `reasons`
(every program- and project-level reason present); a Project named before a list scopes it to
that Project, and the other members are `effective`. Metric-level reasons are listed per
metric. Run sequence numbers are the listed order (1, 2, …).

| # | Runs (sequence order) | Members | Expected reportability; reasons |
| --- | --- | --- | --- |
| S01 | at020 | P1, P2 | `reportable`; figures section 8.6 |
| S02 | contract | P1 (request `construction_contract`) | `reportable`; section 8.6 |
| S03 | p200_eur | P2 | `not_reportable`; P2 `source_gap` [`currency_mismatch`, `fx_missing`], all values `null` |
| S04 | p200_eur | P2 (request `EUR`) | `reportable`; P2 `original_budget 400000.0000`, `current_budget 400000.0000`, `eac 400000.0000`, `variance 0.0000` (a verified zero) |
| S05 | stale | P1, P2 | `not_reportable`; [`approval_stale`] |
| S06 | proposed | P1, P2 | `not_reportable`; [`approval_missing`]; `pending_source_versions` = [proposed hash] |
| S07 | at020, proposed | P1, P2 | `reportable` (S01 figures); `pending_source_versions` = [proposed hash] |
| S08 | at020, withdrawal | P1, P2 | `not_reportable`; [`withdrawn_source`] |
| S09 | at020, version_conflict | P1, P2 | `not_reportable`; [`source_version_conflict`] (terminal: no `source_version_ambiguous` although 2 approved heads exist) |
| S10 | at020, spoofed (refused at admission) | P1, P2 | `not_reportable`; [`source_refused`]; `denominator.refused_runs = 1` |
| S11 | spoofed, at020 | P1, P2 | `reportable` (refused run older than the effective version); `refused_runs = 1` |
| S12 | unknown_actor | P1, P2 | `not_reportable`; [`approval_actor_unrecognized`] |
| S13 | eac_conflict | P1, P2 | `reportable`; P1 `eac`/`variance` [`eac_basis_conflict`]; P2 `eac`/`variance` [`eac_incomplete`]; Program `eac`/`variance` both reasons |
| S14 | reconciliation_failure | P1, P2 | `not_reportable`; P1 [`source_reconciliation_failed`] all `null`; P2 reported with S01 P2 figures |
| S15 | at020 (`syn-fin-a`), second_system (`syn-fin-c`, mapping `syn-fin-c`/`SYN-P-100` → P1) | P1, P2 | `not_reportable`; P1 [`double_count_detected`]; program [`double_count_detected`] |
| S16 | partial_export | P1, P2 | `not_reportable`; [`partial_export`, `source_version_missing`] |
| S17 | tampered_body | P1, P2 | `not_reportable`; [`hash_mismatch`, `source_version_missing`] |
| S18 | duplicate_identity | P1, P2 | `not_reportable`; [`source_refused`, `source_version_missing`] |
| S19 | at020, no designation | P1, P2 | `source_not_integrated`; every value `null`; denominator `member_projects 2` |
| S20 | at020 | P1, P2 (period `2026-09`) | `not_reportable`; [`period_mismatch`] |
| S21 | at020 | P1, P2 (`construction_contract`) | `not_reportable`; [`perspective_mismatch`] |
| S22 | at020 | P1, P2 (`net`) | `not_reportable`; [`basis_mismatch`] |
| S23 | at020; `SYN-P-200` revision 1 `proposed` | P1, P2 | `not_reportable`; P2 [`mapping_unreviewed`]; P1 reported |
| S24 | at020; `SYN-P-200` revision 2 `quarantined` | P1, P2 | P2 [`mapping_quarantined`] |
| S25 | at020; extra accepted `syn-fin-a`/`SYN-P-201` → P2 | P1, P2 | P2 [`mapping_ambiguous`] |
| S26 | at020; no mapping for P2 | P1, P2 | P2 [`mapping_missing`] |
| S27 | at020 | P1, P2, P3 | `not_reportable`; P3 [`missing_project`]; P1, P2 reported |
| S28 | at020 | P1, P2, `unresolved_members 1` | `not_reportable`; program [`membership_unresolved`]; per-Project figures reported |
| S29 | rounding_edges | P3 | `reportable`; `original_budget 0.0150`, `current_budget 0.0150`; `contingency` [`aggregate_out_of_range`]; `presentation_amount("0.0150", "USD") == "0.02"` while each line presents `"0.00"` |
| S30 | (none) | P1 | `not_reportable`; [`source_version_missing`] |
| S31 | spoofed, at020, spoofed_b, at020 (identical re-import) | P1, P2 | `reportable` (S01 figures): the admitting run of the at020 version is sequence 4 > 3; `refused_runs = 2` (recovery) |
| S32 | spoofed, at020, spoofed_b | P1, P2 | `not_reportable`; [`source_refused`]; `refused_runs = 2` |
| S33 | at020 | P1, P2 (period `2026-09`), plus a later refused partial_export | `not_reportable`; [`partial_export`, `period_mismatch`] — the refused run poisons across periods |
| S34 | cycle_a, cycle_b | P1, P2 | `not_reportable`; [`source_version_ambiguous`] |
| S35 | at020, withdrawal_dangling | P1, P2 | `not_reportable`; [`source_version_ambiguous`] (1 approved and 1 withdrawn head) |
| S36 | at020 | P1, P2, `membership_truncated` true | `not_reportable`; [`membership_truncated`]; per-Project figures reported |
| S37 | at020 | P1, P2, `source_cutoff 2026-10-30T00:00:00Z` | `not_reportable`; [`source_version_missing`] (the only version is cut off after the requested source cutoff) |

### 8.6 Golden values (exact decimal strings)

**S01 (AT-020).**

| Metric | P1 | P2 | Program |
| --- | --- | --- | --- |
| `original_budget` | `1000000.0000` | `500000.0000` | `1500000.0000` |
| `current_budget` | `875000.0000` | `650000.0000` | `1525000.0000` |
| `approved_changes` | `25000.0000` | `0.0000` | `25000.0000` |
| `pending_changes` | `40000.0000` | `0.0000` | `40000.0000` |
| `transfer_net` | `-150000.0000` | `150000.0000` | `0.0000` |
| `transfers_in` | `0.0000` | `150000.0000` | `0.0000` (eliminated) |
| `transfers_out` | `150000.0000` | `0.0000` | `0.0000` (eliminated) |
| `pending_transfer_net` | `0.0000` | `0.0000` | `0.0000` |
| `actual_cost` | `400000.0000` | `100000.0000` | `500000.0000` |
| `forecast_cost_to_complete` | `450000.0000` | `560000.0000` | `1010000.0000` |
| `eac` (`computed`) | `850000.0000` | `660000.0000` | `1510000.0000` |
| `variance` | `25000.0000` | `-10000.0000` | `15000.0000` |
| `committed_cost` | `600000.0000` | `300000.0000` | `900000.0000` |
| `contingency` | `50000.0000` | `null` [`measure_not_reported`] | `null` [`measure_not_reported`] |
| `allowance` | `null` [`measure_not_reported`] | `null` [`measure_not_reported`] | `null` [`measure_not_reported`] |

`transfer_eliminations` = [`SYN-T-1`, P1 → P2, `SYN-CC-03300`, `SYN-WBS-CONC`,
`150000.0000`, `USD`, approved]. Reconciliation: P1 `1000000.0000 + 25000.0000 −
150000.0000 = 875000.0000`; P2 `500000.0000 + 0.0000 + 150000.0000 = 650000.0000`; Program
identity `1500000.0000 + 25000.0000 + 0.0000 = 1525000.0000`. A wrong consolidation that
adds `transfers_in` to `current_budget` would give `1675000.0000` (negative test).
`denominator` = `{member_projects 2, unresolved_members 0, projects_reportable 2,
missing_source_count 0, refused_runs 0, projects_by_source_state {effective 2, others 0}}`.

**S02.** P1: `original_contract 2000000.0000`, `approved_changes 42500.5000`,
`pending_changes 7000.0000`, `revised_contract 2042500.5000`, `actual_cost 800000.0000`,
`eac 1900000.0000` (`source`), `variance 142500.5000`, `transfer_net`, `transfers_in`,
`transfers_out`, `pending_transfer_net` all `0.0000`, `forecast_cost_to_complete`,
`committed_cost`, `contingency`, `allowance` `null` [`measure_not_reported`].

**Presentation vectors (`presentation_amount`, ROUND_HALF_EVEN).**

| Amount | Currency | Result |
| --- | --- | --- |
| `0.0050` | USD | `0.00` |
| `0.0150` | USD | `0.02` |
| `0.0250` | USD | `0.02` |
| `-0.0250` | USD | `-0.02` |
| `-0.0050` | USD | `0.00` (no negative zero) |
| `0.0251` | USD | `0.03` |
| `1234.5650` | EUR | `1234.56` |
| `1234.5750` | EUR | `1234.58` |
| `2.5000` | JPY | `2` |
| `3.5000` | JPY | `4` |
| `-2.5000` | JPY | `-2` |
| `9999999999999999.9999` | USD | `10000000000000000.00` |

**Amount vectors (`parse_amount` → `format_amount`).** `0` → `0.0000`; `1.5` → `1.5000`;
`-0.0001` → `-0.0001`; `9999999999999999.9999` accepted; `-9999999999999999.9999` accepted;
`10000000000000000` → `amount_range`; `0.00001` → `amount_scale`; `-0` → `amount_negative_zero`;
`1E3`, `1,000`, `1 000`, `+1`, `.5`, `5.`, `00.1`, `NaN`, `Infinity` → `amount_grammar`.

Every digest value (file, body, content, slice, overview) is recorded by the I11-B
implementer at freeze in the manifest and in `FIXTURE_FILE_SHA256`; this contract fixes the
inputs and the decimal expectations, not hex strings it cannot compute (F1-U06).

---

## 9. F-2 plan (contract level; not authorized by F-1)

### 9.1 Tables (schema `knowledge`; F1-D07, F1-D08)

Common to every table: `principal_id NOT NULL` with FK to the principal table and every
cross-table FK composite `(x_id, principal_id)`; append-only (`BEFORE UPDATE OR DELETE`
trigger raising), `BEFORE TRUNCATE` refusal trigger, no `ON DELETE CASCADE`; amounts
`NUMERIC(20,4)` with `CHECK (amount > -10000000000000000 AND amount < 10000000000000000)`;
closed-value `CHECK`s for every section 3.2 vocabulary; timestamps `timestamptz`.

| Table | Key columns | Uniqueness / checks |
| --- | --- | --- |
| `financial_source_designations` (`fdes_`) | `designation_id`, `source_system`, `perspectives text[]`, `approvers text[]`, `decision_reference`, `designated_by`, `designated_at`, `revokes_designation_id` | operator-only writes; revocation is a new row |
| `financial_source_runs` (`fsrun_`) | `run_id`, `designation_id`, `run_sequence`, `file_sha256`, `file_size`, `format_version`, `outcome`, `refusal_code`, `refusal_line`, `version_id` (nullable; composite FK to the version), `imported_by`, `imported_at` | unique `(principal_id, designation_id, run_sequence)`; **no** uniqueness on `file_sha256` (every import appends a run, so re-importing an identical good file clears poisoning — section 3.7 step 6); `outcome = 'admitted'` ⇔ `version_id IS NOT NULL` ⇔ `refusal_code IS NULL` CHECK; many runs → 1 version |
| `financial_source_versions` (`fsver_`) | `version_id`, section 3.5 header fields, `body_sha256` of the first admitting run, `content_sha256` | unique `(principal_id, source_system, source_version_ref, content_sha256)`: an identical content from a later run reuses the row (idempotency lives at the version, not the file); a second content under the same ref is a new row and surfaces as `source_version_conflict`; approval-field CHECKs of section 3.5 |
| `financial_project_mappings` (`fmap_`) | `mapping_id`, `source_system`, `external_project_id`, `revision`, `state`, `project_id`, `match_basis`, `reviewed_by`, `reviewed_at`, `reason` | unique `(principal_id, source_system, external_project_id, revision)`; `match_basis = 'operator_review'` CHECK; composite FK `(project_id, principal_id)` → `knowledge.projects (project_id, principal_id)`; revision gap-free trigger |
| `financial_period_snapshots` (`fpsn_`) | `snapshot_id`, `version_id`, `external_project_id`, 3 counts, `slice_sha256` | unique `(principal_id, version_id, external_project_id)` |
| `financial_account_lines` (`fline_`) | `line_id`, `version_id`, `ref`, external ids, `cost_code`, `wbs_package`, `measure`, `amount` | unique `(version_id, ref)`; unique `(version_id, external_project_id, coalesce(external_contract_id, ''), cost_code, wbs_package, measure)`; sign CHECK per measure |
| `financial_change_orders` (`fchg_`) | `change_order_id`, `version_id`, `ref`, external ids, scope, `change_status`, `amount` | unique `(version_id, ref)`; `amount <> 0` |
| `financial_scope_transfers` (`fxfr_`) | `transfer_id`, `version_id`, `transfer_ref`, `cost_code`, `wbs_package`, `change_status` | unique `(version_id, transfer_ref)` |
| `financial_transfer_legs` (`fleg_`) | `leg_id`, `transfer_id`, `ref`, `external_project_id`, `leg_side`, `amount` | unique `(transfer_id, leg_side)`; sign CHECK by side; `DEFERRABLE INITIALLY DEFERRED` constraint trigger: each transfer has exactly 2 legs, different projects, Σ = 0 at commit |

**Schema and access obligations (F-2/F-3; R11-F02).** Every F-2 DDL and query names the
tables schema-qualified as `knowledge.financial_*`; nothing is created in, granted through or
read from schema `financial` or `procore`, and no F-2/F-3 module reads `financial.*` or
`procore.*`. F-2 extends the scope guard with these checks.

**Database privileges (R11-F16).** No `GRANT`/`REVOKE` and no MCP object grant in the F-2
revision (the S5b-1/S6-2 precedent: tables owned by the migrating role). In the creator-bound
grant mechanism of `src/my_pa/infrastructure/database/mcp_object_grants.py` all 9 tables are
classified `excluded` (never `application_read`/`application_write`), and F-2 adds all 9
`("knowledge", "financial_*")` pairs to `_PROTECTED`, so no later MCP database profile can
expose them. Rows are written only by the import transaction of the application; they are read
only through the F-3 read path.

Only the import transaction writes rows; a version's lines, orders, transfers, legs and
snapshots are inserted in the same transaction as the first run that admits it, and the readback
`source_content_sha256(rows → SourceVersion)` must equal `content_sha256` before commit
(hash parity), else the transaction aborts.

### 9.2 Identifier kinds planned (F-2 adds; F-1 adds none)

`FINANCIAL_SOURCE_DESIGNATION = "fdes"`, `FINANCIAL_SOURCE_RUN = "fsrun"`,
`FINANCIAL_SOURCE_VERSION = "fsver"`, `FINANCIAL_PROJECT_MAPPING = "fmap"`,
`FINANCIAL_PERIOD_SNAPSHOT = "fpsn"`, `FINANCIAL_ACCOUNT_LINE = "fline"`,
`FINANCIAL_CHANGE_ORDER = "fchg"`, `FINANCIAL_SCOPE_TRANSFER = "fxfr"`,
`FINANCIAL_TRANSFER_LEG = "fleg"` (all unused at the basis; F-2 re-verifies collisions).

### 9.3 Switch

`MY_PA_FINANCIAL_SOURCE_ENABLED` (F-2 adds the Settings field), **default off**; when off no
import, mapping-review or finance read is composed. Enabling it in any environment is an
operator gate and does not designate a source.

### 9.4 Import, review, quarantine, recovery

- **Import** is operator-only and attested-local (S5b-2 / ADR-016 precedent): input is the
  file bytes plus a `designation_id`; the application calls `parse_synthetic_finance` (or a
  future designated adapter producing the same `SourceVersion`), `admit_source_run`, then
  persists. Every import appends a run; an identical content reuses its version row
  (idempotency at the version). The surface is an **operator-only, attested-local
  capability** (e.g. `financial_sources.import`), whose operator CLI and HTTP gateway entry
  points are the same capability (R11 ruling Q1); it is **never** ChatLLM, remote MCP,
  façade or web. F1-O09 stays open only for the operator to choose a CLI-only surface. No
  client, ChatLLM or remote caller can import, approve, designate or map.
- **Mapping review** (operator-only) appends a revision; there is no automatic proposal from
  names in F-2.
- **Quarantine** of a wrong mapping: append a `quarantined` revision; every overview using it
  turns `mapping_quarantined`; nothing is deleted or rewritten.
- **Recovery:** switch off (halts import and reads); immutable rows are retained; a wrong
  version is superseded or withdrawn by a new source version, never edited; a poisoning
  refused run is cleared by re-importing a good export (section 3.7 step 6); **no write to
  any source system ever**.
- **AT-020 DB half:** `tests/integration/test_financial_scope_transfer.py` (database +
  integration) — owned by F-2; it imports the section 8.2 fixture into an isolated synthetic
  database and asserts the S01 values, the deferred leg-balance trigger, append-only and
  TRUNCATE refusals, and readback hash parity. It is **not** added in F-1, not even skipped.

---

## 10. F-3 plan (contract level; not authorized by F-1)

| Item | Decision |
| --- | --- |
| Capability | `programs.financial.overview` (read, `programs.*` family next to `programs.overview`); payload `program_entity_id`, `period`, `perspective`, `currency`, **`cost_basis`** (F1-D11), optional `source_cutoff` (RFC3339, normalized to UTC, passed as `request.source_cutoff`, section 5.3 step 1); resolves members with the S4 resolver (passing its unresolved count and truncation flag), then `evaluate_financial_overview` over persisted rows; response = section 5.4 with `program_entity_id` and money as decimal strings (`amount_decimal`, F1-D03) |
| Per-Project read | none separate: per-Project figures are in the overview; a dedicated read is a later decision |
| Operator status read | an operator-only read of designations, runs, refusals and the mapping queue (name fixed by F-3) |
| Purpose | a new `program_financial_read` purpose (distinct from `program_reporting_read`) — fixed here at contract level only (R11 ruling Q9); nothing is added to code in F-1 |
| Switches | composed only when `MY_PA_FINANCIAL_SOURCE_ENABLED` **and** `MY_PA_PROGRAM_REPORTING_ENABLED` are on |
| ChatLLM | `CHATLLM_OPERATOR_DECISION_REQUIRED` (withheld) until OD-06 and OD-08 are decided |
| Remote MCP / façade / web | not in any default grant set; no façade entry; no web route — each an operator decision (F1-O10) |
| Disclosure | `reportable` is presented as source integrity and coverage only, never as a certified total (F1-U11); `reportability`, every reason, the denominator, `source_versions`, `pending_source_versions`, `source_cutoff_at` are always returned; a `not_reportable` total is `null`, never `0`; without a designation the answer is `source_not_integrated` with empty measures (07 example) |

---

## 11. Security and abuse

| Concern | Control |
| --- | --- |
| Parser abuse (size, row, line, cell bombs) | V2 size check before decoding; V8 row and line caps before splitting cells; 24 fixed cells ≤ 64 chars; linear; no nesting, no quoting, no entity expansion, no eval |
| Encoding tricks | ASCII only; BOM, CR, TAB, control bytes, quotes refused file-wide |
| Formula injection | section 7.5; the amount column is grammar-only |
| Partial / truncated / corrupted exports | `end` record, 2 row counts, final LF, body SHA-256; whole-file reject. The body SHA-256 is declared **inside the same file**: it detects truncation and accidental corruption, **not deliberate tampering** — anyone who edits the file can recompute it (F1-U10) |
| Money correctness | Decimal only; `FloatOperation`, `Inexact`, `Rounded` trapped; scale 4 exact; rounding only in presentation; `NUMERIC(20,4)` range on input and on aggregates |
| Authority | `status`, `approved_by` and `approved_at` are **self-asserted export content**; the designation check is a **consistency check**, not authentication. Authenticity rests entirely on **provenance**: an operator-only import of a file the operator obtained from the designated source. There is no signature. A client can never mark approved, designate, import or map (F-2/F-3 policy); proposed versions never feed figures or supersede |
| Spoofing | the file's `source_system` is checked against the designation at admission (a consistency check on a self-asserted string: a forged file naming `syn-fin-a` / `syn-approver-1` with a recomputed body hash is admitted and can be effective — only operator provenance prevents it, F1-U10); same ref with new content ⇒ `source_version_conflict`, which detects an edit **only when the original content was imported too**; external ids resolve only through operator-reviewed mappings; double coverage ⇒ `double_count_detected` |
| Determinism | sorted inputs, canonical encoder, schema-prefixed digests, period from data only, no clock; property tests prove order independence |
| Information leak | refusals carry code and line only; no logging or printing in the finance modules |

---

## 12. Tests, crosswalk, prove-red and the scope guard

### 12.1 Test modules (all FAST, unmarked; 9 modules)

| Module | Tests (exact names) |
| --- | --- |
| `tests/unit/test_financial_money.py` | `test_amount_grammar_accepts_the_frozen_forms`; `test_amount_grammar_refuses_exponent_separators_and_locale`; `test_amount_refuses_negative_zero_leading_plus_and_leading_zeros`; `test_amount_scale_above_4_is_refused_never_rounded`; `test_amount_range_is_numeric_20_4`; `test_no_float_is_accepted_anywhere`; `test_money_sum_is_exact_at_full_precision`; `test_money_sum_is_exact_and_traps_inexact`; `test_empty_sum_and_negated_zero_are_storable`; `test_presentation_rounding_is_half_even_per_currency`; `test_unknown_currency_has_no_minor_units`; `test_format_amount_always_writes_4_places` |
| `tests/unit/test_financial_domain.py` | `test_records_refuse_float_and_unquantized_amounts`; `test_mapping_match_basis_is_operator_review_only`; `test_current_mapping_is_the_highest_revision`; `test_effective_version_ignores_proposed_supersession`; `test_withdrawal_withdraws_the_superseded_version`; `test_two_approved_heads_are_ambiguous`; `test_same_ref_different_content_is_a_version_conflict`; `test_run_from_an_undesignated_system_is_refused`; `test_period_snapshot_slices_by_external_project`; `test_supersession_cycle_is_ambiguous`; `test_approved_and_withdrawn_heads_are_ambiguous`; `test_several_withdrawn_heads_are_withdrawn_source`; `test_dangling_withdrawal_stays_a_withdrawn_head`; `test_conflict_is_system_wide_and_terminal`; `test_admitting_run_is_the_latest_carrying_the_content`; `test_mapping_revision_gap_is_an_input_error`; `test_duplicate_designation_is_an_input_error` |
| `tests/unit/test_financial_equations.py` | `test_revised_contract_is_original_plus_approved_changes`; `test_pending_changes_never_enter_approved_figures`; `test_eac_is_actual_plus_ctc_or_source_eac_never_both`; `test_variance_requires_one_version_scope`; `test_owner_budget_reconciliation_identity`; `test_at020_owning_project_figures_balance`; `test_at020_consolidation_is_net_neutral`; `test_at020_transfer_is_eliminated_once`; `test_at020_pending_change_is_reported_separately`; `test_at020_unapproved_transfer_is_excluded`; `test_at020_currency_mismatch_is_not_consolidated`; `test_double_count_is_detected` |
| `tests/unit/test_financial_reportability.py` | `test_no_designation_is_source_not_integrated`; `test_project_level_reason_nulls_every_metric_of_that_project`; `test_program_total_is_not_reportable_when_any_member_is`; `test_per_project_figures_survive_a_program_gap`; `test_no_zero_is_substituted`; `test_denominator_counts_every_member`; `test_evaluator_has_no_threshold_parameter`; `test_currency_mismatch_reports_fx_missing`; `test_refused_run_newer_than_effective_poisons_the_designation`; `test_membership_unresolved_blocks_program_totals_only`; `test_stale_approval_is_not_reportable`; `test_unrecognized_approver_is_not_reportable`; `test_admitted_run_failing_hash_parity_is_hash_mismatch`; `test_identical_reimport_clears_poisoning`; `test_poisoning_crosses_periods`; `test_membership_truncated_blocks_program_totals_only`; `test_source_cutoff_excludes_later_versions`; `test_project_cap_is_the_s4_cap` |
| `tests/unit/test_financial_canonical.py` | `test_content_hash_ignores_row_order`; `test_content_object_round_trips`; `test_decode_refuses_unknown_keys_and_numbers`; `test_hash_parity_detects_a_changed_amount`; `test_overview_digest_is_deterministic`; `test_slice_hash_covers_only_its_project`; `test_canonical_encoder_bytes_are_pinned`; `test_decode_refuses_bool_counts_and_nan` |
| `tests/unit/test_financial_properties.py` | `test_seeded_balanced_transfers_consolidate_to_zero`; `test_seeded_pending_rows_never_move_approved_metrics`; `test_seeded_amount_strings_round_trip`; `test_seeded_body_mutations_are_refused`; `test_seeded_input_order_never_changes_the_overview`; `test_seeded_presentation_rounding_matches_integer_reference` |
| `tests/unit/test_financial_source_parser.py` | `test_valid_fixture_parses_to_its_golden_version`; `test_each_malformed_fixture_refuses_with_its_code`; `test_refusal_carries_code_and_line_only`; `test_oversized_input_is_refused_before_decoding`; `test_too_many_rows_under_an_injected_limit`; `test_formula_injection_is_refused_in_text_cells_only`; `test_a_negative_amount_is_not_a_formula`; `test_partial_export_is_rejected_whole`; `test_tampered_body_is_a_hash_mismatch`; `test_parser_raises_only_type_error_for_non_bytes`; `test_period_is_data_never_ingest_time`; `test_end_line_cells_are_validated`; `test_transfer_leg_sign_is_not_masked_by_amount_sign` |
| `tests/unit/test_financial_source_fixtures.py` | `test_fixture_files_match_their_pinned_sha256`; `test_fixture_directory_equals_the_manifest`; `test_every_scenario_matches_its_golden`; `test_fixture_identifiers_are_synthetic`; `test_no_test_calls_the_fixture_writer`; `test_fixtures_are_not_text_normalised` (asserts `.gitattributes` carries the section 8.1 rule and that the CRLF, TAB, BOM and no-final-LF fixtures still hold those bytes) |
| `tests/architecture/test_financial_source_scope.py` | `test_financial_crosswalk_names_real_tests`; `test_no_financial_capability_purpose_or_id_kind`; `test_no_financial_table_or_migration`; `test_financial_switch_has_no_consumer`; `test_financial_modules_are_imported_only_by_their_own_slice`; `test_financial_modules_import_only_their_allowed_roots`; `test_financial_modules_use_no_float_io_or_logging`; `test_programs_financial_overview_is_not_served`; `test_the_table_guard_does_not_match_legacy_names` |

### 12.2 Seeded property tests

`random.Random(seed)` with `# noqa: S311 - deterministic test data, not a secret`, seeds
`range(200)` per property (S6-1 oracle precedent); generators build valid synthetic versions
from the section 8 vocabulary (2–6 Projects, 0–20 lines each, 0–5 transfers, amounts drawn as
integers of ten-thousandths in `(-10^20, 10^20)` and formatted). Properties: balanced
transfers consolidate to 0 and every transfer is eliminated once; adding pending change
orders / pending transfers leaves every approved metric identical; `format_amount(parse_amount(s))`
is canonical and idempotent; a single random byte change in the body of a valid file is
refused (never admitted with a different content under the declared hash); shuffling every
evaluator input yields the same `overview_sha256`; `presentation_amount` equals an
integer-arithmetic half-even reference. Not exhaustive (F1-U07).

### 12.3 Architecture scope guard (`tests/architecture/test_financial_source_scope.py`)

| Test | Pins |
| --- | --- |
| `test_financial_crosswalk_names_real_tests` | every `test_*` named in section 12.1 and 12.5 is a function defined in the module of its row (S4 guard precedent) |
| `test_no_financial_capability_purpose_or_id_kind` | no `Capability` or `Purpose` value contains `financ`; no `IdKind` value is one of the 9 planned prefixes and no member name contains `FINANCIAL` |
| `test_no_financial_table_or_migration` | the exact 9 planned names with identifier boundaries — `(?<![A-Za-z0-9_])financial_(source_designations\|source_runs\|source_versions\|project_mappings\|period_snapshots\|account_lines\|change_orders\|scope_transfers\|transfer_legs)(?![A-Za-z0-9_])` — match no table name in `METADATA` and no text of `migrations/versions/*.py` or `migrations/sql/*.sql` (R11-F01) |
| `test_the_table_guard_does_not_match_legacy_names` | positive control: the same pattern does **not** match the legacy names present at the basis (`procore_financial_change_orders`, `procore_financial_change_order_line_items`, `procore_financial_change_events`, `second_brain_financial_source_coverage_snapshots`, `raw_financial_source_payload_persisted`), and **does** match each of the 9 planned names written alone and schema-qualified (`knowledge.financial_source_runs`) — so the guard is shown to discriminate |
| `test_financial_switch_has_no_consumer` | `MY_PA_FINANCIAL_SOURCE_ENABLED` and `financial_source_enabled` occur in no file under `src/`, `apps/`, `ops/`, `migrations/`, `web/src/`, nor in any `.env*` example file |
| `test_financial_modules_are_imported_only_by_their_own_slice` | by `ast`, `my_pa.domain.project_controls.financial` is imported only by its own modules and `my_pa.infrastructure.financial`; `my_pa.infrastructure.financial` by nothing under `src/`, `apps/`, `ops/`, `migrations/` (tests only) |
| `test_financial_modules_import_only_their_allowed_roots` | the 6 domain modules import only the standard library, `my_pa.domain.schedule.canonical` (name `canonical_json_bytes` only), `my_pa.domain.program.vocabulary` (name `MetricValueState` only) and each other; the 2 infrastructure modules additionally only the finance domain |
| `test_financial_modules_use_no_float_io_or_logging` | in the 8 modules: no `float` name or float literal, no import of `logging`, `os`, `pathlib`, `io`, `socket`, `urllib`, `http`, `subprocess`, `pickle`, `xml`, `csv`, `json` (outside `canonical.py`'s use of the shared encoder), no call to `print`, `open`, `eval`, `exec`, `compile`, `__import__` |
| `test_programs_financial_overview_is_not_served` | the strings `programs.financial` and `program_financial_read` occur in no file under `src/`, `apps/`, `ops/`, `migrations/`, `web/src/` (R11-F15) |

### 12.4 Prove-red plan (1 mutation at a time, revert after each, `git status` clean)

| # | Guard | Single mutation | Test that must turn red (for that reason) |
| --- | --- | --- | --- |
| PR-01 | scale refused, not rounded | `parse_amount` quantizes a 5-place input | `test_amount_scale_above_4_is_refused_never_rounded` |
| PR-02 | float refused | drop the `type(value) is Decimal` check in `is_storable_amount` | `test_no_float_is_accepted_anywhere`, which asserts `is_storable_amount(1.5) is False` with no exception (expected failure: `AttributeError` from a Decimal-only method called on the float) |
| PR-03a | precision | set `FINANCE_CONTEXT.prec = 10` only | `test_money_sum_is_exact_at_full_precision` (input: `money_sum` of `9999999999999999.9999` 3 times; expected `29999999999999999.9997` exactly; expected failure: `Rounded` raised) |
| PR-03b | inexact trap | remove `Inexact` **and** `Rounded` from the traps (1 named alternative; then run again removing only `Rounded`) | `test_money_sum_is_exact_and_traps_inexact` (input: `Decimal("1") / Decimal("3")` under `FINANCE_CONTEXT`; expected failure: no exception raised). Each alternative is run separately and reported |
| PR-04 | presentation mode | `ROUND_HALF_UP` in `presentation_amount` | `test_presentation_rounding_is_half_even_per_currency` |
| PR-05 | pending excluded | `approved_changes` includes `pending` | `test_pending_changes_never_enter_approved_figures` |
| PR-06 | EAC exclusivity | EAC adds `source_eac` to the computed value when both exist | `test_eac_is_actual_plus_ctc_or_source_eac_never_both` |
| PR-07 | elimination | Program `transfers_in` sums all member legs | `test_at020_transfer_is_eliminated_once` |
| PR-08 | reconciliation | skip section 4.5 | `test_owner_budget_reconciliation_identity` |
| PR-09 | double count | skip the cross-version ref check | `test_double_count_is_detected` |
| PR-10 | no zero substitution | a missing balance measure returns `0.0000` | `test_no_zero_is_substituted` |
| PR-11 | Program gate | Program total reported when 1 member is `not_reportable` | `test_program_total_is_not_reportable_when_any_member_is` |
| PR-12 | proposed never supersedes | count `proposed` in supersession | `test_effective_version_ignores_proposed_supersession` |
| PR-13 | version conflict | drop the same-ref/different-content rule | `test_same_ref_different_content_is_a_version_conflict` |
| PR-14 | stale approval | drop the `approved_at < cutoff_at` rule | `test_stale_approval_is_not_reportable` |
| PR-15 | refused run poisons | ignore refused runs | `test_refused_run_newer_than_effective_poisons_the_designation` |
| PR-16 | hash order independence | sort `account_lines` by input order in the canonical object | `test_content_hash_ignores_row_order` |
| PR-17 | hash parity (evaluator) | `evaluate_financial_overview` skips the section 3.7 step 7 recomputation | `tests/unit/test_financial_reportability.py::test_admitted_run_failing_hash_parity_is_hash_mismatch` (input: an admitted S01 run whose stored `content_sha256` is the digest of `syn_version_conflict`'s content; expected failure: overview `reportable` instead of [`hash_mismatch`]) |
| PR-18 | formula refusal | skip the formula check | `test_formula_injection_is_refused_in_text_cells_only` |
| PR-19 | negative amount legitimate | apply the formula check to `amount` | `test_a_negative_amount_is_not_a_formula` |
| PR-20 | body hash | skip V14 | `test_tampered_body_is_a_hash_mismatch` |
| PR-21 | partial export (count) | skip V13 count equality only | `test_partial_export_is_rejected_whole`, which exercises `malformed/partial_export__count.csv` (expected failure: admitted, or refused with a later code, instead of `partial_export` at line 3) |
| PR-22 | size before decode | move V2 after V4 | `test_oversized_input_is_refused_before_decoding` (input: `max_bytes + 1` bytes whose first bytes are non-ASCII `0xC3 0x96`; expected `too_large`; expected failure: `non_ascii` at line 1) |
| PR-23 | fixture pin | change 1 byte of `syn_at020_owner_budget.csv` | `test_fixture_files_match_their_pinned_sha256` |
| PR-24 | synthetic ids | rename `SYN-P-100` to `P-100` in 1 fixture (and its pin) | `test_fixture_identifiers_are_synthetic` |
| PR-25 | no threshold | add `materiality: Decimal = Decimal(0)` to the evaluator | `test_evaluator_has_no_threshold_parameter` |
| PR-26 | no capability | add a `Capability` member `programs.financial.overview` (scratch, not committed) | `test_no_financial_capability_purpose_or_id_kind` |
| PR-27 | no table | add a scratch `Table("financial_source_runs", METADATA, ...)` | `test_no_financial_table_or_migration` |
| PR-28 | no switch consumer | read `MY_PA_FINANCIAL_SOURCE_ENABLED` in `src/my_pa/bootstrap/settings.py` | `test_financial_switch_has_no_consumer` |
| PR-29 | import containment | import `my_pa.infrastructure.financial.synthetic_csv` from an application module | `test_financial_modules_are_imported_only_by_their_own_slice` |
| PR-30 | allowed roots | import `my_pa.domain.lineage.vocabulary` in `model.py` | `test_financial_modules_import_only_their_allowed_roots` |
| PR-31 | no IO | `import logging` in `synthetic_csv.py` | `test_financial_modules_use_no_float_io_or_logging` |
| PR-32 | crosswalk | rename 1 crosswalk test | `test_financial_crosswalk_names_real_tests` |
| PR-33 | legacy discrimination | drop the leading `(?<![A-Za-z0-9_])` boundary | `test_the_table_guard_does_not_match_legacy_names` (expected failure: `procore_financial_change_orders` matched) |
| PR-34 | conflict terminal | let resolution continue after a conflict | `test_conflict_is_system_wide_and_terminal` (S09 gains `source_version_ambiguous`) |
| PR-35 | cycle | compute heads without cycle detection | `test_supersession_cycle_is_ambiguous` |
| PR-36 | admitting run | use the **least** `run_sequence` carrying the content | `test_identical_reimport_clears_poisoning` (S31) |
| PR-37 | truncation gate | ignore `membership_truncated` | `test_membership_truncated_blocks_program_totals_only` |
| PR-38 | source cutoff | ignore `request.source_cutoff` | `test_source_cutoff_excludes_later_versions` (S37) |
| PR-39 | encoder pin | change the separators of the imported encoder in a scratch copy | `test_canonical_encoder_bytes_are_pinned` |
| PR-40 | leg sign masking | apply `amount_sign` to transfer legs | `test_transfer_leg_sign_is_not_masked_by_amount_sign` |

A prove-red that stays green is reported as redundancy, a masked test or an unreachable
hazard, never as "covered".

### 12.5 Crosswalk

| Requirement | Contract | F-1 test (module::name) or owner |
| --- | --- | --- |
| CR-011 immutable source version, hash, period, cutoff, status, approval actor | 3.5, 3.7, 6 | `tests/unit/test_financial_domain.py::test_same_ref_different_content_is_a_version_conflict`; `tests/unit/test_financial_canonical.py::test_content_object_round_trips` |
| CR-011 perspective, currency ISO 4217, cost basis, `NUMERIC(20,4)`, minor unit, rounding | 3.2, 3.3 | `tests/unit/test_financial_money.py::test_amount_range_is_numeric_20_4`; `tests/unit/test_financial_money.py::test_presentation_rounding_is_half_even_per_currency` |
| CR-011 identity tuple; mapping append-only, never fuzzy | 3.6, 3.8 | `tests/unit/test_financial_domain.py::test_mapping_match_basis_is_operator_review_only`; `tests/unit/test_financial_domain.py::test_current_mapping_is_the_highest_revision` |
| CR-011 `revised_contract` | 4.2 | `tests/unit/test_financial_equations.py::test_revised_contract_is_original_plus_approved_changes` |
| CR-011 EAC XOR | 4.3 | `tests/unit/test_financial_equations.py::test_eac_is_actual_plus_ctc_or_source_eac_never_both` |
| CR-011 variance same scope | 4.4 | `tests/unit/test_financial_equations.py::test_variance_requires_one_version_scope` |
| CR-011 pending separate; planned/unapproved never affect approved | 4.1, 4.6 | `tests/unit/test_financial_equations.py::test_pending_changes_never_enter_approved_figures`; `tests/unit/test_financial_properties.py::test_seeded_pending_rows_never_move_approved_metrics` |
| CR-011 transfer legs, elimination, reconcile once, double count | 4.5–4.7 | `tests/unit/test_financial_equations.py::test_double_count_is_detected`; `tests/unit/test_financial_properties.py::test_seeded_balanced_transfers_consolidate_to_zero` |
| CR-011 `NOT_REPORTABLE` on missing source/project/mapping/approval/FX | 5 | `tests/unit/test_financial_reportability.py::test_currency_mismatch_reports_fx_missing`; `tests/unit/test_financial_source_fixtures.py::test_every_scenario_matches_its_golden` |
| CR-011 tests: malformed / external spoof | 3.10, 7 | `tests/unit/test_financial_source_parser.py::test_each_malformed_fixture_refuses_with_its_code`; `tests/unit/test_financial_domain.py::test_run_from_an_undesignated_system_is_refused` |
| CR-011 tests: stale approval | 3.7 | `tests/unit/test_financial_reportability.py::test_stale_approval_is_not_reportable` |
| CR-011 tests: exact hash parity | 6.2 | `tests/unit/test_financial_canonical.py::test_hash_parity_detects_a_changed_amount` |
| CR-011 recovery (halt, retain, quarantine, no source write) | 9.4 | F-2 |
| WP-05A parser tamper / FX / period / currency | 7, 5 | `tests/unit/test_financial_source_parser.py::test_tampered_body_is_a_hash_mismatch`; `tests/unit/test_financial_source_parser.py::test_period_is_data_never_ingest_time` |
| WP-05A independently reconcile an approved synthetic export exactly | 8.6 | `tests/unit/test_financial_equations.py::test_at020_owning_project_figures_balance` |
| WP-05A tables, importer, view | 9, 10 | F-2, F-3 |
| AT-020 two Projects, approved 2 legs Σ=0 + pending, same WBS package | 8.2 | `tests/unit/test_financial_equations.py::test_at020_pending_change_is_reported_separately` |
| AT-020 consolidation net-neutral; owning-Project figures balanced | 4.6, 8.6 | `tests/unit/test_financial_equations.py::test_at020_consolidation_is_net_neutral`; `tests/unit/test_financial_equations.py::test_at020_transfer_is_eliminated_once` |
| AT-020 hashes/period match | 6 | `tests/unit/test_financial_canonical.py::test_content_hash_ignores_row_order` |
| AT-020 unapproved transfer, currency mismatch, double count rejected | 4.6, 5 | `tests/unit/test_financial_equations.py::test_at020_unapproved_transfer_is_excluded`; `tests/unit/test_financial_equations.py::test_at020_currency_mismatch_is_not_consolidated` |
| AT-020 database + integration half | 9.4 | F-2 `tests/integration/test_financial_scope_transfer.py` |
| OD-06 no designation ⇒ `source_not_integrated` | 5.3 step 2 | `tests/unit/test_financial_reportability.py::test_no_designation_is_source_not_integrated` |
| OD-06 nothing public or persistent | 12.3 | `tests/architecture/test_financial_source_scope.py::test_no_financial_table_or_migration`; `tests/architecture/test_financial_source_scope.py::test_programs_financial_overview_is_not_served` |
| OD-08 default `NOT_REPORTABLE`, per-Project partial figures, denominator, no zero substitution, no threshold | 5 | `tests/unit/test_financial_reportability.py::test_per_project_figures_survive_a_program_gap`; `tests/unit/test_financial_reportability.py::test_denominator_counts_every_member`; `tests/unit/test_financial_reportability.py::test_evaluator_has_no_threshold_parameter` |
| UB-009 no real source; synthetic only | 7, 8.1 | `tests/unit/test_financial_source_fixtures.py::test_fixture_identifiers_are_synthetic`; `tests/architecture/test_financial_source_scope.py::test_financial_switch_has_no_consumer` |
| OD-08 truncated membership never reportable | 5.1, 5.3 | `tests/unit/test_financial_reportability.py::test_membership_truncated_blocks_program_totals_only` |
| CR-011 version resolution total (cycles, mixed heads, dangling, system-wide conflict) | 3.7 | `tests/unit/test_financial_domain.py::test_supersession_cycle_is_ambiguous`; `tests/unit/test_financial_domain.py::test_approved_and_withdrawn_heads_are_ambiguous`; `tests/unit/test_financial_domain.py::test_conflict_is_system_wide_and_terminal` |
| CR-011 recovery from a refused run | 3.7 step 6 | `tests/unit/test_financial_reportability.py::test_identical_reimport_clears_poisoning` |
| 07 `source_cutoff` | 5.3 step 1 | `tests/unit/test_financial_reportability.py::test_source_cutoff_excludes_later_versions` |
| CR-011 exact hash parity (evaluator) | 3.7 step 7 | `tests/unit/test_financial_reportability.py::test_admitted_run_failing_hash_parity_is_hash_mismatch`; `tests/unit/test_financial_canonical.py::test_canonical_encoder_bytes_are_pinned` |
| Legacy names never match the planned-table guard | 12.3 | `tests/architecture/test_financial_source_scope.py::test_the_table_guard_does_not_match_legacy_names` |

---

## 13. Divergences, open operator decisions, residuals

### 13.1 Divergences (package vs repository vs this contract)

| ID | Package | This contract | Reason |
| --- | --- | --- | --- |
| F1-D01 | `domain/project_controls/financial.py` | subpackage `domain/project_controls/financial/` (6 modules), not re-exported | the existing package is the Constraint domain; a single module would exceed reviewable size and couple the Constraint export surface |
| F1-D02 | "isolated format parsers" | 1 pure in-process parser of 1 synthetic format | no real format is designated; containment of a real adapter belongs to F-2 import |
| F1-D03 | 07 `value` integer/number; `amount_decimal` string only in eliminations | every money value is a decimal string with 4 places | JSON numbers lose exactness; no float anywhere |
| F1-D04 | 07 `coverage_state` (8 values) | S4 `MetricValueState` + finance reasons | the repository's Program precedent (S4 D-11) |
| F1-D05 | — | `FinancialNotReportableReason` separate from S4 `NotReportableReason` | the S4 set is closed and pinned by its scope guard |
| F1-D06 | identity `(source_system, external_account/project/contract/cost_code/scope, source_version, period, perspective, currency)` | identity adds `cost_basis` and `measure`; `cost_code`, `wbs_package` explicit; CR's `scope` is `wbs_package`; CR's `external_account` is **omitted** (the synthetic format has no account identifier separate from `cost_code`; a designated source with one needs a format revision) | 2 measures of 1 cost code are distinct facts; basis changes meaning (R11-F17) |
| F1-D07 | 8 tables | 9 (adds `financial_source_designations`) | the operator designation must be durable and attributable |
| F1-D08 | — | F-2 tables schema-qualified `knowledge.financial_*`, never created in, granted through or read from schema `financial` or `procore` | the `financial` schema is a migrated legacy schema (67 objects: 28 `MIGRATE_DATA`, 20 `REBUILD_AND_VALIDATE`, 11 `ARCHIVE_LEGACY_SOURCE_ONLY`, 8 `REINITIALIZE_OPERATIONAL_STATE`; 65 `FINANCIAL_OPERATIONAL`, 2 personal), unanalysed, whose production row content is unverified, and which is not a designated source |
| F1-D09 | buyout, billing, cash flow "only if source-backed" | not in v1 measures | no source backs them; adding a measure is a contract amendment |
| F1-D10 | variance against "approved current budget" | contract perspective uses `revised_contract` | the contract perspective has no budget measure |
| F1-D11 | 07 input without `cost_basis` | F-3 requires `cost_basis` | variance is defined only within 1 basis |
| F1-D12 | 07 `transfer_eliminations` | same fields plus `cost_code`, `wbs_package`, `source_content_sha256` instead of `source_version_id` | F-1 has no persisted ids |
| F1-D13 | AT-020 database+integration test | domain half F-1; DB half F-2 | F-1 has no persistence; no skipped test |
| F1-D14 | parser sandbox tests | `tests/unit/` | `tests/parser_isolation/` is `SCAFFOLD_ONLY` |
| F1-D15 | switch implied | no Settings field in F-1 | no consumer may exist; pinned |
| F1-D16 | status `withdrawn` on a version | withdrawal is a new immutable version naming the withdrawn one | versions are immutable |
| F1-D17 | "stale approval" undefined | `approved_at < cutoff_at` | the only data-derived staleness; any other rule is F1-O02 |
| F1-D18 | supersession undefined | proposed versions never supersede | unapproved data may not move the approved position |
| F1-D19 | "never fuzzy autoaccept" | `MatchBasis` has 1 member `operator_review` | closed by type |
| F1-D20 | — | `domain/schedule/currency.py` not reused | it is schedule publication currency, not money |
| F1-D21 | "exact hash parity" | reuse the schedule ASCII encoder and schema-prefix idiom, pinned by a finance-owned byte vector (`test_canonical_encoder_bytes_are_pinned`) | 1 encoder; finance content is ASCII; a schedule-side change turns finance red (R11-F21) |
| F1-D22 | 07 output fields `grain`, `unit`, `coverage_state`, `dedupe_basis`, `source_run_ids`, `as_of`, `excluded_project_count`, `nonadditive_across_projects`; input `source_cutoff` | mapped or dropped per the section 5.4 table; `source_cutoff` is `request.source_cutoff` | the F-1 evaluator defines every field it returns (R11-F07) |
| F1-D23 | no truncation reason (the contract's first revision had 28 reasons) | 29: `membership_truncated` added | a truncated Program would otherwise be `reportable` (R11-F06) |
| F1-D24 | parser code name | `source_version_not_first` (was `source_version_missing`) | the reason `source_version_missing` has a different meaning (R11-F22) |

### 13.2 Open operator decisions

| ID | Decision | Default until decided |
| --- | --- | --- |
| F1-O01 | Designate each finance source (Owner budget, construction contract), its export, adapter and schedule (OD-06) | none; `source_not_integrated` |
| F1-O02 | Approval hierarchy, recognized approvers, and the staleness rule | `approved_at < cutoff_at` ⇒ stale; approvers only from a designation |
| F1-O03 | Materiality thresholds (OD-08) | none; every gap material |
| F1-O04 | FX authority, rate source and conversion policy | no FX; mismatch not reportable |
| F1-O05 | Program consolidation perspective and elimination policy | per request perspective; internal transfers eliminated from gross movement only |
| F1-O13 | Whether the owner-budget reconciliation identity (section 4.5, `current = original + approved changes + transfer_net`) holds for a designated source, or which other adjustments a real budget carries | model default: the identity applies; a real source failing it is `source_reconciliation_failed` on every Project until decided (R11-F19) |
| F1-O06 | Reporting period calendar (calendar vs fiscal month) and cutoff convention | calendar month `YYYY-MM`, UTC |
| F1-O07 | Default cost basis | none; the request names it |
| F1-O08 | Who reviews mappings; quarantine procedure | operator only |
| F1-O09 | Import surface: operator-only capability vs operator CLI | capability, attested-local, operator-only (S5b-2 precedent) |
| F1-O10 | ChatLLM, remote MCP, façade and web exposure of finance reads | withheld |
| F1-O11 | Retention of raw import files and refused runs | hashes and parsed rows only; no raw file stored |
| F1-O12 | Whether the migrated legacy `financial` schema (`forecast_*`, `second_brain_financial_*`, `staffing_*`) or the legacy `procore.procore_financial_*` tables are an OD-06 candidate source | not a source; never read; needs its own analysis and designation; UB-009 stands |

### 13.3 Residuals

| ID | Residual |
| --- | --- |
| F1-U01 | The F-1 parser runs in-process with byte/row/line/cell bounds but no child process or `RLIMIT_AS`; F-2 decides containment for imports |
| F1-U02 | The synthetic format is not any real export; a real source needs its own adapter producing `SourceVersion`, its own fixtures and review |
| F1-U03 | ASCII-only identifiers; a real source with non-ASCII names needs a normalisation rule and a new format version |
| F1-U04 | No FX: a multi-currency Program is never reportable |
| F1-U05 | Program membership is an evaluator input in F-1; F-3 wires the S4 resolver |
| F1-U06 | Hex digests are frozen by the I11-B implementer, not by this contract |
| F1-U07 | Seeded property tests sample; they do not prove |
| F1-U08 | `presentation_amount` has no production consumer until F-3 |
| F1-U09 | The migrated legacy `financial` schema (67 objects, 28 data-migration targets, so production may hold real financial rows — unverified) and the `procore.procore_financial_*` tables are unanalysed; UB-009 stands; flagged to the operator as F1-O12 |
| F1-U10 | **No authenticity.** `body_sha256`, `source_system`, `status`, `approved_by` and `approved_at` are self-asserted inside the file; a deliberate forger recomputes the hash and names the designated system and approver. Authenticity rests entirely on operator-only import of an operator-obtained file (provenance); there is no signature. Same-ref conflict detects an edit only when the original content was imported first |
| F1-U11 | `reportable` certifies source integrity and coverage only, never a certified total (OD-08); F-3 wording must say so |
| F1-U12 | Cross-system double-count detection by ref is fail-closed against legitimate ref reuse by independent systems, and misses the same change order under different refs in 2 systems |

---

## 14. F-1 work split (proposal)

2 sequential packages; B depends on A's public symbols. A single package was considered and
rejected: 8 source modules, 9 test modules and 73 fixture files exceed a reviewable diff, and
the parser/fixture half can be reviewed against frozen domain symbols.

| Package | Owned paths | Deliverables |
| --- | --- | --- |
| **I11-A** pure domain | `src/my_pa/domain/project_controls/financial/` (6 modules); `tests/unit/test_financial_money.py`, `tests/unit/test_financial_domain.py`, `tests/unit/test_financial_equations.py`, `tests/unit/test_financial_reportability.py`, `tests/unit/test_financial_canonical.py`, `tests/unit/test_financial_properties.py` | sections 3–6; tests build versions in Python (no fixture files); AT-020 domain assertions from the section 8.2 values written inline; prove-red PR-01–PR-17, PR-25, PR-34–PR-38; **at its own head** re-measures the R-17 figures (494 → 500 source, 953 → 959 test) in both contended `docs/plans` files and the claimed FAST/mypy figures, re-weighs `tests/ci_shard_weights.json` and runs `python -m tests.ci_shard verify` (owned paths add those 3 files) |
| **I11-B** parser, fixtures, guard, pins | `src/my_pa/infrastructure/financial/` (2 modules); `tests/fixtures/financial_source/`, `tests/fixtures/financial_source_writer.py`; `.gitattributes` (section 8.1 rule only); `tests/unit/test_financial_source_parser.py`, `tests/unit/test_financial_source_fixtures.py`, `tests/architecture/test_financial_source_scope.py`; the count pins in `docs/plans/mcv-completion-plan.md` and `docs/plans/relationship-intelligence-implementation-plan.md`; `tests/ci_shard_weights.json` | sections 7, 8, 12.3; manifest and `FIXTURE_FILE_SHA256` frozen; prove-red PR-18–PR-24, PR-26–PR-33, PR-39, PR-40; at its own head re-measures the R-17 figures (500 → 502, 959 → 962), the claimed counts and the shard weights |

Either implementer that finds this contract wrong against code reality stops at that point and
reports a proposed amendment; trivial naming resolutions are allowed and listed in the
handoff.

---

## 15. Design review R11 — finding → fix map (revision R11-1)

R11 (PASS_WITH_REQUIRED_CHANGES at `6c00e671`) findings and where each is resolved:

| Finding | Severity | Fix |
| --- | --- | --- |
| R11-F01 | major | 12.3 `test_no_financial_table_or_migration`: exact 9 names with identifier boundaries over `migrations/versions/*.py` and `migrations/sql/*.sql` plus `METADATA`; positive control `test_the_table_guard_does_not_match_legacy_names`; PR-33 |
| R11-F02 | major | R-10 rewritten (migrated legacy schema, dispositions, sensitivity, families, unverified production rows), R-10a Procore financial tables, F1-D08, F1-O12, F1-U09, 9.1 schema and access obligations; ADR-018 Context |
| R11-F03 | major | 3.7 rewritten: exhaustive head table (cycle, approved + withdrawn, several withdrawn, dangling withdrawal), conflict system-wide and terminal; domain tests; goldens S34, S35 |
| R11-F04 | major | 8.5 S16–S18 list both reasons; the reason column is declared the complete sorted list; S09 terminal note |
| R11-F05 | major | 3.7 admitting run = greatest `run_sequence` carrying the content; cross-scope poisoning stated; recovery by re-import; 9.1 runs → version many-to-1, no file-hash uniqueness; goldens S31–S33; PR-36 |
| R11-F06 | major | reason `membership_truncated` (29), request field, S4 cap; S36; PR-37; F1-D23 |
| R11-F07 | major | `request.source_cutoff` defined (5.3 step 1); 07 output mapping table (5.4, F1-D22); verified-zero note; S37; PR-38 |
| R11-F08 | major | section 11 Authority/Spoofing/Partial rows reworded; 8.3 tampered row; 3.7 steps 1 and 5; F1-U10; ADR-018 decision 2 |
| R11-F09 | major | R-17 and section 14: each package re-measures its own pins, claimed counts and shard weights (I11-A 500/959, I11-B 502/962) |
| R11-F10 | major | 8.1 `.gitattributes` rule owned by I11-B; `test_fixtures_are_not_text_normalised`; `read_bytes` only |
| R11-F11 | major | PR-02, PR-03a/b, PR-17 (evaluator test), PR-21 (`partial_export__count.csv`), PR-22 rewritten with named inputs and expected failures |
| R11-F12 | minor | 3.2 and 7.7: `amount_sign` for account lines only; `test_transfer_leg_sign_is_not_masked_by_amount_sign`; PR-40 |
| R11-F13 | minor | V13 applies the full V15 checks to the `end` line; `test_end_line_cells_are_validated` |
| R11-F14 | minor | 3.3 rows for `money_sum` start, negation/`copy_abs`/zero normalisation, `parse_amount` quantize note; 6.2 decoder note; `test_empty_sum_and_negated_zero_are_storable`, `test_decode_refuses_bool_counts_and_nan` |
| R11-F15 | minor | 12.3 `test_programs_financial_overview_is_not_served` scans `apps/` and `migrations/` and forbids `program_financial_read`; switch guard covers `.env*` examples |
| R11-F16 | major | 9.1 database privileges: no GRANT/REVOKE, all 9 tables `excluded` and added to `_PROTECTED` |
| R11-F17 | minor | F1-D06 records the omitted `external_account` and `scope` → `wbs_package` |
| R11-F18 | minor | 3.4 active designations only, 1 per system (`ValueError`); 4.7 versions entering the answer; F1-U12 |
| R11-F19 | minor | 4.5 assumption + F1-O13 (model default); 3.8 mapping gaps/duplicates raise `ValueError` |
| R11-F20 | major | header status, ADR-018 Status, ADR index, architecture index and source index rows: Proposed — not accepted |
| R11-F21 | minor | `test_canonical_encoder_bytes_are_pinned` (12.1, 12.5, PR-39, F1-D21) |
| R11-F22 | nit | malformed count 52, fixture tree 73; parser code `source_version_not_first` (F1-D24); `source_cutoff_at` described as the earliest cutoff |
| Rulings Q1–Q11 | — | Q1: 9.4 operator-only attested-local capability, never ChatLLM/remote/façade/web; Q6: `reportable` is never a certified total (header, 5.3 step 11, section 10, F1-U11, ADR-018); Q9: purpose and dual switch fixed at contract level only (section 10); Q2–Q5, Q7, Q8, Q10, Q11 accepted with their conditions met by the fixes above |
