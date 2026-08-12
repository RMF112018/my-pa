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
    private let maximumContactsScanned: Int
    private let maximumMembershipsScanned: Int
    private let maximumContainers: Int
    private let maximumGroups: Int

    public init(
        store: CNContactStore,
        identityEpoch: String,
        maximumContactsScanned: Int = 5_000,
        maximumMembershipsScanned: Int = 10_000,
        maximumContainers: Int = 1_000,
        maximumGroups: Int = 5_000
    ) throws {
        guard !identityEpoch.isEmpty, identityEpoch.utf8.count <= 200 else {
            throw NativeSourceContractError.contactsIdentityEpochUnavailable
        }
        guard 1...10_000 ~= maximumContactsScanned,
              1...50_000 ~= maximumMembershipsScanned,
              1...1_000 ~= maximumContainers,
              1...10_000 ~= maximumGroups
        else { throw NativeSourceContractError.contactsTraversalExceeded }
        self.store = store
        self.identityEpoch = try PlatformIdentity.contacts("contacts-epoch", identityEpoch)
        self.accountKey = try PlatformIdentity.contacts("contacts-account", "platform-default")
        self.maximumContactsScanned = maximumContactsScanned
        self.maximumMembershipsScanned = maximumMembershipsScanned
        self.maximumContainers = maximumContainers
        self.maximumGroups = maximumGroups
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
        let containers = try boundedContainers()
        return try containers.map { container in
            ContactsContainerDescriptor(
                identity: try containerIdentity(container.identifier),
                kind: kind(container.type),
                displayLabel: container.name,
                isSelectable: true
            )
        }.sorted { try $0.identity.recordIdentifier().rawValue < $1.identity.recordIdentifier().rawValue }
    }

    public func groups() throws -> [ContactsGroupDescriptor] {
        let containers = try boundedContainers()
        var result: [ContactsGroupDescriptor] = []
        for container in containers {
            let groups = try store.groups(
                matching: CNGroup.predicateForGroupsInContainer(withIdentifier: container.identifier)
            )
            guard groups.count <= maximumGroups - result.count else {
                throw NativeSourceContractError.contactsTraversalExceeded
            }
            result.append(contentsOf: try groups.map { group in
                ContactsGroupDescriptor(
                    identity: ContactsGroupIdentity(
                        container: try containerIdentity(container.identifier),
                        groupKey: try PlatformIdentity.contacts("contacts-group", group.identifier)
                    ),
                    displayLabel: group.name
                )
            })
        }
        return try result.sorted {
            try $0.identity.recordIdentifier().rawValue < $1.identity.recordIdentifier().rawValue
        }
    }

    public func contacts(_ query: ContactsTraversalQuery) throws -> ContactsTraversalResult {
        let candidates = try boundedContainers().filter {
            try containerIdentity($0.identifier) == query.container
        }
        guard candidates.count == 1, let container = candidates.first else {
            throw NativeSourceContractError.unknownBucket
        }
        let request = CNContactFetchRequest(keysToFetch: [
            CNContactIdentifierKey as CNKeyDescriptor,
            CNContactTypeKey as CNKeyDescriptor,
        ])
        request.predicate = CNContact.predicateForContactsInContainer(
            withIdentifier: container.identifier
        )
        request.unifyResults = true
        request.mutableObjects = false
        request.sortOrder = .none
        let contacts = ContactEnumerationState(maximum: maximumContactsScanned)
        try store.enumerateContacts(with: request) { contact, stop in
            contacts.append(contact, stop: stop)
        }
        let rawContacts = try contacts.result()
        let memberships = try groupMemberships(
            containerIdentifier: container.identifier,
            targetContactIdentifiers: Set(rawContacts.map(\.identifier))
        )
        let values = try rawContacts.map { contact in
            try ContactObservation(
                identity: ContactIdentity(
                    container: query.container,
                    identityEpoch: identityEpoch,
                    contactKey: try PlatformIdentity.contacts("contacts-contact", contact.identifier)
                ),
                structuralType: contact.structuralType == .organization ? .organization : .person,
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

    private func groupMemberships(
        containerIdentifier: String,
        targetContactIdentifiers: Set<String>
    ) throws -> [String: [ContactsIdentityComponent]] {
        let state = ContactMembershipState(
            maximum: maximumMembershipsScanned,
            targets: targetContactIdentifiers
        )
        let groups = try store.groups(
            matching: CNGroup.predicateForGroupsInContainer(withIdentifier: containerIdentifier)
        )
        guard groups.count <= maximumGroups else {
            throw NativeSourceContractError.contactsTraversalExceeded
        }
        for group in groups {
            let groupKey = try PlatformIdentity.contacts("contacts-group", group.identifier)
            let request = CNContactFetchRequest(
                keysToFetch: [CNContactIdentifierKey as CNKeyDescriptor]
            )
            request.predicate = CNContact.predicateForContactsInGroup(
                withIdentifier: group.identifier
            )
            request.unifyResults = true
            request.mutableObjects = false
            request.sortOrder = .none
            try store.enumerateContacts(with: request) { contact, stop in
                state.observe(contact.identifier, groupKey: groupKey, stop: stop)
            }
            if state.exceeded { throw NativeSourceContractError.contactsTraversalExceeded }
        }
        return try state.result()
    }

    private func boundedContainers() throws -> [CNContainer] {
        // Contacts returns this array atomically; the public API offers no
        // streaming container callback. Refuse immediately after return and
        // before mapping, property reads, or nested group/contact traversal.
        let containers = try store.containers(matching: nil)
        guard containers.count <= maximumContainers else {
            throw NativeSourceContractError.contactsTraversalExceeded
        }
        return containers
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

private struct RawContactObservation: Sendable {
    let identifier: String
    let structuralType: CNContactType
}

private final class ContactEnumerationState: @unchecked Sendable {
    private let lock = NSLock()
    private let maximum: Int
    private var values: [RawContactObservation] = []
    private var overflowed = false

    init(maximum: Int) { self.maximum = maximum }

    func append(_ contact: CNContact, stop: UnsafeMutablePointer<ObjCBool>) {
        lock.lock()
        defer { lock.unlock() }
        if values.count >= maximum {
            overflowed = true
            stop.pointee = true
            return
        }
        values.append(
            RawContactObservation(
                identifier: contact.identifier,
                structuralType: contact.contactType
            )
        )
    }

    func result() throws -> [RawContactObservation] {
        lock.lock()
        defer { lock.unlock() }
        if overflowed { throw NativeSourceContractError.contactsTraversalExceeded }
        return values
    }
}

private final class ContactMembershipState: @unchecked Sendable {
    private let lock = NSLock()
    private let maximum: Int
    private let targets: Set<String>
    private var scanned = 0
    private var values: [String: [ContactsIdentityComponent]] = [:]
    private(set) var exceeded = false

    init(maximum: Int, targets: Set<String>) {
        self.maximum = maximum
        self.targets = targets
    }

    func observe(
        _ identifier: String,
        groupKey: ContactsIdentityComponent,
        stop: UnsafeMutablePointer<ObjCBool>
    ) {
        lock.lock()
        defer { lock.unlock() }
        scanned += 1
        if scanned > maximum {
            exceeded = true
            stop.pointee = true
            return
        }
        if targets.contains(identifier) {
            values[identifier, default: []].append(groupKey)
        }
    }

    func result() throws -> [String: [ContactsIdentityComponent]] {
        lock.lock()
        defer { lock.unlock() }
        if exceeded { throw NativeSourceContractError.contactsTraversalExceeded }
        for keys in values.values where keys.count > NativeSourceProtocolV1.maximumContactGroupMemberships {
            throw NativeSourceContractError.contactsGroupLimitExceeded
        }
        return values
    }
}
