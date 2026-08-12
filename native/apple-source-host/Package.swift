// swift-tools-version: 6.2

import PackageDescription

let package = Package(
    name: "AppleSourceHost",
    // Declared, not inherited. `SMAppService` — the supported service-lifecycle
    // API of the target distribution model (OD-COMP-009) — is macOS 13+, and
    // MailKit is macOS 12+. Without this the package would silently default to a
    // deployment target on which the compatibility probe cannot compile, and the
    // proof would be that the frameworks are *unavailable* rather than that they
    // are available.
    platforms: [.macOS(.v13)],
    products: [
        .library(name: "AppleSourceHost", targets: ["AppleSourceHost"]),
        // The production-shaped macOS mechanism layer.  It links EventKit and
        // Contacts and is inert until an operator-owned process supplies stores
        // and invokes it.  The core protocol target remains framework-free.
        .library(name: "AppleSourceHostPlatform", targets: ["AppleSourceHostPlatform"]),
        .executable(
            name: "apple-source-host",
            targets: ["AppleSourceHostPlatformHost"]
        ),
    ],
    targets: [
        .target(name: "AppleSourceHost"),
        .target(
            name: "AppleSourceHostPlatform",
            dependencies: ["AppleSourceHost"],
            linkerSettings: [.linkedFramework("ScriptingBridge")]
        ),
        // A runnable, deliberately non-activating host boundary. It validates
        // operator configuration/checkpoints, constructs the inert production
        // composition, and writes content-free dry-run receipts into a protected
        // spool. It never requests TCC, registers observers, or enumerates data.
        .executableTarget(
            name: "AppleSourceHostPlatformHost",
            dependencies: ["AppleSourceHost", "AppleSourceHostPlatform"]
        ),
        // OD-COMP-009 compile-only compatibility probe. Deliberately NOT a
        // dependency of `AppleSourceHost`: the shipping module must keep linking
        // none of these frameworks while every `swift build` still re-proves that
        // they compile on this toolchain.
        .target(
            name: "AppleFrameworkCompatibilityProbe",
            path: "Compatibility/AppleFrameworkCompatibilityProbe"
        ),
        // WP-16 Apple Mail automation shape probe. Same footing and same
        // reason: it imports ScriptingBridge so that every build re-proves the
        // mechanism is *present* — which is what makes "operator-gated" a
        // different statement from "does not exist" — while the shipping module
        // keeps linking nothing. Also deliberately NOT a dependency of
        // `AppleSourceHost`, because ScriptingBridge is the one framework on
        // this machine that can mutate Apple Mail.
        .target(
            name: "AppleMailAutomationShapeProbe",
            path: "Compatibility/AppleMailAutomationShapeProbe"
        ),
        // WP-17 EventKit shape probe. Same footing and the same reason: it
        // imports EventKit so that every build re-proves the calendar read
        // mechanism is *present* — which is what makes "operator-gated" a
        // different statement from "does not exist" — while the shipping module
        // keeps linking nothing. Also deliberately NOT a dependency of
        // `AppleSourceHost`, because EventKit is the framework that can mutate a
        // calendar and the shipping module linking no Apple framework is
        // WP-15's control 1, proved at link time.
        .target(
            name: "AppleCalendarEventKitProbe",
            path: "Compatibility/AppleCalendarEventKitProbe"
        ),
        // WP-18 Contacts shape probe. Same footing and the same reason: it
        // imports Contacts so that every build re-proves the contacts read
        // mechanism is *present* — which is what makes "operator-gated" a
        // different statement from "does not exist" — while the shipping module
        // keeps linking nothing. Also deliberately NOT a dependency of
        // `AppleSourceHost`, because one contact store answers both the read
        // methods and the request that saves, and the shipping module linking no
        // Apple framework is WP-15's control 1, proved at link time.
        .target(
            name: "AppleContactsShapeProbe",
            path: "Compatibility/AppleContactsShapeProbe"
        ),
        // Compile-only EventKit Reminders probe. The shipping library remains
        // framework-free and cannot request TCC or mutate a reminder store.
        .target(
            name: "AppleTasksEventKitProbe",
            path: "Compatibility/AppleTasksEventKitProbe"
        ),
        .executableTarget(
            name: "AppleSourceHostContractChecks",
            dependencies: ["AppleSourceHost"],
            path: "Tests/AppleSourceHostContractChecks"
        ),
        .executableTarget(
            name: "AppleSourceHostFixtureExport",
            dependencies: ["AppleSourceHost"],
            path: "Tests/AppleSourceHostFixtureExport"
        ),
    ]
)
