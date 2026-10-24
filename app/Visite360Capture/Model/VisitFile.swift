// Visite telle que l'app la connaît : points pris, pièces annoncées par une flèche mais pas
// encore prises, flèches entre les points (étape 6).
//
// Sur le téléphone, une visite est un dossier Documents/<visite>/ avec un dossier par point,
// comme sur le Mac (D20). L'état complet de l'app est dans visite-app.json. À chaque
// enregistrement, l'app écrit aussi visite.json, au format lu par le Mac (docs/visite-json.md) :
// seulement les points déjà pris et les flèches entre eux. Le dossier reste ainsi utilisable
// tel quel sur le Mac, quel que soit le moyen de transfert.
//
// Ce fichier n'utilise que Foundation : il est testé sur le Mac par `swift test`.

import Foundation

/// Point de la visite. `id` est le nom de son dossier, `name` le texte affiché.
public struct VisitPoint: Codable, Equatable, Sendable {
    public var id: String
    public var name: String

    public init(id: String, name: String) {
        self.id = id
        self.name = name
    }

    enum CodingKeys: String, CodingKey {
        case id
        case name = "nom"
    }
}

/// Flèche du point `from` vers le point `to`, dans le repère de la visionneuse : `angle` en
/// degrés depuis le centre du panorama de `from`, positif vers la droite ; `pitch` (hauteur)
/// en degrés, positif vers le haut.
public struct VisitLink: Codable, Equatable, Sendable {
    public var from: String
    public var to: String
    public var angle: Double
    public var pitch: Double?

    public init(from: String, to: String, angle: Double, pitch: Double?) {
        self.from = from
        self.to = to
        self.angle = angle
        self.pitch = pitch
    }

    enum CodingKeys: String, CodingKey {
        case from = "de"
        case to = "vers"
        case angle
        case pitch = "hauteur"
    }
}

/// Contenu de visite-app.json, et de visite.json une fois exporté.
public struct VisitFile: Codable, Equatable, Sendable {
    public static let appFileName = "visite-app.json"
    public static let macFileName = "visite.json"

    public var version = 1
    public var name: String
    public var start: String?
    public var points: [VisitPoint] = []
    public var links: [VisitLink] = []

    public init(name: String) {
        self.name = name
    }

    enum CodingKeys: String, CodingKey {
        case version
        case name = "nom"
        case start = "depart"
        case points
        case links = "liens"
    }

    public func point(_ id: String) -> VisitPoint? {
        points.first { $0.id == id }
    }

    public func displayName(_ id: String) -> String {
        point(id)?.name ?? id
    }

    /// Ajoute un point (pris ou annoncé). Renvoie son id, unique dans la visite.
    @discardableResult
    public mutating func addPoint(name: String) -> String {
        let base = FolderName.make(from: name)
        var id = base
        var suffix = 2
        while point(id) != nil {
            id = "\(base)-\(suffix)"
            suffix += 1
        }
        points.append(VisitPoint(id: id, name: name.trimmingCharacters(in: .whitespaces)))
        return id
    }

    /// Ajoute ou remplace la flèche de `from` vers `to`.
    public mutating func setLink(from: String, to: String, angle: Double, pitch: Double?) {
        links.removeAll { $0.from == from && $0.to == to }
        links.append(VisitLink(from: from, to: to, angle: angle, pitch: pitch))
    }

    public func links(from id: String) -> [VisitLink] {
        links.filter { $0.from == id }
    }

    /// Retire un point et ses flèches de départ. S'il reste des flèches vers lui, il redevient
    /// une pièce annoncée, à reprendre.
    public mutating func removePoint(_ id: String) {
        links.removeAll { $0.from == id }
        if !links.contains(where: { $0.to == id }) {
            points.removeAll { $0.id == id }
        }
        if start == id { start = nil }
    }

    /// visite.json pour le Mac : seulement les points pris (taken) et les flèches entre eux.
    public func exported(taken: Set<String>) -> VisitFile {
        var result = VisitFile(name: name)
        result.points = points.filter { taken.contains($0.id) }
        result.links = links.filter { taken.contains($0.from) && taken.contains($0.to) }
        result.start = start.flatMap { taken.contains($0) ? $0 : nil } ?? result.points.first?.id
        return result
    }
}

/// Nom de dossier sûr, comme ceux attendus sur le Mac : « Salon 2 » devient « salon-2 ».
public enum FolderName {
    public static func make(from text: String) -> String {
        let folded = text.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: nil)
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-_"))
        let parts = folded.lowercased().unicodeScalars.split { !allowed.contains($0) || !$0.isASCII }
        let name = parts.map { String(String.UnicodeScalarView($0)) }.joined(separator: "-")
        return name.isEmpty ? "point" : String(name.prefix(60))
    }
}

/// Angle d'une flèche visée pendant la prise de vue d'un point.
public enum ArrowAim {
    /// Hauteur maximale d'une flèche, en degrés au-dessus ou au-dessous de l'horizon.
    public static let maxPitch = 60.0

    /// Le panorama est centré sur le cap de départ de la prise de vue (cap_depart de
    /// capture.json) : l'angle de la flèche est l'écart entre le cap visé et ce cap de départ.
    public static func angle(yaw: Double, startYaw: Double) -> Double {
        let rounded = (Orientation.wrap(yaw - startYaw) * 10).rounded() / 10
        return rounded == -180 ? 180 : rounded
    }

    public static func pitch(_ pitch: Double) -> Double {
        (max(-maxPitch, min(maxPitch, pitch)) * 10).rounded() / 10
    }
}
