// Écran de prise de vue : aperçu de la caméra, cibles à viser, consignes, puis flèches vers
// les autres pièces.

import AVFoundation
import simd
import SwiftUI

struct CameraPreview: UIViewRepresentable {
    let session: AVCaptureSession

    final class PreviewView: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
        var preview: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }
    }

    func makeUIView(context: Context) -> PreviewView {
        let view = PreviewView()
        view.preview.session = session
        view.preview.videoGravity = .resizeAspectFill
        return view
    }

    func updateUIView(_ view: PreviewView, context: Context) {
        if let connection = view.preview.connection, connection.isVideoRotationAngleSupported(90) {
            connection.videoRotationAngle = 90
        }
    }
}

/// Cibles dessinées par-dessus l'aperçu, là où elles se trouvent dans la pièce.
struct TargetsOverlay: View {
    let rotation: simd_double3x3
    let targets: [Target]
    let done: Set<Int>
    let suggested: Target?
    /// Flèches déjà visées : direction dans le monde et nom de la pièce d'arrivée.
    let arrows: [(direction: SIMD3<Double>, label: String)]
    let fieldOfView: Double

    var body: some View {
        Canvas { context, size in
            // L'aperçu remplit la hauteur de l'écran avec le grand côté de l'image.
            let focal = Double(size.height) / 2 / tan(fieldOfView * .pi / 360)
            let center = CGPoint(x: size.width / 2, y: size.height / 2)
            for target in targets {
                guard let p = Orientation.project(target.direction, rotation: rotation, focal: focal)
                else { continue }
                let point = CGPoint(x: center.x + p.x, y: center.y + p.y)
                let isDone = done.contains(target.id)
                let isNext = target.id == suggested?.id
                let radius: CGFloat = isNext ? 22 : 12
                let circle = Path(ellipseIn: CGRect(
                    x: point.x - radius, y: point.y - radius, width: 2 * radius, height: 2 * radius
                ))
                if isDone {
                    context.fill(circle, with: .color(.green.opacity(0.7)))
                } else {
                    context.stroke(circle, with: .color(isNext ? .orange : .white), lineWidth: isNext ? 4 : 2)
                }
            }
            for arrow in arrows {
                guard let p = Orientation.project(arrow.direction, rotation: rotation, focal: focal)
                else { continue }
                let point = CGPoint(x: center.x + p.x, y: center.y + p.y)
                let marker = Path(ellipseIn: CGRect(x: point.x - 9, y: point.y - 9, width: 18, height: 18))
                context.fill(marker, with: .color(.blue))
                context.draw(
                    Text("→ \(arrow.label)").font(.headline).foregroundStyle(.white),
                    at: CGPoint(x: point.x, y: point.y - 24)
                )
            }
            let reticle = Path(ellipseIn: CGRect(x: center.x - 28, y: center.y - 28, width: 56, height: 56))
            context.stroke(reticle, with: .color(.white.opacity(0.9)), lineWidth: 2)
        }
        .allowsHitTesting(false)
    }
}

struct CaptureView: View {
    @StateObject private var model: CaptureModel
    @Environment(\.dismiss) private var dismiss
    @State private var confirmStop = false
    /// Direction notée au moment de « Flèche ici », pendant le choix de la pièce.
    @State private var aim: Aim?

    struct Aim: Identifiable {
        let id = UUID()
        let angle: Double
        let pitch: Double
    }

    init(visit: VisitFolder, pointID: String, setup: CaptureSetup) {
        _model = StateObject(wrappedValue: CaptureModel(visit: visit, pointID: pointID, setup: setup))
    }

    private var arrowsDone: Bool { model.phase == .shooting && model.mandatoryLeft == 0 }

    private var arrowMarkers: [(direction: SIMD3<Double>, label: String)] {
        guard let startYaw = model.startYaw else { return [] }
        let file = model.visit.load()
        return model.arrows.map {
            (Orientation.direction(yaw: startYaw + $0.angle, pitch: $0.pitch ?? 0), file.displayName($0.to))
        }
    }

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            if let tracker = model.tracker {
                ARPreview(session: tracker.session).ignoresSafeArea()
            } else if let camera = model.camera as? CameraController {
                CameraPreview(session: camera.session).ignoresSafeArea()
            }
            if let rotation = model.rotation, model.phase == .shooting {
                TargetsOverlay(
                    rotation: rotation, targets: model.targets, done: Set(model.done.keys),
                    suggested: model.suggested, arrows: arrowMarkers,
                    fieldOfView: model.camera.fieldOfView
                )
                .ignoresSafeArea()
            }
            VStack {
                header
                Spacer()
                footer
            }
            .padding()
        }
        .navigationBarBackButtonHidden(true)
        .statusBarHidden()
        .onAppear {
            UIApplication.shared.isIdleTimerDisabled = true
            model.start()
        }
        .onDisappear {
            UIApplication.shared.isIdleTimerDisabled = false
            model.stop()
        }
        .confirmationDialog(
            "Il manque \(model.mandatoryLeft) photo(s). Arrêter quand même ?",
            isPresented: $confirmStop, titleVisibility: .visible
        ) {
            Button("Arrêter, le panorama aura des trous", role: .destructive) { dismiss() }
            Button("Continuer la prise de vue", role: .cancel) {}
        }
        .sheet(item: $aim) { aim in
            ArrowTargetSheet(model: model) { choice in
                switch choice {
                case .point(let id): model.addArrow(to: id, angle: aim.angle, pitch: aim.pitch)
                case .newRoom(let name): model.addArrow(toNewRoom: name, angle: aim.angle, pitch: aim.pitch)
                }
                self.aim = nil
            }
        }
        .alert(
            "Problème",
            isPresented: Binding(get: { model.problem != nil }, set: { if !$0 { model.problem = nil } })
        ) {
            Button("OK") {}
        } message: {
            Text(model.problem ?? "")
        }
    }

    private var header: some View {
        VStack(spacing: 6) {
            if let error = model.camera.error {
                Text(error.localizedDescription)
            } else if model.phase == .framing {
                Text("Visez un mur moyennement éclairé, pas une fenêtre.")
                Text("L'exposition sera la même pour toutes les photos du point.")
                    .font(.footnote)
            } else if model.drift.isTooFar, let offset = model.drift.offset {
                Text("L'objectif s'est déplacé de \(Int((offset * 100).rounded())) cm").font(.headline)
                Text(model.placement?.instruction ?? "Revenez au-dessus de la marque au sol.")
                Text("Suivez le point du guide jusqu'à la croix. Les photos reprendront ensuite.")
                    .font(.footnote)
            } else if let target = model.suggested {
                Text("\(target.row.label) : photo \(target.number) sur \(target.rowCount)")
                    .font(.headline)
                Text(hint(for: target))
                Text("Tournez autour du téléphone, pas sur vous-même.").font(.footnote)

            } else {
                Text("Toutes les photos sont prises.").font(.headline)
                Text("Visez le milieu de chaque porte vers une autre pièce, puis « Flèche ici ».")
                Text(
                    model.arrows.isEmpty
                        ? "Les flèches de la visite partiront de là."
                        : "\(model.arrows.count) flèche(s) : un rond bleu chacune."
                )
                .font(.footnote)
            }
        }
        .multilineTextAlignment(.center)
        .foregroundStyle(.white)
        .padding(12)
        .frame(maxWidth: .infinity)
        .background(
            model.drift.isTooFar ? Color.red.opacity(0.85) : Color.black.opacity(0.55),
            in: RoundedRectangle(cornerRadius: 12)
        )
    }



    private var footer: some View {
        VStack(spacing: 12) {
            if model.tracker != nil, model.phase == .shooting {
                PlacementGuide(placement: model.placement, drift: model.drift, lensHeight: model.lensHeight)
            }
            if arrowsDone {
                Button {
                    if let current = model.currentAim() {
                        aim = Aim(angle: current.angle, pitch: current.pitch)
                    }
                } label: {
                    Label("Flèche ici", systemImage: "arrow.up.right.circle")
                }
                .buttonStyle(.borderedProminent)
                .tint(.blue)
            }
            buttons
        }
        .controlSize(.large)
    }

    private var buttons: some View {
        HStack(spacing: 12) {
            if model.phase == .framing {
                Button("Annuler") { dismiss() }
                    .buttonStyle(.bordered)
                Button("Verrouiller et commencer") { model.begin() }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.rotation == nil || !model.camera.isRunning)
            } else {
                Button("Refaire la dernière") { model.undoLast() }
                    .buttonStyle(.bordered)
                    .disabled(model.done.isEmpty || model.isBusy)
                Button(model.mandatoryLeft == 0 ? "Terminer" : "Arrêter") {
                    if model.mandatoryLeft == 0 { dismiss() } else { confirmStop = true }
                }
                .buttonStyle(.borderedProminent)
            }
        }
        .tint(.orange)
        .controlSize(.large)
    }

    /// Consigne pour amener l'objectif sur la cible conseillée.
    private func hint(for target: Target) -> String {
        guard let rotation = model.rotation else { return "" }
        if model.isBusy { return "Photo…" }
        if let roll = Orientation.roll(rotation), abs(roll) > Aiming().rollTolerance {
            return "Tenez le téléphone droit."
        }
        let pitch = target.pitch - Orientation.pitch(rotation)
        if abs(target.pitch) < 80 {
            let yaw = Orientation.wrap(target.yaw - Orientation.yaw(rotation))
            if abs(yaw) > 4 { return yaw > 0 ? "Tournez vers la droite →" : "← Tournez vers la gauche" }
        }
        if abs(pitch) > 3 { return pitch > 0 ? "Inclinez vers le haut ↑" : "Inclinez vers le bas ↓" }
        return model.isSteady ? "Visez le rond orange." : "Ne bougez plus…"
    }
}

/// Choix de la pièce où mène une flèche : un autre point de la visite, ou une pièce pas encore
/// prise, qui sera proposée au moment de créer le point suivant.
struct ArrowTargetSheet: View {
    enum Choice {
        case point(String)
        case newRoom(String)
    }

    @ObservedObject var model: CaptureModel
    let choose: (Choice) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var newRoom = ""

    var body: some View {
        let file = model.visit.load()
        let others = file.points.filter { $0.id != model.pointID }
        NavigationStack {
            List {
                if !others.isEmpty {
                    Section("Vers un point de la visite") {
                        ForEach(others, id: \.id) { point in
                            Button {
                                choose(.point(point.id))
                            } label: {
                                LabeledContent(
                                    point.name,
                                    value: model.visit.point(point.id).isTaken ? "" : "à prendre"
                                )
                            }
                        }
                    }
                }
                Section {
                    TextField("cuisine, chambre…", text: $newRoom)
                    Button("Ajouter la flèche") {
                        choose(.newRoom(newRoom))
                    }
                    .disabled(newRoom.trimmingCharacters(in: .whitespaces).isEmpty)
                } header: {
                    Text("Vers une pièce pas encore prise")
                } footer: {
                    Text("Elle sera proposée quand vous créerez le point suivant.")
                }
            }
            .navigationTitle("Où mène cette porte ?")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Annuler") { dismiss() }
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}

/// Réglage « ×1 + AR » : vue de dessus de l'objectif par rapport à sa place de départ. La
/// croix est la place, le point l'objectif ; le haut du guide est la direction visée. À droite,
/// une jauge pour la hauteur. Vert : à sa place ; orange : il s'en éloigne ; rouge : trop loin,
/// les photos sont suspendues.
struct PlacementGuide: View {
    let placement: Placement?
    let drift: LensDrift
    /// Hauteur de l'objectif au-dessus du sol, une fois le sol repéré (étape 10).
    let lensHeight: Double?

    /// Rayon du guide, en mètres : au-delà, le point reste collé au bord.
    private let range = 0.08

    private var color: Color {
        guard let offset = drift.offset else { return .gray }
        if drift.isTooFar { return .red }
        return offset < drift.clear * 0.6 ? .green : .orange
    }

    var body: some View {
        HStack(alignment: .center, spacing: 14) {
            Canvas { context, size in
                let radius = Double(min(size.width, size.height)) / 2 - 6
                let center = CGPoint(x: size.width / 2, y: size.height / 2)
                let scale = radius / range
                func circle(_ r: Double) -> Path {
                    Path(ellipseIn: CGRect(x: center.x - r, y: center.y - r, width: 2 * r, height: 2 * r))
                }
                context.fill(circle(radius), with: .color(.black.opacity(0.45)))
                context.stroke(circle(drift.limit * scale), with: .color(.white.opacity(0.8)), lineWidth: 1.5)
                context.stroke(circle(drift.clear * 0.6 * scale), with: .color(.green.opacity(0.7)), lineWidth: 1)
                var cross = Path()
                cross.move(to: CGPoint(x: center.x - 8, y: center.y))
                cross.addLine(to: CGPoint(x: center.x + 8, y: center.y))
                cross.move(to: CGPoint(x: center.x, y: center.y - 8))
                cross.addLine(to: CGPoint(x: center.x, y: center.y + 8))
                context.stroke(cross, with: .color(.white), lineWidth: 2)
                // Direction visée, en haut du guide.
                var tick = Path()
                tick.move(to: CGPoint(x: center.x - 6, y: center.y - radius + 8))
                tick.addLine(to: CGPoint(x: center.x, y: center.y - radius + 1))
                tick.addLine(to: CGPoint(x: center.x + 6, y: center.y - radius + 8))
                context.stroke(tick, with: .color(.white.opacity(0.8)), lineWidth: 2)
                guard let placement else { return }
                var x = placement.right * scale, y = -placement.forward * scale
                let length = (x * x + y * y).squareRoot()
                if length > radius - 6 {
                    x *= (radius - 6) / length
                    y *= (radius - 6) / length
                }
                let dot = CGPoint(x: center.x + x, y: center.y + y)
                var arrow = Path()
                arrow.move(to: dot)
                arrow.addLine(to: center)
                context.stroke(arrow, with: .color(color.opacity(0.8)), style: StrokeStyle(lineWidth: 2, dash: [4, 3]))
                context.fill(Path(ellipseIn: CGRect(x: dot.x - 7, y: dot.y - 7, width: 14, height: 14)), with: .color(color))
            }
            .frame(width: 120, height: 120)
            heightGauge
            VStack(alignment: .leading, spacing: 4) {
                if let offset = drift.offset {
                    Text("Objectif à \(Int((offset * 100).rounded())) cm de sa place")
                        .font(.subheadline.bold())
                    Text("Limite \(Int(drift.limit * 100)) cm").font(.caption)
                    if let placement, offset >= Placement.negligible {
                        Text(placement.instruction).font(.caption)
                    }
                } else {
                    Text("Suivi de position…").font(.subheadline.bold())
                    Text("Bougez doucement pour qu'ARKit repère la pièce.").font(.caption)
                }
                if let lensHeight {
                    Text("Sol repéré : objectif à \(lensHeight.formatted(.number.precision(.fractionLength(2)))) m")
                        .font(.caption)
                } else {
                    Text("Sol pas encore repéré : il le sera pendant les photos vers le bas.")
                        .font(.caption)
                }
            }
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(10)
        .background(.black.opacity(0.45), in: RoundedRectangle(cornerRadius: 12))
    }

    /// Hauteur de l'objectif : le trait blanc est la hauteur de départ.
    private var heightGauge: some View {
        Canvas { context, size in
            let middle = Double(size.height) / 2
            let scale = (middle - 6) / range
            let bar = Path(roundedRect: CGRect(x: size.width / 2 - 3, y: 0, width: 6, height: size.height), cornerRadius: 3)
            context.fill(bar, with: .color(.black.opacity(0.45)))
            var level = Path()
            level.move(to: CGPoint(x: 0, y: middle))
            level.addLine(to: CGPoint(x: size.width, y: middle))
            context.stroke(level, with: .color(.white), lineWidth: 2)
            guard let placement else { return }
            let y = middle - max(-range, min(range, placement.up)) * scale
            context.fill(
                Path(ellipseIn: CGRect(x: Double(size.width) / 2 - 6, y: y - 6, width: 12, height: 12)),
                with: .color(color)
            )
        }
        .frame(width: 16, height: 120)
    }
}
