// Envoi d'une visite au serveur du projet (étape 13, docs/serveur.md) : réponses du serveur et
// journal de l'envoi, qui permet de le reprendre après une coupure ou un redémarrage de l'app.
//
// Le serveur répond à l'annonce d'un envoi par une adresse de dépôt pour chaque fichier qui lui
// manque. L'app dépose ces fichiers en arrière-plan, un par un, puis demande la fin de l'envoi.
// Le journal, rangé à côté de la visite, note les dépôts réussis ; mais c'est toujours le serveur
// qui dit ce qui manque : une reprise refait l'annonce et ne dépose que ce qu'il redemande.

import Foundation

/// Dépôt d'un fichier, tel que le décrit le serveur.
public struct Deposit: Codable, Equatable, Sendable {
    public let path: String
    public let url: String
    public let headers: [String: String]

    public init(path: String, url: String, headers: [String: String]) {
        self.path = path
        self.url = url
        self.headers = headers
    }

    enum CodingKeys: String, CodingKey {
        case path = "chemin"
        case url = "adresse"
        case headers = "en_tetes"
    }
}

/// Réponse du serveur à l'annonce d'un envoi.
public struct UploadStart: Codable, Equatable, Sendable {
    public let visit: String
    public let deposits: [Deposit]
    public let alreadyThere: Int

    enum CodingKeys: String, CodingKey {
        case visit = "visite"
        case deposits = "depots"
        case alreadyThere = "deja"
    }
}

/// État d'une visite sur le serveur.
public struct OnlineVisit: Codable, Equatable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let state: String
    public let message: String
    public let link: String?
    public let created: Double
    public let photosDeleted: Bool

    public var label: String {
        switch state {
        case "envoi": "Envoi en cours"
        case "en_attente": "En attente"
        case "en_cours": "Assemblage en cours"
        case "prete": "Prête"
        case "echec": "Échec"
        default: state
        }
    }

    public var isWorking: Bool { ["envoi", "en_attente", "en_cours"].contains(state) }

    enum CodingKeys: String, CodingKey {
        case id
        case name = "nom"
        case state = "etat"
        case message
        case link = "lien"
        case created = "cree_le"
        case photosDeleted = "photos_effacees"
    }
}

public enum UploadPlanError: LocalizedError, Equatable {
    case unknownFile(String)

    public var errorDescription: String? {
        switch self {
        case .unknownFile(let path):
            "Le serveur demande un fichier qui n'est pas dans la visite : \(path)."
        }
    }
}

/// Journal d'un envoi au serveur, rangé dans le dossier de la visite.
public struct UploadJournal: Codable, Equatable, Sendable {
    public static let fileName = ".envoi-serveur.json"

    /// Identifiant de la visite sur le serveur.
    public var visit: String
    /// Chemins à déposer, demandés par le serveur à la dernière annonce.
    public var pending: [String]
    /// Chemins déposés avec succès depuis cette annonce.
    public var done: Set<String> = []
    /// Dernier problème de dépôt, à montrer à l'utilisateur.
    public var problem: String?
    /// Vrai une fois la fin de l'envoi acceptée par le serveur.
    public var finished = false

    public init(visit: String, pending: [String]) {
        self.visit = visit
        self.pending = pending
    }

    /// Fichiers encore à déposer.
    public var remaining: [String] { pending.filter { !done.contains($0) } }

    /// Vrai quand tout est déposé et qu'il reste à demander la fin de l'envoi.
    public var readyToFinish: Bool { !finished && remaining.isEmpty }

    public var fraction: Double {
        pending.isEmpty ? 1 : Double(pending.count - remaining.count) / Double(pending.count)
    }

    /// Nouveau journal après une annonce : ce que le serveur redemande remplace l'ancien plan.
    public static func after(_ start: UploadStart) -> UploadJournal {
        UploadJournal(visit: start.visit, pending: start.deposits.map(\.path))
    }

    public static func load(from folder: URL) -> UploadJournal? {
        guard let data = try? Data(contentsOf: folder.appendingPathComponent(fileName)) else {
            return nil
        }
        return try? JSONDecoder().decode(UploadJournal.self, from: data)
    }

    public func save(to folder: URL) throws {
        let data = try JSONEncoder().encode(self)
        try data.write(to: folder.appendingPathComponent(Self.fileName), options: .atomic)
    }
}

/// Une tâche de dépôt : fichier local et requête à envoyer.
public struct PlannedUpload: Equatable, Sendable {
    public let path: String
    public let file: URL
    public let request: URLRequest
}

public enum UploadPlan {
    /// Requêtes de dépôt pour ce que le serveur demande. Refuse un chemin inconnu de la visite :
    /// l'app n'envoie jamais un fichier qu'elle n'a pas annoncé.
    public static func uploads(for start: UploadStart, items: [ManifestItem]) throws -> [PlannedUpload] {
        let byPath = Dictionary(uniqueKeysWithValues: items.map { ($0.path, $0) })
        return try start.deposits.map { deposit in
            guard let item = byPath[deposit.path], let url = URL(string: deposit.url) else {
                throw UploadPlanError.unknownFile(deposit.path)
            }
            var request = URLRequest(url: url, timeoutInterval: 120)
            request.httpMethod = "PUT"
            for (name, value) in deposit.headers {
                request.setValue(value, forHTTPHeaderField: name)
            }
            request.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
            return PlannedUpload(path: deposit.path, file: item.url, request: request)
        }
    }
}
