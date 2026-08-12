import AppleSourceHost
import Foundation

public struct PlatformSourceSelection: Codable, Hashable, Sendable {
    public let kind: NativeSourceKind
    public let accountID: NativeSourceOpaqueID
    public let bucketID: NativeSourceOpaqueID

    public init(
        kind: NativeSourceKind,
        accountID: NativeSourceOpaqueID,
        bucketID: NativeSourceOpaqueID
    ) {
        self.kind = kind
        self.accountID = accountID
        self.bucketID = bucketID
    }
}

/// Separate, expiring authority artifact issued by the authenticated Python
/// application for exactly one bridge/request/envelope and one source bucket.
public struct PlatformAuthorizedReadGrant: Codable, Hashable, Sendable {
    public static let schema = "my-pa.apple-source-read-grant.v1"
    public static let authorization = "AUTHORIZED_LIVE_PERSONAL_DATA_READ"

    public let schema: String
    public let configurationID: NativeSourceOpaqueID
    public let bridgeID: NativeSourceOpaqueID
    public let requestID: NativeSourceOpaqueID
    public let envelopeID: NativeSourceOpaqueID
    public let kind: NativeSourceKind
    public let accountID: NativeSourceOpaqueID
    public let bucketID: NativeSourceOpaqueID
    public let authorization: String
    public let expiresAtUnixMilliseconds: Int64
    public let pageLimit: Int
    public let timeRange: NativeTimeRange

    public init(
        schema: String = Self.schema,
        configurationID: NativeSourceOpaqueID,
        bridgeID: NativeSourceOpaqueID,
        requestID: NativeSourceOpaqueID,
        envelopeID: NativeSourceOpaqueID,
        kind: NativeSourceKind,
        accountID: NativeSourceOpaqueID,
        bucketID: NativeSourceOpaqueID,
        authorization: String,
        expiresAtUnixMilliseconds: Int64,
        pageLimit: Int,
        timeRange: NativeTimeRange
    ) {
        self.schema = schema
        self.configurationID = configurationID
        self.bridgeID = bridgeID
        self.requestID = requestID
        self.envelopeID = envelopeID
        self.kind = kind
        self.accountID = accountID
        self.bucketID = bucketID
        self.authorization = authorization
        self.expiresAtUnixMilliseconds = expiresAtUnixMilliseconds
        self.pageLimit = pageLimit
        self.timeRange = timeRange
    }
}

/// Operator-authored production configuration. Decoding is admission only: it
/// cannot activate a watcher or construct a framework store.
public struct PlatformAppleSourceConfiguration: Codable, Hashable, Sendable {
    public static let schema = "my-pa.apple-source-host.v1"

    public let schema: String
    public let configurationID: NativeSourceOpaqueID
    public let protocolVersion: String
    public let contactsIdentityEpoch: String
    public let mailGeneration: String
    public let selections: [PlatformSourceSelection]
    public let activationRequested: Bool

    public init(
        schema: String = Self.schema,
        configurationID: NativeSourceOpaqueID,
        protocolVersion: String = NativeSourceProtocolV1.identifier,
        contactsIdentityEpoch: String,
        mailGeneration: String,
        selections: [PlatformSourceSelection],
        activationRequested: Bool = false
    ) {
        self.schema = schema
        self.configurationID = configurationID
        self.protocolVersion = protocolVersion
        self.contactsIdentityEpoch = contactsIdentityEpoch
        self.mailGeneration = mailGeneration
        self.selections = selections
        self.activationRequested = activationRequested
    }
}

public struct PlatformSourceCheckpoint: Codable, Hashable, Sendable {
    public let configurationID: NativeSourceOpaqueID
    public let kind: NativeSourceKind
    public let bucketID: NativeSourceOpaqueID
    public let cursor: NativeReadCursor?

    public init(
        configurationID: NativeSourceOpaqueID,
        kind: NativeSourceKind,
        bucketID: NativeSourceOpaqueID,
        cursor: NativeReadCursor?
    ) {
        self.configurationID = configurationID
        self.kind = kind
        self.bucketID = bucketID
        self.cursor = cursor
    }
}

private struct PlatformCheckpointKey: Hashable {
    let kind: NativeSourceKind
    let bucketID: NativeSourceOpaqueID
}

public struct PlatformHostAdmissionSummary: Codable, Hashable, Sendable {
    public let configurationID: NativeSourceOpaqueID
    public let admittedSelections: Int
    public let admittedCheckpoints: Int
    public let activationState: String
    public let mailState: PlatformMailReadAvailability
    public let handoffState: String
    public let protectedArtifacts: Int
}

/// Content-free receipt written by the explicitly bounded dry-run handoff.
/// It proves production composition and protected-spool reachability only; it
/// is not a source-data admission envelope and carries no cursor or content.
public struct PlatformProtectedHandoffReceipt: Codable, Hashable, Sendable {
    public static let schema = "my-pa.apple-source-handoff-receipt.v1"

    public let schema: String
    public let configurationID: NativeSourceOpaqueID
    public let kind: NativeSourceKind
    public let bucketID: NativeSourceOpaqueID
    public let checkpointPresent: Bool
    public let state: String
}

public enum PlatformHostAdmissionError: Error, Equatable, Sendable {
    case unsupportedSchema
    case unsupportedProtocol
    case contactsIdentityEpochMissing
    case noSelection
    case duplicateSelection
    case mailUnavailable
    case activationRequiresSeparateOperatorGrant
    case checkpointConfigurationMismatch
    case checkpointNotSelected
    case duplicateCheckpoint
    case selectionLimitExceeded
    case checkpointLimitExceeded
    case liveReadGrantInvalid
    case liveReadGrantExpired
}

/// Pure application boundary used by the executable and production bootstrap.
/// It validates exact configuration/checkpoint identity and always leaves this
/// process dormant. Activation remains a separate operator-gated lifecycle act.
public enum PlatformHostAdmission {
    public static let maximumSelections = 16
    public static let maximumCheckpoints = 16

    public static func validate(
        configuration: PlatformAppleSourceConfiguration,
        checkpoints: [PlatformSourceCheckpoint]
    ) throws -> PlatformHostAdmissionSummary {
        guard configuration.schema == PlatformAppleSourceConfiguration.schema else {
            throw PlatformHostAdmissionError.unsupportedSchema
        }
        guard configuration.protocolVersion == NativeSourceProtocolV1.identifier else {
            throw PlatformHostAdmissionError.unsupportedProtocol
        }
        guard !configuration.contactsIdentityEpoch.isEmpty,
              configuration.contactsIdentityEpoch.utf8.count <= 200
        else { throw PlatformHostAdmissionError.contactsIdentityEpochMissing }
        guard !configuration.selections.isEmpty else {
            throw PlatformHostAdmissionError.noSelection
        }
        guard configuration.selections.count <= maximumSelections else {
            throw PlatformHostAdmissionError.selectionLimitExceeded
        }
        guard checkpoints.count <= maximumCheckpoints else {
            throw PlatformHostAdmissionError.checkpointLimitExceeded
        }
        let selected = Set(configuration.selections)
        guard selected.count == configuration.selections.count else {
            throw PlatformHostAdmissionError.duplicateSelection
        }
        if selected.contains(where: { $0.kind == .mail }) {
            guard MailIdentityComponent(rawValue: configuration.mailGeneration) != nil else {
                throw PlatformHostAdmissionError.mailUnavailable
            }
        }
        guard !configuration.activationRequested else {
            throw PlatformHostAdmissionError.activationRequiresSeparateOperatorGrant
        }
        let selectedCheckpointKeys = Set(configuration.selections.map {
            PlatformCheckpointKey(kind: $0.kind, bucketID: $0.bucketID)
        })
        guard selectedCheckpointKeys.count == configuration.selections.count else {
            throw PlatformHostAdmissionError.duplicateSelection
        }
        var checkpointKeys = Set<PlatformCheckpointKey>()
        for checkpoint in checkpoints {
            guard checkpoint.configurationID == configuration.configurationID else {
                throw PlatformHostAdmissionError.checkpointConfigurationMismatch
            }
            let key = PlatformCheckpointKey(kind: checkpoint.kind, bucketID: checkpoint.bucketID)
            guard selectedCheckpointKeys.contains(key) else {
                throw PlatformHostAdmissionError.checkpointNotSelected
            }
            guard checkpointKeys.insert(key).inserted else {
                throw PlatformHostAdmissionError.duplicateCheckpoint
            }
        }
        return PlatformHostAdmissionSummary(
            configurationID: configuration.configurationID,
            admittedSelections: selected.count,
            admittedCheckpoints: checkpoints.count,
            activationState: "dormant",
            mailState: .availableOperatorGatedAutomation,
            handoffState: "admitted_not_composed",
            protectedArtifacts: 0
        )
    }

    public static func validateAuthorizedRead(
        configuration: PlatformAppleSourceConfiguration,
        checkpoints: [PlatformSourceCheckpoint],
        grant: PlatformAuthorizedReadGrant,
        nowUnixMilliseconds: Int64
    ) throws -> PlatformHostAdmissionSummary {
        guard configuration.schema == PlatformAppleSourceConfiguration.schema,
              configuration.protocolVersion == NativeSourceProtocolV1.identifier,
              configuration.activationRequested,
              grant.schema == PlatformAuthorizedReadGrant.schema,
              grant.configurationID == configuration.configurationID,
              grant.authorization == PlatformAuthorizedReadGrant.authorization,
              1...NativeSourceProtocolV1.maximumPageSize ~= grant.pageLimit,
              configuration.selections.count == 1,
              let selection = configuration.selections.first,
              selection.kind == grant.kind,
              selection.accountID == grant.accountID,
              selection.bucketID == grant.bucketID
        else { throw PlatformHostAdmissionError.liveReadGrantInvalid }
        guard grant.expiresAtUnixMilliseconds >= nowUnixMilliseconds else {
            throw PlatformHostAdmissionError.liveReadGrantExpired
        }
        let dormant = PlatformAppleSourceConfiguration(
            configurationID: configuration.configurationID,
            protocolVersion: configuration.protocolVersion,
            contactsIdentityEpoch: configuration.contactsIdentityEpoch,
            mailGeneration: configuration.mailGeneration,
            selections: configuration.selections,
            activationRequested: false
        )
        let admitted = try validate(configuration: dormant, checkpoints: checkpoints)
        return PlatformHostAdmissionSummary(
            configurationID: admitted.configurationID,
            admittedSelections: admitted.admittedSelections,
            admittedCheckpoints: admitted.admittedCheckpoints,
            activationState: "authorized_single_pass",
            mailState: admitted.mailState,
            handoffState: "authorized_read_not_started",
            protectedArtifacts: 0
        )
    }

    /// Execute the production composition boundary without invoking a source.
    /// Construction wires the real adapters; this handoff only proves that each
    /// selected kind resolves to that composition and its checkpoint. It never
    /// calls discovery, authorization observation, or traversal.
    public static func nonLiveHandoff(
        configuration: PlatformAppleSourceConfiguration,
        checkpoints: [PlatformSourceCheckpoint],
        composition: PlatformAppleSourceComposition
    ) throws -> PlatformHostAdmissionSummary {
        let admitted = try validate(configuration: configuration, checkpoints: checkpoints)
        let kinds = Set(configuration.selections.map(\.kind))
        try composition.requireNonLiveHandoff(for: kinds)
        return PlatformHostAdmissionSummary(
            configurationID: admitted.configurationID,
            admittedSelections: admitted.admittedSelections,
            admittedCheckpoints: admitted.admittedCheckpoints,
            activationState: admitted.activationState,
            mailState: composition.mailAvailability,
            handoffState: "production_composition_inert",
            protectedArtifacts: 0
        )
    }

    /// Resolve the real production composition and durably enqueue one
    /// content-free receipt per selected bucket in an owner-only bounded spool.
    /// This deliberately invokes no discovery, TCC observation, or source read.
    public static func protectedNonLiveHandoff(
        configuration: PlatformAppleSourceConfiguration,
        checkpoints: [PlatformSourceCheckpoint],
        composition: PlatformAppleSourceComposition,
        spool: ProtectedSpool
    ) throws -> PlatformHostAdmissionSummary {
        let admitted = try nonLiveHandoff(
            configuration: configuration,
            checkpoints: checkpoints,
            composition: composition
        )
        let checkpointBySelection = Dictionary(
            uniqueKeysWithValues: checkpoints.map {
                (PlatformCheckpointKey(kind: $0.kind, bucketID: $0.bucketID), $0)
            }
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let selections = configuration.selections.sorted {
            ($0.kind.rawValue, $0.bucketID.rawValue) < ($1.kind.rawValue, $1.bucketID.rawValue)
        }
        for selection in selections {
            let checkpoint = checkpointBySelection[
                PlatformCheckpointKey(kind: selection.kind, bucketID: selection.bucketID)
            ]
            let receipt = PlatformProtectedHandoffReceipt(
                schema: PlatformProtectedHandoffReceipt.schema,
                configurationID: configuration.configurationID,
                kind: selection.kind,
                bucketID: selection.bucketID,
                checkpointPresent: checkpoint != nil,
                state: "production_composition_inert"
            )
            let cursorMaterial = checkpoint?.cursor?.rawValue ?? "no-checkpoint"
            let envelopeID = try PlatformIdentity.opaque(
                "protected-handoff-receipt",
                [
                    configuration.configurationID.rawValue,
                    selection.kind.rawValue,
                    selection.bucketID.rawValue,
                    cursorMaterial,
                ].joined(separator: "\u{1f}")
            )
            _ = try spool.enqueue(
                try NativeSpoolItem(
                    envelopeID: envelopeID,
                    kind: selection.kind,
                    accountID: selection.accountID,
                    bucketID: selection.bucketID,
                    payload: Array(try encoder.encode(receipt))
                )
            )
        }
        return PlatformHostAdmissionSummary(
            configurationID: admitted.configurationID,
            admittedSelections: admitted.admittedSelections,
            admittedCheckpoints: admitted.admittedCheckpoints,
            activationState: admitted.activationState,
            mailState: admitted.mailState,
            handoffState: "production_composition_spooled",
            protectedArtifacts: selections.count
        )
    }

    /// Read exactly one previously authorized page and enqueue its immutable
    /// envelope. Application-issued authority identities are carried unchanged.
    public static func authorizedSinglePassHandoff(
        configuration: PlatformAppleSourceConfiguration,
        checkpoints: [PlatformSourceCheckpoint],
        grant: PlatformAuthorizedReadGrant,
        nowUnixMilliseconds: Int64,
        composition: PlatformAppleSourceComposition,
        spool: ProtectedSpool
    ) throws -> PlatformHostAdmissionSummary {
        let admitted = try validateAuthorizedRead(
            configuration: configuration,
            checkpoints: checkpoints,
            grant: grant,
            nowUnixMilliseconds: nowUnixMilliseconds
        )
        let selection = configuration.selections[0]
        var lifecycle = try NativeHostLifecycle(hostInstanceID: grant.bridgeID)
        do {
            _ = try lifecycle.negotiate(
                NativeProtocolOffer(supportedVersions: [configuration.protocolVersion])
            )
            try lifecycle.openedSpool()
            try lifecycle.readyForHandoff()
            let request = try NativeReadRequest(
                bucketID: selection.bucketID,
                timeRange: grant.timeRange,
                cursor: checkpoints.first?.cursor,
                limit: grant.pageLimit
            )
            let envelopeRequest = try NativeReadEnvelopeRequest(
                requestID: grant.requestID,
                kind: selection.kind,
                accountID: selection.accountID,
                request: request
            )
            let envelope = try NativeAdmissionEnvelope(
                metadata: try NativeEnvelopeMetadata(
                    envelopeID: grant.envelopeID,
                    hostInstanceID: grant.bridgeID,
                    emittedAtUnixMilliseconds: nowUnixMilliseconds
                ),
                request: envelopeRequest,
                page: try composition.read(selection.kind, request: request)
            )
            _ = try spool.enqueue(try NativeSpoolItem(admissionEnvelope: envelope))
            return PlatformHostAdmissionSummary(
                configurationID: admitted.configurationID,
                admittedSelections: admitted.admittedSelections,
                admittedCheckpoints: admitted.admittedCheckpoints,
                activationState: "authorized_single_pass_complete",
                mailState: admitted.mailState,
                handoffState: lifecycle.state.rawValue,
                protectedArtifacts: 1
            )
        } catch {
            lifecycle.refuse(error)
            throw error
        }
    }

}
