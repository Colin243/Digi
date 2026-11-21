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
        guard let url = ServerAddress.url(from: text) else { return nil }
        return OnlineEngine.Configuration(baseURL: url, apiKey: key)
    }

    static let priority = "digi.director.priority"

    /// Best results unless the user chooses otherwise: speed is opt-in.
    static func userPriority() -> DirectorPriority {
        DirectorPriority(rawValue: UserDefaults.standard.string(forKey: priority) ?? "") ?? .bestResults
    }

    static func userPreference() -> UserEnginePreference {
        UserEnginePreference(rawValue: UserDefaults.standard.string(forKey: preference) ?? "") ?? .automatic
    }
}

/// Planning runs kept on the phone (newest last), for the quality-versus-speed readout.
enum RunLogStore {
    private static let key = "digi.director.runlog"

    static func load() -> [RunRecord] {
        guard let data = UserDefaults.standard.data(forKey: key) else { return [] }
        return (try? JSONDecoder().decode([RunRecord].self, from: data)) ?? []
    }

    static func save(_ records: [RunRecord]) {
        if let data = try? JSONEncoder().encode(records) { UserDefaults.standard.set(data, forKey: key) }
    }

    static func append(_ record: RunRecord) { save(RunLog.appended(load(), record)) }

    static func update(_ id: UUID, _ change: (inout RunRecord) -> Void) {
        var all = load()
        guard let i = all.firstIndex(where: { $0.id == id }) else { return }
        change(&all[i]); save(all)
    }
}
