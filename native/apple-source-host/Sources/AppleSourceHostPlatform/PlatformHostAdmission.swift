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
}

/// Pure application boundary used by the executable and production bootstrap.
/// It validates exact configuration/checkpoint identity and always leaves this
/// process dormant. Activation remains a separate operator-gated lifecycle act.
public enum PlatformHostAdmission {
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
            mailState: .availableOperatorGatedAutomation
        )
    }
}
