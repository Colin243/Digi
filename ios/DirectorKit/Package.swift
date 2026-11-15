// swift-tools-version: 6.0
import PackageDescription

// Engine-agnostic core of the Photography Director: the shot model, the DirectorEngine
// contract, the privacy-aware upload policy and the online/offline router. It has no MLX or
// network dependency, so it builds and tests on a Mac with `swift test`. The on-device engine
// (mlx-swift-lm) and the online engine (HTTP) live in the app target and conform to
// DirectorEngine.
let package = Package(
    name: "DirectorKit",
    platforms: [.iOS(.v18), .macOS(.v14)],
    products: [.library(name: "DirectorKit", targets: ["DirectorKit"])],
    targets: [
        .target(name: "DirectorKit"),
        .testTarget(name: "DirectorKitTests", dependencies: ["DirectorKit"]),
    ]
)
