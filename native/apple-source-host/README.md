# Apple source host protocol boundary

This Swift 6.2 package is the WP-12D synthetic native-host foundation for Apple
Mail, Calendar, and Contacts source reads. It retains WP-12A's frozen protocol
identifier `my-pa.native-source.v1`, provider-neutral immutable values, three
read-only adapter protocols, and deterministic synthetic adapters.

WP-12D adds the application-facing foundations needed by the later admission
slice without implementing admission itself:

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

**Neither probe is a dependency of anything else in this package**, so the
shipping target still links no Apple framework. See
`docs/campaign/WP-16-MAIL-ADAPTER-RECORD.md` for the mechanism matrix and for why
Apple Mail automation cannot be scoped to reading.

The package declares `platforms: [.macOS(.v13)]` because `SMAppService` is macOS
13+ and MailKit is macOS 12+.

The package has no external dependency and its production target imports no
Apple personal-data framework. It does not request permissions, inspect a live
account, install or activate a service, open a network or database connection,
or mutate a source. Its synthetic adapters are contract fixtures, not evidence
that a live adapter is feasible. The spool stores only explicitly supplied
handoff bytes and has no application, database, or network client.

Run its bounded validation with:

```sh
swift run --package-path native/apple-source-host AppleSourceHostContractChecks
swift build -c release --package-path native/apple-source-host
```

The installed Swift 6.2 toolchain does not include `XCTest` or the Swift
`Testing` module, so the contract checks are a dependency-free executable test
target. A failure throws and exits nonzero. Twenty-one checks cover version mismatch,
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
caught, body and attachment bounds on the wire as well as in Swift, and cursor
ordering. Repository
architecture tests independently scan dependencies, imports, configuration and
public surfaces.

Live framework adapters, TCC, signing/notarization, registration, application
admission, persistence, watchers, service activation, and deployment remain
outside this package and require their owning later slice and authority.
