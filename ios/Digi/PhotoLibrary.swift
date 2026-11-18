import SwiftUI
import UIKit
import ImageIO

/// A photo taken with Digi, kept in the app's own folder so the in-app album can list it. The copy in the
/// system Photos library is separate: deleting here never touches Photos, and Digi never reads Photos.
struct AppPhoto: Identifiable, Hashable {
    let id: String
    let url: URL
    let date: Date
}

final class AppPhotoStore: ObservableObject {
    static let shared = AppPhotoStore()
    @Published private(set) var photos: [AppPhoto] = []
    private let dir: URL
    private let queue = DispatchQueue(label: "digi.photostore", qos: .utility)
    private let thumbnails = NSCache<NSString, UIImage>()

    private init() {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        dir = base.appendingPathComponent("Digi/Photos", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        #if DEBUG
        // Debug only: `-digiDebugPhotos 1` fills the album with sample images to look at the layout.
        if UserDefaults.standard.integer(forKey: "digiDebugPhotos") > 0, (try? FileManager.default.contentsOfDirectory(atPath: dir.path))?.isEmpty ?? true {
            for i in 0..<14 {
                let size = i % 3 == 0 ? CGSize(width: 1200, height: 900) : CGSize(width: 900, height: 1200)
                let image = UIGraphicsImageRenderer(size: size).image { ctx in
                    let hue = CGFloat(i) / 14
                    UIColor(hue: hue, saturation: 0.35, brightness: 0.55, alpha: 1).setFill(); ctx.fill(CGRect(origin: .zero, size: size))
                    UIColor(hue: hue, saturation: 0.25, brightness: 0.85, alpha: 1).setFill()
                    ctx.cgContext.fillEllipse(in: CGRect(x: size.width * 0.3, y: size.height * 0.3, width: size.width * 0.4, height: size.width * 0.4))
                }
                if let data = image.jpegData(compressionQuality: 0.8) {
                    let url = dir.appendingPathComponent(String(format: "20261116-1200%02d-debug%02d.jpg", i, i))
                    try? data.write(to: url)
                }
            }
        }
        #endif
        reload()
    }

    /// Lists the folder, newest first. Names start with the capture time, so the name order is the time order.
    func reload() {
        let files = (try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: [.contentModificationDateKey])) ?? []
        photos = files.filter { $0.pathExtension == "jpg" }
            .map { url in
                let date = (try? url.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
                return AppPhoto(id: url.lastPathComponent, url: url, date: date)
            }
            .sorted { $0.id > $1.id }
    }

    /// Keeps a copy of a photo that was saved to Photos. Safe to call from any thread.
    func add(_ data: Data) {
        queue.async {
            let formatter = DateFormatter()
            formatter.dateFormat = "yyyyMMdd-HHmmss"
            let name = "\(formatter.string(from: Date()))-\(UUID().uuidString.prefix(4)).jpg"
            try? data.write(to: self.dir.appendingPathComponent(name), options: .atomic)
            DispatchQueue.main.async { self.reload() }
        }
    }

    func delete(_ photo: AppPhoto) {
        try? FileManager.default.removeItem(at: photo.url)
        thumbnails.removeObject(forKey: photo.id as NSString)
        reload()
    }

    func image(_ photo: AppPhoto) -> UIImage? { UIImage(contentsOfFile: photo.url.path) }

    /// A small square-friendly preview, decoded from the file at reduced size and cached.
    func thumbnail(_ photo: AppPhoto) -> UIImage? {
        if let cached = thumbnails.object(forKey: photo.id as NSString) { return cached }
        guard let source = CGImageSourceCreateWithURL(photo.url as CFURL, nil),
              let cg = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceCreateThumbnailWithTransform: true,
                kCGImageSourceThumbnailMaxPixelSize: 420] as CFDictionary) else { return nil }
        let image = UIImage(cgImage: cg)
        thumbnails.setObject(image, forKey: photo.id as NSString)
        return image
    }
}

/// The in-app album: every photo taken with Digi in a grid, tap one to view it full screen.
struct PhotoLibraryView: View {
    @ObservedObject private var store = AppPhotoStore.shared
    @Environment(\.guidanceTheme) private var theme
    var note: String?
    var close: () -> Void
    @State private var selected: AppPhoto?

    private let columns = [GridItem(.adaptive(minimum: 108), spacing: 3)]

    var body: some View {
        ZStack {
            theme.body.ignoresSafeArea()
            VStack(spacing: 0) {
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Photos").font(.title3.weight(.semibold))
                        Text(store.photos.isEmpty ? "TAKEN WITH DIGI" : "\(store.photos.count) TAKEN WITH DIGI")
                            .font(.system(size: 10, design: .monospaced)).tracking(0.6).foregroundStyle(theme.silver.opacity(0.6))
                    }
                    Spacer()
                    Button("Done", action: close).foregroundStyle(theme.accent).frame(minWidth: 44, minHeight: 44)
                        .accessibilityIdentifier("photos-done")
                }.padding(.horizontal, 20).padding(.top, 8).padding(.bottom, 10)

                if let note {
                    Text(note).font(.footnote).foregroundStyle(theme.silver.opacity(0.75))
                        .padding(.horizontal, 20).padding(.bottom, 8).frame(maxWidth: .infinity, alignment: .leading)
                }

                if store.photos.isEmpty {
                    Spacer()
                    Image(systemName: "photo.on.rectangle").font(.system(size: 32)).foregroundStyle(theme.accent)
                    Text("Your next moment starts here.").font(.headline).padding(.top, 6)
                    Text("Photos you take with Digi show up here.").font(.subheadline).foregroundStyle(theme.silver.opacity(0.65))
                    Spacer()
                } else {
                    ScrollView {
                        LazyVGrid(columns: columns, spacing: 3) {
                            ForEach(store.photos) { photo in
                                Button { selected = photo } label: {
                                    Color.clear.aspectRatio(1, contentMode: .fit)
                                        .overlay {
                                            if let image = store.thumbnail(photo) {
                                                Image(uiImage: image).resizable().scaledToFill()
                                            } else { Rectangle().fill(theme.panel) }
                                        }
                                        .clipped().contentShape(Rectangle())
                                }.buttonStyle(.plain).accessibilityLabel("Photo from \(photo.date.formatted(date: .abbreviated, time: .shortened))")
                            }
                        }
                    }
                }
            }
            .foregroundStyle(theme.silver)

            if let selected {
                PhotoViewer(start: selected) { self.selected = nil }
                    .transition(.opacity)
            }
        }
        .animation(.easeOut(duration: 0.18), value: selected)
    }
}

/// Full-screen viewer: swipe between photos, pinch or double-tap to zoom, share, or remove from the album.
private struct PhotoViewer: View {
    @ObservedObject private var store = AppPhotoStore.shared
    @Environment(\.guidanceTheme) private var theme
    let start: AppPhoto
    var close: () -> Void
    @State private var current: String
    @State private var confirmDelete = false

    init(start: AppPhoto, close: @escaping () -> Void) {
        self.start = start; self.close = close
        _current = State(initialValue: start.id)
    }

    private var photo: AppPhoto? { store.photos.first { $0.id == current } }

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            TabView(selection: $current) {
                ForEach(store.photos) { p in
                    ZoomableImage(image: store.image(p)).ignoresSafeArea().tag(p.id)
                }
            }.tabViewStyle(.page(indexDisplayMode: .never)).ignoresSafeArea()

            VStack {
                HStack {
                    glassButton("chevron.left", "Back to photos", action: close)
                    Spacer()
                    if let photo {
                        Text(photo.date.formatted(date: .abbreviated, time: .shortened))
                            .font(.system(size: 11, design: .monospaced)).padding(.horizontal, 12).padding(.vertical, 8)
                            .background(.black.opacity(0.5), in: Capsule())
                    }
                    Spacer()
                    Color.clear.frame(width: 44, height: 44)
                }.padding(.horizontal, 16).padding(.top, 8)
                Spacer()
                HStack(spacing: 40) {
                    if let photo, let image = store.image(photo) {
                        ShareLink(item: Image(uiImage: image), preview: SharePreview("Photo", image: Image(uiImage: image))) {
                            iconLabel("square.and.arrow.up", "SHARE")
                        }
                    }
                    Button { confirmDelete = true } label: { iconLabel("trash", "REMOVE") }
                }.padding(.bottom, 28)
            }
            .foregroundStyle(.white)
        }
        .confirmationDialog("Remove from Digi?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Remove from this album", role: .destructive) { removeCurrent() }
        } message: {
            Text("The copy in your Photos library stays.")
        }
        .onChange(of: store.photos) { _, photos in
            if photos.isEmpty { close() }
        }
    }

    private func removeCurrent() {
        guard let photo, let index = store.photos.firstIndex(of: photo) else { return }
        let next = store.photos.indices.contains(index + 1) ? store.photos[index + 1] : (index > 0 ? store.photos[index - 1] : nil)
        store.delete(photo)
        if let next { current = next.id } else { close() }
    }

    private func glassButton(_ symbol: String, _ label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol).font(.system(size: 16, weight: .semibold)).frame(width: 44, height: 44)
                .background(.black.opacity(0.5), in: Circle()).overlay(Circle().stroke(.white.opacity(0.22), lineWidth: 0.5))
        }.accessibilityLabel(label)
    }

    private func iconLabel(_ symbol: String, _ text: String) -> some View {
        VStack(spacing: 4) {
            Image(systemName: symbol).font(.system(size: 20)).frame(width: 52, height: 52)
                .background(.black.opacity(0.5), in: Circle()).overlay(Circle().stroke(.white.opacity(0.22), lineWidth: 0.5))
            Text(text).font(.system(size: 9, design: .monospaced)).foregroundStyle(theme.accent)
        }
    }
}

/// A zoomable image: pinch, pan while zoomed, double-tap to zoom in and out.
private struct ZoomableImage: UIViewRepresentable {
    let image: UIImage?

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> UIScrollView {
        let scroll = FittingScrollView()
        scroll.delegate = context.coordinator
        scroll.minimumZoomScale = 1; scroll.maximumZoomScale = 5
        scroll.showsHorizontalScrollIndicator = false; scroll.showsVerticalScrollIndicator = false
        scroll.backgroundColor = .clear
        let view = UIImageView(image: image)
        view.contentMode = .scaleAspectFit
        scroll.addSubview(view)
        scroll.fitted = view
        context.coordinator.imageView = view
        context.coordinator.scroll = scroll
        let tap = UITapGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.doubleTap(_:)))
        tap.numberOfTapsRequired = 2
        scroll.addGestureRecognizer(tap)
        return scroll
    }

    func updateUIView(_ scroll: UIScrollView, context: Context) {
        context.coordinator.imageView?.image = image
        scroll.setNeedsLayout()
    }

    /// Keeps the picture filling the view whenever it is not zoomed (the bounds are zero until the first layout).
    final class FittingScrollView: UIScrollView {
        var fitted: UIImageView?
        override func layoutSubviews() {
            super.layoutSubviews()
            guard zoomScale == 1, let fitted else { return }
            fitted.frame = bounds
            contentSize = bounds.size
        }
    }

    final class Coordinator: NSObject, UIScrollViewDelegate {
        var imageView: UIImageView?
        weak var scroll: UIScrollView?
        func viewForZooming(in scrollView: UIScrollView) -> UIView? { imageView }
        @objc func doubleTap(_ gesture: UITapGestureRecognizer) {
            guard let scroll else { return }
            if scroll.zoomScale > 1.01 { scroll.setZoomScale(1, animated: true); return }
            let point = gesture.location(in: imageView)
            let size = CGSize(width: scroll.bounds.width / 2.5, height: scroll.bounds.height / 2.5)
            scroll.zoom(to: CGRect(x: point.x - size.width / 2, y: point.y - size.height / 2, width: size.width, height: size.height), animated: true)
        }
    }
}
