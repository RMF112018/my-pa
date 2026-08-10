/// OD-COMP-009 framework-compatibility probe — **compile-time only**.
///
/// The open decision recommends "a supported signed/notarized local helper/service
/// architecture; prove framework compatibility before final choice." This target
/// is that proof, and it is deliberately the narrowest possible form of it: it
/// *compiles* against the frameworks a live read-only Apple source host and a
/// registered login-item service would need, on this exact toolchain and SDK, and
/// it does nothing else.
///
/// Constraints this file must keep, and which the repository's WP-15 architecture
/// tests enforce rather than trust:
///
/// * every reference is to a **metatype** — `EKEventStore.self`, not
///   `EKEventStore()`. Nothing is instantiated, so no store is created and no
///   permission dialogue can be reached;
/// * there is no `requestAccess`, no `requestFullAccessTo…`, no `SMAppService`
///   `register`/`unregister` call. Compatibility is a link-and-typecheck
///   question, and answering it does not require touching TCC;
/// * the production `AppleSourceHost` target does **not** depend on this target
///   and imports none of these frameworks. A `swift build` builds both, so the
///   compatibility claim is re-proved on every build without the personal-data
///   frameworks ever entering the shipping module;
/// * only read-oriented symbols appear. No mutating type (`EKEventStore.save`,
///   `CNSaveRequest`) is named anywhere in this file.
///
/// What this proves: these frameworks exist in this SDK, expose these symbols,
/// and link. What it does **not** prove: that a live enumeration works, that TCC
/// will grant, that a signed helper will notarize, or that Mail content is
/// reachable at all. Those need an operator, a signing identity and a real
/// machine — see `docs/campaign/WP-15-NATIVE-HOST-RECORD.md`.

import Contacts
import EventKit
import MailKit
import ServiceManagement

public enum AppleFrameworkCompatibilityProbe {
    /// EventKit — the Calendar read path (WP-17).
    public static let eventStoreType: EKEventStore.Type = EKEventStore.self
    public static let eventType: EKEvent.Type = EKEvent.self
    public static let calendarType: EKCalendar.Type = EKCalendar.self
    public static let calendarSourceType: EKSource.Type = EKSource.self
    public static let calendarEntity: EKEntityType = .event
    public static let calendarAuthorizationStatusType: EKAuthorizationStatus.Type =
        EKAuthorizationStatus.self

    /// Contacts — the Contacts read path (WP-18).
    public static let contactStoreType: CNContactStore.Type = CNContactStore.self
    public static let contactType: CNContact.Type = CNContact.self
    public static let contactFetchRequestType: CNContactFetchRequest.Type =
        CNContactFetchRequest.self
    public static let contactContainerType: CNContainer.Type = CNContainer.self
    public static let contactGroupType: CNGroup.Type = CNGroup.self
    public static let contactAuthorizationStatusType: CNAuthorizationStatus.Type =
        CNAuthorizationStatus.self

    /// ServiceManagement — the login-item/service lifecycle of the target
    /// distribution model. Referenced as a type; never registered.
    public static let appServiceType: SMAppService.Type = SMAppService.self
    public static let appServiceStatusType: SMAppService.Status.Type = SMAppService.Status.self

    /// MailKit — and this is the finding, not the reassurance. MailKit links and
    /// its types resolve, but it is an **extension-point** framework: `MEExtension`,
    /// `MEMessageDecoder`, `MEMessageSecurityHandler`, `MEMessageActionHandler`.
    /// The SDK exposes no store, no account enumeration, no mailbox listing and no
    /// message query. Compatibility here therefore does **not** imply Mail
    /// readability, which is exactly what completion-plan doc 08 warns against
    /// assuming, and WP-16 owns finding the actual mechanism.
    public static let mailMessageType: MEMessage.Type = MEMessage.self
    // Existential metatypes are not `Sendable`, so these are functions rather
    // than stored globals; the compatibility question is answered identically
    // and the module stays warning-free under strict concurrency.
    public static func mailExtensionType() -> MEExtension.Protocol { MEExtension.self }
    public static func mailDecoderType() -> MEMessageDecoder.Protocol { MEMessageDecoder.self }

    /// Names only; nothing is registered, granted, or opened by this target.
    public static let probedFrameworks = ["EventKit", "Contacts", "MailKit", "ServiceManagement"]
}
