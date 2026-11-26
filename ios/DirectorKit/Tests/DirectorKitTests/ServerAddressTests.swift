import XCTest
@testable import DirectorKit

final class ServerAddressTests: XCTestCase {
    private func s(_ text: String) -> String? { ServerAddress.url(from: text)?.absoluteString }

    func testPrivateAndLocalHostsDefaultToHTTP() {
        XCTAssertEqual(s("192.168.1.20:8787"), "http://192.168.1.20:8787")
        XCTAssertEqual(s("10.0.0.142:8787"), "http://10.0.0.142:8787")
        XCTAssertEqual(s("172.20.5.9:8787"), "http://172.20.5.9:8787")
        XCTAssertEqual(s("100.79.9.41:8787"), "http://100.79.9.41:8787")  // Tailscale
        XCTAssertEqual(s("169.254.1.2:8787"), "http://169.254.1.2:8787")
        XCTAssertEqual(s("localhost:8787"), "http://localhost:8787")
        XCTAssertEqual(s("my-mac.local:8787"), "http://my-mac.local:8787")
        XCTAssertEqual(s("my-mac:8787"), "http://my-mac:8787")
        XCTAssertEqual(s("[fe80::1]:8787"), "http://[fe80::1]:8787")
    }

    func testOtherHostsDefaultToHTTPS() {
        XCTAssertEqual(s("host.tailnet.ts.net"), "https://host.tailnet.ts.net")
        XCTAssertEqual(s("example.com:8443"), "https://example.com:8443")
        XCTAssertEqual(s("8.8.8.8:8787"), "https://8.8.8.8:8787")  // a public IP is not private
        XCTAssertEqual(s("172.32.0.1:8787"), "https://172.32.0.1:8787")  // just outside 172.16/12
        XCTAssertEqual(s("100.128.0.1:8787"), "https://100.128.0.1:8787")  // just outside 100.64/10
        XCTAssertEqual(s("[2001:db8::1]:8787"), "https://[2001:db8::1]:8787")
    }

    func testAnExplicitSchemeIsKept() {
        XCTAssertEqual(s("https://192.168.1.20:8787"), "https://192.168.1.20:8787")
        XCTAssertEqual(s("HTTP://192.168.1.20:8787"), "HTTP://192.168.1.20:8787")
        XCTAssertEqual(s("  https://host.ts.net/ \n"), "https://host.ts.net/")
        XCTAssertTrue(ServerAddress.isPlainHTTP(ServerAddress.url(from: "HTTP://10.0.0.1")!))
        XCTAssertFalse(ServerAddress.isPlainHTTP(ServerAddress.url(from: "host.ts.net")!))
    }

    func testOtherSchemesAndJunkAreRefused() {
        for bad in ["", "   ", "ftp://host", "file:///etc/passwd", "javascript:alert(1)", "192.168.1.20 :8787", "http://", "https://:8787"] {
            XCTAssertNil(s(bad), bad)
        }
    }
}
