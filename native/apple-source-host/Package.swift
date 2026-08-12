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
    ],
    targets: [
        .target(name: "AppleSourceHost"),
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
