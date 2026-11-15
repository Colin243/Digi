import SwiftUI
import PhotosUI
import DirectorKit

/// The Photography Director screen: pick a place photo (and optional inspiration photos), choose a
/// style, and watch shots stream in from the online engine or the phone.
struct DirectorView: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var model = DirectorModel()

    @AppStorage(DirectorDefaults.serverURL) private var serverURL = ""
    @AppStorage(DirectorDefaults.preference) private var preferenceRaw = UserEnginePreference.automatic.rawValue
    @State private var apiKey = DirectorKeychain.read() ?? ""

    @State private var mode: DirectorMode = .scene
    @State private var style: DirectorStyle = .relaxedCandid
    @State private var brief = ""
    @State private var targetItem: PhotosPickerItem?
    @State private var targetImage: UIImage?
    @State private var inspirationItems: [PhotosPickerItem] = []
    @State private var inspirationImages: [UIImage] = []

    private var canRun: Bool {
        guard targetImage != nil, model.phase != .running else { return false }
        return mode != .inspiration || (3...5).contains(inspirationImages.count)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("What to shoot") {
                    Picker("Mode", selection: $mode) {
                        Text("Portrait").tag(DirectorMode.scene)
                        Text("Scenery").tag(DirectorMode.scenery)
                        Text("Inspiration photos").tag(DirectorMode.inspiration)
                    }.pickerStyle(.segmented).accessibilityIdentifier("director-mode")

                    PhotosPicker(selection: $targetItem, matching: .images) {
                        Label(targetImage == nil ? "Choose the place photo" : "Change the place photo", systemImage: "photo")
                    }
                    if let targetImage { Image(uiImage: targetImage).resizable().scaledToFit().frame(maxHeight: 160).clipShape(RoundedRectangle(cornerRadius: 8)) }

                    if mode == .scene {
                        Picker("Style", selection: $style) {
                            ForEach(DirectorStyle.allCases, id: \.self) { Text($0.label).tag($0) }
                        }
                        TextField("Optional note, e.g. she prefers seated poses", text: $brief)
                    } else if mode == .scenery {
                        TextField("Optional note, e.g. calm and minimal", text: $brief)
                    } else {
                        PhotosPicker(selection: $inspirationItems, maxSelectionCount: 5, matching: .images) {
                            Label("Choose 3 to 5 inspiration photos (\(inspirationImages.count) picked)", systemImage: "photo.stack")
                        }
                        if !inspirationImages.isEmpty {
                            ScrollView(.horizontal) {
                                HStack { ForEach(inspirationImages.indices, id: \.self) { i in
                                    Image(uiImage: inspirationImages[i]).resizable().scaledToFill().frame(width: 72, height: 72).clipShape(RoundedRectangle(cornerRadius: 6))
                                } }
                            }
                        }
                    }
                    Button { run() } label: {
                        HStack { if model.phase == .running { ProgressView() }; Text(model.phase == .running ? model.stageText : "Plan my shots") }
                    }.disabled(!canRun).accessibilityIdentifier("director-run")
                    if model.phase == .running { Button("Cancel", role: .cancel) { model.cancel() } }
                }

                results

                Section {
                    TextField("Server address, e.g. 192.168.1.20:8787", text: $serverURL)
                        .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                        .accessibilityIdentifier("director-server")
                    SecureField("Client key from `photo-ai server keygen`", text: $apiKey)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                        .onChange(of: apiKey) { _, v in DirectorKeychain.write(v) }
                        .accessibilityIdentifier("director-key")
                    Picker("When online", selection: $preferenceRaw) {
                        Text("Send photos").tag(UserEnginePreference.automatic.rawValue)
                        Text("Send text only").tag(UserEnginePreference.textOnly.rawValue)
                        Text("Stay offline").tag(UserEnginePreference.offlineOnly.rawValue)
                    }
                } header: { Text("Director server") } footer: {
                    Text("The key is stored in the iOS Keychain. With no server set, the on-device director is used. Text-only needs a server that supports it; for now it falls back to the phone.")
                }
            }
            .navigationTitle("Director")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { model.cancel(); dismiss() } } }
            .onChange(of: targetItem) { _, item in load(item) { targetImage = $0 } }
            .onChange(of: inspirationItems) { _, items in
                Task {
                    var images: [UIImage] = []
                    for item in items { if let d = try? await item.loadTransferable(type: Data.self), let i = UIImage(data: d) { images.append(i) } }
                    inspirationImages = images
                }
            }
        }
        .preferredColorScheme(.dark)
    }

    @ViewBuilder private var results: some View {
        if let notice = model.notice { Section { Label(notice, systemImage: "arrow.triangle.2.circlepath").font(.footnote) } }
        if case .failed(let message) = model.phase {
            Section { Label(message, systemImage: "exclamationmark.triangle").foregroundStyle(.orange) }
        }
        if !model.shots.isEmpty {
            Section {
                ForEach(Array(model.shots.enumerated()), id: \.offset) { i, shot in
                    ShotCard(index: i + 1, shot: shot, kept: model.deck.isKept(shot),
                             rewriting: model.deck.pending.contains(i),
                             onKeep: { model.toggleKeep(shot) },
                             onUse: { PinnedShotStore.shared.pin(shot); model.cancel(); dismiss() })
                }
                Button { model.refresh() } label: {
                    Label(refreshTitle, systemImage: "arrow.clockwise")
                }.disabled(!model.deck.canRefresh || model.phase == .running)
                    .accessibilityIdentifier("director-refresh")
            } header: {
                Text(model.engineUsed == .online ? "Shots · online" : model.engineUsed == .offline ? "Shots · on this phone" : "Shots")
            } footer: {
                Text("Star the shots you like, then refresh to replace the rest.")
            }
        }
    }

    private var refreshTitle: String {
        let kept = model.deck.keptCount, total = model.shots.count
        if model.phase == .running && model.deck.isRefreshing { return "Rewriting…" }
        if kept == total { return "All shots kept" }
        return kept == 0 ? "Refresh all shots" : "Refresh the other \(total - kept)"
    }

    private func run() {
        model.run(mode: mode, style: style, brief: brief, target: targetImage, inspiration: inspirationImages)
    }

    private func load(_ item: PhotosPickerItem?, _ apply: @escaping (UIImage) -> Void) {
        guard let item else { return }
        Task { if let d = try? await item.loadTransferable(type: Data.self), let i = UIImage(data: d) { apply(i) } }
    }
}

private struct ShotCard: View {
    let index: Int
    let shot: Shot
    let kept: Bool
    let rewriting: Bool
    let onKeep: () -> Void
    let onUse: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline) {
                Text("\(index). \(shot.title)").font(.headline)
                Spacer()
                Button(action: onKeep) { Image(systemName: kept ? "star.fill" : "star").foregroundStyle(kept ? .yellow : .secondary) }
                    .buttonStyle(.borderless).accessibilityLabel(kept ? "Unkeep this shot" : "Keep this shot")
                    .accessibilityIdentifier("director-keep-\(index)")
            }
            if !shot.sceneReading.isEmpty { Text(shot.sceneReading).font(.footnote).foregroundStyle(.secondary) }
            row("Stand", shot.cameraPosition); row("Height", shot.cameraHeight); row("Angle", shot.cameraAngle)
            row("Subject", shot.subjectPosition); row("Framing", shot.distanceAndFraming); row("Light", shot.lightingTip)
            row("Pose", shot.bodyPose); row("Head", shot.headDirection); row("Gaze", shot.gaze); row("Expression", shot.expressionCue)
            if !shot.needsOnSiteCheck.isEmpty { row("Check on site", shot.needsOnSiteCheck.joined(separator: "; ")) }
            Button("Use this shot on the camera", action: onUse)
                .buttonStyle(.borderedProminent).padding(.top, 4).accessibilityIdentifier("director-use-shot-\(index)")
        }.padding(.vertical, 4)
            .opacity(rewriting ? 0.35 : 1)
            .overlay { if rewriting { ProgressView("Rewriting…") } }
            .animation(.easeOut(duration: 0.2), value: rewriting)
    }

    @ViewBuilder private func row(_ label: String, _ text: String) -> some View {
        if !text.isEmpty {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(label).font(.caption.weight(.semibold)).foregroundStyle(.secondary).frame(width: 78, alignment: .leading)
                Text(text).font(.subheadline)
            }
        }
    }
}
