// Liste des points pris sur le téléphone, création d'un point, envoi vers le Mac.

import SwiftUI

struct PointsView: View {
    @State private var points: [PointFolder] = []
    @State private var path: [Route] = []
    @State private var askName = false
    @State private var name = ""
    @State private var problem: String?

    enum Route: Hashable {
        case capture(PointFolder)
        case detail(PointFolder)
    }

    var body: some View {
        NavigationStack(path: $path) {
            List {
                Section {
                    Button {
                        name = ""
                        askName = true
                    } label: {
                        Label("Nouveau point", systemImage: "camera.viewfinder")
                    }
                }
                Section("Points pris") {
                    if points.isEmpty {
                        Text("Aucun point pour l'instant.").foregroundStyle(.secondary)
                    }
                    ForEach(points) { point in
                        NavigationLink(value: Route.detail(point)) {
                            VStack(alignment: .leading) {
                                Text(point.name)
                                Text("\(point.load()?.photos.count ?? 0) photos")
                                    .font(.footnote).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }
            .navigationTitle("Visite360")
            .navigationDestination(for: Route.self) { route in
                switch route {
                case .capture(let point): CaptureView(point: point)
                case .detail(let point): PointDetailView(point: point)
                }
            }
            .alert("Nom du point", isPresented: $askName) {
                TextField("salon, cuisine…", text: $name)
                Button("Commencer") { create() }
                Button("Annuler", role: .cancel) {}
            } message: {
                Text("Le nom de la pièce, qui sera le nom du dossier sur le Mac.")
            }
            .alert(
                "Problème",
                isPresented: Binding(get: { problem != nil }, set: { if !$0 { problem = nil } })
            ) {
                Button("OK") {}
            } message: {
                Text(problem ?? "")
            }
            .onAppear(perform: reload)
            .onChange(of: path) { reload() }
        }
    }

    private func reload() {
        points = PointStore.list()
    }

    private func create() {
        do {
            let point = try PointStore.create(name: name)
            path.append(.capture(point))
        } catch {
            problem = "Impossible de créer le point : \(error.localizedDescription)"
        }
    }
}

struct PointDetailView: View {
    let point: PointFolder
    @State private var archive: URL?
    @State private var problem: String?

    var body: some View {
        let file = point.load()
        List {
            Section("Photos") {
                ForEach(Row.allCases, id: \.self) { row in
                    let count = file?.photos.filter { $0.row == row }.count ?? 0
                    LabeledContent(row.label, value: "\(count) sur \(row.count)")
                }
            }
            Section {
                Button {
                    share()
                } label: {
                    Label("Envoyer au Mac (AirDrop)", systemImage: "square.and.arrow.up")
                }
            } footer: {
                Text(
                    "Sur le Mac, décompresser l'archive dans visites/<nom de la visite>/, puis "
                        + "lancer visite360 stitch visites/<nom de la visite>/\(point.name). "
                        + "Le dossier est aussi visible dans le Finder quand l'iPhone est branché."
                )
            }
        }
        .navigationTitle(point.name)
        .sheet(item: Binding(get: { archive.map(SharedFile.init) }, set: { archive = $0?.url })) {
            ActivityView(items: [$0.url])
        }
        .alert(
            "Problème",
            isPresented: Binding(get: { problem != nil }, set: { if !$0 { problem = nil } })
        ) {
            Button("OK") {}
        } message: {
            Text(problem ?? "")
        }
    }

    private func share() {
        do {
            archive = try PointStore.archive(point)
        } catch {
            problem = "Impossible de préparer l'archive : \(error.localizedDescription)"
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
