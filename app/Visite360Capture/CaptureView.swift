// Écran de prise de vue : aperçu de la caméra, cibles à viser, consignes.

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

    init(point: PointFolder, lens: Lens) {
        _model = StateObject(wrappedValue: CaptureModel(point: point, lens: lens))
    }

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            CameraPreview(session: model.camera.session).ignoresSafeArea()
            if let rotation = model.rotation, model.phase == .shooting {
                TargetsOverlay(
                    rotation: rotation, targets: model.targets, done: Set(model.done.keys),
                    suggested: model.suggested, fieldOfView: model.camera.fieldOfView
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
            } else if let target = model.suggested {
                Text("\(target.row.label) : photo \(target.number) sur \(target.rowCount)")
                    .font(.headline)
                Text(hint(for: target))
                Text("Tournez autour du téléphone, pas sur vous-même.").font(.footnote)
            } else {
                Text("Toutes les photos sont prises.").font(.headline)
            }
        }
        .multilineTextAlignment(.center)
        .foregroundStyle(.white)
        .padding(12)
        .frame(maxWidth: .infinity)
        .background(.black.opacity(0.55), in: RoundedRectangle(cornerRadius: 12))
    }

    private var footer: some View {
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
