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

**Revision R5-1.** Design review R5 (verdict BLOCK at `33748fc1`) findings R5-F01…F15 are
resolved in place: text acquisition from the text page's attributed characters with a
deterministic suppressed-object rule (sections 2.4, 5.4), the bold-label wrap and the R2
§15.6 summary rule (5.9, 5.10), the OD overlay shape (4.5), level gaps (5.11), the
non-embedded-font residual and `engine` provenance (1.3, 6.4, 6.6), a reachable prove-red
plan (10.6), and the minor items (sections 2.1, 2.3, 4.2, 4.6, 5.2, 5.14, 6.2, 7, 11).

**Revision R5-2.** Re-review 1 (PASS_WITH_REQUIRED_CHANGES at `1fcdcacd`) findings
RR1-F01…F07 are resolved in sections 2.4, 5.3, 5.4, 5.5 (step 7), 8.2, 8.5, 10.4, 10.6
and 11.2. **Revision R5-3.** Re-review 2 findings RR2-F01…F04 are resolved in sections
5.3, 5.4, 5.5, 5.7, 5.9, 5.10, 8.5, 10.4, 10.6 and 11.

**Revision FR5 (as implemented).** Final review FR5 (BLOCK, narrow, at `2b814b8c`) is
resolved by implementation commits and recorded here: the section 5.4 step 3 cross-cell
rule is implemented with a PDFium-backed fixture (`full_duplicate_text_object` /
`cross_band`, FR5-F01); the implementation deviations found by measurement are recorded
in sections 2.3, 2.4, 3.5, 4.5, 5.1, 5.2, 5.4, 6.1, 6.2, 6.6, 7 and 11 (FR5-F03); the
reachable CropBox, per-1,000-object budget and unmapped-metadata tests are added (FR5-F02,
F04, F05); the section 10.6 "must fail" column is corrected and rows M78–M85 are added
(FR5-F06); the FR5-F07 observations are fixed (D-39, incremental form walk, character-walk
checkpoint) or recorded (section 11.2). `PARSER_VERSION` stays `"1"`: these changes alter
output only for inputs no golden contains, and no S5a result has been released or persisted.

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
`ScheduleParseResult` whose canonical bytes are identical across runs; for the **synthetic
fixtures** (whose Type3 fonts carry their own glyph boxes) they are also identical across
macOS and Linux and across `pypdfium2` 5.0.0 (floor, PDFium 143.0.7483.0) and 5.13.0
(PDFium 153.0.7999.0). For real inputs whose fonts are not embedded, geometry may depend on
the host font environment (U-10); the result therefore carries the PDFium build as
non-digested provenance (section 6.4). Every R2 §37 family has a generated fixture, independent ground truth and a
pinned golden; every parser-scope R2 §38 assertion and §39 gate has a named test; FAST,
ruff, ruff format, mypy (current and floor-pinned) and the shard partition proof are
green. Nothing is persisted or served.

---

## 2. Repository reauthentication at `787d806a` and divergences from R2

### 2.1 Table — R2 claim, repository truth, S5a decision

| # | R2 claim / assumption | Repository truth at `787d806a` | S5a decision |
|---|---|---|---|
| T-01 | Reviewed head `d6c706bb`, 178 capabilities, 47 purposes, Alembic 108 / head `7d9a450dfd07` | Head `787d806a`; Alembic head `c5260943d933` (122 revisions per `docs/architecture/00_ARCHITECTURE_INDEX.md`) | S5a touches none of these registries; nothing to rederive except module/test counts (T-14) |
| T-02 | `pypdfium2` is an existing dependency usable for schedule parsing | `pyproject.toml` declares `"pypdfium2>=5.0,<6"`; its comment block (lines 178–193) states the use as "pinned pdfium rasterizer for GoodNotes visual page identity" only, with "Floor 5.0" justified by `PYPDFIUM_INFO`/`PDFIUM_INFO` | Range unchanged. The comment block gains a schedule paragraph (section 7.6): current use now also "read text objects (geometry, base-font name, font size, matrix) and the text page's per-character attribution from an admitted Full-Schedule PDF under `src/my_pa/infrastructure/schedule/pdf.py`; no rendering" and the floor rationale gains "the raw `FPDFText_*`/`FPDFTextObj_*`/`FPDFFont_*`/`FPDFPageObj_*`/`FPDFPage_Get*Box` functions S5a uses exist at 5.0.0" |
| T-03 | "Exact two-subtree confinement" (R2 §41, R2-AC-008) | `tests/architecture/test_scope_and_hygiene.py` `CONFINED_IMPORT_ROOTS` maps each root to **one** subtree string; `"pypdfium2": "infrastructure/goodnotes"`; importers today: `infrastructure/goodnotes/pdf.py`, `infrastructure/goodnotes/visual.py` | Guard change in section 2.2 (module-exact for schedule — D-03) |
| T-04 | Application must not import a PDF engine | `tests/architecture/test_dependency_direction.py` `PROVIDER_AND_PARSER_ROOTS` includes `pypdfium2`; application/adapters/contracts rules and the planted-import self-test already cover it; `test_domain_uses_only_the_standard_library` forbids third-party imports under `domain/` | No change to that file. `domain/schedule` is stdlib-only by that existing rule |
| T-05 | R2 §12.1 primitive "`PdfTextObj`" (R2-D-007) | The helper class `pypdfium2.PdfTextObj` (and `PdfFont`) exists at 5.13.0 but **not** at the 5.0.0 floor (measured: floor `dir(pypdfium2)` has no `PdfTextObj`, no `PdfFont`) | S5a uses only `PdfDocument`/`PdfPage`/`PdfTextPage` helpers (present at both) plus raw `pypdfium2.raw` functions (section 2.3). The repository record type is named `PdfTextObject` (R2 §43.4) and is not the library class — D-05 |
| T-06 | GoodNotes idiom | `src/my_pa/infrastructure/goodnotes/pdf.py`: `import pypdfium2 as pdfium  # type: ignore[import-untyped]`; `%PDF` magic check before `pdfium.PdfDocument(payload)`; `PdfiumError` mapped to `ValueError` with a fixed message; `document.close()` in `finally` | Same import line and ignore code; same magic-before-open order (stricter: `%PDF-` at offset 0); same close-in-`finally`; refusal carries a closed code, never a message containing source text |
| T-07 | — | `pypdfium2` is untyped (`import-untyped`); everything from `pypdfium2.raw` is `Any` under strict mypy | `pdf.py` converts every raw return to a concrete Python type at the call site (`int(...)`, `float(...)`, `bytes(...)`) so no `Any` escapes the module |
| T-08 | Tests in `tests/unit/test_schedule_full_profile.py` etc. (R2 §42) | `git ls-files tests/unit` lists 234 tracked files, none schedule-named; markers are strict (`--strict-markers`); `slow` is excluded from every CI lane (`tests/architecture/test_knowledge_tests_declare_lanes.py` docstring and the FAST `-m` expression) | S5a test modules are unmarked FAST tests; nothing S5a needs may be `slow` (section 10.4) |
| T-09 | — | CI is sharded: `tests/ci_shard.py` places any file absent from `tests/ci_shard_weights.json` by a stable SHA-256 of its path; `python -m tests.ci_shard verify --lane fast --shards 3 -m "<FAST expression>"` is the partition proof run by `validate-static`; `tests/architecture/test_ci_shards*.py` pin the matrix | New test files need no weight-table edit; implementers run the verify command (section 10.5) |
| T-10 | — | `.github/workflows/repository-checks.yml` runs on `ubuntu-latest`; the `dependency-floor` job installs every runtime floor (`pypdfium2==5.0.0` among them) and runs FAST and a bare `mypy` | Goldens must be byte-identical on Linux and at the floor — section 6.6 and D-14 make that hold by construction |
| T-11 | Synthetic fixtures via "a small vector/text PDF generator" | Precedent `tests/fixtures/tbr_workbook.py` writes real OOXML with stdlib only; `src/my_pa/infrastructure/goodnotes/pdf.py` `_assemble_pdf` writes a minimal xref PDF with stdlib only | Generator `tests/fixtures/schedule_full_pdf.py`, stdlib only (section 8) |
| T-12 | Generic extraction must stay separate | `SUPPORTED_MEDIA_TYPES: Final = frozenset({"text/markdown", "text/plain"})` in `src/my_pa/domain/extraction/text.py`; `application/capabilities.py` derives its content-type manifest from it | Unchanged; a scope test re-asserts it (section 10.1) |
| T-13 | `domain/schedule/model.py` is WP-01 | Neither `src/my_pa/domain/schedule/` nor `src/my_pa/infrastructure/schedule/` exists | S5a creates both with the parser-facing subset only (section 3) — D-01 |
| T-14 | Count guards | `tests/architecture/test_spelled_counts_match_the_sets_they_name.py::test_section_3_states_the_module_counts_it_says_it_derives` binds `docs/plans/mcv-completion-plan.md` line 77 ("436 … Python modules under `src/my_pa` and 823 … test modules", spelled out) to `find src/my_pa -name "*.py"` and `find tests -name "test_*.py"` | S5a adds 6 source modules (436 → 442) and 5 test modules (823 → 828); the implementer who lands the last module updates that sentence (spelled out, in the file's own style) and adds a dated "Current-tree remeasurement" paragraph after it, demoting the previous one to "Historical", re-measured with the two commands. **Also lockstep (F10):** `tests/architecture/test_claimed_test_counts_match_collection.py` binds, by equality, figures in `docs/plans/relationship-intelligence-implementation-plan.md` — the "Types" row's mypy corpus "clean over N files" (line 663 at the basis, 616; derived from `[tool.mypy] files`, which the 6 new `src` modules change), the "FAST tier validation" row's collected/passed figures (line 660 at the basis; the new FAST tests change them) and the "Architecture tier" row's collected/passed figure (line 661 at the basis; the new architecture module changes it). The last-landing implementer re-measures each with the command the row names and adds a dated current paragraph in the row's own style, demoting the prior one to "Historical" |
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
| open | `pypdfium2.PdfDocument(data: bytes, password=None)` | raises `PdfiumError` with `.err_code` (`raw.FPDF_ERR_PASSWORD` = 4, `raw.FPDF_ERR_SECURITY` = 5, `raw.FPDF_ERR_FORMAT` = 3, measured at both versions; an `/Encrypt` with an unknown `/Filter` gives 5, a `/Standard` handler with an unsupported revision gives 4); `data` must be `bytes` (a `str` is a path). **FR5:** `.err_code` is PDFium's *process-global* last error, and a load that fails without recording one (an empty page tree reports "Success") leaves the previous failure's code in place (measured at both versions: after a password-protected file, the empty page tree reports 4). `pdf.py` therefore first opens the constant bytes `%PDF-` (refused with `FPDF_ERR_FORMAT` = 3) before every open, so the mapping depends on the input bytes alone and an unrecorded failure maps to `CORRUPT_PDF` (D-40) |
| encryption | `raw.FPDF_GetSecurityHandlerRevision(doc.raw)` | `-1` means unencrypted; an RC4 rev-2 file with an empty user password **opens** and returns 2 (measured) |
| page count | `len(doc)` (`FPDF_GetPageCount`) | page tree only; no content parse |
| page size without loading | `raw.FPDF_GetPageSizeByIndexF(doc.raw, i, byref(FS_SIZEF))` | checked for every page before any page loads |
| page | `doc[i]` → `PdfPage`; `raw.FPDFPage_GetRotation(page.raw)`; `raw.FPDFPage_GetMediaBox` / `raw.FPDFPage_GetCropBox(page.raw, &l, &b, &r, &t)`; `page.close()` | `GetCropBox` returns 0 when no `/CropBox` is present (measured); an offset `/MediaBox [100 50 1324 842]` passes the size-by-index check (measured), hence V7's origin check |
| text page | `page.get_textpage()` → `PdfTextPage`; `.close()` | the source of every character (section 2.4) |
| characters | `raw.FPDFText_CountChars(tp)`, `raw.FPDFText_GetUnicode(tp, i)`, `raw.FPDFText_GetTextObject(tp, i)`, `raw.FPDFText_IsGenerated(tp, i)`, `raw.FPDFText_HasUnicodeMapError(tp, i)` | the only text source (section 2.4); `GetTextObject` returns NULL for generated characters (measured); handles are compared by `ctypes.cast(h, c_void_p).value` |
| embedding | `raw.FPDFFont_GetIsEmbedded(font)` | 1 for the Type3 fixtures (measured); counted, not enforced (D-36) |
| objects | `raw.FPDFPage_CountObjects`, `raw.FPDFPage_GetObject`, `raw.FPDFPageObj_GetType` (`FPDF_PAGEOBJ_TEXT`, `FPDF_PAGEOBJ_FORM`) | top level only; forms see below |
| form XObject | `raw.FPDFFormObj_CountObjects`, `raw.FPDFFormObj_GetObject` | used only to count nested objects and detect nested text (section 5.2 V8) |
| font | `raw.FPDFTextObj_GetFont(obj)`, `raw.FPDFFont_GetBaseFontName(font, buf, n)` | NUL-terminated bytes, decoded `latin-1` (lossless) |
| size | `raw.FPDFTextObj_GetFontSize(obj, byref(c_float))` | the `Tf` size; matrix scale is separate |
| bounds | `raw.FPDFPageObj_GetBounds(obj, &l, &b, &r, &t)` | page space, glyph-tight (measured: depends on the font program — section 6.6) |
| matrix | `raw.FPDFPageObj_GetMatrix(obj, byref(FS_MATRIX))` | `a b c d e f` |

Not called: rendering (`FPDF_RenderPage*`, `PdfPage.render`), `init_forms`/
`FPDFDOC_InitFormFillEnvironment`, attachments, bookmarks, links, actions, annotations,
`FPDFTextObj_GetText` (section 2.4), `PdfTextPage.get_text_range`,
`FPDFPageObj_GetRotatedBounds`, `PdfPage.get_objects`. The installed PDFium builds report
empty feature flags (`PDFIUM_INFO.flags == ()`, origin `pdfium-binaries`), i.e. no V8 and no
XFA. ctypes note: any UTF-16 buffer API takes a `POINTER(c_ushort)` (a `c_char` array raises
`ctypes.ArgumentError`); base-font names take a `c_char` buffer.

### 2.4 Measured text-page behaviour and the text-acquisition rule (R5-F01)

PDFium has no API that returns a text object's characters independent of the text page,
and the text page rewrites what it reports. Measured with throwaway Type3 probes
(identity `/ToUnicode`), byte-identical results at 5.0.0 and 5.13.0:

| Drawn | `FPDFTextObj_GetText` | non-generated characters attributed by `FPDFText_GetTextObject` |
|---|---|---|
| a 22-character name, then the same name at +0.1 / +0.25 / +0.3 / +0.5 / +1.0 pt in x | first object full; second `''` | first object full; **second: 0 characters** |
| the same name at +2.0 pt | both full | both full (R5 probe font). **FR5 re-measurement on the fixture Type3 fonts at 7 pt, both versions:** the 22-character name is suppressed at +0.1…+3.0 pt and **not** at +3.4 / +4.0 pt; `5` is not suppressed at +2.0 pt. The envelope is glyph-width dependent (item 5) |
| name, identical copy, copy at +0.2 pt | full, `''`, `''` | full, 0, 0 |
| `5` then `5` at +0.3 / +0.5 / +1.0 pt | `'5'`, `''` | 1, 0 |
| `5` then `5` at +2.0 / +3.6 pt | both `'5'` | 1, 1 |
| `5` then `8` at +0.0 / +0.3 pt (different text) | `'5'`, `'8'` | 1, 1 |
| `Same` regular then `Same` **bold**, same position (either order) or bold at +0.3 pt | first full, second `''` | first full, second 0 (font ignored) |
| `Same` and `Same` at +0.3 pt in y | first full, second `''` | 4, 0 |
| `SYN  1000` (2 spaces) | `'SYN 1000'` | `SYN 1000` (the run is collapsed inside the text page) |
| `A<TAB>B  C` | `'A\tB C'` | `A\tB C` (with the fixture fonts, whose `/ToUnicode` maps 0x20..0x7E only, the tab character also carries `HasUnicodeMapError == 1`, so the object is `unmapped`; this is a property of the font) |
| `  Pad  ` | `' Pad '` | ` Pad ` |
| ID `SYN-1000`, then a name and `5` on the same line | `'SYN-1000 '`, `'Synthetic activity 001 '`, `'5'` | `SYN-1000`, `Synthetic activity 001`, `5`; the 2 trailing spaces are generated characters attributed to no object |
| `Dup` at x 134 and `Dup` at x 620 on one line | `'Dup '`, `'Dup'` | `Dup`, `Dup` (+1 generated space) |
| `Dup` on 2 rows 15 pt apart | both `'Dup'` | both `Dup` (+ generated `\r\n`) |
| `() Tj` (empty show) | — | produces **no page object at all** |
| `( ) Tj` | `' '` | 1 character (a space) |
| glyphs with no `/ToUnicode` and non-standard glyph names | — | code-point fallback with `HasUnicodeMapError == 1` on every character |

**Rule.** For each page, `pdf.py` walks the text page once and builds, per top-level text
object, the string of its attributed characters in character-index order, keeping only
characters with `IsGenerated == 0` and a non-NULL `GetTextObject`. That string is the
object's `text`. Consequences, all fixed by this contract:

1. Generated characters never enter evidence (no dependency on neighbouring objects).
2. **Suppressed objects.** `suppressed = True` means exactly "the top-level text object has
   0 attributed characters", whatever the cause. Causes measured by R5 at both PDFium
   versions: (a) a same-text near-duplicate of an earlier object (the table above);
   (b) `0 Tf` (zero-area box); (c) `0 Tz` (zero-width box; **FR5:** PDFium folds `0 Tz` into
   the object matrix, `a == 0`, so such an object is never near-horizontal: in the data zone
   V10 refuses the page `UNSUPPORTED_LAYOUT` before section 5.4 runs, and in the header/footer
   it is ignored); (d) character codes outside the
   font's `FirstChar..LastChar` (zero-area box). Other causes are possible (for example a
   font with `/MissingWidth`). An empty show produces no object, so it is not a cause. Its
   geometry, font and size are still read. Section 5.4 resolves it deterministically; a
   **zero-area** suppressed object is always twinless; no suppressed object is silently
   dropped or resolved first-write-wins.
2a. **Invariant.** Every attributed character must map to a top-level text object of the
   page (D-09 guarantees no text in forms). A character attributed to an unknown handle is
   an invariant breach → `PARSER_EXCEPTION`.
3. **Whitespace runs.** A run of consecutive spaces inside one object is reported as one
   space; exact internal-whitespace preservation (R2 §16.4) is impossible through PDFium.
   Recorded as D-30 with a WP-04 owner (U-18). A within-publication pair of IDs differing
   only in run length becomes a `DUPLICATE_ACTIVITY_ID` (fails closed).
4. **Unmapped characters.** An object with any attributed character whose
   `HasUnicodeMapError == 1`, or whose code point is 0 or a surrogate, is `unmapped = True`;
   section 5.7 makes its cell `AMBIGUOUS` (D-17).
5. The measured suppression envelope (same text; up to at least 1.0 pt in x — **FR5:** up to
   at least 3.0 pt and not at 3.4 pt for a 22-character name in the 7 pt fixture font, not at
   2.0 pt for a single digit, i.e. it grows with the string's width; 0.3 pt in y; any font)
   is PDFium-internal and is **not** a profile constant. R2 §12.7's
   0.25 pt tolerance is applied by section 5.4 to the suppressed object's geometry, so the
   R2 semantics hold whatever PDFium's envelope is (U-15).

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
| `ScheduleParseCounts` | `pages, rows, project_summaries, wbs_summaries, activities, milestones, ambiguous, chart_objects_excluded, watermark_objects_excluded, suppressed_objects, duplicate_objects_collapsed, non_embedded_font_objects, issues, warnings` (all `int`) | derived, never independently set; `issues`/`warnings` count de-duplicated issues, `duplicate_objects_collapsed` counts objects (section 5.14) |
| `ScheduleParseEngine` | `pypdfium2_version: str, pdfium_version: str` | provenance from `pypdfium2.version.PYPDFIUM_INFO`/`PDFIUM_INFO`; **outside** the canonical object and digest (section 6.4) so WP-01 can persist it on the parser run |
| `ScheduleParseResult` | `parser_name: str, parser_version: str, profile_id: str, profile_version: int, document_sha256: str, document_size_bytes: int, outcome: SchedulePublicationStatus, published_schedule_title: str \| None, data_date: date \| None, run_date: date \| None, counts: ScheduleParseCounts, rows: tuple[ParsedScheduleRow, ...], issues: tuple[ScheduleParseIssue, ...], engine: ScheduleParseEngine` | `outcome` in the 4 terminal members; `FAILED` ⇒ `rows == ()` |
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
| `PdfTextObject` | `pdf.py` | frozen slots dataclass: `page_number: int, object_ordinal: int` (0-based top-level index), `text: str` (attributed non-generated characters, section 2.4; `""` iff suppressed), `suppressed: bool`, `unmapped: bool`, `font_base_name: str` (raw, may carry a subset prefix), `font_embedded: bool`, `font_size_mpt: int`, `box: ScheduleBox`, `matrix: tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]` (exact `Decimal(float)` of `a b c d e f`); property `normalized_box(page)` per R2 §12.3 |
| `PdfPageText` | `pdf.py` | `page_number, width_mpt, height_mpt, objects: tuple[PdfTextObject, ...]` |
| `PdfDocumentText` | `pdf.py` | `page_count: int, pages: tuple[PdfPageText, ...]` |
| `ScheduleParseRefusal(Exception)` | `pdf.py` | carries `code: ScheduleIssueCode` and, for a page-specific `UNSUPPORTED_LAYOUT`, `page_number: int \| None` (FR5: needed for the section 5.14 page reference); `str(exc) == code.value`; never source text |
| `ExtractionLimits` | `pdf.py` | a `Protocol` of the 6 `ScheduleParseLimits` fields extraction reads (FR5: `pdf.py` may not import `full_profile`, which imports it) |
| `ProfileTextObject` | `full_profile.py` | (FR5) a `PdfTextObject` after section 5.4 step 1: `source`, resolved `text` (`None` = unknown-text fragment) and `twin` (`object_ordinal` or `None`); the stage types `PageZones`, `DuplicateResolution`, `PdfPhysicalRow` hold these instead of bare `PdfTextObject`s, which keep the "text `''` iff suppressed" invariant |
| `ParseBudget` | `pdf.py` | `clock: Callable[[], float], deadline: float \| None`; `.checkpoint()` raises `ScheduleParseRefusal(PROCESSING_BUDGET_EXCEEDED)` when `deadline is not None and clock() > deadline` |
| `extract_pdf_text_objects(data: bytes, *, limits: ScheduleParseLimits, budget: ParseBudget) -> PdfDocumentText` | `pdf.py` | validation V1–V9 of section 5.2; raises `ScheduleParseRefusal` |
| `FullScheduleProfile` | `full_profile.py` | frozen dataclass holding every section 4 constant; one instance `P6_FULL_V1` |
| `ScheduleParseLimits` | `full_profile.py` | frozen dataclass of section 4.10; `PRODUCTION_LIMITS`; `__post_init__` refuses any field greater than its production value (limits may only tighten — D-24) |
| `PageZones` | `full_profile.py` | `page_number, metadata_objects, table_objects, chart_excluded: int, watermark_excluded: int` |
| `exclude_profile_non_data(page: PdfPageText, profile) -> PageZones` | `full_profile.py` | section 5.3; raises `UNSUPPORTED_LAYOUT` for a rotated table object |
| `collapse_duplicate_objects(objects) -> DuplicateResolution` | `full_profile.py` | section 5.4; returns kept objects (suppressed ones carrying their twin's text), collapsed objects with their twin, and issue drafts |
| `ProfileValidation` | `full_profile.py` | `title, data_date, run_date` (coherent values or `None`), `issues` |
| `validate_full_profile(zones: Sequence[PageZones], profile, *, expected_data_date: date \| None) -> ProfileValidation` | `full_profile.py` | V11–V13 of section 5.2; raises `UNSUPPORTED_LAYOUT` for a page-1 classification failure |
| `PdfPhysicalRow` | `full_profile.py` | `page_number, physical_line_ordinal, seed: PdfTextObject, objects: tuple[PdfTextObject, ...]` (x-ordered), `box: ScheduleBox` |
| `group_table_rows_by_overlap(objects, *, page_number, profile) -> tuple[PdfPhysicalRow, ...]` | `full_profile.py` | section 5.5 |
| `AssignedRow` | `full_profile.py` | the physical row plus six `ScheduleCellEvidence` and per-row issue drafts |
| `assign_full_cells(row: PdfPhysicalRow, profile) -> AssignedRow` | `full_profile.py` | sections 5.6–5.8 |
| `classify_full_row(assigned: AssignedRow, previous: PdfPhysicalRow \| None, profile, *, row_ordinal: int) -> ClassifiedRow` | `full_profile.py` | sections 5.9–5.10 (FR5: keyword `row_ordinal` carries the publication-wide ordinal) |
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
  (R2 §43.6); a golden digest change without a version bump fails review. (FR5 re-review 1:
  the bump rule is relative to the last *merged* parser. Before S5a merges, the parser is
  unreleased and changes land under `"1"`; `"1"` freezes at merge, and every later change that
  could alter a result for identical bytes bumps it.)

### 4.2 Page geometry

| Constant | Value |
|---|---|
| `PAGE_WIDTH_MPT` | 1,224,000 |
| `PAGE_HEIGHT_MPT` | 792,000 |
| `PAGE_SIZE_TOLERANCE_MPT` | 500 (inclusive, each dimension, measured from `FPDF_GetPageSizeByIndexF`) |
| page rotation | `FPDFPage_GetRotation == 0` |
| page origin | `/MediaBox` lower-left within 500 mpt of `(0, 0)`; if `FPDFPage_GetCropBox` reports a box, it equals the MediaBox within 500 mpt on every edge (R5-F12) |

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
| OD occlusion exception (R2 §12.5, §13.4.6, §37.6) | column-header band | the other 5 anchors are exact, **exactly one** non-anchor object has x-centre in the OD band and text matching the date grammar (section 4.7), no further extra object exists, and either (a) **replaced**: no `OD` anchor is present, or (b) **overlay**: exactly one `OD` anchor is present in the OD band → warning `HEADER_OD_OCCLUDED` (page ref, field `ORIGINAL_DURATION`). Anything else is a header mismatch |
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
| rotation | with the exact `Decimal` matrix: `a > 0` and `WATERMARK_TAN_MIN * a <= abs(b) <= WATERMARK_TAN_MAX * a`, where `WATERMARK_TAN_MIN = Decimal("0.087489")` (tan 5°) and `WATERMARK_TAN_MAX = Decimal("11.430052")` (tan 85°); no float trigonometry (R5-F11) |
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
| `WRAP_PITCH_MPT` | 10,000 (strictly less) | R2 §12.9; measured as top-edge pitch (D-21; the corpus row pitch is not stated by R2 — U-02) |
| `DUPLICATE_EDGE_TOLERANCE_MPT` | 250 (inclusive, every edge) | R2 §12.7 |
| `CELL_OVERLAP_MPT` | 250 (x-intersection strictly greater ⇒ overlapping) | S5a, equal to the duplicate tolerance (D-04) |
| `INDENT_TOLERANCE_MPT` | 1,500 | R2 §14.2 |
| `INDENT_MIN_SEPARATION_MPT` | 3,000 (= 2 × tolerance) | S5a (D-20); the corpus's smallest measured centroid gap is 3.52 pt, a margin of only 0.52 pt (U-16) |
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
| `max_text_chars` | 2,000,000 (`FPDFText_CountChars` summed over pages, checked right after each text page loads and before any character is read) | `BOUNDS_EXCEEDED` |
| `max_rows` | 25,000 | `BOUNDS_EXCEEDED` |
| `max_issues` | 50,000 (after de-duplication) | `BOUNDS_EXCEEDED` |
| `max_row_warnings` | 16 (unreachable at production values: at most 9 distinct row-referencing codes exist (the 8 row codes of section 5.14 plus `DUPLICATE_TEXT_OBJECT_COLLAPSED`), so only an injected limit can exercise it — a green production-limit test is not coverage) | `BOUNDS_EXCEEDED` |
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
objects within a page, after every 1,000 characters of a page's attribution walk (FR5-F07),
after extraction, before each page's grouping, before hierarchy, before step (9).

### 5.2 Validation order

| # | Check | Result |
|---|---|---|
| V1 | `len(data) > max_bytes` | `SOURCE_TOO_LARGE`, before any PDFium call |
| V2 | `not data.startswith(b"%PDF-")` (empty included) | `UNSUPPORTED_MEDIA_TYPE`, before any PDFium call |
| V3 | prime the last error (section 2.3, D-40), then open; `PdfiumError.err_code in {FPDF_ERR_PASSWORD, FPDF_ERR_SECURITY}` | `ENCRYPTED_PDF` (no password is ever supplied; error 5 = unsupported security handler, R5-F09) |
| V3' | open fails otherwise | `CORRUPT_PDF` |
| V4 | `FPDF_GetSecurityHandlerRevision != -1` | `ENCRYPTED_PDF` (D-13) |
| V5 | page count `0` (defensive: measured, PDFium already refuses an empty page tree at V3') | `UNSUPPORTED_LAYOUT`; `> max_pages` → `BOUNDS_EXCEEDED`, before any page load |
| V6 | every page's size by index (no load) within section 4.2 | else `UNSUPPORTED_LAYOUT` |
| V7 | per page, after load: rotation `0` (catches `/Rotate 180`, whose size by index is unswapped) and the section 4.2 origin rule (MediaBox/CropBox). `FPDFPage_GetMediaBox` reads the page's own `/MediaBox` only (measured: it returns 0 for a box inherited from the page tree); such a page cannot prove its origin and is refused (D-41, U-20). An offset CropBox of the profile size passes V6 (size by index is media ∩ crop) and is refused here | else `UNSUPPORTED_LAYOUT` |
| V8 | per page: cumulative object counts after `FPDFPage_CountObjects` and, incrementally, after each form level's `FPDFFormObj_CountObjects` (before reading that level's children; FR5-F07), all before reading any text of that page; a form XObject containing a text object at any depth, or nesting deeper than `max_form_depth` → `UNSUPPORTED_LAYOUT` (D-09); cumulative characters from `FPDFText_CountChars` right after the text page loads; then the section 2.4 attribution walk | caps → `BOUNDS_EXCEEDED` |
| V9 | no text object in the whole document with a non-whitespace attributed character | `IMAGE_ONLY_PDF` |
| V10 | zone partition; a remaining table object not near-horizontal | `UNSUPPORTED_LAYOUT` |
| V11 | page 1: column anchors exact or OD-occluded; Layout, Data Date, Run Date, title, signature each present exactly once and valid; signature `n == 1` | else `UNSUPPORTED_LAYOUT` (classification, R2 §11 — D-12) |
| V12 | pages 2..N: column anchors exact or OD-occluded | else `HEADER_SIGNATURE_MISMATCH` (page ref, error) |
| V13 | every page: each metadata item present once; normalized title, layout value, Data Date, Run Date equal page 1's; `n == page ordinal`; `m == page count` | else `PAGE_METADATA_MISMATCH` (page ref, one per page) |
| V13' | `expected_data_date is not None` and the coherent Data Date differs | `EXPECTED_DATA_DATE_MISMATCH` (no page ref); skipped when Data Date is incoherent |

V1–V10 failures stop the parse: outcome `FAILED`, `rows == ()`, `issues ==` the one
refusal issue (D-16). Non-suppressed text objects whose attributed text is whitespace only
count toward caps (V8) and are then dropped; they are never evidence. Suppressed objects
are **not** dropped (section 5.4).

### 5.3 Exclusion order per page (R2 §§12.4–12.6)

For each kept text object, in object order:

1. **Chart:** y-centre in the data zone and `x0 + x1 >= 2 * 615,500` → excluded,
   counted in `chart_objects_excluded`, contributes nothing anywhere.
1a. **Twins (RR1-F01, RR2-F01):** first, every **non-suppressed** remaining object that
   matches the section 4.6 watermark signature on its own text and geometry is marked
   `watermark_candidate`. Then section 5.4.1 runs over every remaining object of the page,
   so every suppressed object carries its twin's text (or is twinless) **before** the
   watermark test. A twin candidate must lie in the same zone (data zone vs header/footer)
   as `S`. Marked watermark objects take part in twin resolution only as described in
   section 5.4.1 (they never make an ordinary duplicate under the watermark's box
   twinless, and a suppressed watermark copy still finds the watermark as its twin even
   though its large box also crosses ordinary table text). Consequence: a watermark drawn
   twice (for example a fill and a `1 Tr` stroke copy; measured: the copy has 0 attributed characters) is two objects with text `DRAFT`,
   each tested against section 4.6 on **its own** geometry and rotation, so both are
   excluded and R2 §12.6 stays exactly as narrow as before. A twinless suppressed object
   never matches the watermark signature (its text is unknown).
2. **Header/footer:** y-centre outside the data zone → metadata set (near-horizontal
   objects only participate in section 4.5 matching; others are ignored). Never rows.
3. **Watermark:** matches section 4.6 → excluded, counted in
   `watermark_objects_excluded`.
4. **Rotation:** any remaining (table) object not near-horizontal → `UNSUPPORTED_LAYOUT`.

### 5.4 Suppressed objects and duplicate collapse (R2 §12.7, R5-F01)

Step 1 runs at section 5.3 step 1a (after the chart step, before the watermark step).
Steps 2–4 run separately within the metadata set and within the table set of each page,
after section 5.3 (a suppressed object is zoned by its own geometry like any other),
processing objects in `object_ordinal` order.

1. **Twin of a suppressed object (RR1-F01, RR1-F03).** For a suppressed object `S` whose
   box has positive area, the candidates are chosen as follows (RR2-F01). Let `W` be the
   objects marked `watermark_candidate` at section 5.3 step 1a whose box intersects `S`'s
   with positive area. (a) If `W` is non-empty **and** `S`'s own box and matrix satisfy the
   section 4.6 bbox and rotation conditions (text aside — `S` has none yet), the candidates
   are exactly `W`. (b) Otherwise the candidates are the **non-suppressed**, non-chart
   objects of the same page and zone whose box intersects `S`'s box with positive area,
   **excluding** every marked watermark object. So the `double_draw` stroke copy takes
   `DRAFT` from the watermark (case a) and is then tested against section 4.6 on its own
   geometry, while an ordinary duplicate under the watermark's box twins only with its true
   original (case b). If there is no candidate, or the candidates do not all have the same
   `normalize_display_text`, `S` is **twinless**. Otherwise the twin `M` is the candidate with the largest intersection area
   (integer mpt²), ties broken by lowest `object_ordinal`, and `S.text := M.text` (PDFium
   suppresses only same-text objects, section 2.4). A zero-area `S` is always twinless. A
   twinless `S` in the table set is a fragment of unknown text in its band, making that
   cell `AMBIGUOUS` + `AMBIGUOUS_CELL` (field = its band); in the metadata set it is
   ignored; it never matches the watermark signature.
2. **Exact duplicate.** An object `O` (suppressed with a twin, or not suppressed) is an
   exact duplicate of an earlier **kept** object `K` iff `normalize_display_text` of both
   texts is equal, the prefix-normalized base fonts are equal, and every box edge differs by
   `<= 250` mpt. `O` is collapsed into the earliest such `K`: issue
   `DUPLICATE_TEXT_OBJECT_COLLAPSED` (warning; page ref; in the table set the row ref and
   field of `K` once rows exist; in the metadata set no row and no field), and
   `duplicate_objects_collapsed += 1`.
3. **Not a duplicate (RR1-F04).** A suppressed `S` with a twin that is not collapsed stays
   a kept fragment carrying the twin's text. If `S` lands in the same band and row as `M`,
   that cell is **always** `AMBIGUOUS` + `OVERLAPPING_CELL_TEXT`, whatever their
   x-intersection (section 5.7.2's 250 mpt test does not apply to this pair, so a narrow
   glyph shifted about 1 pt is never joined as `"x x"`); if in addition the font class
   differs from `M`'s in the left region, the "mixed" case also applies (row `AMBIGUOUS`,
   R2 §13.3). If `S` lands in a different band or row from `M`, `S`'s cell is `AMBIGUOUS` +
   `AMBIGUOUS_CELL` (field = `S`'s band). Never first-write-wins. (FR5: the field is the cell
   `S` lands in, which differs from its band only when a bold label fragment in the ID band
   merges into the summary name. If `M` itself collapsed into a kept object `K` at step 2,
   `S`'s twin becomes `K`: same cell → overlapping, else `AMBIGUOUS_CELL` — D-42.)
4. `suppressed_objects` counts every suppressed object on every page (all zones except
   chart, which section 5.3 removes first), including watermark copies and twinless
   objects.

### 5.5 Physical row grouping (R2 §12.8)

Per page, over kept table objects:

1. Unassigned pool sorted by `(-y1, x0, object_ordinal)`.
2. Seed = first unassigned object. Seed interval `[s0, s1] = [seed.y0, seed.y1]`.
3. Each other unassigned object `o`, in pool order, joins iff
   `min_h = min(s1 - s0, o.y1 - o.y0) > 0` and
   `2 * max(0, min(s1, o.y1) - max(s0, o.y0)) >= min_h`. The comparison is always to the
   **seed** interval, never to the growing union (no chaining).
4. Row objects ordered by `(x0 + x1, -y1, object_ordinal)`. Row box = union of members.
5. Repeat until the pool is empty. Rows are emitted in seed order (after step 7's
   insertions); `physical_line_ordinal` counts from 1 per page; `row_ordinal` counts from 1 across the
   publication in (page, physical line) order and never changes (R2 §12.13).
6. A row whose box height `y1 - y0 > 16,000` is `AMBIGUOUS` with `AMBIGUOUS_CELL`
   (field `None`) (D-22).
7. **Zero-height objects (RR1-F02).** An object with `y1 == y0` (for example a zero-area
   suppressed object) never seeds a row and is left out of steps 1–5; afterwards it joins
   the first row, in emission order, whose **seed** interval contains its `y0` (closed
   interval); if none does it forms a row of its own (which section 5.10 then classifies,
   normally as `AMBIGUOUS`). It never changes another row's seed. **Placement (RR2-F02):**
   such an own row is inserted into the emission order at the position its object would
   take as a seed under the step 1 key `(-y1, x0, object_ordinal)`; `physical_line_ordinal`
   and `row_ordinal` are assigned only after all insertions, and the §5.9 predecessor `P`
   is taken from that final order. This deviates from R2 §12.8's "highest unassigned object
   is the seed" only for objects whose R2 overlap ratio is undefined (0/0) — D-38.

### 5.6 Font classes

`font_class(o)`: strip `SUBSET_PREFIX` once from `font_base_name`; `REGULAR` if the result
equals `Arial`, `BOLD` if it equals `Arial,Bold`, else `OTHER`. Style is profile evidence
only (R2 §13.3).

### 5.7 Cell assignment (R2 §12.10)

1. Each row object goes to the band containing its x-centre (section 4.3). An object with
   x-centre `< 37.0` → row `AMBIGUOUS` + `AMBIGUOUS_CELL` (field `None`). An `OTHER`-font
   object → row `AMBIGUOUS` + `AMBIGUOUS_CELL` (field = its band). These 2 row-level rules
   never fire for an unknown-text fragment (RR3-F02): such a fragment only makes its own
   cell `AMBIGUOUS` + `AMBIGUOUS_CELL` (field = its band), or, when out of the grid,
   records `AMBIGUOUS_CELL` with field `None` without changing the row type. An `unmapped` object
   (section 2.4) or a twinless suppressed object (section 5.4) → its cell `AMBIGUOUS` +
   `AMBIGUOUS_CELL` (field = its band); in the ID or Name band that makes the row
   `AMBIGUOUS` through section 5.10 rule 5, 7 or 8 (which rule is decided by real text only,
   per the unknown-text paragraph below).
2. Within one cell, fragments are ordered by `x0`. Two fragments **overlap** iff their
   x-intersection `> 250` mpt. Any overlap → cell state `AMBIGUOUS`, `text` = the
   x-ordered join, issue `OVERLAPPING_CELL_TEXT` (field). Never last-write-wins.
3. Otherwise the cell text is the fragments' `normalize_display_text(raw)` joined with one
   ASCII space; no fragments → `PUBLISHED_BLANK`, `text = None`.
4. `cells` always holds 6 entries in `ScheduleFieldCode` order without `HIERARCHY`; each
   fragment keeps raw text, box, raw base-font name and size (R2 §18.6).

**Unknown-text fragments (RR2-F03).** A twinless suppressed object (section 5.4.1) is an
unknown-text fragment. It is excluded from `IDr`/`IDb`/`Nr`/`Nb` below and from the band
conditions of section 5.9, but it stays a fragment of its own cell, which is `AMBIGUOUS` +
`AMBIGUOUS_CELL` (field = its band) — so the row's left-label case, wrap and missing-ID
codes are decided by real text only, and the unknown fragment's ambiguity is reported
alongside them. The "Cells" column below lists real-text fragments; in every case an
unknown-text fragment is added to its band's cell as well and makes that cell `AMBIGUOUS`.
An `unmapped` object (section 2.4) is not an unknown-text fragment: it has text and takes
part in the left-label case normally.

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

### 5.9 Row wrap (R2 §12.9, R5-F02)

Checked before classification. Physical row `R` (not the first row on its page) with
predecessor `P` on the same page is a wrap line iff **all** hold:

- `P.box.y1 - R.box.y1 < 10,000` (top-edge pitch);
- (unknown-text fragments, section 5.7, are ignored by all 4 band conditions below)
- `R` has no `REGULAR`-font object in the ID band (a regular ID would be an independent
  identity cell; a bold label continuation starting at the indent x is not);
- `R` has no object in the OD, RD, Start or Finish bands;
- `R` has at least 1 object, of any font class, in the merged label region `[37.0, 435.5)`.

Then `R` is `AMBIGUOUS` + `ROW_WRAP_UNSUPPORTED`; `P` is unchanged; nothing is
concatenated. There is no cross-page detection or continuation. A bold-label line at normal
pitch with no OD/RD/Start/Finish is not a wrap; section 5.10 rule 6 decides it.

### 5.10 Classification precedence (R2 §15)

Applied to each non-wrap row after section 5.7 (first match wins):

| # | Condition | `row_type` | Issue |
|---|---|---|---|
| 1 | already `AMBIGUOUS` by sections 5.5–5.7 | `AMBIGUOUS` | as recorded |
| 2 | ID-bearing with `ACTIVITY_ID` and `ACTIVITY_NAME` both `PUBLISHED_VALUE`; OD and RD `PUBLISHED_VALUE` equal to 0; exactly one of Start/Finish `PUBLISHED_VALUE` and the other `PUBLISHED_BLANK` | `MILESTONE` | — |
| 3 | ID-bearing with ID and name `PUBLISHED_VALUE`, OD and RD both `PUBLISHED_VALUE` equal to 0, without the exact date pattern | `AMBIGUOUS` | `AMBIGUOUS_CELL` (field `None`) |
| 4 | ID-bearing with ID and name `PUBLISHED_VALUE` | `ACTIVITY` | cell issues stay on their cells |
| 5 | ID-bearing with the ID or the name cell not `PUBLISHED_VALUE` (blank or `AMBIGUOUS`) | `AMBIGUOUS` | `AMBIGUOUS_CELL` (field = the first of `ACTIVITY_ID`, `ACTIVITY_NAME` that is not `PUBLISHED_VALUE`) |
| 6 | summary label present, its cell not `AMBIGUOUS`, and the required cells structurally present (R2 §15.6): at least 1 of OD/RD/Start/Finish not `PUBLISHED_BLANK` | `WBS_SUMMARY` (section 5.11 may promote one to `PROJECT_SUMMARY`) | — |
| 6' | summary label present, label cell not `AMBIGUOUS`, but OD/RD/Start/Finish all `PUBLISHED_BLANK` | `AMBIGUOUS` | `AMBIGUOUS_CELL` (field `None`) (D-32) |
| 7 | "no label" with at least one of OD/RD/Start/Finish holding a **real-text** fragment, or "name only" (a row whose non-blank cells hold only unknown-text fragments falls to rule 8) | `AMBIGUOUS` | `ACTIVITY_LIKE_ROW_MISSING_ID` (`ACTIVITY_ID`) |
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
   at level 0 with no parent, or it has a parent **whose level is exactly `L - 1`** and that
   is itself determinate. A skipped level (parent at `L - 2` or shallower, or no parent at
   `L > 0`) is the R2 §14.12 "missing/invalid lower-level parent" and is indeterminate
   (D-33). Indeterminate
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

Issues are de-duplicated on `(code, page_number, row_ordinal, field)` (so 2 objects
collapsed into the same kept object yield 1 `DUPLICATE_TEXT_OBJECT_COLLAPSED` issue while
`counts.duplicate_objects_collapsed == 2`; `counts.issues`, `counts.warnings` and the golden
`issue_counts` count de-duplicated issues — R5-F07) and sorted by
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
- `ScheduleParseResult`: `FAILED` ⇒ `rows == ()` and (FR5) every count is 0 except
  `issues == 1`, including `pages`; `rows` strictly increasing
  `row_ordinal` from 1; counts equal those derived from `rows`/`issues`;
  `document_sha256` 64 lowercase hex.

### 6.2 Number and text representation

| Value | Canonical form |
|---|---|
| geometry (mpt int) | decimal string with exactly 3 decimals, sign only when negative: `"598.600"` |
| normalized row box (R2 §12.3) | `x0/W, (H - y1)/H, x1/W, (H - y0)/H` with `W`/`H` the page's measured mpt; `Decimal` division under `localcontext(prec=28)`, quantized to `0.000001` `ROUND_HALF_EVEN`, string `"0.042956"`; a quantized negative zero is replaced by `Decimal(0)` before `str()` so `-0.000000` never appears (the same rule applies to every decimal string here) |
| font size | 3-decimal string from mpt |
| duration | `str(value)` of the quantized `Decimal` (`"12.000"`) |
| date | ISO `YYYY-MM-DD` |
| enum | its string value |
| absent | JSON `null` |
| raw text | the object's attributed non-generated characters as PDFium's text page reports them (section 2.4: whitespace runs already collapsed, never generated characters); not further normalized, except (FR5) that a code point 0, a surrogate or one above U+10FFFF is substituted by U+FFFD (and marks the object `unmapped`); normalized fields are NFC. A suppressed object with a twin reports its twin's text |

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
`row_ordinal` order; issues in section 5.14 order. `ScheduleParseResult.engine` is **not**
a key: the canonical object and its digest must not vary with the installed PDFium build
(goldens are shared by the floor and current venvs); the engine is provenance carried
beside it (R5-F05).

### 6.5 Canonical JSON

`json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
allow_nan=False).encode("ascii")`, no trailing newline. `ensure_ascii=True` makes the
bytes ASCII regardless of platform encoding; the section 2.4 `unmapped` rule keeps
surrogate and NUL code points out of every evidence string. Digest: SHA-256 of those bytes, lowercase hex.

### 6.6 Cross-run and cross-platform determinism

- Integer-millipoint geometry, `Decimal` derived quantities, sorted output, no `float`
  formatting, no `dict`/`set` iteration order dependence, no clock, no randomness.
- PDFium text bounds are glyph-tight and depend on the font program: measured, a
  non-embedded `/TrueType /BaseFont /Arial` gives `x1 = 70.800` for an 8-character string
  where its `/Widths` (556) advance sum gives `71.136`, and an unknown font name gives
  different bounds again — i.e. the substituted system font decides the box. The fixture
  fonts are therefore **Type3** fonts (section 8.2) whose glyph boxes come from `d1` in the
  PDF itself; measured at 5.0.0 and 5.13.0, bounds equal the analytic values exactly
  (`SYN-1000` at 7 pt from (40, 600) with 500-unit glyphs: `[40.000, 598.600, 68.000,
  604.900]`). Fixture goldens are therefore expected byte-identical on macOS and Linux and
  at the floor; the `dependency-floor` and `validate` FAST shards prove it on Linux (D-14,
  U-08).
- **Real inputs are not covered by that argument.** If a real export does not embed its
  fonts, the same bytes can yield different geometry on different hosts under the same
  `PARSER_VERSION` (U-10). S5a decision (D-36): such objects are accepted, counted in
  `counts.non_embedded_font_objects` (a property of the bytes, so it is in the digest; FR5:
  counted over every extracted top-level text object that is suppressed or has a
  non-whitespace character, chart and watermark objects included), and
  the PDFium build is carried as `engine` provenance; WP-04 measures embedding on the corpus
  and decides whether to refuse.
- The canonical result deliberately excludes PDFium/`pypdfium2` versions; a PDFium change
  that alters output fails the goldens, which is the intended signal.

---

## 7. Security of PDF parsing (hostile input)

| Concern | Control in S5a |
|---|---|
| byte bombs | V1 size check before any PDFium call (test monkeypatches `PdfDocument` to fail if called) |
| page bombs | V5 page count from the page tree, V6 sizes by index, both before any page load |
| object/char bombs | V8 cumulative caps checked after each page's object count and form walk (before reading that page's text) and after each text page's `FPDFText_CountChars` (before reading any character) — the parse stops early, never after materializing the document |
| decompression bombs | **Residual.** PDFium inflates a page's content streams inside `FPDF_LoadPage`; one hostile page can allocate before any cap is read, and the cooperative budget cannot pre-empt C code. Mitigations in S5a: the 16 MiB input cap, per-page object/char caps, the budget between pages, and handle release. Subprocess isolation with `RLIMIT_AS` is **out of scope** for S5a (it changes the worker's process model, which is WP-03's, and is not cheap to make deterministic in tests); recorded as U-05 for WP-03 |
| active content | no JavaScript (PDFium builds have no V8: `PDFIUM_INFO.flags == ()`), no form environment (`init_forms` never called), no actions/links/annotations/attachments read, no rendering, no network or file I/O (PDFium has none on this path; input is in-memory bytes) |
| encryption | no password is ever passed; V3 `FPDF_ERR_PASSWORD`/`FPDF_ERR_SECURITY` and V4 revision `!= -1` all refuse, so an empty-user-password file and an unknown security handler are refused too |
| resource cleanup | `PdfTextPage.close()`, `PdfPage.close()`, `PdfDocument.close()` each in `finally`, innermost first, on every path including refusals and budget expiry (test counts closes) |
| error mapping | last error primed before every open (D-40); `PdfiumError` → `CORRUPT_PDF`/`ENCRYPTED_PDF`; any other `Exception` escaping steps (3)–(12) of section 5.1 → `PARSER_EXCEPTION`; `MemoryError` re-raised (transient, WP-03 retries); results carry codes only |
| concurrency | PDFium is not thread-safe; S5a calls it from one thread per process and holds no Python-side global state; PDFium's last error is process-global (FR5, D-40), one more reason to serialize. If GoodNotes rendering and schedule parsing ever share a process, WP-03 must serialize PDFium use (U-12) |
| redaction | `ScheduleParseRefusal` text is its code; no module in either schedule package imports `logging` or calls `print`; no exception chains source text (`raise ... from None` on mapping); the scope guard enforces the import/print rule |

### 7.5 Exception contract of `parse_full_schedule`

Returns a `ScheduleParseResult` for every input `bytes`; raises only `MemoryError`,
`KeyboardInterrupt`/`SystemExit`, and `TypeError` for a non-`bytes` argument (programming
error).

### 7.6 `pyproject.toml` comment (range unchanged)

The `pypdfium2` paragraph keeps its GoodNotes text and adds: current use also reads text
objects (geometry, base-font name, font size, matrix) and the text page's per-character
attribution from an admitted Full-Schedule PDF in
`src/my_pa/infrastructure/schedule/pdf.py` without rendering; the 5.0 floor also carries
every raw `FPDFText_CountChars`/`GetUnicode`/`GetTextObject`/`IsGenerated`/
`HasUnicodeMapError`, `FPDFTextObj_GetFont`/`GetFontSize`, `FPDFFont_GetBaseFontName`/
`GetIsEmbedded`, `FPDFPageObj_GetBounds`/`GetMatrix`, `FPDFPage_GetMediaBox`/
`GetCropBox`, `FPDF_GetPageSizeByIndexF` and `FPDF_GetSecurityHandlerRevision` function
the schedule parser calls (the
`PdfTextObj`/`PdfFont` helpers are 5.x-later and deliberately unused); security surface
adds hostile admitted PDFs bounded by section 7 of this contract. Nothing else in the file
changes.

---

## 8. Synthetic fixtures (WP-00)

### 8.1 Generator

`tests/fixtures/schedule_full_pdf.py` — stdlib only (`hashlib`, `dataclasses`, `decimal`,
`datetime`, `json`, `pathlib`, `argparse`; no `math` — R5-F11); no PDF library. It mirrors
`_assemble_pdf` in `src/my_pa/infrastructure/goodnotes/pdf.py`: `%PDF-1.7`, objects in a
fixed order, a classic xref, a trailer; no `/Info`, no timestamps, no random `/ID` (the
encrypted fixture uses the fixed `/ID` `000102…0f`). Content-stream numbers are written
from `Decimal`/`str` with fixed formatting, never `repr(float)`. Each fixture is a pure
function `build(family, variant) -> FixtureCase` returning `pdf: bytes`,
`expected_data_date`, `limits` (production unless the variant tightens), `truth`
(section 8.4). Fixtures are generated at test time; **no PDF is committed**.

### 8.2 Fonts and text objects

- Two Type3 fonts per document: `/BaseFont /Arial` and `/BaseFont /Arial,Bold`; the
  `subset` variant uses `/BaseFont /SYNABC+Arial,Bold` (6 capitals + `+`). Default
  ("uniform") metrics: one shared `CharProc` per code 32..126 drawing a box with
  `500 0 0 -200 500 700 d1`, `/FontMatrix [0.001 0 0 0.001 0 0]`, `/Widths` all 500,
  `/Encoding /Differences`, and a `/ToUnicode` identity CMap for 0x20..0x7E. With these,
  each object's attributed characters equal its string except that a run of spaces is
  reported as one space (section 2.4, measured at both PDFium versions); fixtures that are
  not about that behaviour contain no double spaces. An `OTHER`-font variant uses
  `/BaseFont /Courier`; the `unmapped` variant omits `/ToUnicode`.
- **"glyph_metrics" fonts (R5-F05):** per-glyph `CharProc`s with distinct `d1` boxes —
  digits `500 0 0 0 500 650`, lowercase without descender `500 0 0 0 500 500`, descenders
  `g j p q y` `500 0 0 -200 500 500`, capitals and punctuation `500 0 0 0 500 700`, and a
  non-zero left-side bearing on `1` (`500 0 80 0 420 650`) — so heights and left edges
  depend on content, as in a real font. Truth for those variants is computed from the same
  per-glyph table.
- Analytic bounds for the uniform metrics, `n` characters at size `s` from origin
  `(x, y)`: `[x, y - 0.2s, x + 0.5ns, y + 0.7s]`. Body size 7 pt, level-1 summaries 8 pt,
  the project summary 10 pt, title 12 pt.
- **Text-state reset (RR1-F02).** `Tc`, `Tw`, `Tz`, `TL`, `Tr` and `Ts` persist across
  `BT`/`ET`, so every fixture text object writes them explicitly in its own block —
  `BT /Fn s Tf 0 Tc 0 Tw 100 Tz 0 TL 0 Tr 0 Ts a b c d e f Tm (…) Tj ET` — except the
  parameter a variant deliberately sets (the `double_draw` stroke copy's `1 Tr`, the
  `zero_char_object` codes), which is still reset by the next object's own block. A
  generator unit test asserts every `BT` block in every fixture sets all 6.
- One text object per `BT … Tf … Tm … Tj ET` block. Rotation `Tm` entries are literal
  `Decimal` constants: 7° watermark `0.992546 0.121869 -0.121869 0.992546`; 0.4° skew
  `0.999976 0.006981 -0.006981 0.999976`; 1° skew `0.999848 0.017452 -0.017452 0.999848`.

### 8.3 Common synthetic page frame

| Item | Placement (baseline origin, PDF space) |
|---|---|
| title | `Synthetic Project Schedule`, bold 12 pt at (40, 760) |
| layout | `Layout: SYN Full`, regular 7 pt at (40, 740) |
| Data Date / Run Date | `Data Date: 04-May-26` at (300, 740); `Run Date: 11-May-26` at (900, 740) |
| column anchors | regular 7 pt at y 710, x0 = 38.88, 134.52, 446.63, 478.20, 520.50, 576.97 (R2 §13.2 starts) |
| chart timescale header | `May 26` at (700, 710) (header zone, right of the chart boundary) |
| rows | first baseline 685, pitch 15 pt (a synthetic choice: R2 states no row pitch — U-02), 40 rows maximum per page (last baseline 100) |
| row cells | ID at the level's indent x; name x0 134.0; OD right edge 465.0; RD right edge 496.0; Start x0 501.0; Finish x0 562.0 |
| indent x by level | R2 measured centroids 52.57, 56.78, 60.30, 63.88, 67.70, 71.53, 75.35, 79.08; **jitter (R5-F06):** in families 5 and 19, ID-bearing rows at level 4 alternate left edge `+0.0` / `+0.6` pt (at least 2 rows each), so the level-4 cluster spans 0.6 pt and its centroid stays at least 3.23 pt from both neighbours; every other level is exact |
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
| 1 | `full_valid_2p` (`base`, `subset_prefix`, `zone_edges`, `split_name`, `id_double_space`) | 2 | project summary L0, 2 WBS L1, activities L2, a Start-only and a Finish-only milestone (OD 0, RD 0), one date with `*`, every ID followed by its name and cells on the same line; `subset_prefix` uses the prefixed bold base name; `zone_edges` adds activity rows whose objects' y-centres are exactly 700.000 and 95.000 pt; `split_name` draws one name as 2 abutting objects overlapping by 0.2 pt in x; `id_double_space` draws ID `SYN  1001` (2 spaces) | C; `split_name` name text is the 2 fragments joined by one space; `id_double_space` publishes `SYN 1001` (measured collapse, D-30) | row types, milestone pattern, marker, prefix normalization, zone-edge inclusivity, cell-overlap threshold, no generated characters in evidence; ID precision/recall, name/date/duration accuracy; AC-009, 018 |
| 2 | `full_merged_summary_label` (`base`, `label_only`) | 1 | bold L1 label from x0 52.57 whose box crosses 131.0, OD/RD/dates aligned; `label_only`: a bold label row at normal pitch with all 4 value cells blank | C / R (`label_only` row `AMBIGUOUS` + `AMBIGUOUS_CELL`, D-32) | §38 merged label never an ID; no summary→activity promotion; R2 §15.6 required cells; AC-012 |
| 3 | `full_summary_vertical_offset` (`base`, `glyph_metrics`) | 1 | 10 pt bold project label with centre 3.0 pt above the 7 pt numeric cells' centre (overlap ratio ≈ 0.74); `glyph_metrics` repeats the page with the per-glyph font (descender labels, digit-only cells, a bearing on `1`) | C | §38 one row by overlap under uniform and realistic metrics; AC-012 |
| 4 | `full_summary_zero_zero` (`base`, `id_both_dates`) | 1 | blank-ID bold summary with OD `0`, RD `0`, one Start date; `id_both_dates`: an ID-bearing row with OD `0`, RD `0` and both dates | C / R (row `AMBIGUOUS` + `AMBIGUOUS_CELL`, section 5.10 rule 3) | stays `WBS_SUMMARY`, never milestone; malformed zero-duration not guessed; AC-018 |
| 5 | `full_nested_hierarchy` | 3 | all 8 indent levels with every child exactly 1 level below its parent; level-4 jitter (section 8.3); repeated label `Synthetic Phase A` at 2 positions; page 2 opens with activities whose parent summary is on page 1 | C | exact parents/paths, stack carry, repeated labels distinct; hierarchy gate; AC-019 |
| 6 | `full_header_occluded_od` (`replaced`, `overlay`) | 2 | page 2 OD anchor replaced by `04-May-26` with x0 436.0 / page 2 keeps its OD anchor and also carries `04-May-26` at x0 436.0 | C + `HEADER_OD_OCCLUDED` (page 2), both variants | §38 parses and warns only; R2 §12.5/§13.4.6/§37.6 both shapes; AC-014 |
| 7 | `full_header_mismatch` (`later_page`, `first_page`) | 2 | `RD` and `Start` anchors missing on page 2 / page 1 | R + `HEADER_SIGNATURE_MISMATCH` / F `UNSUPPORTED_LAYOUT` | AC-014 refusal |
| 8 | `full_missing_activity_id` | 2 | page 2 row with OD/RD/Start/Finish only, plus its name in the chart region | R + `ACTIVITY_LIKE_ROW_MISSING_ID` | §38 invents no ID/name, links nothing; missing-ID gate; AC-016, 021 |
| 9 | `full_duplicate_activity_id` | 1 | two activities `SYN-1100` with different names | R + `DUPLICATE_ACTIVITY_ID` ×2 | no winner; zero links; AC-021 |
| 10 | `full_duration_date_in_rd` | 1 | a summary and an activity with `15-Mar-28` at RD x0 467.6 | P + `INVALID_DURATION` ×2 | §38 cells stay; coercion gate = 0; AC-017 |
| 11 | `full_duration_date_in_od` | 1 | an activity with `15-Mar-28` at OD x0 436.0 | P + `INVALID_DURATION` | same; AC-017 |
| 12 | `full_invalid_date` | 1 | `31-Feb-27` in Finish; `30-Foo-26` in Start | P + `INVALID_DATE` ×2 | coercion gate; AC-023 |
| 13 | `full_chart_duplicates` | 1 | every row's name/dates repeated at x0 620/700 | C, `chart_objects_excluded` > 0 | §38 zero chart fragments; chart gate; AC-010 |
| 14 | `full_draft_watermark` (`signature`, `off_signature`, `slight_skew`, `skew_1deg`, `double_draw`) | 1 | rotated (7°) `DRAFT` whose box edges each sit 6–10 pt (not 0) from the signature box, crossing the table; an activity named `DRAFT`; `off_signature` moves every edge 20 pt; `slight_skew` adds an activity name at 0.4°; `skew_1deg` at 1°; `double_draw`: the `signature` watermark drawn twice at the same `Tm`, the copy with `1 Tr` (measured: copy has 0 attributed characters, box 0.5 pt larger) | C, `watermark_objects_excluded == 1`, `DRAFT` name kept / F `UNSUPPORTED_LAYOUT` / C / F `UNSUPPORTED_LAYOUT` / C with `watermark_objects_excluded == 2`, `suppressed_objects == 1`, no duplicate warning | §38 watermark zero fragments; watermark gate; near-horizontal boundary; AC-011 |
| 15 | `full_duplicate_text_object` (`base`, `shift_0_5`, `bold_over_regular`, `same_text_2pt`, `under_watermark`, `cross_band`) | 1 | `base`: one activity name drawn 3 times (identical, identical, +0.2 pt in x — measured: 2 suppressed objects) and, on another activity, OD `5` drawn twice 0.3 pt apart (measured: second suppressed); `shift_0_5`: a name redrawn +0.5 pt (suppressed); `bold_over_regular`: a regular name redrawn in bold at the same position (suppressed); `same_text_2pt`: OD `5` redrawn +2.0 pt (measured: **not** suppressed); `under_watermark`: the `base` duplicates placed inside the family 14 `signature` watermark's box, with that watermark drawn; `cross_band` (FR5-F01): an ID whose x-centre is 130.8 pt and its same-text redraw +0.5 pt (centre 131.3, Name band; measured suppressed at both versions), the name at x0 150 | `base`: P — 1 `DUPLICATE_TEXT_OBJECT_COLLAPSED` issue (`counts.duplicate_objects_collapsed == 2`, `suppressed_objects == 3`) and `OVERLAPPING_CELL_TEXT` on the OD cell; `shift_0_5`: R (name cell overlapping → row `AMBIGUOUS`); `bold_over_regular`: R (mixed → row `AMBIGUOUS`); `same_text_2pt`: P (`OVERLAPPING_CELL_TEXT`); `under_watermark`: as `base`, plus `watermark_objects_excluded == 1`; `cross_band`: R (Name cell `AMBIGUOUS` + `AMBIGUOUS_CELL`, row `AMBIGUOUS` by rule 5, `suppressed_objects == 1`) | §38 exact duplicate collapses; R2 §12.7 0.25 pt boundary with PDFium suppression; R2 §13.3 mixed style; no first-write-wins |
| 16 | `full_overlapping_cell_text` (`od`, `id`, `id_split`, `unmapped`, `zero_char_object`) | 1 | `5` and `8` 0.3 pt apart in OD (measured: both reported) / IDs `SYN-1101` and `SYN-1102` 0.3 pt apart / an ID drawn as `SYN-` and `1201` abutting without overlap / an activity name in a font without `/ToUnicode` / in an activity's RD band an object showing codes `<0a0b>` outside the font's `FirstChar..LastChar` (measured: 0 attributed characters, zero-area box) | P + `OVERLAPPING_CELL_TEXT` / R (row `AMBIGUOUS`) / R (ID cell with 2 fragments, D-11) / R (unmapped name → row `AMBIGUOUS`) / P (twinless suppressed object → RD cell `AMBIGUOUS` + `AMBIGUOUS_CELL`) | §38 non-identical overlap ambiguous; no last-write-wins; identity never assembled from pieces |
| 17 | `full_ambiguous_hierarchy` (`close_centroids`, `orphan`, `level_gap`) | 1 | edges at 52.57 and 54.40 / a level-2 activity before any summary / a level-3 activity directly under a level-1 summary (no level-2 summary) | P + `HIERARCHY_AMBIGUOUS` (all 3) | every ambiguity explicit; R2 §14.12; AC-019 |
| 18 | `full_row_wrap_unsupported` (`regular_name`, `bold_label`) | 1 | an activity followed by a regular name-only line 8 pt lower / a bold summary label followed by a bold continuation line starting at the same indent x (inside the ID band) 8 pt lower | R + `ROW_WRAP_UNSUPPORTED` (both) | wrap-concatenation gate = 0; no phantom summary; AC-013 |
| 19 | `full_multi_page_86_equivalent` | 86 | 54 pages × 40 rows + 32 pages × 39 rows = 3408 rows: 443 summaries (1 project + 442 WBS), 2964 ID-bearing (2900 activities, 32 Start-only and 32 Finish-only milestones), 1 missing-ID row on page 21; OD occlusion on page 37; date tokens in a summary RD (page 55), an activity RD (page 58), an activity OD (page 61); watermark and chart duplicates on every page | R; counts equal `MEASURED_CORPUS`; issues: 1 missing-ID, 1 occlusion warning, 3 invalid-duration | corpus-shape reproduction; performance target; AC-037 |
| 20 | `corrupt_pdf` (`garbage`, `not_a_pdf`, `empty`) | — | `%PDF-1.7\n` + 8 × `\x00garbage\n` (measured `FPDF_ERR_FORMAT`) / `not a pdf` / `b""` | F `CORRUPT_PDF` / F `UNSUPPORTED_MEDIA_TYPE` ×2 | AC-007 |
| 21 | `encrypted_pdf` (`user_password`, `empty_user_password`, `unknown_filter`) | 1 | RC4 40-bit, standard handler R2, `/P -44`, stdlib RC4 + `hashlib.md5(usedforsecurity=False)`; user `synthetic-user` / empty, owner `synthetic-owner` / `/Encrypt << /Filter /SynUnknown … >>` | F `ENCRYPTED_PDF` ×3 (measured: error 4 / opens with revision 2 / error 5) | AC-007 |
| 22 | `image_only_pdf` | 1 | correct page size, one 1×1 DeviceGray image XObject and a filled path, no text | F `IMAGE_ONLY_PDF` | AC-007 |
| 23 | `wrong_page_size` (`letter`, `rotated`, `rotated_180`, `offset_origin`, `zero_pages`) | 1 | 612×792 / `/Rotate 90` (measured: size by index reads 792×1224, so V6 refuses) / `/Rotate 180` (size unswapped; V7 refuses) / `/MediaBox [100 50 1324 842]` (measured: passes the size check; V7 origin refuses) / empty `/Kids` (measured: PDFium refuses to open) | F `UNSUPPORTED_LAYOUT` ×4 / F `CORRUPT_PDF` | AC-009 |
| 24 | `page_metadata_mismatch` (`data_date`, `run_date`, `title`, `page_number`, `page_total`) | 2 | page 2 differs in the named item | R + `PAGE_METADATA_MISMATCH` (page 2) | AC-015 |
| 25 | `expected_data_date_mismatch` (`mismatch`, `match`) | 2 | `full_valid_2p` bytes with `expected_data_date` 2026-05-05 / 2026-05-04 | R + `EXPECTED_DATA_DATE_MISMATCH` / C | AC-015 |
| 26 | `bounds_exceeded` (`bytes`, `pages`, `text_objects`, `page_objects`, `chars`, `rows`, `issues`, `row_warnings`, `hierarchy_depth`, `cell_evidence`, `form_text`, `form_depth`, `time_first`, `time_mid`) | varies | `bytes`: valid bytes padded after `%%EOF` to 16 MiB + 1 (production); `pages`: 251 blank frame-size pages (production); the others use tightened `ScheduleParseLimits` on small documents (e.g. `max_rows=3` with 4 rows); `form_text`: a form XObject holding a text object; `form_depth`: 5 nested form XObjects holding only a path (production `max_form_depth`); `time_*`: fake clock per section 5.15 | F `SOURCE_TOO_LARGE` / `BOUNDS_EXCEEDED` / `UNSUPPORTED_LAYOUT` / `PROCESSING_BUDGET_EXCEEDED` | AC-007; production limit values pinned separately by `test_production_limits_are_the_r2_bounds` |

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
- `ScheduleParseResult.engine` is never written to a golden (it differs between the floor
  and current venvs, which share the goldens).
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
| golden row fields (page, ordinals, type, indent, parent, path, ID, name, OD/RD, Start/Finish + marker, bboxes, cell evidence, warnings, outcome) | `test_every_case_matches_its_golden` (parametrized over every family and variant of section 8.5) |
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
`test_object_text_is_attributed_non_generated_characters` (section 2.4 table rows as
assertions, including the measured suppression and whitespace-collapse cases, so a PDFium
upgrade that changes them fails here first), `test_no_generated_character_enters_evidence`,
`test_suppressed_objects_resolve_deterministically` (including the RR1-F02 causes `0 Tf` and out-of-range codes with zero-area twinlessness, and `0 Tz`, which in the data zone is refused by V10 first (FR5), and the RR1-F03 unit case: a split name whose second fragment is duplicated at +0.1 pt takes the second fragment's text, never the first's), `test_unmapped_characters_make_the_cell_ambiguous` (including a monkeypatched surrogate and NUL code point), `test_unknown_character_handle_is_parser_exception`, `test_fixture_text_state_is_reset_in_every_block`, `test_zero_height_own_row_is_placed_by_the_seed_key` (RR2-F02), `test_unknown_text_fragment_does_not_decide_the_row_case` (RR2-F03: a missing-ID row plus a zero-area object in the ID band yields both `ACTIVITY_LIKE_ROW_MISSING_ID` and `AMBIGUOUS_CELL`; a wrap line plus such an object still yields `ROW_WRAP_UNSUPPORTED`; RR3-F01: a row consisting only of a zero-area object yields `AMBIGUOUS_CELL` and **no** `ACTIVITY_LIKE_ROW_MISSING_ID`; RR3-F02: an out-of-grid or `OTHER`-font unknown-text fragment does not make its row `AMBIGUOUS`),
`test_security_error_and_unknown_filter_are_encrypted`, `test_page_origin_is_validated` (FR5-F02: includes the offset-CropBox case that passes V6),
`test_a_stale_pdfium_error_never_decides_the_refusal` (D-40),
`test_a_suppressed_copy_in_another_cell_is_ambiguous` (FR5-F01: PDFium probe, cross-row unit case, collapsed-twin redirect),
`test_budget_checkpoints_every_1000_objects` (FR5-F04), `test_budget_checkpoints_every_1000_characters` and
`test_form_objects_join_the_cap_before_their_children_are_read` (FR5-F07),
`test_metadata_ignores_unmapped_objects` (FR5-F05, D-17), `test_overlapping_title_pieces_never_publish_a_doubled_title` (D-39), `test_a_stacked_two_line_title_is_joined` (D-39 needs the y-overlap; mutant B6),
`test_engine_provenance_is_outside_the_digest`;
`test_schedule_full_profile.py::test_od_occlusion_admits_replaced_and_overlay_only`,
`test_wrap_detects_bold_label_continuations`, `test_summary_requires_a_value_cell`,
`test_level_gap_is_hierarchy_ambiguous`, `test_watermark_rotation_uses_decimal_tangents`;
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

Each row names a fixture or unit case that makes the mutant **reachable** (R5-F06); a
mutant left green is reported as redundancy, a masked test or an unreachable hazard, never
"covered".

| # | Mutant | Reached by | Must fail |
|---|---|---|---|
| M01–M14 | each of the 7 grid constants `+1,000` and `-1,000` mpt (**14 runs**) | unit band-boundary cases sit exactly on and 1 mpt either side of every line | `test_profile_constants_are_frozen`, `test_cell_band_boundaries_on_every_grid_line` (FR5 correction: no golden object lies within 1 pt of 131.0 or 615.5, so families 2 and 13 do not also fail; the pin and the band test are the guards) |
| M15 | `ROW_OVERLAP_RATIO` `1/2` → `3/4` | family 3 (ratio ≈ 0.74) | family 3 golden, `test_overlap_ratio_boundary_is_one_half` |
| M16 | `ROW_MAX_SPAN_MPT` 16,000 → 30,000 | unit row-span case (a 20 pt tall object overlapping a 7 pt seed) | `test_rows_group_by_seed_overlap_not_centre_distance` |
| M17 | `CHART_BOUNDARY` → 700.0 | family 13 (chart name at x0 620) | family 13 golden, `chart_admitted` gate |
| M18 | watermark text `DRAFT` → `DRAFTX` | family 14 `signature` | family 14 golden (becomes `UNSUPPORTED_LAYOUT`) |
| M19 | watermark tolerance 12 → 5 pt | family 14 `signature` (edges 6–10 pt off the signature) | family 14 golden |
| M20 | `WATERMARK_TAN_MIN` → `0.13` (above tan 7° = 0.122785) | family 14 `signature` | family 14 golden, `test_watermark_rotation_uses_decimal_tangents` |
| M21 | `NEAR_HORIZONTAL_TAN` 0.01 → 0.005 | family 14 `slight_skew` (tan 0.4° = 0.00698) | family 14 `slight_skew` golden |
| M22 | `NEAR_HORIZONTAL_TAN` 0.01 → 0.02 | family 14 `skew_1deg` (tan 1° = 0.01745) | family 14 `skew_1deg` golden |
| M23 | `DUPLICATE_EDGE_TOLERANCE_MPT` 250 → 100 | family 15 `base` (+0.2 pt suppressed copy) | family 15 golden (`counts.duplicate_objects_collapsed` 1, name overlapping) |
| M24 | `DUPLICATE_EDGE_TOLERANCE_MPT` 250 → 400 | family 15 `base` (+0.3 pt suppressed `5`) | family 15 golden (OD collapses instead of overlapping) |
| M25 | `CELL_OVERLAP_MPT` 250 → 100 | family 1 `split_name` (0.2 pt overlap) | family 1 `split_name` golden |
| M26 | `CELL_OVERLAP_MPT` 250 → 4,000 | family 16 `od` (3.2 pt overlap) | family 16 `od` golden |
| M27 | `INDENT_TOLERANCE_MPT` 1,500 → 500 | families 5 and 19 level-4 jitter (0.6 pt) | family 5 golden, `hierarchy_accuracy`, family 19 summary |
| M28 | `INDENT_MIN_SEPARATION_MPT` 3,000 → 1,000 | family 17 `close_centroids` (1.83 pt) | family 17 golden |
| M29 | `INDENT_MIN_SEPARATION_MPT` 3,000 → 3,600 | family 5 (3.52 pt gap) | family 5 golden |
| M30 | `WRAP_PITCH_MPT` 10,000 → 7,000 | family 18 (8 pt pitch) | family 18 goldens |
| M31 | `WRAP_PITCH_MPT` 10,000 → 16,000 | family 2 `label_only` (15 pt pitch) | family 2 `label_only` golden (becomes a wrap) |
| M32 | data zone top 700.0 → 699.9 | family 1 `zone_edges` | family 1 `zone_edges` golden |
| M33 | data zone bottom 95.0 → 95.1 | family 1 `zone_edges` | family 1 `zone_edges` golden |
| M34 | header split 724.0 → 745.0 | base frame (Layout centre 741.75 enters the column-header band) | every C golden (page-1 `UNSUPPORTED_LAYOUT`) |
| M35 | header split 724.0 → 705.0 | base frame (anchor centre 711.75 leaves the band) | every C golden |
| M36 | `max_form_depth` 4 → 8 | family 26 `form_depth` | family 26 `form_depth` golden |
| M37 | rule: y-centre grouping with 2 pt tolerance replacing overlap | family 3 | family 3, `test_rows_group_by_seed_overlap_not_centre_distance` |
| M38 | rule: union instead of fixed seed | unit chaining case | `test_grouping_compares_to_the_fixed_seed` |
| M39 | rule: drop suppressed objects (first-write-wins) | family 15 all variants | family 15 goldens, `test_suppressed_objects_resolve_deterministically` |
| M40 | rule: last-write-wins in a cell | family 16 `od` | family 16, `test_exact_duplicate_collapses_and_overlap_is_ambiguous` |
| M41 | rule: build text with `FPDFTextObj_GetText` (keeps generated characters) | family 1 `base` (ID and name on one line) | `test_no_generated_character_enters_evidence`, family 1 golden |
| M42 | rule: chart-side repair of a missing name | family 8 | family 8, `test_missing_id_row_invents_nothing_and_links_nothing` |
| M43 | rule: date token in OD/RD shifted into Start | families 10–11 | families 10–11 (FR5 correction: the moved token is a valid date, so `date_accuracy`/`duration_accuracy` fail, not `coerced_invalid`) |
| M44 | rule: split a bold label at 131.0 into ID + name | family 2 | family 2, `test_merged_summary_label_is_never_an_activity_id` |
| M45 | rule: wrap requires no object at all in the ID band (pre-R5 rule) | family 18 `bold_label` | family 18 `bold_label` golden |
| M46 | rule: summary without the R2 §15.6 required-cell check | family 2 `label_only` | family 2 `label_only` golden |
| M47 | rule: OD occlusion only when the anchor is absent | family 6 `overlay` | family 6 `overlay` golden, `test_od_occlusion_admits_replaced_and_overlay_only` |
| M48 | rule: accept any lower-level parent (level gaps) | family 17 `level_gap` | family 17 `level_gap` golden |
| M49 | rule: any `AMBIGUOUS` row → `PARTIAL` (undo D-10) | family 16 `id` | family 16 `id` golden, `test_outcome_derivation_table` |
| M50 | rule: page-1 header failure → review (undo D-12) | family 7 `first_page` | family 7 `first_page` golden |
| M51 | rule: concatenate multi-fragment ID (undo D-11) | family 16 `id_split` | family 16 `id_split` golden |
| M52 | rule: milestone allows both dates | family 4 `id_both_dates` | family 4 `id_both_dates` golden |
| M53 | rule: duplicate ID keeps the first occurrence | family 9 | family 9 golden, `test_missing_and_duplicate_ids_force_review_required` (FR5 correction: `bad_identity_linked` is structurally masked — the remaining duplicate issue keeps `REVIEW_REQUIRED`, which already links nothing) |
| M54 | rule: drop V2 (`%PDF-` magic) | family 20 `not_a_pdf` | family 20 golden (becomes `CORRUPT_PDF`) |
| M55 | rule: V1 after open | `test_byte_cap_is_checked_before_pdfium_opens` | that test |
| M56 | rule: drop V4 (revision check) | family 21 `empty_user_password` | family 21 golden |
| M57 | rule: map error 5 to `CORRUPT_PDF` | family 21 `unknown_filter` | family 21 golden |
| M58 | rule: drop V6 size check | family 23 `letter` | family 23 `letter` golden |
| M59 | rule: drop V7 rotation check | family 23 `rotated_180` | family 23 `rotated_180` golden |
| M60 | rule: drop V7 origin check | family 23 `offset_origin` | family 23 `offset_origin` golden |
| M61 | rule: treat unmapped characters as mapped | family 16 `unmapped` | family 16 `unmapped` golden |
| M62 | rule: concatenate a wrap line | family 18 | family 18, `wrap_concatenated` |
| M63 | rule: remove one `close()` from a `finally` | `test_handles_are_closed_on_every_exit` | that test |
| M64 | rule: include `engine` in the canonical object | `test_engine_provenance_is_outside_the_digest` | that test (and the floor-venv golden run) |
| M65 | guard: `import pypdfium2` in `full_profile.py` | section 2.2 | `test_a_confined_dependency_is_imported_only_where_it_belongs` |
| M66 | guard: remove the import from `pdf.py` | section 2.2 | `test_every_confined_dependency_is_actually_used_there` |
| M67 | guard: edit 1 golden byte | any golden | `test_golden_files_are_pinned_by_digest` |
| M68 | guard: add `"application/pdf"` to `SUPPORTED_MEDIA_TYPES` | — | `test_generic_extraction_still_excludes_pdf` |
| M69 | guard: `import logging` in `pdf.py` | — | `test_schedule_modules_neither_log_nor_print` |
| M70 | rule: run twin resolution after the watermark step (pre-RR1 order) | family 14 `double_draw` | family 14 `double_draw` golden (becomes `UNSUPPORTED_LAYOUT`) |
| M71 | rule: give a twinless suppressed object a guessed text instead of an unknown-text fragment | family 16 `zero_char_object` | family 16 `zero_char_object` golden, `test_suppressed_objects_resolve_deterministically` |
| M72 | rule: twin = lowest-ordinal intersecting candidate (pre-RR1) | unit split-name duplicate case | `test_suppressed_objects_resolve_deterministically` |
| M73 | rule: drop the surrogate/NUL clause of D-17 | unit monkeypatched code points | `test_unmapped_characters_make_the_cell_ambiguous` |
| M74 | rule: apply the 250 mpt x-intersection test to a suppressed object and its twin | unit case over hand-built `PdfTextObject`s: a suppressed object whose box intersects its twin's by 200 mpt in x (not reachable through PDFium's ~1 pt envelope with the fixture glyphs, so it is a pure-algorithm case) | `test_suppressed_objects_resolve_deterministically` |
| M75 | rule: marked watermark objects are ordinary twin candidates (pre-RR2) | family 15 `under_watermark` | family 15 `under_watermark` golden (duplicates become twinless) |
| M76 | rule: a zero-height own row is appended at the end of the page | unit case in `test_zero_height_own_row_is_placed_by_the_seed_key` | that test |
| M77 | rule: unknown-text fragments count in the left-label case and wrap conditions | unit cases in `test_unknown_text_fragment_does_not_decide_the_row_case` | that test |
| M78 | rule: omit the section 5.4 step 3 different-band/row clause (FR5-F01) | family 15 `cross_band`, PDFium probe | family 15 `cross_band` golden and truth, gates, `test_exact_duplicate_collapses_and_overlap_is_ambiguous`, `test_a_suppressed_copy_in_another_cell_is_ambiguous` |
| M79 | rule: no redirect of a twin that itself collapsed (D-42) | unit collapsed-twin case | `test_a_suppressed_copy_in_another_cell_is_ambiguous` |
| M80 | rule: disable the V7 CropBox comparison (FR5 A8) | offset CropBox `[100 50 1324 842]` | `test_page_origin_is_validated` |
| M81 | rule: drop the per-1,000-object budget checkpoint (FR5 A3) | a page of 1,100 objects | `test_budget_checkpoints_every_1000_objects` |
| M82 | rule: unmapped metadata objects participate (FR5 A15) | Data Date drawn without `/ToUnicode` | `test_metadata_ignores_unmapped_objects` |
| M83 | rule: overlapping title pieces publish the joined title (undo D-39) | fake-bold title +0.3 / +0.5 pt | `test_overlapping_title_pieces_never_publish_a_doubled_title` |
| M84 | rule: no checkpoint in the character walk | a page of 1,440 characters, 30 objects | `test_budget_checkpoints_every_1000_characters` |
| M85 | rule: a form subtree is counted before the cap is compared | 4-deep path-only form, tight cap | `test_form_objects_join_the_cap_before_their_children_are_read` |
| B6 | rule: D-39 without its positive-area (y-overlap) condition | stacked two-line title | `test_a_stacked_two_line_title_is_joined` |

FR5 column note: M30, M31 and M45 are killed by their named goldens plus truth and unit tests;
no section 10.3 gate fails for them (the wrap gate detects concatenation only, M62). M43 and
M53 are corrected above; an equivalent mutant (`PROJECT_SUMMARY` without `level == 0`, FR5
A14) exists because the first summary can only be determinate at level 0.

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
| D-10 | ambiguous cell → partial or review by identity impact | any `AMBIGUOUS` row → `REVIEW_REQUIRED`; ambiguous non-identity cell → `PARTIAL` | an ambiguous row may hide an ID; R2 §17.3 step 3 and the §39 dropped-row gate cannot hold under `PARTIAL` (endorsed by R5). Stricter than R2 §22 for a non-identity `OTHER`-font object in a numeric band, which also makes its row `AMBIGUOUS`. `AMBIGUOUS_CELL` in section 5.13 rule 3 is reachable only through non-row cases and is harmless |
| D-11 | concatenate fragments within a cell | ID cell with more than 1 fragment → ambiguous | identity is never assembled from pieces; generated characters cannot create fragments (section 2.4). If real exports split IDs across objects, every publication becomes review-required (U-14) |
| D-12 | header failures → review | page-1 classification failure → `UNSUPPORTED_LAYOUT`; later pages → review | §11 says non-matching PDFs are unsupported |
| D-13 | "encrypted/password-required → fail" | any security handler refuses, even with an empty user password | measured: such files open silently |
| D-14 | generator unspecified | Type3 fixture fonts with `Arial`/`Arial,Bold` base names | measured: non-embedded font bounds depend on font substitution |
| D-15 | memory/time bounds enforced | decompression inside `FPDF_LoadPage` is not pre-emptible; no subprocess isolation in S5a | see U-05 |
| D-16 | failed = no accepted parse | `FAILED` results carry no rows and exactly 1 issue | deterministic, minimal |
| D-17 | — | an object with any `HasUnicodeMapError` character, NUL or surrogate code point is `unmapped`; its table cell is `AMBIGUOUS` + `AMBIGUOUS_CELL`; metadata ignores it | measured: without `/ToUnicode` PDFium falls back to the code with the error flag set; fail closed per object rather than refusing the document; keeps lone surrogates out of JSONB |
| D-18 | metadata retained after coherence | per-item `None` when incoherent | never claim a coherent value that is not |
| D-19 | ambiguity never invents a parent | indeterminacy propagates to descendants | a path through an indeterminate ancestor is not deterministic |
| D-20 | nearest-centroid assignment | own fixed-seed cluster; adjacent centroids `>= 3.0` pt apart or indeterminate | nearest-centroid can cross clusters; measured centroids are 3.52–4.21 pt apart |
| D-21 | "within <10 pt of the preceding row cluster" with no independent ID/numeric/date cells | top-edge pitch `< 10.0` pt; no **regular** object in the ID band; no OD/RD/Start/Finish object; at least 1 object in `[37.0, 435.5)` | a bold continuation of a summary label starts at its indent x, inside the ID band, and must not become a phantom summary (R5-F02). Top-edge pitch is a synthetic reading of R2's phrase; the corpus row pitch is not stated by R2 (U-02) |
| D-22 | 16 pt span "may" | over-span row → `AMBIGUOUS` + `AMBIGUOUS_CELL` | R2 gives no consequence |
| D-23 | style contract for IDs/labels | numeric/date cells accept regular or bold | R2 is silent; summaries plausibly print bold numbers |
| D-24 | bounds fixed | injectable limits that may only tighten | deterministic bounds tests without giant fixtures |
| D-25 | WP-02 includes a parser-run/row persistence interface | none; `ScheduleParseResult` is the interface | S5a forbids persistence |
| D-26 | one unit test module named | 4 unit modules + 1 architecture module | separation of pure, PDFium and golden tiers |
| D-27 | parser name/version unnamed | `cpm-workbench-full-parser` / `"1"` | needed for canonical bytes |
| D-28 | duplicate collapse "before row grouping" | also within metadata objects; never chart objects | duplicated header text must not fail "exactly one" rules |
| D-29 | non-negative decimal | quantized 3 dp; 9 integer digits max; no leading zeros | `NUMERIC(12,3)` fit and one canonical form |
| D-30 | internal whitespace in IDs preserved exactly (§16.4) | a run of spaces inside one text object is reported by PDFium as one space; IDs are published as reported | measured at both PDFium versions; no PDFium API returns the uncollapsed string (U-18) |
| D-31 | duplicates collapse; distinct overlaps are ambiguous (§12.7) | PDFium-suppressed same-text objects are kept, given their twin's text, and then judged by the R2 0.25 pt rule (section 5.4) | measured: PDFium empties same-text objects within about 1 pt in any font; without this rule overlap would be silently first-write-wins (R5-F01) |
| D-32 | summaries need structurally present required cells (§15.6) | a bold label row needs at least 1 non-blank OD/RD/Start/Finish; otherwise `AMBIGUOUS` | fail closed on a label-only line that could be a wrap or stray text |
| D-33 | missing/invalid lower-level parent → `hierarchy_ambiguous` (§14.12) | a parent must be exactly 1 level shallower | a skipped level is the R2 evidence of a missing parent; assumes the export indents a child exactly 1 step (U-16) |
| D-34 | OD header "absent/replaced" and "replaces/overlays" | both the replaced and the overlay shape admitted, nothing broader | R2 §12.5, §13.4.6, §37.6 read together (R5-F03) |
| D-35 | page size only | MediaBox origin and CropBox equality also checked | measured: an offset MediaBox passes the size check, and every zone assumes a (0,0) origin |
| D-36 | determinism across platforms | real non-embedded-font inputs accepted, counted and paired with `engine` provenance outside the digest | refusing could fail a corpus whose embedding is unknown; WP-04 decides (U-10) |
| D-37 | encrypted → fail | `FPDF_ERR_SECURITY` (5) also → `ENCRYPTED_PDF` | measured: an unknown security handler returns 5 |
| D-38 | §12.8 "choose the highest unassigned object as the row seed" | zero-height objects never seed; they join a row whose seed interval contains them, else form an own row placed by the seed key | R2's ratio `intersection / min(height)` is undefined (0/0) at zero height; only degenerate 0-character objects reach it (RR2-F02, RR2-F04) |
| D-39 | — (title pieces are joined) | a page title whose pieces overlap (positive-area intersection and x-intersection over 250 mpt) is invalid: page 1 `UNSUPPORTED_LAYOUT`, later pages `PAGE_METADATA_MISMATCH` | measured at both versions: a fake-bold title redraw +0.3/+0.5 pt keeps its characters and is not collapsed, which published a doubled title with no issue (FR5-F07); mirrors section 5.7 step 2 |
| D-40 | — | PDFium's last error is primed with `%PDF-` before every open | the error is process-global and stale after an unrecorded failure (FR5) |
| D-41 | page size only | a page whose own dictionary has no `/MediaBox` is refused | `FPDFPage_GetMediaBox` does not read the inherited box; the origin cannot be proven (FR5); see U-20 |
| D-42 | — | a suppressed object's twin that collapsed is replaced by the kept object it collapsed into | keeps section 5.4 step 3 fail-closed and deterministic (FR5-F01) |

### 11.2 Residuals and unknowns

| ID | Item | Owner |
|---|---|---|
| U-01 | No real corpus is available: every synthetic-assumption constant (sections 4.4 bands, 4.5 grammars, 4.6 angle/tolerance) is unverified against real bytes; an export that differs fails `UNSUPPORTED_LAYOUT`/review (fail closed, R2 §51.9) | WP-04 authorized-corpus evaluation; any change bumps `PARSER_VERSION` |
| U-02 | Header/metadata token shapes, the 724 pt split, the row pitch (R2 states none; fixtures use 15 pt) and the top-edge wrap reading are assumptions | WP-04 |
| U-03 | Watermark angle range and ±12 pt tolerance are assumptions | WP-04 |
| U-04 | Whether real exports put table text, or the `DRAFT` watermark itself, inside form XObjects is unknown; S5a refuses text in forms, so a form-wrapped watermark would make the corpus `FAILED`, not `REVIEW_REQUIRED` — WP-04 must check before accepting D-09 | WP-04 |
| U-05 | Decompression-bomb memory inside one page load is bounded only by the 16 MiB input; subprocess/`RLIMIT_AS` isolation is a WP-03 decision | WP-03 |
| U-06 | Specialty layouts sharing the same 6 columns and metadata cannot be distinguished without real layout values; R2 already defers them | future profile package |
| U-07 | Text render mode (invisible text) is not consulted | WP-04 security review |
| U-08 | Linux identity of goldens is argued (Type3 bounds come from the file) and measured only on macOS at both PDFium versions locally; CI's Linux FAST/floor shards are the first Linux proof | S5a CI run |
| U-09 | The R2 parser-only `< 30 s` target is asserted; the worker `< 60 s` target and RSS `<= 512 MiB` are not measurable without the worker | WP-03/WP-04 |
| U-10 | Real-input geometry may depend on the host font environment when fonts are not embedded (measured for non-embedded `Arial`); WP-04 measures `FPDFFont_GetIsEmbedded` on the corpus and decides refuse/flag (D-36). `engine` identifies the PDFium build, not the host's font set: 2 hosts with the same build and different system fonts produce different geometry with identical provenance, which WP-04's decision must account for | WP-04 |
| U-11 | Refusing every security handler also refuses owner-password-only (permissions) exports; WP-04 confirms the corpus has no `/Encrypt` | WP-04 |
| U-12 | PDFium is not thread-safe; if GoodNotes rendering and schedule parsing share a process, PDFium calls must be serialized | WP-03 |
| U-13 | NFC and `str.isspace` follow the running Python's Unicode database; code points unassigned in an older database could normalize differently after a Python upgrade | WP-04 / Python upgrades |
| U-14 | D-11 assumes one text object per published Activity ID; WP-04 measures it on the corpus | WP-04 |
| U-15 | PDFium's same-text suppression envelope (measured: x offsets up to at least 1.0 pt, not 2.0 pt; 0.3 pt in y; font ignored) is internal to PDFium and may change between builds; section 5.4 applies R2's 0.25 pt rule independently, and `test_object_text_is_attributed_non_generated_characters` pins the envelope so a change is seen | S5a tests / PDFium upgrades |
| U-16 | The level-gap rule (D-33) and the 3.0 pt centroid separation (D-20, only 0.52 pt margin over the corpus's 3.52 pt minimum) assume the corpus indents each child exactly 1 step | WP-04 |
| U-17 | Whether real fonts carry `/ToUnicode` (otherwise every cell is `unmapped` and every publication review-required) is unknown | WP-04 |
| U-18 | Whether any corpus Activity ID contains consecutive spaces (D-30). Within a publication a run-length-only difference fails closed as `DUPLICATE_ACTIVITY_ID`; **across** publications an ID whose source changes only in space-run length would be falsely merged into one Stable Activity — WP-01/WP-04 must know this | WP-04 |
| U-19 | Corpus summaries whose 4 value cells are all blank (an empty WBS can print that way) become `AMBIGUOUS` under D-32, and through D-33 their children cascade to `HIERARCHY_AMBIGUOUS`; WP-04 counts them | WP-04 |
| U-20 | Whether real exports carry a per-page `/MediaBox` (D-41). A page-tree-inherited box fails the whole publication `UNSUPPORTED_LAYOUT`; `FPDF_GetPageBoundingBox` is inheritance-aware (measured `[0 0 1224 792]`) and could replace the call after a contract amendment | WP-04 |
| U-21 | Metadata near-duplicates other than the title (FR5-F07): Layout, dates, signature and anchors already fail closed through their "exactly once" rules; a non-text metadata near-duplicate class is not otherwise detected | WP-04 |
| U-22 | D-39 availability risk: a real export that double-draws its title to fake bold (offset beyond the 0.25 pt duplicate tolerance) would make **every** publication `FAILED` (`UNSUPPORTED_LAYOUT` on page 1). Fail-closed by design; WP-04 must measure whether the corpus title is drawn once, and if not, a profile change (bumping `PARSER_VERSION`) must decide how such a redraw is resolved. A stacked multi-line title (pieces disjoint in y) is unaffected and pinned by `test_a_stacked_two_line_title_is_joined` | WP-04 |
