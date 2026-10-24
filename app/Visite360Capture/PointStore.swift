// Rangement des points sur le téléphone, comme sur le Mac (D20) :
// Documents/<point>/photos/IMG_0001.jpg et Documents/<point>/capture.json (docs/capture-json.md).
//
// Le dossier Documents de l'app est visible dans l'app Fichiers et dans le Finder quand
// l'iPhone est branché au Mac.

import Foundation

/// Une photo dans capture.json.
struct PhotoEntry: Codable {
    let file: String
    let row: Row
    let number: Int
    let yaw: Double
    let pitch: Double
    let rotation: [[Double]]
    let time: Date

    enum CodingKeys: String, CodingKey {
        case file = "fichier"
        case row = "rangee"
        case number = "numero"
        case yaw = "cap"
        case pitch = "inclinaison"
        case rotation
        case time = "heure"
    }
}

/// Contenu de capture.json.
struct CaptureFile: Codable {
    static let currentFormat = 1
    static let frame =
        "rotation caméra vers monde ; photo : x droite, y bas, z objectif ; "
        + "monde : y vers le bas, cap de départ arbitraire"

    var format = currentFormat
    var app: String
    var device: String
    var started: Date
    var frame = CaptureFile.frame
    var exposure: Exposure?
    var photos: [PhotoEntry] = []

    enum CodingKeys: String, CodingKey {
        case format, app
        case device = "appareil"
        case started = "debut"
        case frame = "repere"
        case exposure = "exposition"
        case photos
    }
}

struct PointFolder: Identifiable, Hashable {
    let url: URL

    var id: URL { url }
    var name: String { url.lastPathComponent }
    var photos: URL { url.appendingPathComponent("photos", isDirectory: true) }
    var captureURL: URL { url.appendingPathComponent("capture.json") }

    func load() -> CaptureFile? {
        guard let data = try? Data(contentsOf: captureURL) else { return nil }
        return try? PointStore.decoder.decode(CaptureFile.self, from: data)
    }
}

enum PointStore {
    static let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .withoutEscapingSlashes]
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }()

    static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }()

    static var root: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
    }

    /// Points enregistrés, le plus récent en premier.
    static func list() -> [PointFolder] {
        let keys: [URLResourceKey] = [.isDirectoryKey, .creationDateKey]
        let urls = (try? FileManager.default.contentsOfDirectory(
            at: root, includingPropertiesForKeys: keys, options: [.skipsHiddenFiles]
        )) ?? []
        return urls
            .filter { (try? $0.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true }
            .sorted {
                let a = (try? $0.resourceValues(forKeys: [.creationDateKey]).creationDate) ?? .distantPast
                let b = (try? $1.resourceValues(forKeys: [.creationDateKey]).creationDate) ?? .distantPast
                return a > b
            }
            .map(PointFolder.init)
    }

    /// Nom de dossier sûr, comme ceux attendus sur le Mac : « Salon 2 » devient « salon-2 ».
    static func folderName(from text: String) -> String {
        let folded = text.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: .current)
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-_"))
        let parts = folded.lowercased().unicodeScalars.split { !allowed.contains($0) || !$0.isASCII }
        let name = parts.map { String(String.UnicodeScalarView($0)) }.joined(separator: "-")
        return name.isEmpty ? "point" : name
    }

    /// Crée le dossier d'un nouveau point, avec un suffixe si le nom est déjà pris.
    static func create(name: String) throws -> PointFolder {
        let base = folderName(from: name)
        var candidate = base
        var suffix = 2
        while FileManager.default.fileExists(atPath: root.appendingPathComponent(candidate).path) {
            candidate = "\(base)-\(suffix)"
            suffix += 1
        }
        let point = PointFolder(url: root.appendingPathComponent(candidate, isDirectory: true))
        try FileManager.default.createDirectory(at: point.photos, withIntermediateDirectories: true)
        return point
    }

    /// Écrit capture.json d'un coup, pour ne jamais laisser un fichier à moitié écrit.
    static func save(_ file: CaptureFile, in point: PointFolder) throws {
        try encoder.encode(file).write(to: point.captureURL, options: .atomic)
    }

    /// Archive ZIP du dossier du point, à envoyer par AirDrop. Le système fabrique le ZIP
    /// lui-même quand on lui demande de lire un dossier « pour envoi ».
    static func archive(_ point: PointFolder) throws -> URL {
        var coordinationError: NSError?
        var result: Result<URL, Error> = .failure(CocoaError(.fileReadUnknown))
        NSFileCoordinator().coordinate(
            readingItemAt: point.url, options: [.forUploading], error: &coordinationError
        ) { zipped in
            let target = FileManager.default.temporaryDirectory
                .appendingPathComponent("\(point.name).zip")
            result = Result {
                try? FileManager.default.removeItem(at: target)
                try FileManager.default.copyItem(at: zipped, to: target)
                return target
            }
        }
        if let coordinationError { throw coordinationError }
        return try result.get()
    }

    /// Identifiant du modèle, par exemple « iPhone15,4 » pour un iPhone 15.
    static var deviceModel: String {
        var info = utsname()
        uname(&info)
        return withUnsafeBytes(of: &info.machine) { bytes in
            String(decoding: bytes.prefix { $0 != 0 }, as: UTF8.self)
        }
    }

    static var appVersion: String {
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?"
        return "Visite360 Capture \(version)"
    }
}
