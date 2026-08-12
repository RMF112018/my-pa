public struct NativeProtocolOffer: Codable, Hashable, Sendable {
    public let supportedVersions: [String]

    public init(supportedVersions: [String]) {
        self.supportedVersions = supportedVersions
    }
}

public struct NativeProtocolAgreement: Codable, Hashable, Sendable {
    public let selectedVersion: String

    public init(offer: NativeProtocolOffer) throws {
        guard offer.supportedVersions.contains(NativeSourceProtocolV1.identifier) else {
            throw NativeSourceContractError.unsupportedVersion
        }
        self.selectedVersion = NativeSourceProtocolV1.identifier
    }

    private enum CodingKeys: String, CodingKey { case selectedVersion }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        let selectedVersion = try values.decode(String.self, forKey: .selectedVersion)
        guard selectedVersion == NativeSourceProtocolV1.identifier else {
            throw NativeSourceContractError.unsupportedVersion
        }
        self.selectedVersion = selectedVersion
    }
}

public struct NativeEnvelopeMetadata: Codable, Hashable, Sendable {
    public let protocolVersion: String
    public let envelopeID: NativeSourceOpaqueID
    public let hostInstanceID: NativeSourceOpaqueID
    public let emittedAtUnixMilliseconds: Int64

    public init(
        protocolVersion: String = NativeSourceProtocolV1.identifier,
        envelopeID: NativeSourceOpaqueID,
        hostInstanceID: NativeSourceOpaqueID,
        emittedAtUnixMilliseconds: Int64
    ) throws {
        guard protocolVersion == NativeSourceProtocolV1.identifier else {
            throw NativeSourceContractError.unsupportedVersion
        }
        self.protocolVersion = protocolVersion
        self.envelopeID = envelopeID
        self.hostInstanceID = hostInstanceID
        self.emittedAtUnixMilliseconds = emittedAtUnixMilliseconds
    }

    private enum CodingKeys: String, CodingKey {
        case protocolVersion, envelopeID, hostInstanceID, emittedAtUnixMilliseconds
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            protocolVersion: values.decode(String.self, forKey: .protocolVersion),
            envelopeID: values.decode(NativeSourceOpaqueID.self, forKey: .envelopeID),
            hostInstanceID: values.decode(NativeSourceOpaqueID.self, forKey: .hostInstanceID),
            emittedAtUnixMilliseconds: values.decode(Int64.self, forKey: .emittedAtUnixMilliseconds)
        )
    }
}

public struct NativeDiscoveryEnvelope: Codable, Hashable, Sendable {
    public let metadata: NativeEnvelopeMetadata
    public let snapshot: NativeDiscoverySnapshot

    public init(metadata: NativeEnvelopeMetadata, snapshot: NativeDiscoverySnapshot) throws {
        let accountIDs = snapshot.accounts.map(\.id)
        let bucketIDs = snapshot.buckets.map(\.id)
        guard Set(accountIDs).count == accountIDs.count,
              Set(bucketIDs).count == bucketIDs.count
        else {
            throw NativeSourceContractError.duplicateIdentity
        }
        guard accountIDs == accountIDs.sorted(by: { $0.rawValue < $1.rawValue }),
              bucketIDs == bucketIDs.sorted(by: { $0.rawValue < $1.rawValue })
        else {
            throw NativeSourceContractError.nonCanonicalOrder
        }
        self.metadata = metadata
        self.snapshot = snapshot
    }

    private enum CodingKeys: String, CodingKey { case metadata, snapshot }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            metadata: values.decode(NativeEnvelopeMetadata.self, forKey: .metadata),
            snapshot: values.decode(NativeDiscoverySnapshot.self, forKey: .snapshot)
        )
    }
}

public enum NativePreflightState: String, Codable, CaseIterable, Sendable {
    case reachable
    case permissionDenied = "permission_denied"
    case unavailable
    case identityDrift = "identity_drift"
}

public struct NativeBucketSelection: Codable, Hashable, Sendable {
    public let kind: NativeSourceKind
    public let accountID: NativeSourceOpaqueID
    public let bucketID: NativeSourceOpaqueID

    public init(kind: NativeSourceKind, accountID: NativeSourceOpaqueID, bucketID: NativeSourceOpaqueID) {
        self.kind = kind
        self.accountID = accountID
        self.bucketID = bucketID
    }
}

public struct NativePreflightRequest: Codable, Hashable, Sendable {
    public let protocolVersion: String
    public let requestID: NativeSourceOpaqueID
    public let selections: [NativeBucketSelection]

    public init(
        protocolVersion: String = NativeSourceProtocolV1.identifier,
        requestID: NativeSourceOpaqueID,
        selections: [NativeBucketSelection]
    ) throws {
        guard protocolVersion == NativeSourceProtocolV1.identifier else {
            throw NativeSourceContractError.unsupportedVersion
        }
        guard !selections.isEmpty,
              Set(selections).count == selections.count,
              selections == selections.sorted(by: Self.lessThan)
        else {
            throw NativeSourceContractError.nonCanonicalOrder
        }
        self.protocolVersion = protocolVersion
        self.requestID = requestID
        self.selections = selections
    }

    private enum CodingKeys: String, CodingKey {
        case protocolVersion, requestID, selections
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            protocolVersion: values.decode(String.self, forKey: .protocolVersion),
            requestID: values.decode(NativeSourceOpaqueID.self, forKey: .requestID),
            selections: values.decode([NativeBucketSelection].self, forKey: .selections)
        )
    }

    private static func lessThan(_ lhs: NativeBucketSelection, _ rhs: NativeBucketSelection) -> Bool {
        (lhs.kind.rawValue, lhs.accountID.rawValue, lhs.bucketID.rawValue)
            < (rhs.kind.rawValue, rhs.accountID.rawValue, rhs.bucketID.rawValue)
    }
}

public struct NativePreflightResult: Codable, Hashable, Sendable {
    public let selection: NativeBucketSelection
    public let state: NativePreflightState
    public let failure: NativeProviderFailure?

    public init(
        selection: NativeBucketSelection,
        state: NativePreflightState,
        failure: NativeProviderFailure? = nil
    ) throws {
        let consistent: Bool
        switch state {
        case .reachable:
            consistent = failure == nil
        case .permissionDenied:
            consistent = failure == .permissionDenied
        case .unavailable:
            consistent = [.accountUnavailable, .bucketUnavailable, .transientUnavailable]
                .contains(failure)
        case .identityDrift:
            consistent = failure == .bucketUnavailable
        }
        guard consistent else {
            throw NativeSourceContractError.inconsistentEnvelope
        }
        self.selection = selection
        self.state = state
        self.failure = failure
    }

    private enum CodingKeys: String, CodingKey { case selection, state, failure }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            selection: values.decode(NativeBucketSelection.self, forKey: .selection),
            state: values.decode(NativePreflightState.self, forKey: .state),
            failure: values.decodeIfPresent(NativeProviderFailure.self, forKey: .failure)
        )
    }
}

public struct NativePreflightEnvelope: Codable, Hashable, Sendable {
    public let metadata: NativeEnvelopeMetadata
    public let requestID: NativeSourceOpaqueID
    public let results: [NativePreflightResult]

    public init(
        metadata: NativeEnvelopeMetadata,
        request: NativePreflightRequest,
        results: [NativePreflightResult]
    ) throws {
        guard results.map(\.selection) == request.selections else {
            throw NativeSourceContractError.inconsistentEnvelope
        }
        self.metadata = metadata
        self.requestID = request.requestID
        self.results = results
    }

    private enum CodingKeys: String, CodingKey { case metadata, requestID, results }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        let metadata = try values.decode(NativeEnvelopeMetadata.self, forKey: .metadata)
        let requestID = try values.decode(NativeSourceOpaqueID.self, forKey: .requestID)
        let results = try values.decode([NativePreflightResult].self, forKey: .results)
        let request = try NativePreflightRequest(
            protocolVersion: metadata.protocolVersion,
            requestID: requestID,
            selections: results.map(\.selection)
        )
        try self.init(metadata: metadata, request: request, results: results)
    }
}

public struct NativeReadEnvelopeRequest: Codable, Hashable, Sendable {
    public let protocolVersion: String
    public let requestID: NativeSourceOpaqueID
    public let kind: NativeSourceKind
    public let accountID: NativeSourceOpaqueID
    public let request: NativeReadRequest

    public init(
        protocolVersion: String = NativeSourceProtocolV1.identifier,
        requestID: NativeSourceOpaqueID,
        kind: NativeSourceKind,
        accountID: NativeSourceOpaqueID,
        request: NativeReadRequest
    ) throws {
        guard protocolVersion == NativeSourceProtocolV1.identifier else {
            throw NativeSourceContractError.unsupportedVersion
        }
        self.protocolVersion = protocolVersion
        self.requestID = requestID
        self.kind = kind
        self.accountID = accountID
        self.request = request
    }

    private enum CodingKeys: String, CodingKey {
        case protocolVersion, requestID, kind, accountID, request
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            protocolVersion: values.decode(String.self, forKey: .protocolVersion),
            requestID: values.decode(NativeSourceOpaqueID.self, forKey: .requestID),
            kind: values.decode(NativeSourceKind.self, forKey: .kind),
            accountID: values.decode(NativeSourceOpaqueID.self, forKey: .accountID),
            request: values.decode(NativeReadRequest.self, forKey: .request)
        )
    }
}

/// Versioned handoff bytes for a future authenticated application admission
/// use case. This value is not an admission result and grants no authority.
public struct NativeAdmissionEnvelope: Codable, Hashable, Sendable {
    public let metadata: NativeEnvelopeMetadata
    public let requestID: NativeSourceOpaqueID
    public let kind: NativeSourceKind
    public let accountID: NativeSourceOpaqueID
    public let bucketID: NativeSourceOpaqueID
    public let records: [NativeSourceRecord]
    public let nextCursor: NativeReadCursor?

    public init(
        metadata: NativeEnvelopeMetadata,
        request: NativeReadEnvelopeRequest,
        page: NativeReadPage
    ) throws {
        guard page.records.allSatisfy({
            $0.kind == request.kind && $0.bucketID == request.request.bucketID
        }) else {
            throw NativeSourceContractError.inconsistentEnvelope
        }
        self.metadata = metadata
        self.requestID = request.requestID
        self.kind = request.kind
        self.accountID = request.accountID
        self.bucketID = request.request.bucketID
        self.records = page.records
        self.nextCursor = page.nextCursor
    }

    private enum CodingKeys: String, CodingKey {
        case metadata, requestID, kind, accountID, bucketID, records, nextCursor
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        let metadata = try values.decode(NativeEnvelopeMetadata.self, forKey: .metadata)
        let requestID = try values.decode(NativeSourceOpaqueID.self, forKey: .requestID)
        let kind = try values.decode(NativeSourceKind.self, forKey: .kind)
        let accountID = try values.decode(NativeSourceOpaqueID.self, forKey: .accountID)
        let bucketID = try values.decode(NativeSourceOpaqueID.self, forKey: .bucketID)
        let records = try values.decode([NativeSourceRecord].self, forKey: .records)
        let nextCursor = try values.decodeIfPresent(NativeReadCursor.self, forKey: .nextCursor)
        let request = try NativeReadEnvelopeRequest(
            protocolVersion: metadata.protocolVersion,
            requestID: requestID,
            kind: kind,
            accountID: accountID,
            request: NativeReadRequest(bucketID: bucketID, cursor: nil, limit: max(records.count, 1))
        )
        try self.init(
            metadata: metadata,
            request: request,
            page: try NativeReadPage(records: records, nextCursor: nextCursor)
        )
    }
}

public protocol NativeHostApplicationBoundary: Sendable {
    func negotiate(_ offer: NativeProtocolOffer) throws -> NativeProtocolAgreement
    func discover(_ kind: NativeSourceKind, metadata: NativeEnvelopeMetadata) throws -> NativeDiscoveryEnvelope
    func preflight(_ request: NativePreflightRequest, metadata: NativeEnvelopeMetadata) throws -> NativePreflightEnvelope
    func read(_ request: NativeReadEnvelopeRequest, metadata: NativeEnvelopeMetadata) throws -> NativeAdmissionEnvelope
}
