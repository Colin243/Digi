// Reads exported originals through ImageIO. Never opens the Photos library database.
import Foundation
import ImageIO
import UniformTypeIdentifiers
let args = CommandLine.arguments
let input = URL(fileURLWithPath: args[1], isDirectory: true)
let output = URL(fileURLWithPath: args[2], isDirectory: true)
try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
let files = try FileManager.default.contentsOfDirectory(at: input, includingPropertiesForKeys: nil).sorted { $0.path < $1.path }
var rows: [[String: Any]] = []
for url in files {
 guard let source = CGImageSourceCreateWithURL(url as CFURL, nil), let p = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [String: Any] else { continue }
 let tiff = p[kCGImagePropertyTIFFDictionary as String] as? [String: Any] ?? [:]
 let exif = p[kCGImagePropertyExifDictionary as String] as? [String: Any] ?? [:]
 let model = tiff[kCGImagePropertyTIFFModel as String] as? String ?? "unknown"
 var row: [String: Any] = ["file": url.lastPathComponent, "model": model, "width": p[kCGImagePropertyPixelWidth as String] ?? 0, "height": p[kCGImagePropertyPixelHeight as String] ?? 0, "included": model.lowercased().contains("iphone")]
 for key in ["ISOSpeedRatings", "ExposureTime", "FNumber", "LensModel", "Flash", "DateTimeOriginal"] { if let v = exif[key] { row[key] = v } }
 if model.lowercased().contains("iphone") {
  let options: [CFString: Any] = [kCGImageSourceCreateThumbnailFromImageAlways: true, kCGImageSourceCreateThumbnailWithTransform: true, kCGImageSourceThumbnailMaxPixelSize: 1200]
  if let image = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) {
   let destURL = output.appendingPathComponent(url.lastPathComponent + ".jpg")
   if let dest = CGImageDestinationCreateWithURL(destURL as CFURL, UTType.jpeg.identifier as CFString, 1, nil) {
    CGImageDestinationAddImage(dest, image, [kCGImageDestinationLossyCompressionQuality: 0.95] as CFDictionary)
    row["thumbnail_created"] = CGImageDestinationFinalize(dest)
    row["analysis_file"] = destURL.path
   }
  }
 }
 rows.append(row)
}
let data = try JSONSerialization.data(withJSONObject: rows, options: [.prettyPrinted, .sortedKeys])
try data.write(to: output.appendingPathComponent("manifest.json"))
print("Inspected \(rows.count); iPhone \(rows.filter { $0["included"] as? Bool == true }.count)")
