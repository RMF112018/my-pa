/// WP-17 EventKit **shape** probe — compile-time only, and it reads nothing.
///
/// This is the target that makes "the calendar mechanism requires an operator
/// TCC grant" a different statement from "the calendar mechanism does not
/// exist". EventKit is a real, documented, public read API — that is the honest
/// difference between WP-17 and WP-16, whose finding was a negative — and every
/// symbol a read-only calendar adapter would need is named below, resolved by
/// the compiler on every `swift build`.
///
/// Constraints this file must keep, and which
/// `tests/architecture/test_wp17_calendar_adapter.py` enforces rather than
/// trusts:
///
/// * **nothing is instantiated and nothing is called.** Types are referenced as
///   metatypes, instance members as key paths, and methods as *unapplied*
///   references. Every declaration below is a function that is compiled and
///   never invoked, which is the strongest form of "resolves" that costs
///   nothing at runtime. No `EKEventStore` is constructed anywhere in this
///   repository, so no consent dialogue can be reached and no calendar can be
///   enumerated;
/// * **no authorization is requested.** `EKEventStore.authorizationStatus(for:)`
///   is named as an unapplied reference and never called; the request APIs are
///   named nowhere at all. A TCC grant is operator-gated (EXT-04) and asking is
///   the thing this package refuses to do;
/// * **no mutating symbol appears.** There is no `save`, no `remove`, no
///   `commit`, no `EKEventEditViewController`. A read-only adapter needs none of
///   them, and naming one would end WP-15's control 1 as a *structural* claim
///   even in a target nothing links;
/// * **this target is a dependency of nothing.** A `swift build` compiles it, so
///   the compatibility claim is re-proved on every build, while the shipping
///   `AppleSourceHost` module keeps importing only `Foundation` and linking no
///   Apple framework. That link-time property is WP-15's control 1 and is the
///   strongest guarantee in this package.
///
/// **What this proves:** EventKit exists in this SDK, exposes these types, these
/// members and these read methods, and typechecks against them on this
/// toolchain. **What it does not prove:** that a live enumeration works, that TCC
/// will grant, that any of these members returns what a reader expects, or that
/// performance is acceptable. Those need an operator and a real machine — see
/// `docs/campaign/WP-17-CALENDAR-ADAPTER-RECORD.md`.
///
/// The key-path form is deliberate and is worth more than a metatype list. A
/// metatype proves a *type* resolves; `\EKEvent.occurrenceDate` proves a
/// *member* resolves, with its type, and the members are where a calendar
/// adapter's assumptions actually live.

import EventKit

public enum AppleCalendarEventKitShapeProbe {
    // MARK: The types a read-only calendar adapter would name

    public static func storeType() -> EKEventStore.Type { EKEventStore.self }
    public static func eventType() -> EKEvent.Type { EKEvent.self }
    public static func calendarType() -> EKCalendar.Type { EKCalendar.self }
    public static func sourceType() -> EKSource.Type { EKSource.self }
    public static func recurrenceRuleType() -> EKRecurrenceRule.Type { EKRecurrenceRule.self }
    public static func participantType() -> EKParticipant.Type { EKParticipant.self }

    // MARK: The enumerations that carry the semantics WP-17 is about

    /// Authorization, which is what control 2 fails closed on. Named as values;
    /// none of them is queried from a store.
    ///
    /// `@available(macOS 14, *)` is a finding rather than boilerplate: the
    /// package floor is macOS 13 (`SMAppService`, OD-COMP-009), and the split of
    /// calendar consent into `fullAccess` and `writeOnly` only exists from macOS
    /// 14. On 13 the vocabulary is the older single `authorized`. The adapter's
    /// `CalendarAuthorizationState` names the four states both versions agree
    /// on, so it does not depend on which of the two a host is running.
    @available(macOS 14.0, *)
    public static func authorizationStates() -> [EKAuthorizationStatus] {
        [.notDetermined, .restricted, .denied, .fullAccess, .writeOnly]
    }

    /// **Control 4's evidence.** EventKit models a cancelled event as a *status*
    /// on an event that is still there, not as an event that is gone. The
    /// adapter's `CalendarOccurrenceLifecycle.cancelled` is that fact carried
    /// across the seam rather than a convention this package invented.
    public static func eventStatuses() -> [EKEventStatus] {
        [.none, .confirmed, .tentative, .canceled]
    }

    public static func entityType() -> EKEntityType { .event }

    // MARK: The members, which is where a calendar adapter's assumptions live

    /// **Control 1's evidence.** `occurrenceDate` is the start the series
    /// originally scheduled an occurrence for, which is exactly the anchor
    /// `CalendarOccurrenceIdentity` uses; `isDetached` is EventKit's own name for
    /// a modified instance. Without the first, a moved occurrence would have to
    /// be keyed by where it is now, and every move would read as a delete and a
    /// create.
    public static func originalStartKeyPath() -> KeyPath<EKEvent, Date?> {
        \EKEvent.occurrenceDate
    }

    public static func detachedKeyPath() -> KeyPath<EKEvent, Bool> { \EKEvent.isDetached }

    /// **Control 5's evidence.** `isAllDay` and `timeZone` are separate members:
    /// an all-day event is a flag on the event rather than a midnight instant,
    /// and an event's zone is its own rather than the reader's.
    public static func allDayKeyPath() -> KeyPath<EKEvent, Bool> { \EKEvent.isAllDay }
    public static func zoneKeyPath() -> KeyPath<EKEvent, TimeZone?> { \EKEvent.timeZone }
    public static func startKeyPath() -> KeyPath<EKEvent, Date> { \EKEvent.startDate }
    public static func endKeyPath() -> KeyPath<EKEvent, Date> { \EKEvent.endDate }
    public static func statusKeyPath() -> KeyPath<EKEvent, EKEventStatus> { \EKEvent.status }

    /// The four identity levels, as EventKit publishes them: the source
    /// (account), the calendar, the series and the occurrence.
    public static func sourceIdentifierKeyPath() -> KeyPath<EKSource, String> {
        \EKSource.sourceIdentifier
    }

    public static func calendarIdentifierKeyPath() -> KeyPath<EKCalendar, String> {
        \EKCalendar.calendarIdentifier
    }

    public static func seriesIdentifierKeyPath() -> KeyPath<EKEvent, String> {
        \EKEvent.calendarItemIdentifier
    }

    public static func eventIdentifierKeyPath() -> KeyPath<EKEvent, String> {
        \EKEvent.eventIdentifier
    }

    public static func lastModifiedKeyPath() -> KeyPath<EKEvent, Date?> {
        \EKEvent.lastModifiedDate
    }

    // MARK: The read methods, referenced unapplied and never invoked

    /// **Control 3's and the horizon's evidence.** The bounded read is genuinely
    /// source-side: EventKit takes a start, an end and a calendar list and
    /// returns the occurrences in that window, already expanded. This is the
    /// method a live mechanism would implement `CalendarMechanism.occurrences`
    /// with, and the unapplied reference below proves its signature without
    /// creating a store to call it on.
    public static func boundedPredicateFactory()
        -> (EKEventStore) -> (Date, Date, [EKCalendar]?) -> NSPredicate {
        EKEventStore.predicateForEvents(withStart:end:calendars:)
    }

    public static func boundedReadMethod() -> (EKEventStore) -> (NSPredicate) -> [EKEvent] {
        EKEventStore.events(matching:)
    }

    public static func calendarListMethod() -> (EKEventStore) -> (EKEntityType) -> [EKCalendar] {
        EKEventStore.calendars(for:)
    }

    /// Observing authorization is a read; *requesting* it raises the dialogue.
    /// This is the observing one, referenced and never called.
    public static func authorizationStatusMethod() -> (EKEntityType) -> EKAuthorizationStatus {
        EKEventStore.authorizationStatus(for:)
    }

    /// Names only; nothing is opened, granted, enumerated or stored by this
    /// target.
    public static let probedFrameworks = ["EventKit"]
}
