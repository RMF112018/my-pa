import AppleSourceHost
import CryptoKit
import Foundation

/// Stable, content-free provider-key encoding for the core identity alphabets.
/// The digest avoids storing an account/contact locator in the handoff identity.
enum PlatformIdentity {
    static func calendar(_ namespace: String, _ providerKey: String) throws
        -> CalendarIdentityComponent {
        guard let value = CalendarIdentityComponent(rawValue: digest(namespace, providerKey)) else {
            throw NativeSourceContractError.calendarInvalidIdentityComponent
        }
        return value
    }

    static func contacts(_ namespace: String, _ providerKey: String) throws
        -> ContactsIdentityComponent {
        guard let value = ContactsIdentityComponent(rawValue: digest(namespace, providerKey)) else {
            throw NativeSourceContractError.contactsInvalidIdentityComponent
        }
        return value
    }

    private static func digest(_ namespace: String, _ providerKey: String) -> String {
        SHA256.hash(data: Data("\(namespace)\u{1f}\(providerKey)".utf8))
            .map { String(format: "%02x", $0) }
            .joined()
    }
}
