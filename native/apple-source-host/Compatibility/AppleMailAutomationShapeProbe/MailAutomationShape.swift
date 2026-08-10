/// WP-16 Apple Mail automation **shape** probe — compile-time only, and it sends
/// nothing.
///
/// WP-15 proved MailKit is an extension-point framework with no store, no
/// account enumeration, no mailbox listing and no message query, and WP-16
/// re-proved that against this SDK's full public surface. The mechanism that
/// *does* expose accounts, mailboxes and messages on this machine is Apple Mail's
/// scripting terminology, reached through `ScriptingBridge`, `OSAKit` or
/// `NSAppleScript`.
///
/// Reaching it requires a TCC Automation grant, which is operator-gated
/// (EXT-04), and **sending a single Apple Event to Mail is what raises the
/// dialogue**. So this target proves the two halves that can be proved without
/// consent, and refuses the third:
///
/// * the framework is *present and links* on this toolchain and SDK — every
///   `swift build` re-proves it, which is what separates "the mechanism does not
///   exist" from "the mechanism exists and we do not have permission";
/// * the *terminology* the mechanism would use is written down here as data,
///   with its four-character Apple Event codes, and
///   `tests/architecture/test_wp16_mail_adapter.py` checks that table against
///   Apple's own `Mail.sdef` on this machine. The table is therefore verified
///   rather than asserted;
/// * nothing is instantiated, no `SBApplication` is created, no script is
///   compiled or run, and no event is sent. There is no `sendEvent`, no
///   `NSAppleScript`, no `OSAScript`, no `executeAndReturnError`, no
///   `applicationWithBundleIdentifier`. Constructing an `SBApplication` is
///   itself harmless, but every subsequent property access on it is an event, so
///   the honest boundary is to not construct one at all.
///
/// **The finding this table exists to carry.** `mutationTermsConsentCannotWithhold`
/// is not a warning; it is the evidence. TCC Automation is granted per
/// *(client, target application)* pair and not per command, so a grant that lets
/// this host read `date received` is the same grant that lets it send
/// `coredelo` at a mailbox. Read-only against Apple Mail is therefore not
/// something the permission system can enforce — it can only be enforced by the
/// client not linking the framework, which is exactly what the shipping
/// `AppleSourceHost` target does and what this target is kept out of.
///
/// This target is deliberately **not** a dependency of `AppleSourceHost`.

import ScriptingBridge

public enum AppleMailAutomationShapeProbe {
    /// The framework itself. Metatypes only; nothing is instantiated, so no
    /// event can be sent and no consent dialogue can be reached.
    public static let bridgeApplicationType: SBApplication.Type = SBApplication.self
    public static let bridgeObjectType: SBObject.Type = SBObject.self
    public static let bridgeElementArrayType: SBElementArray.Type = SBElementArray.self

    /// Existential metatypes are not `Sendable`, so this is a function rather
    /// than a stored global — the same accommodation the OD-COMP-009 probe makes
    /// for `MEExtension`.
    public static func bridgeApplicationDelegateType() -> SBApplicationDelegate.Protocol {
        SBApplicationDelegate.self
    }

    /// One term of Apple Mail's scripting dictionary.
    public struct Term: Hashable, Sendable {
        /// The `<class name=…>` the term belongs to, or `""` for a command.
        public let scriptingClass: String
        /// The `<property name=…>`, `<element type=…>` or `<command name=…>`.
        public let member: String
        /// The four-character Apple Event code Mail publishes for it.
        public let code: String

        public init(scriptingClass: String, member: String, code: String) {
            self.scriptingClass = scriptingClass
            self.member = member
            self.code = code
        }
    }

    /// The read-only shape a Mail traversal would use. Every entry is declared
    /// `access="r"` in Mail's own dictionary, and the architecture test checks
    /// that claim against the file rather than trusting this list.
    public static let readShapeTerms: [Term] = [
        Term(scriptingClass: "account", member: "id", code: "ID  "),
        Term(scriptingClass: "account", member: "account type", code: "atyp"),
        Term(scriptingClass: "mailbox", member: "unread count", code: "mbuc"),
        Term(scriptingClass: "mailbox", member: "account", code: "mact"),
        Term(scriptingClass: "mailbox", member: "container", code: "mbxc"),
        Term(scriptingClass: "message", member: "id", code: "ID  "),
        Term(scriptingClass: "message", member: "message id", code: "meid"),
        Term(scriptingClass: "message", member: "date received", code: "rdrc"),
        Term(scriptingClass: "message", member: "date sent", code: "drcv"),
        Term(scriptingClass: "message", member: "message size", code: "msze"),
        Term(scriptingClass: "message", member: "source", code: "raso"),
        Term(scriptingClass: "message", member: "all headers", code: "alhe"),
        Term(scriptingClass: "mail attachment", member: "id", code: "ID  "),
        Term(scriptingClass: "mail attachment", member: "MIME type", code: "attp"),
        Term(scriptingClass: "mail attachment", member: "file size", code: "atsz"),
        Term(scriptingClass: "mail attachment", member: "downloaded", code: "atdn"),
    ]

    /// The mutation the same grant carries. A TCC Automation consent is
    /// per-application, so none of these can be withheld while `readShapeTerms`
    /// is allowed.
    public static let mutationTermsConsentCannotWithhold: [Term] = [
        Term(scriptingClass: "", member: "delete", code: "coredelo"),
        Term(scriptingClass: "", member: "move", code: "coremove"),
        Term(scriptingClass: "", member: "duplicate", code: "coreclon"),
        Term(scriptingClass: "", member: "send", code: "emsgsend"),
        Term(scriptingClass: "", member: "synchronize", code: "emalsyac"),
        Term(scriptingClass: "message", member: "deleted status", code: "isdl"),
        Term(scriptingClass: "message", member: "read status", code: "isrd"),
        Term(scriptingClass: "message", member: "junk mail status", code: "isjk"),
        Term(scriptingClass: "message", member: "mailbox", code: "mbxp"),
        Term(scriptingClass: "account", member: "password", code: "macp"),
    ]

    /// The bundle identifier a grant would name. A string, never a target: this
    /// module has no code path that hands it to anything.
    public static let terminologyOwnerBundleIdentifier = "com.apple.mail"

    /// Names only; nothing is opened, granted, compiled or sent by this target.
    public static let probedFrameworks = ["ScriptingBridge"]
}
