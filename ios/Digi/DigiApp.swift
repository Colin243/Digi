import SwiftUI
import AVFoundation
import Photos
import CoreImage
import ImageIO

@main
struct DigiApp: App {
    var body: some Scene { WindowGroup { CameraView() } }
}

enum PhotoFlash: String, CaseIterable, Identifiable {
    case off = "Off", auto = "Auto", on = "On"
    var id: String { rawValue }
    var mode: AVCaptureDevice.FlashMode {
        switch self { case .off: return .off; case .auto: return .auto; case .on: return .on }
    }
    var symbol: String {
        switch self { case .off: return "bolt.slash"; case .auto: return "bolt.badge.a"; case .on: return "bolt.fill" }
    }
}

final class CameraController: NSObject, ObservableObject, AVCapturePhotoCaptureDelegate, AVCaptureVideoDataOutputSampleBufferDelegate {
    let session = AVCaptureSession()
    private let output = AVCapturePhotoOutput()
    // Persistent opt-in study; ordinary shooting uses the physical wide camera.
    @Published private(set) var captureStudyEnabled = UserDefaults.standard.bool(forKey: "digi.captureStudy")
    @Published private(set) var studyFeedback = UserDefaults.standard.string(forKey: "digi.studyFeedback") ?? "No study capture yet"
    private var maskStudy: Bool { captureStudyEnabled }
    private let maskStudyQueue = DispatchQueue(label: "digi.mask-study", qos: .utility)
    private var studyCaptureStart: CFAbsoluteTime = 0
    private var studyForCapture = false
    private var studyCameraType = ""
    private var studyZoomFactor: CGFloat = 1
    private var photoProcessingReceived = false // main queue; capture completion must not reopen the shutter during rendering

    private var captureDevice: AVCaptureDevice? // capture queue only
    @Published var focusPoint: CGPoint?
    @Published var focusSupported = false
    @Published var exposureLocked = false
    @Published var exposureBias: Float = 0
    @Published var exposureRange: ClosedRange<Float> = -2...2
    @Published var exposureSupported = false
    @Published var lastFlashFired = false
    private var focusGeneration = 0 // capture queue; cancels stale lock requests
    private var requestedFlashForCapture: PhotoFlash = .off
    private var flashSuppressed = false
    @Published var supportedFlash: [PhotoFlash] = []
    @Published var flash = PhotoFlash(rawValue: UserDefaults.standard.string(forKey: "digi.flash") ?? "Off") ?? .off {
        didSet { UserDefaults.standard.set(flash.rawValue, forKey: "digi.flash") }
    }
    private let video = AVCaptureVideoDataOutput()
    private let renderQueue = DispatchQueue(label: "digi.preview", qos: .userInitiated)
    private let photoRenderQueue = DispatchQueue(label: "digi.photo-render", qos: .userInitiated)
    private let renderer = G12Renderer()
    private let previewSlot = DispatchSemaphore(value: 1)
    private var renderEnabled = true // confined to renderQueue
    private var captureWithLook = false // frozen at shutter press
    @Published var renderedPreview: CGImage?
    var lookEnabled: Bool { lookAvailable }
    @Published var photoLookApplied = false
    var lookAvailable: Bool {
        var info = utsname(); uname(&info)
        let model = withUnsafePointer(to: &info.machine) { $0.withMemoryRebound(to: CChar.self, capacity: 1) { String(cString: $0) } }
        #if targetEnvironment(simulator)
        return renderer != nil
        #else
        return model == "iPhone18,1" && renderer != nil
        #endif
    }
    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        // Process each available frame. A 1/24 threshold on a 30 fps stream
        // discards every other frame (15 fps), rather than producing 24 fps.
        guard renderEnabled,
              let pixel = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        guard previewSlot.wait(timeout: .now()) == .success else { return }
        autoreleasepool {
            guard let frame = renderer?.render(CIImage(cvPixelBuffer: pixel), maxDimension: 960) else { previewSlot.signal(); return }
            DispatchQueue.main.async {
                if self.lookEnabled && self.ready { self.renderedPreview = frame }
                self.previewSlot.signal()
            }
        }
    }
    private let queue = DispatchQueue(label: "digit.capture")
    @Published var status = "Opening camera…"
    @Published var lastPhoto: UIImage?
    @Published var ready = false
    @Published var busy = false
    @Published var pending = false
    private var pendingData: Data?
    private var configured = false

    func start() {
        let active = lookAvailable
        renderQueue.async { self.renderEnabled = active }
        AVCaptureDevice.requestAccess(for: .video) { allowed in
            guard allowed else { self.message("Allow Camera access in Settings to take photos."); return }
            self.queue.async {
                do {
                    if !self.configured {
                        let studyDevice = self.maskStudy ? self.probeSkinCamera() : nil
                        guard let device = studyDevice ?? AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back) else {
                            self.message("No rear camera available. Use a connected iPhone.")
                            return
                        }
                        let input = try AVCaptureDeviceInput(device: device)
                        self.session.beginConfiguration()
                        self.session.sessionPreset = .photo
                        guard self.session.canAddInput(input), self.session.canAddOutput(self.output) else {
                            self.session.commitConfiguration()
                            self.message("Camera configuration is unavailable.")
                            return
                        }
                        self.session.addInput(input)
                        self.captureDevice = device
                        self.session.addOutput(self.output)
                        // Favor still-image processing quality without increasing preview work.
                        self.output.maxPhotoQualityPrioritization = .quality
                        if self.session.canAddOutput(self.video) {
                            self.video.alwaysDiscardsLateVideoFrames = true
                            self.video.setSampleBufferDelegate(self, queue: self.renderQueue)
                            self.session.addOutput(self.video)
                            if let connection = self.video.connection(with: .video), connection.isVideoRotationAngleSupported(0) {
                                connection.videoRotationAngle = 0
                            }
                        }
                        self.session.commitConfiguration()
                        // Available matte types depend on the committed inputs and outputs.
                        // Enable before startRunning to avoid an expensive live reconfiguration.
                        if self.maskStudy {
                            // Skin mattes are advertised without depth on this device.
                            // Depth forced the dual camera to its 100mm view during testing.
                            self.output.isDepthDataDeliveryEnabled = false
                            try device.lockForConfiguration()
                            device.videoZoomFactor = max(device.minAvailableVideoZoomFactor, 1)
                            device.unlockForConfiguration()
                            if self.output.availableSemanticSegmentationMatteTypes.contains(.skin) {
                                self.output.enabledSemanticSegmentationMatteTypes = [.skin]
                            }
                        } else {
                            self.output.enabledSemanticSegmentationMatteTypes = []
                        }
                        self.configured = true
                    }
                    if !self.session.isRunning { self.session.startRunning() }
                    let modes = PhotoFlash.allCases.filter { self.output.supportedFlashModes.contains($0.mode) }
                    let canFocus = self.captureDevice.map { $0.isFocusPointOfInterestSupported && $0.isFocusModeSupported(.autoFocus) && $0.isFocusModeSupported(.continuousAutoFocus) } ?? false
                    DispatchQueue.main.async {
                        self.exposureSupported = self.captureDevice?.isExposureModeSupported(.continuousAutoExposure) == true
                        if let device = self.captureDevice {
                            self.exposureRange = max(-2, device.minExposureTargetBias)...min(2, device.maxExposureTargetBias)
                        }
                        self.focusSupported = canFocus
                        self.supportedFlash = modes
                        if !modes.contains(self.flash) { self.flash = .off }
                        self.ready = true
                        if !self.busy { self.status = self.pending ? "Photo not saved yet. Retry when ready." : "" }
                    }
                } catch { self.message("Camera could not start: \(error.localizedDescription)") }
            }
        }
    }

    func stop() {
        focus(at: nil)
        ready = false
        renderedPreview = nil
        queue.async { if self.session.isRunning { self.session.stopRunning() } }
    }

    func setCaptureStudyEnabled(_ enabled: Bool) {
        guard enabled != captureStudyEnabled, !busy, !pending else { return }
        captureStudyEnabled = enabled
        UserDefaults.standard.set(enabled, forKey: "digi.captureStudy")
        ready = false
        renderedPreview = nil
        focusPoint = nil
        focusSupported = false
        exposureLocked = false
        exposureBias = 0
        exposureSupported = false
        status = "Configuring camera…"
        queue.async {
            self.focusGeneration += 1 // Cancel a pending lock before replacing the camera.
            if self.session.isRunning { self.session.stopRunning() }
            self.session.beginConfiguration()
            for output in self.session.outputs { self.session.removeOutput(output) }
            for input in self.session.inputs { self.session.removeInput(input) }
            self.session.commitConfiguration()
            self.captureDevice = nil
            self.configured = false
            DispatchQueue.main.async { self.start() }
        }
    }

    func focus(at point: CGPoint?, lock: Bool = false) {
        guard point == nil || (ready && focusSupported && !busy && !pending) else { return }
        if let point, !(0...1).contains(point.x) || !(0...1).contains(point.y) { return }
        queue.async {
            guard let device = self.captureDevice,
                  device.isFocusPointOfInterestSupported,
                  device.isFocusModeSupported(point == nil ? .continuousAutoFocus : .autoFocus) else { return }
            do {
                try device.lockForConfiguration()
                defer { device.unlockForConfiguration() }
                self.focusGeneration += 1
                let generation = self.focusGeneration
                device.focusPointOfInterest = point ?? CGPoint(x: 0.5, y: 0.5)
                if device.isExposurePointOfInterestSupported {
                    device.exposurePointOfInterest = point ?? CGPoint(x: 0.5, y: 0.5)
                }
                if device.isExposureModeSupported(.continuousAutoExposure) {
                    device.exposureMode = .continuousAutoExposure
                }
                if point == nil { device.setExposureTargetBias(0, completionHandler: nil) }
                // One-shot AF settles and holds; continuous AF resumes on reset.
                device.focusMode = point == nil ? .continuousAutoFocus : .autoFocus
                DispatchQueue.main.async {
                    self.focusPoint = point
                    self.exposureLocked = false
                    if point == nil { self.exposureBias = 0 }
                }
                if lock && point != nil {
                    self.queue.asyncAfter(deadline: .now() + 0.2) {
                        self.finishFocusLock(generation: generation, attempts: 30)
                    }
                }
            } catch { self.message("Could not adjust focus. Try tapping again.") }
        }
    }

    private func finishFocusLock(generation: Int, attempts: Int) {
        guard generation == focusGeneration, let device = captureDevice else { return }
        if device.isAdjustingFocus || device.isAdjustingExposure {
            guard attempts > 0 else { message("Could not lock yet. Hold the camera still and try again."); return }
            queue.asyncAfter(deadline: .now() + 0.1) {
                self.finishFocusLock(generation: generation, attempts: attempts - 1)
            }
            return
        }
        guard device.isFocusModeSupported(.locked), device.isExposureModeSupported(.locked) else {
            message("Exposure lock is unavailable on this camera."); return
        }
        do {
            try device.lockForConfiguration()
            device.focusMode = .locked
            device.exposureMode = .locked
            device.unlockForConfiguration()
            DispatchQueue.main.async { self.exposureLocked = true }
        } catch { message("Could not lock focus and exposure.") }
    }

    func setBrightness(_ value: Float) {
        guard ready, !busy, !pending, exposureSupported, !exposureLocked else { return }
        let bias = min(exposureRange.upperBound, max(exposureRange.lowerBound, value))
        exposureBias = bias
        queue.async {
            guard let device = self.captureDevice, device.exposureMode != .locked else { return }
            do {
                try device.lockForConfiguration()
                device.setExposureTargetBias(bias, completionHandler: nil)
                device.unlockForConfiguration()
            } catch { self.message("Could not adjust brightness.") }
        }
    }

    func capture(angle: CGFloat) {
        guard ready, !busy, pendingData == nil else { return }
        busy = true
        photoProcessingReceived = false
        captureWithLook = lookEnabled && lookAvailable
        studyForCapture = maskStudy
        if studyForCapture { studyFeedback = "Recording capture study…" }
        let requestedFlash = flash // freeze with this shutter request
        requestedFlashForCapture = requestedFlash
        flashSuppressed = false
        status = "Capturing…"
        queue.async {
            self.focusGeneration += 1 // Do not complete a pending AE/AF lock during capture.
            if let connection = self.output.connection(with: .video), connection.isVideoRotationAngleSupported(angle) {
                connection.videoRotationAngle = angle
            }
            let settings = AVCapturePhotoSettings(format: [AVVideoCodecKey: AVVideoCodecType.jpeg])
            guard self.output.supportedFlashModes.contains(requestedFlash.mode),
                  requestedFlash != .on || self.captureDevice?.isFlashAvailable == true else {
                DispatchQueue.main.async {
                    self.busy = false
                    self.status = "Flash unavailable. Choose Off or try again shortly."
                }
                return
            }
            settings.photoQualityPrioritization = .quality
            settings.flashMode = requestedFlash.mode
            if self.output.isAutoRedEyeReductionSupported { settings.isAutoRedEyeReductionEnabled = true }
            if self.studyForCapture {
                // Availability can change with formats; request only currently enabled types.
                settings.isDepthDataDeliveryEnabled = self.output.isDepthDataDeliveryEnabled
                settings.enabledSemanticSegmentationMatteTypes = self.output.enabledSemanticSegmentationMatteTypes.filter { $0 == .skin }
                self.studyCaptureStart = CFAbsoluteTimeGetCurrent()
                self.studyCameraType = self.captureDevice?.deviceType.rawValue ?? "unknown"
                self.studyZoomFactor = self.captureDevice?.videoZoomFactor ?? 1
            }
            self.output.capturePhoto(with: settings, delegate: self)
        }
    }

    func photoOutput(_ output: AVCapturePhotoOutput, didFinishProcessingPhoto photo: AVCapturePhoto, error: Error?) {
        DispatchQueue.main.async { self.photoProcessingReceived = true }
        guard error == nil, let data = photo.fileDataRepresentation() else {
            DispatchQueue.main.async { self.busy = false; self.status = "Capture failed. Try again." }
            return
        }
        let study = studyForCapture
        let matte = study ? photo.semanticSegmentationMatte(for: .skin) : nil
        let elapsed = CFAbsoluteTimeGetCurrent() - studyCaptureStart
        let supported = study && output.availableSemanticSegmentationMatteTypes.contains(.skin)
        let requested = study && output.enabledSemanticSegmentationMatteTypes.contains(.skin)
        let fired = photo.resolvedSettings.isFlashEnabled
        let cameraType = studyCameraType
        let zoomFactor = studyZoomFactor
        DispatchQueue.main.async {
            self.lastFlashFired = fired
            self.flashSuppressed = self.requestedFlashForCapture == .on && !self.lastFlashFired
            let style = self.captureWithLook
            self.photoRenderQueue.async {
                let styled = style ? self.renderer?.jpeg(data) : nil
                let result = styled ?? data
                if study {
                    self.maskStudyQueue.async {
                        let feedback = Self.exportMaskStudy(data: data, result: result, matte: matte,
                            supported: supported, requested: requested, lookApplied: styled != nil,
                            flashFired: fired, captureSeconds: elapsed, cameraType: cameraType, zoomFactor: zoomFactor)
                        DispatchQueue.main.async {
                            self.studyFeedback = feedback
                            UserDefaults.standard.set(feedback, forKey: "digi.studyFeedback")
                            if self.status.hasPrefix("Saved to Photos") { self.status = "Saved to Photos. \(feedback)" }
                        }
                    }
                }
                DispatchQueue.main.async {
                    self.photoLookApplied = styled != nil
                    self.lastPhoto = UIImage(data: result)
                    self.pendingData = result
                    self.pending = true
                    self.save()
                }
            }
        }
    }

    func photoOutput(_ output: AVCapturePhotoOutput, didFinishCaptureFor resolvedSettings: AVCaptureResolvedPhotoSettings, error: Error?) {
        if let error {
            DispatchQueue.main.async {
                // didFinishCaptureFor is the final delegate callback. A processed photo may
                // still be rendering and saving, so only a capture with no photo callback
                // can reopen the shutter here.
                if !self.photoProcessingReceived && !self.pending {
                    self.busy = false
                    self.status = "Capture failed: \(error.localizedDescription)"
                }
            }
        }
    }


    // Diagnostic setup runs once, never on the preview queue. A successful capability
    // report is not a guarantee that a particular photo will contain a matte.
    private func probeSkinCamera() -> AVCaptureDevice? {
        let types: [AVCaptureDevice.DeviceType] = [.builtInWideAngleCamera, .builtInDualCamera, .builtInDualWideCamera, .builtInTripleCamera]
        var reports: [[String: Any]] = []
        var selected: AVCaptureDevice?
        for type in types {
            guard let device = AVCaptureDevice.default(type, for: .video, position: .back),
                  let input = try? AVCaptureDeviceInput(device: device) else { continue }
            let probe = AVCaptureSession()
            let photo = AVCapturePhotoOutput()
            let preview = AVCaptureVideoDataOutput()
            probe.beginConfiguration()
            probe.sessionPreset = .photo
            guard probe.canAddInput(input), probe.canAddOutput(photo) else { probe.commitConfiguration(); continue }
            probe.addInput(input); probe.addOutput(photo)
            if probe.canAddOutput(preview) { probe.addOutput(preview) }
            probe.commitConfiguration()
            let before = photo.availableSemanticSegmentationMatteTypes.map { $0.rawValue }
            // Keep depth disabled: capability alone must not change framing.
            let supportsSkin = photo.availableSemanticSegmentationMatteTypes.contains(.skin)
            reports.append(["camera": type.rawValue, "name": device.localizedName,
                "depth_supported": photo.isDepthDataDeliverySupported,
                "matte_types_before_depth": before,
                "matte_types_depth_disabled": photo.availableSemanticSegmentationMatteTypes.map { $0.rawValue }, "zoom": device.videoZoomFactor, "minimum_zoom": device.minAvailableVideoZoomFactor,
                "skin_supported": supportsSkin, "flash_available": device.hasFlash,
                "preview_connected": probe.outputs.contains(preview)])
            if supportsSkin && device.hasFlash && selected == nil { selected = device }
            probe.beginConfiguration()
            probe.removeInput(input); probe.removeOutput(photo)
            if probe.outputs.contains(preview) { probe.removeOutput(preview) }
            probe.commitConfiguration()
        }
        do {
            let root = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
            let data = try JSONSerialization.data(withJSONObject: ["cameras": reports, "selected": selected?.deviceType.rawValue ?? "physical-wide-fallback"], options: [.prettyPrinted, .sortedKeys])
            try data.write(to: root.appendingPathComponent("mask-capabilities.json"), options: .atomic)
        } catch { NSLog("Digi capability export failed: %@", error.localizedDescription) }
        return selected
    }

    private static func exportMaskStudy(data: Data, result: Data, matte: AVSemanticSegmentationMatte?,
        supported: Bool, requested: Bool, lookApplied: Bool, flashFired: Bool,
        captureSeconds: Double, cameraType: String, zoomFactor: CGFloat) -> String {
        let started = CFAbsoluteTimeGetCurrent()
        do {
            let root = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
            var folder = root.appendingPathComponent("MaskStudy/" + UUID().uuidString, isDirectory: true)
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            var values = URLResourceValues(); values.isExcludedFromBackup = true
            try folder.setResourceValues(values)
            // Exact pre-LUT capture bytes; never modified by the experiment.
            try data.write(to: folder.appendingPathComponent("original.jpg"), options: .atomic)
            // Exact bytes used for the Photos save, including original fallback.
            try result.write(to: folder.appendingPathComponent("styled.jpg"), options: .atomic)
            let source = CGImageSourceCreateWithData(data as CFData, nil)
            let properties = source.flatMap { CGImageSourceCopyPropertiesAtIndex($0, 0, nil) as? [String: Any] } ?? [:]
            let orientation = (properties[kCGImagePropertyOrientation as String] as? NSNumber)?.int32Value ?? 1
            var record: [String: Any] = ["skin_supported": supported, "skin_requested": requested,
                "skin_delivered": matte != nil, "look_applied": lookApplied,
                "flash_fired": flashFired, "capture_to_callback_seconds": captureSeconds,
                "camera_type": cameraType, "zoom_factor": zoomFactor,
                "original_orientation": orientation, "mask_orientation": 1,
                "color_processing": "none", "light_source": "unknown", "context": "unknown", "direction": "unknown"]
            if let matte {
                let mask = CIImage(cvPixelBuffer: matte.mattingImage).oriented(forExifOrientation: orientation)
                let context = CIContext(options: [.cacheIntermediates: false])
                try context.writePNGRepresentation(of: mask, to: folder.appendingPathComponent("skin.png"), format: .L8, colorSpace: CGColorSpaceCreateDeviceGray())
                record["mask_width"] = Int(mask.extent.width)
                record["mask_height"] = Int(mask.extent.height)
            }
            record["export_seconds"] = CFAbsoluteTimeGetCurrent() - started
            let json = try JSONSerialization.data(withJSONObject: record, options: [.prettyPrinted, .sortedKeys])
            try json.write(to: folder.appendingPathComponent("capture.json"), options: .atomic)
            NSLog("Digi mask study exported: %@", folder.lastPathComponent)
            return matte == nil ? "Study saved; no skin mask delivered" : "Study saved with skin mask"
        } catch {
            // Diagnostic failure must not interrupt the normal photo save.
            NSLog("Digi mask study export failed: %@", error.localizedDescription)
            return "Study export failed"
        }
    }

    func save() {
        guard let data = pendingData else { return }
        busy = true
        status = "Saving to Photos…"
        PHPhotoLibrary.requestAuthorization(for: .addOnly) { permission in
            guard permission == .authorized || permission == .limited else {
                DispatchQueue.main.async { self.busy = false; self.status = "Allow Photos access in Settings, then retry. Photo retained until app closes." }
                return
            }
            PHPhotoLibrary.shared().performChanges {
                PHAssetCreationRequest.forAsset().addResource(with: .photo, data: data, options: nil)
            } completionHandler: { saved, error in
                DispatchQueue.main.async {
                    self.busy = false
                    if saved {
                        self.pendingData = nil; self.pending = false
                        self.status = self.flashSuppressed ? "Saved to Photos. Flash did not fire; try again when available." : self.captureWithLook && !self.photoLookApplied ? "Saved original to Photos. G12 look could not be applied." : self.studyForCapture && !self.studyFeedback.hasPrefix("Recording") ? "Saved to Photos. \(self.studyFeedback)" : "Saved to Photos"
                    }
                    else { self.status = "Save failed. Photo retained; tap Retry save. \(error?.localizedDescription ?? "")" }
                }
            }
        }
    }

    private func message(_ text: String) { DispatchQueue.main.async { self.status = text } }
}

private enum CameraRotation {
    static func angle(for orientation: UIInterfaceOrientation) -> CGFloat {
        switch orientation {
        case .portrait: return 90
        case .portraitUpsideDown: return 270
        case .landscapeLeft: return 180
        default: return 0
        }
    }
}

final class PreviewSurface: UIView {
    override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
    var orientationChanged: ((UIInterfaceOrientation) -> Void)?
    var focusRequested: ((CGPoint, Bool) -> Void)?
    var focusPositionChanged: ((CGPoint?) -> Void)?
    var selectedFocus: CGPoint?
    private var lastFocusPosition: CGPoint?
    override init(frame: CGRect) {
        super.init(frame: frame)
        let tap = UITapGestureRecognizer(target: self, action: #selector(tapFocus(_:)))
        let hold = UILongPressGestureRecognizer(target: self, action: #selector(holdFocus(_:)))
        tap.require(toFail: hold)
        addGestureRecognizer(tap)
        addGestureRecognizer(hold)
        accessibilityIdentifier = "camera-viewfinder"
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    @objc private func tapFocus(_ gesture: UITapGestureRecognizer) {
        guard preview.connection != nil else { return }
        let point = gesture.location(in: self)
        let videoRect = preview.layerRectConverted(fromMetadataOutputRect: CGRect(x: 0, y: 0, width: 1, height: 1))
        guard videoRect.contains(point) else { return }
        focusRequested?(preview.captureDevicePointConverted(fromLayerPoint: point), false)
    }
    @objc private func holdFocus(_ gesture: UILongPressGestureRecognizer) {
        guard gesture.state == .began, preview.connection != nil else { return }
        let point = gesture.location(in: self)
        let videoRect = preview.layerRectConverted(fromMetadataOutputRect: CGRect(x: 0, y: 0, width: 1, height: 1))
        guard videoRect.contains(point) else { return }
        focusRequested?(preview.captureDevicePointConverted(fromLayerPoint: point), true)
    }
    private var lastOrientation: UIInterfaceOrientation?
    var preview: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }
    override func layoutSubviews() {
        super.layoutSubviews()
        let orientation = window?.windowScene?.interfaceOrientation ?? .landscapeRight
        if orientation != lastOrientation {
            lastOrientation = orientation
            DispatchQueue.main.async { self.orientationChanged?(orientation) }
        }
        let angle = CameraRotation.angle(for: orientation)
        if let connection = preview.connection, connection.isVideoRotationAngleSupported(angle) { connection.videoRotationAngle = angle }
        let displayPoint = selectedFocus.map { preview.layerPointConverted(fromCaptureDevicePoint: $0) }
        let normalized = displayPoint.flatMap { point -> CGPoint? in
            guard bounds.width > 0, bounds.height > 0 else { return nil }
            return CGPoint(x: point.x / bounds.width, y: point.y / bounds.height)
        }
        if normalized != lastFocusPosition {
            lastFocusPosition = normalized
            DispatchQueue.main.async { self.focusPositionChanged?(normalized) }
        }
    }
}

struct CameraPreview: UIViewRepresentable {
    let session: AVCaptureSession
    var focusPoint: CGPoint?
    var orientationChanged: (UIInterfaceOrientation) -> Void
    var focusRequested: (CGPoint, Bool) -> Void
    var focusPositionChanged: (CGPoint?) -> Void
    func makeUIView(context: Context) -> PreviewSurface {
        let view = PreviewSurface()
        view.backgroundColor = .black
        view.preview.session = session
        view.orientationChanged = orientationChanged
        view.focusRequested = focusRequested
        view.focusPositionChanged = focusPositionChanged
        // Show the complete camera frame; captured pixels are not cropped in this foundation build.
        view.preview.videoGravity = .resizeAspect
        return view
    }
    func updateUIView(_ uiView: PreviewSurface, context: Context) {
        uiView.selectedFocus = focusPoint
        uiView.setNeedsLayout()
    }
}

private enum CameraStyle {
    static let body = Color(red: 0.075, green: 0.08, blue: 0.08)
    static let panel = Color(red: 0.13, green: 0.14, blue: 0.14)
    static let accent = Color(red: 0.88, green: 0.74, blue: 0.48)
    static let silver = Color(red: 0.90, green: 0.91, blue: 0.88)
}

struct CameraView: View {
    @StateObject private var camera = CameraController()
    @Environment(\.scenePhase) private var phase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @AppStorage("digit.grid") private var grid = false
    @AppStorage("digit.haptics") private var haptics = true
    @State private var cameraPicker = false
    @State private var options = false
    @State private var review = false
    @State private var showStatus = true
    @State private var previewOrientation: UIInterfaceOrientation = .portrait
    @State private var focusDisplayPoint: CGPoint?

    var body: some View {
        GeometryReader { geometry in
            let portrait = geometry.size.height > geometry.size.width
            let cameraLayout = portrait ? AnyLayout(VStackLayout(spacing: 16)) : AnyLayout(HStackLayout(spacing: 16))
            let railLayout = portrait ? AnyLayout(HStackLayout(spacing: 12)) : AnyLayout(VStackLayout(spacing: 12))
            ZStack {
                CameraStyle.body.ignoresSafeArea()
                cameraLayout {
                    (portrait ? AnyLayout(HStackLayout(spacing: 12)) : AnyLayout(VStackLayout(alignment: .leading, spacing: 6))) {
                        Text("Digi").font(.system(size: 15, weight: .semibold, design: .rounded))
                            .tracking(1)
                        Button {
                            options = false
                            cameraPicker = true
                        } label: {
                            VStack(spacing: 2) {
                                Text("G12").font(.system(size: 25, weight: .light, design: .rounded))
                                Image(systemName: "chevron.down").font(.system(size: 9, weight: .semibold))
                            }.frame(minWidth: 44, minHeight: 44)
                        }.buttonStyle(.plain)
                            .accessibilityLabel("Choose camera, G12")
                            .accessibilityIdentifier("camera-picker")
                        if !portrait { Rectangle().fill(CameraStyle.accent).frame(width: 22, height: 2).padding(.top, 5) }
                        Spacer()
                        if camera.captureStudyEnabled {
                            Text("STUDY").font(.system(size: 10, weight: .semibold, design: .monospaced))
                                .foregroundStyle(CameraStyle.accent)
                        }
                        Text(camera.exposureLocked ? "LOCK" : "AUTO").font(.system(size: 11, weight: .semibold, design: .monospaced)).foregroundStyle(CameraStyle.accent)
                        Label(camera.flash.rawValue, systemImage: camera.flash.symbol)
                            .font(.system(size: 10, weight: .medium))
                            .foregroundStyle(camera.flash == .off ? CameraStyle.silver : CameraStyle.accent)
                            .accessibilityLabel("Flash \(camera.flash.rawValue)")
                        Text(portrait ? "3:4 JPEG" : "4:3\nJPEG").font(.system(size: 10, design: .monospaced)).lineSpacing(5).foregroundStyle(.white.opacity(0.6))
                    }.frame(width: portrait ? nil : 58, height: portrait ? 44 : nil, alignment: .leading)
                        .padding(.vertical, portrait ? 0 : 16)

                    ZStack {
                        CameraPreview(session: camera.session, focusPoint: camera.focusPoint,
                                      orientationChanged: { previewOrientation = $0 },
                                      focusRequested: { camera.focus(at: $0, lock: $1) },
                                      focusPositionChanged: { focusDisplayPoint = $0 })
                        if camera.lookEnabled, let frame = camera.renderedPreview {
                            Image(uiImage: UIImage(cgImage: frame, scale: 1, orientation: previewOrientation == .portrait ? .right : previewOrientation == .landscapeLeft ? .down : .up))
                                .resizable().scaledToFit().allowsHitTesting(false)
                        }
                        if grid {
                            GeometryReader { area in
                                Path { path in
                                    for fraction in [CGFloat(1.0 / 3), CGFloat(2.0 / 3)] {
                                        path.move(to: CGPoint(x: area.size.width * fraction, y: 0))
                                        path.addLine(to: CGPoint(x: area.size.width * fraction, y: area.size.height))
                                        path.move(to: CGPoint(x: 0, y: area.size.height * fraction))
                                        path.addLine(to: CGPoint(x: area.size.width, y: area.size.height * fraction))
                                    }
                                }.stroke(.white.opacity(0.38), lineWidth: 0.5)
                            }.allowsHitTesting(false).accessibilityHidden(true)
                        }
                        if camera.focusPoint != nil, let point = focusDisplayPoint {
                            GeometryReader { area in
                                Rectangle().stroke(CameraStyle.accent, lineWidth: 1.5)
                                    .frame(width: 54, height: 54)
                                    .overlay(alignment: .top) {
                                        Text(camera.exposureLocked ? "AE/AF LOCK" : "AF/AE").font(.system(size: 10, weight: .semibold, design: .monospaced))
                                            .foregroundStyle(CameraStyle.accent).offset(y: -16)
                                    }
                                    .position(x: point.x * area.size.width, y: point.y * area.size.height)
                            }.allowsHitTesting(false).accessibilityLabel("Selected focus point")
                        }
                        if showStatus && !camera.status.isEmpty {
                            VStack {
                                Spacer()
                                VStack(spacing: 8) {
                                    Text(camera.status).font(.subheadline).multilineTextAlignment(.center)
                                    if camera.pending && !camera.busy {
                                        Button("Retry save") { camera.save() }
                                            .buttonStyle(.borderedProminent).tint(CameraStyle.accent).foregroundStyle(.black)
                                    }
                                }.padding(12).background(.black.opacity(0.8), in: RoundedRectangle(cornerRadius: 12)).padding(12)
                            }
                        }
                    }
                    .aspectRatio(portrait ? 3.0 / 4 : 4.0 / 3, contentMode: .fit)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                    .overlay(RoundedRectangle(cornerRadius: 10).stroke(.white.opacity(0.12), lineWidth: 1))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)

                    railLayout {
                        Button { changePanel() } label: {
                            Image(systemName: options ? "xmark" : "slider.horizontal.3")
                                .font(.system(size: 18, weight: .medium)).frame(width: 48, height: 48)
                                .background(options ? CameraStyle.accent : CameraStyle.panel, in: Circle())
                                .foregroundStyle(options ? CameraStyle.body : CameraStyle.silver)
                        }.accessibilityLabel(options ? "Close options" : "Camera options")
                        Spacer(minLength: 0)
                        Button(action: takePhoto) {
                            ZStack {
                                Circle().stroke(.white.opacity(0.45), lineWidth: 2).frame(width: 78, height: 78)
                                Circle().fill(LinearGradient(colors: [Color.white, CameraStyle.silver, Color.gray], startPoint: .topLeading, endPoint: .bottomTrailing))
                                    .frame(width: 66, height: 66)
                                Circle().stroke(.white.opacity(0.7), lineWidth: 1).frame(width: 59, height: 59)
                            }.frame(width: 84, height: 84)
                        }.buttonStyle(ShutterPressStyle())
                            .disabled(!camera.ready || camera.busy || camera.pending)
                            .opacity(camera.ready && !camera.busy && !camera.pending ? 1 : 0.4)
                            .accessibilityLabel("Take photo")
                        Spacer(minLength: 0)
                        Button { options = false; review = true } label: {
                            ZStack {
                                RoundedRectangle(cornerRadius: 9).fill(CameraStyle.panel)
                                if let photo = camera.lastPhoto {
                                    Image(uiImage: photo).resizable().scaledToFill()
                                } else {
                                    Image(systemName: "photo").font(.system(size: 19)).foregroundStyle(.white.opacity(0.55))
                                }
                            }.frame(width: 52, height: 44).clipShape(RoundedRectangle(cornerRadius: 9))
                                .overlay(RoundedRectangle(cornerRadius: 9).stroke(.white.opacity(0.3), lineWidth: 1))
                        }.accessibilityLabel("Review last photo")
                    }.frame(width: portrait ? nil : 84, height: portrait ? 84 : nil).padding(.vertical, 10)
                }.padding(.horizontal, 18).padding(.vertical, 12)

                if options {
                    Color.black.opacity(0.25).ignoresSafeArea().onTapGesture { options = false }.accessibilityLabel("Dismiss options")
                    HStack {
                        Spacer()
                        VStack(alignment: .leading, spacing: 0) {
                            HStack {
                                Text("Shooting options").font(.headline)
                                Spacer()
                                Button("Done") { options = false }.foregroundStyle(CameraStyle.accent).frame(minWidth: 44, minHeight: 44)
                            }.padding(.horizontal, 20)
                            ScrollView {
                                VStack(alignment: .leading, spacing: 18) {
                                    Toggle(isOn: $grid) { Label("Framing grid", systemImage: "grid") }
                                    Toggle(isOn: $haptics) { Label("Shutter feedback", systemImage: "hand.tap") }
                                    Divider().overlay(.white.opacity(0.15))
                                    HStack { Text("Exposure"); Spacer(); Text(camera.exposureLocked ? "Locked" : "Auto").foregroundStyle(CameraStyle.accent) }
                                    HStack {
                                        Image(systemName: "sun.min")
                                        Slider(value: Binding(get: { camera.exposureBias }, set: { camera.setBrightness($0) }), in: camera.exposureRange, step: 0.1)
                                            .accessibilityLabel("Brightness")
                                            .disabled(!camera.ready || !camera.exposureSupported || camera.exposureLocked || camera.busy || camera.pending)
                                        Image(systemName: "sun.max")
                                    }
                                    Text(camera.exposureLocked ? "Tap the viewfinder to unlock before adjusting brightness." : "Brightness \(camera.exposureBias, specifier: "%+.1f") EV")
                                        .font(.footnote).foregroundStyle(.secondary)
                                    HStack {
                                        Text(camera.focusPoint == nil ? "Focus: Auto" : "Focus: Hold")
                                        Spacer()
                                        Button("Auto focus") { camera.focus(at: nil) }
                                            .disabled(camera.focusPoint == nil || camera.busy)
                                    }
                                    Text("Tap to focus and meter the light. Touch and hold to lock focus and exposure. Tap again to unlock.")
                                        .font(.footnote).foregroundStyle(.white.opacity(0.7))
                                    VStack(alignment: .leading, spacing: 8) {
                                        Label("Flash", systemImage: "bolt.fill")
                                        Picker("Flash mode", selection: $camera.flash) {
                                            ForEach(PhotoFlash.allCases) { mode in
                                                Text(mode.rawValue).tag(mode).disabled(!camera.supportedFlash.contains(mode))
                                            }
                                        }.pickerStyle(.segmented).accessibilityIdentifier("flash-mode")
                                            .disabled(!camera.ready || camera.busy || camera.pending || camera.supportedFlash.count < 2)
                                        Text(camera.supportedFlash.count < 2 ? "Flash is unavailable on this camera." : "Use On for direct flash portraits. Auto lets the camera decide.")
                                            .font(.footnote).foregroundStyle(.white.opacity(0.7))
                                    }
                                    Divider().overlay(.white.opacity(0.15))
                                    Toggle("Capture study", isOn: Binding(
                                        get: { camera.captureStudyEnabled },
                                        set: { camera.setCaptureStudyEnabled($0) }
                                    ))
                                    .disabled(camera.busy || camera.pending)
                                    Text("Saves an original, the finished photo, and any skin mask together for local camera testing.")
                                        .font(.footnote).foregroundStyle(.white.opacity(0.7))
                                    if camera.captureStudyEnabled {
                                        Text(camera.studyFeedback).font(.footnote).foregroundStyle(CameraStyle.accent)
                                            .accessibilityIdentifier("study-result")
                                    }
                                    Label("Photos save automatically", systemImage: "checkmark.circle").font(.footnote).foregroundStyle(.white.opacity(0.7))
                                    Button("Camera & Photos permissions", action: openSettings).font(.subheadline).foregroundStyle(CameraStyle.accent).frame(minHeight: 44)
                                }.padding(20)
                            }
                        }.frame(width: min(360, geometry.size.width - 48))
                            .background(CameraStyle.panel, in: RoundedRectangle(cornerRadius: 22))
                            .overlay(RoundedRectangle(cornerRadius: 22).stroke(.white.opacity(0.14), lineWidth: 1))
                            .frame(maxHeight: portrait ? 360 : .infinity)
                            .padding(.trailing, portrait ? 18 : 112).padding(.vertical, 12)
                    }.transition(.opacity)
                }
                if review {
                    CameraStyle.body.ignoresSafeArea()
                    VStack(spacing: 8) {
                        HStack {
                            Text("Last photo").font(.headline)
                            Spacer()
                            Button("Done") { review = false }.foregroundStyle(CameraStyle.accent).frame(minWidth: 44, minHeight: 44)
                        }
                        if let photo = camera.lastPhoto {
                            Image(uiImage: photo).resizable().scaledToFit().frame(maxWidth: .infinity, maxHeight: .infinity)
                            Text(camera.photoLookApplied ? "G12 Look" : "Original").font(.caption).foregroundStyle(CameraStyle.accent)
                            Text(camera.pending ? "Not saved yet. Return to the camera to retry." : camera.busy ? "Saving…" : "Saved to Photos")
                                .font(.footnote).foregroundStyle(.white.opacity(0.7))
                        } else {
                            Spacer()
                            Image(systemName: "photo.on.rectangle").font(.system(size: 32)).foregroundStyle(CameraStyle.accent)
                            Text("Your next moment starts here.").font(.headline)
                            Text("Take a photo to see it here.").font(.subheadline).foregroundStyle(.white.opacity(0.65))
                            Spacer()
                        }
                    }.padding(.horizontal, 24).padding(.vertical, 10)
                }
            }.foregroundStyle(CameraStyle.silver).tint(CameraStyle.accent)
        }
        .sheet(isPresented: $cameraPicker) {
            CameraPickerView()
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
        .preferredColorScheme(.dark)
        .statusBarHidden()
        .onAppear { camera.start() }
        .onChange(of: phase) { _, newPhase in if newPhase == .active { camera.start() } else { camera.stop() } }
        .task(id: camera.status) {
            showStatus = true
            if camera.status.hasPrefix("Saved to Photos") {
                try? await Task.sleep(for: .seconds(2))
                if !Task.isCancelled { showStatus = false }
            }
        }
    }

    private func takePhoto() {
        options = false
        if haptics { UIImpactFeedbackGenerator(style: .light).impactOccurred() }
        let orientation = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first?.interfaceOrientation
        camera.capture(angle: CameraRotation.angle(for: orientation ?? .portrait))
    }
    private func changePanel() {
        if haptics { UISelectionFeedbackGenerator().selectionChanged() }
        withAnimation(reduceMotion ? nil : .easeOut(duration: 0.18)) { options.toggle() }
    }
    private func openSettings() {
        if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
    }
}

private struct CameraPickerView: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 12) {
                    cameraRow("G12", detail: "Your everyday classic", available: true)
                    cameraRow("S95", detail: "Coming soon", available: false)
                    cameraRow("G7 X", detail: "Coming soon", available: false)
                }.padding(20)
            }
            .background(CameraStyle.body)
            .navigationTitle("Your cameras")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }.tint(CameraStyle.accent)
                }
            }
        }.preferredColorScheme(.dark)
    }

    private func cameraRow(_ name: String, detail: String, available: Bool) -> some View {
        Button { dismiss() } label: {
            HStack(spacing: 16) {
                Image(systemName: "camera").font(.system(size: 24))
                    .foregroundStyle(available ? CameraStyle.accent : CameraStyle.silver.opacity(0.5))
                VStack(alignment: .leading, spacing: 4) {
                    Text(name).font(.title3.weight(.semibold))
                    Text(detail).font(.subheadline).foregroundStyle(.secondary)
                }
                Spacer()
                if available {
                    Image(systemName: "checkmark.circle.fill").foregroundStyle(CameraStyle.accent)
                }
            }.foregroundStyle(CameraStyle.silver)
                .padding(18).frame(maxWidth: .infinity, alignment: .leading)
                .background(CameraStyle.panel, in: RoundedRectangle(cornerRadius: 16))
        }.buttonStyle(.plain).disabled(!available)
            .accessibilityLabel(available ? "\(name), selected" : "\(name), coming soon")
            .accessibilityIdentifier("camera-\(name)")
    }
}

private struct ShutterPressStyle: ButtonStyle {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.scaleEffect(configuration.isPressed ? 0.94 : 1)
            .animation(reduceMotion ? nil : .easeOut(duration: 0.12), value: configuration.isPressed)
    }
}
