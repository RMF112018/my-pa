import AppleSourceHost
import Contacts
import EventKit
import Foundation

/// Apple Mail has no public read store API on macOS. The admitted fallback is a
/// closed ScriptingBridge client that names only read property/element codes.
/// The OS grant is broader, so the mechanism stays separately operator-gated.
public enum PlatformMailReadAvailability: String, Codable, Sendable {
    case availableOperatorGatedAutomation = "available_operator_gated_automation"
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
    public let tasks: BoundedTasksReadAdapter
    public let mail: BoundedMailReadAdapter
    public let mailAvailability: PlatformMailReadAvailability
    public let changeSignals: PlatformSourceChangeSignals

    public init(
        eventStore: EKEventStore,
        contactStore: CNContactStore,
        contactsIdentityEpoch: String,
        mailGeneration: String
    ) throws {
        self.calendar = BoundedCalendarReadAdapter(
            mechanism: try EventKitCalendarMechanism(store: eventStore)
        )
        self.contacts = BoundedContactsReadAdapter(
            mechanism: try ContactsStoreMechanism(
                store: contactStore,
                identityEpoch: contactsIdentityEpoch
            )
        )
        self.tasks = BoundedTasksReadAdapter(
            mechanism: try EventKitTasksMechanism(store: eventStore)
        )
        self.mail = BoundedMailReadAdapter(
            mechanism: try AppleMailAutomationMechanism(generation: mailGeneration)
        )
        self.mailAvailability = .availableOperatorGatedAutomation
        self.changeSignals = PlatformSourceChangeSignals()
    }

    /// Resolve selected kinds against the real production adapters without
    /// observing TCC or touching a source. Accessing these descriptors is inert.
    public func requireNonLiveHandoff(for kinds: Set<NativeSourceKind>) throws {
        for kind in kinds {
            switch kind {
            case .calendar:
                _ = calendar.descriptor
            case .contacts:
                _ = contacts.descriptor
            case .tasks:
                _ = tasks.descriptor
            case .mail:
                _ = mail.descriptor
            }
        }
    }
}
