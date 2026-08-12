import Foundation

/// WP-17's mechanism seam.
///
/// EventKit is a real, documented, public **read** API — unlike WP-16's
/// situation, where the finding was that no read mechanism exists. So the
/// question here is not whether a calendar can be read; it is whether it can be
/// read *safely*, and that question is answered here rather than in whatever
/// eventually talks to EventKit.
///
/// The shipping host links **no Apple framework** — WP-15's control 1, proved at
/// link time — and EventKit is an Apple framework, so the adapter is defined over
/// this seam and not over EventKit's event store. The probe target
/// `Compatibility/AppleCalendarEventKitProbe`
/// carries the EventKit references, is compiled by every `swift build`, and is a
/// dependency of nothing; that target is what makes "needs an operator TCC grant"
/// a different statement from "does not exist".
///
/// Three properties of the seam carry findings rather than conveniences:
///
/// 1. **Every operation is a read, and there is no consent *request*.** The
///    adapter can observe that authorization is absent and refuse. It cannot ask
///    for it: on macOS the asking is what raises the dialogue, and a TCC grant is
///    operator-gated (EXT-04).
/// 2. **A mechanism that cannot publish an occurrence's original start cannot be
///    read from.** See `publishesOriginalOccurrenceStart`. Occurrence identity is
///    anchored to the originally scheduled start, so a mechanism that only knows
///    where an occurrence is *now* cannot mint a stable identity for a moved
///    instance, and minting one anyway makes every move look like a delete and a
///    create.
/// 3. **The result declares whether it walked the whole store**, and a bounded
///    read against a mechanism that says it did is refused. The descriptor's
///    optimistic claim is the half nobody can trust; the result's claim is the
///    half that cannot be got right by writing a hopeful descriptor.

// MARK: - Authorization

/// What the mechanism can observe about authorization **without asking for it**.
///
/// The four cases mirror EventKit's own `EKAuthorizationStatus` vocabulary, and
/// exactly one of them permits a read. In particular `notDetermined` does **not**
/// mean "try it and see": trying is what raises the dialogue.
public enum CalendarAuthorizationState: String, Codable, CaseIterable, Sendable {
    case authorized
    case denied
    /// Withheld by policy — a profile or a parental control — rather than by the
    /// person at the keyboard. Reported separately because "you said no" and
    /// "your organisation said no" are different facts, and the second one is not
    /// fixable by asking again.
    case restricted
    case notDetermined = "not_determined"
}

// MARK: - Mechanism identity

public enum CalendarMechanismKind: String, Codable, CaseIterable, Sendable {
    /// The in-process fixture this package's harness drives. Seeded by hand with
    /// obviously synthetic content.
    case fixtureSeeded = "fixture_seeded"
    /// EventKit's event store. Present on this machine and operator-gated; see
    /// `AppleCalendarEventKitProbe` and
    /// `docs/campaign/WP-17-CALENDAR-ADAPTER-RECORD.md`. **Nothing in this
    /// repository implements it**, because implementing it means holding a TCC
    /// grant this package must not obtain.
    case eventKitStore = "event_kit_store"
}

public struct CalendarMechanismDescriptor: Codable, Hashable, Sendable {
    public let mechanism: CalendarMechanismKind
    /// Whether the mechanism can name the start an occurrence was originally
    /// scheduled for, as distinct from the start it currently has. EventKit
    /// publishes it as an event's `occurrenceDate`. A mechanism that does not is
    /// refused at read time rather than trusted to be close enough.
    public let publishesOriginalOccurrenceStart: Bool
    /// Whether reaching this mechanism at all needs a grant only a human can
    /// give. Recorded, not enforced — the enforcement is `authorizationState()`.
    public let requiresOperatorConsent: Bool

    public init(
        mechanism: CalendarMechanismKind,
        publishesOriginalOccurrenceStart: Bool,
        requiresOperatorConsent: Bool
    ) {
        self.mechanism = mechanism
        self.publishesOriginalOccurrenceStart = publishesOriginalOccurrenceStart
        self.requiresOperatorConsent = requiresOperatorConsent
    }
}

// MARK: - Discovery

public struct CalendarAccountDescriptor: Hashable, Sendable {
    public let accountKey: CalendarIdentityComponent
    public let displayLabel: String

    public init(accountKey: CalendarIdentityComponent, displayLabel: String) {
        self.accountKey = accountKey
        self.displayLabel = displayLabel
    }

    public var identity: CalendarAccountIdentity {
        CalendarAccountIdentity(accountKey: accountKey)
    }
}

public struct CalendarBucketDescriptor: Hashable, Sendable {
    public let identity: CalendarBucketIdentity
    public let displayLabel: String
    public let isSelectable: Bool

    public init(identity: CalendarBucketIdentity, displayLabel: String, isSelectable: Bool) {
        self.identity = identity
        self.displayLabel = displayLabel
        self.isSelectable = isSelectable
    }
}

// MARK: - The bounded horizon

/// The window one calendar read may ask for.
///
/// A calendar has no natural end, so an unbounded calendar read is an unbounded
/// enumeration; the horizon is what makes the read finite. It is enforced by
/// `throw` on the initialiser **and** on the decode path, because a bound that
/// only exists on an initialiser is not a bound — the same value arrives as JSON.
///
/// **Exceeding it is refused, never narrowed.** A horizon quietly clipped from
/// ten years to one returns a page indistinguishable from "nothing is scheduled
/// after next spring", which is silent loss of exactly the kind §28 is about.
public struct CalendarHorizonWindow: Codable, Hashable, Sendable {
    public let startUnixMilliseconds: Int64
    public let endUnixMilliseconds: Int64

    public init(startUnixMilliseconds: Int64, endUnixMilliseconds: Int64) throws {
        guard startUnixMilliseconds <= endUnixMilliseconds else {
            throw NativeSourceContractError.invalidTimeRange
        }
        let (span, overflow) = endUnixMilliseconds.subtractingReportingOverflow(
            startUnixMilliseconds
        )
        let ceiling = Int64(NativeSourceProtocolV1.maximumCalendarHorizonDays)
            * CalendarCivil.millisecondsPerDay
        guard !overflow, span <= ceiling else {
            throw NativeSourceContractError.calendarHorizonExceeded
        }
        self.startUnixMilliseconds = startUnixMilliseconds
        self.endUnixMilliseconds = endUnixMilliseconds
    }

    private enum CodingKeys: String, CodingKey { case startUnixMilliseconds, endUnixMilliseconds }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            startUnixMilliseconds: values.decode(Int64.self, forKey: .startUnixMilliseconds),
            endUnixMilliseconds: values.decode(Int64.self, forKey: .endUnixMilliseconds)
        )
    }

    public init(_ range: NativeTimeRange) throws {
        try self.init(
            startUnixMilliseconds: range.startUnixMilliseconds,
            endUnixMilliseconds: range.endUnixMilliseconds
        )
    }
}

// MARK: - Occurrences

/// One occurrence, as the mechanism reports it.
///
/// The invariants here are the ones a mechanism can get wrong in a way that
/// looks right:
///
/// * a `confirmed` occurrence must sit exactly where its identity says it was
///   scheduled. An occurrence that has moved and still calls itself confirmed is
///   an identity that has silently re-pointed, which is the defect control 1
///   exists to prevent. `cancelled` and `detached` are free to sit elsewhere —
///   that is what they mean;
/// * an all-day occurrence must be anchored to a whole day. The anchor is a
///   date-derived integer, so an all-day occurrence keyed to some mid-afternoon
///   instant is a value that has already lost the fact that a whole day was
///   meant.
///
/// There is deliberately **no title, no location, no attendee and no note**.
/// Occurrence content is not part of WP-17's acceptance, and a content field
/// nothing needs is a content field that eventually holds somebody's calendar in
/// a public repository.
public struct CalendarOccurrence: Codable, Hashable, Sendable {
    public let identity: CalendarOccurrenceIdentity
    public let lifecycle: CalendarOccurrenceLifecycle
    public let schedule: CalendarSchedule
    /// When the source last changed this occurrence. Carried as the record's
    /// revision, so a consumer can tell an unchanged re-read from a changed one.
    public let lastModifiedUnixMilliseconds: Int64

    public init(
        identity: CalendarOccurrenceIdentity,
        lifecycle: CalendarOccurrenceLifecycle,
        schedule: CalendarSchedule,
        lastModifiedUnixMilliseconds: Int64
    ) throws {
        if lifecycle == .confirmed {
            guard schedule.scheduleAnchorUnixMilliseconds
                == identity.originalStartUnixMilliseconds
            else {
                throw NativeSourceContractError.calendarLifecycleInconsistent
            }
        }
        if schedule.isAllDay {
            guard CalendarCivil.floorModulo(
                identity.originalStartUnixMilliseconds,
                by: CalendarCivil.millisecondsPerDay
            ) == 0 else {
                throw NativeSourceContractError.calendarLifecycleInconsistent
            }
        }
        self.identity = identity
        self.lifecycle = lifecycle
        self.schedule = schedule
        self.lastModifiedUnixMilliseconds = lastModifiedUnixMilliseconds
    }

    private enum CodingKeys: String, CodingKey {
        case identity, lifecycle, schedule, lastModifiedUnixMilliseconds
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            identity: values.decode(CalendarOccurrenceIdentity.self, forKey: .identity),
            lifecycle: values.decode(CalendarOccurrenceLifecycle.self, forKey: .lifecycle),
            schedule: values.decode(CalendarSchedule.self, forKey: .schedule),
            lastModifiedUnixMilliseconds: values.decode(
                Int64.self,
                forKey: .lastModifiedUnixMilliseconds
            )
        )
    }

    /// The pagination key. It is the composed record identifier, whose final
    /// field is fixed-width and order-preserving, so lexicographic comparison of
    /// these keys is chronological within a series.
    public func cursorKey() throws -> String {
        try identity.recordIdentifier().rawValue
    }
}

// MARK: - Traversal

public struct CalendarTraversalQuery: Hashable, Sendable {
    public let bucket: CalendarBucketIdentity
    /// Never optional. A calendar read without a horizon is the unbounded
    /// enumeration the horizon exists to prevent, so the type has nowhere to put
    /// "no bound".
    public let window: CalendarHorizonWindow
    /// Exclusive lower bound on the occurrence cursor key.
    public let afterCursorKey: String?
    public let limit: Int

    public init(
        bucket: CalendarBucketIdentity,
        window: CalendarHorizonWindow,
        afterCursorKey: String?,
        limit: Int
    ) throws {
        guard limit > 0, limit <= NativeSourceProtocolV1.maximumPageSize else {
            throw NativeSourceContractError.invalidPageLimit
        }
        self.bucket = bucket
        self.window = window
        self.afterCursorKey = afterCursorKey
        self.limit = limit
    }
}

public struct CalendarTraversalResult: Hashable, Sendable {
    public let occurrences: [CalendarOccurrence]
    /// **The honest truncation signal.** A page that stops short of the window
    /// must say so, and the adapter refuses a result whose `moreAvailable` and
    /// cursor disagree. A truncated page that reports itself complete is the
    /// calendar equivalent of a clamped limit: the caller stops paging and never
    /// learns what it did not receive.
    public let moreAvailable: Bool
    /// The mechanism's own declaration that satisfying this query required
    /// enumerating the whole store rather than applying the window at the
    /// source. A bounded read against a mechanism that says `true` is refused:
    /// "bounded horizon" is the acceptance, and a client-side filter after a
    /// full enumeration is precisely not that.
    public let enumeratedWholeStore: Bool

    public init(
        occurrences: [CalendarOccurrence],
        moreAvailable: Bool,
        enumeratedWholeStore: Bool
    ) {
        self.occurrences = occurrences
        self.moreAvailable = moreAvailable
        self.enumeratedWholeStore = enumeratedWholeStore
    }
}

// MARK: - The seam

/// Everything the bounded adapter needs from whatever actually reads a calendar.
///
/// The operation set is closed and every member of it is a read.
/// `tests/architecture/test_wp17_calendar_adapter.py::test_the_calendar_mechanism_seam_declares_only_read_operations`
/// holds it to exactly these four, so adding a fifth is a decision somebody has
/// to make on purpose rather than a line in a diff. There is no `save`, no
/// `remove`, no `commit`, and no request for consent.
public protocol CalendarMechanism: Sendable {
    var descriptor: CalendarMechanismDescriptor { get }
    func authorizationState() throws -> CalendarAuthorizationState
    func accounts() throws -> [CalendarAccountDescriptor]
    func calendars() throws -> [CalendarBucketDescriptor]
    func occurrences(_ query: CalendarTraversalQuery) throws -> CalendarTraversalResult
}
