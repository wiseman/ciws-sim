// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "CIWSSimulation",
    platforms: [.macOS(.v15), .visionOS(.v2)],
    products: [
        .library(name: "CIWSSimulation", targets: ["CIWSSimulation"]),
        .library(name: "CIWSSound", targets: ["CIWSSound"])
    ],
    targets: [
        .target(name: "CIWSSimulation", resources: [.process("Resources")]),
        // Real-time synthesis: optimized in every configuration
        .target(name: "CIWSSound", swiftSettings: [.unsafeFlags(["-O"])]),
        .testTarget(name: "CIWSSimulationTests", dependencies: ["CIWSSimulation", "CIWSSound"], resources: [.process("Fixtures")])
    ]
)
