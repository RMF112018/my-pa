import Foundation

/// WP-18 control 2: identity that makes instability **visible** rather than
/// silently minting a second person.
///
/// The contacts tree is not the calendar's. A calendar is four levels deep and
/// strictly nested — account, calendar, series, occurrence. Contacts branches:
/// an account holds containers, and a container holds **both** groups and
/// contacts, with a contact belonging to zero or more of its container's groups.
/// So two different things sit at the same depth, and the composition carries a
/// fixed discriminator field to keep them apart. `account:container:group:g` and
/// `account:container:contact:e:k` cannot be confused, because field 2 is drawn
/// from a closed two-member set and no component can forge it — the component
/// alphabet excludes `:`, exactly as the mail and calendar alphabets do, so a
/// composed identifier splits back into its fields unambiguously.
///
/// **The subtle half is the epoch, and it is where a contacts adapter loses
/// people.** The framework's contact identifier is documented as stable, and it
/// is — right up to the paths where it is not. A restore from backup, an account
/// removed and re-added, a container re-synced from the server: each can re-mint
/// the identifiers of every contact it holds. A stored identity recording only
/// the identifier would therefore be a correct-looking key that quietly starts
/// pointing at somebody else, or that silently produces a second record for one
/// person.
///
/// So the epoch is **inside** the identity, in WP-16's shape. When the epoch
/// changes every identity changes, and a reconciler is handed a disjoint key
/// space instead of a set of mismatched contents. A disjoint key space is
/// visible; mismatched contents under a stable-looking key are not. The
/// observation additionally carries an explicit
/// `ContactIdentityAssurance`, so a consumer cannot read an identifier the
/// mechanism refused to vouch for as one it did.
///
/// **A finding, recorded here rather than discovered later.** On this platform
/// the local container's contact identifiers are not bare UUIDs — they carry a
/// suffix after a colon. `:` is the composition separator and is therefore
/// excluded from the component alphabet below, so a live mechanism must encode
/// such an identifier into this alphabet before it reaches the seam, and must
/// **refuse** rather than trim if the encoded form does not fit. Nothing in this
/// repository does that encoding, because nothing in this repository reads a
/// contact.

// MARK: - Components

/// One component of a contact identity.
///
/// The alphabet excludes `:` for the reason `MailIdentityComponent`'s and
/// `CalendarIdentityComponent`'s do: `:` is the composition separator and
/// `NativeSourceOpaqueID` admits it, so the restriction has to live here or the
/// join is ambiguous.
public struct ContactsIdentityComponent: RawRepresentable, Codable, Hashable, Sendable {
    public let rawValue: String

    public init?(rawValue: String) {
        let allowed = CharacterSet(
            charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._"
        )
        guard !rawValue.isEmpty,
              rawValue.utf8.count <= NativeSourceProtocolV1.maximumContactsIdentityComponentBytes,
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
                debugDescription: "Invalid contacts identity component"
            )
        }
        self = value
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(rawValue)
    }
}

/// The fixed discriminator that keeps the two things at depth three apart.
///
/// A group and a contact are siblings inside a container, so separator count
/// alone cannot separate them the way it separates a calendar series from one of
/// its occurrences. The discriminator is a literal field at a fixed position,
/// drawn from this closed set, and it is not a component — nothing a mechanism
/// supplies can occupy that position.
public enum ContactsIdentityBranch: String, Codable, CaseIterable, Sendable {
    case group
    case contact
}

// MARK: - The levels

public struct ContactsAccountIdentity: Codable, Hashable, Sendable {
    public let accountKey: ContactsIdentityComponent

    public init(accountKey: ContactsIdentityComponent) {
        self.accountKey = accountKey
    }

    /// Level 1. No separator at all.
    public func recordIdentifier() throws -> NativeSourceOpaqueID {
        try ContactsIdentityComposition.compose([accountKey.rawValue])
    }
}

public struct ContactsContainerIdentity: Codable, Hashable, Sendable {
    public let accountKey: ContactsIdentityComponent
    public let containerKey: ContactsIdentityComponent

    public init(accountKey: ContactsIdentityComponent, containerKey: ContactsIdentityComponent) {
        self.accountKey = accountKey
        self.containerKey = containerKey
    }

    /// Level 2. One separator.
    public func recordIdentifier() throws -> NativeSourceOpaqueID {
        try ContactsIdentityComposition.compose([accountKey.rawValue, containerKey.rawValue])
    }

    public var account: ContactsAccountIdentity {
        ContactsAccountIdentity(accountKey: accountKey)
    }

    /// Reads a container identifier back into its two components.
    ///
    /// Refuses anything that is not exactly two colon-free components. A read
    /// request naming a container the adapter cannot decompose is refused rather
    /// than guessed at: guessing is how a contact ends up filed under another
    /// account.
    public init(bucketID: NativeSourceOpaqueID) throws {
        let parts = bucketID.rawValue.split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count == 2,
              let accountKey = ContactsIdentityComponent(rawValue: String(parts[0])),
              let containerKey = ContactsIdentityComponent(rawValue: String(parts[1]))
        else {
            throw NativeSourceContractError.contactsInvalidIdentityComponent
        }
        self.accountKey = accountKey
        self.containerKey = containerKey
    }
}

public struct ContactsGroupIdentity: Codable, Hashable, Sendable {
    public let container: ContactsContainerIdentity
    public let groupKey: ContactsIdentityComponent

    public init(container: ContactsContainerIdentity, groupKey: ContactsIdentityComponent) {
        self.container = container
        self.groupKey = groupKey
    }

    /// Level 3, group branch. Three separators, with the branch discriminator in
    /// field 2.
    public func recordIdentifier() throws -> NativeSourceOpaqueID {
        try ContactsIdentityComposition.compose([
            container.accountKey.rawValue,
            container.containerKey.rawValue,
            ContactsIdentityBranch.group.rawValue,
            groupKey.rawValue,
        ])
    }
}

/// A contact identity that carries its own epoch.
///
/// See this file's header. The epoch is not metadata beside the identity — it is
/// a field of it, so that a re-mint produces a visibly different key rather than
/// a stable-looking key pointing somewhere new.
public struct ContactIdentity: Codable, Hashable, Sendable {
    public let container: ContactsContainerIdentity
    /// The epoch these contact keys belong to. Changes when the source re-mints
    /// the identifiers of the container — a restore, a re-sync, an account
    /// removed and re-added.
    public let identityEpoch: ContactsIdentityComponent
    public let contactKey: ContactsIdentityComponent

    public init(
        container: ContactsContainerIdentity,
        identityEpoch: ContactsIdentityComponent,
        contactKey: ContactsIdentityComponent
    ) {
        self.container = container
        self.identityEpoch = identityEpoch
        self.contactKey = contactKey
    }

    /// Level 3, contact branch. Four separators, with the branch discriminator
    /// in field 2 and the epoch in field 3.
    public func recordIdentifier() throws -> NativeSourceOpaqueID {
        try ContactsIdentityComposition.compose([
            container.accountKey.rawValue,
            container.containerKey.rawValue,
            ContactsIdentityBranch.contact.rawValue,
            identityEpoch.rawValue,
            contactKey.rawValue,
        ])
    }
}

// MARK: - Composition

public enum ContactsIdentityComposition {
    public static let separator = ":"

    /// Joins components into an opaque identifier, or **refuses**.
    ///
    /// Refuses rather than trims, for the reason WP-16 and WP-17 give: a trimmed
    /// identity is the one truncation with no honest partial form, because it
    /// silently aliases two people onto one record. Five maximum-length
    /// components genuinely do exceed `NativeSourceOpaqueID`'s ceiling, so this
    /// path is reachable and is not decoration.
    public static func compose(_ components: [String]) throws -> NativeSourceOpaqueID {
        let joined = components.joined(separator: separator)
        guard let identifier = NativeSourceOpaqueID(rawValue: joined) else {
            throw NativeSourceContractError.contactsIdentityTooLong
        }
        return identifier
    }
}

// MARK: - Assurance

/// What the mechanism is willing to say about the identifier it just handed over.
///
/// **WP-18 control 2 lives in this enum, and control 6 does too.** A contact row
/// is an observation carrying provenance, not an assertion about a person, and
/// the provenance that matters most here is how much the source vouches for its
/// own key. The three answers are genuinely different facts and are never
/// collapsed: an identifier the mechanism vouches for, an identifier the
/// mechanism knows was re-minted, and an identifier the mechanism will not
/// characterise at all. A consumer handed the third as if it were the first has
/// been told something untrue.
public enum ContactIdentityAssurance: String, Codable, CaseIterable, Sendable {
    /// Stable for as long as `ContactIdentity.identityEpoch` is unchanged. This
    /// is the strongest claim available and it is still epoch-relative; there is
    /// deliberately no case meaning "stable forever", because no source offers
    /// one.
    case stableWithinEpoch = "stable_within_epoch"
    /// The mechanism knows this identifier is not the one it published for the
    /// same person before the current epoch. Carried, never dropped: a re-mint
    /// reported as an ordinary new contact is how one person becomes two.
    case reMintedInThisEpoch = "re_minted_in_this_epoch"
    /// The mechanism cannot characterise the identifier. Ambiguity is carried
    /// rather than rounded up to `stableWithinEpoch`, which is the whole of
    /// brief §22 in one field.
    case unknown
}

/// Person or organization, which is the only discriminator the minimum key set
/// buys and the only one it needs.
///
/// It is here so that a downstream consumer cannot read every contact row as a
/// person. An organization record has no person in it, and treating one as a
/// person is precisely the "observation mistaken for truth" §22 forbids. It
/// carries no content: two cases, neither of which names anybody.
public enum ContactStructuralType: String, Codable, CaseIterable, Sendable {
    case person
    case organization
}
