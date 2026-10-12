import Foundation
import Vision
import ImageIO
let source = URL(fileURLWithPath: "output/portrait-audit/existing-iphone-portraits.json")
let rows = try JSONSerialization.jsonObject(with: Data(contentsOf: source)) as! [[String:Any]]
var result = [[String:Any]]()
for row in rows {
    let path = row["analysis_file"] as! String
    let request = VNDetectFaceRectanglesRequest()
    try VNImageRequestHandler(url: URL(fileURLWithPath:path), options: [:]).perform([request])
    let faces = (request.results ?? []).map { face in
        ["x": face.boundingBox.minX, "y": face.boundingBox.minY, "width": face.boundingBox.width, "height": face.boundingBox.height, "confidence": CGFloat(face.confidence)]
    }
    result.append(["file":path,"faces":faces,"split":row["split"] as! String])
}
try JSONSerialization.data(withJSONObject:result,options:[.prettyPrinted,.sortedKeys]).write(to:URL(fileURLWithPath:"output/portrait-model/faces.json"))
print("Reviewed \(result.count) portrait candidates")
