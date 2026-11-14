import Foundation

/// A multipart/form-data body (RFC 7578), built in memory. Images are already downscaled
/// (about 1024 px JPEG), so a request is small enough to hold as `Data`.
public struct MultipartBody: Equatable, Sendable {
    public enum Part: Equatable, Sendable {
        case field(name: String, value: String)
        case file(name: String, filename: String, contentType: String, data: Data)
    }

    public let boundary: String
    public private(set) var parts: [Part] = []

    public init(boundary: String = "digi-" + UUID().uuidString) { self.boundary = boundary }

    public mutating func addField(_ name: String, _ value: String) {
        parts.append(.field(name: name, value: value))
    }

    public mutating func addFile(_ name: String, filename: String, contentType: String = "image/jpeg", data: Data) {
        parts.append(.file(name: name, filename: filename, contentType: contentType, data: data))
    }

    public var contentType: String { "multipart/form-data; boundary=\(boundary)" }

    public var data: Data {
        var out = Data()
        func put(_ s: String) { out.append(Data(s.utf8)) }
        for part in parts {
            put("--\(boundary)\r\n")
            switch part {
            case let .field(name, value):
                put("Content-Disposition: form-data; name=\"\(Self.quote(name))\"\r\n\r\n")
                put(value)
            case let .file(name, filename, type, bytes):
                put("Content-Disposition: form-data; name=\"\(Self.quote(name))\"; filename=\"\(Self.quote(filename))\"\r\n")
                put("Content-Type: \(type)\r\n\r\n")
                out.append(bytes)
            }
            put("\r\n")
        }
        put("--\(boundary)--\r\n")
        return out
    }

    /// Header parameter values can't contain quotes or line breaks.
    private static func quote(_ s: String) -> String {
        s.replacingOccurrences(of: "\"", with: "%22").replacingOccurrences(of: "\r", with: "%0D")
            .replacingOccurrences(of: "\n", with: "%0A")
    }
}
