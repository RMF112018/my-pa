import Foundation

/// The frozen identifier for the first source-host protocol boundary.
public enum NativeSourceProtocolV1 {
    public static let identifier = "my-pa.native-source.v1"
    public static let supportedIdentifiers = [identifier]
    /// Frozen page ceiling. An unbounded page is an unbounded spool item, so the
    /// bound belongs to the protocol rather than to whichever adapter happens to
    /// build the page. Over-bound input is **refused**, never clamped: silently
    /// serving 100 of the 5000 records asked for is data loss the caller cannot
    /// see. Must equal `NATIVE_SOURCE_MAX_PAGE_SIZE` in
    /// `src/my_pa/contracts/v1/native_sources.py`; a test compares the literals.
    public static let maximumPageSize = 100
    /// Frozen cursor ceiling, in UTF-8 bytes. Must equal the `next_cursor`
    /// `max_length` on `NativeAdmissionEnvelope`.
    public static let maximumCursorBytes = 512
}

/// Source categories supported by protocol v1. These are product categories,
/// not names of a concrete operating-system framework or provider API.
public enum NativeSourceKind: String, Codable, CaseIterable, Sendable {
    case mail
    case calendar
    case contacts
}

/// An identifier whose provider locator remains outside the public protocol.
public struct NativeSourceOpaqueID: RawRepresentable, Codable, Hashable, Sendable {
    public let rawValue: String

    public init?(rawValue: String) {
        let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._:")
        guard !rawValue.isEmpty,
              rawValue.utf8.count <= 200,
              rawValue.first?.isLetter == true || rawValue.first?.isNumber == true,
              rawValue.last?.isLetter == true || rawValue.last?.isNumber == true,
              rawValue.unicodeScalars.allSatisfy(allowed.contains)
        else {
            return nil
        }
        self.rawValue = rawValue
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        let rawValue = try container.decode(String.self)
        guard let value = Self(rawValue: rawValue) else {
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Invalid opaque identifier"
            )
        }
        self = value
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(rawValue)
    }
}

public struct NativeSourceAccount: Codable, Hashable, Sendable {
    public let id: NativeSourceOpaqueID
    public let kind: NativeSourceKind
    public let displayLabel: String

    public init(id: NativeSourceOpaqueID, kind: NativeSourceKind, displayLabel: String) {
        self.id = id
        self.kind = kind
        self.displayLabel = displayLabel
    }
}

public struct NativeSourceBucket: Codable, Hashable, Sendable {
    public let id: NativeSourceOpaqueID
    public let accountID: NativeSourceOpaqueID
    public let parentID: NativeSourceOpaqueID?
    public let kind: NativeSourceKind
    public let displayLabel: String
    public let isSelectable: Bool

    public init(
        id: NativeSourceOpaqueID,
        accountID: NativeSourceOpaqueID,
        parentID: NativeSourceOpaqueID? = nil,
        kind: NativeSourceKind,
        displayLabel: String,
        isSelectable: Bool
    ) {
        self.id = id
        self.accountID = accountID
        self.parentID = parentID
        self.kind = kind
        self.displayLabel = displayLabel
        self.isSelectable = isSelectable
    }
}

public struct NativeDiscoverySnapshot: Codable, Hashable, Sendable {
    public let protocolVersion: String
    public let kind: NativeSourceKind
    public let accounts: [NativeSourceAccount]
    public let buckets: [NativeSourceBucket]

    public init(
        kind: NativeSourceKind,
        accounts: [NativeSourceAccount],
        buckets: [NativeSourceBucket]
    ) throws {
        guard accounts.allSatisfy({ $0.kind == kind }),
              buckets.allSatisfy({ $0.kind == kind }),
              buckets.allSatisfy({ bucket in accounts.contains(where: { $0.id == bucket.accountID }) })
        else {
            throw NativeSourceContractError.inconsistentDiscovery
        }
        self.protocolVersion = NativeSourceProtocolV1.identifier
        self.kind = kind
        self.accounts = accounts
        self.buckets = buckets
    }

    private enum CodingKeys: String, CodingKey {
        case protocolVersion, kind, accounts, buckets
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        let protocolVersion = try values.decode(String.self, forKey: .protocolVersion)
        guard protocolVersion == NativeSourceProtocolV1.identifier else {
            throw NativeSourceContractError.unsupportedVersion
        }
        try self.init(
            kind: values.decode(NativeSourceKind.self, forKey: .kind),
            accounts: values.decode([NativeSourceAccount].self, forKey: .accounts),
            buckets: values.decode([NativeSourceBucket].self, forKey: .buckets)
        )
    }
}

/// An inclusive, source-neutral UTC interval represented without importing a
/// date or operating-system framework.
public struct NativeTimeRange: Codable, Hashable, Sendable {
    public let startUnixMilliseconds: Int64
    public let endUnixMilliseconds: Int64

    public init(startUnixMilliseconds: Int64, endUnixMilliseconds: Int64) throws {
        guard startUnixMilliseconds <= endUnixMilliseconds else {
            throw NativeSourceContractError.invalidTimeRange
        }
        self.startUnixMilliseconds = startUnixMilliseconds
        self.endUnixMilliseconds = endUnixMilliseconds
    }

    private enum CodingKeys: String, CodingKey {
        case startUnixMilliseconds, endUnixMilliseconds
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            startUnixMilliseconds: values.decode(Int64.self, forKey: .startUnixMilliseconds),
            endUnixMilliseconds: values.decode(Int64.self, forKey: .endUnixMilliseconds)
        )
    }
}

public struct NativeReadCursor: RawRepresentable, Codable, Hashable, Sendable {
    public let rawValue: String

    public init?(rawValue: String) {
        guard !rawValue.isEmpty,
              rawValue.utf8.count <= NativeSourceProtocolV1.maximumCursorBytes,
              !rawValue.contains(where: { $0.isWhitespace })
        else {
            return nil
        }
        self.rawValue = rawValue
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        let rawValue = try container.decode(String.self)
        guard let value = Self(rawValue: rawValue) else {
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Invalid read cursor"
            )
        }
        self = value
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(rawValue)
    }
}

/// Stable, content-free failure vocabulary shared by synthetic host envelopes.
public enum NativeProviderFailure: String, Codable, CaseIterable, Error, Sendable {
    case permissionDenied = "permission_denied"
    case accountUnavailable = "account_unavailable"
    case bucketUnavailable = "bucket_unavailable"
    case transientUnavailable = "transient_unavailable"
    case invalidCursor = "invalid_cursor"
    case unsupportedVersion = "unsupported_version"
    case malformedRequest = "malformed_request"
    case capacityExceeded = "capacity_exceeded"
    case payloadTooLarge = "payload_too_large"
    case integrityFailure = "integrity_failure"
}

public struct NativeReadRequest: Codable, Hashable, Sendable {
    public let bucketID: NativeSourceOpaqueID
    public let timeRange: NativeTimeRange?
    public let cursor: NativeReadCursor?
    public let limit: Int

    public init(
        bucketID: NativeSourceOpaqueID,
        timeRange: NativeTimeRange? = nil,
        cursor: NativeReadCursor? = nil,
        limit: Int
    ) throws {
        guard limit > 0, limit <= NativeSourceProtocolV1.maximumPageSize else {
            throw NativeSourceContractError.invalidPageLimit
        }
        self.bucketID = bucketID
        self.timeRange = timeRange
        self.cursor = cursor
        self.limit = limit
    }

    private enum CodingKeys: String, CodingKey {
        case bucketID, timeRange, cursor, limit
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            bucketID: values.decode(NativeSourceOpaqueID.self, forKey: .bucketID),
            timeRange: values.decodeIfPresent(NativeTimeRange.self, forKey: .timeRange),
            cursor: values.decodeIfPresent(NativeReadCursor.self, forKey: .cursor),
            limit: values.decode(Int.self, forKey: .limit)
        )
    }
}

/// Immutable source evidence. Payload bytes are returned to the admitting
/// application boundary; this type grants no mutation authority.
public struct NativeSourceRecord: Codable, Hashable, Sendable {
    public let id: NativeSourceOpaqueID
    public let bucketID: NativeSourceOpaqueID
    public let kind: NativeSourceKind
    public let sourceRevision: String
    public let sourceModifiedUnixMilliseconds: Int64?
    public let payload: [UInt8]

    public init(
        id: NativeSourceOpaqueID,
        bucketID: NativeSourceOpaqueID,
        kind: NativeSourceKind,
        sourceRevision: String,
        sourceModifiedUnixMilliseconds: Int64?,
        payload: [UInt8]
    ) {
        self.id = id
        self.bucketID = bucketID
        self.kind = kind
        self.sourceRevision = sourceRevision
        self.sourceModifiedUnixMilliseconds = sourceModifiedUnixMilliseconds
        self.payload = payload
    }
}

public struct NativeReadPage: Codable, Hashable, Sendable {
    public let records: [NativeSourceRecord]
    public let nextCursor: NativeReadCursor?

    /// Refuses an over-bound page rather than truncating it. Trimming to the
    /// ceiling here would drop records the caller never learns about and would
    /// make `nextCursor` a lie; the honest answer to "more than the protocol
    /// admits" is to not produce the page at all.
    public init(records: [NativeSourceRecord], nextCursor: NativeReadCursor?) throws {
        guard records.count <= NativeSourceProtocolV1.maximumPageSize else {
            throw NativeSourceContractError.invalidPageLimit
        }
        self.records = records
        self.nextCursor = nextCursor
    }

    private enum CodingKeys: String, CodingKey {
        case records, nextCursor
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            records: values.decode([NativeSourceRecord].self, forKey: .records),
            nextCursor: values.decodeIfPresent(NativeReadCursor.self, forKey: .nextCursor)
        )
    }
}

public enum NativeSourceContractError: Error, Equatable, Sendable {
    case inconsistentDiscovery
    case invalidTimeRange
    case invalidPageLimit
    case mismatchedSourceKind
    case unknownBucket
    case missingSyntheticPage
    case duplicateSyntheticPage
    case duplicateIdentity
    case nonCanonicalOrder
    case unsupportedVersion
    case inconsistentEnvelope
    case invalidRecurrence
    case recurrenceLimitExceeded
}
