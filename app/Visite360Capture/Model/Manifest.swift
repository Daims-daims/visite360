// Liste des fichiers d'une visite à envoyer au Mac ou au serveur, avec leur taille et leurs
// empreintes (docs/transfert.md, docs/serveur.md). Le destinataire s'en sert pour ne demander que
// ce qui lui manque et pour refuser un fichier arrivé abîmé. Le Mac lit l'empreinte SHA-256 ; le
// stockage du serveur vérifie l'empreinte MD5, la seule qu'il sache contrôler à l'arrivée.

import CryptoKit
import Foundation

public struct ManifestItem: Equatable, Sendable {
    /// Chemin dans le dossier de la visite, par exemple « salon/photos/IMG_0001.jpg ».
    public let path: String
    public let url: URL
    public let size: Int
    public let sha256: String
    public let md5: String
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
        let md5: String

        enum CodingKeys: String, CodingKey {
            case path = "chemin"
            case size = "taille"
            case sha256
            case md5
        }
    }

    public init(visit: String, items: [ManifestItem]) {
        self.visit = visit
        files = items.map { Entry(path: $0.path, size: $0.size, sha256: $0.sha256, md5: $0.md5) }
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
            let print = try fingerprint(url)
            return ManifestItem(
                path: path, url: url, size: print.size, sha256: print.sha256, md5: print.md5
            )
        }
    }

    /// Taille et empreintes SHA-256 et MD5 d'un fichier, lu une seule fois, par morceaux.
    public static func fingerprint(_ url: URL) throws -> (size: Int, sha256: String, md5: String) {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var sha = SHA256()
        var md5 = Insecure.MD5()
        var size = 0
        while let chunk = try handle.read(upToCount: 1 << 20), !chunk.isEmpty {
            sha.update(data: chunk)
            md5.update(data: chunk)
            size += chunk.count
        }
        let hex = { (bytes: any Sequence<UInt8>) in bytes.map { String(format: "%02x", $0) }.joined() }
        return (size, hex(sha.finalize()), hex(md5.finalize()))
    }
}
