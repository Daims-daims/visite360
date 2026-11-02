import CryptoKit
import Foundation
import XCTest

@testable import CaptureGeometry

final class ServerUploadTests: XCTestCase {
    private var folder: URL!

    override func setUpWithError() throws {
        folder = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let photos = folder.appendingPathComponent("salon/photos", isDirectory: true)
        try FileManager.default.createDirectory(at: photos, withIntermediateDirectories: true)
        for number in 1...4 {
            let data = Data((0..<1000).map { UInt8(($0 * number) % 251) })
            try data.write(to: photos.appendingPathComponent(String(format: "IMG_%04d.jpg", number)))
        }
        try Data("{}".utf8).write(to: folder.appendingPathComponent("salon/capture.json"))
        try Data("{\"version\": 1}".utf8).write(to: folder.appendingPathComponent("visite.json"))
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: folder)
    }

    private func start(_ paths: [String]) -> UploadStart {
        let deposits = paths.map {
            Deposit(path: $0, url: "https://stockage.test/v/\($0)?sig=1", headers: ["Content-MD5": "x"])
        }
        let json: [String: Any] = [
            "visite": "abc",
            "deja": 0,
            "depots": deposits.map { ["chemin": $0.path, "adresse": $0.url, "en_tetes": $0.headers] },
        ]
        let data = try! JSONSerialization.data(withJSONObject: json)
        return try! JSONDecoder().decode(UploadStart.self, from: data)
    }

    func testManifestCarriesBothDigests() throws {
        let items = try Manifest.items(visit: folder, points: ["salon"])
        let photo = try XCTUnwrap(items.first { $0.path == "salon/photos/IMG_0001.jpg" })
        let data = try Data(contentsOf: photo.url)
        let md5 = Insecure.MD5.hash(data: data).map { String(format: "%02x", $0) }.joined()
        XCTAssertEqual(photo.md5, md5)
        XCTAssertEqual(photo.sha256.count, 64)
        let body = try JSONEncoder().encode(ManifestRequest(visit: "appart", items: items))
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: Any])
        let entry = try XCTUnwrap((object["fichiers"] as? [[String: Any]])?.first)
        XCTAssertEqual(Set(entry.keys), ["chemin", "taille", "sha256", "md5"])
    }

    func testInterruptedUploadResumesWithWhatTheServerStillAsks() throws {
        let items = try Manifest.items(visit: folder, points: ["salon"])
        let all = items.map(\.path)
        var journal = UploadJournal.after(start(all))
        XCTAssertEqual(journal.remaining.count, 6)

        // Deux dépôts réussis, puis coupure : le journal est relu au redémarrage de l'app.
        journal.done.insert(all[0])
        journal.done.insert(all[1])
        try journal.save(to: folder)
        let reloaded = try XCTUnwrap(UploadJournal.load(from: folder))
        XCTAssertEqual(reloaded.remaining, Array(all[2...]))
        XCTAssertFalse(reloaded.readyToFinish)
        XCTAssertEqual(reloaded.fraction, 2.0 / 6.0, accuracy: 1e-9)

        // À la reprise, le serveur ne redemande que ce qui lui manque.
        let resumed = start(Array(all[2...]))
        let uploads = try UploadPlan.uploads(for: resumed, items: items)
        XCTAssertEqual(uploads.map(\.path), Array(all[2...]))
        XCTAssertEqual(uploads[0].request.httpMethod, "PUT")
        XCTAssertEqual(uploads[0].request.value(forHTTPHeaderField: "Content-MD5"), "x")
        XCTAssertEqual(uploads[0].file.lastPathComponent, URL(fileURLWithPath: all[2]).lastPathComponent)

        var next = UploadJournal.after(resumed)
        for path in next.pending { next.done.insert(path) }
        XCTAssertTrue(next.readyToFinish)
    }

    func testNothingLeftToSendIsReadyToFinish() {
        let journal = UploadJournal.after(start([]))
        XCTAssertTrue(journal.readyToFinish)
        XCTAssertEqual(journal.fraction, 1)
    }

    func testUnknownFileAskedByTheServerIsRefused() throws {
        let items = try Manifest.items(visit: folder, points: ["salon"])
        XCTAssertThrowsError(try UploadPlan.uploads(for: start(["../secret"]), items: items)) {
            XCTAssertEqual($0 as? UploadPlanError, .unknownFile("../secret"))
        }
    }

    func testOnlineVisitIsDecodedFromTheServerAnswer() throws {
        let json = """
            {"id": "0123", "nom": "appart", "etat": "en_cours", "message": "Point 1 sur 2",
             "lien": null, "cree_le": 1800000000, "prete_le": null, "photos_effacees": false}
            """
        let visit = try JSONDecoder().decode(OnlineVisit.self, from: Data(json.utf8))
        XCTAssertEqual(visit.label, "Assemblage en cours")
        XCTAssertTrue(visit.isWorking)
        XCTAssertNil(visit.link)
    }
}
