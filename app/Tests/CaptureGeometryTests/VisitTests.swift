import Foundation
import XCTest

@testable import CaptureGeometry

final class VisitTests: XCTestCase {
    func testArrowAngleIsMeasuredFromTheStartHeading() {
        XCTAssertEqual(ArrowAim.angle(yaw: 120, startYaw: 30), 90)
        XCTAssertEqual(ArrowAim.angle(yaw: -170, startYaw: 170), 20)
        XCTAssertEqual(ArrowAim.angle(yaw: 10, startYaw: -170), 180)
        XCTAssertEqual(ArrowAim.angle(yaw: 12.345, startYaw: 0), 12.3)
        XCTAssertEqual(ArrowAim.pitch(-75), -60)
    }

    func testFolderNamesAreSafe() {
        XCTAssertEqual(FolderName.make(from: "Salle de bains 2"), "salle-de-bains-2")
        XCTAssertEqual(FolderName.make(from: "Entrée"), "entree")
        XCTAssertEqual(FolderName.make(from: "../.."), "point")
    }

    func testPointIdsAreUnique() {
        var visit = VisitFile(name: "Appartement")
        XCTAssertEqual(visit.addPoint(name: "Chambre"), "chambre")
        XCTAssertEqual(visit.addPoint(name: "chambre"), "chambre-2")
    }

    func testExportKeepsTakenPointsAndTheirLinksOnly() throws {
        var visit = VisitFile(name: "Appartement")
        let salon = visit.addPoint(name: "Salon")
        let cuisine = visit.addPoint(name: "Cuisine")
        let chambre = visit.addPoint(name: "Chambre")  // annoncée, pas encore prise
        visit.setLink(from: salon, to: cuisine, angle: 90, pitch: -5)
        visit.setLink(from: salon, to: chambre, angle: -90, pitch: nil)
        visit.setLink(from: salon, to: cuisine, angle: 95, pitch: -5)  // visée refaite

        let exported = visit.exported(taken: [salon, cuisine])

        XCTAssertEqual(exported.points.map(\.id), [salon, cuisine])
        XCTAssertEqual(exported.links, [VisitLink(from: salon, to: cuisine, angle: 95, pitch: -5)])
        XCTAssertEqual(exported.start, salon)
        // Clés attendues par le Mac (src/visite360/visite.py), rien d'autre.
        let json = try JSONSerialization.jsonObject(with: JSONEncoder().encode(exported))
        let object = try XCTUnwrap(json as? [String: Any])
        XCTAssertEqual(Set(object.keys), ["version", "nom", "depart", "points", "liens"])
        let link = try XCTUnwrap((object["liens"] as? [[String: Any]])?.first)
        XCTAssertEqual(Set(link.keys), ["de", "vers", "angle", "hauteur"])
    }

    func testRemovedPointStaysAnnouncedWhileAnArrowLeadsToIt() {
        var visit = VisitFile(name: "Appartement")
        let salon = visit.addPoint(name: "Salon")
        let cuisine = visit.addPoint(name: "Cuisine")
        visit.setLink(from: salon, to: cuisine, angle: 90, pitch: nil)
        visit.setLink(from: cuisine, to: salon, angle: -90, pitch: nil)

        visit.removePoint(cuisine)
        XCTAssertNotNil(visit.point(cuisine))
        XCTAssertEqual(visit.links.count, 1)

        visit.removePoint(salon)
        XCTAssertNil(visit.point(salon))
        XCTAssertTrue(visit.links.isEmpty)
    }

    func testManifestListsVisitFiles() throws {
        let visit = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: visit) }
        let photos = visit.appendingPathComponent("salon/photos", isDirectory: true)
        try FileManager.default.createDirectory(at: photos, withIntermediateDirectories: true)
        try Data("{}".utf8).write(to: visit.appendingPathComponent("visite.json"))
        try Data("{}".utf8).write(to: visit.appendingPathComponent("salon/capture.json"))
        try Data("abc".utf8).write(to: photos.appendingPathComponent("IMG_0002.jpg"))
        try Data("abc".utf8).write(to: photos.appendingPathComponent("IMG_0001.jpg"))
        try Data().write(to: photos.appendingPathComponent(".DS_Store"))

        let items = try Manifest.items(visit: visit, points: ["salon"])

        XCTAssertEqual(items.map(\.path), [
            "visite.json", "salon/capture.json", "salon/photos/IMG_0001.jpg",
            "salon/photos/IMG_0002.jpg",
        ])
        XCTAssertEqual(items[2].size, 3)
        // SHA-256 de « abc ».
        XCTAssertEqual(
            items[2].sha256, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )
    }
}

final class LensDriftTests: XCTestCase {
    func testReferenceIsTheFirstTrackedPositionAfterStart() {
        var drift = LensDrift()
        drift.update(SIMD3(5, 0, 0), started: false)
        XCTAssertNil(drift.reference)
        drift.start()
        drift.update(nil, started: true)  // ARKit ne suit pas encore
        drift.update(SIMD3(1, 1.5, 0), started: true)
        XCTAssertEqual(drift.reference, SIMD3(1, 1.5, 0))
        XCTAssertEqual(drift.offset, 0)
    }

    func testAlertStartsAboveTheLimitAndClearsBelowTheLowerThreshold() {
        var drift = LensDrift()
        drift.start()
        drift.update(SIMD3(0, 0, 0), started: true)
        drift.update(SIMD3(0.04, 0, 0), started: true)
        XCTAssertFalse(drift.isTooFar)
        drift.update(SIMD3(0.03, 0, 0.04), started: true)  // 5 cm : à la limite, pas au-delà
        XCTAssertFalse(drift.isTooFar)
        drift.update(SIMD3(0.3, 0, 0), started: true)  // pivot sur les talons
        XCTAssertTrue(drift.isTooFar)
        XCTAssertEqual(drift.offset ?? 0, 0.3, accuracy: 1e-12)
        drift.update(SIMD3(0.04, 0, 0), started: true)  // revenu, mais pas assez
        XCTAssertTrue(drift.isTooFar)
        drift.update(SIMD3(0.02, 0, 0), started: true)
        XCTAssertFalse(drift.isTooFar)
    }

    func testLostTrackingKeepsTheAlertState() {
        var drift = LensDrift()
        drift.start()
        drift.update(SIMD3(0, 0, 0), started: true)
        drift.update(SIMD3(0, 0, 0.2), started: true)
        drift.update(nil, started: true)
        XCTAssertNil(drift.offset)
        XCTAssertTrue(drift.isTooFar)
    }

    func testTrackedSetupUsesTheMainLens() {
        XCTAssertEqual(CaptureSetup.wideTracked.lens, .wide)
        XCTAssertTrue(CaptureSetup.wideTracked.tracksPosition)
        XCTAssertFalse(CaptureSetup.ultraWide.tracksPosition)
    }
}
