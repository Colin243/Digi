// Offline feasibility probe. Masks are not skin labels or camera calibration.
import Foundation
import Vision
import CoreImage
import ImageIO
import UniformTypeIdentifiers

let rows = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: "output/portrait-model/faces.json"))) as! [[String:Any]]
let context = CIContext(options: [.cacheIntermediates: false])
var report = [[String:Any]]()
for (index, row) in rows.enumerated() {
    let path = row["file"] as! String
    let request = VNGeneratePersonSegmentationRequest()
    request.qualityLevel = .accurate
    request.outputPixelFormat = kCVPixelFormatType_OneComponent8
    let start = Date()
    do {
        try VNImageRequestHandler(url: URL(fileURLWithPath: path), options: [:]).perform([request])
        guard let buffer = request.results?.first?.pixelBuffer else {
            report.append(["file": path, "status": "no-mask"]); continue
        }
        let elapsed = Date().timeIntervalSince(start)
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        let width = CVPixelBufferGetWidth(buffer), height = CVPixelBufferGetHeight(buffer)
        let stride = CVPixelBufferGetBytesPerRow(buffer)
        let bytes = CVPixelBufferGetBaseAddress(buffer)!.assumingMemoryBound(to: UInt8.self)
        var foreground = 0, uncertain = 0
        for y in 0..<height { for x in 0..<width {
            let value = bytes[y * stride + x]
            if value >= 128 { foreground += 1 }
            if value > 25 && value < 230 { uncertain += 1 }
        }}
        CVPixelBufferUnlockBaseAddress(buffer, .readOnly)
        let image = CIImage(cvPixelBuffer: buffer)
        let url = URL(fileURLWithPath: "output/portrait-segmentation/mask-\(index).png")
        try context.writePNGRepresentation(of: image, to: url, format: .L8, colorSpace: CGColorSpaceCreateDeviceGray())
        report.append(["file": path, "split": row["split"]!, "mask": url.path, "seconds": elapsed,
                       "width": width, "height": height,
                       "foreground_fraction": Double(foreground) / Double(width * height),
                       "uncertain_fraction": Double(uncertain) / Double(width * height), "status": "generated"])
    } catch { report.append(["file": path, "status": "error", "error": error.localizedDescription]) }
}
let data = try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
try data.write(to: URL(fileURLWithPath: "output/portrait-segmentation/report.json"))
print(String(data: data, encoding: .utf8)!)
