// Orientation du téléphone par Core Motion (gyroscope et accéléromètre), 60 fois par seconde.

import CoreMotion
import Foundation
import simd

final class MotionTracker {
    private let manager = CMMotionManager()

    var isAvailable: Bool { manager.isDeviceMotionAvailable }

    /// Mesures brutes pour RotationAxis (réglage « ×0,5 + capteurs ») : instant en secondes,
    /// vitesse de rotation en rad/s et accélération donnée par l'utilisateur en m/s², dans le
    /// repère de l'appareil. Appelé sur le fil principal, avant handler.
    var onSample: ((Double, SIMD3<Double>, SIMD3<Double>) -> Void)?

    /// Appelle handler sur le fil principal avec la rotation caméra → monde et la vitesse de
    /// rotation du téléphone (degrés par seconde).
    ///
    /// Référence « X arbitraire, Z vertical » : gyroscope et gravité seulement, sans la
    /// boussole, que les appareils électriques et le métal d'un logement perturbent.
    func start(_ handler: @escaping (simd_double3x3, Double) -> Void) {
        guard manager.isDeviceMotionAvailable, !manager.isDeviceMotionActive else { return }
        manager.deviceMotionUpdateInterval = 1.0 / 60.0
        manager.startDeviceMotionUpdates(using: .xArbitraryZVertical, to: .main) { [weak self] motion, _ in
            guard let self, let motion else { return }
            let q = motion.attitude.quaternion
            let g = motion.gravity
            let deviceToReference = Orientation.deviceToReference(
                quaternion: simd_quatd(ix: q.x, iy: q.y, iz: q.z, r: q.w),
                gravity: SIMD3(g.x, g.y, g.z)
            )
            let r = motion.rotationRate
            let a = motion.userAcceleration
            self.onSample?(
                motion.timestamp, SIMD3(r.x, r.y, r.z), SIMD3(a.x, a.y, a.z) * 9.81
            )
            let speed = simd_length(SIMD3(r.x, r.y, r.z)) * 180 / .pi
            handler(Orientation.cameraToWorld(deviceToReference: deviceToReference), speed)
        }
    }

    func stop() {
        manager.stopDeviceMotionUpdates()
    }
}
