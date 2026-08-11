import Foundation

/// WP-18's mechanism seam.
///
/// The framework this seam stands in front of is a real, documented, public
/// **read** API — the same footing as WP-17's calendar and not WP-16's mail,
/// whose finding was that no read mechanism existed. So the question is not
/// whether contacts can be read; it is whether they can be read *safely*, and
/// that question is answered here rather than inside whatever eventually talks
/// to the framework.
///
/// The shipping host links **no Apple framework** — WP-15's control 1, proved at
/// link time — so the adapter is defined over this seam and not over a contact
/// store. The probe target `Compatibility/AppleContactsShapeProbe` carries the
/// framework references, is compiled by every `swift build`, and is a dependency
/// of nothing; that target is what makes "needs an operator TCC grant" a
/// different statement from "does not exist".
///
/// Four properties of the seam carry findings rather than conveniences:
///
/// 1. **The key set is the privacy control, and it is closed by the type.**
///    A contact read has to declare which keys it fetches. `ContactsFetchKey`
///    has two cases and there is no third, so a wider request is not something
///    this package refuses — it is something this package cannot express. See
///    `ContactsMinimumKeySet`.
/// 2. **A mechanism that cannot name its identity epoch cannot be read from.**
///    See `publishesIdentityEpoch`. A contact identifier is stable only relative
///    to an epoch, so a mechanism that cannot name the epoch cannot mint a
///    stable identity, and minting one anyway hands every downstream reconciler
///    a key that silently re-points.
/// 3. **A mechanism that cannot report group membership cannot be read from
///    either.** See `publishesGroupMembership`. An empty membership list means
///    "this person is in no group", and a mechanism that discards membership
///    would emit exactly that — the empty-versus-unavailable distinction the
///    campaign has enforced since WP-09, one level down from the page.
/// 4. **Every operation is a read, and there is no consent *request*.** The
///    adapter can observe that authorization is absent and refuse. It cannot ask
///    for it: on macOS the asking is what raises the dialogue, and a TCC grant
///    is operator-gated (EXT-04).

// MARK: - Authorization

/// What the mechanism can observe about authorization **without asking for it**.
///
/// Four cases, mirroring the framework's own vocabulary on this platform, and
/// exactly one of them permits a read. `notDetermined` does **not** mean "try it
/// and see": trying is what raises the dialogue.
///
/// The framework's enumeration carries a fifth case elsewhere — a partial grant
/// — and it is marked explicitly unavailable on macOS in this SDK. That was
/// measured rather than assumed (see the shape probe), and it is why this
/// vocabulary is four and not five: a case that cannot occur on the only
/// platform this host runs on would be a state nothing could ever produce and
/// every reader would have to handle.
public enum ContactsAuthorizationState: String, Codable, CaseIterable, Sendable {
    case authorized
    case denied
    /// Withheld by policy — a profile or a parental control — rather than by the
    /// person at the keyboard. Reported separately because "you said no" and
    /// "your organisation said no" are different facts, and the second is not
    /// fixable by asking again.
    case restricted
    case notDetermined = "not_determined"
}

// MARK: - The minimum key set

/// The **closed universe** of keys this package may ask a contacts mechanism to
/// fetch.
///
/// This is control 1, and it is a privacy control rather than an optimisation. A
/// contact read declares its keys up front, and every key declared is personal
/// data pulled out of a store and into a process. So the enumeration below is
/// the whole vocabulary, and it contains **no content-bearing case**: no given
/// or family name, no email address, no phone number, no postal address, no
/// birthday, no photograph or thumbnail, no note, no organization name, no
/// social profile, no instant-message handle. There is nowhere to put one, which
/// is the same shape WP-15 used for content-free telemetry and WP-17 used for the
/// all-day span: the bound is that the wrong value has no field to live in.
///
/// Each case is justified against WP-18's acceptance criteria, and a case that
/// cannot be justified there does not belong here:
///
/// * `identifier` — acceptance says **stable source identity**. The identifier
///   is the whole of it. Without it there is no record, only a count. It is an
///   opaque provider key, not a fact about a person;
/// * `structuralType` — acceptance says the observation is an observation.
///   Person and organization are different kinds of row, and a consumer that
///   reads an organization as a person has been handed a false statement about
///   somebody who does not exist. Two cases, naming nobody.
///
/// **What is deliberately not here, and does not cost a key.** Group and
/// container membership — acceptance's third criterion — is reached through the
/// framework's membership predicates rather than through a fetched key, so
/// preserving the structure costs nothing against this budget. That is a finding
/// worth stating: the one acceptance criterion that sounds like it needs more
/// data needs none.
public enum ContactsFetchKey: String, Codable, CaseIterable, Sendable {
    case identifier = "contact_identifier"
    case structuralType = "contact_structural_type"
}

/// The frozen minimum, in canonical order.
///
/// Equal to `ContactsFetchKey.allCases` by construction — the universe *is* the
/// minimum — so widening the request and widening the vocabulary are the same
/// edit, and both are visible in one place.
/// `tests/architecture/test_wp18_contacts_adapter.py` pins the members from
/// outside Swift so the set cannot grow quietly, and
/// `AppleSourceHostContractChecks` re-derives the equality at runtime.
public enum ContactsMinimumKeySet {
    public static let keys: [ContactsFetchKey] = [.identifier, .structuralType]

    /// Whether a declared key list is exactly the minimum, in order. Not a
    /// subset test: a *narrower* list is refused too, because an observation
    /// built from fewer keys than the contract names is an observation missing a
    /// field the consumer will read as absent rather than as unfetched.
    public static func isTheMinimum(_ declared: [ContactsFetchKey]) -> Bool {
        declared == keys
    }
}

// MARK: - Mechanism identity

public enum ContactsMechanismKind: String, Codable, CaseIterable, Sendable {
    /// The in-process fixture this package's harness drives. Seeded by hand with
    /// obviously synthetic content.
    case fixtureSeeded = "fixture_seeded"
    /// The platform's contact store. Present on this machine and operator-gated;
    /// see `AppleContactsShapeProbe` and
    /// `docs/campaign/WP-18-CONTACTS-ADAPTER-RECORD.md`. **Nothing in this
    /// repository implements it**, because implementing it means holding a TCC
    /// grant this package must not obtain.
    case platformContactStore = "platform_contact_store"
}

/// Where a container's records actually live, which is what decides how fragile
/// its identifiers are.
///
/// Not decoration: a local container's keys survive a re-sync because there is
/// no server to re-sync from, and a server-backed container's may not. A
/// consumer weighing `ContactIdentityAssurance` needs to know which kind of
/// container it is looking at.
public enum ContactsContainerKind: String, Codable, CaseIterable, Sendable {
    case local
    case exchange
    case cardDAV = "card_dav"
    case unassigned
}

public struct ContactsMechanismDescriptor: Codable, Hashable, Sendable {
    public let mechanism: ContactsMechanismKind
    /// Whether the mechanism can name the epoch its contact keys belong to. A
    /// mechanism that cannot is refused at read time rather than trusted to be
    /// close enough; see `ContactIdentity`.
    public let publishesIdentityEpoch: Bool
    /// Whether the mechanism reports which of its container's groups a contact
    /// belongs to. A mechanism that does not would report every contact as
    /// belonging to no group, which is a statement rather than a silence, and is
    /// refused for that reason.
    public let publishesGroupMembership: Bool
    /// Whether reaching this mechanism at all needs a grant only a human can
    /// give. Recorded, not enforced — the enforcement is `authorizationState()`.
    public let requiresOperatorConsent: Bool

    public init(
        mechanism: ContactsMechanismKind,
        publishesIdentityEpoch: Bool,
        publishesGroupMembership: Bool,
        requiresOperatorConsent: Bool
    ) {
        self.mechanism = mechanism
        self.publishesIdentityEpoch = publishesIdentityEpoch
        self.publishesGroupMembership = publishesGroupMembership
        self.requiresOperatorConsent = requiresOperatorConsent
    }
}

// MARK: - Discovery

public struct ContactsAccountDescriptor: Hashable, Sendable {
    public let accountKey: ContactsIdentityComponent
    public let displayLabel: String

    public init(accountKey: ContactsIdentityComponent, displayLabel: String) {
        self.accountKey = accountKey
        self.displayLabel = displayLabel
    }

    public var identity: ContactsAccountIdentity {
        ContactsAccountIdentity(accountKey: accountKey)
    }
}

public struct ContactsContainerDescriptor: Hashable, Sendable {
    public let identity: ContactsContainerIdentity
    public let kind: ContactsContainerKind
    public let displayLabel: String
    public let isSelectable: Bool

    public init(
        identity: ContactsContainerIdentity,
        kind: ContactsContainerKind,
        displayLabel: String,
        isSelectable: Bool
    ) {
        self.identity = identity
        self.kind = kind
        self.displayLabel = displayLabel
        self.isSelectable = isSelectable
    }
}

public struct ContactsGroupDescriptor: Hashable, Sendable {
    public let identity: ContactsGroupIdentity
    public let displayLabel: String

    public init(identity: ContactsGroupIdentity, displayLabel: String) {
        self.identity = identity
        self.displayLabel = displayLabel
    }
}

// MARK: - Observations

/// One contact, as the mechanism reports it.
///
/// **This is an observation carrying provenance, not an assertion about a
/// person** (brief §22). It says: at this epoch, in this container, under this
/// key, the source held a row of this structural kind, belonging to these
/// groups, read with exactly these keys — and it says how far the source is
/// willing to vouch for the key. It does not say who anybody is, and it has no
/// field in which to say so.
///
/// There is deliberately **no name, no email address, no telephone number, no
/// postal address, no birthday, no photograph and no note**. Contact content is
/// not part of WP-18's acceptance, and a content field nothing needs is a
/// content field that eventually holds somebody's address book in a public
/// repository. Nothing here scores, ranks, or infers anything about anybody
/// either; that is a different plane and explicitly a different package.
///
/// Three invariants a mechanism can get wrong in a way that looks right:
///
/// * the declared key list must be exactly the frozen minimum. Wider is a
///   privacy failure; narrower is a field the consumer reads as absent when it
///   was merely unfetched;
/// * membership must be strictly ascending and free of duplicates, so a
///   membership set has one representation and two equal memberships cannot
///   encode differently;
/// * membership must fit the frozen ceiling, and over it the observation is
///   **refused** rather than shortened.
public struct ContactObservation: Codable, Hashable, Sendable {
    public let identity: ContactIdentity
    public let structuralType: ContactStructuralType
    /// How far the mechanism vouches for `identity`. Never optional: an
    /// observation that does not state its assurance is one a consumer will
    /// assume is stable.
    public let identityAssurance: ContactIdentityAssurance
    /// The groups of this contact's container the source says it belongs to.
    /// Empty means "in none of them", which is a fact the mechanism had to be
    /// able to state — see `ContactsMechanismDescriptor.publishesGroupMembership`.
    public let groupKeys: [ContactsIdentityComponent]
    /// The keys this observation was actually built from. Carried per record so
    /// that control 1 is legible in the payload rather than only in the code
    /// that produced it.
    public let observedKeys: [ContactsFetchKey]

    public init(
        identity: ContactIdentity,
        structuralType: ContactStructuralType,
        identityAssurance: ContactIdentityAssurance,
        groupKeys: [ContactsIdentityComponent],
        observedKeys: [ContactsFetchKey]
    ) throws {
        guard ContactsMinimumKeySet.isTheMinimum(observedKeys) else {
            throw NativeSourceContractError.contactsKeySetWidened
        }
        guard groupKeys.count <= NativeSourceProtocolV1.maximumContactGroupMemberships else {
            throw NativeSourceContractError.contactsGroupLimitExceeded
        }
        guard zip(groupKeys, groupKeys.dropFirst()).allSatisfy({ $0.rawValue < $1.rawValue })
        else {
            throw NativeSourceContractError.contactsMembershipInconsistent
        }
        self.identity = identity
        self.structuralType = structuralType
        self.identityAssurance = identityAssurance
        self.groupKeys = groupKeys
        self.observedKeys = observedKeys
    }

    private enum CodingKeys: String, CodingKey {
        case identity, structuralType, identityAssurance, groupKeys, observedKeys
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            identity: values.decode(ContactIdentity.self, forKey: .identity),
            structuralType: values.decode(ContactStructuralType.self, forKey: .structuralType),
            identityAssurance: values.decode(
                ContactIdentityAssurance.self,
                forKey: .identityAssurance
            ),
            groupKeys: values.decode([ContactsIdentityComponent].self, forKey: .groupKeys),
            observedKeys: values.decode([ContactsFetchKey].self, forKey: .observedKeys)
        )
    }

    /// The pagination key: the composed record identifier. Contact keys are
    /// opaque provider strings with no order of their own, so the cursor is
    /// lexicographic over the composed identifier and the adapter requires the
    /// mechanism to return them strictly ascending.
    public func cursorKey() throws -> String {
        try identity.recordIdentifier().rawValue
    }
}

// MARK: - Traversal

public struct ContactsTraversalQuery: Hashable, Sendable {
    public let container: ContactsContainerIdentity
    /// What the mechanism is permitted to fetch. Set by the adapter from the
    /// frozen minimum, never by the mechanism, and refused here if it is
    /// anything else — so a mechanism is *told* what it may read rather than
    /// asked to be careful.
    public let requestedKeys: [ContactsFetchKey]
    /// Exclusive lower bound on the observation cursor key.
    public let afterCursorKey: String?
    public let limit: Int

    public init(
        container: ContactsContainerIdentity,
        requestedKeys: [ContactsFetchKey],
        afterCursorKey: String?,
        limit: Int
    ) throws {
        guard ContactsMinimumKeySet.isTheMinimum(requestedKeys) else {
            throw NativeSourceContractError.contactsKeySetWidened
        }
        guard limit > 0, limit <= NativeSourceProtocolV1.maximumPageSize else {
            throw NativeSourceContractError.invalidPageLimit
        }
        self.container = container
        self.requestedKeys = requestedKeys
        self.afterCursorKey = afterCursorKey
        self.limit = limit
    }
}

public struct ContactsTraversalResult: Hashable, Sendable {
    public let observations: [ContactObservation]
    /// The epoch these contact keys belong to. Cross-checked against every
    /// observation, so a mechanism cannot publish one epoch and key its records
    /// with another.
    public let identityEpoch: ContactsIdentityComponent
    /// **The honest truncation signal.** A page that stops short must say so,
    /// and the adapter refuses a result whose `moreAvailable` and cursor
    /// disagree. A truncated page reporting itself complete is how a caller
    /// stops paging and never learns what it did not receive.
    public let moreAvailable: Bool
    /// The mechanism's own declaration that satisfying this query required
    /// walking **every container** rather than bounding to the one asked for. A
    /// bounded read against a mechanism that says `true` is refused: the
    /// container is the scope bound, and a client-side filter after a full walk
    /// is precisely not that.
    ///
    /// It names *containers* and not pages on purpose. The framework offers a
    /// container-scoped and a group-scoped predicate, which are genuine
    /// source-side scope bounds, and offers **no limit or offset at all**, so a
    /// page is necessarily a slice the mechanism takes after materialising the
    /// container. Calling that "bounded" would be the overstatement this field
    /// exists to avoid; the record says so in as many words.
    public let enumeratedEveryContainer: Bool

    public init(
        observations: [ContactObservation],
        identityEpoch: ContactsIdentityComponent,
        moreAvailable: Bool,
        enumeratedEveryContainer: Bool
    ) {
        self.observations = observations
        self.identityEpoch = identityEpoch
        self.moreAvailable = moreAvailable
        self.enumeratedEveryContainer = enumeratedEveryContainer
    }
}

// MARK: - The seam

/// Everything the bounded adapter needs from whatever actually reads contacts.
///
/// The operation set is closed and every member of it is a read.
/// `tests/architecture/test_wp18_contacts_adapter.py::test_the_contacts_mechanism_seam_declares_only_read_operations`
/// holds it to exactly these five, across the declaration and every protocol
/// extension of it anywhere under `native/`, so adding a sixth is a decision
/// somebody has to make on purpose rather than a line in a diff. There is no
/// save, no add, no update, no delete, no execute, no commit — and no request
/// for consent.
public protocol ContactsMechanism: Sendable {
    var descriptor: ContactsMechanismDescriptor { get }
    func authorizationState() throws -> ContactsAuthorizationState
    func accounts() throws -> [ContactsAccountDescriptor]
    func containers() throws -> [ContactsContainerDescriptor]
    func groups() throws -> [ContactsGroupDescriptor]
    func contacts(_ query: ContactsTraversalQuery) throws -> ContactsTraversalResult
}
