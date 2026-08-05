// swift-tools-version: 6.2

import PackageDescription

let package = Package(
    name: "AppleSourceHost",
    products: [
        .library(name: "AppleSourceHost", targets: ["AppleSourceHost"]),
    ],
    targets: [
        .target(name: "AppleSourceHost"),
        .executableTarget(
            name: "AppleSourceHostContractChecks",
            dependencies: ["AppleSourceHost"],
            path: "Tests/AppleSourceHostContractChecks"
        ),
    ]
)
