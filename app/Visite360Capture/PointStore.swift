// Rangement des visites sur le téléphone, comme sur le Mac (D20) :
// Documents/<visite>/<point>/photos/IMG_0001.jpg, Documents/<visite>/<point>/capture.json
// (docs/capture-json.md), Documents/<visite>/visite.json et visite-app.json (VisitFile.swift).
// Les points pris avec l'étape 5, hors de toute visite, sont restés dans Documents/<point>/.
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
    /// Mode « ×1 + AR » : déplacement de l'objectif depuis sa place de départ, en mètres, dans
    /// le repère d'ARKit (y vers le haut). Absent si ARKit ne suivait pas la position.
    var lensOffset: [Double]? = nil

    enum CodingKeys: String, CodingKey {
        case lensOffset = "deplacement_m"
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
    /// Absent des fichiers écrits avant le choix de l'objectif : ×1.
    var lens: Lens?
    /// Cap visé au verrouillage, dans le repère des rotations : le Mac en fait le centre du
    /// panorama, et les flèches se mesurent depuis lui. Absent des fichiers de l'étape 5.
    var startYaw: Double?
    /// « arkit » quand la position de l'objectif a été suivie (mode « ×1 + AR »).
    var tracking: String?
    var photos: [PhotoEntry] = []

    enum CodingKeys: String, CodingKey {
        case format, app
        case lens = "objectif"
        case startYaw = "cap_depart"
        case tracking = "suivi_position"
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

    /// Un point est pris dès qu'il a une photo notée dans capture.json.
    var isTaken: Bool { !(load()?.photos.isEmpty ?? true) }
}

struct VisitFolder: Identifiable, Hashable {
    let url: URL

    var id: URL { url }
    var folderName: String { url.lastPathComponent }
    var appURL: URL { url.appendingPathComponent(VisitFile.appFileName) }
    var macURL: URL { url.appendingPathComponent(VisitFile.macFileName) }

    func load() -> VisitFile {
        guard let data = try? Data(contentsOf: appURL),
              let file = try? PointStore.decoder.decode(VisitFile.self, from: data)
        else { return VisitFile(name: folderName) }
        return file
    }

    func point(_ id: String) -> PointFolder {
        PointFolder(url: url.appendingPathComponent(id, isDirectory: true))
    }

    func takenPoints(_ file: VisitFile) -> Set<String> {
        Set(file.points.map(\.id).filter { point($0).isTaken })
    }

    /// Écrit visite-app.json et visite.json, chacun d'un coup.
    func save(_ file: VisitFile) throws {
        try PointStore.encoder.encode(file).write(to: appURL, options: .atomic)
        let exported = file.exported(taken: takenPoints(file))
        try PointStore.encoder.encode(exported).write(to: macURL, options: .atomic)
    }

    /// Lit, modifie et réécrit la visite.
    @discardableResult
    func update<T>(_ change: (inout VisitFile) throws -> T) throws -> T {
        var file = load()
        let result = try change(&file)
        try save(file)
        return result
    }

    /// Crée le dossier d'un point de la visite. id est celui d'une pièce annoncée par une
    /// flèche, ou nil pour un nouveau point.
    func createPoint(name: String, announced id: String?) throws -> PointFolder {
        let pointID = try update { file -> String in
            if let id, file.point(id) != nil { return id }
            return file.addPoint(name: name)
        }
        let folder = point(pointID)
        try FileManager.default.createDirectory(at: folder.photos, withIntermediateDirectories: true)
        return folder
    }

    /// Supprime un point et ses photos du téléphone.
    func deletePoint(_ id: String) throws {
        try? FileManager.default.removeItem(at: point(id).url)
        try update { $0.removePoint(id) }
    }

    /// Range dans la visite un point pris hors visite (étape 5).
    func adopt(_ loose: PointFolder) throws {
        var file = load()
        let id = file.addPoint(name: loose.name)
        try FileManager.default.moveItem(at: loose.url, to: point(id).url)
        try save(file)
    }
}

enum PointStore {
    static let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
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

    private static func folders() -> [URL] {
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
    }

    /// Visites enregistrées, la plus récente en premier.
    static func visits() -> [VisitFolder] {
        folders()
            .filter { FileManager.default.fileExists(atPath: $0.appendingPathComponent(VisitFile.appFileName).path) }
            .map(VisitFolder.init)
    }

    /// Points pris avec l'étape 5, hors de toute visite.
    static func loosePoints() -> [PointFolder] {
        folders()
            .filter { FileManager.default.fileExists(atPath: $0.appendingPathComponent("photos").path) }
            .map(PointFolder.init)
    }

    /// Crée le dossier d'une nouvelle visite, avec un suffixe si le nom est déjà pris.
    static func createVisit(name: String) throws -> VisitFolder {
        let base = FolderName.make(from: name)
        var candidate = base
        var suffix = 2
        while FileManager.default.fileExists(atPath: root.appendingPathComponent(candidate).path) {
            candidate = "\(base)-\(suffix)"
            suffix += 1
        }
        let visit = VisitFolder(url: root.appendingPathComponent(candidate, isDirectory: true))
        try FileManager.default.createDirectory(at: visit.url, withIntermediateDirectories: true)
        try visit.save(VisitFile(name: name.trimmingCharacters(in: .whitespaces)))
        return visit
    }

    static func deleteVisit(_ visit: VisitFolder) throws {
        try FileManager.default.removeItem(at: visit.url)
    }

    /// Écrit capture.json d'un coup, pour ne jamais laisser un fichier à moitié écrit.
    static func save(_ file: CaptureFile, in point: PointFolder) throws {
        try encoder.encode(file).write(to: point.captureURL, options: .atomic)
    }

    /// Archive ZIP d'un dossier (visite ou point), à envoyer par AirDrop. Le système fabrique
    /// le ZIP lui-même quand on lui demande de lire un dossier « pour envoi ».
    static func archive(_ folder: URL) throws -> URL {
        var coordinationError: NSError?
        var result: Result<URL, Error> = .failure(CocoaError(.fileReadUnknown))
        NSFileCoordinator().coordinate(
            readingItemAt: folder, options: [.forUploading], error: &coordinationError
        ) { zipped in
            let target = FileManager.default.temporaryDirectory
                .appendingPathComponent("\(folder.lastPathComponent).zip")
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
