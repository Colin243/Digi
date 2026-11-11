import SwiftUI

@main
struct IOSBenchApp: App {
    @StateObject private var runner = BenchRunner()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView(runner: runner)
        }
        .onChange(of: scenePhase) { _, phase in runner.scenePhaseChanged(phase) }
    }
}
