import AppleSourceHost
import Contacts
import Foundation

/// Production-shaped, minimum-key, read-only Contacts implementation.
///
/// The identity epoch is supplied by the application configuration/persistence
/// plane and must change when the operator re-admits a restored/re-synced store.
/// The framework publishes no such epoch.  This mechanism requests only
/// identifier and structural type and reconstructs memberships with documented
/// group predicates.  It never creates or executes a save request and never
/// requests authorization.
public final class ContactsStoreMechanism: ContactsMechanism, @unchecked Sendable {
    public let descriptor = ContactsMechanismDescriptor(
        mechanism: .platformContactStore,
        publishesIdentityEpoch: true,
        publishesGroupMembership: true,
        requiresOperatorConsent: true
    )

    private let store: CNContactStore
    private let identityEpoch: ContactsIdentityComponent
    private let accountKey: ContactsIdentityComponent

    public init(store: CNContactStore, identityEpoch: String) throws {
        guard !identityEpoch.isEmpty, identityEpoch.utf8.count <= 200 else {
            throw NativeSourceContractError.contactsIdentityEpochUnavailable
        }
        self.store = store
        self.identityEpoch = try PlatformIdentity.contacts("contacts-epoch", identityEpoch)
        self.accountKey = try PlatformIdentity.contacts("contacts-account", "platform-default")
    }

    public func authorizationState() throws -> ContactsAuthorizationState {
        switch CNContactStore.authorizationStatus(for: .contacts) {
        case .authorized: return .authorized
        case .denied: return .denied
        case .restricted: return .restricted
        case .notDetermined: return .notDetermined
        @unknown default: return .denied
        }
    }

    public func accounts() throws -> [ContactsAccountDescriptor] {
        [ContactsAccountDescriptor(accountKey: accountKey, displayLabel: "Apple Contacts")]
    }

    public func containers() throws -> [ContactsContainerDescriptor] {
        try store.containers(matching: nil).map { container in
            ContactsContainerDescriptor(
                identity: try containerIdentity(container.identifier),
                kind: kind(container.type),
                displayLabel: container.name,
                isSelectable: true
            )
        }.sorted { try $0.identity.recordIdentifier().rawValue < $1.identity.recordIdentifier().rawValue }
    }

    public func groups() throws -> [ContactsGroupDescriptor] {
        try store.containers(matching: nil).flatMap { container in
            try store.groups(
                matching: CNGroup.predicateForGroupsInContainer(withIdentifier: container.identifier)
            ).map { group in
                ContactsGroupDescriptor(
                    identity: ContactsGroupIdentity(
                        container: try containerIdentity(container.identifier),
                        groupKey: try PlatformIdentity.contacts("contacts-group", group.identifier)
                    ),
                    displayLabel: group.name
                )
            }
        }.sorted { try $0.identity.recordIdentifier().rawValue < $1.identity.recordIdentifier().rawValue }
    }

    public func contacts(_ query: ContactsTraversalQuery) throws -> ContactsTraversalResult {
        let candidates = try store.containers(matching: nil).filter {
            try containerIdentity($0.identifier) == query.container
        }
        guard candidates.count == 1, let container = candidates.first else {
            throw NativeSourceContractError.unknownBucket
        }
        let groupValues = try store.groups(
            matching: CNGroup.predicateForGroupsInContainer(withIdentifier: container.identifier)
        )
        var memberships: [String: [ContactsIdentityComponent]] = [:]
        for group in groupValues {
            let groupKey = try PlatformIdentity.contacts("contacts-group", group.identifier)
            for contact in try store.unifiedContacts(
                matching: CNContact.predicateForContactsInGroup(withIdentifier: group.identifier),
                keysToFetch: [CNContactIdentifierKey as CNKeyDescriptor]
            ) {
                memberships[contact.identifier, default: []].append(groupKey)
            }
        }
        let values = try store.unifiedContacts(
            matching: CNContact.predicateForContactsInContainer(withIdentifier: container.identifier),
            keysToFetch: [
                CNContactIdentifierKey as CNKeyDescriptor,
                CNContactTypeKey as CNKeyDescriptor,
            ]
        ).map { contact in
            try ContactObservation(
                identity: ContactIdentity(
                    container: query.container,
                    identityEpoch: identityEpoch,
                    contactKey: try PlatformIdentity.contacts("contacts-contact", contact.identifier)
                ),
                structuralType: contact.contactType == .organization ? .organization : .person,
                identityAssurance: .stableWithinEpoch,
                groupKeys: (memberships[contact.identifier] ?? []).sorted {
                    $0.rawValue < $1.rawValue
                },
                observedKeys: query.requestedKeys
            )
        }.filter { try $0.cursorKey() > (query.afterCursorKey ?? "") }
            .sorted { try $0.cursorKey() < $1.cursorKey() }
        return ContactsTraversalResult(
            observations: Array(values.prefix(query.limit)),
            identityEpoch: identityEpoch,
            moreAvailable: values.count > query.limit,
            enumeratedEveryContainer: false
        )
    }

    private func containerIdentity(_ providerKey: String) throws -> ContactsContainerIdentity {
        ContactsContainerIdentity(
            accountKey: accountKey,
            containerKey: try PlatformIdentity.contacts("contacts-container", providerKey)
        )
    }

    private func kind(_ value: CNContainerType) -> ContactsContainerKind {
        switch value {
        case .local: return .local
        case .exchange: return .exchange
        case .cardDAV: return .cardDAV
        case .unassigned: return .unassigned
        @unknown default: return .unassigned
        }
    }
}
