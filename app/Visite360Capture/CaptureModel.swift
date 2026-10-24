// Déroulement de la prise de vue d'un point : cadrage et verrouillage de l'exposition, puis
// déclenchement automatique quand le téléphone vise une cible et ne bouge plus.

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
    let lens: Lens
    let camera = CameraController()
    private let motion = MotionTracker()
    private let aiming = Aiming()

    @Published private(set) var phase: Phase = .framing
    @Published private(set) var rotation: simd_double3x3?
    @Published private(set) var targets: [Target] = []
    @Published private(set) var done: [Int: PhotoEntry] = [:]
    @Published private(set) var isBusy = false
    @Published private(set) var isSteady = false
    @Published var problem: String?

    private var file: CaptureFile
    private var order: [Int] = []
    private var steadySince: Date?

    /// Un point se prend d'une traite : le cap de départ de Core Motion est arbitraire et change
    /// à chaque démarrage, donc des photos de deux séances ne partageraient pas le même repère.
    init(point: PointFolder, lens: Lens) {
        self.point = point
        self.lens = lens
        file = CaptureFile(
            app: PointStore.appVersion, device: PointStore.deviceModel, started: Date(), lens: lens
        )
    }

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
    }

    /// Verrouille l'exposition et place les cibles : la première face au téléphone.
    func begin() {
        guard let rotation, phase == .framing else { return }
        let startYaw = Orientation.yaw(rotation)
        camera.lock { [weak self] exposure in
            guard let self else { return }
            file.exposure = exposure
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

    private func update(rotation: simd_double3x3, speed: Double) {
        self.rotation = rotation
        if speed > Self.steadySpeed {
            steadySince = nil
        } else if steadySince == nil {
            steadySince = Date()
        }
        isSteady = steadySince.map { Date().timeIntervalSince($0) >= Self.steadyDelay } ?? false
        guard phase == .shooting, !isBusy, isSteady,
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
            rotation: Orientation.rows(rotation), time: time
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
