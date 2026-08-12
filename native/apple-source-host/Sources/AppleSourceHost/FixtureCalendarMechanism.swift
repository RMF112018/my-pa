import Foundation

/// Ways a calendar mechanism can be wrong, so that the adapter's re-checks are
/// exercised rather than merely written.
///
/// Each is a real failure mode of a real calendar source: one that ignores the
/// window it was given, one that satisfies the window by enumerating everything,
/// one that returns occurrences the cursor cannot resume from, one that claims
/// more is available without filling the page, one that answers with another
/// calendar's occurrences, and — the one this package exists to name — one that
/// reports a cancelled occurrence by leaving it out.
public enum FixtureCalendarFault: Hashable, Sendable {
    case none
    case ignoreTheWindow
    case declareWholeStoreEnumeration
    case returnKeysOutOfOrder
    case claimMoreAvailableWithoutFillingThePage
    case leakAnotherCalendarsOccurrence
    /// Not detectable by the adapter, and included for exactly that reason: the
    /// harness compares a read taken with this fault against the same read
    /// without it, so "a cancellation must not be reported as an absence" is
    /// *measured* rather than asserted. Nothing downstream of a mechanism can
    /// tell a dropped cancellation from an occurrence that never existed, which
    /// is the whole argument for representing it.
    case dropCancelledOccurrences
}

/// The in-process mechanism the WP-17 harness drives.
///
/// **Level of proof, stated plainly: in-process, over a seam, against a store
/// this package seeded itself.** No EventKit event store is constructed
/// anywhere in this repository, no TCC grant is held or requested, and no
/// calendar belonging to anyone is read. What the seam buys is that every
/// refusal lives in
/// `BoundedCalendarReadAdapter`, so the refusals hold for any mechanism
/// satisfying the seam — including an EventKit one, if an operator ever grants
/// the consent that would let somebody write it.
///
/// Mutable state with plain `var`s and `@unchecked Sendable`, following
/// `FixtureMailMechanism`: the contract-check executable drives this from one
/// thread, and the call counters exist so that "no read happened" can be
/// *measured* after a refusal rather than inferred by reading the adapter.
public final class FixtureCalendarMechanism: CalendarMechanism, @unchecked Sendable {
    public let descriptor: CalendarMechanismDescriptor

    private let accountDescriptors: [CalendarAccountDescriptor]
    private let calendarDescriptors: [CalendarBucketDescriptor]
    private let store: [(key: String, occurrence: CalendarOccurrence)]
    private var authorization: CalendarAuthorizationState
    private var fault: FixtureCalendarFault

    public private(set) var authorizationCalls = 0
    public private(set) var accountCalls = 0
    public private(set) var calendarCalls = 0
    public private(set) var occurrenceCalls = 0

    public init(
        descriptor: CalendarMechanismDescriptor,
        accounts: [CalendarAccountDescriptor],
        calendars: [CalendarBucketDescriptor],
        occurrences: [CalendarOccurrence],
        authorization: CalendarAuthorizationState = .authorized,
        fault: FixtureCalendarFault = .none
    ) throws {
        self.descriptor = descriptor
        self.accountDescriptors = accounts
        self.calendarDescriptors = calendars
        self.store = try occurrences
            .map { (key: try $0.cursorKey(), occurrence: $0) }
            .sorted { $0.key < $1.key }
        self.authorization = authorization
        self.fault = fault
    }

    // MARK: Harness controls — not part of `CalendarMechanism`

    public func setAuthorization(_ state: CalendarAuthorizationState) {
        authorization = state
    }

    public func setFault(_ value: FixtureCalendarFault) {
        fault = value
    }

    public func resetCallCounters() {
        authorizationCalls = 0
        accountCalls = 0
        calendarCalls = 0
        occurrenceCalls = 0
    }

    public var readCalls: Int { accountCalls + calendarCalls + occurrenceCalls }

    // MARK: CalendarMechanism

    public func authorizationState() throws -> CalendarAuthorizationState {
        authorizationCalls += 1
        return authorization
    }

    public func accounts() throws -> [CalendarAccountDescriptor] {
        accountCalls += 1
        return accountDescriptors
    }

    public func calendars() throws -> [CalendarBucketDescriptor] {
        calendarCalls += 1
        return calendarDescriptors
    }

    public func occurrences(_ query: CalendarTraversalQuery) throws -> CalendarTraversalResult {
        occurrenceCalls += 1
        var selected = store
        if fault != .leakAnotherCalendarsOccurrence {
            selected = selected.filter { $0.occurrence.identity.series.bucket == query.bucket }
        }
        if fault == .dropCancelledOccurrences {
            selected = selected.filter { $0.occurrence.lifecycle != .cancelled }
        }
        if fault != .ignoreTheWindow {
            selected = selected.filter {
                $0.occurrence.schedule.overlaps(
                    startUnixMilliseconds: query.window.startUnixMilliseconds,
                    endUnixMilliseconds: query.window.endUnixMilliseconds
                )
            }
        }
        if let after = query.afterCursorKey {
            selected = selected.filter { $0.key > after }
        }
        var page = Array(selected.prefix(query.limit))
        var moreAvailable = selected.count > page.count
        if fault == .returnKeysOutOfOrder {
            page.reverse()
        }
        if fault == .claimMoreAvailableWithoutFillingThePage {
            page = Array(page.dropLast())
            moreAvailable = true
        }
        return CalendarTraversalResult(
            occurrences: page.map(\.occurrence),
            moreAvailable: moreAvailable,
            enumeratedWholeStore: fault == .declareWholeStoreEnumeration
        )
    }
}
