import Foundation

/// One fixture message. Every value used with this type in this repository is
/// obviously synthetic — `person-a@example.invalid`, `Fixture Subject 001` —
/// because `.invalid` is the reserved TLD and a fixture that could be mistaken
/// for a real mailbox is a privacy incident waiting for a careless `grep`.
public struct FixtureMailMessage: Hashable, Sendable {
    public let providerKey: MailIdentityComponent
    public let receivedUnixMilliseconds: Int64
    public let sentUnixMilliseconds: Int64?
    public let headerBytes: [UInt8]
    public let bodyBytes: [UInt8]
    public let attachments: [MailAttachmentDescriptor]

    public init(
        providerKey: MailIdentityComponent,
        receivedUnixMilliseconds: Int64,
        sentUnixMilliseconds: Int64?,
        headerBytes: [UInt8],
        bodyBytes: [UInt8],
        attachments: [MailAttachmentDescriptor] = []
    ) {
        self.providerKey = providerKey
        self.receivedUnixMilliseconds = receivedUnixMilliseconds
        self.sentUnixMilliseconds = sentUnixMilliseconds
        self.headerBytes = headerBytes
        self.bodyBytes = bodyBytes
        self.attachments = attachments
    }
}

/// Ways a mechanism can be wrong, so that the adapter's re-checks are exercised
/// rather than merely written.
///
/// Each of these is a real failure mode of a real mechanism: a source that
/// ignores the date bound it was given, one that satisfies the bound by walking
/// everything, and one that returns messages in an order the cursor cannot
/// resume from.
public enum FixtureMailFault: Hashable, Sendable {
    case none
    case ignoreTheWindow
    case declareWholeMailboxScan
    case returnKeysOutOfOrder
}

/// The in-process mechanism the WP-16 harness drives.
///
/// **Level of proof, stated plainly: in-process, not over a socket.** A loopback
/// IMAP responder would prove the wire grammar, and it is not merely
/// disproportionate here — it is forbidden. WP-15's control 2 scans *every* file
/// under `native/` for the raw Darwin networking primitives and for the
/// framework-level network clients above them, so a listening or connecting
/// harness anywhere in this package — test targets included — turns that guard
/// red. The record says so rather than implying coverage this harness does not
/// have.
///
/// Mutable state with plain `var`s and `@unchecked Sendable`: the contract-check
/// executable drives this from one thread, and the call counters exist so that
/// "no read happened" can be *measured* after a refusal rather than inferred
/// from reading the adapter.
public final class FixtureMailMechanism: MailMechanism, @unchecked Sendable {
    public let descriptor: MailMechanismDescriptor

    private let accountDescriptors: [MailAccountDescriptor]
    private let mailboxDescriptors: [MailMailboxDescriptor]
    private var messages: [FixtureMailMessage]
    private var currentGeneration: MailIdentityComponent
    private var consent: MailConsentState
    private var fault: FixtureMailFault

    public private(set) var consentCalls = 0
    public private(set) var accountCalls = 0
    public private(set) var mailboxCalls = 0
    public private(set) var summaryCalls = 0
    public private(set) var contentCalls = 0

    public init(
        descriptor: MailMechanismDescriptor,
        accounts: [MailAccountDescriptor],
        mailboxes: [MailMailboxDescriptor],
        messages: [FixtureMailMessage],
        generation: MailIdentityComponent,
        consent: MailConsentState = .granted,
        fault: FixtureMailFault = .none
    ) {
        self.descriptor = descriptor
        self.accountDescriptors = accounts
        self.mailboxDescriptors = mailboxes
        self.messages = messages.sorted { $0.providerKey.rawValue < $1.providerKey.rawValue }
        self.currentGeneration = generation
        self.consent = consent
        self.fault = fault
    }

    // MARK: Harness controls — not part of `MailMechanism`

    public func setConsent(_ state: MailConsentState) {
        consent = state
    }

    public func setFault(_ value: FixtureMailFault) {
        fault = value
    }

    /// A sync cycle that adds mail without invalidating what the client holds.
    /// Provider keys already issued keep meaning what they meant.
    public func syncPreservingGeneration(adding added: [FixtureMailMessage]) {
        messages = (messages + added)
            .sorted { $0.providerKey.rawValue < $1.providerKey.rawValue }
    }

    /// The other kind of sync cycle: the source re-generates its key space. This
    /// is IMAP's `UIDVALIDITY` bump, and everything the client holds becomes
    /// meaningless. The adapter is *supposed* to produce different identities
    /// afterwards.
    public func regenerate(as generation: MailIdentityComponent) {
        currentGeneration = generation
    }

    public func resetCallCounters() {
        consentCalls = 0
        accountCalls = 0
        mailboxCalls = 0
        summaryCalls = 0
        contentCalls = 0
    }

    public var readCalls: Int {
        accountCalls + mailboxCalls + summaryCalls + contentCalls
    }

    // MARK: MailMechanism

    public func consentState() throws -> MailConsentState {
        consentCalls += 1
        return consent
    }

    public func accounts() throws -> [MailAccountDescriptor] {
        accountCalls += 1
        return accountDescriptors
    }

    public func mailboxes() throws -> [MailMailboxDescriptor] {
        mailboxCalls += 1
        return mailboxDescriptors
    }

    public func messageSummaries(_ query: MailTraversalQuery) throws -> MailTraversalResult {
        summaryCalls += 1
        var selected = messages
        if let window = query.window, fault != .ignoreTheWindow {
            selected = selected.filter { window.contains($0.receivedUnixMilliseconds) }
        }
        if let after = query.afterProviderKey {
            selected = selected.filter { $0.providerKey.rawValue > after.rawValue }
        }
        selected = Array(selected.prefix(query.limit))
        if fault == .returnKeysOutOfOrder {
            selected.reverse()
        }
        return MailTraversalResult(
            summaries: selected.map {
                MailMessageSummary(
                    providerKey: $0.providerKey,
                    receivedUnixMilliseconds: $0.receivedUnixMilliseconds,
                    sentUnixMilliseconds: $0.sentUnixMilliseconds,
                    attachments: $0.attachments
                )
            },
            generation: currentGeneration,
            scannedWholeMailbox: fault == .declareWholeMailboxScan || query.window == nil
        )
    }

    public func messageContent(_ identity: MailMessageIdentity) throws -> MailMessageContent {
        contentCalls += 1
        guard let message = messages.first(where: {
            $0.providerKey.rawValue == identity.providerKey.rawValue
        }) else {
            throw NativeProviderFailure.bucketUnavailable
        }
        return MailMessageContent(
            headerBytes: message.headerBytes,
            bodyBytes: message.bodyBytes,
            attachments: message.attachments
        )
    }
}
