import Foundation

/// Ways a contacts mechanism can be wrong, so that the adapter's re-checks are
/// exercised rather than merely written.
///
/// Each is a real failure mode of a real contacts source: one that satisfies a
/// container-scoped query by walking every container, one that returns keys the
/// cursor cannot resume from, one that claims more is available without filling
/// the page, one that answers with another container's people, one that names a
/// group nothing published, one whose declared epoch and keyed epoch disagree,
/// one whose grant is withdrawn mid-session — and the one this package exists to
/// name, a mechanism that reports "in no group" where it means "I did not look".
public enum FixtureContactsFault: Hashable, Sendable {
    case none
    case declareEveryContainerSweep
    case returnKeysOutOfOrder
    case claimMoreAvailableWithoutFillingThePage
    case leakAnotherContainersContact
    case claimAnUndeclaredGroup
    case driftTheIdentityEpoch
    /// The revocation case. The first authorization observation is honest and
    /// every one after it reports `denied`, which is what a grant withdrawn from
    /// System Settings mid-session actually looks like to a running process.
    case revokeAuthorizationAfterTheFirstCheck
    /// Not detectable by the adapter, and included for exactly that reason: the
    /// harness compares a read taken with this fault against the same read
    /// without it, so "membership must not be reported as absence" is *measured*
    /// rather than asserted. Nothing downstream of a mechanism can tell a
    /// discarded membership from a person who is genuinely in no group, which is
    /// the whole argument for `publishesGroupMembership` being a refusal at the
    /// seam.
    case forgetGroupMembership
}

/// The in-process mechanism the WP-18 harness drives.
///
/// **Level of proof, stated plainly: in-process, over a seam, against a store
/// this package seeded itself.** No contact store is constructed anywhere in
/// this repository, no TCC grant is held or requested, and no contact belonging
/// to anyone is read. Every value below is obviously synthetic. What the seam
/// buys is that every refusal lives in `BoundedContactsReadAdapter`, so the
/// refusals hold for any mechanism satisfying the seam — including a live one,
/// if an operator ever grants the consent that would let somebody write it.
///
/// Mutable state with plain `var`s and `@unchecked Sendable`, following
/// `FixtureMailMechanism` and `FixtureCalendarMechanism`: the contract-check
/// executable drives this from one thread, and the call counters exist so that
/// "no read happened" can be *measured* after a refusal rather than inferred by
/// reading the adapter.
public final class FixtureContactsMechanism: ContactsMechanism, @unchecked Sendable {
    public let descriptor: ContactsMechanismDescriptor

    private let accountDescriptors: [ContactsAccountDescriptor]
    private let containerDescriptors: [ContactsContainerDescriptor]
    private let groupDescriptors: [ContactsGroupDescriptor]
    private let store: [(key: String, observation: ContactObservation)]
    private let epoch: ContactsIdentityComponent
    private var authorization: ContactsAuthorizationState
    private var fault: FixtureContactsFault

    public private(set) var authorizationCalls = 0
    public private(set) var accountCalls = 0
    public private(set) var containerCalls = 0
    public private(set) var groupCalls = 0
    public private(set) var contactCalls = 0

    public init(
        descriptor: ContactsMechanismDescriptor,
        accounts: [ContactsAccountDescriptor],
        containers: [ContactsContainerDescriptor],
        groups: [ContactsGroupDescriptor],
        observations: [ContactObservation],
        identityEpoch: ContactsIdentityComponent,
        authorization: ContactsAuthorizationState = .authorized,
        fault: FixtureContactsFault = .none
    ) throws {
        self.descriptor = descriptor
        self.accountDescriptors = accounts
        self.containerDescriptors = containers
        self.groupDescriptors = groups
        self.store = try observations
            .map { (key: try $0.cursorKey(), observation: $0) }
            .sorted { $0.key < $1.key }
        self.epoch = identityEpoch
        self.authorization = authorization
        self.fault = fault
    }

    // MARK: Harness controls — not part of `ContactsMechanism`

    public func setAuthorization(_ state: ContactsAuthorizationState) {
        authorization = state
    }

    public func setFault(_ value: FixtureContactsFault) {
        fault = value
    }

    public func resetCallCounters() {
        authorizationCalls = 0
        accountCalls = 0
        containerCalls = 0
        groupCalls = 0
        contactCalls = 0
    }

    public var readCalls: Int { accountCalls + containerCalls + groupCalls + contactCalls }

    // MARK: ContactsMechanism

    public func authorizationState() throws -> ContactsAuthorizationState {
        authorizationCalls += 1
        if fault == .revokeAuthorizationAfterTheFirstCheck, authorizationCalls > 1 {
            return .denied
        }
        return authorization
    }

    public func accounts() throws -> [ContactsAccountDescriptor] {
        accountCalls += 1
        return accountDescriptors
    }

    public func containers() throws -> [ContactsContainerDescriptor] {
        containerCalls += 1
        return containerDescriptors
    }

    public func groups() throws -> [ContactsGroupDescriptor] {
        groupCalls += 1
        return groupDescriptors
    }

    public func contacts(_ query: ContactsTraversalQuery) throws -> ContactsTraversalResult {
        contactCalls += 1
        var selected = store
        if fault != .leakAnotherContainersContact {
            selected = selected.filter { $0.observation.identity.container == query.container }
        }
        if let after = query.afterCursorKey {
            selected = selected.filter { $0.key > after }
        }
        var page = Array(selected.prefix(query.limit))
        var moreAvailable = selected.count > page.count
        if fault == .returnKeysOutOfOrder {
            page.reverse()
        }
        if fault == .claimMoreAvailableWithoutFillingThePage {
            page = Array(page.dropLast())
            moreAvailable = true
        }
        var observations = page.map(\.observation)
        if fault == .forgetGroupMembership {
            observations = try observations.map { try $0.withGroupKeys([]) }
        }
        if fault == .claimAnUndeclaredGroup {
            observations = try observations.map { try $0.withGroupKeys([Self.undeclaredGroupKey]) }
        }
        return ContactsTraversalResult(
            observations: observations,
            identityEpoch: fault == .driftTheIdentityEpoch ? Self.driftedEpoch : epoch,
            moreAvailable: moreAvailable,
            enumeratedEveryContainer: fault == .declareEveryContainerSweep
        )
    }

    /// A group key no fixture ever publishes, so the adapter's membership
    /// re-check has something undeclared to reject.
    public static let undeclaredGroupKey = ContactsIdentityComponent(rawValue: "group-omega")!
    /// An epoch no fixture record is keyed with.
    public static let driftedEpoch = ContactsIdentityComponent(rawValue: "epoch-drifted")!
}

extension ContactObservation {
    /// The same observation with a different membership list. Used only by the
    /// fixture's faults, and it routes through the throwing initialiser so a
    /// fault cannot manufacture an observation the type would otherwise refuse.
    fileprivate func withGroupKeys(
        _ groupKeys: [ContactsIdentityComponent]
    ) throws -> ContactObservation {
        try ContactObservation(
            identity: identity,
            structuralType: structuralType,
            identityAssurance: identityAssurance,
            groupKeys: groupKeys,
            observedKeys: observedKeys
        )
    }
}
