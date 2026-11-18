import AVFoundation
import SwiftUI

struct ContentView: View {
    @ObservedObject var runner: BenchRunner
    @State private var preset: Preset = .standard
    @State private var repeats = Preset.standard.defaultRepeats
    @State private var cameraPauseResume = true
    @State private var reloadTest = true
    @State private var cooldown = 0.0
    @State private var compositionsMaxTokens = BenchRunner.defaultCompositionsMaxTokens

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    CameraPreview(session: runner.camera.session)
                        .frame(height: 140)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                    Text(runner.memoryLine).font(.caption.monospacedDigit())
                }

                Section("Run") {
                    Picker("Preset", selection: $preset) {
                        ForEach(Preset.allCases) { Text($0.rawValue.capitalized).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    .onChange(of: preset) { _, p in repeats = p.defaultRepeats }
                    Text(preset.blurb).font(.caption).foregroundStyle(.secondary)
                    Stepper("Repeats per size: \(repeats)", value: $repeats, in: 1...30)
                    Toggle("Pause camera around inference", isOn: $cameraPauseResume)
                    Toggle("Reload test at the end", isOn: $reloadTest)
                    Stepper("Cooldown between trials: \(Int(cooldown)) s", value: $cooldown, in: 0...120, step: 15)
                    Stepper(compositionsMaxTokens == 0 ? "Compositions max tokens: off (1600)"
                                : "Compositions max tokens: \(compositionsMaxTokens)",
                            value: $compositionsMaxTokens, in: 0...1600, step: 50)
                    if runner.running {
                        Button("Stop after current call", role: .destructive) { runner.stop() }
                    } else {
                        Button("Start benchmark") {
                            runner.start(preset: preset, repeats: repeats, cameraPauseResume: cameraPauseResume,
                                         reloadTest: reloadTest, cooldown: cooldown,
                                         compositionsMaxTokens: compositionsMaxTokens)
                        }
                        .bold()
                    }
                }

                Section("Status") {
                    Text(runner.status).font(.callout)
                    if let f = runner.fallback {
                        Label(f, systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(.orange)
                            .font(.callout)
                    }
                    ScrollViewReader { proxy in
                        ScrollView {
                            VStack(alignment: .leading, spacing: 2) {
                                ForEach(Array(runner.log.enumerated()), id: \.offset) { i, line in
                                    Text(line).font(.caption2.monospaced()).id(i)
                                }
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .frame(height: 220)
                        .onChange(of: runner.log.count) { _, n in proxy.scrollTo(n - 1, anchor: .bottom) }
                    }
                }

                Section("Results (tap to AirDrop)") {
                    if runner.results.isEmpty { Text("None yet").foregroundStyle(.secondary) }
                    ForEach(runner.results, id: \.self) { url in
                        ShareLink(item: url) {
                            Label(url.lastPathComponent, systemImage: "square.and.arrow.up").font(.caption)
                        }
                    }
                }
            }
            .navigationTitle("Digi Bench")
            .navigationBarTitleDisplayMode(.inline)
            .onAppear { runner.refreshResults() }
        }
    }
}

struct CameraPreview: UIViewRepresentable {
    let session: AVCaptureSession

    final class PreviewView: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
        var previewLayer: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }
    }

    func makeUIView(context: Context) -> PreviewView {
        let v = PreviewView()
        v.backgroundColor = .black
        v.previewLayer.session = session
        v.previewLayer.videoGravity = .resizeAspectFill
        return v
    }

    func updateUIView(_ uiView: PreviewView, context: Context) {}
}
