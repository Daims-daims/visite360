import XCTest
import simd

@testable import CaptureGeometry

/// Téléphone tenu droit en portrait, objectif arrière vers +Y de la référence de Core Motion.
private let upright = simd_double3x3(columns: (
    SIMD3(1, 0, 0),   // x de l'écran → X (à droite)
    SIMD3(0, 0, 1),   // haut de l'écran → Z (vers le haut)
    SIMD3(0, -1, 0)   // sortie de l'écran → -Y (vers le photographe)
))

private func aroundZ(_ degrees: Double) -> simd_double3x3 {
    simd_double3x3(simd_quatd(angle: degrees * .pi / 180, axis: SIMD3(0, 0, 1)))
}

private func aroundX(_ degrees: Double) -> simd_double3x3 {
    simd_double3x3(simd_quatd(angle: degrees * .pi / 180, axis: SIMD3(1, 0, 0)))
}

/// Gravité que mesurerait l'appareil, dans son propre repère, en g.
private func gravity(_ deviceToReference: simd_double3x3) -> SIMD3<Double> {
    deviceToReference.transpose * SIMD3(0, 0, -1)
}

private func world(_ deviceToReference: simd_double3x3) -> simd_double3x3 {
    let measured = Orientation.deviceToReference(
        quaternion: simd_quatd(deviceToReference), gravity: gravity(deviceToReference)
    )
    return Orientation.cameraToWorld(deviceToReference: measured)
}

final class GeometryTests: XCTestCase {
    func testUprightPhoneLooksForwardAtTheHorizon() {
        let rotation = world(upright)
        XCTAssertEqual(Orientation.yaw(rotation), 0, accuracy: 1e-9)
        XCTAssertEqual(Orientation.pitch(rotation), 0, accuracy: 1e-9)
        XCTAssertEqual(Orientation.roll(rotation) ?? 99, 0, accuracy: 1e-9)
        // Même convention que spherical.py : haut de l'image vers -y, droite vers +x.
        XCTAssertEqual(simd_length(rotation * SIMD3(0, -1, 0) - SIMD3(0, -1, 0)), 0, accuracy: 1e-9)
        XCTAssertEqual(simd_length(rotation * SIMD3(1, 0, 0) - SIMD3(1, 0, 0)), 0, accuracy: 1e-9)
    }

    func testTurningRightIncreasesYaw() {
        // Vu d'en haut, tourner vers la droite est une rotation horaire autour de Z.
        let rotation = world(aroundZ(-30) * upright)
        XCTAssertEqual(Orientation.yaw(rotation), 30, accuracy: 1e-9)
        XCTAssertEqual(Orientation.pitch(rotation), 0, accuracy: 1e-9)
    }

    func testTiltingUpIncreasesPitch() {
        let rotation = world(aroundZ(-90) * aroundX(45) * upright)
        XCTAssertEqual(Orientation.pitch(rotation), 45, accuracy: 1e-9)
        XCTAssertEqual(Orientation.yaw(rotation), 90, accuracy: 1e-9)
        XCTAssertEqual(Orientation.roll(rotation) ?? 99, 0, accuracy: 1e-9)
    }

    func testTransposedAttitudeIsDetectedByGravity() {
        let attitude = aroundZ(-60) * aroundX(30) * upright
        let fromTranspose = Orientation.deviceToReference(
            quaternion: simd_quatd(attitude.transpose), gravity: gravity(attitude)
        )
        XCTAssertEqual(simd_length(fromTranspose.columns.0 - attitude.columns.0), 0, accuracy: 1e-9)
        XCTAssertEqual(simd_length(fromTranspose.columns.2 - attitude.columns.2), 0, accuracy: 1e-9)
    }

    func testRotationMatchesTargetDirection() {
        let target = Target(id: 0, row: .haut, number: 3, yaw: 90, pitch: 45)
        let rotation = world(aroundZ(-90) * aroundX(45) * upright)
        XCTAssertEqual(Orientation.angle(Orientation.forward(rotation), target.direction), 0, accuracy: 1e-9)
        XCTAssertTrue(Aiming().isAligned(target, rotation: rotation))
    }

    func testTiltedPhoneIsNotAligned() {
        let target = Target(id: 0, row: .horizon, number: 1, yaw: 0, pitch: 0)
        // Penché de 20° sur le côté : rotation autour de l'axe de l'objectif (-Y).
        let tilted = simd_double3x3(simd_quatd(angle: 20 * .pi / 180, axis: SIMD3(0, 1, 0)))
        let rotation = world(tilted * upright)
        XCTAssertEqual(abs(Orientation.roll(rotation) ?? 0), 20, accuracy: 1e-9)
        XCTAssertFalse(Aiming().isAligned(target, rotation: rotation))
    }

    func testCeilingIgnoresRoll() {
        let target = Target(id: 0, row: .plafond, number: 1, yaw: 0, pitch: 90)
        let rotation = world(aroundZ(70) * aroundX(90) * upright)
        XCTAssertNil(Orientation.roll(rotation))
        XCTAssertTrue(Aiming().isAligned(target, rotation: rotation))
    }

    func testPlanFollowsTheShootingGuide() {
        let targets = Plan.targets(startYaw: 170)
        XCTAssertEqual(targets.count, 30)
        XCTAssertEqual(targets.filter { $0.row == .horizon }.count, 12)
        XCTAssertEqual(targets[0].yaw, 170, accuracy: 1e-9)
        XCTAssertEqual(targets[1].yaw, -160, accuracy: 1e-9)
        XCTAssertEqual(targets.filter { $0.row.isOptional }.map(\.row), [.sol])
    }

    func testNearestSkipsDoneTargets() {
        let targets = Plan.targets(startYaw: 0)
        let rotation = world(upright)
        XCTAssertEqual(Aiming().nearest(targets, done: [], rotation: rotation)?.target.id, 0)
        let next = Aiming().nearest(targets, done: [0], rotation: rotation)
        XCTAssertEqual(next?.target.row, .horizon)
        XCTAssertEqual(next?.angle ?? 0, 30, accuracy: 1e-9)
    }

    func testProjectionPutsTargetToTheRightOfCenter() {
        let rotation = world(upright)
        let point = Orientation.project(Orientation.direction(yaw: 10, pitch: 5), rotation: rotation, focal: 100)
        XCTAssertNotNil(point)
        XCTAssertGreaterThan(point!.x, 0)
        XCTAssertLessThan(point!.y, 0)
        XCTAssertNil(Orientation.project(Orientation.direction(yaw: 180, pitch: 0), rotation: rotation, focal: 100))
    }

    func testRowsAreWrittenLineByLine() {
        let rotation = world(aroundZ(-30) * upright)
        let rows = Orientation.rows(rotation)
        let axis = Orientation.forward(rotation)
        XCTAssertEqual(rows[0][2], axis.x, accuracy: 1e-12)
        XCTAssertEqual(rows[1][2], axis.y, accuracy: 1e-12)
        XCTAssertEqual(rows[2][2], axis.z, accuracy: 1e-12)
    }
}
