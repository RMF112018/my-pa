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
| 1 | Host is source-read-only | **Static guard over the shipping Swift target** (Python architecture test) + **Swift compile-time** (no framework is linked, so no mutating type exists to call) | `tests/architecture/test_wp15_native_host_admission.py::test_the_shipping_host_holds_no_write_path_into_an_apple_source`, `::test_the_read_only_boundary_declares_no_mutating_operation`, `::test_no_write_capable_entitlement_or_usage_declaration_exists` |
| 2 | Host holds no DB credential | **Static guard over the whole `native/**` tree**, including `Package.swift` | `::test_the_host_cannot_reach_a_database_or_read_a_credential`, `::test_the_host_package_declares_no_dependency_and_links_no_library` |
| 3 | Spool owner-only / bounded / atomic | **Swift runtime** (`stat` at runtime on a real spool) + static guard on the refusal paths | `AppleSourceHostContractChecks::checkSpoolItemsAreOwnerOnlyRegularFiles`, `::checkProtectedSpoolLifecycle`, `::checkProtectedSpoolFaultsAndBounds`; `::test_the_spool_bounds_exist_and_refuse_rather_than_evict` |
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

## Non-vacuity — three controlled reversions, observed and reverted

Each was planted, observed failing for the intended reason, and reverted. The
tree contains none of them.

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
their read-oriented symbols as *metatypes only*. It compiles clean. The package
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

* `NativeSourceController` has **zero** references anywhere in `src/my_pa`
  outside the two modules that define the native plane — no gateway, no HTTP
  route, no MCP tool, no CLI command constructs it;
* every transport refuses a `native_sources.*` capability name outright —
  `adapters/normalization.py` raises `UnsupportedError` for the native vocabulary
  rather than routing it.

If either half stops being true, the quarantine stops describing a vacuous
residual and becomes a live §18 isolation failure — and now something goes red at
that moment rather than at review time. Reversion 2 above proves the guard bites.

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

| Item | Disposition | Reason |
|---|---|---|
| `NativeSourceProtocolV1.swift` page/cursor bounds (`maximumPageSize = 100`, `maximumCursorBytes = 512`) | **PORT** | Bounding the read protocol is WP-15's own acceptance ("spool bounded"), and an unbounded page is an unbounded spool item. Ported with the same frozen literals. |
| `contracts/v1/native_sources.py` envelope bounds (`records` max length, `next_cursor` max length) | **PORT** | The application-side half of the same bound. Without it the Swift bound is advisory, because the application would accept a page the host would not have produced. |
| `NATIVE_SOURCE_MAX_PAGE_SIZE` constant | **PORT** | Required by the above. |
| `application/native_sources.py::read_and_admit_page` + `NativeReadPageReceipt` | **DECLINE** | It is a baseline-worker driver: it issues a SYNC grant, reads a page and advances a checkpoint. That is WP-20/WP-21 (frozen baseline, backfill, watchers), not host foundation. Porting it here would import the checkpoint plane WP-15 has no acceptance criteria for. |
| `application/native_sources.py::adapter_identity` | **DECLINE** | Only meaningful as an input to the frozen baseline run record it feeds. Dead weight without the run. |
| `infrastructure/persistence/native_sources.py` `SqlNativeBaselineStore` (+724) — `prepare`/`claim`/`resume_point`/`checkpoint_admitted_page`/`finish`/`complete` | **DECLINE** | The entire WP-20 baseline plane, and it cannot land without revision `a7c3e8d1f642`. It also adds tables to a plane that is currently quarantined *because nothing reaches it*; landing a worker would create the reachability this package's guard exists to prevent. |
| `migrations/versions/…a7c3e8d1f642_freeze_native_baseline_runs.py` (+483) | **DECLINE (not re-authored)** | WP-03 attempted and reverted it as application-incompatible. Re-authoring it forward would be correct **only** with the application half above, which is declined. Re-authoring the schema with nothing reading it would add 4 altered tables and a widened CHECK to a quarantined plane for no proved behaviour — the opposite of §17's intent. **No migration was added by WP-15; the chain is untouched at a single head.** |
| `domain/native_sources/models.py` — `NativeRunState.RUNNING` | **DECLINE, and it is the sharp one** | `tables.py` derives **two** CHECKs from this one enum (`native_run_state_is_known`, `native_bucket_run_state_is_known`) and `a7c3e8d1f642` widens only the first. Adding `RUNNING` desyncs the second and **no current test catches it** — the parity guard compares constraint *names*, not definitions. This is WP-03 backlog item 7, and it is still owned by whoever reschedules WP-12E's baseline half. WP-15 does not take it, and does not weaken the guard to hide it. |
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

## Verification at this head

| Command | Exit | Observed |
|---|---|---|
| `swift build --package-path native/apple-source-host` | 0 | `Build complete!`, zero warnings, zero errors |
| `.build/debug/AppleSourceHostContractChecks` | 0 | `AppleSourceHostContractChecks: PASS (13 checks)` (was 10) |
| `.build/debug/AppleSourceHostFixtureExport` | 0 | six-key JSON export including the spool item and spool health |
| `pytest tests/architecture -q` | 1 | **2030 passed, 1 failed** — the known unowned `web/node_modules` failure only |
| `pytest tests/schema tests/database -q` | 0 | **286 passed** (was 285) |
| `pytest -q` (full) | 1 | **4632 passed, 1 failed, 0 errors** (was 4615/1) — same single known failure |
| `ruff check .` | 0 | All checks passed |
| `ruff format --check .` | 0 | 583 files already formatted |
| `mypy` | 0 | no issues in 177 source files |
| `alembic heads` | 0 | `8f2b6c4d1a37 (head)` over 26 revision files — unchanged |

Two pre-existing documentation defects surfaced and were corrected: a rotted
citation in `CAMPAIGN-BRIEF.md`, whose WP-13 section named a line range ending
one line past the end of the 744-line file it cites — already red at the base
head, confirmed by re-running with only this package's brief edit stashed and the spelled test-module count in `docs/plans/mcv-completion-plan.md`
that adding one module made stale. Neither guard was weakened.
