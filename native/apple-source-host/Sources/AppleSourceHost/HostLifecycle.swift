import Foundation

/// WP-15 production-shaped host lifecycle.
///
/// This is the *shape* the signed/notarized local helper will run through, built
/// and proved now so that the later operator-gated activation (EXT-03/04/05) is a
/// configuration and signing step rather than a redesign. Nothing here registers
/// a service, requests a permission, or links `ServiceManagement`: the lifecycle
/// names the states and refuses the illegal transitions, and the prerequisites
/// that would move `distributionModel` off `unsignedDevelopmentBuild` are
/// enumerated as data rather than assumed.
///
/// The framework-compatibility question OD-COMP-009 asks — *will the frameworks a
/// signed local helper needs actually build against this toolchain?* — is answered
/// by the separate `AppleFrameworkCompatibilityProbe` target, which compiles
/// against them without this target ever importing one.

public enum NativeHostDistributionModel: String, Codable, CaseIterable, Sendable {
    /// What this repository builds today: `swift build`, unsigned, no service
    /// registration, no entitlements, no TCC grant.
    case unsignedDevelopmentBuild = "unsigned_development_build"
    /// The recommended target model. Reachable only through the operator-gated
    /// prerequisites below; no code path in this package selects it.
    case signedNotarizedLoginItemService = "signed_notarized_login_item_service"
}

/// Everything that must be supplied from outside this repository before the
/// target distribution model is reachable. Enumerated so the gap is legible and
/// machine-readable rather than a sentence in a README.
public enum NativeHostActivationPrerequisite: String, Codable, CaseIterable, Sendable {
    case appleSigningIdentity = "apple_signing_identity"
    case notarizationTicket = "notarization_ticket"
    case hardenedRuntimeEntitlements = "hardened_runtime_entitlements"
    case serviceRegistration = "service_registration"
    case tccGrant = "tcc_grant"
    case eligibleHostMachine = "eligible_host_machine"
}

public enum NativeHostLifecycleState: String, Codable, CaseIterable, Sendable {
    case constructed
    case protocolNegotiated = "protocol_negotiated"
    case spoolOpened = "spool_opened"
    case readyForHandoff = "ready_for_handoff"
    case stopped
    case refused
}

public enum NativeHostLifecycleError: Error, Equatable, Sendable {
    case illegalTransition(from: NativeHostLifecycleState, to: NativeHostLifecycleState)
    case activationNotAuthorized(NativeHostActivationPrerequisite)
}

/// An explicit state machine rather than a set of booleans. Every transition is
/// named, and anything not named is refused — so a host that skipped negotiation
/// cannot reach the state in which it is allowed to hand anything off.
public struct NativeHostLifecycle: Codable, Hashable, Sendable {
    public private(set) var state: NativeHostLifecycleState
    public let hostInstanceID: NativeSourceOpaqueID
    public let distributionModel: NativeHostDistributionModel

    /// Always false in this package. There is no method that can set it, because
    /// there is no method that registers a service.
    public var serviceRegistrationPerformed: Bool { false }

    /// None of these is satisfied here, and the type offers no way to satisfy
    /// one. Presence of a prerequisite in this list is a statement that an
    /// operator, not this repository, closes it.
    public static let unsatisfiedActivationPrerequisites: [NativeHostActivationPrerequisite] =
        NativeHostActivationPrerequisite.allCases

    public init(
        hostInstanceID: NativeSourceOpaqueID,
        distributionModel: NativeHostDistributionModel = .unsignedDevelopmentBuild
    ) throws {
        guard distributionModel == .unsignedDevelopmentBuild else {
            // Selecting the signed model from code would claim an activation this
            // build has not performed and cannot perform.
            throw NativeHostLifecycleError.activationNotAuthorized(.appleSigningIdentity)
        }
        self.state = .constructed
        self.hostInstanceID = hostInstanceID
        self.distributionModel = distributionModel
    }

    private static let permitted: [NativeHostLifecycleState: Set<NativeHostLifecycleState>] = [
        .constructed: [.protocolNegotiated, .refused, .stopped],
        .protocolNegotiated: [.spoolOpened, .refused, .stopped],
        .spoolOpened: [.readyForHandoff, .refused, .stopped],
        .readyForHandoff: [.readyForHandoff, .refused, .stopped],
        .refused: [.stopped],
        .stopped: [],
    ]

    private mutating func transition(to next: NativeHostLifecycleState) throws {
        guard Self.permitted[state, default: []].contains(next) else {
            throw NativeHostLifecycleError.illegalTransition(from: state, to: next)
        }
        state = next
    }

    /// Version agreement is the first transition and it is not optional: a host
    /// whose offer does not carry the frozen identifier is refused here rather
    /// than parsed as best it can be.
    @discardableResult
    public mutating func negotiate(_ offer: NativeProtocolOffer) throws -> NativeProtocolAgreement {
        do {
            let agreement = try NativeProtocolAgreement(offer: offer)
            try transition(to: .protocolNegotiated)
            return agreement
        } catch {
            state = .refused
            throw error
        }
    }

    public mutating func openedSpool() throws {
        try transition(to: .spoolOpened)
    }

    public mutating func readyForHandoff() throws {
        try transition(to: .readyForHandoff)
    }

    /// Records a refusal and returns its class. The failure itself is never
    /// retained: a lifecycle carries a state, not an error message.
    @discardableResult
    public mutating func refuse(_ error: Error) -> NativeHostErrorClass {
        state = .refused
        return NativeHostErrorClass(error)
    }

    public mutating func stop() {
        state = .stopped
    }

    private enum CodingKeys: String, CodingKey {
        case state, hostInstanceID, distributionModel
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        let model = try values.decode(NativeHostDistributionModel.self, forKey: .distributionModel)
        guard model == .unsignedDevelopmentBuild else {
            throw NativeHostLifecycleError.activationNotAuthorized(.appleSigningIdentity)
        }
        self.state = try values.decode(NativeHostLifecycleState.self, forKey: .state)
        self.hostInstanceID = try values.decode(NativeSourceOpaqueID.self, forKey: .hostInstanceID)
        self.distributionModel = model
    }
}
