@preconcurrency import AVFoundation
import Foundation

/// A real capture session (back wide camera, .photo preset, video data output) that the
/// benchmark stops before inference and restarts after, timing how long capture takes to
/// deliver frames again. This is the pause/resume the Digi camera screen would do.
final class CameraProbe: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate, @unchecked Sendable {
    let session = AVCaptureSession()
    static let presetName = "photo"
    private let sessionQueue = DispatchQueue(label: "bench.camera.session")
    private let frameQueue = DispatchQueue(label: "bench.camera.frames")
    private let lock = NSLock()
    private var frames = 0
    private var waitingSince: Double?
    private var firstFrameAt: Double?
    private(set) var configured = false
    private(set) var configureError: String?
    var onEvent: ((String, String) -> Void)?

    var frameCount: Int { lock.withLock { frames } }

    private func beginWaiting(at t: Double) { lock.withLock { waitingSince = t; firstFrameAt = nil } }
    private func endWaiting() { lock.withLock { waitingSince = nil } }
    private func firstFrameTime() -> Double? { lock.withLock { firstFrameAt } }

    func configure() async {
        let granted = await AVCaptureDevice.requestAccess(for: .video)
        guard granted else { configureError = "camera permission denied"; return }
        guard let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back) else {
            configureError = "no back camera (simulator?)"
            return
        }
        await withCheckedContinuation { (cont: CheckedContinuation<Void, Never>) in
            sessionQueue.async {
                defer { cont.resume() }
                do {
                    self.session.beginConfiguration()
                    self.session.sessionPreset = .photo
                    let input = try AVCaptureDeviceInput(device: device)
                    guard self.session.canAddInput(input) else { throw NSError(domain: "camera", code: 1) }
                    self.session.addInput(input)
                    let out = AVCaptureVideoDataOutput()
                    out.alwaysDiscardsLateVideoFrames = true
                    out.setSampleBufferDelegate(self, queue: self.frameQueue)
                    guard self.session.canAddOutput(out) else { throw NSError(domain: "camera", code: 2) }
                    self.session.addOutput(out)
                    self.session.commitConfiguration()
                    self.configured = true
                } catch {
                    self.session.commitConfiguration()
                    self.configureError = "camera configuration failed: \(error.localizedDescription)"
                }
            }
        }
        let nc = NotificationCenter.default
        nc.addObserver(forName: AVCaptureSession.wasInterruptedNotification, object: session, queue: nil) { [weak self] n in
            let reason = (n.userInfo?[AVCaptureSessionInterruptionReasonKey] as? Int).map(String.init) ?? "?"
            self?.onEvent?("camera_interrupted", "reason \(reason)")
        }
        nc.addObserver(forName: AVCaptureSession.interruptionEndedNotification, object: session, queue: nil) { [weak self] _ in
            self?.onEvent?("camera_interruption_ended", "")
        }
        nc.addObserver(forName: AVCaptureSession.runtimeErrorNotification, object: session, queue: nil) { [weak self] n in
            let err = (n.userInfo?[AVCaptureSessionErrorKey] as? NSError)?.localizedDescription ?? "?"
            self?.onEvent?("camera_error", err)
        }
    }

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        let t = now()
        lock.withLock {
            frames += 1
            if waitingSince != nil, firstFrameAt == nil { firstFrameAt = t }
        }
    }

    /// Returns stopRunning() duration.
    func stop() async -> Double {
        await withCheckedContinuation { cont in
            sessionQueue.async {
                let t0 = now()
                if self.session.isRunning { self.session.stopRunning() }
                cont.resume(returning: now() - t0)
            }
        }
    }

    /// Starts capture and waits for the first frame. Returns (startRunning() duration,
    /// request -> first frame, or nil after `timeout`).
    func start(timeout: Double = 5) async -> (call: Double, firstFrame: Double?) {
        let t0 = now()
        beginWaiting(at: t0)
        let call: Double = await withCheckedContinuation { cont in
            sessionQueue.async {
                let s = now()
                if !self.session.isRunning { self.session.startRunning() }
                cont.resume(returning: now() - s)
            }
        }
        while now() - t0 < timeout {
            if let f = firstFrameTime() {
                endWaiting()
                return (call, f - t0)
            }
            try? await Task.sleep(nanoseconds: 2_000_000)
        }
        endWaiting()
        return (call, nil)
    }
}
