import Foundation

/// The WP-18 Contacts adapter: minimum-key, read-only, and framework-free.
///
/// It implements the existing `ContactsReadAdapter` over `ContactsMechanism`.
/// Everything that makes the read safe lives here rather than in the mechanism,
/// so a future live mechanism inherits the refusals instead of being trusted to
/// reimplement them:
///
/// * **authorization is re-checked on every operation and is never cached.**
///   This type has no stored state but the mechanism itself — no `var`, no
///   memo, no last-good page — so there is nothing for a revoked grant to leave
///   behind. A grant withdrawn between two calls makes the second call refuse;
///   it does not make it serve the first call's records again. The refusal is a
///   thrown `NativeProviderFailure.permissionDenied` and is therefore a
///   different *value* from a successful read of an empty container, which is an
///   empty `NativeReadPage`. "No authorization" must never arrive downstream
///   looking like "you have no contacts";
/// * **the key set is set here, from the frozen minimum, and re-checked on every
///   record.** The mechanism is told what it may fetch rather than asked to be
///   careful, and an observation declaring anything else is refused;
/// * a mechanism that cannot name its identity epoch is refused outright,
///   because contact identity is anchored to that epoch; so is one that cannot
///   report group membership, because "in no group" and "membership unknown" are
///   different facts and only the first is representable;
/// * the mechanism's own answer is re-checked against the container, the epoch,
///   the declared groups and the page limit it was given, so a mechanism that
///   ignores its bounds is caught rather than believed;
/// * a truncated page must declare itself, and the declaration is cross-checked
///   against the page it came with;
/// * **nothing is filtered.** There is no `filter` over anything below, and that
///   absence is the point: every bound here is enforced by refusing the whole
///   page, because a page silently missing the records that failed a check is a
///   page that reads as complete.
///
/// There is no mutation surface. The seam offers five operations and all five
/// are reads; this type adds none, and the only thing it writes is the page it
/// returns.
public struct BoundedContactsReadAdapter: ContactsReadAdapter, Sendable {
    private let mechanism: any ContactsMechanism

    public init(mechanism: any ContactsMechanism) {
        self.mechanism = mechanism
    }

    public var descriptor: ContactsMechanismDescriptor { mechanism.descriptor }

    // MARK: Discovery

    /// Accounts, containers and groups, in the vocabulary the protocol already
    /// has.
    ///
    /// `account → container → group` survives the read as
    /// `NativeSourceAccount → NativeSourceBucket → NativeSourceBucket`, with the
    /// group's `parentID` naming its container. No parallel envelope is
    /// invented; the structure is carried by fields the admitting application
    /// already understands.
    public func discoverContactCollections() throws -> NativeDiscoverySnapshot {
        try requireAuthorization()
        let accounts = try mechanism.accounts().map { descriptor in
            NativeSourceAccount(
                id: try descriptor.identity.recordIdentifier(),
                kind: .contacts,
                displayLabel: descriptor.displayLabel
            )
        }
        let containerDescriptors = try mechanism.containers()
        let containers = try containerDescriptors.map { descriptor in
            NativeSourceBucket(
                id: try descriptor.identity.recordIdentifier(),
                accountID: try descriptor.identity.account.recordIdentifier(),
                parentID: nil,
                kind: .contacts,
                displayLabel: descriptor.displayLabel,
                isSelectable: descriptor.isSelectable
            )
        }
        let known = Set(containerDescriptors.map(\.identity))
        let groups = try mechanism.groups().map { descriptor in
            // A group whose container discovery did not report is a group whose
            // place in the tree cannot be stated. Refused rather than attached
            // to whichever container looks plausible.
            guard known.contains(descriptor.identity.container) else {
                throw NativeSourceContractError.contactsMembershipInconsistent
            }
            return NativeSourceBucket(
                id: try descriptor.identity.recordIdentifier(),
                accountID: try descriptor.identity.container.account.recordIdentifier(),
                parentID: try descriptor.identity.container.recordIdentifier(),
                kind: .contacts,
                displayLabel: descriptor.displayLabel,
                // A group is a membership view of its container, not a separate
                // place to read from: a bounded read is scoped to a container.
                isSelectable: false
            )
        }
        return try NativeDiscoverySnapshot(
            kind: .contacts,
            accounts: accounts.sorted { $0.id.rawValue < $1.id.rawValue },
            buckets: (containers + groups).sorted { $0.id.rawValue < $1.id.rawValue }
        )
    }

    // MARK: Traversal

    public func readContacts(_ request: NativeReadRequest) throws -> NativeReadPage {
        try requireAuthorization()
        guard mechanism.descriptor.publishesIdentityEpoch else {
            throw NativeSourceContractError.contactsIdentityEpochUnavailable
        }
        guard mechanism.descriptor.publishesGroupMembership else {
            throw NativeSourceContractError.contactsMembershipUnavailable
        }
        let container = try ContactsContainerIdentity(bucketID: request.bucketID)
        let query = try ContactsTraversalQuery(
            container: container,
            requestedKeys: ContactsMinimumKeySet.keys,
            afterCursorKey: request.cursor?.rawValue,
            limit: request.limit
        )
        let declaredGroups = try declaredGroupIdentifiers()
        let result = try mechanism.contacts(query)

        guard !result.enumeratedEveryContainer else {
            throw NativeSourceContractError.contactsUnboundedEnumeration
        }
        guard result.observations.count <= request.limit else {
            throw NativeSourceContractError.invalidPageLimit
        }
        try requireStrictlyAscendingUniqueKeys(result.observations, after: query.afterCursorKey)
        try requireEveryObservationBelongsTo(container, result.observations)
        try requireEveryObservationCarries(result.identityEpoch, result.observations)
        try requireEveryObservationReadOnly(query.requestedKeys, result.observations)
        try requireEveryMembershipIsDeclared(declaredGroups, result.observations)

        let nextCursor = try honestNextCursor(for: result, limit: request.limit)
        let records = try result.observations.map { observation in
            try record(for: observation, bucketID: request.bucketID)
        }
        return try NativeReadPage(records: records, nextCursor: nextCursor)
    }

    // MARK: Internals

    /// Fail-closed, exhaustively, with no `default`.
    ///
    /// Exactly one authorization state permits a read and the other three
    /// refuse. The `switch` is exhaustive on purpose: a `default` arm would
    /// silently admit any state a later framework adds, and "a state we have not
    /// heard of" is not a state to read somebody's address book on.
    ///
    /// Called at the top of every operation, every time. Nothing here remembers
    /// a previous answer, which is what makes a mid-session revocation refuse
    /// rather than serve.
    private func requireAuthorization() throws {
        switch try mechanism.authorizationState() {
        case .authorized:
            return
        case .denied:
            throw NativeProviderFailure.permissionDenied
        case .restricted:
            throw NativeProviderFailure.permissionDenied
        case .notDetermined:
            throw NativeProviderFailure.permissionDenied
        }
    }

    private func declaredGroupIdentifiers() throws -> Set<String> {
        Set(try mechanism.groups().map { try $0.identity.recordIdentifier().rawValue })
    }

    private func requireStrictlyAscendingUniqueKeys(
        _ observations: [ContactObservation],
        after: String?
    ) throws {
        var previous = after
        for observation in observations {
            let key = try observation.cursorKey()
            if let previous, key <= previous {
                throw NativeSourceContractError.nonCanonicalOrder
            }
            previous = key
        }
    }

    private func requireEveryObservationBelongsTo(
        _ container: ContactsContainerIdentity,
        _ observations: [ContactObservation]
    ) throws {
        guard observations.allSatisfy({ $0.identity.container == container }) else {
            throw NativeSourceContractError.unknownBucket
        }
    }

    /// The epoch the result declares and the epoch its records are keyed with
    /// have to be one epoch. A mechanism that publishes one and keys with
    /// another has produced identifiers no reconciler can place.
    private func requireEveryObservationCarries(
        _ epoch: ContactsIdentityComponent,
        _ observations: [ContactObservation]
    ) throws {
        guard observations.allSatisfy({ $0.identity.identityEpoch == epoch }) else {
            throw NativeSourceContractError.contactsIdentityEpochMismatch
        }
    }

    /// Control 1, re-checked per record rather than trusted per query.
    private func requireEveryObservationReadOnly(
        _ requested: [ContactsFetchKey],
        _ observations: [ContactObservation]
    ) throws {
        guard observations.allSatisfy({ $0.observedKeys == requested }) else {
            throw NativeSourceContractError.contactsKeySetWidened
        }
    }

    /// Control 3, re-checked against what discovery says exists.
    ///
    /// A membership naming a group the mechanism does not publish is not a
    /// harmless extra: it is a place in the tree that does not exist, and a
    /// consumer that stores it has a dangling edge it will later resolve to
    /// whatever next takes that key.
    private func requireEveryMembershipIsDeclared(
        _ declared: Set<String>,
        _ observations: [ContactObservation]
    ) throws {
        for observation in observations {
            for key in observation.groupKeys {
                let group = ContactsGroupIdentity(
                    container: observation.identity.container,
                    groupKey: key
                )
                guard declared.contains(try group.recordIdentifier().rawValue) else {
                    throw NativeSourceContractError.contactsUnknownGroup
                }
            }
        }
    }

    /// The honest truncation signal, cross-checked rather than copied.
    ///
    /// A mechanism claiming more is available must have filled the page — a
    /// short page with more behind it is incoherent — and must have left an
    /// observation to resume from.
    private func honestNextCursor(
        for result: ContactsTraversalResult,
        limit: Int
    ) throws -> NativeReadCursor? {
        guard result.moreAvailable else { return nil }
        guard result.observations.count == limit, let last = result.observations.last else {
            throw NativeSourceContractError.contactsTruncationUndeclared
        }
        guard let cursor = NativeReadCursor(rawValue: try last.cursorKey()) else {
            throw NativeSourceContractError.contactsTruncationUndeclared
        }
        return cursor
    }

    /// **A finding, carried honestly rather than papered over.** The framework
    /// publishes no per-contact modification date, so there is no timestamp to
    /// put in `sourceModifiedUnixMilliseconds` and it is `nil`. The revision is
    /// the identity epoch, which is the only revision the source actually
    /// offers: it tells a consumer when the whole container's keys were re-minted
    /// and tells it nothing about whether one person's row changed. A synthesised
    /// per-record timestamp would look like the second and be the first.
    private func record(
        for observation: ContactObservation,
        bucketID: NativeSourceOpaqueID
    ) throws -> NativeSourceRecord {
        NativeSourceRecord(
            id: try observation.identity.recordIdentifier(),
            bucketID: bucketID,
            kind: .contacts,
            sourceRevision: observation.identity.identityEpoch.rawValue,
            sourceModifiedUnixMilliseconds: nil,
            payload: Array(try JSONEncoder().encode(observation))
        )
    }
}
