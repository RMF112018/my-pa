/// The frozen identifier for the first source-host protocol boundary.
public enum NativeSourceProtocolV1 {
    public static let identifier = "my-pa.native-source.v1"
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
        guard !rawValue.isEmpty, !rawValue.contains(where: { $0.isWhitespace }) else {
            return nil
        }
        self.rawValue = rawValue
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
}

public struct NativeReadCursor: RawRepresentable, Codable, Hashable, Sendable {
    public let rawValue: String

    public init?(rawValue: String) {
        guard !rawValue.isEmpty, !rawValue.contains(where: { $0.isWhitespace }) else {
            return nil
        }
        self.rawValue = rawValue
    }
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
        guard limit > 0 else {
            throw NativeSourceContractError.invalidPageLimit
        }
        self.bucketID = bucketID
        self.timeRange = timeRange
        self.cursor = cursor
        self.limit = limit
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

    public init(records: [NativeSourceRecord], nextCursor: NativeReadCursor?) {
        self.records = records
        self.nextCursor = nextCursor
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
}
