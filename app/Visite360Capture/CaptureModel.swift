// Déroulement de la prise de vue d'un point : cadrage et verrouillage de l'exposition,
// déclenchement automatique quand le téléphone vise une cible et ne bouge plus, puis flèches
// visées vers les autres pièces de la visite (étape 6).

import Foundation
import simd
import UIKit

@MainActor
final class CaptureModel: ObservableObject {
    enum Phase {
        /// Le photographe vise un mur moyennement éclairé avant de verrouiller l'exposition.
        case framing
        case shooting
    }

    /// Le téléphone doit rester presque immobile un court instant avant le déclenchement.
    static let steadySpeed = 8.0   // degrés par seconde
    static let steadyDelay = 0.35  // secondes

    let point: PointFolder
    let pointID: String
    let visit: VisitFolder
    let lens: Lens
    let camera: PhotoCamera
    /// Caméra ARKit, en mode « ×1 + AR » : elle donne en plus la position de l'objectif.
    let tracker: ARCameraController?
    private let motion = MotionTracker()
    private let aiming = Aiming()

    @Published private(set) var phase: Phase = .framing
    @Published private(set) var rotation: simd_double3x3?
    @Published private(set) var targets: [Target] = []
    @Published private(set) var done: [Int: PhotoEntry] = [:]
    @Published private(set) var isBusy = false
    @Published private(set) var isSteady = false
    /// Flèches visées depuis ce point.
    @Published private(set) var arrows: [VisitLink] = []
    /// Déplacement de l'objectif depuis sa place de départ (réglage « ×1 + AR »).
    @Published private(set) var drift = LensDrift()
    /// Distance entre le téléphone et l'axe de rotation (réglage « ×0,5 + capteurs »).
    @Published private(set) var axis = RotationAxis()
    let watchesAxis: Bool
    @Published var problem: String?

    private var file: CaptureFile
    private var order: [Int] = []
    private var steadySince: Date?
    /// Cap visé au verrouillage : centre du panorama et origine des flèches.
    private(set) var startYaw: Double?

    /// Un point se prend d'une traite : le cap de départ de Core Motion est arbitraire et change
    /// à chaque démarrage, donc des photos de deux séances ne partageraient pas le même repère.
    init(visit: VisitFolder, pointID: String, setup: CaptureSetup) {
        self.visit = visit
        self.pointID = pointID
        point = visit.point(pointID)
        lens = setup.lens
        if setup.tracksPosition {
            let tracker = ARCameraController()
            self.tracker = tracker
            camera = tracker
        } else {
            tracker = nil
            camera = CameraController()
        }
        file = CaptureFile(
            app: PointStore.appVersion, device: PointStore.deviceModel, started: Date(), lens: lens
        )
        watchesAxis = setup.watchesRotationAxis
        file.tracking = setup.tracksPosition ? "arkit" : setup.watchesRotationAxis ? "capteurs" : nil
        tracker?.onPosition = { [weak self] position in
            guard let self else { return }
            let wasTooFar = drift.isTooFar
            drift.update(position, started: phase == .shooting)
            if drift.isTooFar, !wasTooFar {
                UINotificationFeedbackGenerator().notificationOccurred(.warning)
            }
        }
        if watchesAxis {
            motion.onSample = { [weak self] time, rate, acceleration in
                guard let self, phase == .shooting else { return }
                let wasTooFar = axis.isTooFar
                axis.add(time: time, rotationRate: rate, acceleration: acceleration)
                if axis.isTooFar, !wasTooFar {
                    UINotificationFeedbackGenerator().notificationOccurred(.warning)
                }
            }
        }
    }

    /// Objectif hors de sa place (« ×1 + AR ») ou rotation autour du corps (« ×0,5 + capteurs ») :
    /// les photos sont suspendues.
    var parallaxAlert: Bool { drift.isTooFar || axis.isTooFar }

    var mandatoryLeft: Int {
        targets.filter { !$0.row.isOptional && done[$0.id] == nil }.count
    }

    /// Prochaine cible conseillée : la première qui reste, dans l'ordre de la fiche.
    var suggested: Target? { targets.first { done[$0.id] == nil } }

    func start() {
        camera.start(lens: lens)
        guard motion.isAvailable else {
            problem = "Ce téléphone ne donne pas son orientation. Le simulateur n'en a pas."
            return
        }
        motion.start { [weak self] rotation, speed in
            self?.update(rotation: rotation, speed: speed)
        }
    }

    func stop() {
        motion.stop()
        camera.stop()
        // visite.json ne contient que les points pris : il change avec la première photo.
        saveVisit { _ in }
    }

    /// Verrouille l'exposition et place les cibles : la première face au téléphone.
    func begin() {
        guard let rotation, phase == .framing else { return }
        let startYaw = Orientation.yaw(rotation)
        camera.lock { [weak self] exposure in
            guard let self else { return }
            file.exposure = exposure
            file.startYaw = startYaw
            self.startYaw = startYaw
            drift.start()
            axis.reset()
            targets = Plan.targets(startYaw: startYaw, lens: lens)
            phase = .shooting
        }
    }

    /// Retire la dernière photo prise, pour la refaire.
    func undoLast() {
        guard let id = order.popLast(), let entry = done.removeValue(forKey: id) else { return }
        try? FileManager.default.removeItem(at: point.photos.appendingPathComponent(entry.file))
        file.photos.removeAll { $0.file == entry.file }
        save()
    }

    /// Direction visée en ce moment, en angle et hauteur de flèche.
    func currentAim() -> (angle: Double, pitch: Double)? {
        guard let rotation, let startYaw else { return nil }
        return (
            ArrowAim.angle(yaw: Orientation.yaw(rotation), startYaw: startYaw),
            ArrowAim.pitch(Orientation.pitch(rotation))
        )
    }

    /// Enregistre une flèche vers un point de la visite, pris ou annoncé.
    func addArrow(to target: String, angle: Double, pitch: Double) {
        saveVisit { $0.setLink(from: self.pointID, to: target, angle: angle, pitch: pitch) }
    }

    /// Enregistre une flèche vers une pièce pas encore prise, qui devient un point annoncé.
    func addArrow(toNewRoom name: String, angle: Double, pitch: Double) {
        saveVisit { file in
            let target = file.addPoint(name: name)
            file.setLink(from: self.pointID, to: target, angle: angle, pitch: pitch)
        }
    }

    func removeArrow(to target: String) {
        saveVisit { $0.links.removeAll { $0.from == self.pointID && $0.to == target } }
    }

    private func saveVisit(_ change: (inout VisitFile) -> Void) {
        do {
            try visit.update(change)
            arrows = visit.load().links(from: pointID)
        } catch {
            problem = "Impossible d'enregistrer la visite : \(error.localizedDescription)"
        }
    }

    private func update(rotation: simd_double3x3, speed: Double) {
        self.rotation = rotation
        if speed > Self.steadySpeed {
            steadySince = nil
        } else if steadySince == nil {
            steadySince = Date()
        }
        isSteady = steadySince.map { Date().timeIntervalSince($0) >= Self.steadyDelay } ?? false
        // Objectif trop loin de sa place : pas de photo tant qu'il n'y est pas revenu.
        guard phase == .shooting, !isBusy, isSteady, !parallaxAlert,
              let (target, _) = aiming.nearest(targets, done: Set(done.keys), rotation: rotation),
              aiming.isAligned(target, rotation: rotation)
        else { return }
        shoot(target, rotation: rotation)
    }

    private func shoot(_ target: Target, rotation: simd_double3x3) {
        isBusy = true
        let time = Date()
        camera.capture { [weak self] result in
            guard let self else { return }
            defer {
                isBusy = false
                steadySince = nil
            }
            switch result {
            case .failure(let error):
                problem = "La photo a échoué : \(error.localizedDescription)"
            case .success(let data):
                record(data, target: target, rotation: rotation, time: time)
            }
        }
    }

    private func record(_ data: Data, target: Target, rotation: simd_double3x3, time: Date) {
        let name = nextFileName()
        do {
            try data.write(to: point.photos.appendingPathComponent(name), options: .atomic)
        } catch {
            problem = "Impossible d'enregistrer la photo : \(error.localizedDescription)"
            return
        }
        let entry = PhotoEntry(
            file: name, row: target.row, number: target.number,
            yaw: Orientation.yaw(rotation), pitch: Orientation.pitch(rotation),
            rotation: Orientation.rows(rotation), time: time,
            lensOffset: drift.displacement(tracker?.position).map { d in
                [d.x, d.y, d.z].map { ($0 * 1000).rounded() / 1000 }
            },
            axisDistance: watchesAxis ? axis.distance.map { ($0 * 1000).rounded() / 1000 } : nil
        )
        done[target.id] = entry
        order.append(target.id)
        file.photos.append(entry)
        save()
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
    }

    /// IMG_0001.jpg, IMG_0002.jpg… sans jamais reprendre un nom existant.
    private func nextFileName() -> String {
        let existing = (try? FileManager.default.contentsOfDirectory(atPath: point.photos.path)) ?? []
        let numbers = existing.compactMap { Int($0.dropFirst(4).prefix(4)) }
        return String(format: "IMG_%04d.jpg", (numbers.max() ?? 0) + 1)
    }

    /// capture.json est réécrit après chaque photo : rien n'est perdu si l'app est fermée.
    private func save() {
        do {
            try PointStore.save(file, in: point)
        } catch {
            problem = "Impossible d'enregistrer capture.json : \(error.localizedDescription)"
        }
    }
}
