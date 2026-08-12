import Foundation

/// How complete a mail record is, stated in numbers rather than in a flag.
///
/// Partiality is always *quantified*: the true body size and the true
/// attachment count are recorded whether or not the body and the descriptors
/// were carried. A consumer can therefore tell the difference between "this
/// message has no body" and "this message's body was too large to carry, and it
/// was 4 MB", which is the difference a truncation destroys.
public struct MailContentCompleteness: Codable, Hashable, Sendable {
    public let bodyIncluded: Bool
    public let bodyByteSize: Int
    public let attachmentCount: Int
    public let attachmentsDescribed: Int

    public init(
        bodyIncluded: Bool,
        bodyByteSize: Int,
        attachmentCount: Int,
        attachmentsDescribed: Int
    ) throws {
        guard bodyByteSize >= 0,
              attachmentCount >= 0,
              attachmentsDescribed >= 0,
              attachmentsDescribed <= attachmentCount,
              attachmentsDescribed <= NativeSourceProtocolV1.maximumMailAttachmentDescriptors
        else {
            throw NativeSourceContractError.mailContentInconsistent
        }
        self.bodyIncluded = bodyIncluded
        self.bodyByteSize = bodyByteSize
        self.attachmentCount = attachmentCount
        self.attachmentsDescribed = attachmentsDescribed
    }

    public var isPartial: Bool {
        !bodyIncluded || attachmentsDescribed < attachmentCount
    }

    private enum CodingKeys: String, CodingKey {
        case bodyIncluded, bodyByteSize, attachmentCount, attachmentsDescribed
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            bodyIncluded: values.decode(Bool.self, forKey: .bodyIncluded),
            bodyByteSize: values.decode(Int.self, forKey: .bodyByteSize),
            attachmentCount: values.decode(Int.self, forKey: .attachmentCount),
            attachmentsDescribed: values.decode(Int.self, forKey: .attachmentsDescribed)
        )
    }
}

/// The bytes one mail record carries, and the invariant that makes truncation
/// structurally impossible.
///
/// `body != nil` implies `body!.count == completeness.bodyByteSize`. A truncated
/// body has fewer bytes than the size it claims, so it cannot be constructed and
/// it cannot be decoded — the check is on `init` **and** on `init(from:)`,
/// because a bound enforced only on the initialiser is a bound that can be
/// walked around by handing the host JSON, which is the pattern WP-15 fixed for
/// the page and cursor ceilings.
///
/// The only permitted partial forms are *whole* omissions, and each records what
/// it omitted.
public struct MailRecordContent: Codable, Hashable, Sendable {
    public let identity: MailMessageIdentity
    public let receivedUnixMilliseconds: Int64
    public let sentUnixMilliseconds: Int64?
    public let headers: [UInt8]
    public let body: [UInt8]?
    public let attachments: [MailAttachmentDescriptor]
    public let completeness: MailContentCompleteness

    public init(
        identity: MailMessageIdentity,
        receivedUnixMilliseconds: Int64,
        sentUnixMilliseconds: Int64?,
        headers: [UInt8],
        body: [UInt8]?,
        attachments: [MailAttachmentDescriptor],
        completeness: MailContentCompleteness
    ) throws {
        guard headers.count <= NativeSourceProtocolV1.maximumMailHeaderBytes else {
            throw NativeSourceContractError.mailHeaderTooLarge
        }
        guard (body != nil) == completeness.bodyIncluded else {
            throw NativeSourceContractError.mailContentInconsistent
        }
        if let body {
            guard body.count == completeness.bodyByteSize else {
                throw NativeSourceContractError.mailContentInconsistent
            }
            guard body.count <= NativeSourceProtocolV1.maximumMailBodyBytes else {
                throw NativeSourceContractError.mailBodyTooLarge
            }
        }
        guard attachments.count == completeness.attachmentsDescribed else {
            throw NativeSourceContractError.mailContentInconsistent
        }
        guard attachments.count <= NativeSourceProtocolV1.maximumMailAttachmentDescriptors else {
            throw NativeSourceContractError.mailAttachmentLimitExceeded
        }
        self.identity = identity
        self.receivedUnixMilliseconds = receivedUnixMilliseconds
        self.sentUnixMilliseconds = sentUnixMilliseconds
        self.headers = headers
        self.body = body
        self.attachments = attachments
        self.completeness = completeness
    }

    private enum CodingKeys: String, CodingKey {
        case identity, receivedUnixMilliseconds, sentUnixMilliseconds
        case headers, body, attachments, completeness
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            identity: values.decode(MailMessageIdentity.self, forKey: .identity),
            receivedUnixMilliseconds: values.decode(Int64.self, forKey: .receivedUnixMilliseconds),
            sentUnixMilliseconds: values.decodeIfPresent(
                Int64.self,
                forKey: .sentUnixMilliseconds
            ),
            headers: values.decode([UInt8].self, forKey: .headers),
            body: values.decodeIfPresent([UInt8].self, forKey: .body),
            attachments: values.decode([MailAttachmentDescriptor].self, forKey: .attachments),
            completeness: values.decode(MailContentCompleteness.self, forKey: .completeness)
        )
    }
}

/// The WP-16 Mail adapter: bounded, read-only, and framework-free.
///
/// It implements the existing `MailReadAdapter` over `MailMechanism`. Everything
/// that makes the read safe lives here rather than in the mechanism, so a future
/// live mechanism inherits the refusals instead of being trusted to reimplement
/// them:
///
/// * consent is checked **before** the first read, and a mechanism that is not
///   granted is never called again on that request;
/// * a mechanism that publishes no generation is refused outright;
/// * a date-bounded read against a mechanism that can only filter client-side is
///   refused rather than performed;
/// * the mechanism's own answer is re-checked against the window it was given,
///   so a mechanism that ignores its bound is caught rather than believed;
/// * bodies are carried whole or omitted whole; attachment bytes are never
///   carried at all;
/// * ordering and uniqueness are re-derived here, because the cursor is only
///   sound if the provider keys strictly ascend.
public struct BoundedMailReadAdapter: MailReadAdapter, Sendable {
    private let mechanism: any MailMechanism

    public init(mechanism: any MailMechanism) {
        self.mechanism = mechanism
    }

    public var descriptor: MailMechanismDescriptor { mechanism.descriptor }

    // MARK: Discovery

    public func discoverMail() throws -> NativeDiscoverySnapshot {
        try requireConsent()
        let accounts = try mechanism.accounts().map {
            NativeSourceAccount(id: $0.id, kind: .mail, displayLabel: $0.displayLabel)
        }
        let buckets = try mechanism.mailboxes().map {
            NativeSourceBucket(
                id: $0.id,
                accountID: $0.accountID,
                parentID: $0.parentID,
                kind: .mail,
                displayLabel: $0.displayLabel,
                isSelectable: $0.isSelectable
            )
        }
        return try NativeDiscoverySnapshot(
            kind: .mail,
            accounts: accounts.sorted { $0.id.rawValue < $1.id.rawValue },
            buckets: buckets.sorted { $0.id.rawValue < $1.id.rawValue }
        )
    }

    // MARK: Traversal

    public func readMail(_ request: NativeReadRequest) throws -> NativeReadPage {
        try requireConsent()
        guard mechanism.descriptor.publishesGeneration else {
            throw NativeSourceContractError.mailGenerationUnavailable
        }

        let window = try plannedWindow(for: request.timeRange)
        let after = try request.cursor.map { cursor -> MailIdentityComponent in
            guard let component = MailIdentityComponent(rawValue: cursor.rawValue) else {
                throw NativeSourceContractError.mailInvalidIdentityComponent
            }
            return component
        }
        let query = try MailTraversalQuery(
            mailboxID: request.bucketID,
            window: window,
            afterProviderKey: after,
            limit: request.limit
        )
        let result = try mechanism.messageSummaries(query)

        if request.timeRange != nil, result.scannedWholeMailbox {
            throw NativeSourceContractError.mailDateBoundNotSourceSide
        }
        guard result.summaries.count <= request.limit else {
            throw NativeSourceContractError.invalidPageLimit
        }
        try requireStrictlyAscendingUniqueKeys(result.summaries, after: after)
        if let window {
            guard result.summaries.allSatisfy({ window.contains($0.receivedUnixMilliseconds) })
            else {
                throw NativeSourceContractError.mailDateBoundViolated
            }
        }

        let admitted = result.summaries.filter { summary in
            guard let range = request.timeRange else { return true }
            return summary.receivedUnixMilliseconds >= range.startUnixMilliseconds
                && summary.receivedUnixMilliseconds <= range.endUnixMilliseconds
        }
        let records = try admitted.map { summary in
            try record(for: summary, generation: result.generation, bucketID: request.bucketID)
        }
        let nextCursor = result.summaries.count == request.limit
            ? result.summaries.last.flatMap { NativeReadCursor(rawValue: $0.providerKey.rawValue) }
            : nil
        return try NativeReadPage(records: records, nextCursor: nextCursor)
    }

    // MARK: Internals

    private func requireConsent() throws {
        switch try mechanism.consentState() {
        case .granted:
            return
        case .denied, .notDetermined:
            throw NativeProviderFailure.permissionDenied
        case .targetUnavailable:
            throw NativeProviderFailure.accountUnavailable
        }
    }

    private func plannedWindow(for range: NativeTimeRange?) throws -> MailDayWindow? {
        guard let range else { return nil }
        switch mechanism.descriptor.dateBound {
        case .clientSideAfterFullScan:
            throw NativeSourceContractError.mailDateBoundNotSourceSide
        case .sourceSideExact, .sourceSideDayGranular:
            return try MailDayWindow.widening(range)
        }
    }

    private func requireStrictlyAscendingUniqueKeys(
        _ summaries: [MailMessageSummary],
        after: MailIdentityComponent?
    ) throws {
        var previous = after?.rawValue
        for summary in summaries {
            if let previous, summary.providerKey.rawValue <= previous {
                throw NativeSourceContractError.nonCanonicalOrder
            }
            previous = summary.providerKey.rawValue
        }
    }

    private func record(
        for summary: MailMessageSummary,
        generation: MailIdentityComponent,
        bucketID: NativeSourceOpaqueID
    ) throws -> NativeSourceRecord {
        let identity = MailMessageIdentity(
            mailboxID: bucketID,
            generation: generation,
            providerKey: summary.providerKey
        )
        let content = try mechanism.messageContent(identity)
        let bodyFits = content.bodyBytes.count <= NativeSourceProtocolV1.maximumMailBodyBytes
        let described = Array(
            content.attachments.prefix(NativeSourceProtocolV1.maximumMailAttachmentDescriptors)
        )
        let completeness = try MailContentCompleteness(
            bodyIncluded: bodyFits,
            bodyByteSize: content.bodyBytes.count,
            attachmentCount: content.attachments.count,
            attachmentsDescribed: described.count
        )
        let payload = try MailRecordContent(
            identity: identity,
            receivedUnixMilliseconds: summary.receivedUnixMilliseconds,
            sentUnixMilliseconds: summary.sentUnixMilliseconds,
            headers: content.headerBytes,
            body: bodyFits ? content.bodyBytes : nil,
            attachments: described,
            completeness: completeness
        )
        return NativeSourceRecord(
            id: try identity.recordIdentifier(),
            bucketID: bucketID,
            kind: .mail,
            sourceRevision: generation.rawValue,
            sourceModifiedUnixMilliseconds: summary.receivedUnixMilliseconds,
            payload: Array(try JSONEncoder().encode(payload))
        )
    }
}
