// swift-tools-version:5.9
// Tests de la géométrie et du modèle de visite de l'app, lancés sur le Mac par `swift test`
// depuis ce dossier.
// L'app elle-même se construit avec Visite360Capture.xcodeproj.

import PackageDescription

let package = Package(
    name: "CaptureGeometry",
    platforms: [.macOS(.v13)],
    targets: [
        .target(
            name: "CaptureGeometry", path: "Visite360Capture", sources: ["Geometry", "Model"]
        ),
        .testTarget(
            name: "CaptureGeometryTests",
            dependencies: ["CaptureGeometry"],
            path: "Tests/CaptureGeometryTests"
        ),
    ]
)
