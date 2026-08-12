import AppleSourceHost
import Contacts
import EventKit
import Foundation

/// Apple Mail has no public read store API on macOS. MailKit is an extension
/// surface and ScriptingBridge cannot structurally enforce read-only access.
/// The platform composition therefore carries the limitation as a value rather
/// than silently substituting Graph, automation, or a fixture.
public enum PlatformMailReadAvailability: String, Codable, Sendable {
    case unavailableNoPublicReadAPI = "unavailable_no_public_read_api"
}

/// Notification names a separately activated watcher may observe. Merely
/// composing this value registers no observer and reads no personal data.
public struct PlatformSourceChangeSignals: Sendable {
    // Raw platform notification names keep this descriptor inert and avoid
    // conflating a change signal with the framework's mutation surface.
    public let calendar = Notification.Name("EKEventStoreChangedNotification")
    public let contacts = Notification.Name("CNContactStoreDidChangeNotification")

    public init() {}
}

/// Inert production composition. The caller supplies already-created stores and
/// an application-owned contacts identity epoch. No permission request, TCC
/// prompt, signing, installation, observer registration, read, admission,
/// persistence, or watcher activation happens in this initializer.
public struct PlatformAppleSourceComposition: @unchecked Sendable {
    public let calendar: BoundedCalendarReadAdapter
    public let contacts: BoundedContactsReadAdapter
    public let mail: PlatformMailReadAvailability
    public let changeSignals: PlatformSourceChangeSignals

    public init(
        eventStore: EKEventStore,
        contactStore: CNContactStore,
        contactsIdentityEpoch: String
    ) throws {
        self.calendar = BoundedCalendarReadAdapter(
            mechanism: EventKitCalendarMechanism(store: eventStore)
        )
        self.contacts = BoundedContactsReadAdapter(
            mechanism: try ContactsStoreMechanism(
                store: contactStore,
                identityEpoch: contactsIdentityEpoch
            )
        )
        self.mail = .unavailableNoPublicReadAPI
        self.changeSignals = PlatformSourceChangeSignals()
    }
}
