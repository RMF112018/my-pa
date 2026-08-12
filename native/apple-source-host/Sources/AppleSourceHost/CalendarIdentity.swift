import Foundation

/// WP-17 control 1: four levels of identity, composed injectively.
///
/// Account, calendar, series, occurrence. They are not four independent
/// identifiers — each is the previous one with a field appended, joined by `:`,
/// and the component alphabet **excludes `:`** exactly as WP-16's does. That is
/// what makes the composition injective: a composed identifier splits back into
/// its fields unambiguously, and the number of separators alone says which level
/// it is. A series and one of its occurrences therefore cannot collide, because
/// they carry a different number of separators and no component can forge one.
///
/// **The subtle half is the occurrence key, and it is where calendar adapters
/// lose data.** An occurrence is keyed by the start it was *originally
/// scheduled* for, never by the start it currently has. A detached instance that
/// the organiser moved from Tuesday to Thursday keeps its Tuesday key: it is the
/// same occurrence, moved. Keying by the actual start would make the move look
/// like a deletion and a creation — the Tuesday occurrence vanishes and an
/// unrelated Thursday one appears — and every downstream reconciler would
/// believe it.
///
/// The key is rendered as a fixed-width, order-preserving decimal rather than as
/// the signed integer's own text. `String(-1)` sorts before `String(-2)` and
/// after `String(10)`, so a cursor over raw decimal keys resumes in the wrong
/// place; the bias-and-pad below makes lexicographic order and chronological
/// order the same order for every `Int64`, including instants before 1970.

// MARK: - Components

/// One component of a calendar identity.
///
/// The alphabet excludes `:` for the reason `MailIdentityComponent`'s does: `:`
/// is the composition separator and `NativeSourceOpaqueID` admits it, so the
/// restriction has to live here or the join is ambiguous.
public struct CalendarIdentityComponent: RawRepresentable, Codable, Hashable, Sendable {
    public let rawValue: String

    public init?(rawValue: String) {
        let allowed = CharacterSet(
            charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._"
        )
        guard !rawValue.isEmpty,
              rawValue.utf8.count <= NativeSourceProtocolV1.maximumCalendarIdentityComponentBytes,
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
                debugDescription: "Invalid calendar identity component"
            )
        }
        self = value
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(rawValue)
    }
}

// MARK: - The four levels

public struct CalendarAccountIdentity: Codable, Hashable, Sendable {
    public let accountKey: CalendarIdentityComponent

    public init(accountKey: CalendarIdentityComponent) {
        self.accountKey = accountKey
    }

    /// Level 1. No separator at all, which is why an account identifier can
    /// never be mistaken for a calendar, a series or an occurrence.
    public func recordIdentifier() throws -> NativeSourceOpaqueID {
        try CalendarIdentityComposition.compose([accountKey.rawValue])
    }
}

public struct CalendarBucketIdentity: Codable, Hashable, Sendable {
    public let accountKey: CalendarIdentityComponent
    public let calendarKey: CalendarIdentityComponent

    public init(accountKey: CalendarIdentityComponent, calendarKey: CalendarIdentityComponent) {
        self.accountKey = accountKey
        self.calendarKey = calendarKey
    }

    /// Level 2. One separator.
    public func recordIdentifier() throws -> NativeSourceOpaqueID {
        try CalendarIdentityComposition.compose([accountKey.rawValue, calendarKey.rawValue])
    }

    public var account: CalendarAccountIdentity { CalendarAccountIdentity(accountKey: accountKey) }

    /// Reads a bucket identifier back into its two components.
    ///
    /// Refuses anything that is not exactly two colon-free components. A read
    /// request naming a bucket the adapter cannot decompose is refused rather
    /// than guessed at: guessing is how an occurrence ends up filed under the
    /// wrong account.
    public init(bucketID: NativeSourceOpaqueID) throws {
        let parts = bucketID.rawValue.split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count == 2,
              let accountKey = CalendarIdentityComponent(rawValue: String(parts[0])),
              let calendarKey = CalendarIdentityComponent(rawValue: String(parts[1]))
        else {
            throw NativeSourceContractError.calendarInvalidIdentityComponent
        }
        self.accountKey = accountKey
        self.calendarKey = calendarKey
    }
}

public struct CalendarSeriesIdentity: Codable, Hashable, Sendable {
    public let bucket: CalendarBucketIdentity
    /// The key of the event *series*. A non-recurring event is a series of one,
    /// so every occurrence has one and the level is never absent.
    public let seriesKey: CalendarIdentityComponent

    public init(bucket: CalendarBucketIdentity, seriesKey: CalendarIdentityComponent) {
        self.bucket = bucket
        self.seriesKey = seriesKey
    }

    /// Level 3. Two separators.
    public func recordIdentifier() throws -> NativeSourceOpaqueID {
        try CalendarIdentityComposition.compose([
            bucket.accountKey.rawValue, bucket.calendarKey.rawValue, seriesKey.rawValue,
        ])
    }
}

public struct CalendarOccurrenceIdentity: Codable, Hashable, Sendable {
    public let series: CalendarSeriesIdentity
    /// **The start this occurrence was originally scheduled for**, never the
    /// start it currently has. See this file's header.
    public let originalStartUnixMilliseconds: Int64

    public init(series: CalendarSeriesIdentity, originalStartUnixMilliseconds: Int64) {
        self.series = series
        self.originalStartUnixMilliseconds = originalStartUnixMilliseconds
    }

    /// Level 4. Three separators, and a fixed-width final field.
    public func recordIdentifier() throws -> NativeSourceOpaqueID {
        try CalendarIdentityComposition.compose([
            series.bucket.accountKey.rawValue,
            series.bucket.calendarKey.rawValue,
            series.seriesKey.rawValue,
            CalendarIdentityComposition.orderPreservingKey(originalStartUnixMilliseconds),
        ])
    }
}

// MARK: - Composition

public enum CalendarIdentityComposition {
    public static let separator = ":"
    /// `UInt64.max` is twenty digits, so twenty is the width at which every
    /// biased instant renders without a leading-zero ambiguity.
    public static let orderPreservingKeyDigits = 20

    /// Joins components into an opaque identifier, or **refuses**.
    ///
    /// Refuses rather than trims, for the reason WP-16 gives: a trimmed identity
    /// is the one truncation with no honest partial form, because it silently
    /// aliases two distinct occurrences onto one record. Four maximum-length
    /// components genuinely do exceed `NativeSourceOpaqueID`'s ceiling, so this
    /// path is reachable and is not decoration.
    public static func compose(_ components: [String]) throws -> NativeSourceOpaqueID {
        let joined = components.joined(separator: separator)
        guard let identifier = NativeSourceOpaqueID(rawValue: joined) else {
            throw NativeSourceContractError.calendarIdentityTooLong
        }
        return identifier
    }

    /// Renders a signed instant so that lexicographic order equals chronological
    /// order. Bias by 2^63 to make the value unsigned, then zero-pad to a fixed
    /// width; both halves are needed, and either alone leaves a cursor that
    /// resumes in the wrong place.
    public static func orderPreservingKey(_ unixMilliseconds: Int64) -> String {
        let biased = UInt64(bitPattern: unixMilliseconds) ^ 0x8000_0000_0000_0000
        let digits = String(biased)
        let padding = orderPreservingKeyDigits - digits.count
        return padding > 0 ? String(repeating: "0", count: padding) + digits : digits
    }
}

// MARK: - Lifecycle

/// What an occurrence *is*, which is not the same question as whether it is
/// present.
///
/// **WP-17 control 4 lives in this enum.** A cancelled occurrence is emitted
/// carrying `cancelled`; it is never dropped from a page. Absence and
/// cancellation are different facts about a calendar — "the 10:00 stand-up was
/// cancelled" and "there was never a 10:00 stand-up" lead to different actions —
/// and a reader that receives the first as the second has been told something
/// untrue.
public enum CalendarOccurrenceLifecycle: String, Codable, CaseIterable, Sendable {
    /// Happening as the series scheduled it.
    case confirmed
    /// Called off, and still reported. The schedule it carries is the slot it
    /// was called off from.
    case cancelled
    /// A detached instance: the same occurrence, moved or edited away from what
    /// the series says. Its identity is still anchored to the original start.
    case detached
}
