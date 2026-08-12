import AppleSourceHost
import EventKit
import Foundation

/// Production-shaped, read-only EventKit implementation of the calendar seam.
///
/// Construction accepts an existing store.  It never requests authorization,
/// creates an event, saves, removes, or commits.  Calling a read before a human
/// has separately granted Calendar access returns `permissionDenied` through the
/// bounded adapter.  Tests exercise only authorization observation and injected
/// mapping values; no local calendar is enumerated by repository validation.
public final class EventKitCalendarMechanism: CalendarMechanism, @unchecked Sendable {
    public let descriptor = CalendarMechanismDescriptor(
        mechanism: .eventKitStore,
        publishesOriginalOccurrenceStart: true,
        requiresOperatorConsent: true
    )

    private let store: EKEventStore

    public init(store: EKEventStore) {
        self.store = store
    }

    public func authorizationState() throws -> CalendarAuthorizationState {
        switch EKEventStore.authorizationStatus(for: .event) {
        case .authorized: return .authorized
        case .denied: return .denied
        case .restricted: return .restricted
        case .notDetermined: return .notDetermined
        case .fullAccess: return .authorized
        case .writeOnly: return .denied
        @unknown default: return .denied
        }
    }

    public func accounts() throws -> [CalendarAccountDescriptor] {
        let values = Dictionary(grouping: store.calendars(for: .event), by: { $0.source.sourceIdentifier })
        return try values.map { providerKey, calendars in
            CalendarAccountDescriptor(
                accountKey: try PlatformIdentity.calendar("calendar-account", providerKey),
                displayLabel: calendars[0].source.title
            )
        }.sorted { $0.accountKey.rawValue < $1.accountKey.rawValue }
    }

    public func calendars() throws -> [CalendarBucketDescriptor] {
        try store.calendars(for: .event).map { calendar in
            CalendarBucketDescriptor(
                identity: CalendarBucketIdentity(
                    accountKey: try PlatformIdentity.calendar(
                        "calendar-account", calendar.source.sourceIdentifier
                    ),
                    calendarKey: try PlatformIdentity.calendar(
                        "calendar-bucket", calendar.calendarIdentifier
                    )
                ),
                displayLabel: calendar.title,
                isSelectable: true
            )
        }.sorted { try $0.identity.recordIdentifier().rawValue < $1.identity.recordIdentifier().rawValue }
    }

    public func occurrences(_ query: CalendarTraversalQuery) throws -> CalendarTraversalResult {
        let selected = try store.calendars(for: .event).filter { calendar in
            CalendarBucketIdentity(
                accountKey: try PlatformIdentity.calendar(
                    "calendar-account", calendar.source.sourceIdentifier
                ),
                calendarKey: try PlatformIdentity.calendar(
                    "calendar-bucket", calendar.calendarIdentifier
                )
            ) == query.bucket
        }
        guard selected.count == 1 else { throw NativeSourceContractError.unknownBucket }
        let predicate = store.predicateForEvents(
            withStart: Date(timeIntervalSince1970: Double(query.window.startUnixMilliseconds) / 1000),
            end: Date(timeIntervalSince1970: Double(query.window.endUnixMilliseconds) / 1000),
            calendars: selected
        )
        let all = try store.events(matching: predicate).map(observation)
            .filter { try $0.cursorKey() > (query.afterCursorKey ?? "") }
            .sorted { try $0.cursorKey() < $1.cursorKey() }
        return CalendarTraversalResult(
            occurrences: Array(all.prefix(query.limit)),
            moreAvailable: all.count > query.limit,
            enumeratedWholeStore: false
        )
    }

    private func observation(_ event: EKEvent) throws -> CalendarOccurrence {
        guard let startDate = event.startDate, let endDate = event.endDate else {
            throw NativeSourceContractError.calendarScheduleInconsistent
        }
        let bucket = CalendarBucketIdentity(
            accountKey: try PlatformIdentity.calendar(
                "calendar-account", event.calendar.source.sourceIdentifier
            ),
            calendarKey: try PlatformIdentity.calendar(
                "calendar-bucket", event.calendar.calendarIdentifier
            )
        )
        let original = event.occurrenceDate ?? startDate
        let schedule: CalendarSchedule
        if event.isAllDay {
            var calendar = Calendar(identifier: .gregorian)
            calendar.timeZone = event.timeZone ?? .current
            let first = calendar.dateComponents([.year, .month, .day], from: startDate)
            let inclusiveEnd = endDate.addingTimeInterval(-1)
            let last = calendar.dateComponents([.year, .month, .day], from: inclusiveEnd)
            schedule = .allDay(
                try CalendarAllDaySpan(
                    firstDay: try CalendarDate(
                        year: required(first.year), month: required(first.month), day: required(first.day)
                    ),
                    lastDay: try CalendarDate(
                        year: required(last.year), month: required(last.month), day: required(last.day)
                    )
                )
            )
        } else {
            schedule = .timed(
                try CalendarTimedInterval.at(
                    startUnixMilliseconds: milliseconds(startDate),
                    endUnixMilliseconds: milliseconds(endDate),
                    timezoneIdentifier: (event.timeZone ?? .current).identifier
                )
            )
        }
        let originalMilliseconds: Int64
        if event.isAllDay {
            var calendar = Calendar(identifier: .gregorian)
            calendar.timeZone = event.timeZone ?? .current
            let originalDay = calendar.dateComponents([.year, .month, .day], from: original)
            originalMilliseconds = try CalendarDate(
                year: required(originalDay.year),
                month: required(originalDay.month),
                day: required(originalDay.day)
            ).identityAnchorUnixMilliseconds
        } else {
            originalMilliseconds = milliseconds(original)
        }
        let lifecycle: CalendarOccurrenceLifecycle = if event.status == .canceled {
            .cancelled
        } else if event.isDetached || schedule.scheduleAnchorUnixMilliseconds != originalMilliseconds {
            .detached
        } else {
            .confirmed
        }
        return try CalendarOccurrence(
            identity: CalendarOccurrenceIdentity(
                series: CalendarSeriesIdentity(
                    bucket: bucket,
                    seriesKey: try PlatformIdentity.calendar(
                        "calendar-series", event.calendarItemIdentifier
                    )
                ),
                originalStartUnixMilliseconds: originalMilliseconds
            ),
            lifecycle: lifecycle,
            schedule: schedule,
            lastModifiedUnixMilliseconds: milliseconds(event.lastModifiedDate ?? startDate)
        )
    }

    private func milliseconds(_ date: Date) -> Int64 {
        Int64((date.timeIntervalSince1970 * 1000).rounded())
    }

    private func required(_ value: Int?) throws -> Int {
        guard let value else { throw NativeSourceContractError.calendarScheduleInconsistent }
        return value
    }
}
