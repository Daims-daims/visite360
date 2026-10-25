// Caméra arrière ×1 pilotée par ARKit (mode « ×1 + suivi AR », essai de l'étape 6) : aperçu,
// verrouillage de l'exposition, photos en pleine résolution, et surtout position de l'objectif
// en mètres, pour avertir quand il s'éloigne de sa place (parallaxe, docs/prise-de-vue.md).
//
// ARKit garde la caméra pour lui seul et n'utilise que l'objectif ×1 : ce mode n'existe pas au
// ×0,5. L'orientation des photos vient toujours de Core Motion (MotionTracker), comme dans
// l'autre mode ; ARKit ne fournit que la position.

import ARKit
import CoreImage
import Foundation
import SceneKit
import SwiftUI

final class ARCameraController: NSObject, ObservableObject, ARSessionDelegate, PhotoCamera {
    let session = ARSession()
    @Published private(set) var error: CameraError?
    @Published private(set) var isRunning = false
    /// Angle de vue sur le grand côté de l'image, en degrés, lu sur les images d'ARKit.
    private(set) var fieldOfView: Double = 70
    /// Position de l'objectif en mètres dans le repère d'ARKit, ou nil si ARKit ne suit pas la
    /// position en ce moment (démarrage, mur uni, mouvement trop rapide).
    private(set) var position: SIMD3<Double>?
    /// Direction horizontale visée par le téléphone dans le repère d'ARKit (y vers le haut).
    /// Quand il vise le plafond ou le sol, c'est la dernière direction horizontale connue.
    private(set) var heading: SIMD3<Double>?
    /// Surfaces horizontales repérées par ARKit (sol, tables, plafond), pour en déduire la
    /// hauteur de l'objectif au-dessus du sol (étape 10, FloorLevel).
    private(set) var horizontalPlanes: [FloorLevel.Plane] = []
    /// Appelé sur le fil principal à chaque image, avec la position (ou nil).
    var onPosition: ((SIMD3<Double>?) -> Void)?

    private let context = CIContext()

    func start(lens: Lens) {
        guard ARWorldTrackingConfiguration.isSupported,
              let format = ARWorldTrackingConfiguration.recommendedVideoFormatForHighResolutionFrameCapturing
        else {
            error = .failed(
                "le suivi de position ARKit n'est pas disponible sur cet appareil (le simulateur "
                    + "n'en a pas). Choisir ×0,5 ou ×1."
            )
            return
        }
        let configuration = ARWorldTrackingConfiguration()
        configuration.videoFormat = format
        configuration.worldAlignment = .gravity
        // Le sol, vu pendant la rangée de photos vers le bas, donne la hauteur de l'objectif.
        configuration.planeDetection = [.horizontal]
        session.delegate = self
        session.run(configuration, options: [.resetTracking, .removeExistingAnchors])
        isRunning = true
    }

    func stop() {
        session.pause()
        isRunning = false
    }

    /// Verrouille exposition, mise au point et balance des blancs de la caméra utilisée par ARKit.
    func lock(_ completion: @escaping (Exposure?) -> Void) {
        guard let device = ARWorldTrackingConfiguration.configurableCaptureDeviceForPrimaryCamera else {
            completion(nil)
            return
        }
        do {
            try device.lockForConfiguration()
            if device.isExposureModeSupported(.locked) { device.exposureMode = .locked }
            if device.isFocusModeSupported(.locked) { device.focusMode = .locked }
            if device.isWhiteBalanceModeSupported(.locked) { device.whiteBalanceMode = .locked }
            device.unlockForConfiguration()
        } catch {
            self.error = .failed(error.localizedDescription)
        }
        completion(Exposure(iso: Double(device.iso), durationSeconds: CMTimeGetSeconds(device.exposureDuration)))
    }

    /// Prend une photo en pleine résolution et la renvoie en JPEG, dans le sens portrait.
    func capture(_ completion: @escaping (Result<Data, Error>) -> Void) {
        session.captureHighResolutionFrame { [weak self] frame, error in
            guard let self else { return }
            let result: Result<Data, Error>
            if let error {
                result = .failure(error)
            } else if let frame, let data = jpeg(frame.capturedImage) {
                result = .success(data)
            } else {
                result = .failure(CameraError.failed("photo vide"))
            }
            DispatchQueue.main.async { completion(result) }
        }
    }

    /// L'image d'ARKit est dans le sens du capteur (paysage) : on la tourne d'un quart de tour
    /// vers la droite pour un téléphone tenu en portrait, comme les photos de CameraController.
    private func jpeg(_ buffer: CVPixelBuffer) -> Data? {
        let image = CIImage(cvPixelBuffer: buffer).oriented(.right)
        guard let space = CGColorSpace(name: CGColorSpace.sRGB) else { return nil }
        let options = [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: 0.92]
        return context.jpegRepresentation(of: image, colorSpace: space, options: options)
    }

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        let camera = frame.camera
        let width = Double(camera.imageResolution.width)
        let fx = Double(camera.intrinsics[0][0])
        if fx > 0 { fieldOfView = 2 * atan(width / 2 / fx) * 180 / .pi }
        if case .normal = camera.trackingState {
            let t = camera.transform.columns.3
            position = SIMD3(Double(t.x), Double(t.y), Double(t.z))
            // L'objectif vise l'axe -z de la caméra d'ARKit, quel que soit le sens du téléphone.
            let z = camera.transform.columns.2
            let flat = SIMD3(-Double(z.x), 0, -Double(z.z))
            if simd_length(flat) > 0.3 { heading = simd_normalize(flat) }
        } else {
            position = nil
        }
        let classifies = ARPlaneAnchor.isClassificationSupported
        horizontalPlanes = frame.anchors.compactMap { anchor in
            guard let plane = anchor as? ARPlaneAnchor, plane.alignment == .horizontal else { return nil }
            let center = plane.transform * SIMD4(plane.center, 1)
            let area = Double(plane.planeExtent.width * plane.planeExtent.height)
            let isFloor: Bool? = classifies ? plane.classification == .floor : nil
            return FloorLevel.Plane(height: Double(center.y), area: area, isFloor: isFloor)
        }
        onPosition?(position)
    }

    func session(_ session: ARSession, didFailWithError error: Error) {
        self.error = .failed(error.localizedDescription)
    }
}

/// Aperçu de la caméra quand ARKit la pilote.
struct ARPreview: UIViewRepresentable {
    let session: ARSession

    func makeUIView(context: Context) -> ARSCNView {
        let view = ARSCNView()
        view.session = session
        view.automaticallyUpdatesLighting = false
        return view
    }

    func updateUIView(_ view: ARSCNView, context: Context) {}
}
