// Écrans du serveur (étape 13) : connexion par code reçu par e-mail, envoi d'une visite au
// serveur, et liste des visites en ligne avec leur état, leur lien, la dépublication et la
// suppression.

import SwiftUI

/// Connexion : adresse e-mail, puis code à 6 chiffres reçu par e-mail.
struct LoginForm: View {
    let onLogin: (String) -> Void
    @AppStorage("emailServeur") private var email = ""
    @State private var code = ""
    @State private var info: String?
    @State private var working = false
    @State private var problem: String?

    var body: some View {
        Group {
        Section {
            TextField("adresse@exemple.fr", text: $email)
                .keyboardType(.emailAddress)
                .textContentType(.emailAddress)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
            Button("Recevoir un code") { Task { await askCode() } }
                .disabled(working || !email.contains("@"))
        } header: {
            Text("Connexion au serveur")
        } footer: {
            Text("Seules les adresses autorisées par le propriétaire du projet reçoivent un code.")
        }
        if let info {
            Section {
                TextField("123 456", text: $code)
                    .keyboardType(.numberPad)
                    .textContentType(.oneTimeCode)
                Button("Se connecter") { Task { await login() } }
                    .disabled(working || code.filter(\.isNumber).count != 6)
            } header: {
                Text("Code reçu par e-mail")
            } footer: {
                Text(info)
            }
        }
        }
        .problemAlert($problem)
    }

    private func askCode() async {
        working = true
        defer { working = false }
        do {
            info = try await ServerClient.configured().requestCode(email: email.trimmingCharacters(in: .whitespaces))
        } catch {
            problem = error.localizedDescription
        }
    }

    private func login() async {
        working = true
        defer { working = false }
        do {
            let address = try await ServerClient.configured().login(
                email: email.trimmingCharacters(in: .whitespaces), code: code.filter(\.isNumber)
            )
            code = ""
            info = nil
            onLogin(address)
        } catch {
            problem = error.localizedDescription
        }
    }
}

/// Envoi d'une visite au serveur, qui l'assemble et la publie.
struct ServerSendView: View {
    let visit: VisitFolder
    @ObservedObject private var sender = ServerSender.shared
    @Environment(\.dismiss) private var dismiss
    @State private var connected: String?
    @State private var checking = true

    var body: some View {
        NavigationStack {
            Form {
                if ServerConfig.address == nil {
                    Section { Text(ServerConfig.missing) }
                } else if checking {
                    Section { ProgressView() }
                } else if connected == nil {
                    LoginForm { connected = $0 }
                } else {
                    sendSection
                }
            }
            .navigationTitle("Envoyer au serveur")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Fermer") { dismiss() }
                }
            }
            .task { await check() }
        }
    }

    @ViewBuilder private var sendSection: some View {
        let state = sender.progress[visit.folderName]
        let journal = sender.journal(visit)
        let resumable = journal.map { !$0.finished } ?? false
        Section {
            Button(resumable && state?.running != true ? "Reprendre l'envoi" : "Envoyer") {
                Task { await sender.send(visit) }
            }
            .disabled(state?.running == true)
            if let state, state.running {
                ProgressView(value: state.fraction) { Text(state.text) }
            }
        } header: {
            Text("Connecté : \(connected ?? "")")
        } footer: {
            Text(
                "L'envoi continue si l'app passe en arrière-plan, et reprend seul après une coupure "
                    + "de réseau. Si l'app est fermée, « Reprendre l'envoi » ne renvoie que ce qui manque."
            )
        }
        if let problem = state?.problem ?? journal?.problem, state?.running != true {
            Section("Problème") { Text(problem) }
        }
        if let result = state?.result {
            Section("Reçu par le serveur") {
                LabeledContent("État", value: result.label)
                Text(result.message).font(.footnote).foregroundStyle(.secondary)
                Text("L'assemblage prend quelques minutes par point. Suivre son avancement et "
                    + "copier le lien dans « Mes visites en ligne ».")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }
    }

    private func check() async {
        defer { checking = false }
        guard ServerConfig.address != nil, SessionToken.read() != nil else { return }
        connected = try? await ServerClient.configured().me()
    }
}

/// Visites envoyées au serveur : état, lien, dépublication, nouvelle publication, suppression.
struct OnlineVisitsView: View {
    @State private var connected: String?
    @State private var checking = true
    @State private var visits: [OnlineVisit] = []
    @State private var deleting: OnlineVisit?
    @State private var info: String?
    @State private var problem: String?

    var body: some View {
        Form {
            if ServerConfig.address == nil {
                Section { Text(ServerConfig.missing) }
            } else if checking {
                Section { ProgressView() }
            } else if connected == nil {
                LoginForm { address in
                    connected = address
                    Task { await refresh() }
                }
            } else {
                if visits.isEmpty {
                    Section {
                        Text("Aucune visite envoyée au serveur pour l'instant.").foregroundStyle(.secondary)
                    }
                }
                ForEach(visits) { visit in
                    Section { row(visit) }
                }
                if let info {
                    Section { Text(info).font(.footnote).foregroundStyle(.secondary) }
                }
            }
        }
        .navigationTitle("Mes visites en ligne")
        .toolbar {
            if connected != nil {
                ToolbarItem(placement: .primaryAction) {
                    Button("Se déconnecter") {
                        Task {
                            await (try? ServerClient.configured())?.logout()
                            connected = nil
                            visits = []
                        }
                    }
                }
            }
        }
        .refreshable { await refresh() }
        .task { await start() }
        .confirmationDialog(
            "Supprimer « \(deleting?.name ?? "") » du serveur ?",
            isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }),
            titleVisibility: .visible
        ) {
            Button("Supprimer", role: .destructive) {
                if let visit = deleting { act { try await $0.delete(visit: visit.id) } }
            }
            Button("Annuler", role: .cancel) {}
        } message: {
            Text("Photos, panoramas et lien seront effacés du serveur. La visite reste sur ce téléphone.")
        }
        .problemAlert($problem)
    }

    @ViewBuilder private func row(_ visit: OnlineVisit) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(visit.name).font(.headline)
            Text(visit.label).foregroundStyle(visit.state == "echec" ? .red : visit.state == "prete" ? .green : .orange)
            if visit.state != "prete" {
                Text(visit.message).font(.footnote).foregroundStyle(.secondary)
            }
            if visit.photosDeleted {
                Text("Photos d'origine effacées du serveur (30 jours).")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }
        if let link = visit.link, let url = URL(string: link) {
            ShareLink(item: url) { Label("Partager le lien", systemImage: "square.and.arrow.up") }
            Button {
                UIPasteboard.general.string = link
                info = "Lien copié. Il est le seul accès à la visite : ne le donner qu'aux personnes voulues."
            } label: {
                Label("Copier le lien", systemImage: "doc.on.doc")
            }
            Button("Dépublier") { act { try await $0.unpublish(visit: visit.id).message } }
        } else if visit.state == "prete" || visit.state == "echec" {
            Button(visit.state == "echec" ? "Relancer l'assemblage" : "Publier") {
                act { try await $0.republish(visit: visit.id).message }
            }
        }
        if visit.state != "en_cours" {
            Button("Supprimer du serveur", role: .destructive) { deleting = visit }
        }
    }

    private func act(_ action: @escaping (ServerClient) async throws -> String) {
        Task {
            do {
                info = try await action(try ServerClient.configured())
                await refresh()
            } catch {
                problem = error.localizedDescription
            }
        }
    }

    private func start() async {
        guard ServerConfig.address != nil, SessionToken.read() != nil else {
            checking = false
            return
        }
        connected = try? await ServerClient.configured().me()
        if connected != nil {
            await refresh()
        }
        checking = false
        if connected != nil {
            // Suit l'assemblage tant qu'une visite est en cours.
            while !Task.isCancelled, visits.contains(where: \.isWorking) {
                try? await Task.sleep(for: .seconds(5))
                await refresh()
            }
        }
    }

    private func refresh() async {
        do {
            visits = try await ServerClient.configured().visits()
        } catch ServerError.notConnected {
            connected = nil
        } catch {
            problem = error.localizedDescription
        }
    }
}
