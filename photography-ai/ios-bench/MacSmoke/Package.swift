// swift-tools-version: 6.0
// Runs the iPhone harness's inference code (ModelHost.swift, PromptKit.swift, symlinked from
// ../IOSBench) on a Mac, to check the Swift path end to end before using the phone.
// Build with xcodebuild (plain `swift build` cannot compile MLX's Metal shaders); see README.
import PackageDescription

let package = Package(
    name: "MacSmoke",
    platforms: [.macOS(.v14)],
    dependencies: [
        .package(url: "https://github.com/ml-explore/mlx-swift-lm", exact: "3.32.3"),
        .package(url: "https://github.com/ml-explore/mlx-swift", .upToNextMinor(from: "0.32.3")),
        .package(url: "https://github.com/huggingface/swift-transformers", .upToNextMajor(from: "1.3.0")),
    ],
    targets: [
        .executableTarget(
            name: "MacSmoke",
            dependencies: [
                .product(name: "MLXVLM", package: "mlx-swift-lm"),
                .product(name: "MLXLMCommon", package: "mlx-swift-lm"),
                .product(name: "MLX", package: "mlx-swift"),
                .product(name: "Tokenizers", package: "swift-transformers"),
            ],
            swiftSettings: [.swiftLanguageMode(.v5)]),
    ]
)
