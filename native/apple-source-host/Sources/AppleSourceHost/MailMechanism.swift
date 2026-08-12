import Foundation

/// WP-16's mechanism seam.
///
/// The shipping host links **no Apple framework**, which is WP-15's control 1
/// proved at link time; nothing here may change that. So the Mail adapter is
/// defined over a seam rather than over a framework: `MailMechanism` states
/// everything the adapter needs from whatever actually talks to a mail source,
/// and the adapter is the part that holds the bounds, the identity rules and the
/// refusals. A fixture drives the seam here. A live mechanism — if one is ever
/// permitted — implements the same seam in a target that is not this one.
///
/// Two properties of the seam are load-bearing and are worth stating before the
/// declarations, because both encode a *finding* rather than a convenience:
///
/// 1. **Every operation is a read.** There is no move, no delete, no flag, no
///    mark-as-read, and no consent *request*. The last of those is deliberate:
///    a seam with a `requestConsent` on it is a seam that can raise a TCC
///    dialogue, and TCC grants are operator-gated (EXT-04). The adapter can
///    observe that consent is absent and refuse. It cannot ask for it.
/// 2. **A mechanism that publishes no generation cannot be read from.** See
///    `MailMechanismDescriptor.publishesGeneration`. Message identity is only
///    stable within a generation, so a mechanism that cannot name its generation
///    cannot mint a stable identity, and minting one anyway would hand every
///    downstream reconciler an identifier that silently re-points.

// MARK: - Consent

/// What the mechanism can observe about consent **without asking for it**.
public enum MailConsentState: String, Codable, CaseIterable, Sendable {
    case granted
    case denied
    /// Consent has never been decided. This is not "try and see": on macOS the
    /// trying is what raises the dialogue, so the adapter treats it exactly like
    /// `denied` and stops before any read.
    case notDetermined = "not_determined"
    /// The mechanism's target is not present or not running.
    case targetUnavailable = "target_unavailable"
}

// MARK: - Mechanism identity and capabilities

public enum MailMechanismKind: String, Codable, CaseIterable, Sendable {
    /// The in-process fixture. IMAP-shaped: it publishes a generation, keys
    /// messages by an ordered provider key, and bounds by whole days.
    case fixtureImapShaped = "fixture_imap_shaped"
    /// Apple Mail driven through its scripting terminology. Present on this
    /// machine and operator-gated; see `AppleMailAutomationShapeProbe` and
    /// `docs/campaign/WP-16-MAIL-ADAPTER-RECORD.md`.
    case appleMailAutomation = "apple_mail_automation"
    /// An IMAP client. Structurally impossible inside this host — WP-15's
    /// control 2 forbids a socket anywhere under `native/` — and named here so
    /// that the impossibility is written down rather than rediscovered.
    case imapNetworkClient = "imap_network_client"
}

/// How far into the source a date bound actually reaches.
public enum MailDateBoundEnforcement: String, Codable, CaseIterable, Sendable {
    /// The source applies the exact millisecond interval.
    case sourceSideExact = "source_side_exact"
    /// The source applies a whole-day interval — IMAP `SEARCH SINCE`/`BEFORE`
    /// carry a date and no time — so the adapter widens the request to whole
    /// UTC days and refines the result back to the exact interval itself. The
    /// widening is always outward, never inward: narrowing at the source would
    /// drop records the caller asked for.
    case sourceSideDayGranular = "source_side_day_granular"
    /// The source cannot bound at all and the caller would have to filter after
    /// a full enumeration. The adapter **refuses** a date-bounded read against
    /// such a mechanism rather than performing the full scan, because
    /// "date-bounded without enumerating the whole store" is the acceptance and
    /// a client-side filter after a full scan is precisely not that.
    case clientSideAfterFullScan = "client_side_after_full_scan"
}

public struct MailMechanismDescriptor: Codable, Hashable, Sendable {
    public let mechanism: MailMechanismKind
    public let dateBound: MailDateBoundEnforcement
    /// Whether the mechanism can name the generation its provider keys belong
    /// to. IMAP publishes one (`UIDVALIDITY`). Apple Mail's scripting
    /// terminology publishes nothing equivalent, which is why an automation
    /// mechanism would set this `false` and be refused at read time.
    public let publishesGeneration: Bool
    /// Whether reaching this mechanism at all needs a grant only a human can
    /// give. Recorded, not enforced — the enforcement is `consentState()`.
    public let requiresOperatorConsent: Bool

    public init(
        mechanism: MailMechanismKind,
        dateBound: MailDateBoundEnforcement,
        publishesGeneration: Bool,
        requiresOperatorConsent: Bool
    ) {
        self.mechanism = mechanism
        self.dateBound = dateBound
        self.publishesGeneration = publishesGeneration
        self.requiresOperatorConsent = requiresOperatorConsent
    }
}

// MARK: - Identity

/// One component of a mail message identity.
///
/// The character set deliberately **excludes `:`**, which is what makes the
/// composed identifier in `MailMessageIdentity.recordIdentifier()` injective:
/// the last two colon-separated fields of the composed string are always the
/// generation and the provider key, so distinct triples cannot collide onto one
/// identifier. `NativeSourceOpaqueID` does admit `:`, so this restriction has to
/// live here rather than being inherited.
public struct MailIdentityComponent: RawRepresentable, Codable, Hashable, Sendable {
    public let rawValue: String

    public init?(rawValue: String) {
        let allowed = CharacterSet(
            charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._"
        )
        guard !rawValue.isEmpty,
              rawValue.utf8.count <= NativeSourceProtocolV1.maximumMailIdentityComponentBytes,
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
                debugDescription: "Invalid mail identity component"
            )
        }
        self = value
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(rawValue)
    }
}

/// A message identity that carries its own generation.
///
/// **This is the whole of WP-16 control 2 and it is worth being exact about.** A
/// provider key is stable only relative to a generation of the mailbox. IMAP
/// says so in as many words: a UID is unique and ascending *within a
/// `UIDVALIDITY` value*, and when the server changes `UIDVALIDITY` every UID the
/// client holds is meaningless. A stored identity that recorded only the UID
/// would therefore be a correct-looking identifier that silently starts pointing
/// at a different message.
///
/// So the generation is not metadata beside the identity — it is *inside* it.
/// When the generation changes, every identity changes, and a reconciler sees a
/// disjoint key space instead of a set of mismatched contents. That is the
/// intended behaviour, and the contract checks assert the change rather than
/// asserting stability across it.
public struct MailMessageIdentity: Codable, Hashable, Sendable {
    public let mailboxID: NativeSourceOpaqueID
    public let generation: MailIdentityComponent
    public let providerKey: MailIdentityComponent

    public init(
        mailboxID: NativeSourceOpaqueID,
        generation: MailIdentityComponent,
        providerKey: MailIdentityComponent
    ) {
        self.mailboxID = mailboxID
        self.generation = generation
        self.providerKey = providerKey
    }

    /// The record identifier this identity composes to.
    ///
    /// Throws rather than trimming when the composition would exceed
    /// `NativeSourceOpaqueID`'s ceiling. A trimmed identity is the one kind of
    /// truncation with no honest partial form: two distinct messages would
    /// silently become one record.
    public func recordIdentifier() throws -> NativeSourceOpaqueID {
        let composed = "\(mailboxID.rawValue):\(generation.rawValue):\(providerKey.rawValue)"
        guard let identifier = NativeSourceOpaqueID(rawValue: composed) else {
            throw NativeSourceContractError.mailIdentityTooLong
        }
        return identifier
    }
}

// MARK: - Traversal

/// A whole-UTC-day interval, which is the coarsest bound a source may apply
/// while still being a source-side bound.
///
/// The alignment is an invariant rather than a convention: a window that is not
/// day-aligned has not been widened, and a request that reaches a day-granular
/// source unwidened silently drops every record on the boundary days.
public struct MailDayWindow: Codable, Hashable, Sendable {
    public static let millisecondsPerDay: Int64 = 86_400_000

    public let startUnixMilliseconds: Int64
    public let endUnixMilliseconds: Int64

    public init(startUnixMilliseconds: Int64, endUnixMilliseconds: Int64) throws {
        guard startUnixMilliseconds <= endUnixMilliseconds,
              Self.isDayStart(startUnixMilliseconds),
              Self.isDayEnd(endUnixMilliseconds)
        else {
            throw NativeSourceContractError.mailWindowNotDayAligned
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

    /// Widens an exact interval outward to whole UTC days. Outward only: the
    /// widened window always contains the original.
    public static func widening(_ range: NativeTimeRange) throws -> MailDayWindow {
        try MailDayWindow(
            startUnixMilliseconds: dayFloor(range.startUnixMilliseconds),
            endUnixMilliseconds: dayFloor(range.endUnixMilliseconds) + millisecondsPerDay - 1
        )
    }

    /// Floor division, so that instants before 1970 round down rather than
    /// toward zero. Truncating division would widen the wrong way for a negative
    /// instant and lose the boundary day.
    public static func dayFloor(_ milliseconds: Int64) -> Int64 {
        let quotient = milliseconds / millisecondsPerDay
        let remainder = milliseconds % millisecondsPerDay
        return (remainder < 0 ? quotient - 1 : quotient) * millisecondsPerDay
    }

    private static func isDayStart(_ milliseconds: Int64) -> Bool {
        dayFloor(milliseconds) == milliseconds
    }

    private static func isDayEnd(_ milliseconds: Int64) -> Bool {
        dayFloor(milliseconds) + millisecondsPerDay - 1 == milliseconds
    }

    public func contains(_ milliseconds: Int64) -> Bool {
        milliseconds >= startUnixMilliseconds && milliseconds <= endUnixMilliseconds
    }
}

public struct MailTraversalQuery: Hashable, Sendable {
    public let mailboxID: NativeSourceOpaqueID
    /// Absent means "no date bound was asked for", never "scan everything and
    /// let the caller sort it out".
    public let window: MailDayWindow?
    /// Exclusive lower bound on the provider key, which is how the cursor is
    /// carried into the mechanism.
    public let afterProviderKey: MailIdentityComponent?
    public let limit: Int

    public init(
        mailboxID: NativeSourceOpaqueID,
        window: MailDayWindow?,
        afterProviderKey: MailIdentityComponent?,
        limit: Int
    ) throws {
        guard limit > 0, limit <= NativeSourceProtocolV1.maximumPageSize else {
            throw NativeSourceContractError.invalidPageLimit
        }
        self.mailboxID = mailboxID
        self.window = window
        self.afterProviderKey = afterProviderKey
        self.limit = limit
    }
}

public struct MailAccountDescriptor: Hashable, Sendable {
    public let id: NativeSourceOpaqueID
    public let displayLabel: String

    public init(id: NativeSourceOpaqueID, displayLabel: String) {
        self.id = id
        self.displayLabel = displayLabel
    }
}

public struct MailMailboxDescriptor: Hashable, Sendable {
    public let id: NativeSourceOpaqueID
    public let accountID: NativeSourceOpaqueID
    public let parentID: NativeSourceOpaqueID?
    public let displayLabel: String
    public let isSelectable: Bool

    public init(
        id: NativeSourceOpaqueID,
        accountID: NativeSourceOpaqueID,
        parentID: NativeSourceOpaqueID? = nil,
        displayLabel: String,
        isSelectable: Bool
    ) {
        self.id = id
        self.accountID = accountID
        self.parentID = parentID
        self.displayLabel = displayLabel
        self.isSelectable = isSelectable
    }
}

public enum MailAttachmentDisposition: String, Codable, CaseIterable, Sendable {
    case metadataOnly = "metadata_only"
    case omittedOversize = "omitted_oversize"
    case omittedNotDownloaded = "omitted_not_downloaded"
}

/// An attachment, described and never carried.
///
/// There is no `bytes` field and there is not going to be one by accident: the
/// bound on attachment size is enforced by the type having nowhere to put an
/// attachment, which is the same shape WP-15 used for content-free telemetry. A
/// 2 GB attachment costs this record a few dozen bytes.
public struct MailAttachmentDescriptor: Codable, Hashable, Sendable {
    public let id: NativeSourceOpaqueID
    public let mimeType: String
    public let byteSize: Int
    public let disposition: MailAttachmentDisposition

    public init(
        id: NativeSourceOpaqueID,
        mimeType: String,
        byteSize: Int,
        disposition: MailAttachmentDisposition
    ) throws {
        guard byteSize >= 0 else {
            throw NativeSourceContractError.mailContentInconsistent
        }
        guard byteSize <= NativeSourceProtocolV1.maximumMailAttachmentBytes
            || disposition == .omittedOversize
        else {
            throw NativeSourceContractError.mailContentInconsistent
        }
        self.id = id
        self.mimeType = mimeType
        self.byteSize = byteSize
        self.disposition = disposition
    }

    private enum CodingKeys: String, CodingKey { case id, mimeType, byteSize, disposition }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            id: values.decode(NativeSourceOpaqueID.self, forKey: .id),
            mimeType: values.decode(String.self, forKey: .mimeType),
            byteSize: values.decode(Int.self, forKey: .byteSize),
            disposition: values.decode(MailAttachmentDisposition.self, forKey: .disposition)
        )
    }
}

public struct MailMessageSummary: Hashable, Sendable {
    public let providerKey: MailIdentityComponent
    public let receivedUnixMilliseconds: Int64
    public let sentUnixMilliseconds: Int64?
    public let attachments: [MailAttachmentDescriptor]

    public init(
        providerKey: MailIdentityComponent,
        receivedUnixMilliseconds: Int64,
        sentUnixMilliseconds: Int64?,
        attachments: [MailAttachmentDescriptor]
    ) {
        self.providerKey = providerKey
        self.receivedUnixMilliseconds = receivedUnixMilliseconds
        self.sentUnixMilliseconds = sentUnixMilliseconds
        self.attachments = attachments
    }
}

public struct MailTraversalResult: Hashable, Sendable {
    public let summaries: [MailMessageSummary]
    /// The generation these provider keys belong to.
    public let generation: MailIdentityComponent
    /// The mechanism's own declaration that satisfying this query required
    /// walking the whole mailbox. A date-bounded read against a mechanism that
    /// says `true` is refused: the descriptor's claim about where the bound is
    /// applied and the result's claim have to agree, and this is the half that
    /// cannot be got right by writing an optimistic descriptor.
    public let scannedWholeMailbox: Bool

    public init(
        summaries: [MailMessageSummary],
        generation: MailIdentityComponent,
        scannedWholeMailbox: Bool
    ) {
        self.summaries = summaries
        self.generation = generation
        self.scannedWholeMailbox = scannedWholeMailbox
    }
}

public struct MailMessageContent: Hashable, Sendable {
    public let headerBytes: [UInt8]
    /// `nil` means the mechanism refused the body before reading it. When the
    /// body was read, this is the complete value, never a prefix.
    public let bodyBytes: [UInt8]?
    /// Exact size when known. A production mechanism may leave this `nil` when
    /// it conservatively omits a body from a provider-level size upper bound.
    public let bodyByteSize: Int?
    public let attachments: [MailAttachmentDescriptor]
    public let attachmentCount: Int

    public init(headerBytes: [UInt8], bodyBytes: [UInt8], attachments: [MailAttachmentDescriptor]) {
        self.headerBytes = headerBytes
        self.bodyBytes = bodyBytes
        self.bodyByteSize = bodyBytes.count
        self.attachments = attachments
        self.attachmentCount = attachments.count
    }

    public init(
        headerBytes: [UInt8],
        bodyBytes: [UInt8]?,
        bodyByteSize: Int?,
        attachments: [MailAttachmentDescriptor],
        attachmentCount: Int
    ) {
        self.headerBytes = headerBytes
        self.bodyBytes = bodyBytes
        self.bodyByteSize = bodyByteSize
        self.attachments = attachments
        self.attachmentCount = attachmentCount
    }
}

// MARK: - The seam

/// Everything the bounded adapter needs from whatever actually reads mail.
///
/// The operation set is closed and every member of it is a read.
/// `tests/architecture/test_wp16_mail_adapter.py::test_the_mail_mechanism_seam_declares_only_read_operations`
/// holds it to exactly these five, so adding a sixth is a decision somebody has
/// to make on purpose rather than a line in a diff.
public protocol MailMechanism: Sendable {
    var descriptor: MailMechanismDescriptor { get }
    func consentState() throws -> MailConsentState
    func accounts() throws -> [MailAccountDescriptor]
    func mailboxes() throws -> [MailMailboxDescriptor]
    func messageSummaries(_ query: MailTraversalQuery) throws -> MailTraversalResult
    func messageContent(_ identity: MailMessageIdentity) throws -> MailMessageContent
}
