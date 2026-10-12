// Offline Core Image finishing study. Not a G12-calibrated model or app default.
import Foundation
import CoreImage
import ImageIO
import UniformTypeIdentifiers

@main struct FinishingProbe {
    static func main() throws {
        let root = URL(fileURLWithPath: "output/finishing-study", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let context = CIContext(options: [.workingColorSpace: CGColorSpace(name: CGColorSpace.linearSRGB)!, .cacheIntermediates: false])
        let space = CGColorSpace(name: CGColorSpace.sRGB)!
        let renderer = G12Renderer(directory: URL(fileURLWithPath: "ios/Digi"))!
        let rows = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: "output/portrait-model/faces.json"))) as! [[String: Any]]
        var report = [[String: Any]]()
        for (index, row) in rows.enumerated() {
            try autoreleasepool {
                let path = row["file"] as! String
                let data = try Data(contentsOf: URL(fileURLWithPath: path))
                let source = CGImageSourceCreateWithData(data as CFData, nil)!
                let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any] ?? [:]
                let exif = properties[kCGImagePropertyExifDictionary] as? [CFString: Any] ?? [:]
                let flash = (exif[kCGImagePropertyExifFlash] as? NSNumber).map { ($0.intValue & 1) != 0 }
                let skinAux = CGImageSourceCopyAuxiliaryDataInfoAtIndex(source, 0, kCGImageAuxiliaryDataTypeSemanticSegmentationSkinMatte) != nil
                let input = CIImage(data: data, options: [.applyOrientationProperty: true])!
                let classic = CIImage(cgImage: renderer.render(input)!)
                let start = Date()
                // Conservative experimental values, not learned Canon parameters.
                let filtered = classic.applyingFilter("CINoiseReduction", parameters: ["inputNoiseLevel": 0.015, "inputSharpness": 0.15]).cropped(to: classic.extent)
                let finished = filtered.applyingFilter("CIDissolveTransition", parameters: ["inputTargetImage": classic, "inputTime": 0.65]).cropped(to: classic.extent)
                try context.writePNGRepresentation(of: classic, to: root.appendingPathComponent("classic-\(index).png"), format: .RGBA8, colorSpace: space)
                try context.writePNGRepresentation(of: finished, to: root.appendingPathComponent("gentle-\(index).png"), format: .RGBA8, colorSpace: space)
                report.append(["file": path, "split": row["split"]!, "embedded_skin_mask": skinAux,
                               "flash_fired": flash.map { $0 as Any } ?? NSNull(), "seconds_render_and_export": Date().timeIntervalSince(start),
                               "width": Int(classic.extent.width), "height": Int(classic.extent.height)])
            }
        }
        let data = try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
        try data.write(to: root.appendingPathComponent("report.json"))
        print(String(data: data, encoding: .utf8)!)
    }
}
