// Caméra arrière principale (×1) par AVFoundation : aperçu, verrouillage de l'exposition, de
// la mise au point et de la balance des blancs, prise de photos JPEG.

import AVFoundation
import Foundation

/// Réglages d'exposition verrouillés, notés dans capture.json.
struct Exposure: Codable {
    let iso: Double
    let durationSeconds: Double

    enum CodingKeys: String, CodingKey {
        case iso
        case durationSeconds = "duree_s"
    }
}

enum CameraError: LocalizedError {
    case denied
    case unavailable
    case failed(String)

    var errorDescription: String? {
        switch self {
        case .denied:
            "L'accès à la caméra est refusé. L'autoriser dans Réglages > Visite360."
        case .unavailable:
            "Caméra arrière introuvable pour cet objectif. Le simulateur n'a pas de caméra : "
                + "utiliser un iPhone, ou choisir l'autre objectif."
        case .failed(let message):
            "La caméra a échoué : \(message)"
        }
    }
}

final class CameraController: NSObject, ObservableObject, AVCapturePhotoCaptureDelegate {
    let session = AVCaptureSession()
    @Published private(set) var error: CameraError?
    @Published private(set) var isRunning = false
    /// Angle de vue sur le grand côté de l'image, en degrés.
    private(set) var fieldOfView: Double = 70

    private let output = AVCapturePhotoOutput()
    private let queue = DispatchQueue(label: "visite360.camera")
    private var device: AVCaptureDevice?
    private var pending: [Int64: (Result<Data, Error>) -> Void] = [:]

    func start(lens: Lens) {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            queue.async { self.configure(lens) }
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { granted in
                if granted {
                    self.queue.async { self.configure(lens) }
                } else {
                    self.report(.denied)
                }
            }
        default:
            report(.denied)
        }
    }

    func stop() {
        queue.async {
            self.session.stopRunning()
            DispatchQueue.main.async { self.isRunning = false }
        }
    }

    private func report(_ error: CameraError) {
        DispatchQueue.main.async { self.error = error }
    }

    private func configure(_ lens: Lens) {
        if session.isRunning { return }
        let type: AVCaptureDevice.DeviceType =
            lens == .ultraWide ? .builtInUltraWideCamera : .builtInWideAngleCamera
        guard let device = AVCaptureDevice.default(type, for: .video, position: .back) else {
            report(.unavailable)
            return
        }
        do {
            session.beginConfiguration()
            session.sessionPreset = .photo
            if session.inputs.isEmpty {
                let input = try AVCaptureDeviceInput(device: device)
                guard session.canAddInput(input), session.canAddOutput(output) else {
                    throw CameraError.failed("configuration refusée")
                }
                session.addInput(input)
                session.addOutput(output)
            }
            output.maxPhotoQualityPrioritization = .balanced
            if let connection = output.connection(with: .video),
               connection.isVideoRotationAngleSupported(90) {
                // Portrait : la photo est enregistrée dans le sens où on la voit à l'écran.
                connection.videoRotationAngle = 90
            }
            session.commitConfiguration()
            // Le grand-angle déforme les bords de l'image : iOS le corrige, l'assemblage suppose
            // une image sans déformation.
            if device.isGeometricDistortionCorrectionSupported {
                try device.lockForConfiguration()
                device.isGeometricDistortionCorrectionEnabled = true
                device.unlockForConfiguration()
            }
            self.device = device
            fieldOfView = Double(device.activeFormat.videoFieldOfView)
            session.startRunning()
            DispatchQueue.main.async { self.isRunning = true }
        } catch {
            session.commitConfiguration()
            report(.failed(error.localizedDescription))
        }
    }

    /// Verrouille exposition, mise au point et balance des blancs sur la scène actuelle, pour
    /// que toutes les photos du point aient la même luminosité (docs/prise-de-vue.md).
    func lock(_ completion: @escaping (Exposure?) -> Void) {
        queue.async {
            guard let device = self.device else {
                DispatchQueue.main.async { completion(nil) }
                return
            }
            do {
                try device.lockForConfiguration()
                if device.isExposureModeSupported(.locked) { device.exposureMode = .locked }
                if device.isFocusModeSupported(.locked) { device.focusMode = .locked }
                if device.isWhiteBalanceModeSupported(.locked) { device.whiteBalanceMode = .locked }
                device.unlockForConfiguration()
            } catch {
                self.report(.failed(error.localizedDescription))
            }
            let exposure = Exposure(
                iso: Double(device.iso), durationSeconds: CMTimeGetSeconds(device.exposureDuration)
            )
            DispatchQueue.main.async { completion(exposure) }
        }
    }

    /// Rend la main à l'exposition automatique.
    func unlock() {
        queue.async {
            guard let device = self.device, (try? device.lockForConfiguration()) != nil else { return }
            if device.isExposureModeSupported(.continuousAutoExposure) {
                device.exposureMode = .continuousAutoExposure
            }
            if device.isFocusModeSupported(.continuousAutoFocus) { device.focusMode = .continuousAutoFocus }
            if device.isWhiteBalanceModeSupported(.continuousAutoWhiteBalance) {
                device.whiteBalanceMode = .continuousAutoWhiteBalance
            }
            device.unlockForConfiguration()
        }
    }

    /// Prend une photo JPEG. completion est appelé sur le fil principal.
    func capture(_ completion: @escaping (Result<Data, Error>) -> Void) {
        queue.async {
            let settings = AVCapturePhotoSettings(format: [AVVideoCodecKey: AVVideoCodecType.jpeg])
            settings.flashMode = .off
            // Pas de fusion de plusieurs images : rendu plus régulier d'une photo à l'autre.
            settings.photoQualityPrioritization = .speed
            self.pending[settings.uniqueID] = completion
            self.output.capturePhoto(with: settings, delegate: self)
        }
    }

    func photoOutput(
        _ output: AVCapturePhotoOutput, didFinishProcessingPhoto photo: AVCapturePhoto, error: Error?
    ) {
        let id = photo.resolvedSettings.uniqueID
        let result: Result<Data, Error>
        if let error {
            result = .failure(error)
        } else if let data = photo.fileDataRepresentation() {
            result = .success(data)
        } else {
            result = .failure(CameraError.failed("photo vide"))
        }
        queue.async {
            let completion = self.pending.removeValue(forKey: id)
            DispatchQueue.main.async { completion?(result) }
        }
    }
}
