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
target. A failure throws and exits nonzero. Thirteen checks cover version mismatch,
multi-account label collisions, exact preflight identity, deterministic
handoff, recurrence exceptions/cancellation/bounds, atomic spool lifecycle,
owner-only modes, idempotency, item/byte/payload backpressure, injected crash
residue, recovery, acknowledgement, quarantine retention, malformed wire and
storage bytes, recurrence-bound overflow, root/child-directory substitution, `stat`-verified
0700/0600 owner-only modes with a refused enqueue leaving the inventory intact,
lifecycle transition refusal, and content-free telemetry against a planted
marker. Repository
architecture tests independently scan dependencies, imports, configuration and
public surfaces.

Live framework adapters, TCC, signing/notarization, registration, application
admission, persistence, watchers, service activation, and deployment remain
outside this package and require their owning later slice and authority.
