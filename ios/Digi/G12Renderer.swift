import Foundation
import CoreImage
import ImageIO
import UniformTypeIdentifiers

/// Versioned, device-specific aesthetic profile. Cube coordinates and values are linear sRGB.
final class G12Renderer {
    private let context = CIContext(options: [.workingColorSpace: CGColorSpace(name: CGColorSpace.linearSRGB)!, .cacheIntermediates: false])
    private let cube: Data
    private let dimension: Int
    private let outputSpace = CGColorSpace(name: CGColorSpace.sRGB)!

    init?(directory: URL = Bundle.main.bundleURL) {
        guard let metadata = try? Data(contentsOf: directory.appendingPathComponent("G12-iPhone17Pro.json")),
              let profile = try? JSONSerialization.jsonObject(with: metadata) as? [String: Any],
              let size = profile["dimension"] as? Int, size == 65,
              let data = try? Data(contentsOf: directory.appendingPathComponent("G12-iPhone17Pro.cube.bin")),
              data.count == size * size * size * 4 * MemoryLayout<Float>.size else { return nil }
        dimension = size
        cube = data
    }

    func render(_ input: CIImage, maxDimension: CGFloat? = nil) -> CGImage? {
        var image = input
        if let limit = maxDimension {
            let scale = min(1, limit / max(image.extent.width, image.extent.height))
            image = image.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        }
        guard let filter = CIFilter(name: "CIColorCube", parameters: [kCIInputImageKey: image, "inputCubeDimension": dimension, "inputCubeData": cube]),
              let result = filter.outputImage else { return nil }
        return context.createCGImage(result, from: image.extent, format: .RGBA8, colorSpace: outputSpace)
    }

    func jpeg(_ data: Data) -> Data? {
        guard let input = CIImage(data: data, options: [.applyOrientationProperty: true]),
              let rendered = render(input),
              let original = CGImageSourceCreateWithData(data as CFData, nil) else { return nil }
        var properties = CGImageSourceCopyPropertiesAtIndex(original, 0, nil) as? [CFString: Any] ?? [:]
        properties[kCGImagePropertyOrientation] = 1
        properties[kCGImagePropertyPixelWidth] = rendered.width
        properties[kCGImagePropertyPixelHeight] = rendered.height
        properties[kCGImageDestinationLossyCompressionQuality] = 0.96
        var tiff = properties[kCGImagePropertyTIFFDictionary] as? [CFString: Any] ?? [:]
        tiff[kCGImagePropertyTIFFOrientation] = 1
        tiff[kCGImagePropertyTIFFSoftware] = "Digi G12-inspired Classic v2"
        properties[kCGImagePropertyTIFFDictionary] = tiff
        var exif = properties[kCGImagePropertyExifDictionary] as? [CFString: Any] ?? [:]
        exif[kCGImagePropertyExifPixelXDimension] = rendered.width
        exif[kCGImagePropertyExifPixelYDimension] = rendered.height
        properties[kCGImagePropertyExifDictionary] = exif
        let output = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(output, UTType.jpeg.identifier as CFString, 1, nil) else { return nil }
        CGImageDestinationAddImage(destination, rendered, properties as CFDictionary)
        guard CGImageDestinationFinalize(destination) else { return nil }
        return output as Data
    }
}
