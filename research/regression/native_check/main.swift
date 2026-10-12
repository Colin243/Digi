import Foundation
import CoreImage
import ImageIO
let renderer = G12Renderer(directory: URL(fileURLWithPath: "ios/Digi"))!
for name in ["IMG_9707", "IMG_9708"] {
    let source = try Data(contentsOf: URL(fileURLWithPath: "/Users/colin/Downloads/\(name).JPG"))
    let start = Date()
    guard let result = renderer.jpeg(source) else { fatalError("JPEG render failed") }
    try result.write(to: URL(fileURLWithPath: "output/g12-native/\(name).jpg"))
    let image = CGImageSourceCreateWithData(result as CFData, nil)!
    let p = CGImageSourceCopyPropertiesAtIndex(image, 0, nil)! as NSDictionary
    print(name, p[kCGImagePropertyPixelWidth]!, p[kCGImagePropertyPixelHeight]!, p[kCGImagePropertyOrientation]!, "seconds", Date().timeIntervalSince(start))
}
