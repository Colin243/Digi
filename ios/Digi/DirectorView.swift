import ImageIO
import SwiftUI
import PhotosUI
import DirectorKit

/// The Photography Director: pick a place photo (and inspiration photos), choose a style, and watch
/// shots stream in from the online engine or the phone. Server details live under Advanced.
struct DirectorView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.guidanceTheme) private var theme
    /// One Director for the whole app run: closing the sheet (on purpose or by accident) keeps the photos, the note,
    /// the shots on screen and any plan still streaming, so reopening shows them without another pass.
    @ObservedObject private var model = DirectorModel.shared

    @AppStorage(DirectorDefaults.serverURL) private var serverURL = ""
    @AppStorage(DirectorDefaults.preference) private var preferenceRaw = UserEnginePreference.automatic.rawValue
    @AppStorage(DirectorDefaults.priority) private var priorityRaw = DirectorPriority.bestResults.rawValue
    @State private var apiKey = DirectorKeychain.read() ?? ""
    @State private var advancedOpen = false
    @State private var introNote = false

    private var mode: DirectorMode { get { model.mode } nonmutating set { model.mode = newValue } }
    private var style: DirectorStyle { get { model.style } nonmutating set { model.style = newValue } }
    private var brief: String { get { model.brief } nonmutating set { model.brief = newValue } }
    @State private var targetItem: PhotosPickerItem?
    private var targetImage: UIImage? { get { model.targetImage } nonmutating set { model.targetImage = newValue } }
    @State private var inspirationItems: [PhotosPickerItem] = []
    private var inspirationImages: [UIImage] { get { model.inspirationImages } nonmutating set { model.inspirationImages = newValue } }
    /// Photos still loading from the library (shown at once, so a pick never looks ignored), and a counter so a newer
    /// pick replaces an older one that is still loading.
    @State private var loadingTarget = false
    @State private var loadingInspiration = 0
    @State private var inspirationLoad = 0

    private var accent: Color { theme.hint ?? theme.accent }

    private var canRun: Bool {
        guard targetImage != nil, model.phase != .running else { return false }
        return mode != .inspiration || (loadingInspiration == 0 && (3...5).contains(inspirationImages.count))
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
        .onChange(of: targetItem) { _, item in
            guard let item else { return }
            loadingTarget = true
            Task {
                if let image = await Self.loadPhoto(item) { targetImage = image }
                if targetItem == item { loadingTarget = false }
            }
        }
        .onChange(of: inspirationItems) { _, items in
            inspirationLoad += 1
            let load = inspirationLoad
            loadingInspiration = items.count
            Task {
                // Each photo is shown, and sent to be read ahead, the moment it has loaded, in the order picked.
                var slots = [UIImage?](repeating: nil, count: items.count)
                await withTaskGroup(of: (Int, UIImage?).self) { group in
                    for (i, item) in items.enumerated() { group.addTask { (i, await Self.loadPhoto(item)) } }
                    for await (i, image) in group {
                        slots[i] = image
                        guard load == inspirationLoad else { continue }  // a newer pick is loading
                        loadingInspiration -= 1
                        inspirationImages = slots.compactMap { $0 }
                    }
                }
                if load == inspirationLoad { loadingInspiration = 0; inputsChanged() }
            }
        }
        // Inspiration mode: let the server read the photos while the rest is being chosen.
        .onChange(of: targetImage) { _, _ in inputsChanged() }
        .onChange(of: inspirationImages) { _, _ in inputsChanged() }
        .onChange(of: mode) { _, _ in inputsChanged() }
        .onAppear { inputsChanged() }  // resume reading ahead for photos kept from last time
        // A new server address or key: read the same photos again on that server (after typing pauses).
        .onChange(of: serverURL) { _, _ in inputsChanged(after: 1) }
        .onChange(of: apiKey) { _, _ in inputsChanged(after: 1) }
        .onChange(of: preferenceRaw) { _, _ in inputsChanged() }
    }

    private func inputsChanged(after delay: Double = 0) {
        model.inputsChanged(mode: mode, target: targetImage, inspiration: inspirationImages,
                            inspirationComplete: loadingInspiration == 0, after: delay)
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
            Button { dismiss() } label: {  // closing keeps everything; a plan in progress keeps streaming
                Image(systemName: "xmark").font(.system(size: 16, weight: .semibold))
                    .frame(width: 44, height: 44).background(.white.opacity(0.12), in: Circle()).contentShape(Circle())
            }.accessibilityLabel("Close").accessibilityIdentifier("director-close")
        }
    }

    private var modePicker: some View {
        // Three full-size buttons rather than a segmented control: its thin segments were easy to miss on the phone.
        HStack(spacing: 8) {
            ForEach([(DirectorMode.scene, "Portrait"), (.scenery, "Scenery"), (.inspiration, "Inspiration")], id: \.0) { m, title in
                Button { mode = m } label: {
                    Text(title).font(.subheadline.weight(.semibold)).lineLimit(1).minimumScaleFactor(0.8)
                        .frame(maxWidth: .infinity, minHeight: 48)
                        .background(mode == m ? accent : theme.panel, in: RoundedRectangle(cornerRadius: 14))
                        .foregroundStyle(mode == m ? Color.black : theme.silver)
                        .contentShape(RoundedRectangle(cornerRadius: 14))
                }.buttonStyle(.plain)
                    .accessibilityAddTraits(mode == m ? .isSelected : [])
                    .accessibilityIdentifier("director-mode-\(m.rawValue)")
            }
        }.accessibilityIdentifier("director-mode")
    }

    private var photoCard: some View {
        PhotosPicker(selection: $targetItem, matching: .images) {
            ZStack(alignment: .bottomTrailing) {
                if loadingTarget && targetImage == nil {
                    VStack(spacing: 8) { ProgressView(); Text("Loading photo…").font(.footnote) }
                        .frame(maxWidth: .infinity).frame(height: 150)
                } else if let targetImage {
                    // A fixed-height clear box with the photo drawn over it: a wide photo cannot widen the whole sheet.
                    Color.clear.frame(maxWidth: .infinity).frame(height: 190)
                        .overlay { Image(uiImage: targetImage).resizable().scaledToFill() }
                        .clipped()
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
            .contentShape(RoundedRectangle(cornerRadius: 18))
        }.buttonStyle(.plain).accessibilityIdentifier("director-photo")
    }

    private var styleChips: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Style").font(.footnote.weight(.semibold)).foregroundStyle(.white.opacity(0.55))
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(DirectorStyle.allCases, id: \.self) { s in
                        Button { style = s } label: {
                            Text(s.label).font(.subheadline.weight(.medium)).padding(.horizontal, 16)
                                .frame(minHeight: 44)
                                .background(style == s ? accent : theme.panel, in: Capsule()).contentShape(Capsule())
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
                Label(loadingInspiration > 0 ? "Loading \(loadingInspiration) photos…"
                                             : "Choose 3 to 5 inspiration photos (\(inspirationImages.count) picked)",
                      systemImage: loadingInspiration > 0 ? "hourglass" : "photo.stack")
                    .font(.subheadline.weight(.medium)).frame(maxWidth: .infinity, minHeight: 28, alignment: .leading)
                    .padding(14).background(theme.panel, in: RoundedRectangle(cornerRadius: 14))
                    .contentShape(RoundedRectangle(cornerRadius: 14))
            }.buttonStyle(.plain).accessibilityIdentifier("director-inspiration")
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
                  text: $model.brief)
            .padding(14).background(theme.panel, in: RoundedRectangle(cornerRadius: 14))
    }

    private var runButton: some View {
        VStack(spacing: 8) {
            Button { run() } label: {
                HStack(spacing: 8) {
                    if model.phase == .running { ProgressView().tint(.black) }
                    Text(model.phase == .running ? model.stageText : "Plan my shots").font(.headline)
                }.frame(maxWidth: .infinity, minHeight: 56)
                    .background(accent.opacity(canRun ? 1 : 0.35), in: RoundedRectangle(cornerRadius: 16))
                    .foregroundStyle(Color.black).contentShape(RoundedRectangle(cornerRadius: 16))
            }.buttonStyle(.plain).disabled(!canRun).accessibilityIdentifier("director-run")
            if mode == .inspiration && model.phase != .running && model.prepStatus != .idle {
                Label(model.prepStatus == .working ? "Reading your photos ahead…" : "Photos read ahead: planning will be quicker",
                      systemImage: model.prepStatus == .working ? "hourglass" : "bolt.fill")
                    .font(.footnote).foregroundStyle(.white.opacity(0.6))
                    .accessibilityIdentifier("director-prep-status")
            }
            if model.serverState == .unreachable && model.phase != .running {
                Label("Can't reach your Director server. Check the address in Settings and that your phone can reach it.",
                      systemImage: "wifi.exclamationmark")
                    .font(.footnote).foregroundStyle(.orange.opacity(0.9))
                    .accessibilityIdentifier("director-server-unreachable")
            }
            if model.phase == .running {
                Button(role: .cancel) { model.cancel() } label: {
                    Text("Cancel").font(.subheadline.weight(.medium)).frame(maxWidth: .infinity, minHeight: 44)
                        .background(theme.panel, in: RoundedRectangle(cornerRadius: 14)).contentShape(RoundedRectangle(cornerRadius: 14))
                }.buttonStyle(.plain).accessibilityIdentifier("director-cancel")
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
                    .frame(maxWidth: .infinity, minHeight: 48)
                    .background(theme.panel, in: RoundedRectangle(cornerRadius: 14)).contentShape(RoundedRectangle(cornerRadius: 14))
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
                    }.pickerStyle(.segmented).controlSize(.large).accessibilityIdentifier("director-priority")
                    Text(priorityNote).font(.footnote).foregroundStyle(.white.opacity(0.55))

                    Text("Director server").font(.footnote.weight(.semibold)).foregroundStyle(.white.opacity(0.55)).padding(.top, 6)
                    TextField("Server address, e.g. my-mac.tailnet.ts.net", text: $serverURL)
                        .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                        .padding(14).background(theme.panel, in: RoundedRectangle(cornerRadius: 12))
                        .accessibilityIdentifier("director-server")
                    if let address = ServerAddress.url(from: serverURL) {
                        if ServerAddress.isPlainHTTP(address) {
                            Text("Not encrypted: your key and photos can be read by others on this network. Use it only on a network you trust, or use an https address (for example through Tailscale).")
                                .font(.footnote).foregroundStyle(.orange.opacity(0.9))
                                .accessibilityIdentifier("director-server-plain-http")
                        }
                    } else if !serverURL.trimmingCharacters(in: .whitespaces).isEmpty {
                        Text("That address is not valid. Use a host name or address, with http:// or https:// if you like.")
                            .font(.footnote).foregroundStyle(.red.opacity(0.85))
                    }
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
                    Button {
                        OnboardingStore.reset()
                        introNote = true
                    } label: {
                        Text("Show the introduction again").font(.subheadline.weight(.medium)).frame(maxWidth: .infinity, minHeight: 44)
                            .background(theme.panel, in: RoundedRectangle(cornerRadius: 14))
                            .contentShape(RoundedRectangle(cornerRadius: 14))
                    }
                    .buttonStyle(.plain).accessibilityIdentifier("director-show-intro")
                    if introNote {
                        Text("The introduction will show the next time you open Digi.")
                            .font(.footnote).foregroundStyle(.white.opacity(0.55))
                    }
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

    /// Photos load side by side, already shrunk: decoding a full 48 MP library photo took seconds each, during which
    /// the screen still showed the old pick. The Director sends 1024 px anyway.
    static func loadPhotos(_ items: [PhotosPickerItem]) async -> [UIImage] {
        await withTaskGroup(of: (Int, UIImage?).self) { group in
            for (i, item) in items.enumerated() { group.addTask { (i, await loadPhoto(item)) } }
            var loaded: [(Int, UIImage)] = []
            for await (i, image) in group { if let image { loaded.append((i, image)) } }
            return loaded.sorted { $0.0 < $1.0 }.map(\.1)
        }
    }

    static func loadPhoto(_ item: PhotosPickerItem, maxPixels: Int = 1600) async -> UIImage? {
        guard let data = try? await item.loadTransferable(type: Data.self) else { return nil }
        guard let source = CGImageSourceCreateWithData(data as CFData, [kCGImageSourceShouldCache: false] as CFDictionary),
              let thumb = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                  kCGImageSourceCreateThumbnailFromImageAlways: true, kCGImageSourceCreateThumbnailWithTransform: true,
                  kCGImageSourceThumbnailMaxPixelSize: maxPixels] as CFDictionary)
        else { return UIImage(data: data) }
        return UIImage(cgImage: thumb)
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
                        .frame(width: 44, height: 44).contentShape(Rectangle())
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
                }.font(.footnote.weight(.semibold)).foregroundStyle(accent)
                    .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading).contentShape(Rectangle())
            }.buttonStyle(.plain)

            Button(action: onUse) {
                Text("Use this shot on the camera").font(.subheadline.weight(.semibold))
                    .frame(maxWidth: .infinity, minHeight: 50)
                    .background(accent, in: RoundedRectangle(cornerRadius: 14)).foregroundStyle(Color.black)
                    .contentShape(RoundedRectangle(cornerRadius: 14))
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
