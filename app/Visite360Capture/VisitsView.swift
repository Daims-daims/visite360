// Écrans de l'app hors prise de vue : liste des visites, points et flèches d'une visite,
// détail d'un point, envoi vers le Mac. L'envoi au serveur est dans OnlineViews.swift.

import SwiftUI

enum Route: Hashable {
    case visit(VisitFolder)
    case capture(VisitFolder, String)
    case point(VisitFolder, String)
}

struct VisitsView: View {
    @State private var visits: [VisitFolder] = []
    @State private var loose: [PointFolder] = []
    @State private var path: [Route] = []
    @State private var askName = false
    @State private var name = ""
    @State private var adopting: PointFolder?
    @State private var deleting: VisitFolder?
    @State private var problem: String?
    @AppStorage("reglage") private var setup: CaptureSetup = .wideTracked

    var body: some View {
        NavigationStack(path: $path) {
            List {
                Section {
                    Picker("Objectif", selection: $setup) {
                        ForEach(CaptureSetup.allCases, id: \.self) { Text($0.label).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    Button {
                        name = ""
                        askName = true
                    } label: {
                        Label("Nouvelle visite", systemImage: "house")
                    }
                } footer: {
                    switch setup {
                    case .wideTracked:
                        Text(
                            "×1 + AR (conseillé) : 29 photos par point. ARKit suit l'objectif, montre "
                                + "où le tenir et suspend les photos s'il s'éloigne de plus de 5 cm "
                                + "de sa place."
                        )
                    case .wide:
                        Text("×1 : 29 photos par point, sans suivi de l'objectif.")
                    case .ultraWide:
                        Text("×0,5 : 21 photos par point, sans suivi de l'objectif.")
                    }
                }
                Section("Visites") {
                    if visits.isEmpty {
                        Text("Aucune visite pour l'instant.").foregroundStyle(.secondary)
                    }
                    ForEach(visits) { visit in
                        let file = visit.load()
                        NavigationLink(value: Route.visit(visit)) {
                            VStack(alignment: .leading) {
                                Text(file.name)
                                Text("\(visit.takenPoints(file).count) point(s)")
                                    .font(.footnote).foregroundStyle(.secondary)
                            }
                        }
                        .swipeActions {
                            Button("Supprimer", role: .destructive) { deleting = visit }
                        }
                    }
                }
                if !loose.isEmpty {
                    Section {
                        ForEach(loose) { point in
                            Button {
                                adopting = point
                            } label: {
                                LabeledContent(point.name, value: "\(point.load()?.photos.count ?? 0) photos")
                            }
                        }
                    } header: {
                        Text("Points pris hors visite")
                    } footer: {
                        Text("Pris avant les visites. Toucher un point pour le ranger dans une visite.")
                    }
                }
            }
            .navigationTitle("Visite360")
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    NavigationLink {
                        OnlineVisitsView()
                    } label: {
                        Label("Mes visites en ligne", systemImage: "globe")
                    }
                }
            }
            .navigationDestination(for: Route.self) { route in
                switch route {
                case .visit(let visit): VisitView(visit: visit, path: $path)
                case .capture(let visit, let id): CaptureView(visit: visit, pointID: id, setup: setup)
                case .point(let visit, let id): PointDetailView(visit: visit, pointID: id)
                }
            }
            .alert("Nom de la visite", isPresented: $askName) {
                TextField("Appartement rue…", text: $name)
                Button("Créer") { createVisit() }
                Button("Annuler", role: .cancel) {}
            } message: {
                Text("Ce sera le nom du dossier sur le Mac.")
            }
            .confirmationDialog(
                "Ranger « \(adopting?.name ?? "") » dans quelle visite ?",
                isPresented: Binding(get: { adopting != nil }, set: { if !$0 { adopting = nil } }),
                titleVisibility: .visible
            ) {
                ForEach(visits) { visit in
                    Button(visit.load().name) { adopt(into: visit) }
                }
                Button("Annuler", role: .cancel) {}
            } message: {
                if visits.isEmpty { Text("Créer d'abord une visite.") }
            }
            .confirmationDialog(
                "Supprimer la visite et toutes ses photos de ce téléphone ?",
                isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }),
                titleVisibility: .visible
            ) {
                Button("Supprimer", role: .destructive) { deleteVisit() }
                Button("Annuler", role: .cancel) {}
            } message: {
                Text("Ce qui a déjà été envoyé au Mac ou au serveur y reste.")
            }
            .problemAlert($problem)
            .onAppear(perform: reload)
            .onChange(of: path) { reload() }
        }
    }

    private func reload() {
        visits = PointStore.visits()
        loose = PointStore.loosePoints()
    }

    private func createVisit() {
        do {
            path.append(.visit(try PointStore.createVisit(name: name)))
        } catch {
            problem = "Impossible de créer la visite : \(error.localizedDescription)"
        }
    }

    private func adopt(into visit: VisitFolder) {
        guard let point = adopting else { return }
        do {
            try visit.adopt(point)
        } catch {
            problem = "Impossible de ranger le point : \(error.localizedDescription)"
        }
        reload()
    }

    private func deleteVisit() {
        guard let visit = deleting else { return }
        do {
            try PointStore.deleteVisit(visit)
        } catch {
            problem = "Impossible de supprimer la visite : \(error.localizedDescription)"
        }
        reload()
    }
}

struct VisitView: View {
    let visit: VisitFolder
    @Binding var path: [Route]
    @State private var file = VisitFile(name: "")
    @State private var taken: Set<String> = []
    @State private var askName = false
    @State private var name = ""
    @State private var sending = false
    @State private var sendingOnline = false
    @State private var archive: URL?
    @State private var problem: String?

    var body: some View {
        let points = file.points.filter { taken.contains($0.id) }
        let announced = file.points.filter { !taken.contains($0.id) }
        List {
            Section("Points pris") {
                if points.isEmpty {
                    Text("Aucun point pour l'instant.").foregroundStyle(.secondary)
                }
                ForEach(points, id: \.id) { point in
                    NavigationLink(value: Route.point(visit, point.id)) {
                        VStack(alignment: .leading) {
                            Text(point.name + (file.start == point.id ? " (départ)" : ""))
                            Text(
                                "\(visit.point(point.id).load()?.photos.count ?? 0) photos, "
                                    + "\(file.links(from: point.id).count) flèche(s)"
                            )
                            .font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                }
            }
            if !announced.isEmpty {
                Section {
                    ForEach(announced, id: \.id) { point in
                        Button {
                            startPoint(name: point.name, announced: point.id)
                        } label: {
                            Label("Prendre « \(point.name) »", systemImage: "camera.viewfinder")
                        }
                    }
                } header: {
                    Text("Pièces à prendre")
                } footer: {
                    Text("Annoncées par une flèche depuis un autre point.")
                }
            }
            Section {
                Button {
                    name = ""
                    askName = true
                } label: {
                    Label("Nouveau point", systemImage: "camera.viewfinder")
                }
            }
            if !file.links.isEmpty {
                Section {
                    ForEach(Array(file.links.enumerated()), id: \.offset) { _, link in
                        LabeledContent(
                            "\(file.displayName(link.from)) → \(file.displayName(link.to))",
                            value: String(format: "%.0f°", link.angle)
                        )
                    }
                    .onDelete(perform: deleteLinks)
                } header: {
                    Text("Flèches")
                } footer: {
                    Text(
                        "Une flèche se vise à la fin de la prise de vue d'un point. Pour en refaire "
                            + "une, supprimer le point et le reprendre, ou corriger l'angle dans "
                            + "visite.json sur le Mac."
                    )
                }
            }
            Section {
                Button {
                    sendingOnline = true
                } label: {
                    Label("Envoyer au serveur", systemImage: "icloud.and.arrow.up")
                }
                .disabled(points.isEmpty)
            } footer: {
                Text(
                    "Le serveur assemble la visite, la met en ligne et donne le lien de partage, "
                        + "sans passer par le Mac. Fonctionne en Wi-Fi comme en 4G."
                )
            }
            Section {
                Button {
                    sending = true
                } label: {
                    Label("Envoyer au Mac (Wi-Fi)", systemImage: "wifi")
                }
                .disabled(points.isEmpty)
                Button {
                    share()
                } label: {
                    Label("Envoyer par AirDrop", systemImage: "square.and.arrow.up")
                }
                .disabled(points.isEmpty)
            } footer: {
                Text(
                    "Wi-Fi : lancer d'abord visite360 receive sur le Mac. AirDrop : décompresser "
                        + "l'archive dans visites/ sur le Mac."
                )
            }
        }
        .navigationTitle(file.name)
        .onAppear(perform: reload)
        .alert("Nom du point", isPresented: $askName) {
            TextField("salon, cuisine…", text: $name)
            Button("Commencer") { startPoint(name: name, announced: nil) }
            Button("Annuler", role: .cancel) {}
        } message: {
            Text("Le nom de la pièce, qui sera le nom du dossier sur le Mac.")
        }
        .sheet(isPresented: $sending) {
            SendView(visit: visit)
        }
        .sheet(isPresented: $sendingOnline) {
            ServerSendView(visit: visit)
        }
        .sheet(item: Binding(get: { archive.map(SharedFile.init) }, set: { archive = $0?.url })) {
            ActivityView(items: [$0.url])
        }
        .problemAlert($problem)
    }

    private func reload() {
        file = visit.load()
        taken = visit.takenPoints(file)
    }

    private func startPoint(name: String, announced: String?) {
        do {
            let point = try visit.createPoint(name: name, announced: announced)
            path.append(.capture(visit, point.name))
        } catch {
            problem = "Impossible de créer le point : \(error.localizedDescription)"
        }
    }

    private func deleteLinks(_ offsets: IndexSet) {
        do {
            try visit.update { $0.links.remove(atOffsets: offsets) }
        } catch {
            problem = "Impossible d'enregistrer la visite : \(error.localizedDescription)"
        }
        reload()
    }

    private func share() {
        do {
            try visit.save(visit.load())
            archive = try PointStore.archive(visit.url)
        } catch {
            problem = "Impossible de préparer l'archive : \(error.localizedDescription)"
        }
    }
}

struct PointDetailView: View {
    let visit: VisitFolder
    let pointID: String
    @Environment(\.dismiss) private var dismiss
    @State private var confirmDelete = false
    @State private var problem: String?

    var body: some View {
        let point = visit.point(pointID)
        let file = point.load()
        let tour = visit.load()
        let lens = file?.lens ?? .wide
        List {
            Section("Photos, objectif \(lens.label)") {
                ForEach(Row.allCases, id: \.self) { row in
                    let count = file?.photos.filter { $0.row == row }.count ?? 0
                    LabeledContent(row.label, value: "\(count) sur \(row.count(lens))")
                }
            }
            Section("Flèches") {
                let links = tour.links(from: pointID)
                if links.isEmpty {
                    Text("Aucune flèche depuis ce point.").foregroundStyle(.secondary)
                }
                ForEach(Array(links.enumerated()), id: \.offset) { _, link in
                    LabeledContent(
                        "→ \(tour.displayName(link.to))", value: String(format: "%.0f°", link.angle)
                    )
                }
            }
            Section {
                Button("Supprimer ce point", role: .destructive) { confirmDelete = true }
            } footer: {
                Text("Pour reprendre une pièce : supprimer le point, puis le reprendre depuis la visite.")
            }
        }
        .navigationTitle(tour.displayName(pointID))
        .confirmationDialog(
            "Supprimer ce point et ses photos de ce téléphone ?",
            isPresented: $confirmDelete, titleVisibility: .visible
        ) {
            Button("Supprimer", role: .destructive) { delete() }
            Button("Annuler", role: .cancel) {}
        } message: {
            Text("Ce qui a déjà été envoyé au Mac y reste.")
        }
        .problemAlert($problem)
    }

    private func delete() {
        do {
            try visit.deletePoint(pointID)
            dismiss()
        } catch {
            problem = "Impossible de supprimer le point : \(error.localizedDescription)"
        }
    }
}

/// Envoi de la visite au Mac qui fait tourner `visite360 receive`.
struct SendView: View {
    let visit: VisitFolder
    @StateObject private var finder = MacFinder()
    @Environment(\.dismiss) private var dismiss
    @AppStorage("adresseMac") private var address = ""
    @AppStorage("codeMac") private var code = ""
    @State private var selected: FoundMac?
    @State private var isSending = false
    @State private var fraction = 0.0
    @State private var status = ""
    @State private var result: String?
    @State private var problem: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    if finder.macs.isEmpty {
                        HStack {
                            ProgressView()
                            Text("Recherche du Mac sur le Wi-Fi…").foregroundStyle(.secondary)
                        }
                    }
                    ForEach(finder.macs) { mac in
                        Button {
                            selected = mac
                        } label: {
                            HStack {
                                Text(mac.name)
                                Spacer()
                                if selected == mac { Image(systemName: "checkmark") }
                            }
                        }
                    }
                    TextField("ou adresse : 192.168.1.20:8361", text: $address)
                        .keyboardType(.numbersAndPunctuation)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                } header: {
                    Text("Mac")
                } footer: {
                    Text(
                        finder.problem
                            ?? "Sur le Mac, lancer visite360 receive. Le Mac apparaît ici s'il est sur "
                            + "le même Wi-Fi ; sinon, recopier l'adresse qu'il affiche."
                    )
                }
                Section("Code affiché sur le Mac") {
                    TextField("123 456", text: $code)
                        .keyboardType(.numberPad)
                }
                Section {
                    Button("Envoyer") { Task { await send() } }
                        .disabled(isSending || code.filter(\.isNumber).count != 6)
                    if isSending {
                        ProgressView(value: fraction) { Text(status) }
                    }
                } footer: {
                    Text("Garder l'app ouverte pendant l'envoi. Un envoi interrompu se reprend : "
                        + "seuls les fichiers manquants repartent.")
                }
                if let result {
                    Section("Reçu par le Mac") {
                        Text(result)
                        Text("Pour la voir sur le Mac : visite360 serve visites/\(visit.folderName)")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                }
            }
            .navigationTitle("Envoyer au Mac")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Fermer") { dismiss() }.disabled(isSending)
                }
            }
            .onAppear { finder.start() }
            .onDisappear { finder.stop() }
            .onChange(of: finder.macs) {
                if selected == nil, finder.macs.count == 1 { selected = finder.macs.first }
            }
            .problemAlert($problem)
        }
        .interactiveDismissDisabled(isSending)
    }

    private func send() async {
        isSending = true
        result = nil
        UIApplication.shared.isIdleTimerDisabled = true
        defer {
            isSending = false
            UIApplication.shared.isIdleTimerDisabled = false
        }
        do {
            let target: (host: String, port: Int)
            if !address.trimmingCharacters(in: .whitespaces).isEmpty {
                guard let parsed = Uploader.parse(address: address) else {
                    throw TransferError.message("Adresse invalide. Exemple : 192.168.1.20:8361.")
                }
                target = parsed
            } else if let selected {
                status = "Connexion au Mac…"
                target = try await MacFinder.resolve(selected.endpoint)
            } else {
                throw TransferError.message("Choisir un Mac ou saisir son adresse.")
            }
            let uploader = Uploader(host: target.host, port: target.port, code: code.filter(\.isNumber))
            try await uploader.check()
            result = try await uploader.send(visit: visit) { value, text in
                fraction = value
                status = text
            }
        } catch {
            problem = error.localizedDescription
        }
    }
}

private struct SharedFile: Identifiable {
    let url: URL
    var id: URL { url }
}

/// Feuille de partage du système (AirDrop, Fichiers…).
struct ActivityView: UIViewControllerRepresentable {
    let items: [Any]

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }

    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}

extension View {
    /// Alerte « Problème » affichée tant que message n'est pas nil.
    func problemAlert(_ message: Binding<String?>) -> some View {
        alert(
            "Problème",
            isPresented: Binding(get: { message.wrappedValue != nil }, set: { if !$0 { message.wrappedValue = nil } })
        ) {
            Button("OK") {}
        } message: {
            Text(message.wrappedValue ?? "")
        }
    }
}
