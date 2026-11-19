import SwiftUI
import PhotosUI
import DirectorKit

/// The Photography Director: pick a place photo (and inspiration photos), choose a style, and watch
/// shots stream in from the online engine or the phone. Server details live under Advanced.
struct DirectorView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.guidanceTheme) private var theme
    @StateObject private var model = DirectorModel()

    @AppStorage(DirectorDefaults.serverURL) private var serverURL = ""
    @AppStorage(DirectorDefaults.preference) private var preferenceRaw = UserEnginePreference.automatic.rawValue
    @AppStorage(DirectorDefaults.priority) private var priorityRaw = DirectorPriority.bestResults.rawValue
    @State private var apiKey = DirectorKeychain.read() ?? ""
    @State private var advancedOpen = false

    @State private var mode: DirectorMode = .scene
    @State private var style: DirectorStyle = .relaxedCandid
    @State private var brief = ""
    @State private var targetItem: PhotosPickerItem?
    @State private var targetImage: UIImage?
    @State private var inspirationItems: [PhotosPickerItem] = []
    @State private var inspirationImages: [UIImage] = []

    private var accent: Color { theme.hint ?? theme.accent }

    private var canRun: Bool {
        guard targetImage != nil, model.phase != .running else { return false }
        return mode != .inspiration || (3...5).contains(inspirationImages.count)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                header
                modePicker
                photoCard
                if mode == .scene { styleChips }
                if mode == .inspiration { inspirationPicker }
                noteField
                runButton
                results
                advanced
            }.padding(20)
        }
        .background(theme.body.ignoresSafeArea())
        .foregroundStyle(theme.silver).tint(accent)
        .fontDesign(theme.cueDesign)
        .preferredColorScheme(.dark)
        .onChange(of: targetItem) { _, item in load(item) { targetImage = $0 } }
        .onChange(of: inspirationItems) { _, items in
            Task {
                var images: [UIImage] = []
                for item in items { if let d = try? await item.loadTransferable(type: Data.self), let i = UIImage(data: d) { images.append(i) } }
                inspirationImages = images
            }
        }
        // Inspiration mode: let the server read the photos while the rest is being chosen.
        .onChange(of: targetImage) { _, _ in inputsChanged() }
        .onChange(of: inspirationImages) { _, _ in inputsChanged() }
        .onChange(of: mode) { _, _ in inputsChanged() }
        .onDisappear { model.inputsChanged(mode: mode, target: nil, inspiration: []) }
    }

    private func inputsChanged() {
        model.inputsChanged(mode: mode, target: targetImage, inspiration: inspirationImages)
    }

    // MARK: input

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Plan your shots").font(.title2.weight(.semibold))
                Text("Add a photo of the place and we'll suggest where to stand and how to pose.")
                    .font(.subheadline).foregroundStyle(.white.opacity(0.65))
            }
            Spacer(minLength: 12)
            Button { model.cancel(); dismiss() } label: {
                Image(systemName: "xmark").font(.system(size: 15, weight: .semibold))
                    .frame(width: 36, height: 36).background(.white.opacity(0.12), in: Circle())
            }.accessibilityLabel("Close").accessibilityIdentifier("director-close")
        }
    }

    private var modePicker: some View {
        Picker("Mode", selection: $mode) {
            Text("Portrait").tag(DirectorMode.scene)
            Text("Scenery").tag(DirectorMode.scenery)
            Text("Inspiration").tag(DirectorMode.inspiration)
        }.pickerStyle(.segmented).accessibilityIdentifier("director-mode")
    }

    private var photoCard: some View {
        PhotosPicker(selection: $targetItem, matching: .images) {
            ZStack(alignment: .bottomTrailing) {
                if let targetImage {
                    Image(uiImage: targetImage).resizable().scaledToFill()
                        .frame(maxWidth: .infinity).frame(height: 190).clipped()
                    Label("Change", systemImage: "photo").font(.footnote.weight(.semibold))
                        .padding(.horizontal, 12).padding(.vertical, 7)
                        .background(.black.opacity(0.6), in: Capsule()).padding(10)
                } else {
                    VStack(spacing: 8) {
                        Image(systemName: "photo.badge.plus").font(.system(size: 28)).foregroundStyle(accent)
                        Text("Choose the place photo").font(.headline)
                        Text("Where you'll take the picture").font(.footnote).foregroundStyle(.white.opacity(0.6))
                    }.frame(maxWidth: .infinity).frame(height: 150)
                }
            }
            .background(theme.panel)
            .clipShape(RoundedRectangle(cornerRadius: 18))
            .overlay(RoundedRectangle(cornerRadius: 18)
                .stroke(.white.opacity(0.12), style: StrokeStyle(lineWidth: 1, dash: targetImage == nil ? [6, 5] : [])))
        }.buttonStyle(.plain).accessibilityIdentifier("director-photo")
    }

    private var styleChips: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Style").font(.footnote.weight(.semibold)).foregroundStyle(.white.opacity(0.55))
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(DirectorStyle.allCases, id: \.self) { s in
                        Button { style = s } label: {
                            Text(s.label).font(.subheadline.weight(.medium)).padding(.horizontal, 14).padding(.vertical, 9)
                                .background(style == s ? accent : theme.panel, in: Capsule())
                                .foregroundStyle(style == s ? Color.black : theme.silver)
                        }.buttonStyle(.plain)
                    }
                }
            }
        }
    }

    private var inspirationPicker: some View {
        VStack(alignment: .leading, spacing: 10) {
            PhotosPicker(selection: $inspirationItems, maxSelectionCount: 5, matching: .images) {
                Label("Choose 3 to 5 inspiration photos (\(inspirationImages.count) picked)", systemImage: "photo.stack")
                    .font(.subheadline.weight(.medium)).frame(maxWidth: .infinity, alignment: .leading)
                    .padding(14).background(theme.panel, in: RoundedRectangle(cornerRadius: 14))
            }.buttonStyle(.plain)
            if !inspirationImages.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack { ForEach(inspirationImages.indices, id: \.self) { i in
                        Image(uiImage: inspirationImages[i]).resizable().scaledToFill().frame(width: 72, height: 72)
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                    } }
                }
            }
        }
    }

    private var noteField: some View {
        TextField(mode == .scene ? "Optional note, e.g. she prefers seated poses" :
                  mode == .scenery ? "Optional note, e.g. calm and minimal" : "Optional note",
                  text: $brief)
            .padding(14).background(theme.panel, in: RoundedRectangle(cornerRadius: 14))
    }

    private var runButton: some View {
        VStack(spacing: 8) {
            Button { run() } label: {
                HStack(spacing: 8) {
                    if model.phase == .running { ProgressView().tint(.black) }
                    Text(model.phase == .running ? model.stageText : "Plan my shots").font(.headline)
                }.frame(maxWidth: .infinity, minHeight: 50)
                    .background(accent.opacity(canRun ? 1 : 0.35), in: RoundedRectangle(cornerRadius: 16))
                    .foregroundStyle(Color.black)
            }.buttonStyle(.plain).disabled(!canRun).accessibilityIdentifier("director-run")
            if mode == .inspiration && model.phase != .running && model.prepStatus != .idle {
                Label(model.prepStatus == .working ? "Reading your photos ahead…" : "Photos read ahead: planning will be quicker",
                      systemImage: model.prepStatus == .working ? "hourglass" : "bolt.fill")
                    .font(.footnote).foregroundStyle(.white.opacity(0.6))
                    .accessibilityIdentifier("director-prep-status")
            }
            if model.phase == .running {
                Button("Cancel", role: .cancel) { model.cancel() }.font(.subheadline)
            }
        }
    }

    // MARK: results

    @ViewBuilder private var results: some View {
        if let notice = model.notice {
            Label(notice, systemImage: "arrow.triangle.2.circlepath").font(.footnote)
                .padding(12).frame(maxWidth: .infinity, alignment: .leading)
                .background(theme.panel, in: RoundedRectangle(cornerRadius: 12))
        }
        if case .failed(let message) = model.phase {
            Label(message, systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
                .padding(12).frame(maxWidth: .infinity, alignment: .leading)
                .background(theme.panel, in: RoundedRectangle(cornerRadius: 12))
        }
        if !model.shots.isEmpty {
            HStack {
                Text("Your shots").font(.title3.weight(.semibold))
                Spacer()
                if let e = model.engineUsed {
                    Text(e == .online ? "Online" : "On this phone").font(.caption.weight(.medium))
                        .padding(.horizontal, 10).padding(.vertical, 4).background(.white.opacity(0.12), in: Capsule())
                }
            }
            ForEach(Array(model.shots.enumerated()), id: \.offset) { i, shot in
                ShotCard(index: i + 1, shot: shot, kept: model.deck.isKept(shot),
                         rewriting: model.deck.pending.contains(i),
                         onKeep: { model.toggleKeep(shot) },
                         onUse: { model.markUsed(); PinnedShotStore.shared.pin(shot); model.cancel(); dismiss() })
            }
            Button { model.refresh() } label: {
                Label(refreshTitle, systemImage: "arrow.clockwise").font(.subheadline.weight(.medium))
                    .frame(maxWidth: .infinity, minHeight: 44)
                    .background(theme.panel, in: RoundedRectangle(cornerRadius: 14))
            }.buttonStyle(.plain).disabled(!model.deck.canRefresh || model.phase == .running)
                .accessibilityIdentifier("director-refresh")
            Text("Star the shots you like, then refresh to replace the rest.")
                .font(.footnote).foregroundStyle(.white.opacity(0.55))
        }
    }

    private var refreshTitle: String {
        let kept = model.deck.keptCount, total = model.shots.count
        if model.phase == .running && model.deck.isRefreshing { return "Rewriting…" }
        if kept == total { return "All shots kept" }
        return kept == 0 ? "Refresh all shots" : "Refresh the other \(total - kept)"
    }

    // MARK: advanced

    private var advanced: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button { withAnimation(.easeOut(duration: 0.15)) { advancedOpen.toggle() } } label: {
                HStack {
                    Text("Advanced").font(.headline)
                    Spacer()
                    Image(systemName: advancedOpen ? "chevron.up" : "chevron.down").font(.footnote.weight(.semibold))
                }.frame(minHeight: 44).contentShape(Rectangle())
            }.buttonStyle(.plain).accessibilityIdentifier("director-advanced")
            if advancedOpen {
                VStack(alignment: .leading, spacing: 14) {
                    Text("Quality").font(.footnote.weight(.semibold)).foregroundStyle(.white.opacity(0.55))
                    Picker("Quality", selection: $priorityRaw) {
                        Text("Best results").tag(DirectorPriority.bestResults.rawValue)
                        Text("Balanced").tag(DirectorPriority.balanced.rawValue)
                        Text("Fastest").tag(DirectorPriority.fastest.rawValue)
                    }.pickerStyle(.segmented).accessibilityIdentifier("director-priority")
                    Text(priorityNote).font(.footnote).foregroundStyle(.white.opacity(0.55))

                    Text("Director server").font(.footnote.weight(.semibold)).foregroundStyle(.white.opacity(0.55)).padding(.top, 6)
                    TextField("Server address, e.g. 192.168.1.20:8787", text: $serverURL)
                        .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                        .padding(14).background(theme.panel, in: RoundedRectangle(cornerRadius: 12))
                        .accessibilityIdentifier("director-server")
                    SecureField("Client key from `photo-ai server keygen`", text: $apiKey)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                        .onChange(of: apiKey) { _, v in DirectorKeychain.write(v) }
                        .padding(14).background(theme.panel, in: RoundedRectangle(cornerRadius: 12))
                        .accessibilityIdentifier("director-key")
                    Picker("When online", selection: $preferenceRaw) {
                        Text("Send photos").tag(UserEnginePreference.automatic.rawValue)
                        Text("Send text only").tag(UserEnginePreference.textOnly.rawValue)
                        Text("Stay offline").tag(UserEnginePreference.offlineOnly.rawValue)
                    }
                    Text("The key is stored in the iOS Keychain. With no server set, the on-device director is used. Text-only needs a server that supports it; for now it falls back to the phone.")
                        .font(.footnote).foregroundStyle(.white.opacity(0.55))
                    runStats
                }.padding(.bottom, 8)
            }
        }
    }

    private var priorityNote: String {
        switch DirectorPriority(rawValue: priorityRaw) ?? .bestResults {
        case .bestResults: return "Waits for the online model, which writes the best shots, before falling back to the phone."
        case .balanced: return "Waits a little for the online model, then uses the phone."
        case .fastest: return "Switches to the phone quickly. Shots are usually less detailed."
        }
    }

    /// How each engine has done on this phone: speed, and how often people kept or used what it wrote.
    @ViewBuilder private var runStats: some View {
        let stats = RunLog.summarize(RunLogStore.load())
        if !stats.isEmpty {
            VStack(alignment: .leading, spacing: 4) {
                Text("Your results so far").font(.footnote.weight(.semibold)).foregroundStyle(.white.opacity(0.55))
                ForEach(stats, id: \.engine) { s in
                    Text("\(s.engine == .online ? "Online" : "On this phone"): \(s.runs) runs, first shot in \(Int((s.medianFirstShotSeconds ?? 0).rounded())) s, done in \(Int(s.medianTotalSeconds.rounded())) s. You starred \(Int((s.keepRate * 100).rounded()))% of shots and pinned one in \(Int((s.useRate * 100).rounded()))% of runs.")
                        .font(.footnote).foregroundStyle(.white.opacity(0.7))
                }
            }.padding(.top, 6)
        }
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
    @Environment(\.guidanceTheme) private var theme
    let index: Int
    let shot: Shot
    let kept: Bool
    let rewriting: Bool
    let onKeep: () -> Void
    let onUse: () -> Void
    @State private var open = false

    private var accent: Color { theme.hint ?? theme.accent }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text("\(index)").font(.caption.weight(.bold)).foregroundStyle(.black)
                    .frame(width: 24, height: 24).background(accent, in: Circle())
                Text(shot.title).font(.headline).fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 8)
                Button(action: onKeep) {
                    Image(systemName: kept ? "star.fill" : "star").font(.title3).foregroundStyle(kept ? .yellow : .white.opacity(0.5))
                        .frame(width: 36, height: 36)
                }.buttonStyle(.plain).accessibilityLabel(kept ? "Unkeep this shot" : "Keep this shot")
                    .accessibilityIdentifier("director-keep-\(index)")
            }
            if !shot.sceneReading.isEmpty { Text(shot.sceneReading).font(.footnote).foregroundStyle(.white.opacity(0.65)) }

            group("Camera", symbol: "camera", rows: [("Stand", shot.cameraPosition), ("Height", shot.cameraHeight), ("Angle", shot.cameraAngle)])
            if open {
                group("Framing", symbol: "viewfinder", rows: [("Subject", shot.subjectPosition), ("Framing", shot.distanceAndFraming), ("Lens", shot.zoomOrLens), ("Light", shot.lightingTip)])
                group("Pose", symbol: "figure.stand", rows: [("Pose", shot.bodyPose), ("Head", shot.headDirection), ("Gaze", shot.gaze), ("Expression", shot.expressionCue)])
                if !shot.needsOnSiteCheck.isEmpty {
                    group("Check on site", symbol: "exclamationmark.circle", rows: [("", shot.needsOnSiteCheck.joined(separator: "; "))])
                }
            }
            Button { withAnimation(.easeOut(duration: 0.15)) { open.toggle() } } label: {
                HStack(spacing: 4) {
                    Text(open ? "Show less" : "Show all details")
                    Image(systemName: open ? "chevron.up" : "chevron.down").font(.caption2.weight(.semibold))
                }.font(.footnote.weight(.semibold)).foregroundStyle(accent).frame(minHeight: 32)
            }.buttonStyle(.plain)

            Button(action: onUse) {
                Text("Use this shot on the camera").font(.subheadline.weight(.semibold))
                    .frame(maxWidth: .infinity, minHeight: 46)
                    .background(accent, in: RoundedRectangle(cornerRadius: 14)).foregroundStyle(Color.black)
            }.buttonStyle(.plain).accessibilityIdentifier("director-use-shot-\(index)")
        }
        .padding(16)
        .background(theme.panel, in: RoundedRectangle(cornerRadius: theme.style == .soft ? 22 : 16))
        .opacity(rewriting ? 0.35 : 1)
        .overlay { if rewriting { ProgressView("Rewriting…") } }
        .animation(.easeOut(duration: 0.2), value: rewriting)
    }

    @ViewBuilder private func group(_ title: String, symbol: String, rows: [(String, String)]) -> some View {
        let shown = rows.filter { !$0.1.isEmpty }
        if !shown.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Label(title, systemImage: symbol).font(.caption.weight(.semibold)).foregroundStyle(accent)
                ForEach(Array(shown.enumerated()), id: \.offset) { _, r in
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        if !r.0.isEmpty {
                            Text(r.0).font(.caption).foregroundStyle(.white.opacity(0.5)).frame(width: 74, alignment: .leading)
                        }
                        Text(r.1).font(.subheadline).fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
            .padding(12).frame(maxWidth: .infinity, alignment: .leading)
            .background(.white.opacity(0.05), in: RoundedRectangle(cornerRadius: 12))
        }
    }
}
