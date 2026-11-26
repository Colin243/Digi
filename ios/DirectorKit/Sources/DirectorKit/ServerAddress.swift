import Foundation

/// Turns what the user typed as the Director server address into a base URL.
///
/// - Only `http` and `https` are accepted; `ftp://`, `file://` and the like give nil.
/// - With no scheme, a private or local host (home and campus LAN addresses, Tailscale's 100.64.0.0/10, `localhost`,
///   `*.local`, single-word names) gets `http://`, and everything else gets `https://`, so a typed domain such as a
///   Tailscale `*.ts.net` name or a public host is encrypted by default and the API key is never sent in the clear
///   to an address that is not on a private network.
/// - A scheme the user types is kept as typed (iOS itself refuses plain HTTP to public hosts).
public enum ServerAddress {
    public static func url(from text: String) -> URL? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !trimmed.contains(where: { $0.isWhitespace }) else { return nil }
        let full: String
        if let range = trimmed.range(of: "://") {
            let scheme = trimmed[..<range.lowerBound].lowercased()
            guard scheme == "http" || scheme == "https" else { return nil }
            full = trimmed
        } else {
            guard let host = URLComponents(string: "//" + trimmed)?.host, !host.isEmpty else { return nil }
            full = (isPrivateHost(host) ? "http://" : "https://") + trimmed
        }
        guard let url = URL(string: full), let host = url.host, !host.isEmpty else { return nil }
        return url
    }

    /// True when the address is plain `http`, so the key and photos are not encrypted on the way.
    public static func isPlainHTTP(_ url: URL) -> Bool { url.scheme?.lowercased() == "http" }

    /// Hosts that are on this device or a private network.
    public static func isPrivateHost(_ rawHost: String) -> Bool {
        let host = rawHost.trimmingCharacters(in: CharacterSet(charactersIn: "[]")).lowercased()
        if host == "localhost" || host.hasSuffix(".local") { return true }
        if let v4 = ipv4(host) { return isPrivateIPv4(v4) }
        if host.contains(":") {  // an IPv6 literal: loopback, link-local fe80::/10, unique local fc00::/7
            return host == "::1" || host.hasPrefix("fe80:") || host.hasPrefix("fc") || host.hasPrefix("fd")
        }
        return !host.contains(".")  // an unqualified name such as "my-mac"
    }

    private static func ipv4(_ host: String) -> [Int]? {
        let parts = host.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 4 else { return nil }
        let octets = parts.compactMap { Int($0) }
        return octets.count == 4 && octets.allSatisfy({ (0...255).contains($0) }) ? octets : nil
    }

    private static func isPrivateIPv4(_ o: [Int]) -> Bool {
        switch (o[0], o[1]) {
        case (10, _), (127, _), (192, 168), (169, 254): return true
        case (172, 16...31): return true
        case (100, 64...127): return true  // carrier-grade NAT range, which Tailscale uses
        default: return false
        }
    }
}
