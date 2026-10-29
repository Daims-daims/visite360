// App de capture guidée d'une visite (étapes 5, 6 et 13, D25, D26, D39).

import SwiftUI

@main
struct Visite360CaptureApp: App {
    // Reçoit d'iOS la fin des envois au serveur faits en arrière-plan (étape 13).
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var delegate

    var body: some Scene {
        WindowGroup {
            VisitsView()
        }
    }
}
