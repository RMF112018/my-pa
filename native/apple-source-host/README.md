# Apple source host protocol boundary

This Swift 6.2 package is the native-host foundation for Apple Mail, Calendar,
Contacts, and Tasks source reads. It retains WP-12A's frozen protocol
identifier `my-pa.native-source.v1`, provider-neutral immutable values, three
read-only adapter protocols plus the bounded Tasks seam, and deterministic
synthetic adapters.

WP-12D supplied the application-facing envelope/spool foundations. The current
candidate also supplies a separately bounded production composition with a
non-live proof path and an independently authorized single-pass read path:

- deterministic, versioned discovery, preflight, read, and handoff envelopes;
- explicit fail-closed decoding for every invariant-bearing wire/storage value;
- stable opaque account, bucket, series, and occurrence identities that do not
  derive from display labels or private provider locators;
- a closed, content-free provider-failure vocabulary;
- exact selected-bucket preflight results, including synthetic permission and
  identity-drift plants;
- bounded synthetic recurrence expansion that preserves series, scheduled
  occurrence, exception, and timezone identity; and
- an owner-only atomic local spool with explicit item/payload/byte limits,
  deterministic inventory, backpressure, synchronized temporary files,
  exclusive rename, acknowledgement, retained quarantine, and retained crash
  residue recovery. Directory descriptors and device/inode identities remain
  pinned for the spool lifetime; item operations are descriptor-relative and
  fail closed if the visible root or child namespace is substituted. Same-root
  instances share one reference-counted process-lock descriptor, so destroying
  a peer cannot release an operation's cross-process lock.

WP-15 adds the production-shaped foundation around that:

- an explicit host **lifecycle** (`HostLifecycle.swift`) — `constructed →
  protocolNegotiated → spoolOpened → readyForHandoff`, plus `refused` and
  `stopped` — where every transition is named and anything unnamed is refused, so
  a host cannot reach handoff without agreeing the frozen protocol version;
- **content-free operational telemetry** (`HostTelemetry.swift`): a closed event
  vocabulary, a closed host-error class that classifies an error without quoting
  it, and a spool health report of counts against the configured bounds. No type
  in that file declares a free-form `String` field, so a health endpoint, metric
  or log line has nowhere to put a subject line, a message body, a contact value
  or a filesystem path;
- a **compile-only framework-compatibility probe**
  (`Compatibility/AppleFrameworkCompatibilityProbe`) that resolves EventKit,
  Contacts, MailKit and ServiceManagement symbols as metatypes. It is not a
  dependency of the shipping target, instantiates nothing, requests no
  permission, and registers no service. It answers OD-COMP-009's "prove framework
  compatibility" and nothing else. **MailKit links but exposes no store, account
  enumeration or message query** — it is an extension-point framework, so
  compatibility there is not Mail readability.

WP-16 adds the Mail adapter, over a mechanism seam rather than over a framework:

- `MailMechanism.swift` — the closed, five-operation read seam a live mechanism
  would implement, plus the identity, day-window and attachment values. A message
  identity carries its **generation**, because a provider key means nothing
  outside the generation that issued it, and a mechanism that publishes no
  generation is refused before it is read from;
- `BoundedMailReadAdapter.swift` — the adapter, which holds every refusal:
  consent before the first read, a date bound that must reach the source or be
  refused, strict key ordering for the cursor, and content bounds that omit and
  mark or refuse and never trim. A carried body must equal its declared size, on
  the wire as well as in Swift, so a truncated body is not a representable value;
- `FixtureMailMechanism.swift` — the in-process fixture, IMAP-shaped, with three
  injectable mechanism faults and call counters, so "nothing was read after a
  refusal" is a measured number. Every fixture value is obviously synthetic;
- `Compatibility/AppleMailAutomationShapeProbe` — a second compile-only probe, on
  the same footing as the first, that imports `ScriptingBridge` and carries Apple
  Mail's scripting terminology as a data table. It constructs no `SBApplication`,
  compiles no script and **sends no Apple event**. Its table is checked against
  Apple's own `Mail.sdef` by the repository's architecture tests.

**Neither probe is a dependency of anything else in this package**, so probes
remain compile-only. The framework-free `AppleSourceHost` target still links no
Apple personal-data framework. The separately named shipping product
`AppleSourceHostPlatform` now links EventKit, Contacts, and ScriptingBridge and
contains the production-shaped, read-only Calendar, Contacts, Tasks, and Mail
mechanisms; it depends only
on the framework-free core. See
`docs/campaign/WP-16-MAIL-ADAPTER-RECORD.md` for the mechanism matrix and for why
Apple Mail automation cannot be scoped to reading.

The package declares `platforms: [.macOS(.v13)]` because `SMAppService` is macOS
13+ and MailKit is macOS 12+.

The package has no external package dependency. Its platform target accepts
injected `EKEventStore` and `CNContactStore` values, observes authorization,
uses EventKit's bounded event predicate, requests only the Contacts identifier
and structural-type keys, preserves container/group membership, and maps into
the same bounded adapters used by fixtures. Its composition initializer creates
no store, requests no permission, registers no observer, and performs no read.
It carries Calendar/Contacts change-notification names as inert watcher signals.
Mail is implemented through the closed ScriptingBridge read-property mechanism
and remains separately operator-gated because macOS Automation cannot scope the
grant to reads. Its source-side predicate, materialization count, recursive
mailbox depth, message-size/body, header, and attachment bounds all refuse
rather than widen. Graph remains off by default and is not a silent substitute.

The `apple-source-host handoff --dry-run` executable reads absolute regular-file
configuration/checkpoint inputs through `openat(O_NOFOLLOW)` with per-file,
aggregate-byte, selection, and checkpoint caps; constructs the production
composition; resolves only inert adapter descriptors; and writes one
content-free receipt per selection to an explicitly targeted owner-only
`ProtectedSpool` with explicit item/byte/payload limits. It never observes TCC,
discovers an account, enumerates a source, reads personal data, or activates a
watcher. The spool artifact is proof of protected handoff reachability, not data
admission authority.

The separate `handoff --authorized-single-pass` path additionally requires an
absolute, bounded, expiring `my-pa.apple-source-read-grant.v1` artifact whose
configuration identity matches and whose authorization literal is exact. Only
then does it negotiate the lifecycle, open the protected spool, read one
checkpointed bounded page from each selected Calendar, Contacts, Tasks, or Mail
bucket, wrap the page in a versioned immutable admission envelope, and enqueue
it for application pickup. Merely setting `activationRequested` is refused.
This repository implements that operator-gated lifecycle but did not invoke it:
no TCC grant or live personal-data access was authorized for validation.

No repository validation inspects a live account. TCC grants, signing,
installation, service/watcher activation, application admission, persistence,
and live data remain operator-gated. Neither platform mechanism names a save,
remove, commit, save request, consent request, database, network client, or
source mutation. The spool stores only explicitly supplied handoff bytes and has
no application, database, or network client.

Run its bounded validation with:

```sh
swift run --package-path native/apple-source-host AppleSourceHostContractChecks
swift build -c release --package-path native/apple-source-host
```

The installed Swift 6.2 toolchain does not include `XCTest` or the Swift
`Testing` module, so the contract checks are a dependency-free executable test
target. A failure throws and exits nonzero. Thirty-seven checks cover version mismatch,
multi-account label collisions, exact preflight identity, deterministic
handoff, recurrence exceptions/cancellation/bounds, atomic spool lifecycle,
owner-only modes, idempotency, item/byte/payload backpressure, injected crash
residue, recovery, acknowledgement, quarantine retention, malformed wire and
storage bytes, recurrence-bound overflow, root/child-directory substitution, `stat`-verified
0700/0600 owner-only modes with a refused enqueue leaving the inventory intact,
lifecycle transition refusal, content-free telemetry against a planted
marker, and — for the Mail adapter — consent gating measured by call count,
identity stability across reads and across a sync cycle with the generation
change proving the negative, source-side date bounding with a lying mechanism
caught, body and attachment bounds on the wire as well as in Swift, an
attachment descriptor whose oversize label is required off the wire and not
only on its initialiser, and cursor
ordering; Calendar authorization, identity, recurrence, timezone, horizon and
wire bounds; the frozen minimum Contacts key set, epoch-bearing identity,
container/group membership, revocation, pagination and wire bounds; and the
bounded read-only Tasks adapter. Repository
architecture tests independently scan dependencies, imports, configuration and
public surfaces.

TCC grants, signing/notarization, registration, execution against live sources,
database persistence, watcher registration, service activation, and deployment
remain outside the validation performed here and require exact operator
authority. The dry-run executable's inert framework-store construction and
content-free protected receipt grant none of those actions, and the active path
refuses without its separate exact grant.
