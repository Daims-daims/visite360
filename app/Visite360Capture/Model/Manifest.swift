// Liste des fichiers d'une visite à envoyer au Mac, avec leur taille et leur empreinte
// SHA-256 (docs/transfert.md). Le Mac s'en sert pour ne demander que ce qui lui manque et pour
// refuser un fichier arrivé abîmé.

import CryptoKit
import Foundation

public struct ManifestItem: Equatable, Sendable {
    /// Chemin dans le dossier de la visite, par exemple « salon/photos/IMG_0001.jpg ».
    public let path: String
    public let url: URL
    public let size: Int
    public let sha256: String
}

/// Corps de la requête qui annonce un envoi.
public struct ManifestRequest: Encodable {
    public let format = 1
    public let visit: String
    public let files: [Entry]

    public struct Entry: Encodable {
        let path: String
        let size: Int
        let sha256: String

        enum CodingKeys: String, CodingKey {
            case path = "chemin"
            case size = "taille"
            case sha256
        }
    }

    public init(visit: String, items: [ManifestItem]) {
        self.visit = visit
        files = items.map { Entry(path: $0.path, size: $0.size, sha256: $0.sha256) }
    }

    enum CodingKeys: String, CodingKey {
        case format
        case visit = "visite"
        case files = "fichiers"
    }
}

public enum Manifest {
    /// Fichiers de la visite pour les points donnés : visite.json, puis pour chaque point
    /// capture.json et ses photos.
    public static func items(visit: URL, points: [String]) throws -> [ManifestItem] {
        var paths = [VisitFile.macFileName]
        let manager = FileManager.default
        for point in points {
            let folder = visit.appendingPathComponent(point, isDirectory: true)
            if manager.fileExists(atPath: folder.appendingPathComponent("capture.json").path) {
                paths.append("\(point)/capture.json")
            }
            let photos = try manager.contentsOfDirectory(
                atPath: folder.appendingPathComponent("photos").path
            )
            paths += photos.filter { !$0.hasPrefix(".") }.sorted().map { "\(point)/photos/\($0)" }
        }
        return try paths.map { path in
            let url = visit.appendingPathComponent(path)
            let (size, digest) = try fingerprint(url)
            return ManifestItem(path: path, url: url, size: size, sha256: digest)
        }
    }

    /// Taille et empreinte SHA-256 d'un fichier, lu par morceaux.
    public static func fingerprint(_ url: URL) throws -> (Int, String) {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hasher = SHA256()
        var size = 0
        while let chunk = try handle.read(upToCount: 1 << 20), !chunk.isEmpty {
            hasher.update(data: chunk)
            size += chunk.count
        }
        let digest = hasher.finalize().map { String(format: "%02x", $0) }.joined()
        return (size, digest)
    }
}
