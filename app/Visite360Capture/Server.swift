// Envoi d'une visite au serveur du projet (étape 13, docs/serveur.md).
//
// L'adresse du serveur est un réglage de compilation (VISITE360_SERVEUR, dans
// Config/Local.xcconfig), jamais écrit dans le code : un environnement d'intégration s'ajoutera
// sans rien réécrire (D38). La session ouverte par le code reçu par e-mail est gardée dans le
// trousseau de l'iPhone.
//
// Les photos partent par une session d'envoi en arrière-plan d'iOS : l'envoi continue quand
// l'app passe en arrière-plan ou est suspendue, et reprend tout seul après une coupure de réseau.
// Si l'app est fermée de force, iOS annule les dépôts en cours : « Reprendre l'envoi » refait
// l'annonce, et seuls les fichiers que le serveur n'a pas reçus repartent.

import Foundation
import Security
import UIKit

enum ServerConfig {
    static let infoKey = "Visite360Serveur"

    /// Adresse du serveur, ou nil si le réglage est vide (app construite sans serveur).
    static var address: URL? {
        guard let text = Bundle.main.object(forInfoDictionaryKey: infoKey) as? String else {
            return nil
        }
        let trimmed = text.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty, let url = URL(string: trimmed), url.scheme != nil else { return nil }
        return url
    }

    static let missing =
        "L'adresse du serveur n'est pas réglée dans cette version de l'app : renseigner "
        + "VISITE360_SERVEUR dans app/Config/Local.xcconfig, puis réinstaller (docs/app.md)."
}

/// Jeton de session, rangé dans le trousseau de l'iPhone.
enum SessionToken {
    private static let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: "visite360",
        kSecAttrAccount as String: "session",
    ]

    static func read() -> String? {
        var request = query
        request[kSecReturnData as String] = true
        request[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: AnyObject?
        guard SecItemCopyMatching(request as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data
        else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func save(_ token: String) {
        delete()
        var item = query
        item[kSecValueData as String] = Data(token.utf8)
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(item as CFDictionary, nil)
    }

    static func delete() {
        SecItemDelete(query as CFDictionary)
    }
}

enum ServerError: LocalizedError {
    case message(String)
    case notConnected

    var errorDescription: String? {
        switch self {
        case .message(let text): text
        case .notConnected: "Connexion nécessaire : se connecter avec son adresse e-mail."
        }
    }
}

/// Client de l'API du serveur.
struct ServerClient {
    static let guardHeader = "X-Visite360"

    let base: URL

    static func configured() throws -> ServerClient {
        guard let base = ServerConfig.address else { throw ServerError.message(ServerConfig.missing) }
        return ServerClient(base: base)
    }

    private struct Message: Decodable {
        let message: String
    }

    private struct Login: Decodable {
        let jeton: String
        let email: String
    }

    private struct Me: Decodable {
        let email: String
    }

    private struct Visits: Decodable {
        let visites: [OnlineVisit]
    }

    func requestCode(email: String) async throws -> String {
        let answer: Message = try await call("POST", "/api/connexion/code", json: ["email": email])
        return answer.message
    }

    /// Ouvre une session et garde son jeton dans le trousseau. Renvoie l'adresse connectée.
    func login(email: String, code: String) async throws -> String {
        let answer: Login = try await call(
            "POST", "/api/connexion", json: ["email": email, "code": code]
        )
        SessionToken.save(answer.jeton)
        return answer.email
    }

    func logout() async {
        let _: Message? = try? await call("POST", "/api/deconnexion")
        SessionToken.delete()
    }

    func me() async throws -> String {
        let answer: Me = try await call("GET", "/api/moi")
        return answer.email
    }

    func visits() async throws -> [OnlineVisit] {
        let answer: Visits = try await call("GET", "/api/visites")
        return answer.visites
    }

    func start(_ manifest: ManifestRequest) async throws -> UploadStart {
        try await call("POST", "/api/envois", body: try JSONEncoder().encode(manifest))
    }

    func finish(visit: String) async throws -> OnlineVisit {
        try await call("POST", "/api/envois/\(visit)/fin")
    }

    func unpublish(visit: String) async throws -> OnlineVisit {
        try await call("POST", "/api/visites/\(visit)/depublier")
    }

    func republish(visit: String) async throws -> OnlineVisit {
        try await call("POST", "/api/visites/\(visit)/publier")
    }

    func delete(visit: String) async throws -> String {
        let answer: Message = try await call("DELETE", "/api/visites/\(visit)")
        return answer.message
    }

    private func call<T: Decodable>(
        _ method: String, _ path: String, json: [String: String]? = nil, body: Data? = nil
    ) async throws -> T {
        var request = URLRequest(url: base.appendingPathComponent(path), timeoutInterval: 60)
        request.httpMethod = method
        if method != "GET" { request.setValue("1", forHTTPHeaderField: Self.guardHeader) }
        if let token = SessionToken.read() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        let payload = try json.map { try JSONEncoder().encode($0) } ?? body
        if let payload {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = payload
        }
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch {
            throw ServerError.message(
                "Le serveur ne répond pas (\(error.localizedDescription)). Vérifier la connexion "
                    + "à Internet, puis réessayer."
            )
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        if status == 401 {
            SessionToken.delete()
            throw ServerError.notConnected
        }
        guard status == 200 else {
            let message = (try? JSONDecoder().decode(Message.self, from: data))?.message
            throw ServerError.message(message ?? "Le serveur a refusé la demande (erreur \(status)).")
        }
        return try JSONDecoder().decode(T.self, from: data)
    }
}

/// Avancement de l'envoi d'une visite, pour l'écran.
struct SendProgress: Equatable {
    var fraction: Double
    var text: String
    var running: Bool
    var problem: String?
    var result: OnlineVisit?
}

/// Envois au serveur en arrière-plan. Une seule instance, recréée à chaque lancement de l'app
/// avec le même identifiant pour recevoir la fin des dépôts faits pendant son absence.
@MainActor
final class ServerSender: NSObject, ObservableObject {
    static let shared = ServerSender()
    static let sessionID = "visite360.envois"

    @Published private(set) var progress: [String: SendProgress] = [:]
    /// Rappel d'iOS à appeler quand les événements d'arrière-plan sont traités.
    var backgroundCompletion: (() -> Void)?

    private lazy var session: URLSession = {
        let configuration = URLSessionConfiguration.background(withIdentifier: Self.sessionID)
        configuration.sessionSendsLaunchEvents = true
        configuration.isDiscretionary = false
        configuration.allowsCellularAccess = true
        return URLSession(configuration: configuration, delegate: self, delegateQueue: .main)
    }()

    /// Crée la session tout de suite pour recevoir les dépôts terminés pendant l'absence de l'app.
    func activate() {
        _ = session
    }

    /// Dossiers des visites dont un envoi est en cours, d'après leur journal.
    func folders() -> [VisitFolder] {
        PointStore.visits().filter { UploadJournal.load(from: $0.url).map { !$0.finished } ?? false }
    }

    func journal(_ visit: VisitFolder) -> UploadJournal? {
        UploadJournal.load(from: visit.url)
    }

    /// Annonce la visite au serveur et dépose ce qu'il demande. Sert aussi à reprendre.
    func send(_ visit: VisitFolder) async {
        let key = visit.folderName
        progress[key] = SendProgress(fraction: 0, text: "Préparation des fichiers…", running: true)
        do {
            let client = try ServerClient.configured()
            let file = visit.load()
            let taken = file.points.map(\.id).filter { visit.point($0).isTaken }
            guard !taken.isEmpty else { throw ServerError.message("Aucun point pris dans cette visite.") }
            try visit.save(file)
            let items = try Manifest.items(visit: visit.url, points: taken)
            progress[key]?.text = "Annonce au serveur…"
            let start = try await client.start(ManifestRequest(visit: visit.folderName, items: items))
            let uploads = try UploadPlan.uploads(for: start, items: items)
            let journal = UploadJournal.after(start)
            try journal.save(to: visit.url)
            let tasks = await session.allTasks
            for task in tasks where task.taskDescription?.hasPrefix(key + "|") == true {
                task.cancel()
            }
            if uploads.isEmpty {
                await finish(visit, journal: journal)
                return
            }
            for upload in uploads {
                let task = session.uploadTask(with: upload.request, fromFile: upload.file)
                task.taskDescription = "\(key)|\(upload.path)"
                task.resume()
            }
            update(visit, journal)
        } catch {
            progress[key] = SendProgress(
                fraction: 0, text: "", running: false, problem: error.localizedDescription
            )
        }
    }

    private func update(_ visit: VisitFolder, _ journal: UploadJournal) {
        let total = journal.pending.count
        let sent = total - journal.remaining.count
        progress[visit.folderName] = SendProgress(
            fraction: journal.fraction,
            text: "Fichier \(sent) sur \(total) déposé",
            running: !journal.remaining.isEmpty,
            problem: journal.problem
        )
    }

    private func finish(_ visit: VisitFolder, journal: UploadJournal) async {
        var journal = journal
        let key = visit.folderName
        progress[key] = SendProgress(fraction: 1, text: "Vérification sur le serveur…", running: true)
        do {
            let result = try await ServerClient.configured().finish(visit: journal.visit)
            journal.finished = true
            try? journal.save(to: visit.url)
            progress[key] = SendProgress(
                fraction: 1, text: result.message, running: false, result: result
            )
        } catch {
            journal.problem = error.localizedDescription
            try? journal.save(to: visit.url)
            progress[key] = SendProgress(
                fraction: 1, text: "", running: false, problem: error.localizedDescription
            )
        }
    }

    fileprivate func completed(description: String?, status: Int, error: Error?) {
        guard let description, let bar = description.firstIndex(of: "|") else { return }
        let key = String(description[..<bar])
        let path = String(description[description.index(after: bar)...])
        guard let visit = PointStore.visits().first(where: { $0.folderName == key }),
              var journal = UploadJournal.load(from: visit.url)
        else { return }
        if error == nil, status == 200 {
            journal.done.insert(path)
        } else if (error as? URLError)?.code != .cancelled {
            journal.problem = status == 403
                ? "Le stockage a refusé \(path) (adresse expirée ou fichier abîmé) : reprendre l'envoi."
                : "Dépôt de \(path) interrompu : reprendre l'envoi."
        }
        try? journal.save(to: visit.url)
        update(visit, journal)
        if journal.readyToFinish {
            let ready = journal
            Task { await self.finish(visit, journal: ready) }
        }
    }
}

extension ServerSender: URLSessionTaskDelegate {
    nonisolated func urlSession(
        _ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?
    ) {
        let status = (task.response as? HTTPURLResponse)?.statusCode ?? 0
        let description = task.taskDescription
        Task { @MainActor in self.completed(description: description, status: status, error: error) }
    }

    nonisolated func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        Task { @MainActor in
            self.backgroundCompletion?()
            self.backgroundCompletion = nil
        }
    }
}

/// Reçoit d'iOS le réveil de l'app quand des dépôts d'arrière-plan se terminent.
final class AppDelegate: NSObject, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        Task { @MainActor in ServerSender.shared.activate() }
        return true
    }

    func application(
        _ application: UIApplication,
        handleEventsForBackgroundURLSession identifier: String,
        completionHandler: @escaping () -> Void
    ) {
        Task { @MainActor in
            ServerSender.shared.backgroundCompletion = completionHandler
            ServerSender.shared.activate()
        }
    }
}
