import Foundation
import Security
import DirectorKit

/// Where the app finds the Director server, and which engines the user allows.
/// The client key is a secret issued by `photo-ai server keygen`; it lives in the Keychain, never in
/// UserDefaults or the repository.
enum DirectorKeychain {
    private static let service = "com.colin.digit.gift.director"
    private static let account = "server-api-key"

    static func read() -> String? {
        var item: CFTypeRef?
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
            kSecAttrAccount as String: account, kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess, let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    @discardableResult
    static func write(_ key: String) -> Bool {
        let base: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: account,
        ]
        SecItemDelete(base as CFDictionary)
        let trimmed = key.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return true }  // an empty field clears the key
        var add = base
        add[kSecValueData as String] = Data(trimmed.utf8)
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        return SecItemAdd(add as CFDictionary, nil) == errSecSuccess
    }
}

enum DirectorDefaults {
    static let serverURL = "digi.director.serverURL"
    static let preference = "digi.director.preference"

    static func configuration() -> OnlineEngine.Configuration? {
        guard let text = UserDefaults.standard.string(forKey: serverURL)?.trimmingCharacters(in: .whitespaces),
              !text.isEmpty, let key = DirectorKeychain.read(), !key.isEmpty else { return nil }
        let withScheme = text.contains("://") ? text : "http://" + text
        guard let url = URL(string: withScheme), url.host != nil else { return nil }
        return OnlineEngine.Configuration(baseURL: url, apiKey: key)
    }

    static func userPreference() -> UserEnginePreference {
        UserEnginePreference(rawValue: UserDefaults.standard.string(forKey: preference) ?? "") ?? .automatic
    }
}
