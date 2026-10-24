// Géométrie de la capture guidée : cibles des rangées, orientation du téléphone dans le
// repère de l'assemblage, alignement sur une cible.
//
// Ce fichier n'utilise que simd : il est compilé dans l'app et testé sur le Mac par
// `swift test` (dossier app/, Package.swift).
//
// Repère du monde, celui de src/visite360/spherical.py : x vers la droite, y vers le bas,
// z vers l'avant, cap de départ arbitraire. Repère d'une photo : x vers la droite de l'image,
// y vers le bas, z dans l'axe de l'objectif. Une rotation « caméra vers monde » envoie une
// direction vue par la photo dans le repère du monde.

import Foundation
import simd

/// Objectif de l'iPhone utilisé pour un point.
public enum Lens: String, Codable, CaseIterable, Sendable {
    /// Grand-angle ×0,5 : environ 90° × 106° en portrait. Un objet proche tient plus souvent
    /// dans une seule photo, et il y a moins de raccords.
    case ultraWide = "x0.5"
    /// Objectif principal ×1 : environ 54° × 70° en portrait (docs/prise-de-vue.md).
    case wide = "x1"

    public var label: String {
        switch self {
        case .ultraWide: "×0,5"
        case .wide: "×1"
        }
    }
}

/// Rangées de la prise de vue.
public enum Row: String, Codable, CaseIterable, Sendable {
    case horizon, haut, bas, plafond, sol

    /// Inclinaison de la rangée, en degrés (positif vers le haut).
    public func pitch(_ lens: Lens) -> Double {
        switch (self, lens) {
        case (.horizon, _): 0
        case (.haut, .wide): 45
        case (.haut, .ultraWide): 50
        case (.bas, .wide): -45
        case (.bas, .ultraWide): -50
        case (.plafond, _): 90
        case (.sol, _): -90
        }
    }

    /// Nombre de photos de la rangée. Deux photos voisines se recouvrent d'environ la moitié.
    public func count(_ lens: Lens) -> Int {
        switch (self, lens) {
        case (.horizon, .wide): 12
        case (.horizon, .ultraWide): 8
        case (.haut, .wide), (.bas, .wide): 8
        case (.haut, .ultraWide), (.bas, .ultraWide): 6
        case (.plafond, _), (.sol, _): 1
        }
    }

    /// Nom affiché.
    public var label: String {
        switch self {
        case .horizon: "Horizon"
        case .haut: "Haut"
        case .bas: "Bas"
        case .plafond: "Plafond"
        case .sol: "Sol (facultatif)"
        }
    }

    /// La photo du sol est facultative (docs/prise-de-vue.md).
    public var isOptional: Bool { self == .sol }
}

/// Une direction à photographier.
public struct Target: Identifiable, Equatable, Sendable {
    public let id: Int
    public let row: Row
    /// Numéro dans la rangée, à partir de 1, sur rowCount photos.
    public let number: Int
    public let rowCount: Int
    /// Cap en degrés, vers la droite, dans le repère du monde.
    public let yaw: Double
    public let pitch: Double

    public var direction: SIMD3<Double> { Orientation.direction(yaw: yaw, pitch: pitch) }
}

public enum Plan {
    /// Cibles de toutes les rangées, dans l'ordre de la fiche, la première face à startYaw.
    public static func targets(startYaw: Double, lens: Lens) -> [Target] {
        var result: [Target] = []
        for row in Row.allCases {
            let count = row.count(lens)
            for index in 0..<count {
                let yaw = Orientation.wrap(startYaw + 360 * Double(index) / Double(count))
                result.append(Target(
                    id: result.count, row: row, number: index + 1, rowCount: count,
                    yaw: yaw, pitch: row.pitch(lens)
                ))
            }
        }
        return result
    }
}

public enum Orientation {
    /// Passage du repère de l'appareil (Core Motion) à celui de la photo : x de l'écran vers la
    /// droite, y vers le haut de l'écran, z sortant de l'écran ; l'objectif arrière vise -z.
    /// Téléphone tenu en portrait.
    static let cameraToDevice = simd_double3x3(rows: [
        SIMD3(1, 0, 0),
        SIMD3(0, -1, 0),
        SIMD3(0, 0, -1),
    ])

    /// Passage du repère de référence de Core Motion (X horizontal arbitraire, Y horizontal,
    /// Z vers le haut) au repère du monde (y vers le bas).
    static let referenceToWorld = simd_double3x3(rows: [
        SIMD3(1, 0, 0),
        SIMD3(0, 0, -1),
        SIMD3(0, 1, 0),
    ])

    /// Rotation appareil → référence à partir du quaternion d'attitude de Core Motion.
    ///
    /// La gravité mesurée (repère de l'appareil, en g) sert de contrôle : si la matrice tirée
    /// du quaternion ne la retrouve pas, c'est sa transposée qui est la bonne. Cela protège
    /// d'une erreur de convention, impossible à vérifier sans téléphone.
    public static func deviceToReference(
        quaternion: simd_quatd, gravity: SIMD3<Double>
    ) -> simd_double3x3 {
        let matrix = simd_double3x3(quaternion)
        let down = SIMD3<Double>(0, 0, -1)
        let direct = simd_dot(matrix.transpose * down, simd_normalize(gravity))
        let transposed = simd_dot(matrix * down, simd_normalize(gravity))
        return direct >= transposed ? matrix : matrix.transpose
    }

    /// Rotation caméra → monde, dans la convention de l'assemblage.
    public static func cameraToWorld(deviceToReference: simd_double3x3) -> simd_double3x3 {
        referenceToWorld * deviceToReference * cameraToDevice
    }

    /// Direction du monde d'un cap et d'une inclinaison, en degrés.
    public static func direction(yaw: Double, pitch: Double) -> SIMD3<Double> {
        let y = yaw * .pi / 180, p = pitch * .pi / 180
        return SIMD3(cos(p) * sin(y), -sin(p), cos(p) * cos(y))
    }

    /// Axe de l'objectif dans le monde.
    public static func forward(_ rotation: simd_double3x3) -> SIMD3<Double> {
        rotation * SIMD3(0, 0, 1)
    }

    /// Cap de l'objectif, en degrés de -180 à 180, positif vers la droite.
    public static func yaw(_ rotation: simd_double3x3) -> Double {
        let f = forward(rotation)
        return atan2(f.x, f.z) * 180 / .pi
    }

    /// Inclinaison de l'objectif, en degrés, positive vers le haut.
    public static func pitch(_ rotation: simd_double3x3) -> Double {
        asin(max(-1, min(1, -forward(rotation).y))) * 180 / .pi
    }

    /// Penchement du téléphone sur le côté, en degrés : 0 quand il est droit. Indéfini quand
    /// l'objectif vise presque à la verticale.
    public static func roll(_ rotation: simd_double3x3) -> Double? {
        if abs(pitch(rotation)) > 60 { return nil }
        let right = rotation * SIMD3(1, 0, 0)
        return asin(max(-1, min(1, right.y))) * 180 / .pi
    }

    /// Angle en degrés entre deux directions.
    public static func angle(_ a: SIMD3<Double>, _ b: SIMD3<Double>) -> Double {
        let cosine = simd_dot(simd_normalize(a), simd_normalize(b))
        return acos(max(-1, min(1, cosine))) * 180 / .pi
    }

    /// Ramène un angle entre -180 et 180 degrés.
    public static func wrap(_ degrees: Double) -> Double {
        var value = degrees.truncatingRemainder(dividingBy: 360)
        if value > 180 { value -= 360 }
        if value <= -180 { value += 360 }
        return value
    }

    /// Lignes de la rotation, pour capture.json.
    public static func rows(_ rotation: simd_double3x3) -> [[Double]] {
        (0..<3).map { i in [rotation[0][i], rotation[1][i], rotation[2][i]] }
    }

    /// Position à l'écran d'une direction du monde, en points depuis le centre de l'aperçu
    /// (x vers la droite, y vers le bas), ou nil si elle est derrière le téléphone.
    /// focal est la focale de l'aperçu en points.
    public static func project(
        _ direction: SIMD3<Double>, rotation: simd_double3x3, focal: Double
    ) -> SIMD2<Double>? {
        let seen = rotation.transpose * direction
        guard seen.z > 0.05 else { return nil }
        return SIMD2(seen.x / seen.z * focal, seen.y / seen.z * focal)
    }
}

/// Conditions de déclenchement automatique sur une cible.
public struct Aiming: Sendable {
    /// Écart maximal entre l'axe de l'objectif et la cible, en degrés.
    public var tolerance: Double = 3
    /// Penchement maximal du téléphone sur le côté, en degrés.
    public var rollTolerance: Double = 6

    public init() {}

    /// Cible encore à prendre la plus proche de l'axe de l'objectif.
    public func nearest(
        _ targets: [Target], done: Set<Int>, rotation: simd_double3x3
    ) -> (target: Target, angle: Double)? {
        let axis = Orientation.forward(rotation)
        return targets
            .filter { !done.contains($0.id) }
            .map { ($0, Orientation.angle(axis, $0.direction)) }
            .min { $0.1 < $1.1 }
    }

    /// Vrai si le téléphone vise la cible et se tient droit.
    public func isAligned(_ target: Target, rotation: simd_double3x3) -> Bool {
        let angle = Orientation.angle(Orientation.forward(rotation), target.direction)
        guard angle <= tolerance else { return false }
        guard let roll = Orientation.roll(rotation) else { return true }
        return abs(roll) <= rollTolerance
    }
}

/// Réglage de prise de vue choisi sur l'écran d'accueil : un objectif, avec ou sans suivi de
/// la position de l'objectif par ARKit (qui n'existe qu'au ×1).
public enum CaptureSetup: String, CaseIterable, Sendable {
    case ultraWide = "x0.5"
    case wide = "x1"
    case wideTracked = "x1-ar"

    public var lens: Lens {
        self == .ultraWide ? .ultraWide : .wide
    }

    public var tracksPosition: Bool { self == .wideTracked }

    public var label: String {
        switch self {
        case .ultraWide: "×0,5"
        case .wide: "×1"
        case .wideTracked: "×1 + AR"
        }
    }
}

/// Surveille le déplacement de l'objectif depuis sa place de départ, mesuré par ARKit.
///
/// Toutes les photos d'un point doivent être prises du même endroit : si l'objectif bouge,
/// un objet proche ne se superpose plus au fond de la même façon d'une photo à l'autre
/// (parallaxe) et les raccords se voient. Pour un objet à 1 m, 5 cm de déplacement font
/// environ 3° d'écart.
public struct LensDrift: Sendable {
    /// Au-delà, la photo ne part pas et l'écran demande de revenir à sa place, en mètres.
    public var limit = 0.05
    /// En dessous, l'alerte s'efface. Plus bas que limit, pour qu'elle ne clignote pas.
    public var clear = 0.035

    public private(set) var reference: SIMD3<Double>?
    public private(set) var offset: Double?
    public private(set) var isTooFar = false

    public init() {}

    /// Place de départ : la position de l'objectif au verrouillage, ou la première position
    /// connue après lui si ARKit ne la suivait pas encore.
    public mutating func start() {
        reference = nil
        offset = nil
        isTooFar = false
    }

    /// Nouvelle position mesurée (nil si ARKit ne la suit pas). Ne fait rien avant start().
    public mutating func update(_ position: SIMD3<Double>?, started: Bool) {
        guard started, let position else {
            offset = nil
            return
        }
        guard let reference else {
            self.reference = position
            offset = 0
            return
        }
        let distance = simd_length(position - reference)
        offset = distance
        if distance > limit {
            isTooFar = true
        } else if distance < clear {
            isTooFar = false
        }
    }

    /// Déplacement depuis la place de départ, en mètres, à noter avec une photo.
    public func displacement(_ position: SIMD3<Double>?) -> SIMD3<Double>? {
        guard let position, let reference else { return nil }
        return position - reference
    }
}
