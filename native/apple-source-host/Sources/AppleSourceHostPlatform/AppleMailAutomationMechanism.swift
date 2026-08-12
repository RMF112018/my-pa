import AppleSourceHost
import AppKit
import ApplicationServices
import Foundation
import ScriptingBridge

/// Production-shaped Apple Mail reader over a deliberately closed subset of
/// Mail's scripting dictionary.  macOS grants Automation per client/target, not
/// per selector; the OS grant is therefore broader than this implementation.
/// The safety boundary is that only the read element/property codes below are
/// named, the `MailMechanism` seam exposes only reads, and consent is checked
/// with `askUserIfNeeded: false` before an application object is created.
///
/// Construction is dormant and sends no Apple event. Repository tests compile
/// and statically inspect this type but never instantiate or invoke a live Mail
/// client, request TCC, launch Mail, or read a mailbox.
public final class AppleMailAutomationMechanism: MailMechanism, @unchecked Sendable {
    public let descriptor = MailMechanismDescriptor(
        mechanism: .appleMailAutomation,
        dateBound: .sourceSideExact,
        publishesGeneration: true,
        requiresOperatorConsent: true
    )

    private static let mailBundleIdentifier = "com.apple.mail"
    private let generation: MailIdentityComponent
    private let maximumAccounts: Int
    private let maximumMailboxes: Int
    private let maximumMatchingMessages: Int

    public init(
        generation: String,
        maximumAccounts: Int = 50,
        maximumMailboxes: Int = 500,
        maximumMatchingMessages: Int = 101
    ) throws {
        guard let generation = MailIdentityComponent(rawValue: generation) else {
            throw NativeSourceContractError.mailGenerationUnavailable
        }
        guard 1...100 ~= maximumAccounts,
              1...1_000 ~= maximumMailboxes,
              2...101 ~= maximumMatchingMessages
        else { throw NativeSourceContractError.mailAutomationTraversalExceeded }
        self.generation = generation
        self.maximumAccounts = maximumAccounts
        self.maximumMailboxes = maximumMailboxes
        self.maximumMatchingMessages = maximumMatchingMessages
    }

    public func consentState() throws -> MailConsentState {
        guard !NSRunningApplication.runningApplications(
            withBundleIdentifier: Self.mailBundleIdentifier
        ).isEmpty else { return .targetUnavailable }
        let target = NSAppleEventDescriptor(bundleIdentifier: Self.mailBundleIdentifier)
        guard let address = target.aeDesc else { return .targetUnavailable }
        let status = AEDeterminePermissionToAutomateTarget(
            address,
            typeWildCard,
            typeWildCard,
            false
        )
        switch status {
        case noErr: return .granted
        case OSStatus(errAEEventNotPermitted): return .denied
        default: return .notDetermined
        }
    }

    public func accounts() throws -> [MailAccountDescriptor] {
        let values = try mailApplication().elementArray(withCode: Codes.account).map {
            try requireObject($0)
        }
        guard values.count <= maximumAccounts else {
            throw NativeSourceContractError.mailAutomationTraversalExceeded
        }
        return try values.map { account in
            let providerID: String = try value(account, Codes.id)
            let name: String = try value(account, Codes.name)
            return MailAccountDescriptor(
                id: try PlatformIdentity.opaque("mail-account", providerID),
                displayLabel: name
            )
        }.sorted { $0.id.rawValue < $1.id.rawValue }
    }

    public func mailboxes() throws -> [MailMailboxDescriptor] {
        try mailboxBindings().map(\.descriptor)
            .sorted { $0.id.rawValue < $1.id.rawValue }
    }

    public func messageSummaries(_ query: MailTraversalQuery) throws -> MailTraversalResult {
        guard let window = query.window else {
            throw NativeSourceContractError.mailDateBoundNotSourceSide
        }
        guard query.limit < maximumMatchingMessages else {
            throw NativeSourceContractError.mailAutomationTraversalExceeded
        }
        let binding = try selectedMailbox(query.mailboxID)
        let messages = binding.object.elementArray(withCode: Codes.message)
        var predicates = [
            NSPredicate(
                format: "dateReceived >= %@ AND dateReceived <= %@",
                Date(timeIntervalSince1970: Double(window.startUnixMilliseconds) / 1000) as NSDate,
                Date(timeIntervalSince1970: Double(window.endUnixMilliseconds) / 1000) as NSDate
            )
        ]
        if let after = query.afterProviderKey,
           let providerID = Int64(after.rawValue) {
            predicates.append(NSPredicate(format: "id > %lld", providerID))
        }
        let selected = messages.filtered(
            using: NSCompoundPredicate(andPredicateWithSubpredicates: predicates)
        )
        guard selected.count <= maximumMatchingMessages else {
            throw NativeSourceContractError.mailAutomationTraversalExceeded
        }
        let summaries = try selected.map { value in
            let message = try requireObject(value)
            let providerID: Int64 = try self.value(message, Codes.id)
            guard let key = MailIdentityComponent(rawValue: String(providerID)) else {
                throw NativeSourceContractError.mailInvalidIdentityComponent
            }
            let received: Date = try self.value(message, Codes.dateReceived)
            let sent: Date? = try optionalValue(message, Codes.dateSent)
            return MailMessageSummary(
                providerKey: key,
                receivedUnixMilliseconds: milliseconds(received),
                sentUnixMilliseconds: sent.map(milliseconds),
                attachments: []
            )
        }.sorted { $0.providerKey.rawValue < $1.providerKey.rawValue }
        return MailTraversalResult(
            summaries: Array(summaries.prefix(query.limit)),
            generation: generation,
            scannedWholeMailbox: false
        )
    }

    public func messageContent(_ identity: MailMessageIdentity) throws -> MailMessageContent {
        guard identity.generation == generation else {
            throw NativeSourceContractError.mailGenerationUnavailable
        }
        let binding = try selectedMailbox(identity.mailboxID)
        guard let providerID = Int64(identity.providerKey.rawValue) else {
            throw NativeSourceContractError.mailInvalidIdentityComponent
        }
        let message = try requireObject(
            binding.object.elementArray(withCode: Codes.message).object(withID: providerID)
        )
        let headers: String = try value(message, Codes.allHeaders)
        let body: String = try value(message, Codes.content)
        let attachments = try attachmentDescriptors(message)
        guard headers.utf8.count <= NativeSourceProtocolV1.maximumMailHeaderBytes else {
            throw NativeSourceContractError.mailHeaderTooLarge
        }
        return MailMessageContent(
            headerBytes: Array(headers.utf8),
            bodyBytes: Array(body.utf8),
            attachments: attachments
        )
    }

    private func mailApplication() throws -> SBApplication {
        guard try consentState() == .granted,
              let application = SBApplication(bundleIdentifier: Self.mailBundleIdentifier)
        else { throw NativeProviderFailure.permissionDenied }
        return application
    }

    private func mailboxBindings() throws -> [MailboxBinding] {
        let application = try mailApplication()
        let accountObjects = try application.elementArray(withCode: Codes.account).map {
            try requireObject($0)
        }
        guard accountObjects.count <= maximumAccounts else {
            throw NativeSourceContractError.mailAutomationTraversalExceeded
        }
        var bindings: [MailboxBinding] = []
        for account in accountObjects {
            let accountProviderID: String = try value(account, Codes.id)
            let accountID = try PlatformIdentity.opaque("mail-account", accountProviderID)
            try appendMailboxes(
                account.elementArray(withCode: Codes.mailbox),
                accountID: accountID,
                parentID: nil,
                parentPath: accountProviderID,
                into: &bindings
            )
        }
        return bindings
    }

    private func appendMailboxes(
        _ objects: SBElementArray,
        accountID: NativeSourceOpaqueID,
        parentID: NativeSourceOpaqueID?,
        parentPath: String,
        into bindings: inout [MailboxBinding]
    ) throws {
        for raw in objects {
            guard bindings.count < maximumMailboxes else {
                throw NativeSourceContractError.mailAutomationTraversalExceeded
            }
            let mailbox = try requireObject(raw)
            let name: String = try value(mailbox, Codes.name)
            let path = "\(parentPath)/\(name)"
            let mailboxID = try PlatformIdentity.opaque("mail-mailbox", path)
            bindings.append(
                MailboxBinding(
                    descriptor: MailMailboxDescriptor(
                        id: mailboxID,
                        accountID: accountID,
                        parentID: parentID,
                        displayLabel: name,
                        isSelectable: true
                    ),
                    object: mailbox
                )
            )
            try appendMailboxes(
                mailbox.elementArray(withCode: Codes.mailbox),
                accountID: accountID,
                parentID: mailboxID,
                parentPath: path,
                into: &bindings
            )
        }
    }

    private func selectedMailbox(_ id: NativeSourceOpaqueID) throws -> MailboxBinding {
        let matches = try mailboxBindings().filter { $0.descriptor.id == id }
        guard matches.count == 1, let binding = matches.first else {
            throw NativeSourceContractError.unknownBucket
        }
        return binding
    }

    private func attachmentDescriptors(_ message: SBObject) throws
        -> [MailAttachmentDescriptor] {
        let values = message.elementArray(withCode: Codes.attachment)
        guard values.count <= NativeSourceProtocolV1.maximumMailAttachmentDescriptors else {
            throw NativeSourceContractError.mailAttachmentLimitExceeded
        }
        return try values.map { raw in
            let attachment = try requireObject(raw)
            let providerID: String = try value(attachment, Codes.id)
            let mimeType: String = try value(attachment, Codes.mimeType)
            let byteSize: Int = try value(attachment, Codes.fileSize)
            return try MailAttachmentDescriptor(
                id: PlatformIdentity.opaque("mail-attachment", providerID),
                mimeType: mimeType,
                byteSize: byteSize,
                disposition: byteSize > NativeSourceProtocolV1.maximumMailAttachmentBytes
                    ? .omittedOversize : .metadataOnly
            )
        }
    }

    private func value<T>(_ object: SBObject, _ code: AEKeyword) throws -> T {
        guard let result = object.property(withCode: code).get() as? T else {
            throw NativeProviderFailure.transientUnavailable
        }
        return result
    }

    private func optionalValue<T>(_ object: SBObject, _ code: AEKeyword) throws -> T? {
        let result = object.property(withCode: code).get()
        if result == nil || result is NSNull { return nil }
        guard let typed = result as? T else { throw NativeProviderFailure.transientUnavailable }
        return typed
    }

    private func requireObject(_ value: Any) throws -> SBObject {
        guard let object = value as? SBObject else {
            throw NativeProviderFailure.transientUnavailable
        }
        return object
    }

    private func milliseconds(_ date: Date) -> Int64 {
        Int64((date.timeIntervalSince1970 * 1000).rounded())
    }
}

private struct MailboxBinding: @unchecked Sendable {
    let descriptor: MailMailboxDescriptor
    let object: SBObject
}

private enum Codes {
    static let account = fourCC("mact")
    static let mailbox = fourCC("mbxp")
    static let message = fourCC("mssg")
    static let attachment = fourCC("attc")
    static let id = fourCC("ID  ")
    static let name = fourCC("pnam")
    static let dateReceived = fourCC("rdrc")
    static let dateSent = fourCC("drcv")
    static let allHeaders = fourCC("alhe")
    static let content = fourCC("ctnt")
    static let mimeType = fourCC("attp")
    static let fileSize = fourCC("atsz")

    private static func fourCC(_ value: StaticString) -> UInt32 {
        let bytes = Array(value.withUTF8Buffer { Array($0) })
        precondition(bytes.count == 4)
        return bytes.reduce(0) { ($0 << 8) | UInt32($1) }
    }
}
