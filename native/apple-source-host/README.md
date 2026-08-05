# Apple source host protocol boundary

This Swift 6.2 package is the WP-12A compile-time feasibility boundary for
Apple Mail, Calendar, and Contacts source reads. It freezes protocol identifier
`my-pa.native-source.v1`, provider-neutral immutable values, three read-only
adapter protocols, and deterministic synthetic adapters.

The package has no external dependency and its production target imports no
Apple personal-data framework. It does not request permissions, inspect an
account, install or activate a service, open a network or database connection,
or mutate a source. Its synthetic adapters are contract fixtures, not evidence
that a live adapter is feasible.

Run its bounded validation with:

```sh
swift run --package-path native/apple-source-host AppleSourceHostContractChecks
```

The installed Swift 6.2 toolchain does not include `XCTest` or the Swift
`Testing` module, so the contract checks are a dependency-free executable test
target. A failure throws and exits nonzero. The repository's
`test_wp12_slice_a_checkpoint.py` supplies the independent structural scan for
forbidden imports, dependencies, symbols, and mutation methods.

Live framework adapters, TCC, signing/notarization, registration, protected
spooling, application admission, persistence, watchers, and deployment remain
outside WP-12A and require their owning later slice and authority.
