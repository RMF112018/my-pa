import AppleSourceHost
import Foundation

public struct PlatformSourceSelection: Codable, Hashable, Sendable {
    public let kind: NativeSourceKind
    public let bucketID: NativeSourceOpaqueID

    public init(kind: NativeSourceKind, bucketID: NativeSourceOpaqueID) {
        self.kind = kind
        self.bucketID = bucketID
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
        var checkpointKeys = Set<PlatformSourceSelection>()
        for checkpoint in checkpoints {
            guard checkpoint.configurationID == configuration.configurationID else {
                throw PlatformHostAdmissionError.checkpointConfigurationMismatch
            }
            let key = PlatformSourceSelection(
                kind: checkpoint.kind,
                bucketID: checkpoint.bucketID
            )
            guard selected.contains(key) else {
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
                (PlatformSourceSelection(kind: $0.kind, bucketID: $0.bucketID), $0)
            }
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let selections = configuration.selections.sorted {
            ($0.kind.rawValue, $0.bucketID.rawValue) < ($1.kind.rawValue, $1.bucketID.rawValue)
        }
        for selection in selections {
            let checkpoint = checkpointBySelection[selection]
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
                    accountID: configuration.configurationID,
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
}
