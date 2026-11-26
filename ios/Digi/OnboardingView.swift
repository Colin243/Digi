import SwiftUI
import DirectorKit

/// The first-run introduction: five screens designed in Figma ("Digi onboarding and privacy").
///
/// The wording on the privacy page has to match what the Director server really does (photos are deleted after each
/// request; short text notes about them stay in memory for a while). Change both together, and the privacy policy.
/// Colours and shapes come from the guidance theme, so the Soft and Minimal styles work too.
struct OnboardingView: View {
    @Environment(\.guidanceTheme) private var theme
    @State private var flow = OnboardingFlow()
    @AppStorage(DirectorDefaults.serverURL) private var serverURL = ""
    @State private var apiKey = DirectorKeychain.read() ?? ""
    /// Called when the person finishes, skips the last page or taps "Set up later".
    var onFinish: () -> Void

    private var accent: Color { theme.accent }
    private var hint: Color { theme.hint ?? theme.accent }

    var body: some View {
        VStack(spacing: 24) {
            header
            ScrollView {
                VStack(alignment: .leading, spacing: 20) { pageContent }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 4)
            }
            .scrollIndicators(.hidden)
            footer
        }
        .padding(.horizontal, 24).padding(.top, 20).padding(.bottom, 12)
        .background(theme.body.ignoresSafeArea())
        .foregroundStyle(theme.silver).tint(accent)
        .fontDesign(theme.cueDesign)
        .animation(.easeInOut(duration: 0.2), value: flow.page)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("onboarding-\(flow.page.rawValue)")
    }

    // MARK: header and footer

    private var header: some View {
        HStack {
            HStack(spacing: 6) {
                ForEach(0..<OnboardingFlow.pageCount, id: \.self) { i in
                    Capsule().fill(i == flow.index ? accent : theme.silver.opacity(0.25))
                        .frame(width: i == flow.index ? 22 : 8, height: 8)
                }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Step \(flow.index + 1) of \(OnboardingFlow.pageCount)")
            Spacer()
            if flow.canSkip {
                Button("Skip") { flow.skip() }
                    .font(.subheadline.weight(.medium)).foregroundStyle(accent)
                    .frame(minWidth: 44, minHeight: 44)
                    .accessibilityIdentifier("onboarding-skip")
            }
        }
        .frame(minHeight: 44)
    }

    private var footer: some View {
        VStack(spacing: 8) {
            Button { advance() } label: {
                Text(primaryTitle).font(.headline).frame(maxWidth: .infinity, minHeight: 54)
                    .background(accent.opacity(primaryEnabled ? 1 : 0.35), in: RoundedRectangle(cornerRadius: 16))
                    .contentShape(RoundedRectangle(cornerRadius: 16))
            }
            .buttonStyle(.plain).foregroundStyle(.black).disabled(!primaryEnabled)
            .accessibilityIdentifier("onboarding-primary")
            if flow.isLast {
                Button("Set up later") { onFinish() }
                    .font(.subheadline.weight(.medium)).foregroundStyle(accent)
                    .frame(maxWidth: .infinity, minHeight: 44)
                    .accessibilityIdentifier("onboarding-later")
            }
        }
    }

    private var primaryTitle: String {
        switch flow.page {
        case .welcome: return "Get started"
        case .privacy: return "I understand"
        case .connect: return "Save and start"
        default: return "Continue"
        }
    }

    /// The last page needs a valid address and a key before it can "Save and start"; "Set up later" is always there.
    private var primaryEnabled: Bool {
        !flow.isLast || (ServerAddress.url(from: serverURL) != nil && !apiKey.trimmingCharacters(in: .whitespaces).isEmpty)
    }

    private func advance() { if flow.next() { onFinish() } }

    // MARK: pages

    @ViewBuilder private var pageContent: some View {
        switch flow.page {
        case .welcome: welcome
        case .howItWorks: howItWorks
        case .privacy: privacy
        case .permissions: permissions
        case .connect: connect
        }
    }

    private var welcome: some View {
        Group {
            ViewfinderIllustration(theme: theme).frame(height: 300)
            title("Shoot like the photos you love")
            bodyText("Pick a photo you love and a photo of where you are. Digi plans three shots, then coaches you live while you take them.")
        }
    }

    private var howItWorks: some View {
        Group {
            title("How it works")
            row(badge: "1", title: "Choose photos you love", detail: "Three to five reference photos show Digi the look you want.")
            row(badge: "2", title: "Add a photo of your place", detail: "A photo of where you will shoot, so the plan fits the room you have.")
            row(badge: "3", title: "Pick a shot and follow the cues", detail: "Digi tells you where to stand, how high to hold the phone and when to step closer.")
        }
    }

    private var privacy: some View {
        Group {
            title("Your photos and privacy")
            row(badge: nil, title: "Photos go to the Director server", detail: "Only to plan your shots: your reference photos and your place photo.")
            row(badge: nil, title: "Deleted right after reading", detail: "The server may keep short text notes about them in memory for a little while to speed up the next plan.")
            row(badge: nil, title: "Live coaching stays on your phone", detail: "Camera frames are checked in memory and are never stored or sent.")
            row(badge: nil, title: "Your key is kept in the Keychain", detail: "You can clear the server address and key in Settings at any time.")
        }
    }

    private var permissions: some View {
        Group {
            title("Camera and Photos")
            bodyText("iPhone will ask for these. Here is what each one is for.")
            card("Camera", "Shows the live view, coaches you while you shoot and takes your photos.", tag: "Needed to take photos")
            card("Photos", "Digi can add the photos you take to your library. It does not read your library: you choose each reference photo yourself.", tag: "Add only")
            card("Local network", "Only if your Director server is on your Wi-Fi, iPhone asks once to let Digi find it.", tag: "Only if needed")
        }
    }

    private var connect: some View {
        Group {
            title("Connect to a Director server")
            bodyText("Digi plans your shots on a Director server. Enter the address and the access key you were given.")
            field("Server address") {
                TextField("Server address", text: $serverURL, prompt: Text("my-mac.tailnet.ts.net").foregroundStyle(theme.silver.opacity(0.4)))
                    .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                    .accessibilityIdentifier("onboarding-server")
            }
            field("Access key") {
                SecureField("Access key", text: $apiKey, prompt: Text("Key from the person running the server").foregroundStyle(theme.silver.opacity(0.4)))
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                    .onChange(of: apiKey) { _, v in DirectorKeychain.write(v) }
                    .accessibilityIdentifier("onboarding-key")
            }
            footnote("Use an https address when you can. Digi adds https:// to names and public addresses, and http:// only to home, campus and Tailscale addresses.")
            addressNote
            footnote("The photos you choose are sent to this server to plan your shots and are deleted after each request.")
        }
    }

    /// Same wording as Settings: a note for a plain http address, a message for one that is not valid.
    @ViewBuilder private var addressNote: some View {
        if let url = ServerAddress.url(from: serverURL) {
            if ServerAddress.isPlainHTTP(url) {
                Text("Not encrypted: your key and photos can be read by others on this network. Use it only on a network you trust, or use an https address (for example through Tailscale).")
                    .font(.footnote).foregroundStyle(.orange.opacity(0.9))
                    .padding(14).frame(maxWidth: .infinity, alignment: .leading)
                    .background(.orange.opacity(0.1), in: RoundedRectangle(cornerRadius: 12))
                    .overlay(RoundedRectangle(cornerRadius: 12).stroke(.orange.opacity(0.5), lineWidth: 1))
                    .accessibilityIdentifier("onboarding-plain-http")
            }
        } else if !serverURL.trimmingCharacters(in: .whitespaces).isEmpty {
            Text("That address is not valid. Use a host name or address, with http:// or https:// if you like.")
                .font(.footnote).foregroundStyle(.red.opacity(0.85))
        }
    }

    // MARK: pieces

    private func title(_ text: String) -> some View {
        Text(text).font(.title.weight(.semibold)).fixedSize(horizontal: false, vertical: true)
            .accessibilityAddTraits(.isHeader)
    }

    private func bodyText(_ text: String) -> some View {
        Text(text).font(.body).foregroundStyle(theme.silver.opacity(0.7)).fixedSize(horizontal: false, vertical: true)
    }

    private func footnote(_ text: String) -> some View {
        Text(text).font(.footnote).foregroundStyle(theme.silver.opacity(0.6)).fixedSize(horizontal: false, vertical: true)
    }

    /// A step or a point: a numbered badge, or an accent dot when `badge` is nil.
    private func row(badge: String?, title: String, detail: String) -> some View {
        HStack(alignment: .top, spacing: 14) {
            ZStack {
                Circle().fill(badge == nil ? accent.opacity(0.2) : accent)
                if let badge {
                    Text(badge).font(.subheadline.weight(.semibold)).foregroundStyle(.black)
                } else {
                    Circle().fill(accent).frame(width: 10, height: 10)
                }
            }
            .frame(width: 32, height: 32).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.headline)
                Text(detail).font(.subheadline).foregroundStyle(theme.silver.opacity(0.65))
            }
            .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .combine)
    }

    private func card(_ title: String, _ detail: String, tag: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.headline)
            Text(detail).font(.subheadline).foregroundStyle(theme.silver.opacity(0.65))
            Text(tag).font(.footnote.weight(.medium)).foregroundStyle(hint)
        }
        .fixedSize(horizontal: false, vertical: true)
        .padding(16).frame(maxWidth: .infinity, alignment: .leading)
        .background(theme.panel, in: RoundedRectangle(cornerRadius: 16))
        .accessibilityElement(children: .combine)
    }

    private func field<Content: View>(_ label: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(label).font(.footnote.weight(.semibold)).foregroundStyle(theme.silver.opacity(0.55))
            content().padding(14).frame(maxWidth: .infinity, alignment: .leading)
                .background(theme.panel, in: RoundedRectangle(cornerRadius: 12))
        }
    }
}

/// The welcome picture: a viewfinder with thirds lines, a person on the left third, a dashed frame and a cue.
private struct ViewfinderIllustration: View {
    let theme: GuidanceTheme

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width, h = geo.size.height
            ZStack {
                RoundedRectangle(cornerRadius: 24).fill(theme.panel)
                Path { p in
                    for x in [w / 3, 2 * w / 3] { p.move(to: CGPoint(x: x, y: 0)); p.addLine(to: CGPoint(x: x, y: h)) }
                    for y in [h / 3, 2 * h / 3] { p.move(to: CGPoint(x: 0, y: y)); p.addLine(to: CGPoint(x: w, y: y)) }
                }
                .stroke(theme.silver.opacity(0.12), lineWidth: 1)
                Circle().fill(theme.silver.opacity(0.35)).frame(width: 44, height: 44).position(x: w / 3, y: 88)
                UnevenRoundedRectangle(topLeadingRadius: 42, topTrailingRadius: 42)
                    .fill(theme.silver.opacity(0.35)).frame(width: 84, height: 130).position(x: w / 3, y: 185)
                RoundedRectangle(cornerRadius: 14)
                    .stroke(theme.accent, style: StrokeStyle(lineWidth: 2, dash: [10, 8])).padding(14)
                Text("Step closer").font(.subheadline.weight(.semibold)).foregroundStyle(theme.hint ?? theme.accent)
                    .padding(.horizontal, 16).padding(.vertical, 9)
                    .background(theme.body.opacity(0.85), in: Capsule())
                    .position(x: w / 2, y: 255)
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 24))
        .accessibilityHidden(true)
    }
}
