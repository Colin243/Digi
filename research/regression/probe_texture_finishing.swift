// Full-resolution finishing experiment on already-rendered Digi JPEGs.
// No G12 LUT is reapplied. Parameters are experimental, not camera calibration.
import Foundation
import CoreImage
import ImageIO
import Vision

@main struct TextureFinishingProbe {
    static func main() throws {
        let args = CommandLine.arguments
        guard args.count >= 3 else { fatalError("Usage: probe OUTPUT INPUT.jpg [INPUT.jpg ...]") }
        let root = URL(fileURLWithPath: args[1], isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let space = CGColorSpace(name: CGColorSpace.sRGB)!
        let context = CIContext(options: [.workingColorSpace: CGColorSpace(name: CGColorSpace.linearSRGB)!, .cacheIntermediates: false])
        // Denoise chroma only; retain original linear-light luminance and texture.
        let kernel = CIColorKernel(source: """
        kernel vec4 finish(__sample src, __sample nr, float chroma, float shoulder) {
            vec3 w = vec3(0.2126, 0.7152, 0.0722);
            float y = dot(src.rgb, w);
            if (min(src.r, min(src.g, src.b)) < 0.04) { return src; }
            vec3 delta = nr.rgb - src.rgb;
            delta -= vec3(dot(delta, w));
            // Limit the entire chroma vector together to avoid colored speckles
            // caused by independent clipping in near-black or saturated pixels.
            vec3 d = chroma * smoothstep(0.04, 0.10, min(src.r, min(src.g, src.b))) * delta;
            float t = 1.0;
            t = min(t, d.r < 0.0 ? src.r / max(-d.r, 0.000001) : (1.0-src.r) / max(d.r, 0.000001));
            t = min(t, d.g < 0.0 ? src.g / max(-d.g, 0.000001) : (1.0-src.g) / max(d.g, 0.000001));
            t = min(t, d.b < 0.0 ? src.b / max(-d.b, 0.000001) : (1.0-src.b) / max(d.b, 0.000001));
            vec3 rgb = src.rgb + clamp(t, 0.0, 1.0) * d;
            float h = max(y - 0.55, 0.0);
            float outY = y - shoulder * h * h;
            rgb *= outY / max(y, 0.000001);
            return vec4(rgb, src.a); // Preserve extended-range input until output color conversion.
        }
        """)!
        var report = [[String: Any]]()
        for path in args.dropFirst(2) {
            try autoreleasepool {
                let url = URL(fileURLWithPath: path)
                let stem = url.deletingPathExtension().lastPathComponent
                let data = try Data(contentsOf: url)
                let input = CIImage(data: data, options: [.applyOrientationProperty: true])!
                let source = CGImageSourceCreateWithData(data as CFData, nil)!
                let props = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any] ?? [:]
                let exif = props[kCGImagePropertyExifDictionary] as? [CFString: Any] ?? [:]
                let flash = (exif[kCGImagePropertyExifFlash] as? NSNumber).map { ($0.intValue & 1) != 0 }
                let faces = VNDetectFaceRectanglesRequest()
                try VNImageRequestHandler(ciImage: input).perform([faces])
                let boxes = (faces.results ?? []).map { ["x": $0.boundingBox.minX, "y": $0.boundingBox.minY, "width": $0.boundingBox.width, "height": $0.boundingBox.height] }
                let nr = input.clampedToExtent().applyingFilter("CINoiseReduction", parameters: ["inputNoiseLevel": 0.015, "inputSharpness": 0.0]).cropped(to: input.extent)
                var timings = [String: Double]()
                for (name, chroma, shoulder) in [("baseline", 0.0, 0.0), ("chroma", 0.35, 0.0), ("highlights", 0.0, 0.2), ("combined", 0.35, 0.2)] {
                    let start = Date()
                    let output = name == "baseline" ? input : kernel.apply(extent: input.extent, arguments: [input, nr, chroma, shoulder])!
                    try context.writePNGRepresentation(of: output, to: root.appendingPathComponent("\(stem)-\(name).png"), format: .RGBA8, colorSpace: space)
                    timings[name] = Date().timeIntervalSince(start)
                }
                report.append(["input": path, "stem": stem, "width": Int(input.extent.width), "height": Int(input.extent.height), "faces": boxes, "flash_fired": flash.map { $0 as Any } ?? NSNull(), "skin_matte_present": CGImageSourceCopyAuxiliaryDataInfoAtIndex(source, 0, kCGImageAuxiliaryDataTypeSemanticSegmentationSkinMatte) != nil, "mac_render_and_png_seconds": timings])
            }
        }
        let data = try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
        try data.write(to: root.appendingPathComponent("report.json"))
        print(String(data: data, encoding: .utf8)!)
    }
}
