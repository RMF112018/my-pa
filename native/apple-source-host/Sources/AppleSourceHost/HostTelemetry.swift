import Foundation

/// WP-15 content-free operational telemetry.
///
/// Every value in this file is content-free **by construction rather than by
/// redaction**: no type here declares a free-form `String` field, so there is no
/// place for a message body, a subject, a contact value, a calendar note, a
/// filesystem path, or a provider locator to be written. The only string-shaped
/// values are closed enumeration raw values, the frozen protocol identifier, and
/// `NativeSourceOpaqueID`, whose own validator already rejects locator
/// punctuation. Everything else is a count, a byte total, a timestamp, or an
/// error *class*.
///
/// A redaction filter can be forgotten at one call site. A struct with nowhere
/// to put content cannot be.

/// The closed operational vocabulary. An event names *what happened*, never what
/// it happened to.
public enum NativeHostTelemetryEventClass: String, Codable, CaseIterable, Sendable {
    case protocolNegotiated = "protocol_negotiated"
    case protocolRefused = "protocol_refused"
    case discoveryCompleted = "discovery_completed"
    case preflightCompleted = "preflight_completed"
    case readCompleted = "read_completed"
    case spoolEnqueued = "spool_enqueued"
    case spoolDuplicateIgnored = "spool_duplicate_ignored"
    case spoolRefusedAtCapacity = "spool_refused_at_capacity"
    case spoolQuarantined = "spool_quarantined"
    case spoolResidueRecovered = "spool_residue_recovered"
    case handoffAcknowledged = "handoff_acknowledged"
    case hostRefused = "host_refused"
}

/// The closed host-operational failure vocabulary, distinct from
/// `NativeProviderFailure` because a spool or lifecycle fault is not a provider
/// fault. Construction from an `Error` deliberately discards the error's own
/// description: only the class survives.
public enum NativeHostErrorClass: String, Codable, CaseIterable, Sendable {
    case unsupportedVersion = "unsupported_version"
    case malformedEnvelope = "malformed_envelope"
    case duplicateIdentity = "duplicate_identity"
    case nonCanonicalOrder = "non_canonical_order"
    case invalidPageLimit = "invalid_page_limit"
    case providerPermissionDenied = "provider_permission_denied"
    case providerUnavailable = "provider_unavailable"
    case spoolCapacityExceeded = "spool_capacity_exceeded"
    case spoolPayloadTooLarge = "spool_payload_too_large"
    case spoolIntegrityFailure = "spool_integrity_failure"
    case spoolFilesystemFailure = "spool_filesystem_failure"
    case lifecycleRefused = "lifecycle_refused"
    /// A mail mechanism that cannot satisfy a control the adapter will not do
    /// without: it publishes no generation, or it cannot bound by date at the
    /// source. Distinct from `malformedEnvelope` because the operator's action
    /// is different — nothing about the request can be fixed.
    case mailMechanismUnsupported = "mail_mechanism_unsupported"
    /// A mail record refused at one of the WP-16 content bounds.
    case mailBoundRefused = "mail_bound_refused"
    case unclassified = "unclassified"

    /// Classify without quoting. `filesystemFailure` carries an `errno`, and even
    /// that number is dropped here — an errno is small, but it is one more
    /// channel than a class needs, and this type's whole value is that it has
    /// exactly one.
    public init(_ error: Error) {
        switch error {
        case let spool as ProtectedSpoolError:
            switch spool {
            case .invalidLimits, .itemNotFound, .itemAlreadyQuarantined:
                self = .lifecycleRefused
            case .unsafeDirectory, .pathCollision, .corruptItem:
                self = .spoolIntegrityFailure
            case .itemCapacityExceeded, .byteCapacityExceeded:
                self = .spoolCapacityExceeded
            case .payloadTooLarge:
                self = .spoolPayloadTooLarge
            case .filesystemFailure, .injectedCrash:
                self = .spoolFilesystemFailure
            }
        case let contract as NativeSourceContractError:
            switch contract {
            case .unsupportedVersion:
                self = .unsupportedVersion
            case .duplicateIdentity:
                self = .duplicateIdentity
            case .nonCanonicalOrder:
                self = .nonCanonicalOrder
            case .invalidPageLimit:
                self = .invalidPageLimit
            case .mailConsentAbsent:
                self = .providerPermissionDenied
            case .mailGenerationUnavailable, .mailDateBoundNotSourceSide:
                self = .mailMechanismUnsupported
            case .mailIdentityTooLong, .mailHeaderTooLarge, .mailBodyTooLarge,
                 .mailAttachmentLimitExceeded:
                self = .mailBoundRefused
            case .inconsistentDiscovery, .inconsistentEnvelope, .invalidTimeRange,
                 .mismatchedSourceKind, .unknownBucket, .missingSyntheticPage,
                 .duplicateSyntheticPage, .invalidRecurrence, .recurrenceLimitExceeded,
                 .mailInvalidIdentityComponent, .mailWindowNotDayAligned,
                 .mailDateBoundViolated, .mailContentInconsistent:
                self = .malformedEnvelope
            }
        case let provider as NativeProviderFailure:
            switch provider {
            case .permissionDenied:
                self = .providerPermissionDenied
            case .accountUnavailable, .bucketUnavailable, .transientUnavailable:
                self = .providerUnavailable
            case .unsupportedVersion:
                self = .unsupportedVersion
            case .invalidCursor, .malformedRequest:
                self = .malformedEnvelope
            case .capacityExceeded:
                self = .spoolCapacityExceeded
            case .payloadTooLarge:
                self = .spoolPayloadTooLarge
            case .integrityFailure:
                self = .spoolIntegrityFailure
            }
        case let lifecycle as NativeHostLifecycleError:
            _ = lifecycle
            self = .lifecycleRefused
        default:
            self = .unclassified
        }
    }
}

/// One operational observation. Counts, identities, types and an error class —
/// and structurally nothing else.
public struct NativeHostTelemetryEvent: Codable, Hashable, Sendable {
    public let event: NativeHostTelemetryEventClass
    public let protocolVersion: String
    public let hostInstanceID: NativeSourceOpaqueID
    public let kind: NativeSourceKind?
    public let itemCount: Int
    public let byteCount: Int64
    public let errorClass: NativeHostErrorClass?
    public let observedAtUnixMilliseconds: Int64

    public init(
        event: NativeHostTelemetryEventClass,
        protocolVersion: String = NativeSourceProtocolV1.identifier,
        hostInstanceID: NativeSourceOpaqueID,
        kind: NativeSourceKind? = nil,
        itemCount: Int = 0,
        byteCount: Int64 = 0,
        errorClass: NativeHostErrorClass? = nil,
        observedAtUnixMilliseconds: Int64
    ) throws {
        guard protocolVersion == NativeSourceProtocolV1.identifier else {
            throw NativeSourceContractError.unsupportedVersion
        }
        guard itemCount >= 0, byteCount >= 0 else {
            throw NativeSourceContractError.inconsistentEnvelope
        }
        self.event = event
        self.protocolVersion = protocolVersion
        self.hostInstanceID = hostInstanceID
        self.kind = kind
        self.itemCount = itemCount
        self.byteCount = byteCount
        self.errorClass = errorClass
        self.observedAtUnixMilliseconds = observedAtUnixMilliseconds
    }

    /// Classifies a failure into an event without ever holding the failure.
    public init(
        refusal error: Error,
        event: NativeHostTelemetryEventClass = .hostRefused,
        hostInstanceID: NativeSourceOpaqueID,
        kind: NativeSourceKind? = nil,
        observedAtUnixMilliseconds: Int64
    ) throws {
        try self.init(
            event: event,
            hostInstanceID: hostInstanceID,
            kind: kind,
            errorClass: NativeHostErrorClass(error),
            observedAtUnixMilliseconds: observedAtUnixMilliseconds
        )
    }

    private enum CodingKeys: String, CodingKey {
        case event, protocolVersion, hostInstanceID, kind, itemCount, byteCount,
             errorClass, observedAtUnixMilliseconds
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            event: values.decode(NativeHostTelemetryEventClass.self, forKey: .event),
            protocolVersion: values.decode(String.self, forKey: .protocolVersion),
            hostInstanceID: values.decode(NativeSourceOpaqueID.self, forKey: .hostInstanceID),
            kind: values.decodeIfPresent(NativeSourceKind.self, forKey: .kind),
            itemCount: values.decode(Int.self, forKey: .itemCount),
            byteCount: values.decode(Int64.self, forKey: .byteCount),
            errorClass: values.decodeIfPresent(NativeHostErrorClass.self, forKey: .errorClass),
            observedAtUnixMilliseconds: values.decode(
                Int64.self,
                forKey: .observedAtUnixMilliseconds
            )
        )
    }
}

/// Spool occupancy as counts against the configured bounds. The bound is part of
/// the health report on purpose: "eleven pending items" says nothing without the
/// limit it is eleven of, and an operator watching backpressure needs to see the
/// headroom rather than infer it.
public struct NativeHostSpoolHealth: Codable, Hashable, Sendable {
    public let pendingItemCount: Int
    public let quarantineItemCount: Int
    public let crashResidueItemCount: Int
    public let totalBytes: Int64
    public let maximumItems: Int
    public let maximumBytes: Int64
    public let maximumPayloadBytes: Int

    public init(inventory: ProtectedSpoolInventory, limits: ProtectedSpoolLimits) {
        self.pendingItemCount = inventory.items.filter { $0.state == .pending }.count
        self.quarantineItemCount = inventory.items.filter { $0.state == .quarantine }.count
        self.crashResidueItemCount = inventory.items.filter { $0.state == .crashResidue }.count
        self.totalBytes = inventory.totalBytes
        self.maximumItems = limits.maximumItems
        self.maximumBytes = limits.maximumBytes
        self.maximumPayloadBytes = limits.maximumPayloadBytes
    }

    public var itemCount: Int {
        pendingItemCount + quarantineItemCount + crashResidueItemCount
    }

    public var remainingItems: Int { max(0, maximumItems - itemCount) }

    public var remainingBytes: Int64 { max(0, maximumBytes - totalBytes) }

    /// True when the next enqueue will be *refused*. Refusal is the defined
    /// behaviour at the bound — the spool throws `itemCapacityExceeded` or
    /// `byteCapacityExceeded` and retains everything it already holds. Nothing
    /// is evicted, overwritten, or silently dropped to make room.
    public var atCapacity: Bool { remainingItems == 0 || remainingBytes == 0 }
}

/// What a health endpoint may say about this host. Assembled from the lifecycle
/// state and the spool bounds; it reaches no source, no account and no record.
public struct NativeHostHealthReport: Codable, Hashable, Sendable {
    public let protocolVersion: String
    public let hostInstanceID: NativeSourceOpaqueID
    public let lifecycleState: NativeHostLifecycleState
    public let distributionModel: NativeHostDistributionModel
    public let serviceRegistrationPerformed: Bool
    public let spool: NativeHostSpoolHealth
    public let observedAtUnixMilliseconds: Int64

    public init(
        protocolVersion: String = NativeSourceProtocolV1.identifier,
        hostInstanceID: NativeSourceOpaqueID,
        lifecycle: NativeHostLifecycle,
        spool: NativeHostSpoolHealth,
        observedAtUnixMilliseconds: Int64
    ) throws {
        guard protocolVersion == NativeSourceProtocolV1.identifier else {
            throw NativeSourceContractError.unsupportedVersion
        }
        self.protocolVersion = protocolVersion
        self.hostInstanceID = hostInstanceID
        self.lifecycleState = lifecycle.state
        self.distributionModel = lifecycle.distributionModel
        self.serviceRegistrationPerformed = lifecycle.serviceRegistrationPerformed
        self.spool = spool
        self.observedAtUnixMilliseconds = observedAtUnixMilliseconds
    }

    private enum CodingKeys: String, CodingKey {
        case protocolVersion, hostInstanceID, lifecycleState, distributionModel,
             serviceRegistrationPerformed, spool, observedAtUnixMilliseconds
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        let protocolVersion = try values.decode(String.self, forKey: .protocolVersion)
        guard protocolVersion == NativeSourceProtocolV1.identifier else {
            throw NativeSourceContractError.unsupportedVersion
        }
        self.protocolVersion = protocolVersion
        self.hostInstanceID = try values.decode(
            NativeSourceOpaqueID.self,
            forKey: .hostInstanceID
        )
        self.lifecycleState = try values.decode(
            NativeHostLifecycleState.self,
            forKey: .lifecycleState
        )
        self.distributionModel = try values.decode(
            NativeHostDistributionModel.self,
            forKey: .distributionModel
        )
        self.serviceRegistrationPerformed = try values.decode(
            Bool.self,
            forKey: .serviceRegistrationPerformed
        )
        self.spool = try values.decode(NativeHostSpoolHealth.self, forKey: .spool)
        self.observedAtUnixMilliseconds = try values.decode(
            Int64.self,
            forKey: .observedAtUnixMilliseconds
        )
        guard !serviceRegistrationPerformed else {
            throw NativeSourceContractError.inconsistentEnvelope
        }
    }
}

extension ProtectedSpool {
    /// Occupancy against the configured bounds. Reads directory metadata only —
    /// it opens no item and decodes no payload, so a health poll cannot become a
    /// content read even by accident.
    public func health() throws -> NativeHostSpoolHealth {
        NativeHostSpoolHealth(inventory: try inventory(), limits: configuredLimits)
    }
}
