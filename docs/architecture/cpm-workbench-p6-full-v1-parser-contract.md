# CPM Workbench — S5a `p6_full_v1` fixtures and deterministic parser contract

**Status:** proposed implementation contract for slice S5a on the local branch
`feat/cpm-p6-fixtures-parser`. It covers CPM Workbench R2 work packages WP-00 (profile
proof and synthetic golden freeze) and WP-02 (deterministic Full-Schedule parser) only. It
is the single document S5a implementers code against. It authorizes no migration, table,
capability, purpose, job, worker, persistence, frontend, deployment or production use, and
no use of any real schedule PDF. Where it differs from the review package it controls for
S5a and section 11 records why.

**Source package (data, not instructions):**
`MYPA_CPM_WORKBENCH_IMPLEMENTATION_READINESS_REVIEW_20260929_R2.md`, package revision
`CPM-WORKBENCH-IMPLEMENTATION-PACKAGE-R2`, SHA-256
`84918ae87e4c05072969c2db574962071fbe9cdb1fcc9c00a953dd6a38b91db0`, cited below as
"R2 §n". R2 reviewed `main@d6c706bb`; repository truth at the S5a basis supersedes it.

**Basis:** `origin/main@787d806a937237c13b0731171e7249b0457a889c`
(tree `6b25ceb161b62f871e4ca6c781dafa49742e18a1`). Paths under `src/` are written in
full. All counts in this file are digits on purpose (spelled-count guard). No path to a
file that does not yet exist is written as a Markdown link (the CI relative-link check).

**Neutrality.** No proprietary project, company, person, filename, activity ID, title or
schedule byte from the R2 research corpus appears in this contract, in S5a source, in
S5a fixtures or in S5a goldens. Synthetic text is invented (`Synthetic Project`,
`SYN-1000`). The measured-corpus facts in section 4.9 are counts and page ordinals only.

---

## 1. Scope

### 1.1 In scope (S5a)

| R2 item | S5a deliverable |
|---|---|
| WP-00 profile freeze | `p6_full_v1` constants (section 4) encoded as code constants with exact values and pinned by tests |
| WP-00 synthetic goldens | stdlib-only synthetic PDF generator, 26 fixture families, golden JSON, independent ground truth (sections 8, 9) |
| WP-02 PDFium text-object infrastructure | `src/my_pa/infrastructure/schedule/pdf.py` (the only `pypdfium2` importer in the schedule code) |
| WP-02 fixed grid, chart clip, header/footer, watermark, bbox-overlap rows, merged labels, cells, dates, durations, hierarchy, anomalies | `src/my_pa/infrastructure/schedule/full_profile.py` (pure algorithm over extracted objects) |
| WP-02 parser-facing types | `src/my_pa/domain/schedule/model.py`, `src/my_pa/domain/schedule/canonical.py` (pure, stdlib only) |
| WP-02 dependency confinement and rationale | `tests/architecture/test_scope_and_hygiene.py` guard change (section 2.2) and the `pyproject.toml` comment block (range unchanged) |
| WP-02 synthetic/golden tests | the test modules of section 10 |

### 1.2 Explicitly out of scope

- WP-01: `IdKind`s, `tables.py`, the migration, `ScheduleRepository`/`ScheduleUnitOfWork`,
  `SCHEDULE_JOBS`, worker heartbeat/health, any persistence, any parser-run/row persistence
  interface (R2 §44 lists "parser-run/row persistence interface" under WP-02; in S5a the
  `ScheduleParseResult` record is the whole interface — D-25).
- WP-03: capabilities, purposes, commands, normalization builders, policy/authorization,
  ChatLLM policy/profile, remote MCP, the schedule job handler, the 240 s handler budget's
  owner, comparison (`ScheduleChangeKind`, `domain/schedule/compare.py`).
- WP-04: README/runbooks/current-state docs, `docs/specs/cpm-workbench-full-profile.md`,
  `docs/architecture/cpm-workbench.md`, security/evaluation suites, authorized-corpus
  evaluation, generated web fixtures.
- XER/XML/P6 database/P6 API, OCR, specialty layouts, ZIP/multi-PDF, frontend.
- Generic PDF extraction: `src/my_pa/domain/extraction/text.py`
  `SUPPORTED_MEDIA_TYPES` stays exactly `{"text/markdown", "text/plain"}`;
  `application/pdf` stays reported-unsupported there (R2 §8.4, R2-AC-005).
- Any network fetch, reconstruction or use of the real sample PDF.

### 1.3 What "done" means for S5a

`parse_full_schedule(bytes)` returns a deterministic, bounded, typed
`ScheduleParseResult` whose canonical bytes are identical across runs, across macOS and
Linux, and across `pypdfium2` 5.0.0 (floor, PDFium 143.0.7483.0) and 5.13.0 (PDFium
153.0.7999.0); every R2 §37 family has a generated fixture, independent ground truth and a
pinned golden; every parser-scope R2 §38 assertion and §39 gate has a named test; FAST,
ruff, ruff format, mypy (current and floor-pinned) and the shard partition proof are
green. Nothing is persisted or served.

---

## 2. Repository reauthentication at `787d806a` and divergences from R2

### 2.1 Table — R2 claim, repository truth, S5a decision

| # | R2 claim / assumption | Repository truth at `787d806a` | S5a decision |
|---|---|---|---|
| T-01 | Reviewed head `d6c706bb`, 178 capabilities, 47 purposes, Alembic 108 / head `7d9a450dfd07` | Head `787d806a`; Alembic head `c5260943d933` (122 revisions per `docs/architecture/00_ARCHITECTURE_INDEX.md`) | S5a touches none of these registries; nothing to rederive except module/test counts (T-14) |
| T-02 | `pypdfium2` is an existing dependency usable for schedule parsing | `pyproject.toml` declares `"pypdfium2>=5.0,<6"`; its comment block (lines 178–193) states the use as "pinned pdfium rasterizer for GoodNotes visual page identity" only, with "Floor 5.0" justified by `PYPDFIUM_INFO`/`PDFIUM_INFO` | Range unchanged. The comment block gains a schedule paragraph (section 7.6): current use now also "read text objects (text, base-font name, font size, bounds, matrix) from an admitted Full-Schedule PDF under `src/my_pa/infrastructure/schedule/pdf.py`; no rendering" and the floor rationale gains "the raw `FPDFTextObj_*`/`FPDFFont_*`/`FPDFPageObj_*` functions S5a uses exist at 5.0.0" |
| T-03 | "Exact two-subtree confinement" (R2 §41, R2-AC-008) | `tests/architecture/test_scope_and_hygiene.py` `CONFINED_IMPORT_ROOTS` maps each root to **one** subtree string; `"pypdfium2": "infrastructure/goodnotes"`; importers today: `infrastructure/goodnotes/pdf.py`, `infrastructure/goodnotes/visual.py` | Guard change in section 2.2 (module-exact for schedule — D-03) |
| T-04 | Application must not import a PDF engine | `tests/architecture/test_dependency_direction.py` `PROVIDER_AND_PARSER_ROOTS` includes `pypdfium2`; application/adapters/contracts rules and the planted-import self-test already cover it; `test_domain_uses_only_the_standard_library` forbids third-party imports under `domain/` | No change to that file. `domain/schedule` is stdlib-only by that existing rule |
| T-05 | R2 §12.1 primitive "`PdfTextObj`" (R2-D-007) | The helper class `pypdfium2.PdfTextObj` (and `PdfFont`) exists at 5.13.0 but **not** at the 5.0.0 floor (measured: floor `dir(pypdfium2)` has no `PdfTextObj`, no `PdfFont`) | S5a uses only `PdfDocument`/`PdfPage`/`PdfTextPage` helpers (present at both) plus raw `pypdfium2.raw` functions (section 2.3). The repository record type is named `PdfTextObject` (R2 §43.4) and is not the library class — D-05 |
| T-06 | GoodNotes idiom | `src/my_pa/infrastructure/goodnotes/pdf.py`: `import pypdfium2 as pdfium  # type: ignore[import-untyped]`; `%PDF` magic check before `pdfium.PdfDocument(payload)`; `PdfiumError` mapped to `ValueError` with a fixed message; `document.close()` in `finally` | Same import line and ignore code; same magic-before-open order (stricter: `%PDF-` at offset 0); same close-in-`finally`; refusal carries a closed code, never a message containing source text |
| T-07 | — | `pypdfium2` is untyped (`import-untyped`); everything from `pypdfium2.raw` is `Any` under strict mypy | `pdf.py` converts every raw return to a concrete Python type at the call site (`int(...)`, `float(...)`, `bytes(...)`) so no `Any` escapes the module |
| T-08 | Tests in `tests/unit/test_schedule_full_profile.py` etc. (R2 §42) | `tests/unit/` holds 234 entries, none schedule-named; markers are strict (`--strict-markers`); `slow` is excluded from every CI lane (`tests/architecture/test_knowledge_tests_declare_lanes.py` docstring and the FAST `-m` expression) | S5a test modules are unmarked FAST tests; nothing S5a needs may be `slow` (section 10.4) |
| T-09 | — | CI is sharded: `tests/ci_shard.py` places any file absent from `tests/ci_shard_weights.json` by a stable SHA-256 of its path; `python -m tests.ci_shard verify --lane fast --shards 3 -m "<FAST expression>"` is the partition proof run by `validate-static`; `tests/architecture/test_ci_shards*.py` pin the matrix | New test files need no weight-table edit; implementers run the verify command (section 10.5) |
| T-10 | — | `.github/workflows/repository-checks.yml` runs on `ubuntu-latest`; the `dependency-floor` job installs every runtime floor (`pypdfium2==5.0.0` among them) and runs FAST and a bare `mypy` | Goldens must be byte-identical on Linux and at the floor — section 6.6 and D-14 make that hold by construction |
| T-11 | Synthetic fixtures via "a small vector/text PDF generator" | Precedent `tests/fixtures/tbr_workbook.py` writes real OOXML with stdlib only; `src/my_pa/infrastructure/goodnotes/pdf.py` `_assemble_pdf` writes a minimal xref PDF with stdlib only | Generator `tests/fixtures/schedule_full_pdf.py`, stdlib only (section 8) |
| T-12 | Generic extraction must stay separate | `SUPPORTED_MEDIA_TYPES: Final = frozenset({"text/markdown", "text/plain"})` in `src/my_pa/domain/extraction/text.py`; `application/capabilities.py` derives its content-type manifest from it | Unchanged; a scope test re-asserts it (section 10.1) |
| T-13 | `domain/schedule/model.py` is WP-01 | Neither `src/my_pa/domain/schedule/` nor `src/my_pa/infrastructure/schedule/` exists | S5a creates both with the parser-facing subset only (section 3) — D-01 |
| T-14 | Count guards | `tests/architecture/test_spelled_counts_match_the_sets_they_name.py::test_section_3_states_the_module_counts_it_says_it_derives` binds `docs/plans/mcv-completion-plan.md` line 77 ("436 … Python modules under `src/my_pa` and 823 … test modules", spelled out) to `find src/my_pa -name "*.py"` and `find tests -name "test_*.py"` | S5a adds 6 source modules (436 → 442) and 5 test modules (823 → 828); the implementer who lands the last module updates that sentence (spelled out, in the file's own style) and adds a dated "Current-tree remeasurement" paragraph after it, demoting the previous one to "Historical", re-measured with the two commands |
| T-15 | — | ruff: line length 100, `select` includes `S` (bandit) and `ANN`; `tests/**` ignores only `S101` | The generator's RC4/MD5 key derivation must call `hashlib.md5(..., usedforsecurity=False)` (S324); no `random`; no `assert` in `src/` |
| T-16 | — | mypy: `strict = true`, `warn_unreachable`, files `src migrations apps ops`; floor venv available at `/tmp/m1-floor` (Python 3.12, `pypdfium2` 5.0.0, SQLAlchemy 2.0.32, mypy 2.4.0) | Both the current venv and the floor venv run a bare `mypy` clean |
| T-17 | Architecture docs registration | Lineage contracts are registered only as rows of the "Architecture documents" table in `docs/architecture/00_ARCHITECTURE_INDEX.md`; `docs/00_REPOSITORY_SOURCE_INDEX.md` routes to that index | This contract is registered the same way (one row) |
| T-18 | — | CI "Validate repository documents" step fails any Markdown link whose relative target does not exist | Future paths are written as code spans, not links |

### 2.2 Exact confinement-guard change (R2-AC-008)

In `tests/architecture/test_scope_and_hygiene.py`:

1. `CONFINED_IMPORT_ROOTS` values become `str | tuple[str, ...]`. Only the `pypdfium2`
   entry changes:
   `"pypdfium2": ("infrastructure/goodnotes", "infrastructure/schedule/pdf.py")`.
   The comment above it is extended: GoodNotes keeps its subtree; inside the schedule
   plane exactly one module may import the engine.
2. A private helper `_allowed(where: str, entry: str) -> bool` returns
   `where == entry or where.startswith(f"{entry}/")`, and `_entries(value)` returns
   `(value,)` for a `str`, the tuple otherwise.
3. `test_a_confined_dependency_is_imported_only_where_it_belongs` asserts
   `any(_allowed(where, e) for e in _entries(subtree))`; the failure message lists every
   allowed entry.
4. `test_every_confined_dependency_is_actually_used_there` asserts, for **each** entry of
   **each** root, at least one importer matches it (so neither `pypdfium2` allowance can be
   an unused hole), and every importer matches some entry.
5. No other entry, list, or test in the file changes;
   `test_the_derivation_prohibits_nothing_the_package_legitimately_uses` (the
   `third_party == {...}` assertion) is unchanged because `pypdfium2` is already in it.

Prove-red (section 10.6): add `import pypdfium2` to
`src/my_pa/infrastructure/schedule/full_profile.py` → rule 3 fails naming that file;
temporarily remove the import from `pdf.py` → rule 4 fails naming the unused entry.

### 2.3 PDFium API actually used (verified in both venvs)

Verified by reading `pypdfium2.raw` argtypes in `~/my-pa/.venv` (5.13.0) and
`/tmp/m1-floor` (5.0.0); every name below exists with identical argtypes at both.

| Purpose | Call | Notes |
|---|---|---|
| open | `pypdfium2.PdfDocument(data: bytes, password=None)` | raises `PdfiumError` with `.err_code` (`raw.FPDF_ERR_PASSWORD` = 4, `raw.FPDF_ERR_FORMAT` = 3, measured at both versions); `data` must be `bytes` (a `str` is a path) |
| encryption | `raw.FPDF_GetSecurityHandlerRevision(doc.raw)` | `-1` means unencrypted; an RC4 rev-2 file with an empty user password **opens** and returns 2 (measured) |
| page count | `len(doc)` (`FPDF_GetPageCount`) | page tree only; no content parse |
| page size without loading | `raw.FPDF_GetPageSizeByIndexF(doc.raw, i, byref(FS_SIZEF))` | checked for every page before any page loads |
| page | `doc[i]` → `PdfPage`; `raw.FPDFPage_GetRotation(page.raw)`; `page.close()` | |
| text page | `page.get_textpage()` → `PdfTextPage`; `.close()` | required by `FPDFTextObj_GetText` |
| objects | `raw.FPDFPage_CountObjects`, `raw.FPDFPage_GetObject`, `raw.FPDFPageObj_GetType` (`FPDF_PAGEOBJ_TEXT`, `FPDF_PAGEOBJ_FORM`) | top level only; forms see below |
| form XObject | `raw.FPDFFormObj_CountObjects`, `raw.FPDFFormObj_GetObject` | used only to count nested objects and detect nested text (section 5.2 V8) |
| text | `raw.FPDFTextObj_GetText(obj, textpage, buf, n)` | returns byte length of UTF-16LE including a 2-byte NUL |
| font | `raw.FPDFTextObj_GetFont(obj)`, `raw.FPDFFont_GetBaseFontName(font, buf, n)` | NUL-terminated bytes, decoded `latin-1` (lossless) |
| size | `raw.FPDFTextObj_GetFontSize(obj, byref(c_float))` | the `Tf` size; matrix scale is separate |
| bounds | `raw.FPDFPageObj_GetBounds(obj, &l, &b, &r, &t)` | page space, glyph-tight (measured: depends on the font program — section 6.6) |
| matrix | `raw.FPDFPageObj_GetMatrix(obj, byref(FS_MATRIX))` | `a b c d e f` |

Not called: rendering (`FPDF_RenderPage*`, `PdfPage.render`), `init_forms`/
`FPDFDOC_InitFormFillEnvironment`, attachments, bookmarks, links, actions, annotations,
`PdfTextPage.get_text_range`/character APIs, `FPDFPageObj_GetRotatedBounds`,
`PdfPage.get_objects`. The installed PDFium builds report empty feature flags
(`PDFIUM_INFO.flags == ()`, origin `pdfium-binaries`), i.e. no V8 and no XFA.

---

## 3. Module layout and public symbols

### 3.1 Files (6 source modules)

| Module | Layer | May import | Contents |
|---|---|---|---|
| `src/my_pa/domain/schedule/__init__.py` | domain | stdlib, `my_pa.domain.schedule.*` | re-exports the public names of `model` and `canonical`; no logic |
| `src/my_pa/domain/schedule/model.py` | domain | stdlib only | closed enums, parse-result records, text/ID normalization, date/duration grammars, outcome derivation, `stable_link_candidates` |
| `src/my_pa/domain/schedule/canonical.py` | domain | stdlib, `model` | canonical JSON, `cpm-full-cells-v1`, SHA-256 |
| `src/my_pa/infrastructure/schedule/__init__.py` | infrastructure | `full_profile` | re-exports `parse_full_schedule`, `P6_FULL_V1`, `PRODUCTION_LIMITS`, `ScheduleParseLimits`; no logic |
| `src/my_pa/infrastructure/schedule/pdf.py` | infrastructure | stdlib, `pypdfium2`, `my_pa.domain.schedule` | the only PDFium code: open, validate container, extract `PdfTextObject`s under caps and budget |
| `src/my_pa/infrastructure/schedule/full_profile.py` | infrastructure | stdlib, `my_pa.domain.schedule`, `my_pa.infrastructure.schedule.pdf` | frozen profile, limits, exclusion, rows, cells, classification, hierarchy, identity, `parse_full_schedule` |

Dependency direction: `infrastructure/schedule → domain/schedule`; nothing in `domain`,
`contracts`, `application`, `adapters` or `bootstrap` imports `infrastructure/schedule` in
S5a (WP-03's job handler will). `full_profile.py` reaches PDFium only through `pdf.py`.
No module in either package imports `logging`, calls `print`, opens files, reads the
environment, or imports `my_pa.infrastructure.persistence`, `my_pa.application`,
`my_pa.adapters`, `my_pa.bootstrap` or `my_pa.contracts` (section 10.1 scope guard).

### 3.2 How WP-01 reuses this without rework

WP-01 adds persistence-facing members to `src/my_pa/domain/schedule/model.py`
(`SchedulePublicationRole`, `ScheduleBaselineKind`, `ScheduleParserRunStatus`, records
with IDs) and maps `ParsedScheduleRow` field-for-field onto `schedule_rows` columns: the
S5a enums carry the exact R2 §43.2 member names and string values, the four-state
iff-invariant is already enforced in the records, `cell_evidence` is already the
`cpm-full-cells-v1` canonical object bounded at 16 KiB, `warning_codes` is already bounded
at 16, `hierarchy_path` at 32, `row_ordinal` is already the stable 1-based order, and
`parent_row_ordinal` maps to `parent_row_id` by the same run's ordinal→ID map.
`stable_link_candidates` is the identity gate's input. No S5a symbol needs renaming.

### 3.3 Domain symbols (`src/my_pa/domain/schedule/model.py`)

All enums are `enum.StrEnum` (repository idiom, e.g. `src/my_pa/domain/record_events.py`)
with lower-snake values equal to the member name lowercased; declaration order below is the
canonical sort order.

| Symbol | Members / signature | Intent |
|---|---|---|
| `ScheduleRowType` | `PROJECT_SUMMARY, WBS_SUMMARY, ACTIVITY, MILESTONE, AMBIGUOUS` | R2 §43.2 exact |
| `ScheduleCellState` | `PUBLISHED_VALUE, PUBLISHED_BLANK, EXTRACTION_FAILED, AMBIGUOUS` | R2 §17.2 exact |
| `ScheduleIssueSeverity` | `WARNING, ERROR` | R2 exact |
| `ScheduleFieldCode` | `ACTIVITY_ID, ACTIVITY_NAME, ORIGINAL_DURATION, REMAINING_DURATION, START, FINISH, HIERARCHY` | R2 exact |
| `ScheduleIssueCode` | the 23 R2 §43.2 members in R2 order: `SOURCE_VERSION_CHANGED, SOURCE_TOO_LARGE, UNSUPPORTED_MEDIA_TYPE, CORRUPT_PDF, ENCRYPTED_PDF, IMAGE_ONLY_PDF, UNSUPPORTED_LAYOUT, PAGE_METADATA_MISMATCH, EXPECTED_DATA_DATE_MISMATCH, HEADER_SIGNATURE_MISMATCH, HEADER_OD_OCCLUDED, DUPLICATE_TEXT_OBJECT_COLLAPSED, OVERLAPPING_CELL_TEXT, ROW_WRAP_UNSUPPORTED, ACTIVITY_LIKE_ROW_MISSING_ID, DUPLICATE_ACTIVITY_ID, INVALID_DATE, INVALID_DURATION, AMBIGUOUS_CELL, HIERARCHY_AMBIGUOUS, BOUNDS_EXCEEDED, PARSER_EXCEPTION, PROCESSING_BUDGET_EXCEEDED` | `SOURCE_VERSION_CHANGED` is defined (closed set) but never emitted by the parser |
| `SchedulePublicationStatus` | `QUEUED, PROCESSING, COMPLETE, PARTIAL, REVIEW_REQUIRED, FAILED` | R2 exact; the parser emits only the 4 terminal members |
| `ISSUE_SEVERITY: Mapping[ScheduleIssueCode, ScheduleIssueSeverity]` | `WARNING` for `HEADER_OD_OCCLUDED`, `DUPLICATE_TEXT_OBJECT_COLLAPSED`; `ERROR` for every other code | total, exhaustive (test) |
| `ScheduleBox` | frozen slots dataclass `x0: int, y0: int, x1: int, y1: int` | PDF-space millipoints (section 6.2); `x0 <= x1`, `y0 <= y1` enforced |
| `ScheduleCellFragment` | `raw: str, box: ScheduleBox, font_base_name: str, font_size_mpt: int` | one source text object's evidence |
| `ScheduleCellEvidence` | `field: ScheduleFieldCode, state: ScheduleCellState, text: str \| None, fragments: tuple[ScheduleCellFragment, ...]` | `text` is the normalized concatenation; `None` iff no fragments |
| `ScheduleDurationCell` | `state: ScheduleCellState, value: Decimal \| None` | `value is not None` iff `state is PUBLISHED_VALUE`; value `>= 0`, exponent quantized to `-3` |
| `ScheduleDateCell` | `state: ScheduleCellState, value: date \| None, marker: str \| None` | value iff `PUBLISHED_VALUE`; `marker in (None, "*")`; marker only with a value |
| `ScheduleParseIssue` | `code, severity, page_number: int \| None, row_ordinal: int \| None, field: ScheduleFieldCode \| None` | severity must equal `ISSUE_SEVERITY[code]` |
| `ParsedScheduleRow` | `row_ordinal: int` (1-based), `page_number: int` (1-based), `physical_line_ordinal: int` (1-based within page), `row_type`, `indent_level: int \| None`, `parent_row_ordinal: int \| None`, `hierarchy_path: tuple[str, ...] \| None`, `published_activity_id: str \| None`, `activity_name: str \| None`, `original_duration: ScheduleDurationCell`, `remaining_duration: ScheduleDurationCell`, `start: ScheduleDateCell`, `finish: ScheduleDateCell`, `box: ScheduleBox`, `page_width_mpt: int`, `page_height_mpt: int`, `cells: tuple[ScheduleCellEvidence, ...]`, `warning_codes: tuple[ScheduleIssueCode, ...]` | invariants in section 6.1 |
| `ScheduleParseCounts` | `pages, rows, project_summaries, wbs_summaries, activities, milestones, ambiguous, chart_objects_excluded, watermark_objects_excluded, duplicate_objects_collapsed, issues, warnings` (all `int`) | derived, never independently set |
| `ScheduleParseResult` | `parser_name: str, parser_version: str, profile_id: str, profile_version: int, document_sha256: str, document_size_bytes: int, outcome: SchedulePublicationStatus, published_schedule_title: str \| None, data_date: date \| None, run_date: date \| None, counts: ScheduleParseCounts, rows: tuple[ParsedScheduleRow, ...], issues: tuple[ScheduleParseIssue, ...]` | `outcome` in the 4 terminal members; `FAILED` ⇒ `rows == ()` |
| `normalize_activity_id(raw: str) -> str` | `unicodedata.normalize("NFC", raw).strip()` | R2 §16.2: NFC + surrounding whitespace only; case, punctuation, internal whitespace, `.1` preserved |
| `normalize_display_text(raw: str) -> str` | NFC, then every run of `str.isspace()` characters → one ASCII space, then strip | names, labels, metadata, header anchors |
| `parse_profile_date(token: str) -> tuple[date, str \| None] \| None` | grammar of section 4.7; `None` for any grammar or calendar failure | |
| `parse_profile_duration(token: str) -> Decimal \| None` | grammar of section 4.8 | |
| `derive_outcome(issues, rows) -> SchedulePublicationStatus` | section 5.13 | pure |
| `stable_link_candidates(result) -> tuple[ParsedScheduleRow, ...]` | `ACTIVITY`/`MILESTONE` rows in `row_ordinal` order when `outcome in {COMPLETE, PARTIAL}`, else `()` | WP-01 canonicalization input; golden linkage (section 9) |

### 3.4 Canonical symbols (`src/my_pa/domain/schedule/canonical.py`)

| Symbol | Intent |
|---|---|
| `CELLS_SCHEMA: Final = "cpm-full-cells-v1"` | R2 §18.6 |
| `RESULT_SCHEMA: Final = "cpm-full-parse-result-v1"` | S5a |
| `cell_evidence_object(row) -> dict[str, object]` | section 6.3 shape |
| `cell_evidence_bytes(row) -> bytes` | canonical bytes of that object (bounded at 16,384) |
| `parse_result_object(result) -> dict[str, object]` | section 6.4 |
| `canonical_json_bytes(obj) -> bytes` | section 6.5 rules |
| `parse_result_sha256(result) -> str` | lowercase hex SHA-256 of `canonical_json_bytes(parse_result_object(result))` |

### 3.5 Infrastructure symbols (R2 §43.4 and helpers)

| Symbol | Module | Signature-level intent |
|---|---|---|
| `PdfTextObject` | `pdf.py` | frozen slots dataclass: `page_number: int, object_ordinal: int` (0-based top-level index), `text: str` (raw decoded), `font_base_name: str` (raw, may carry a subset prefix), `font_size_mpt: int`, `box: ScheduleBox`, `matrix: tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]` (exact `Decimal(float)` of `a b c d e f`); property `normalized_box(page)` per R2 §12.3 |
| `PdfPageText` | `pdf.py` | `page_number, width_mpt, height_mpt, objects: tuple[PdfTextObject, ...]` |
| `PdfDocumentText` | `pdf.py` | `page_count: int, pages: tuple[PdfPageText, ...]` |
| `ScheduleParseRefusal(Exception)` | `pdf.py` | carries `code: ScheduleIssueCode` only; `str(exc) == code.value`; never source text |
| `ParseBudget` | `pdf.py` | `clock: Callable[[], float], deadline: float \| None`; `.checkpoint()` raises `ScheduleParseRefusal(PROCESSING_BUDGET_EXCEEDED)` when `deadline is not None and clock() > deadline` |
| `extract_pdf_text_objects(data: bytes, *, limits: ScheduleParseLimits, budget: ParseBudget) -> PdfDocumentText` | `pdf.py` | validation V1–V9 of section 5.2; raises `ScheduleParseRefusal` |
| `FullScheduleProfile` | `full_profile.py` | frozen dataclass holding every section 4 constant; one instance `P6_FULL_V1` |
| `ScheduleParseLimits` | `full_profile.py` | frozen dataclass of section 4.10; `PRODUCTION_LIMITS`; `__post_init__` refuses any field greater than its production value (limits may only tighten — D-24) |
| `PageZones` | `full_profile.py` | `page_number, metadata_objects, table_objects, chart_excluded: int, watermark_excluded: int` |
| `exclude_profile_non_data(page: PdfPageText, profile) -> PageZones` | `full_profile.py` | section 5.3; raises `UNSUPPORTED_LAYOUT` for a rotated table object |
| `collapse_duplicate_objects(objects) -> tuple[tuple[PdfTextObject, ...], tuple[PdfTextObject, ...]]` | `full_profile.py` | section 5.4; returns (kept, collapsed) |
| `ProfileValidation` | `full_profile.py` | `title, data_date, run_date` (coherent values or `None`), `issues` |
| `validate_full_profile(zones: Sequence[PageZones], profile, *, expected_data_date: date \| None) -> ProfileValidation` | `full_profile.py` | V11–V13 of section 5.2; raises `UNSUPPORTED_LAYOUT` for a page-1 classification failure |
| `PdfPhysicalRow` | `full_profile.py` | `page_number, physical_line_ordinal, seed: PdfTextObject, objects: tuple[PdfTextObject, ...]` (x-ordered), `box: ScheduleBox` |
| `group_table_rows_by_overlap(objects, *, page_number, profile) -> tuple[PdfPhysicalRow, ...]` | `full_profile.py` | section 5.5 |
| `AssignedRow` | `full_profile.py` | the physical row plus six `ScheduleCellEvidence` and per-row issue drafts |
| `assign_full_cells(row: PdfPhysicalRow, profile) -> AssignedRow` | `full_profile.py` | sections 5.6–5.8 |
| `classify_full_row(assigned: AssignedRow, previous: PdfPhysicalRow \| None, profile) -> ClassifiedRow` | `full_profile.py` | sections 5.9–5.10 |
| `reconstruct_full_hierarchy(rows: Sequence[ClassifiedRow], profile, limits) -> tuple[HierarchyAssignment, ...]` | `full_profile.py` | section 5.11 |
| `parse_full_schedule(data: bytes, *, expected_data_date: date \| None = None, limits: ScheduleParseLimits = PRODUCTION_LIMITS, clock: Callable[[], float] = time.monotonic, deadline: float \| None = None) -> ScheduleParseResult` | `full_profile.py` | the only entry point; never raises for document-caused conditions (section 7.5) |

No parser registry, plugin system, profile registry or future-profile abstraction (R2 §43.6).

---

## 4. Frozen profile `p6_full_v1`

### 4.1 Units and identity

- Geometry is held as **integer millipoints** (1 pt = 1000 mpt). Conversion of every
  PDFium `c_float` value `v`: `int(Decimal(v).scaleb(3).quantize(Decimal(1),
  ROUND_HALF_EVEN))` — `Decimal(float)` is exact, so the conversion is platform-independent.
  Every geometric comparison below is integer arithmetic. "Centre" comparisons use doubled
  coordinates (`x0 + x1` against `2 * boundary`) so no division occurs.
- `PROFILE_ID = "p6_full_v1"`, `PROFILE_VERSION = 1`, `DOCUMENT_TYPE = "full"`.
- `PARSER_NAME = "cpm-workbench-full-parser"`, `PARSER_VERSION = "1"`. The version
  changes whenever identical bytes could produce a different `ScheduleParseResult`
  (R2 §43.6); a golden digest change without a version bump fails review.

### 4.2 Page geometry

| Constant | Value |
|---|---|
| `PAGE_WIDTH_MPT` | 1,224,000 |
| `PAGE_HEIGHT_MPT` | 792,000 |
| `PAGE_SIZE_TOLERANCE_MPT` | 500 (inclusive, each dimension, measured from `FPDF_GetPageSizeByIndexF`) |
| page rotation | `FPDFPage_GetRotation == 0` |

### 4.3 X grid (R2 §12.4, exact)

| Constant | Points | mpt | Band (half-open on the right) |
|---|---|---|---|
| `TABLE_LEFT` | 37.0 | 37,000 | — |
| `ID_NAME` | 131.0 | 131,000 | `ACTIVITY_ID`: `[37.0, 131.0)` |
| `NAME_OD` | 435.5 | 435,500 | `ACTIVITY_NAME`: `[131.0, 435.5)` |
| `OD_RD` | 467.5 | 467,500 | `ORIGINAL_DURATION`: `[435.5, 467.5)` |
| `RD_START` | 498.5 | 498,500 | `REMAINING_DURATION`: `[467.5, 498.5)` |
| `START_FINISH` | 559.0 | 559,000 | `START`: `[498.5, 559.0)` |
| `CHART_BOUNDARY` | 615.5 | 615,500 | `FINISH`: `[559.0, 615.5)`; chart: `x-centre >= 615.5` |

The merged summary-label region is `[37.0, 435.5)`. An object's band is decided by its
x-centre only: `2 * left <= x0 + x1 < 2 * right`. A table object with x-centre `< 37.0` is
out-of-grid (section 5.7).

### 4.4 Y zones (PDF space, y up; fixed values for R2's "approximately" — D-04)

| Zone | Rule on y-centre `cy = (y0 + y1) / 2` | Value | Justification |
|---|---|---|---|
| data zone | `95.0 <= cy <= 700.0` | 95,000 / 700,000 mpt | R2 §12.5 "approximately 95..700"; fixed at R2's stated endpoints, inclusive, because R2's figures are the measured data-centre envelope and no measured header/footer centre is reported inside it |
| column-header band | `700.0 < cy <= 724.0` | 724,000 mpt | **Synthetic assumption.** R2 gives no header y; 24 pt above the data zone holds one header line at the corpus's 7 pt body size with margin; WP-04 evaluation must confirm (U-02) |
| top metadata band | `cy > 724.0` | — | **Synthetic assumption** (U-02) |
| footer zone | `cy < 95.0` | — | complement of the data zone below it |

### 4.5 Header anchors, metadata and page signature (synthetic assumptions — D-04, U-02)

R2 names the required evidence (Layout, Data Date, Run Date, title, `Summary Page N of M`,
six column headers) but not the token shapes. S5a freezes these shapes; every match is
against `normalize_display_text(text)` of one whole near-horizontal text object.

| Evidence | Where | Exact rule |
|---|---|---|
| column anchors | column-header band, x-centre `< 615.5` | exactly one object per column whose text equals `Activity ID`, `Activity Name`, `OD`, `RD`, `Start`, `Finish` respectively and whose x-centre lies in that column's band (section 4.3); no other column-header-band object with x-centre `< 615.5` |
| OD occlusion exception (R2 §12.5) | column-header band | the `OD` anchor is absent, **exactly one** other object has x-centre in the OD band and text matching the date grammar (section 4.7), and the other 5 anchors are exact with no further extra object → warning `HEADER_OD_OCCLUDED` (page ref, field `ORIGINAL_DURATION`) |
| Layout | top metadata band | regex `^Layout: (?P<value>\S.{0,198})$`; exactly one per page |
| Data Date | header or footer zone | regex `^Data Date: (?P<date>\S+)$` with `date` passing section 4.7 **without** a marker; exactly one per page |
| Run Date | header or footer zone | regex `^Run Date: (?P<date>\S+)$`, same date rule; exactly one per page |
| title | top metadata band, x-centre `< 615.5` | every object there not matched by Layout/Data Date/Run Date, ordered by `y1` descending then `x0` ascending, joined by one space; result length 1..300 characters |
| page signature | footer zone | regex `^Summary Page (?P<n>[1-9][0-9]{0,2}) of (?P<m>[1-9][0-9]{0,2})$`; exactly one per page |

Other footer/legend objects are ignored. Header/footer objects are never rows.

### 4.6 Watermark signature (R2 §12.6; fixed values — D-04)

An object is the profile watermark only if **all** hold:

| Property | Value |
|---|---|
| normalized text | exactly `DRAFT` |
| bbox | each edge within ±12.0 pt (12,000 mpt, inclusive) of `(309.0, 244.0, 872.0, 503.0)` |
| rotation | `theta = degrees(atan2(b, a))` from the matrix, `5.0 <= abs(theta) <= 85.0` |
| zone | y-centre in the data zone and x-centre `< 615.5` (it is examined after the chart rule) |

Justification: R2 states the corpus bbox "roughly" to whole points; ±12 pt covers that
rounding while staying far smaller than the bbox itself (563 × 259 pt), so no ordinary
table text can match. R2 records no angle; `[5°, 85°]` excludes near-horizontal text
(section 4.6.1 uses 0.573°) and near-vertical text. WP-04 must confirm against the corpus
(U-03). An ordinary horizontal `DRAFT` cell or footer object is never excluded
(R2-AC-011).

#### 4.6.1 Near-horizontal

`NEAR_HORIZONTAL_TAN = Decimal("0.01")` (≈ 0.573°). With the exact `Decimal` matrix:
near-horizontal iff `a > 0 and d > 0 and abs(b) <= 0.01 * a and abs(c) <= 0.01 * d`.

### 4.7 Date grammar

`^(?P<dd>0[1-9]|[12][0-9]|3[01])-(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-(?P<yy>[0-9]{2})(?P<marker>\*)?$`
(case-sensitive). Year = `2000 + int(yy)` (century window 2000..2099, R2 §12.11). The
calendar must be valid (`datetime.date` construction); `31-Feb-27` fails. `*` is kept as the
raw marker with no meaning. Start vs Finish comes only from the band.

### 4.8 Duration grammar

`^(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,3})?$` → `Decimal(token).quantize(Decimal("0.001"))`
(fits `NUMERIC(12,3)`; non-negative by grammar). Anything else — a sign, a thousands
separator, more than 3 decimals, a leading zero such as `05`, a date token — fails. No unit
conversion (R2 §12.12).

### 4.9 Grouping, cell, hierarchy thresholds and measured-corpus evidence

| Constant | Value | Source |
|---|---|---|
| `ROW_OVERLAP_RATIO` | `1/2`, applied as `2 * intersection >= min(seed_height, obj_height)` | R2 §12.8 |
| `ROW_MAX_SPAN_MPT` | 16,000 | R2 §12.8 |
| `WRAP_PITCH_MPT` | 10,000 (strictly less) | R2 §12.9 |
| `DUPLICATE_EDGE_TOLERANCE_MPT` | 250 (inclusive, every edge) | R2 §12.7 |
| `CELL_OVERLAP_MPT` | 250 (x-intersection strictly greater ⇒ overlapping) | S5a, equal to the duplicate tolerance (D-04) |
| `INDENT_TOLERANCE_MPT` | 1,500 | R2 §14.2 |
| `INDENT_MIN_SEPARATION_MPT` | 3,000 (= 2 × tolerance) | S5a (D-20) |
| `REGULAR_FONT` / `BOLD_FONT` | `"Arial"` / `"Arial,Bold"` after prefix normalization | R2 §13.3 |
| `SUBSET_PREFIX` | `^[A-Z]{6}\+` removed once | R2 §12.1 |
| `TITLE_MAX_CHARS` | 300 | S5a |

`MEASURED_CORPUS: Final` (documented evidence, not a runtime input; R2 §13.1, §13.4):
`pages = 86`, `table_rows = 3408`, `summary_rows = 443`, `id_bearing_rows = 2964`,
`missing_id_rows = 1`, `page_width_pt = 1224`, `page_height_pt = 792`,
`missing_id_page = 21`, `od_header_occluded_page = 37`,
`duration_date_pages = (55, 58, 61)` (summary RD, activity RD, activity OD respectively),
`expected_outcome = REVIEW_REQUIRED`, `indent_centroids_pt = (52.57, 56.78, 60.30, 63.88,
67.70, 71.53, 75.35, 79.08)`. The invariant `443 + 2964 + 1 == 3408` is asserted. No
filename, byte count, digest, title or token of the corpus is encoded.

### 4.10 Limits (R2 §36) — `PRODUCTION_LIMITS`

| Field | Value | On excess |
|---|---|---|
| `max_bytes` | 16,777,216 (16 MiB) | `SOURCE_TOO_LARGE` (D-07) |
| `max_pages` | 250 | `BOUNDS_EXCEEDED` |
| `max_text_objects` | 250,000 (text objects incl. nested in forms, whitespace-only included) | `BOUNDS_EXCEEDED` |
| `max_page_objects` | 1,000,000 (all object types incl. nested) | `BOUNDS_EXCEEDED` (D-08) |
| `max_text_chars` | 2,000,000 (sum of `len(text)` over decoded text objects) | `BOUNDS_EXCEEDED` |
| `max_rows` | 25,000 | `BOUNDS_EXCEEDED` |
| `max_issues` | 50,000 (after de-duplication) | `BOUNDS_EXCEEDED` |
| `max_row_warnings` | 16 | `BOUNDS_EXCEEDED` |
| `max_hierarchy_depth` | 32 (indent clusters; also bounds `hierarchy_path`) | `BOUNDS_EXCEEDED` |
| `max_cell_evidence_bytes` | 16,384 (canonical bytes of one row's `cpm-full-cells-v1`) | `BOUNDS_EXCEEDED` |
| `max_form_depth` | 4 (form XObject nesting walked for counting) | `UNSUPPORTED_LAYOUT` |
| `PROCESSING_BUDGET_SECONDS` | 240 (module constant, not a field: WP-03's handler computes `deadline` from it) | `PROCESSING_BUDGET_EXCEEDED` |

---

## 5. Algorithm

### 5.1 Pipeline

`parse_full_schedule`: (1) SHA-256 and size of `data`; (2) V1–V9 in `pdf.py`;
(3) per page `exclude_profile_non_data` (V10) and `collapse_duplicate_objects`;
(4) `validate_full_profile` (V11–V13); (5) per page `group_table_rows_by_overlap`,
cumulative row cap; (6) `assign_full_cells`, `classify_full_row` with the previous
physical row on the same page; (7) `reconstruct_full_hierarchy` over the whole publication;
(8) identity checks (section 5.12); (9) issue de-duplication, ordering, caps;
(10) `derive_outcome`; (11) row bounds (warnings, cell-evidence bytes); (12) result.
`budget.checkpoint()` runs: after V2, after open, before each page load, after every 1,000
objects within a page, after extraction, before each page's grouping, before hierarchy,
before step (9).

### 5.2 Validation order

| # | Check | Result |
|---|---|---|
| V1 | `len(data) > max_bytes` | `SOURCE_TOO_LARGE`, before any PDFium call |
| V2 | `not data.startswith(b"%PDF-")` (empty included) | `UNSUPPORTED_MEDIA_TYPE`, before any PDFium call |
| V3 | open; `PdfiumError.err_code == FPDF_ERR_PASSWORD` | `ENCRYPTED_PDF` (no password is ever supplied) |
| V3' | open fails otherwise | `CORRUPT_PDF` |
| V4 | `FPDF_GetSecurityHandlerRevision != -1` | `ENCRYPTED_PDF` (D-13) |
| V5 | page count `0` (defensive: measured, PDFium already refuses an empty page tree at V3') | `UNSUPPORTED_LAYOUT`; `> max_pages` → `BOUNDS_EXCEEDED`, before any page load |
| V6 | every page's size by index (no load) within section 4.2 | else `UNSUPPORTED_LAYOUT` |
| V7 | per page, after load: rotation `0` (catches `/Rotate 180`, whose size by index is unswapped) | else `UNSUPPORTED_LAYOUT` |
| V8 | per page: cumulative object counts after `FPDFPage_CountObjects` and each form walk (before reading any text of that page); a form XObject containing a text object at any depth, or nesting deeper than `max_form_depth` → `UNSUPPORTED_LAYOUT` (D-09); cumulative characters after each object; UTF-16 decode is strict and failure → `PARSER_EXCEPTION` (D-17) | caps → `BOUNDS_EXCEEDED` |
| V9 | no decoded text object with non-whitespace text in the whole document | `IMAGE_ONLY_PDF` |
| V10 | zone partition; a remaining table object not near-horizontal | `UNSUPPORTED_LAYOUT` |
| V11 | page 1: column anchors exact or OD-occluded; Layout, Data Date, Run Date, title, signature each present exactly once and valid; signature `n == 1` | else `UNSUPPORTED_LAYOUT` (classification, R2 §11 — D-12) |
| V12 | pages 2..N: column anchors exact or OD-occluded | else `HEADER_SIGNATURE_MISMATCH` (page ref, error) |
| V13 | every page: each metadata item present once; normalized title, layout value, Data Date, Run Date equal page 1's; `n == page ordinal`; `m == page count` | else `PAGE_METADATA_MISMATCH` (page ref, one per page) |
| V13' | `expected_data_date is not None` and the coherent Data Date differs | `EXPECTED_DATA_DATE_MISMATCH` (no page ref); skipped when Data Date is incoherent |

V1–V10 failures stop the parse: outcome `FAILED`, `rows == ()`, `issues ==` the one
refusal issue (D-16). Whitespace-only text objects count toward caps (V8) and are then
dropped; they are never evidence.

### 5.3 Exclusion order per page (R2 §§12.4–12.6)

For each kept text object, in object order:

1. **Chart:** y-centre in the data zone and `x0 + x1 >= 2 * 615,500` → excluded,
   counted in `chart_objects_excluded`, contributes nothing anywhere.
2. **Header/footer:** y-centre outside the data zone → metadata set (near-horizontal
   objects only participate in section 4.5 matching; others are ignored). Never rows.
3. **Watermark:** matches section 4.6 → excluded, counted in
   `watermark_objects_excluded`.
4. **Rotation:** any remaining (table) object not near-horizontal → `UNSUPPORTED_LAYOUT`.

### 5.4 Duplicate collapse (R2 §12.7)

Separately within the metadata set and within the table set of each page: two objects are
exact duplicates iff `normalize_display_text(text)` is equal, the prefix-normalized base
font is equal, and every bbox edge differs by `<= 250` mpt. Process objects in
`object_ordinal` order; an object that duplicates an earlier **kept** object is collapsed
into it. Each collapse emits `DUPLICATE_TEXT_OBJECT_COLLAPSED` (warning; page ref; for the
table set, the row ref and field of the kept object once rows exist; for the metadata set,
no row and no field) and increments `duplicate_objects_collapsed`. Non-identical overlap is
never collapsed (section 5.7).

### 5.5 Physical row grouping (R2 §12.8)

Per page, over kept table objects:

1. Unassigned pool sorted by `(-y1, x0, object_ordinal)`.
2. Seed = first unassigned object. Seed interval `[s0, s1] = [seed.y0, seed.y1]`.
3. Each other unassigned object `o`, in pool order, joins iff
   `min_h = min(s1 - s0, o.y1 - o.y0) > 0` and
   `2 * max(0, min(s1, o.y1) - max(s0, o.y0)) >= min_h`. The comparison is always to the
   **seed** interval, never to the growing union (no chaining).
4. Row objects ordered by `(x0 + x1, -y1, object_ordinal)`. Row box = union of members.
5. Repeat until the pool is empty. Rows are emitted in seed order;
   `physical_line_ordinal` counts from 1 per page; `row_ordinal` counts from 1 across the
   publication in (page, physical line) order and never changes (R2 §12.13).
6. A row whose box height `y1 - y0 > 16,000` is `AMBIGUOUS` with `AMBIGUOUS_CELL`
   (field `None`) (D-22).

### 5.6 Font classes

`font_class(o)`: strip `SUBSET_PREFIX` once from `font_base_name`; `REGULAR` if the result
equals `Arial`, `BOLD` if it equals `Arial,Bold`, else `OTHER`. Style is profile evidence
only (R2 §13.3).

### 5.7 Cell assignment (R2 §12.10)

1. Each row object goes to the band containing its x-centre (section 4.3). An object with
   x-centre `< 37.0` → row `AMBIGUOUS` + `AMBIGUOUS_CELL` (field `None`). An `OTHER`-font
   object → row `AMBIGUOUS` + `AMBIGUOUS_CELL` (field = its band).
2. Within one cell, fragments are ordered by `x0`. Two fragments **overlap** iff their
   x-intersection `> 250` mpt. Any overlap → cell state `AMBIGUOUS`, `text` = the
   x-ordered join, issue `OVERLAPPING_CELL_TEXT` (field). Never last-write-wins.
3. Otherwise the cell text is the fragments' `normalize_display_text(raw)` joined with one
   ASCII space; no fragments → `PUBLISHED_BLANK`, `text = None`.
4. `cells` always holds 6 entries in `ScheduleFieldCode` order without `HIERARCHY`; each
   fragment keeps raw text, box, raw base-font name and size (R2 §18.6).

Left-label interpretation (merged region `[37.0, 435.5)`), with `IDr`/`IDb` = regular/bold
objects in the ID band and `Nr`/`Nb` = regular/bold objects in the Name band:

| Case | Condition | Cells |
|---|---|---|
| ID-bearing | `IDr` non-empty, `IDb` and `Nb` empty | `ACTIVITY_ID` = `IDr`; more than 1 fragment → cell state `AMBIGUOUS` (D-11; the issue is emitted by section 5.10 rule 5); `ACTIVITY_NAME` = `Nr` |
| summary | `IDr` and `Nr` empty, `IDb ∪ Nb` non-empty | `ACTIVITY_ID` = blank; `ACTIVITY_NAME` = all of `IDb ∪ Nb` as **one** merged label, x-ordered — never split at 131.0 (R2 §13.4.1) |
| no label | all four empty | `ACTIVITY_ID`, `ACTIVITY_NAME` blank |
| name only | `Nr` non-empty, `IDr`, `IDb`, `Nb` empty | `ACTIVITY_ID` blank; `ACTIVITY_NAME` = `Nr` (activity-like, no identity) |
| mixed | any other combination (regular with bold in the left region) | both left cells keep their band fragments with state `AMBIGUOUS`; row `AMBIGUOUS` + `AMBIGUOUS_CELL` (field `None`) |

OD/RD/Start/Finish accept `REGULAR` or `BOLD` fragments (D-23).

### 5.8 Dates and durations in cells

- OD/RD: text parses by section 4.8 → `PUBLISHED_VALUE`; populated but failing →
  `EXTRACTION_FAILED` + `INVALID_DURATION` (field). A date token in an OD/RD band is
  parsed as a duration and therefore fails (R2 §12.12, R2-AC-017); columns never shift.
- Start/Finish: section 4.7 → `PUBLISHED_VALUE` with marker; failing →
  `EXTRACTION_FAILED` + `INVALID_DATE` (field).
- An `AMBIGUOUS` cell has no typed value.

### 5.9 Row wrap (R2 §12.9)

Checked before classification. Physical row `R` (not the first row on its page) with
predecessor `P` on the same page is a wrap line iff `P.box.y1 - R.box.y1 < 10,000` and `R`
has no object in the ID, OD, RD, Start or Finish bands and at least 1 object in the Name
band. Then `R` is `AMBIGUOUS` + `ROW_WRAP_UNSUPPORTED`; `P` is unchanged; nothing is
concatenated. There is no cross-page detection or continuation.

### 5.10 Classification precedence (R2 §15)

Applied to each non-wrap row after section 5.7 (first match wins):

| # | Condition | `row_type` | Issue |
|---|---|---|---|
| 1 | already `AMBIGUOUS` by sections 5.5–5.7 | `AMBIGUOUS` | as recorded |
| 2 | ID-bearing with `ACTIVITY_ID` and `ACTIVITY_NAME` both `PUBLISHED_VALUE`; OD and RD `PUBLISHED_VALUE` equal to 0; exactly one of Start/Finish `PUBLISHED_VALUE` and the other `PUBLISHED_BLANK` | `MILESTONE` | — |
| 3 | ID-bearing with ID and name `PUBLISHED_VALUE`, OD and RD both `PUBLISHED_VALUE` equal to 0, without the exact date pattern | `AMBIGUOUS` | `AMBIGUOUS_CELL` (field `None`) |
| 4 | ID-bearing with ID and name `PUBLISHED_VALUE` | `ACTIVITY` | cell issues stay on their cells |
| 5 | ID-bearing with the ID or the name cell not `PUBLISHED_VALUE` (blank or `AMBIGUOUS`) | `AMBIGUOUS` | `AMBIGUOUS_CELL` (field = the first of `ACTIVITY_ID`, `ACTIVITY_NAME` that is not `PUBLISHED_VALUE`) |
| 6 | summary label present and its cell not `AMBIGUOUS` | `WBS_SUMMARY` (section 5.11 may promote one to `PROJECT_SUMMARY`) | — |
| 7 | "no label" with at least one of OD/RD/Start/Finish populated, or "name only" | `AMBIGUOUS` | `ACTIVITY_LIKE_ROW_MISSING_ID` (`ACTIVITY_ID`) |
| 8 | anything else | `AMBIGUOUS` | `AMBIGUOUS_CELL` (field `None`) |

For `AMBIGUOUS` rows `published_activity_id = None` and `activity_name = None`; typed
OD/RD/Start/Finish are still parsed as evidence. For summaries `published_activity_id =
None` and `activity_name` = the label text. For ID-bearing rows `published_activity_id =
normalize_activity_id(raw ID)`. A summary's failed OD/RD/date never turns it into an
activity; chart text never completes a missing identity (it was excluded in section 5.3).

### 5.11 Hierarchy (R2 §14)

1. Eligible rows: `WBS_SUMMARY` and `ACTIVITY`/`MILESTONE`. Left edge = the ID fragment's
   `x0` (ID-bearing) or the merged label's minimum `x0` (summary). `AMBIGUOUS` rows get
   `indent_level = None`, `parent_row_ordinal = None`, `hierarchy_path = None`, no
   hierarchy issue.
2. Cluster the publication-wide multiset of left edges: sort ascending; the first value
   opens a cluster; a value joins the open cluster iff `value - cluster_first <= 1,500`,
   else it opens a new one (fixed seed, no chaining). Centroid = exact mean
   (`fractions.Fraction`). More than `max_hierarchy_depth` clusters → `BOUNDS_EXCEEDED`.
3. `indent_level` = 0-based rank of the row's own cluster. Two adjacent centroids closer
   than 3,000 mpt make every row of both clusters indeterminate (D-20).
4. Walk rows in `row_ordinal` order with one stack across pages (a page break never resets
   it). Summary at level `L`: pop entries with level `>= L`; parent = top of stack or none;
   push. Activity/milestone at level `L`: parent = nearest stack entry with level `< L`;
   stack unchanged.
5. A row is **determinate** iff its own cluster is determinate, and either it is a summary
   at level 0 with no parent, or it has a parent that is itself determinate. Indeterminate
   rows: `parent_row_ordinal = None`, `hierarchy_path = None`, `indent_level` kept when its
   cluster is determinate else `None`, issue `HIERARCHY_AMBIGUOUS` (field `HIERARCHY`).
   Indeterminacy therefore propagates to descendants (D-19); no parent is ever invented.
6. Determinate rows: `hierarchy_path` = the ancestor summaries' `activity_name`s, root
   first, excluding the row itself (root summary: `()`).
7. `PROJECT_SUMMARY`: the first summary in `row_ordinal` order iff it is determinate at
   level 0; every other summary stays `WBS_SUMMARY`. Repeated label text creates distinct
   rows and is never used for identity or promotion.

### 5.12 Identity checks (R2 §16)

- Every `ACTIVITY_LIKE_ROW_MISSING_ID` is an identity failure.
- Duplicate ID: among `ACTIVITY`/`MILESTONE` rows, any `published_activity_id` occurring
  more than once (exact, case-sensitive, after `normalize_activity_id`) emits
  `DUPLICATE_ACTIVITY_ID` (field `ACTIVITY_ID`) on **every** occurrence; no winner.

### 5.13 Outcome derivation (R2 §§10.6, 21, 22)

`derive_outcome` (first match wins):

| # | Condition | Outcome |
|---|---|---|
| 1 | a V1–V10 refusal, any `BOUNDS_EXCEEDED`, `PARSER_EXCEPTION` or `PROCESSING_BUDGET_EXCEEDED` | `FAILED` (no rows) |
| 2 | any of `PAGE_METADATA_MISMATCH`, `EXPECTED_DATA_DATE_MISMATCH`, `HEADER_SIGNATURE_MISMATCH`, `ROW_WRAP_UNSUPPORTED`, `ACTIVITY_LIKE_ROW_MISSING_ID`, `DUPLICATE_ACTIVITY_ID`, or any row with `row_type == AMBIGUOUS` | `REVIEW_REQUIRED` (D-10) |
| 3 | any `INVALID_DATE`, `INVALID_DURATION`, `OVERLAPPING_CELL_TEXT`, `AMBIGUOUS_CELL`, `HIERARCHY_AMBIGUOUS` | `PARTIAL` |
| 4 | otherwise (warnings `HEADER_OD_OCCLUDED`, `DUPLICATE_TEXT_OBJECT_COLLAPSED` do not downgrade) | `COMPLETE` |

`published_schedule_title`, `data_date`, `run_date` are page 1's values only when that item
is coherent across every page, else `None` (D-18).

### 5.14 Issues: scope, de-duplication, order, bounds

| Code | Severity | Page | Row | Field |
|---|---|---|---|---|
| `SOURCE_TOO_LARGE`, `UNSUPPORTED_MEDIA_TYPE`, `CORRUPT_PDF`, `ENCRYPTED_PDF`, `IMAGE_ONLY_PDF`, `BOUNDS_EXCEEDED`, `PARSER_EXCEPTION`, `PROCESSING_BUDGET_EXCEEDED`, `EXPECTED_DATA_DATE_MISMATCH` | error | — | — | — |
| `UNSUPPORTED_LAYOUT` | error | page when page-specific | — | — |
| `PAGE_METADATA_MISMATCH`, `HEADER_SIGNATURE_MISMATCH` | error | yes | — | — |
| `HEADER_OD_OCCLUDED` | warning | yes | — | `ORIGINAL_DURATION` |
| `DUPLICATE_TEXT_OBJECT_COLLAPSED` | warning | yes | table: yes | table: kept object's field |
| row codes (`OVERLAPPING_CELL_TEXT`, `ROW_WRAP_UNSUPPORTED`, `ACTIVITY_LIKE_ROW_MISSING_ID`, `DUPLICATE_ACTIVITY_ID`, `INVALID_DATE`, `INVALID_DURATION`, `AMBIGUOUS_CELL`, `HIERARCHY_AMBIGUOUS`) | error | yes | yes | per section 5 |

Issues are de-duplicated on `(code, page_number, row_ordinal, field)` and sorted by
`(page_number or 0, row_ordinal or 0, code declaration index, field declaration index or
-1)`. More than `max_issues` → `BOUNDS_EXCEEDED`. A row's `warning_codes` = the distinct
codes of all issues referencing it (both severities, the R2 column name is kept), in
declaration order; more than `max_row_warnings` → `BOUNDS_EXCEEDED`. A row whose
`cell_evidence_bytes` exceed `max_cell_evidence_bytes` → `BOUNDS_EXCEEDED`.
`hierarchy_path` length is bounded by the cluster cap.

### 5.15 Time bounds, deterministically

The parser never reads wall time itself: `parse_full_schedule` builds
`ParseBudget(clock, deadline)`; with `deadline=None` no budget applies (S5a has no handler;
WP-03 passes `handler_entry + PROCESSING_BUDGET_SECONDS`). Tests inject a fake clock
(a closure over a counter) that returns `0.0` for the first `k` calls and `10.0` after,
with `deadline=1.0`, so the refusal is proven at the first checkpoint (`k = 0`) and at a
mid-extraction checkpoint (`k` chosen to land inside page 2) with no sleeps and no timing
assertions.

---

## 6. Output model and canonical bytes

### 6.1 Record invariants (enforced in `__post_init__`, `ValueError` with a fixed message)

- Typed duration/date `value is not None` iff `state is PUBLISHED_VALUE` (R2 §17.2,
  R2-AC-023); duration `>= 0` with exponent `-3`; marker only `"*"` and only with a value.
- `ACTIVITY`/`MILESTONE`: `published_activity_id` and `activity_name` non-empty.
  Summaries: `published_activity_id is None`, `activity_name` non-empty. `AMBIGUOUS`:
  both `None`.
- `parent_row_ordinal < row_ordinal` when present; `len(hierarchy_path) <= 32`;
  `len(warning_codes) <= 16` and strictly increasing in declaration order;
  `len(cells) == 6` in field order.
- `ScheduleParseResult`: `FAILED` ⇒ `rows == ()`; `rows` strictly increasing
  `row_ordinal` from 1; counts equal those derived from `rows`/`issues`;
  `document_sha256` 64 lowercase hex.

### 6.2 Number and text representation

| Value | Canonical form |
|---|---|
| geometry (mpt int) | decimal string with exactly 3 decimals, sign only when negative: `"598.600"` |
| normalized row box (R2 §12.3) | `x0/W, (H - y1)/H, x1/W, (H - y0)/H` with `W`/`H` the page's measured mpt; `Decimal` division under `localcontext(prec=28)`, quantized to `0.000001` `ROUND_HALF_EVEN`, string `"0.042956"` |
| font size | 3-decimal string from mpt |
| duration | `str(value)` of the quantized `Decimal` (`"12.000"`) |
| date | ISO `YYYY-MM-DD` |
| enum | its string value |
| absent | JSON `null` |
| raw text | exactly as decoded (not normalized); normalized fields are NFC |

No `float` reaches the canonical object.

### 6.3 `cpm-full-cells-v1`

```json
{"schema":"cpm-full-cells-v1",
 "cells":{"activity_id":{"state":"published_value","text":"SYN-1000",
   "fragments":[{"raw":"SYN-1000","bbox":["52.570","598.600","80.570","604.900"],
                 "font":"Arial","font_size":"7.000"}]},
  "activity_name":{...},"original_duration":{...},"remaining_duration":{...},
  "start":{...},"finish":{...}}}
```

`bbox` is PDF space `[x0, y0, x1, y1]`; `font` is the raw base-font name (subset prefix
kept as provenance). It never holds page text beyond the row's own fragments (R2 §18.6).

### 6.4 Result object

Keys: `schema` (`cpm-full-parse-result-v1`), `parser_name`, `parser_version`, `profile_id`,
`profile_version`, `document_sha256`, `document_size_bytes`, `outcome`,
`published_schedule_title`, `data_date`, `run_date`, `counts` (section 3.3 names),
`rows`, `issues`. Row keys: `row_ordinal`, `page_number`, `physical_line_ordinal`,
`row_type`, `indent_level`, `parent_row_ordinal`, `hierarchy_path`,
`published_activity_id`, `activity_name`, `original_duration` `{state, value}`,
`remaining_duration`, `start` `{state, value, marker}`, `finish`, `bbox_pdf` (4 strings),
`bbox_normalized` (4 strings), `cell_evidence` (section 6.3 object), `warning_codes`.
Issue keys: `code`, `severity`, `page_number`, `row_ordinal`, `field`. Rows in
`row_ordinal` order; issues in section 5.14 order.

### 6.5 Canonical JSON

`json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
allow_nan=False).encode("ascii")`, no trailing newline. `ensure_ascii=True` makes the
bytes ASCII regardless of platform encoding; strict UTF-16 decoding (V8) guarantees no
lone surrogate reaches it. Digest: SHA-256 of those bytes, lowercase hex.

### 6.6 Cross-run and cross-platform determinism

- Integer-millipoint geometry, `Decimal` derived quantities, sorted output, no `float`
  formatting, no `dict`/`set` iteration order dependence, no clock, no randomness.
- PDFium text bounds are glyph-tight and depend on the font program: measured, a
  non-embedded `/TrueType /BaseFont /Arial` gives `x1 = 70.800` for an 8-character string
  where the advance-width sum gives `71.136`, and an unknown font name gives different
  bounds again — i.e. the substituted system font decides the box. The fixture fonts are
  therefore **Type3** fonts (section 8.2) whose glyph boxes come from `d1` in the PDF
  itself; measured at 5.0.0 and 5.13.0, bounds equal the analytic values exactly
  (`SYN-1000` at 7 pt from (40, 600): `[40.000, 598.600, 71.136, 604.900]`). Goldens are
  therefore expected byte-identical on macOS and Linux and at the floor; the
  `dependency-floor` and `validate` FAST shards prove it on Linux (D-14).
- The canonical result deliberately excludes PDFium/`pypdfium2` versions; a PDFium change
  that alters output fails the goldens, which is the intended signal.

---

## 7. Security of PDF parsing (hostile input)

| Concern | Control in S5a |
|---|---|
| byte bombs | V1 size check before any PDFium call (test monkeypatches `PdfDocument` to fail if called) |
| page bombs | V5 page count from the page tree, V6 sizes by index, both before any page load |
| object/char bombs | V8 cumulative caps checked after each page's object count and form walk (before reading that page's text) and after each object's text — the parse stops early, never after materializing the document |
| decompression bombs | **Residual.** PDFium inflates a page's content streams inside `FPDF_LoadPage`; one hostile page can allocate before any cap is read, and the cooperative budget cannot pre-empt C code. Mitigations in S5a: the 16 MiB input cap, per-page object/char caps, the budget between pages, and handle release. Subprocess isolation with `RLIMIT_AS` is **out of scope** for S5a (it changes the worker's process model, which is WP-03's, and is not cheap to make deterministic in tests); recorded as U-05 for WP-03 |
| active content | no JavaScript (PDFium builds have no V8: `PDFIUM_INFO.flags == ()`), no form environment (`init_forms` never called), no actions/links/annotations/attachments read, no rendering, no network or file I/O (PDFium has none on this path; input is in-memory bytes) |
| encryption | no password is ever passed; V3 `FPDF_ERR_PASSWORD` and V4 revision `!= -1` both refuse, so an empty-user-password file is refused too |
| resource cleanup | `PdfTextPage.close()`, `PdfPage.close()`, `PdfDocument.close()` each in `finally`, innermost first, on every path including refusals and budget expiry (test counts closes) |
| error mapping | `PdfiumError` → `CORRUPT_PDF`/`ENCRYPTED_PDF`; strict decode failure → `PARSER_EXCEPTION`; any other `Exception` escaping steps (3)–(12) of section 5.1 → `PARSER_EXCEPTION`; `MemoryError` re-raised (transient, WP-03 retries); results carry codes only |
| redaction | `ScheduleParseRefusal` text is its code; no module in either schedule package imports `logging` or calls `print`; no exception chains source text (`raise ... from None` on mapping); the scope guard enforces the import/print rule |

### 7.5 Exception contract of `parse_full_schedule`

Returns a `ScheduleParseResult` for every input `bytes`; raises only `MemoryError`,
`KeyboardInterrupt`/`SystemExit`, and `TypeError` for a non-`bytes` argument (programming
error).

### 7.6 `pyproject.toml` comment (range unchanged)

The `pypdfium2` paragraph keeps its GoodNotes text and adds: current use also reads text
objects (text, base-font name, font size, bounds, matrix) from an admitted Full-Schedule
PDF in `src/my_pa/infrastructure/schedule/pdf.py` without rendering; the 5.0 floor also
carries every raw `FPDFTextObj_*`, `FPDFFont_GetBaseFontName`, `FPDFPageObj_GetBounds`,
`FPDFPageObj_GetMatrix`, `FPDF_GetPageSizeByIndexF` and
`FPDF_GetSecurityHandlerRevision` function the schedule parser calls (the
`PdfTextObj`/`PdfFont` helpers are 5.x-later and deliberately unused); security surface
adds hostile admitted PDFs bounded by section 7 of this contract. Nothing else in the file
changes.

---

## 8. Synthetic fixtures (WP-00)

### 8.1 Generator

`tests/fixtures/schedule_full_pdf.py` — stdlib only (`hashlib`, `dataclasses`, `decimal`,
`datetime`, `math`, `json`, `pathlib`, `argparse`); no PDF library. It mirrors
`_assemble_pdf` in `src/my_pa/infrastructure/goodnotes/pdf.py`: `%PDF-1.7`, objects in a
fixed order, a classic xref, a trailer; no `/Info`, no timestamps, no random `/ID` (the
encrypted fixture uses the fixed `/ID` `000102…0f`). Content-stream numbers are written
from `Decimal`/`str` with fixed formatting, never `repr(float)`. Each fixture is a pure
function `build(family, variant) -> FixtureCase` returning `pdf: bytes`,
`expected_data_date`, `limits` (production unless the variant tightens), `truth`
(section 8.4). Fixtures are generated at test time; **no PDF is committed**.

### 8.2 Fonts and text objects

- Two Type3 fonts per document: `/BaseFont /Arial` and `/BaseFont /Arial,Bold`; the
  `subset` variant uses `/BaseFont /SYNABC+Arial,Bold` (6 capitals + `+`). Each: one
  shared `CharProc` per code 32..126 drawing a box with `500 0 0 -200 500 700 d1`,
  `/FontMatrix [0.001 0 0 0.001 0 0]`, `/Widths` all 500, `/Encoding /Differences`, and a
  `/ToUnicode` identity CMap for 0x20..0x7E (measured to round-trip text exactly at both
  PDFium versions). An `OTHER`-font variant uses `/BaseFont /Courier`.
- Analytic bounds of a string of `n` characters at size `s` from origin `(x, y)`:
  `[x, y - 0.2s, x + 0.5ns, y + 0.7s]`. Body size 7 pt, level-1 summaries 8 pt, the project
  summary 10 pt, title 12 pt.
- One text object per `BT … Tf … Tm … Tj ET` block; rotation by a `Tm` with `cos/sin`
  written to 6 decimals.

### 8.3 Common synthetic page frame

| Item | Placement (baseline origin, PDF space) |
|---|---|
| title | `Synthetic Project Schedule`, bold 12 pt at (40, 760) |
| layout | `Layout: SYN Full`, regular 7 pt at (40, 740) |
| Data Date / Run Date | `Data Date: 04-May-26` at (300, 740); `Run Date: 11-May-26` at (900, 740) |
| column anchors | regular 7 pt at y 710, x0 = 38.88, 134.52, 446.63, 478.20, 520.50, 576.97 (R2 §13.2 starts) |
| chart timescale header | `May 26` at (700, 710) (header zone, right of the chart boundary) |
| rows | first baseline 685, pitch 15 pt, 40 rows maximum per page (last baseline 100) |
| row cells | ID at the level's indent x; name x0 134.0; OD right edge 465.0; RD right edge 496.0; Start x0 501.0; Finish x0 562.0 |
| indent x by level | R2 measured centroids 52.57, 56.78, 60.30, 63.88, 67.70, 71.53, 75.35, 79.08 |
| chart duplicates | name at x0 620.0 and dates at x0 700.0 on the row baseline |
| footer | `Synthetic legend` at (40, 60); `Summary Page n of m` at (1000, 40) |
| neutral content | IDs `SYN-1000`…, names `Synthetic activity 001`…, labels `Synthetic Phase A`… |

### 8.4 Independent ground truth

Every case carries `truth`: the generator's intended rows (type, page, ID or `None`, name
or `None`, OD/RD/Start/Finish state and value, marker, parent intended row, expected issue
codes per row and per page, expected outcome). Truth is written by the generator from its
own layout plan, never from parser output, and is what the section 10 gate tests compare
against. Goldens (section 9) only pin bytes.

### 8.5 The 26 families (R2 §37)

`P` = pages; outcome codes: C complete, P partial, R review_required, F failed.

| # | Family (variants) | P | Key rows / construction | Expected | Proves (R2 §38 / §39 / AC) |
|---|---|---|---|---|---|
| 1 | `full_valid_2p` (`base`, `subset_prefix`) | 2 | project summary L0, 2 WBS L1, activities L2, a Start-only and a Finish-only milestone (OD 0, RD 0), one date with `*`; `subset_prefix` uses the prefixed bold base name | C | row types, milestone pattern, marker, prefix normalization; ID precision/recall, name/date/duration accuracy; AC-009, 018 |
| 2 | `full_merged_summary_label` | 1 | bold L1 label from x0 52.57 whose box crosses 131.0, OD/RD/dates aligned | C | §38 merged label never an ID; no summary→activity promotion; AC-012 |
| 3 | `full_summary_vertical_offset` | 1 | 10 pt bold project label with centre 3.0 pt above the 7 pt numeric cells' centre (overlap ratio ≈ 0.74) | C | §38 one row by overlap; AC-012 |
| 4 | `full_summary_zero_zero` | 1 | blank-ID bold summary with OD `0`, RD `0`, one Start date | C | stays `WBS_SUMMARY`, never milestone; AC-018 |
| 5 | `full_nested_hierarchy` | 3 | all 8 indent levels; repeated label `Synthetic Phase A` at 2 positions; page 2 opens with activities whose parent summary is on page 1 | C | exact parents/paths, stack carry, repeated labels distinct; hierarchy gate; AC-019 |
| 6 | `full_header_occluded_od` | 2 | page 2 OD anchor replaced by `04-May-26` with x0 436.0 | C + `HEADER_OD_OCCLUDED` (page 2) | §38 parses and warns only; AC-014 |
| 7 | `full_header_mismatch` (`later_page`, `first_page`) | 2 | `RD` and `Start` anchors missing on page 2 / page 1 | R + `HEADER_SIGNATURE_MISMATCH` / F `UNSUPPORTED_LAYOUT` | AC-014 refusal |
| 8 | `full_missing_activity_id` | 2 | page 2 row with OD/RD/Start/Finish only, plus its name in the chart region | R + `ACTIVITY_LIKE_ROW_MISSING_ID` | §38 invents no ID/name, links nothing; missing-ID gate; AC-016, 021 |
| 9 | `full_duplicate_activity_id` | 1 | two activities `SYN-1100` with different names | R + `DUPLICATE_ACTIVITY_ID` ×2 | no winner; zero links; AC-021 |
| 10 | `full_duration_date_in_rd` | 1 | a summary and an activity with `15-Mar-28` at RD x0 467.6 | P + `INVALID_DURATION` ×2 | §38 cells stay; coercion gate = 0; AC-017 |
| 11 | `full_duration_date_in_od` | 1 | an activity with `15-Mar-28` at OD x0 436.0 | P + `INVALID_DURATION` | same; AC-017 |
| 12 | `full_invalid_date` | 1 | `31-Feb-27` in Finish; `30-Foo-26` in Start | P + `INVALID_DATE` ×2 | coercion gate; AC-023 |
| 13 | `full_chart_duplicates` | 1 | every row's name/dates repeated at x0 620/700 | C, `chart_objects_excluded` > 0 | §38 zero chart fragments; chart gate; AC-010 |
| 14 | `full_draft_watermark` (`signature`, `off_signature`) | 1 | rotated (7°) `DRAFT` with box inside the tolerance crossing the table; an activity named `DRAFT`; `off_signature` shifts the box 20 pt | C, `watermark_objects_excluded == 1`, `DRAFT` name kept / F `UNSUPPORTED_LAYOUT` | §38 watermark zero fragments; watermark gate; AC-011 |
| 15 | `full_duplicate_text_object` | 1 | one activity name drawn 3 times: identically and 0.2 pt shifted; on another activity the OD token `5` drawn twice 0.3 pt apart | P: `DUPLICATE_TEXT_OBJECT_COLLAPSED` ×2 (warnings) and `OVERLAPPING_CELL_TEXT` ×1 on that OD cell | §38 exact duplicate collapses; tolerance boundary |
| 16 | `full_overlapping_cell_text` (`od`, `id`) | 1 | `5` and `8` overlapping in OD / two overlapping regular IDs | P + `OVERLAPPING_CELL_TEXT` / R (row `AMBIGUOUS`) | §38 non-identical overlap ambiguous; no last-write-wins |
| 17 | `full_ambiguous_hierarchy` (`close_centroids`, `orphan`) | 1 | edges at 52.57 and 54.40 / a level-2 activity before any summary | P + `HIERARCHY_AMBIGUOUS` | every ambiguity explicit; AC-019 |
| 18 | `full_row_wrap_unsupported` | 1 | an activity followed by a regular name-only line 8 pt lower | R + `ROW_WRAP_UNSUPPORTED` | wrap-concatenation gate = 0; AC-013 |
| 19 | `full_multi_page_86_equivalent` | 86 | 54 pages × 40 rows + 32 pages × 39 rows = 3408 rows: 443 summaries (1 project + 442 WBS), 2964 ID-bearing (2900 activities, 32 Start-only and 32 Finish-only milestones), 1 missing-ID row on page 21; OD occlusion on page 37; date tokens in a summary RD (page 55), an activity RD (page 58), an activity OD (page 61); watermark and chart duplicates on every page | R; counts equal `MEASURED_CORPUS`; issues: 1 missing-ID, 1 occlusion warning, 3 invalid-duration | corpus-shape reproduction; performance target; AC-037 |
| 20 | `corrupt_pdf` (`garbage`, `not_a_pdf`, `empty`) | — | `%PDF-1.7\n` + 8 × `\x00garbage\n` (measured `FPDF_ERR_FORMAT`) / `not a pdf` / `b""` | F `CORRUPT_PDF` / F `UNSUPPORTED_MEDIA_TYPE` ×2 | AC-007 |
| 21 | `encrypted_pdf` (`user_password`, `empty_user_password`) | 1 | RC4 40-bit, standard handler R2, `/P -44`, stdlib RC4 + `hashlib.md5(usedforsecurity=False)`; user `synthetic-user` / empty, owner `synthetic-owner` | F `ENCRYPTED_PDF` ×2 (measured: error 4 / opens with revision 2) | AC-007 |
| 22 | `image_only_pdf` | 1 | correct page size, one 1×1 DeviceGray image XObject and a filled path, no text | F `IMAGE_ONLY_PDF` | AC-007 |
| 23 | `wrong_page_size` (`letter`, `rotated`, `zero_pages`) | 1 | 612×792 / `/Rotate 90` (measured: size by index reads 792×1224, so V6 refuses) / empty `/Kids` (measured: PDFium refuses to open) | F `UNSUPPORTED_LAYOUT` ×2 / F `CORRUPT_PDF` | AC-009 |
| 24 | `page_metadata_mismatch` (`data_date`, `run_date`, `title`, `page_number`, `page_total`) | 2 | page 2 differs in the named item | R + `PAGE_METADATA_MISMATCH` (page 2) | AC-015 |
| 25 | `expected_data_date_mismatch` (`mismatch`, `match`) | 2 | `full_valid_2p` bytes with `expected_data_date` 2026-05-05 / 2026-05-04 | R + `EXPECTED_DATA_DATE_MISMATCH` / C | AC-015 |
| 26 | `bounds_exceeded` (`bytes`, `pages`, `text_objects`, `page_objects`, `chars`, `rows`, `issues`, `row_warnings`, `hierarchy_depth`, `cell_evidence`, `form_text`, `time_first`, `time_mid`) | varies | `bytes`: valid bytes padded after `%%EOF` to 16 MiB + 1 (production); `pages`: 251 blank frame-size pages (production); the others use tightened `ScheduleParseLimits` on small documents (e.g. `max_rows=3` with 4 rows); `form_text`: a form XObject holding a text object; `time_*`: fake clock per section 5.15 | F `SOURCE_TOO_LARGE` / `BOUNDS_EXCEEDED` / `UNSUPPORTED_LAYOUT` / `PROCESSING_BUDGET_EXCEEDED` | AC-007; production limit values pinned separately by `test_production_limits_are_the_r2_bounds` |

Decision on bounds variants: the two caps checked before PDFium does page work (bytes,
pages) use **production** values on real oversized inputs (cheap: padding and blank pages);
caps that would need large documents use **injected tighter** limits, which is sound
because (a) `ScheduleParseLimits` can only tighten, (b) the same comparison code runs with
either instance, and (c) the production values are pinned as constants by their own test.

Test-time targets (measured basis: extracting 27,520 Type3 text objects from an 86-page
synthetic file took 0.65 s at 5.13.0 and 0.76 s at 5.0.0 on the development Mac): family
19 generate + parse under 10 s; all S5a test modules together under 30 s in one FAST
process. A miss is reported, not hidden behind `slow` (section 10.4).

---

## 9. Golden schema

- Path: `tests/fixtures/schedule_full_goldens/<family>__<variant>.json` (`base` when a
  family has no variants); one file per case.
- Content (pretty JSON: `indent=2`, `sort_keys=True`, `ensure_ascii=True`, trailing
  newline):
  `family`, `variant`, `generator_version` (int, starts at 1),
  `parse_inputs` (`expected_data_date` ISO or `null`; `limits` `"production"` or the
  tightened field map), `pdf_sha256`, `pdf_size_bytes`, `result_sha256`, `summary`
  (`outcome`, `counts`, `issue_counts` map code → count), `linkage`
  (`basis`: `eligible` | `review_required` | `failed`; `rows`: `[{row_ordinal,
  published_activity_id}]` from `stable_link_candidates` — empty unless `eligible`), and
  `result` (the full section 6.4 object) for every case **except** family 19 and the
  family 26 `bytes`/`pages` cases, which record `result: null` and rely on
  `result_sha256` + `summary`.
- Golden expectations are not ground truth: section 8.4 truth is compared independently.
- Regeneration is explicit only:
  `PYTHONPATH=src python -m tests.fixtures.schedule_full_pdf write-goldens` (writes every
  file, prints each path and digest). No test calls the writer.
- Not silently regenerated:
  1. `tests/unit/test_schedule_full_goldens.py` holds `GOLDEN_FILE_SHA256: Final` — the
     SHA-256 of every golden file's bytes; a regenerated file changes its digest and fails
     until the test file is edited in the same diff;
  2. the same module asserts the golden directory's file set equals the registered case
     set;
  3. `tests/architecture/test_cpm_full_parser_scope.py` asserts by `ast` that no module
     under `tests/` other than the generator references `write_goldens`;
  4. tests open goldens read-only and compare `canonical_json_bytes(result)` to
     `canonical_json_bytes(golden["result"])` and `parse_result_sha256(result)` to
     `result_sha256`, plus `pdf_sha256` to a freshly generated PDF's digest.

---

## 10. Test plan and crosswalk

### 10.1 Modules (5 new test modules, all FAST, unmarked)

| Module | Holds |
|---|---|
| `tests/unit/test_schedule_model.py` | domain enums, records, normalization, grammars, outcome, canonical bytes |
| `tests/unit/test_schedule_full_profile.py` | profile constants and pure algorithm over hand-built `PdfTextObject` lists (no PDF) |
| `tests/unit/test_schedule_full_pdf.py` | PDFium extraction, hostile input, caps, budget, cleanup |
| `tests/unit/test_schedule_full_goldens.py` | every case vs truth and golden; determinism; pins; §38/§39 |
| `tests/architecture/test_cpm_full_parser_scope.py` | scope guards: generic extraction unchanged, schedule import allowlist, no logging/print, crosswalk names exist, no writer call, neutrality denylist |

Plus the edit to `tests/architecture/test_scope_and_hygiene.py` (section 2.2). Fixture
support (not counted as test modules): `tests/fixtures/schedule_full_pdf.py`,
`tests/fixtures/schedule_full_goldens/`.

Neutrality denylist (in the scope module, as SHA-256 of lowercased word tokens, so the
guard itself carries no proprietary string): `26049e25810bd7c6d59e3a8192e93d98c7b398f37061b36b64b58f795fc3d555`,
`7d8a34ddb21729dc73215f8125fcd0d58e32dc938e91978c5f6f6bdb1f88831d`,
`08bf7134d662b64c5241c42be9e9deb9a7644b35af95cce700e71503403a0e35`,
`d037ceb3377a6d6d9f9dbb49f1fa467f9ca87dfae3579542304a02b38280bf62`; the scan covers
`src/my_pa/domain/schedule/`, `src/my_pa/infrastructure/schedule/`, the generator and the
golden directory, tokenizing on `[A-Za-z0-9]+`.

### 10.2 R2 §38 assertions → tests (`tests/unit/test_schedule_full_goldens.py`)

| §38 assertion | Test |
|---|---|
| golden row fields (page, ordinals, type, indent, parent, path, ID, name, OD/RD, Start/Finish + marker, bboxes, cell evidence, warnings, outcome) | `test_every_case_matches_its_golden` (parametrized) |
| canonicalization linkage / NULL linkage | `test_linkage_is_eligible_only_for_complete_or_partial` |
| merged bold label is one summary, never an ID | `test_merged_summary_label_is_never_an_activity_id` |
| vertical-offset summary is one row | `test_vertical_offset_summary_is_one_row` |
| OD occlusion parses and warns only | `test_occluded_od_header_parses_and_only_warns` |
| missing-ID row: issue, no invented ID/name, no link | `test_missing_id_row_invents_nothing_and_links_nothing` |
| OD/RD date tokens stay in duration cells | `test_duration_date_tokens_stay_in_their_cells` |
| chart duplicates contribute zero fragments | `test_chart_duplicates_contribute_zero_fragments` |
| watermark contributes zero fragments | `test_watermark_contributes_zero_fragments` |
| exact duplicate collapses; non-identical overlap ambiguous | `test_exact_duplicate_collapses_and_overlap_is_ambiguous` |

### 10.3 R2 §39 gates (parser-decidable) → tests

All gates are computed in `test_quality_gates_hold_over_every_case` (parser output vs
section 8.4 truth across all cases) with one assertion per gate so a failure names it.

| Gate | Target | Assertion name inside the test |
|---|---|---|
| Activity-ID precision / recall / exact match | 100% | `id_precision`, `id_recall`, `id_exact` |
| false merge / spurious linkage (via `stable_link_candidates`) | 0 | `stable_false_merge`, `spurious_link` |
| dropped valid ID-bearing row | 0% | `dropped_id_rows` |
| summary→activity/milestone promotion | 0 | `summary_promotion` |
| name exact normalized match | 100% | `name_exact` |
| Start/Finish, OD/RD accuracy | 100% | `date_accuracy`, `duration_accuracy` |
| invalid token coerced to a value | 0 | `coerced_invalid` |
| row-type accuracy | 100% | `row_type_accuracy` |
| parent/path accuracy; ambiguity represented | 100% | `hierarchy_accuracy`, `hierarchy_ambiguity_explicit` |
| chart object admitted | 0 | `chart_admitted` |
| watermark admitted | 0 | `watermark_admitted` |
| wrapped row concatenated | 0 | `wrap_concatenated` |
| missing/duplicate ID linked | 0 | `bad_identity_linked` |
| provenance page/row/cell-bbox match (source version/PDF hash: hash only in S5a) | 100% | `provenance_match` |
| links on `review_required` | 0 | `review_required_links` |

### 10.4 R2 §45 criteria in parser scope → tests

| AC | Test(s) |
|---|---|
| 001 (neutral naming, fixture part) | `test_cpm_full_parser_scope.py::test_schedule_files_carry_no_denylisted_token` |
| 005 | `test_cpm_full_parser_scope.py::test_generic_extraction_still_excludes_pdf` |
| 007 | `test_schedule_full_pdf.py::test_byte_cap_is_checked_before_pdfium_opens`, `test_page_cap_is_checked_before_any_page_loads`, `test_object_and_char_caps_stop_before_the_next_page`, `test_corrupt_encrypted_and_image_only_fail_closed`, `test_budget_refuses_at_first_and_mid_extraction_checkpoints`; `test_schedule_full_profile.py::test_production_limits_are_the_r2_bounds`, `test_limits_can_only_be_tightened` |
| 008 | `test_scope_and_hygiene.py` rules of section 2.2 |
| 009 | `test_schedule_full_profile.py::test_profile_constants_are_frozen`; family 23 via `test_every_case_matches_its_golden` |
| 010–019 | section 10.2 tests plus `test_schedule_full_profile.py::test_rows_group_by_seed_overlap_not_centre_distance`, `test_grouping_compares_to_the_fixed_seed`, `test_overlap_ratio_boundary_is_one_half`, `test_cell_band_boundaries_on_every_grid_line`, `test_classification_precedence`, `test_row_wrap_requires_pitch_below_10pt`, `test_hierarchy_clusters_and_stack`, `test_hierarchy_ambiguity_propagates`, `test_watermark_signature_and_ordinary_draft` |
| 020 (parser part) | `test_schedule_model.py::test_activity_id_normalization_is_nfc_and_trim_only` |
| 021 | `test_schedule_full_profile.py::test_missing_and_duplicate_ids_force_review_required`; `test_linkage_is_eligible_only_for_complete_or_partial` |
| 023 | `test_schedule_model.py::test_cell_value_is_present_iff_published_value` |
| 024 (parser part) | `provenance_match` gate; `test_schedule_model.py::test_cell_evidence_shape_is_cpm_full_cells_v1` |
| 034 (parser part) | `test_schedule_full_pdf.py::test_refusals_carry_codes_only`; scope `test_schedule_modules_neither_log_nor_print` |
| 037 | `test_quality_gates_hold_over_every_case`, `test_86_page_equivalent_reproduces_the_measured_corpus`, `test_generated_pdfs_are_deterministic_and_pinned`, `test_golden_files_are_pinned_by_digest` |

Other required tests: `test_schedule_model.py::test_closed_enums_have_exactly_the_r2_members`,
`test_issue_severity_is_total`, `test_canonical_bytes_are_sorted_ascii_and_stable`,
`test_canonical_numbers_are_fixed_decimal_strings`, `test_outcome_derivation_table`;
`test_schedule_full_pdf.py::test_handles_are_closed_on_every_exit`,
`test_extraction_is_identical_across_runs`, `test_form_xobject_text_is_unsupported_layout`,
`test_undecodable_text_is_parser_exception` (monkeypatched decode input);
`test_schedule_full_goldens.py::test_golden_directory_holds_exactly_the_registered_cases`,
`test_86_page_equivalent_parse_time_is_reported` (prints the duration; asserts only the
R2 30 s parser-only ceiling). `slow` is not used: it is excluded from every CI lane.

### 10.5 Commands the implementer runs (foreground, chunked)

`ruff check .`; `ruff format --check .`; bare `mypy` in the current venv and in the floor
venv (`/tmp/m1-floor`, with `PYTHONPATH=src`); `pytest tests/unit/test_schedule_*.py
tests/architecture/test_cpm_full_parser_scope.py tests/architecture/test_scope_and_hygiene.py
tests/architecture/test_dependency_direction.py` in both venvs (the floor run proves 5.0.0
goldens); `pytest tests/architecture/test_spelled_counts_match_the_sets_they_name.py
tests/architecture/test_claimed_test_counts_match_collection.py
tests/architecture/test_readme_state_claims.py tests/architecture/test_ci_shards*.py`;
`python -m tests.ci_shard verify --lane fast --shards 3 -m "not slow and not database and
not network and not connector and not evaluation and not e2e and not recovery"`; the full
FAST selection in chunks.

### 10.6 Prove-red plan (one mutant at a time, revert after each)

| Mutant | Must fail |
|---|---|
| each of the 7 grid constants ± 1,000 mpt (7 runs) | `test_profile_constants_are_frozen` and `test_cell_band_boundaries_on_every_grid_line`; the 131.0 and 615.5 mutants also fail families 2 and 13 |
| `ROW_OVERLAP_RATIO` to `3/4` | `test_overlap_ratio_boundary_is_one_half`, family 3 golden |
| `ROW_MAX_SPAN_MPT` to 30,000 | the row-span case in `test_rows_group_by_seed_overlap_not_centre_distance` |
| `CHART_BOUNDARY` to 700.0 | family 13 golden, `chart_admitted` gate |
| watermark text `DRAFT` → `DRAFTX`, or tolerance 12 → 2 pt | family 14 (`signature` becomes `UNSUPPORTED_LAYOUT`) |
| `DUPLICATE_EDGE_TOLERANCE_MPT` 250 → 100 / → 400 | family 15 (0.2 pt pair no longer collapses / 0.3 pt pair collapses) |
| `INDENT_TOLERANCE_MPT` 1,500 → 500 | family 5 golden, `hierarchy_accuracy` |
| rule: y-centre grouping with 2 pt tolerance replacing overlap | family 3, `test_rows_group_by_seed_overlap_not_centre_distance` |
| rule: union instead of fixed seed | `test_grouping_compares_to_the_fixed_seed` |
| rule: last-write-wins in a cell | family 16, `test_exact_duplicate_collapses_and_overlap_is_ambiguous` |
| rule: chart-side repair of a missing name | family 8, `test_missing_id_row_invents_nothing_and_links_nothing` |
| rule: date token in OD/RD shifted into Start | families 10–11, `coerced_invalid` |
| rule: split a bold label at 131.0 into ID + name | family 2, `test_merged_summary_label_is_never_an_activity_id` |
| rule: V1 after open | `test_byte_cap_is_checked_before_pdfium_opens` |
| rule: drop the revision check (V4) | family 21 `empty_user_password` |
| rule: concatenate a wrap line | family 18, `wrap_concatenated` |
| guard: `import pypdfium2` in `full_profile.py` | `test_a_confined_dependency_is_imported_only_where_it_belongs` |
| guard: remove the import from `pdf.py` | `test_every_confined_dependency_is_actually_used_there` |
| guard: edit 1 golden byte | `test_golden_files_are_pinned_by_digest` |
| guard: add `"application/pdf"` to `SUPPORTED_MEDIA_TYPES` | `test_generic_extraction_still_excludes_pdf` |
| guard: `import logging` in `pdf.py` | `test_schedule_modules_neither_log_nor_print` |

A mutant that leaves every test green is reported as redundancy, a masked test, or an
unreachable hazard — never as "covered".

---

## 11. Deviations from R2 and residuals

### 11.1 Deviations

| ID | R2 | S5a | Reason |
|---|---|---|---|
| D-01 | enums/records are WP-01 in `domain/schedule/model.py` | S5a creates that module with the parser-facing pure subset | the parser needs typed output now; same names/values so WP-01 extends, not renames |
| D-02 | no canonical module named | `domain/schedule/canonical.py` | canonical bytes are domain logic WP-01 reuses for JSONB |
| D-03 | two-subtree confinement | goodnotes subtree + the single module `infrastructure/schedule/pdf.py` | stricter; keeps the pure algorithm PDFium-free |
| D-04 | "approximately" zones/watermark/near-horizontal; no metadata token shapes | exact values (sections 4.4–4.6, 4.9) and synthetic token grammars | implementable and testable; corpus confirmation is WP-04 (U-02, U-03) |
| D-05 | primitive `PdfTextObj` | raw functions + repository `PdfTextObject` | `PdfTextObj` is absent at the 5.0.0 floor |
| D-06 | units unstated | integer millipoints; decimal strings in output | exact, platform-independent arithmetic and bytes |
| D-07 | bytes over bound listed under both `source_too_large` and `bounds_exceeded` | bytes → `SOURCE_TOO_LARGE`; all other caps → `BOUNDS_EXCEEDED` | one code per condition, matching the worker's fetch-cap code |
| D-08 | 250k text-object bound only | adds 1,000,000 all-object bound | path/image object bombs are otherwise unbounded |
| D-09 | forms not mentioned | text inside a form XObject → `UNSUPPORTED_LAYOUT` | nested bounds are form-space; fail closed rather than guess (U-04) |
| D-10 | ambiguous cell → partial or review by identity impact | any `AMBIGUOUS` row → `REVIEW_REQUIRED`; ambiguous non-identity cell → `PARTIAL` | an ambiguous row may hide an ID; review is the safe side |
| D-11 | concatenate fragments within a cell | ID cell with more than 1 fragment → ambiguous | identity is never assembled from pieces |
| D-12 | header failures → review | page-1 classification failure → `UNSUPPORTED_LAYOUT`; later pages → review | §11 says non-matching PDFs are unsupported |
| D-13 | "encrypted/password-required → fail" | any security handler refuses, even with an empty user password | measured: such files open silently |
| D-14 | generator unspecified | Type3 fixture fonts with `Arial`/`Arial,Bold` base names | measured: non-embedded font bounds depend on font substitution |
| D-15 | memory/time bounds enforced | decompression inside `FPDF_LoadPage` is not pre-emptible; no subprocess isolation in S5a | see U-05 |
| D-16 | failed = no accepted parse | `FAILED` results carry no rows and exactly 1 issue | deterministic, minimal |
| D-17 | — | strict UTF-16 decode; failure → `PARSER_EXCEPTION` | PostgreSQL JSONB rejects lone surrogates |
| D-18 | metadata retained after coherence | per-item `None` when incoherent | never claim a coherent value that is not |
| D-19 | ambiguity never invents a parent | indeterminacy propagates to descendants | a path through an indeterminate ancestor is not deterministic |
| D-20 | nearest-centroid assignment | own fixed-seed cluster; adjacent centroids `>= 3.0` pt apart or indeterminate | nearest-centroid can cross clusters; measured centroids are 3.52–4.21 pt apart |
| D-21 | "within <10 pt of the preceding row cluster" | top-edge pitch `< 10.0` pt with no ID/numeric/date cell | the measured row pitch (~15 pt) makes bbox-gap readings flag every row |
| D-22 | 16 pt span "may" | over-span row → `AMBIGUOUS` + `AMBIGUOUS_CELL` | R2 gives no consequence |
| D-23 | style contract for IDs/labels | numeric/date cells accept regular or bold | R2 is silent; summaries plausibly print bold numbers |
| D-24 | bounds fixed | injectable limits that may only tighten | deterministic bounds tests without giant fixtures |
| D-25 | WP-02 includes a parser-run/row persistence interface | none; `ScheduleParseResult` is the interface | S5a forbids persistence |
| D-26 | one unit test module named | 4 unit modules + 1 architecture module | separation of pure, PDFium and golden tiers |
| D-27 | parser name/version unnamed | `cpm-workbench-full-parser` / `"1"` | needed for canonical bytes |
| D-28 | duplicate collapse "before row grouping" | also within metadata objects; never chart objects | duplicated header text must not fail "exactly one" rules |
| D-29 | non-negative decimal | quantized 3 dp; 9 integer digits max; no leading zeros | `NUMERIC(12,3)` fit and one canonical form |

### 11.2 Residuals and unknowns

| ID | Item | Owner |
|---|---|---|
| U-01 | No real corpus is available: every synthetic-assumption constant (sections 4.4 bands, 4.5 grammars, 4.6 angle/tolerance) is unverified against real bytes; an export that differs fails `UNSUPPORTED_LAYOUT`/review (fail closed, R2 §51.9) | WP-04 authorized-corpus evaluation; any change bumps `PARSER_VERSION` |
| U-02 | Header/metadata token shapes and the 724 pt split are assumptions | WP-04 |
| U-03 | Watermark angle range and ±12 pt tolerance are assumptions | WP-04 |
| U-04 | Whether real exports wrap table text in form XObjects is unknown; S5a refuses | WP-04 |
| U-05 | Decompression-bomb memory inside one page load is bounded only by the 16 MiB input; subprocess/`RLIMIT_AS` isolation is a WP-03 decision | WP-03 |
| U-06 | Specialty layouts sharing the same 6 columns and metadata cannot be distinguished without real layout values; R2 already defers them | future profile package |
| U-07 | Text render mode (invisible text) is not consulted | WP-04 security review |
| U-08 | Linux identity of goldens is argued (Type3 bounds come from the file) and measured only on macOS at both PDFium versions locally; CI's Linux FAST/floor shards are the first Linux proof | S5a CI run |
| U-09 | The R2 parser-only `< 30 s` target is asserted; the worker `< 60 s` target and RSS `<= 512 MiB` are not measurable without the worker | WP-03/WP-04 |
