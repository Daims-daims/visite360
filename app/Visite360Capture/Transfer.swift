// Envoi d'une visite au Mac sur le Wi-Fi local (étape 6, docs/transfert.md).
//
// Le Mac lance `visite360 receive`, qui s'annonce par Bonjour sous le type _visite360._tcp et
// affiche un code à 6 chiffres. L'app trouve le Mac, annonce la liste des fichiers avec leur
// empreinte, envoie ceux qui manquent au Mac, puis demande la fin de l'envoi.

import Foundation
import Network

/// Un Mac trouvé sur le Wi-Fi.
struct FoundMac: Identifiable, Hashable {
    let name: String
    let endpoint: NWEndpoint

    var id: String { name }
}

/// Cherche les Mac qui attendent une visite.
@MainActor
final class MacFinder: ObservableObject {
    static let serviceType = "_visite360._tcp"

    @Published private(set) var macs: [FoundMac] = []
    @Published private(set) var problem: String?
    private var browser: NWBrowser?

    func start() {
        guard browser == nil else { return }
        let browser = NWBrowser(for: .bonjour(type: Self.serviceType, domain: nil), using: .tcp)
        browser.browseResultsChangedHandler = { [weak self] results, _ in
            let found = results.compactMap { result -> FoundMac? in
                guard case .service(let name, _, _, _) = result.endpoint else { return nil }
                return FoundMac(name: name, endpoint: result.endpoint)
            }
            Task { @MainActor in self?.macs = found.sorted { $0.name < $1.name } }
        }
        browser.stateUpdateHandler = { [weak self] state in
            guard case .failed = state else { return }
            Task { @MainActor in
                self?.problem = "Recherche du Mac impossible. Autoriser l'accès au réseau local "
                    + "dans Réglages > Confidentialité et sécurité > Réseau local, ou saisir l'adresse."
            }
        }
        browser.start(queue: .main)
        self.browser = browser
    }

    func stop() {
        browser?.cancel()
        browser = nil
    }

    /// Adresse IPv4 et port d'un Mac trouvé par Bonjour.
    static func resolve(_ endpoint: NWEndpoint) async throws -> (host: String, port: Int) {
        let parameters = NWParameters.tcp
        if let ip = parameters.defaultProtocolStack.internetProtocol as? NWProtocolIP.Options {
            ip.version = .v4
        }
        let connection = NWConnection(to: endpoint, using: parameters)
        // Les changements d'état arrivent tous sur la file principale : le drapeau ne sert
        // qu'à ne reprendre la suite qu'une fois.
        final class Once: @unchecked Sendable { var done = false }
        let once = Once()
        return try await withCheckedThrowingContinuation { continuation in
            connection.stateUpdateHandler = { state in
                guard !once.done else { return }
                switch state {
                case .ready:
                    once.done = true
                    if case .hostPort(let host, let port) = connection.currentPath?.remoteEndpoint {
                        // « 192.168.1.20%en0 » : on retire l'interface.
                        let text = "\(host)".split(separator: "%").first.map(String.init) ?? "\(host)"
                        continuation.resume(returning: (text, Int(port.rawValue)))
                    } else {
                        continuation.resume(throwing: TransferError.message("Adresse du Mac introuvable."))
                    }
                    connection.cancel()
                case .failed(let error), .waiting(let error):
                    once.done = true
                    continuation.resume(throwing: error)
                    connection.cancel()
                default:
                    break
                }
            }
            connection.start(queue: .main)
        }
    }
}

enum TransferError: LocalizedError {
    case message(String)

    var errorDescription: String? {
        switch self {
        case .message(let text): text
        }
    }
}

/// Client du serveur `visite360 receive`.
struct Uploader {
    static let codeHeader = "X-Visite360-Code"

    let host: String
    let port: Int
    let code: String

    private struct Started: Decodable {
        let envoi: String
        let manquants: [String]
    }

    private struct Finished: Decodable {
        let message: String
    }

    private struct Failure: Decodable {
        let message: String
    }

    /// « 192.168.1.20:8361 » ou « 192.168.1.20 » (port par défaut).
    static func parse(address: String) -> (host: String, port: Int)? {
        let parts = address.trimmingCharacters(in: .whitespaces).split(separator: ":")
        guard let host = parts.first, !host.isEmpty, parts.count <= 2 else { return nil }
        guard parts.count == 2 else { return (String(host), 8361) }
        guard let port = Int(parts[1]), (1...65535).contains(port) else { return nil }
        return (String(host), port)
    }

    /// Envoie la visite et renvoie le message du Mac. progress reçoit la part envoyée, de 0 à 1.
    func send(
        visit: VisitFolder, progress: @escaping @MainActor (Double, String) -> Void
    ) async throws -> String {
        let file = visit.load()
        let taken = file.points.map(\.id).filter { visit.point($0).isTaken }
        guard !taken.isEmpty else {
            throw TransferError.message("Aucun point pris dans cette visite.")
        }
        try visit.save(file)  // visite.json à jour avant de calculer les empreintes
        await progress(0, "Préparation des fichiers…")
        let items = try Manifest.items(visit: visit.url, points: taken)
        let body = try JSONEncoder().encode(ManifestRequest(visit: visit.folderName, items: items))
        let started: Started = try await request("POST", "/envois", body: body)
        let missing = Set(started.manquants)
        let toSend = items.filter { missing.contains($0.path) }
        let total = max(1, toSend.reduce(0) { $0 + $1.size })
        var sent = 0
        for (index, item) in toSend.enumerated() {
            await progress(
                Double(sent) / Double(total), "Fichier \(index + 1) sur \(toSend.count)"
            )
            let path = item.path.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? item.path
            let _: [String: Bool] = try await request(
                "PUT", "/envois/\(started.envoi)/\(path)", file: item.url
            )
            sent += item.size
        }
        await progress(1, "Vérification sur le Mac…")
        let finished: Finished = try await request("POST", "/envois/\(started.envoi)/fin")
        return finished.message
    }

    private struct Info: Decodable {
        let app: String
    }

    /// Vérifie que le Mac répond et que le code est bon.
    func check() async throws {
        let info: Info = try await request("GET", "/info")
        guard info.app == "visite360" else {
            throw TransferError.message("Ce n'est pas visite360 qui répond à cette adresse.")
        }
    }

    private func request<T: Decodable>(
        _ method: String, _ path: String, body: Data? = nil, file: URL? = nil
    ) async throws -> T {
        guard let url = URL(string: "http://\(host):\(port)\(path)") else {
            throw TransferError.message("Adresse du Mac invalide : \(host):\(port).")
        }
        var request = URLRequest(url: url, timeoutInterval: 60)
        request.httpMethod = method
        request.setValue(code, forHTTPHeaderField: Self.codeHeader)
        let data: Data
        let response: URLResponse
        do {
            if let file {
                let size = try file.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
                request.setValue(String(size), forHTTPHeaderField: "Content-Length")
                (data, response) = try await URLSession.shared.upload(for: request, fromFile: file)
            } else if let body {
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                (data, response) = try await URLSession.shared.upload(for: request, from: body)
            } else {
                (data, response) = try await URLSession.shared.data(for: request)
            }
        } catch {
            throw TransferError.message(
                "Le Mac ne répond pas (\(error.localizedDescription)). Vérifier que "
                    + "visite360 receive tourne sur le Mac et que l'iPhone est sur le même Wi-Fi."
            )
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200 else {
            let message = (try? JSONDecoder().decode(Failure.self, from: data))?.message
            throw TransferError.message(message ?? "Le Mac a refusé l'envoi (erreur \(status)).")
        }
        return try JSONDecoder().decode(T.self, from: data)
    }
}
