# WP-15 — Apple Native Host Production-Shaped Foundation and Admission

Branch: `bf/wp-15-apple-native-host-foundation`. Base: `9428c7612780679696e88609660666b9ed59727d`.

This record states what WP-15 proved, **at what level it proved it**, and what it
deliberately did not do. It is written so that a later reader can tell a compiled
guarantee from a runtime observation from a document, because the difference is
the whole value of the package.

---

## The six acceptance controls

| # | Control | Proved at | Where |
|---|---|---|---|
| 1 | Host is source-read-only | **Static guard over every Swift file under `native/` except the compile-only probe** (Python architecture test) + **Swift compile-time** (no framework is linked, so no mutating type exists to call) | `tests/architecture/test_wp15_native_host_admission.py::test_the_shipping_host_holds_no_write_path_into_an_apple_source`, `::test_the_read_only_boundary_declares_no_mutating_operation`, `::test_no_write_capable_entitlement_or_usage_declaration_exists` |
| 2 | Host holds no DB credential | **Static guard over the whole `native/**` tree**, including `Package.swift`, down to the raw Darwin socket primitives; plus a shipping-target guard that the host starts no second process | `::test_the_host_cannot_reach_a_database_or_read_a_credential`, `::test_the_shipping_host_starts_no_second_process`, `::test_the_host_package_declares_no_dependency_and_links_no_library` |
| 3 | Spool owner-only / bounded / atomic | **Swift runtime** (`stat` at runtime on a real spool) + static guard on the refusal paths | `AppleSourceHostContractChecks::checkSpoolItemsAreOwnerOnlyRegularFiles`, `::checkProtectedSpoolLifecycle`, `::checkProtectedSpoolFaultsAndBounds`; `::test_the_spool_bounds_exist_and_refuse_rather_than_evict` |
| 3b | Protocol page and cursor bounded, on both sides | **Swift runtime** for the host's refusal; **Python unit** for the application's refusal and for the two literals agreeing | `AppleSourceHostContractChecks::checkFrozenPageAndCursorBoundsRefuseRatherThanClamp`; `tests/unit/test_wp12_slice_c_application.py::test_admission_envelope_refuses_an_over_bound_page_or_cursor_rather_than_trimming`, `::test_the_frozen_bounds_are_the_same_literals_on_both_sides_of_the_boundary` |
| 4 | Bridge identity / version / auth | **Swift runtime** for version refusal and lifecycle ordering; **Python unit + PostgreSQL integration** for bridge identity, envelope binding and adapter authentication | `AppleSourceHostContractChecks::checkHostLifecycleRefusesIllegalTransitionsAndVersionDrift`; `tests/unit/test_wp12_slice_c_application.py`, `tests/schema/test_wp12_slice_c_admission.py` |
| 5 | Replay / idempotency | **Python unit against real Swift spool bytes** + **PostgreSQL integration** (sequential and concurrent) | `test_wp15_a_replayed_protected_spool_item_admits_once_and_names_the_duplicate`; `test_wp15_sequential_replay_adds_no_row_and_operational_rows_stay_content_free`; `test_concurrent_replay_creates_one_immutable_version_and_evidence` |
| 6 | Content-free operational telemetry | **Swift runtime** (planted marker, every emission searched) + **Python architecture guard** (field types, structurally) + **PostgreSQL integration** (operational rows vs. the evidence plane) | `AppleSourceHostContractChecks::checkOperationalTelemetryIsContentFree`; `::test_operational_telemetry_has_nowhere_to_put_personal_content`; `test_wp15_admission_telemetry_and_receipts_carry_no_record_content` |

### Control 3, stated exactly

The bound's behaviour is **refusal, never a drop**. `ProtectedSpool.enqueue`
throws `itemCapacityExceeded`, `byteCapacityExceeded` or `payloadTooLarge`, and
the runtime check confirms that a refused enqueue leaves the existing inventory
byte-identical. Nothing evicts, truncates or overwrites: `unlinkat` appears
exactly once in the whole file, in `acknowledge`, which removes one item the
application has already durably admitted. That count is asserted.

Owner-only is read by `stat` at runtime, not inferred from the `S_IRUSR`
literals: directories are `0700`, item files are `0600` and regular, and both are
owned by the running uid.

### Control 3b — the protocol page and cursor bounds, and why refusal is the only honest answer

An unbounded page is an unbounded spool item, so the bound belongs to the
protocol and not to whichever adapter happens to build the page.
`NativeSourceProtocolV1.maximumPageSize = 100` and `maximumCursorBytes = 512` are
enforced in three places, and every one of them **throws**:

* `NativeReadRequest.init` refuses a `limit` above the ceiling
  (`NativeSourceContractError.invalidPageLimit`), from the memberwise initialiser
  and from `init(from:)`, so the bound cannot be walked around by handing the
  host JSON instead of building a value;
* `NativeReadCursor.init?(rawValue:)` refuses a cursor whose **UTF-8 byte** count
  exceeds the ceiling — bytes, not characters, so a multi-byte cursor is bounded
  by what it actually costs;
* `NativeReadPage.init` refuses an over-long page rather than serving its first
  hundred records. This is stricter than the preserved WP-12E draft, which used a
  `precondition`: a trap is untestable and a truncation is worse than untestable,
  because a short page is indistinguishable from a genuinely short bucket and
  `nextCursor` then describes a position the records do not reach. §28 forbids
  the silent loss, so the page is refused whole.

The application half is `NATIVE_SOURCE_MAX_PAGE_SIZE` and
`NATIVE_SOURCE_MAX_CURSOR_BYTES` in `src/my_pa/contracts/v1/native_sources.py`,
bounding `NativeAdmissionEnvelope.records` and `next_cursor`. Pydantic's failure
here is the right one — nothing is admitted at all. Without it the Swift bound
would be advisory, because the application would accept a page the host would
never have produced.

**The two literals are held equal by a test, not by a comment.**
`test_the_frozen_bounds_are_the_same_literals_on_both_sides_of_the_boundary`
reads `100` and `512` out of the Swift source and compares them to the Python
constants. A bound the host and the application disagree about is not a bound.

### Control 6, and why it is a type rather than a filter

`Sources/AppleSourceHost/HostTelemetry.swift` declares the operational values a
health endpoint, a metric or a log line may carry. **No type in it has a
free-form `String` field.** Every textual value is a closed enumeration raw
value, the frozen protocol identifier, or a `NativeSourceOpaqueID` whose own
validator rejects locator punctuation. `NativeHostErrorClass(_ error: Error)`
classifies without quoting — it discards even the `errno` inside
`filesystemFailure`.

A redaction filter is a promise that every call site remembers to call it. A
struct with nowhere to put content keeps the promise structurally.

---

## Non-vacuity — five controlled reversions, observed and reverted

Each was planted, observed failing for the intended reason, and reverted. The
tree contains none of them.

Reversions 1–3 were measured at `9e974de`, where the architecture module held 13
tests and the Swift binary ran 13 checks; both counts are higher at this head
(15 and 14), so the pass counts quoted in those three entries are the historical
observation and not a claim about the corrected head. Reversions 4 and 5 were
measured here.

1. **Telemetry gains a content field.** Added `public let oldestPendingPayload: String`
   to `NativeHostSpoolHealth` and had `ProtectedSpool.health()` fill it from the
   oldest pending item's payload. The package still **built cleanly**, which is
   the point — this is the change a well-meaning contributor makes.
   - Swift: `Fatal error: … ContractCheckError.failed("An operational emission carried spooled content")`, exit **133**.
   - Python: `AssertionError: NativeHostSpoolHealth.oldestPendingPayload is a free-form String …` — **1 failed, 12 passed**.
   - After revert: build exit 0, `AppleSourceHostContractChecks: PASS (13 checks)` exit 0, **13 passed** exit 0.
2. **A production call site for the quarantined plane.** Imported
   `NativeSourceController` into `src/my_pa/adapters/normalization.py`.
   - `AssertionError: ['adapters/normalization.py'] construct or reference NativeSourceController …` — **1 failed, 12 passed**.
   - After revert: **13 passed**, exit 0.
3. **An error message that quotes the record.** Appended the admitted records'
   payload bytes to `AdmissionDeniedError("native admission escaped its exact
   authorized bucket")`.
   - `AssertionError: an operational artefact of native admission carried the content of an admitted record …`, showing the marker inside the exception text — **1 failed**.
   - After revert: **17 passed**, exit 0.
4. **The page bound honoured by truncation instead of refusal.** Replaced
   `NativeReadPage.init`'s `guard … else { throw }` with
   `Array(records.prefix(maximumPageSize))` — the change that "respects the
   limit" while silently losing records. It **built cleanly**.
   - Swift: `Fatal error: … ContractCheckError.failed("Expected error invalidPageLimit")`, exit **133**.
   - After revert (file byte-identical to before the plant): build exit 0,
     `AppleSourceHostContractChecks: PASS (14 checks)` exit 0.
5. **A composition-root wiring of the quarantined plane.** Imported
   `NativeSourceController` into `apps/gateway.py` — the real gateway
   entrypoint, and a file the guard did not scan before this correction.
   - `AssertionError: ['apps/gateway.py'] construct or reference NativeSourceController …` — **1 failed, 14 passed**.
   - After revert: **15 passed**, exit 0, and `git status --porcelain apps/` empty.

---

## OD-COMP-009 — macOS distribution model

**Resolution.** The target model is the register's recommended default: a
**signed, notarized local helper registered through `ServiceManagement`
(`SMAppService`)**, running as the current user, reading Apple sources read-only
and handing evidence to the authenticated application through the protected
spool. Nothing in this package activates it.

**What was compile-proved, on this machine, on every `swift build`.**
`Compatibility/AppleFrameworkCompatibilityProbe` is a separate library target
that imports **EventKit, Contacts, MailKit and ServiceManagement** and resolves
their read-oriented symbols as metatypes — with one field, `calendarEntity`, an
`EKEntityType` enum case rather than a metatype, because resolving an enum is how
you prove the enum exists. Nothing in the probe is instantiated either way, so
the "no store is created" half is unaffected. It compiles clean. The package
now declares `platforms: [.macOS(.v13)]`, because `SMAppService` is macOS 13+ and
MailKit is macOS 12+; without the declaration the probe would have proved those
frameworks *unavailable* rather than available.

The probe is deliberately **not** a dependency of `AppleSourceHost`, so the
shipping module still links none of these frameworks — a guard asserts both
halves. The probe instantiates nothing, requests no access, and registers no
service, so proving compatibility touched **no TCC state**.

Toolchain of record: Apple Swift 6.2 (`swiftlang-6.2.0.19.9`), target
`arm64-apple-macosx28.0`, SDK `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk`.

**The MailKit finding, which is the substantive one.** MailKit links and its
types resolve, and that is *not* evidence that Apple Mail is readable. The SDK
ships `MEExtension`, `MEMessageDecoder`, `MEMessageSecurityHandler`,
`MEMessageActionHandler` and friends — an **extension-point** framework. There is
no store, no account enumeration, no mailbox listing and no message query
anywhere in its headers. Completion-plan doc 08 warns "do not assume MailKit
enumerates mailbox content"; this package moves that from a caution to a measured
fact. **WP-16 owns finding the actual mechanism, and should not begin from the
assumption that MailKit is it.**

**Lifecycle shape, built now so activation is configuration rather than
redesign.** `Sources/AppleSourceHost/HostLifecycle.swift` is an explicit state
machine — `constructed → protocolNegotiated → spoolOpened → readyForHandoff`,
with `refused` and `stopped` — where every transition is named and anything
unnamed is refused. Version agreement is the first transition and is not
optional. `distributionModel` is `unsignedDevelopmentBuild`;
`signedNotarizedLoginItemService` is refused at construction, because selecting
it from code would claim an activation this build has not performed.
`serviceRegistrationPerformed` is a computed `false` with no setter, and a wire
health report claiming otherwise fails to decode.
`unsatisfiedActivationPrerequisites` enumerates all six gates as data.

**Precise limits — what still needs an operator, real hardware, or both.**

| Gate | What is missing | Owner |
|---|---|---|
| EXT-03 | Apple signing identity and notarization profile. Nothing here is signed or notarized; no `.entitlements` file exists and a guard fails if one appears. | Operator |
| EXT-04 | TCC grants on a pilot Mac. No permission was requested; `requestAccess`/`requestFullAccess` appear nowhere, in either target. | Operator |
| EXT-05 | An eligible pilot Mac, installation, and service lifecycle evidence. `SMAppService.register()` is never called. | Operator |
| EXT-06 | Approved live or non-personal Apple test accounts. **No live personal data was read.** | Operator |
| — | Whether a live EventKit/Contacts enumeration actually works under a real grant. Compile compatibility is not runtime feasibility. | WP-17 / WP-18 |
| — | The Apple Mail read mechanism, given MailKit does not enumerate. | WP-16 |

---

## The WP-04 quarantine — unchanged, and now measured rather than asserted

WP-15 **un-quarantines nothing**. The twenty-two unpartitioned
`native_*`/`source_*` tables, the global advisory-lock namespace and the Swift
spool remain exactly as `tests/architecture/test_user_owned_tables_are_partitioned.py`
records them; that registry required **no edit**, and it still passes in both
directions.

What changed is that the reason the residual is safe is now executable rather
than a sentence. `test_the_native_source_plane_is_reachable_from_no_transport`
measures both halves of the unreachability claim:

* `NativeSourceController` has **zero** references anywhere in **`src/`, `apps/`,
  `scripts/`, `migrations/` or `ops/`** outside the two modules that define the
  native plane — no gateway, no worker, no HTTP route, no MCP tool, no CLI
  command constructs it;
* every transport refuses a `native_sources.*` capability name outright —
  `adapters/normalization.py` raises `UnsupportedError` for the native vocabulary
  rather than routing it.

The first half is scanned over every production root, not over `src/my_pa`. As
originally written this guard read the package only, and independent review
demonstrated the blind spot by planting the import in `apps/gateway.py` — the
real gateway entrypoint — and watching the guard stay green. `apps/gateway.py`,
`apps/worker.py` and `apps/cli/` are precisely where a wiring would land, so a
guard that could not see them was measuring the wrong tree.
`test_the_reachability_scan_reads_every_production_root` now asserts by example
that those files are inside the scan.

If either half stops being true, the quarantine stops describing a vacuous
residual and becomes a live §18 isolation failure — and now something goes red at
that moment rather than at review time. Reversions 2 and 5 above prove the guard
bites, 5 at the entrypoint that used to be invisible to it.

**No two-Principal negative test is offered, and none is claimed**, because
nothing was principal-scoped. Partitioning the native plane remains its own
package; it needs a migration across 22 tables and a per-Principal advisory-lock
namespace, and doing a subset would join partitioned children to unpartitioned
parents (D-09's measured premise).

**Not disturbed:** D-12's 484-table vacuum, the D-15 pin, and
`metadata.principal_id` — still read nowhere in production. **The relationship
plane was not touched**, so WP-12 NOTEs 5/6/7 are not triggered.

---

## Preserved WP-12E work — disposition

Evaluated from `git show b2d597927a6b548830a1ed16340f8d19925496a1` against the
current lineage, item by item.

> **This table was wrong at `9e974de`, and the correction is the port rather than
> a downgraded row.** The three PORT rows below described work that was *not in
> the tree*: `git diff --name-only 9428c761..HEAD` touched no file under
> `src/my_pa`, and `maximumPageSize`, `maximumCursorBytes` and
> `NATIVE_SOURCE_MAX_PAGE_SIZE` appeared nowhere. Commit `9e974de`'s message
> ("Three items ported, nine declined") overstated for the same reason. Commit
> messages are immutable and that one has not been amended; **the commit that
> carries this paragraph is the commit that makes the claim true**, by actually
> porting the three items with the preserved literals. The row's own argument —
> an unbounded page is an unbounded spool item, which is WP-15's acceptance —
> is why the honest fix was to do the work rather than to argue the acceptance
> away.

| Item | Disposition | Reason |
|---|---|---|
| `NativeSourceProtocolV1.swift` page/cursor bounds (`maximumPageSize = 100`, `maximumCursorBytes = 512`) | **PORTED** | Bounding the read protocol is WP-15's own acceptance ("spool bounded"), and an unbounded page is an unbounded spool item. Ported with the same frozen literals, enforced on `NativeReadRequest.limit`, on `NativeReadCursor`'s UTF-8 byte count and on `NativeReadPage.records` — all three by `throw`, and on the decode paths as well as the initialisers. Stricter than the preserved draft in one place: the draft's `precondition` on the page became a thrown `invalidPageLimit`, because a trap cannot be tested and a truncation would lose records silently (§28). See control 3b. |
| `contracts/v1/native_sources.py` envelope bounds (`records` max length, `next_cursor` max length) | **PORTED** | The application-side half of the same bound. Without it the Swift bound is advisory, because the application would accept a page the host would not have produced. `next_cursor` is additionally bounded by **UTF-8 byte** count in the model validator, so a multi-byte cursor cannot pass the application and fail the host. |
| `NATIVE_SOURCE_MAX_PAGE_SIZE` constant | **PORTED** | Required by the above, together with `NATIVE_SOURCE_MAX_CURSOR_BYTES` for the cursor half. Both are held equal to the Swift literals by `test_the_frozen_bounds_are_the_same_literals_on_both_sides_of_the_boundary`, which reads them out of the Swift source — a bound the two sides disagree about is not a bound. |
| `application/native_sources.py::read_and_admit_page` + `NativeReadPageReceipt` | **DECLINE** | It is a baseline-worker driver: it issues a SYNC grant, reads a page and advances a checkpoint. That is WP-20/WP-21 (frozen baseline, backfill, watchers), not host foundation. Porting it here would import the checkpoint plane WP-15 has no acceptance criteria for. |
| `application/native_sources.py::adapter_identity` | **DECLINE** | Only meaningful as an input to the frozen baseline run record it feeds. Dead weight without the run. |
| `infrastructure/persistence/native_sources.py` `SqlNativeBaselineStore` (+724) — `prepare`/`claim`/`resume_point`/`checkpoint_admitted_page`/`finish`/`complete` | **DECLINE** | The entire WP-20 baseline plane, and it cannot land without revision `a7c3e8d1f642`. It also adds tables to a plane that is currently quarantined *because nothing reaches it*; landing a worker would create the reachability this package's guard exists to prevent. |
| `migrations/versions/…a7c3e8d1f642_freeze_native_baseline_runs.py` (+483) | **DECLINE (not re-authored)** | WP-03 attempted and reverted it as application-incompatible. Re-authoring it forward would be correct **only** with the application half above, which is declined. Re-authoring the schema with nothing reading it would add 4 altered tables and a widened CHECK to a quarantined plane for no proved behaviour — the opposite of §17's intent. **No migration was added by WP-15; the chain is untouched at a single head.** |
| `domain/native_sources/models.py` — `NativeRunState.RUNNING` | **DECLINE, and it is the sharp one** | `tables.py` derives **two** CHECKs from this one enum (`native_run_state_is_known`, `native_bucket_run_state_is_known`) and `a7c3e8d1f642` widens only the first. Adding `RUNNING` desyncs the second. **A previous version of this row explained that with a claim about the parity guard that is false**, and it is corrected here rather than dropped, because the next owner would otherwise be reassured about the wrong thing: `tests/schema/test_every_revision_denotes_one_schema.py:166-167` compares `pg_get_constraintdef(con.oid)` — *definitions*, not names. What it compares them *between* is a database freshly built at a revision's parent and one that went up and came back down, so an `upgrade`/`downgrade` pair that widens and re-narrows one CHECK round-trips perfectly and the desync survives it untouched. The comparison that is name-only is elsewhere: `tests/schema/test_native_source_schema_migration.py:228` selects `con.conname`. Whether some third guard would catch the desync was not measured here, and the next owner should measure rather than assume. This is WP-03 backlog item 7, and it is still owned by whoever reschedules WP-12E's baseline half. WP-15 does not take it, and does not weaken the guard to hide it. |
| `domain/native_sources/models.py` — `NativeRun.bridge_id`/`adapter_identity`/`adapter_kinds`, `NativeCheckpoint.job_id`/`admission_authority_id`/`terminal`/`item_count` | **DECLINE** | Fields of the baseline run/checkpoint records above. Same package, same reason. |
| `application/native_baseline.py`, `contracts/native_baseline.py`, `tests/unit/test_wp12_slice_e_baseline.py` | **DECLINE** | WP-20's subject in full. |
| `tests/schema/test_wp12_slice_c_admission.py` (+1530), `tests/unit/test_wp12_slice_c_application.py` (+86) | **DECLINE as a port; RE-AUTHOR in effect** | Almost all of it exercises the declined baseline store. The behaviour WP-15 needed from that surface — replay producing no duplicate at the real database — is proved by tests written against the *current* persistence rather than ported against the absent one. |
| `.ai/goals/**`, `README.md`, `docs/plans/mcv-completion-plan.md` deltas | **DECLINE** | Status prose for a slice that did not land. Porting it would assert completion that does not exist. |

The preserved branch `bf/wp-12e-slice-e-wip` at `b2d5979` is untouched and remains
the record for whoever schedules WP-20.

---

## What WP-15 deliberately did not do

* **No migration.** The Alembic chain is unchanged: 26 revision files, single head
  `8f2b6c4d1a37`.
* **No un-quarantining**, no principal scoping, no registry edit.
* **No signing, notarization, entitlement, TCC prompt or service registration.**
* **No live personal data.** Nothing read the operator's Mail, Calendar or
  Contacts. Every fixture in this package is obviously synthetic.
* **No transport wiring for the native plane.** Making the host reachable is the
  step that turns the quarantine from vacuous into live, and it must be paired
  with the partitioning package, not with this one.
* **No Graph anything.** Graph remains off by default.

---

## Corrections applied after independent review

Independent review of `9e974de` returned one blocker and a set of notes. What
changed, and what deliberately did not:

| Finding | Disposition |
|---|---|
| **Blocker — three PORT rows described work absent from the tree** | Fixed by **doing the port**, not by downgrading the rows. See the blockquote above the disposition table and control 3b. |
| Quarantine-reachability guard scanned `src/my_pa` only; a plant in `apps/gateway.py` stayed green | Scan widened to every production root, with `test_the_reachability_scan_reads_every_production_root` asserting the entrypoints are inside it. Re-planted, observed red, reverted (reversion 5). |
| An existing test's Principal authority had been broadened without need | `test_merged_swift_synthetic_host_drives_discovery_preflight_and_admission` restored to `frozenset({SOURCE_A})`. Its configuration selects `BUCKET_A` only, so single-source authority is exactly what it should demonstrate; a wider input set is a weaker claim. |
| Near-vacuous disjunct in one assertion | **Accepted, not fixed** — carried to the campaign brief as a standing NOTE. |
| Credential scan named framework-level network types but not raw Darwin primitives | `socket(`, `connect(`, `bind(` added to `CREDENTIAL_SURFACE`. Process-start symbols (`posix_spawn`, `Process(`, `NSTask`, `execve`, `fork(`) are held in a separate `PROCESS_SPAWN_SURFACE` scanned over the **shipping target**, because the contract-check executable re-runs itself to prove the spool's cross-process lock and a cross-process property cannot be proved from one process. The tree was clean either way; this closes the guard rather than fixing a leak. |
| Control 1 scanned one directory while control 2 scanned the tree | Control 1 now scans every Swift file under `native/` except the compatibility probe, which has its own test. A second source directory can no longer stale it. |
| Probe header said "every reference is to a metatype"; `calendarEntity` is an enum case | Sentence corrected in the Swift header and in this record. Nothing is instantiated either way. |
| `NativeRunState.RUNNING` decline cited the wrong reason | The decline stands; the false sub-claim about the parity guard is corrected in place, in the row itself. |
| `ruff format --check` reported "583 files"; the observation is 584 | Corrected in the table below. |

**One existing assertion's expected value moved, and it moved upward.**
`tests/architecture/test_wp12_slice_d_native_host.py` requires an explicit
validating `init(from:)` for every invariant-bearing wire value in the protocol
file, and asserted the count was five. Giving `NativeReadPage` a bound gave it an
invariant, and the bound would have held for values built in Swift and not for
the same values arriving as JSON without a decoder of its own — so the decoder
was written and the count is now six. The guard demands one more validating
decoder than before, which is the only direction it can move without deleting
one.

---

## Verification at this head

| Command | Exit | Observed |
|---|---|---|
| `swift build --package-path native/apple-source-host` | 0 | `Build complete!`, zero warnings, zero errors |
| `.build/debug/AppleSourceHostContractChecks` | 0 | `AppleSourceHostContractChecks: PASS (14 checks)` (was 10 at the base, 13 at `9e974de`) |
| `.build/debug/AppleSourceHostFixtureExport` | 0 | six-key JSON export including the spool item and spool health |
| `pytest tests/architecture -q` | 1 | **2032 passed, 1 failed** (was 2030/1 at `9e974de`) — the known unowned `web/node_modules` failure only |
| `pytest tests/schema tests/database -q` | 0 | **286 passed** (was 285 at the base) |
| `pytest -q` (full) | 1 | **4636 passed, 1 failed, 0 errors** (was 4615/1 at the base, 4632/1 at `9e974de`) — same single known failure |
| `ruff check .` | 0 | All checks passed |
| `ruff format --check .` | 0 | 584 files already formatted (the earlier "583" in this table was a miscount) |
| `mypy` | 0 | no issues in 177 source files |
| `alembic heads` | 0 | `8f2b6c4d1a37 (head)` over 26 revision files — unchanged |

Two pre-existing documentation defects surfaced and were corrected: a rotted
citation in `CAMPAIGN-BRIEF.md`, whose WP-13 section named a line range ending
one line past the end of the 744-line file it cites — already red at the base
head, confirmed by re-running with only this package's brief edit stashed and the spelled test-module count in `docs/plans/mcv-completion-plan.md`
that adding one module made stale. Neither guard was weakened.
