import Foundation

/// WP-17 controls 3, 4 and 5, in the one place where they are the same problem.
///
/// A recurrence rule is written in **wall-clock** terms — "09:00 every weekday" —
/// and a calendar stores **instants**. The conversion between the two is where
/// calendar adapters break, and it breaks in three distinct ways that this
/// expander answers separately rather than averaging into one:
///
/// * **the local time is stable and the instant is not.** A 09:00 series in
///   `America/New_York` steps by 24 hours on most days and by 23 or 25 hours
///   across a DST transition. An expander that adds a fixed millisecond interval
///   — which is what `NativeRecurrenceExpander` does, correctly, for a series
///   that is *defined* in UTC — silently walks a wall-clock series an hour off
///   for half the year;
/// * **some wall clocks name no instant.** 02:30 on a US spring-forward Sunday
///   does not happen. This expander **refuses** the series rather than inventing
///   a nearby instant, because the invented one is indistinguishable from a real
///   one afterwards;
/// * **some wall clocks name two.** 01:30 on a US fall-back Sunday happens
///   twice. The earlier is taken, and the choice is written down here rather
///   than left to whichever comparison happened to run first.
///
/// Exceptions carry the other half. An exception with no replacement is a
/// **cancellation** and is expanded into an occurrence marked `cancelled` — not
/// omitted. An exception with a replacement is a **detached** instance and keeps
/// the identity anchored to the start the series originally scheduled, so moving
/// an occurrence is a move rather than a delete and a create.

public struct CalendarRecurrenceException: Codable, Hashable, Sendable {
    /// The start the series scheduled, which is what the exception is *about*.
    public let originalStartUnixMilliseconds: Int64
    /// Where the occurrence actually went. `nil` means it was cancelled, which
    /// is a fact about the occurrence and not its absence.
    public let replacement: CalendarTimedInterval?

    public init(
        originalStartUnixMilliseconds: Int64,
        replacement: CalendarTimedInterval?
    ) {
        self.originalStartUnixMilliseconds = originalStartUnixMilliseconds
        self.replacement = replacement
    }

    private enum CodingKeys: String, CodingKey { case originalStartUnixMilliseconds, replacement }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        self.init(
            originalStartUnixMilliseconds: try values.decode(
                Int64.self,
                forKey: .originalStartUnixMilliseconds
            ),
            replacement: try values.decodeIfPresent(
                CalendarTimedInterval.self,
                forKey: .replacement
            )
        )
    }

    public var isCancellation: Bool { replacement == nil }
}

/// A series defined by a local wall clock in a named zone.
public struct CalendarRecurringSeries: Codable, Hashable, Sendable {
    public let identity: CalendarSeriesIdentity
    public let timezoneIdentifier: String
    /// The local start of the first occurrence. Every later occurrence keeps
    /// this time-of-day, whatever that does to the instant.
    public let firstWallClock: CalendarWallClock
    public let durationSeconds: Int64
    public let intervalDays: Int
    public let occurrenceCount: Int
    public let exceptions: [CalendarRecurrenceException]
    public let lastModifiedUnixMilliseconds: Int64

    public init(
        identity: CalendarSeriesIdentity,
        timezoneIdentifier: String,
        firstWallClock: CalendarWallClock,
        durationSeconds: Int64,
        intervalDays: Int,
        occurrenceCount: Int,
        exceptions: [CalendarRecurrenceException],
        lastModifiedUnixMilliseconds: Int64
    ) throws {
        _ = try CalendarZone.resolve(timezoneIdentifier)
        guard durationSeconds >= 0,
              intervalDays > 0,
              intervalDays <= NativeSourceProtocolV1.maximumCalendarHorizonDays
        else {
            throw NativeSourceContractError.invalidRecurrence
        }
        guard occurrenceCount > 0,
              occurrenceCount <= NativeSourceProtocolV1.maximumCalendarSeriesOccurrences
        else {
            throw NativeSourceContractError.recurrenceLimitExceeded
        }
        let starts = exceptions.map(\.originalStartUnixMilliseconds)
        guard Set(starts).count == starts.count, starts == starts.sorted() else {
            throw NativeSourceContractError.invalidRecurrence
        }
        self.identity = identity
        self.timezoneIdentifier = timezoneIdentifier
        self.firstWallClock = firstWallClock
        self.durationSeconds = durationSeconds
        self.intervalDays = intervalDays
        self.occurrenceCount = occurrenceCount
        self.exceptions = exceptions
        self.lastModifiedUnixMilliseconds = lastModifiedUnixMilliseconds
    }

    private enum CodingKeys: String, CodingKey {
        case identity, timezoneIdentifier, firstWallClock, durationSeconds
        case intervalDays, occurrenceCount, exceptions, lastModifiedUnixMilliseconds
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            identity: values.decode(CalendarSeriesIdentity.self, forKey: .identity),
            timezoneIdentifier: values.decode(String.self, forKey: .timezoneIdentifier),
            firstWallClock: values.decode(CalendarWallClock.self, forKey: .firstWallClock),
            durationSeconds: values.decode(Int64.self, forKey: .durationSeconds),
            intervalDays: values.decode(Int.self, forKey: .intervalDays),
            occurrenceCount: values.decode(Int.self, forKey: .occurrenceCount),
            exceptions: values.decode([CalendarRecurrenceException].self, forKey: .exceptions),
            lastModifiedUnixMilliseconds: values.decode(
                Int64.self,
                forKey: .lastModifiedUnixMilliseconds
            )
        )
    }
}

/// Expands a wall-clock series into occurrences, with every one of them present.
public enum CalendarSeriesExpander {
    /// Which of two instants an ambiguous wall clock resolves to.
    ///
    /// The earlier, always. Stated as a constant rather than left implicit
    /// because the alternative is not wrong so much as *undecided*, and an
    /// undecided answer moves an event by an hour once a year depending on which
    /// branch a comparison took.
    public static let ambiguousWallClockTakesTheEarlierInstant = true

    public static func expand(_ series: CalendarRecurringSeries) throws -> [CalendarOccurrence] {
        let zone = try CalendarZone.resolve(series.timezoneIdentifier)
        let exceptionsByStart = Dictionary(
            uniqueKeysWithValues: series.exceptions.map { ($0.originalStartUnixMilliseconds, $0) }
        )
        var consumed = 0
        var result: [CalendarOccurrence] = []
        result.reserveCapacity(series.occurrenceCount)

        for index in 0..<series.occurrenceCount {
            let epochDay = series.firstWallClock.date.epochDay
                + Int64(index) * Int64(series.intervalDays)
            let wallClock = CalendarWallClock(
                date: CalendarDate(epochDay: epochDay),
                secondsOfDay: series.firstWallClock.secondsOfDay
            )
            let start: Int64
            switch CalendarZone.resolve(wallClock, in: zone) {
            case .skipped:
                // The local time this series is defined at does not exist on
                // this date. Every way of continuing invents an instant, and an
                // invented instant is indistinguishable from a real one once it
                // is in a record.
                throw NativeSourceContractError.calendarScheduleInconsistent
            case let .unique(instant):
                start = instant
            case let .ambiguous(earlier, later):
                start = ambiguousWallClockTakesTheEarlierInstant ? earlier : later
            }
            let (end, overflow) = start.addingReportingOverflow(series.durationSeconds * 1000)
            guard !overflow else {
                throw NativeSourceContractError.invalidRecurrence
            }
            let identity = CalendarOccurrenceIdentity(
                series: series.identity,
                originalStartUnixMilliseconds: start
            )

            if let exception = exceptionsByStart[start] {
                consumed += 1
                if let replacement = exception.replacement {
                    result.append(
                        try CalendarOccurrence(
                            identity: identity,
                            lifecycle: .detached,
                            schedule: .timed(replacement),
                            lastModifiedUnixMilliseconds: series.lastModifiedUnixMilliseconds
                        )
                    )
                } else {
                    // Emitted, not dropped. This line is WP-17 control 4.
                    result.append(
                        try CalendarOccurrence(
                            identity: identity,
                            lifecycle: .cancelled,
                            schedule: .timed(
                                try CalendarTimedInterval.at(
                                    startUnixMilliseconds: start,
                                    endUnixMilliseconds: end,
                                    timezoneIdentifier: series.timezoneIdentifier
                                )
                            ),
                            lastModifiedUnixMilliseconds: series.lastModifiedUnixMilliseconds
                        )
                    )
                }
            } else {
                result.append(
                    try CalendarOccurrence(
                        identity: identity,
                        lifecycle: .confirmed,
                        schedule: .timed(
                            try CalendarTimedInterval.at(
                                startUnixMilliseconds: start,
                                endUnixMilliseconds: end,
                                timezoneIdentifier: series.timezoneIdentifier
                            )
                        ),
                        lastModifiedUnixMilliseconds: series.lastModifiedUnixMilliseconds
                    )
                )
            }
        }

        // An exception that matches no scheduled start is a statement about an
        // occurrence this series never had. Accepting it would mean the series
        // and its exception list disagree and nothing notices.
        guard consumed == series.exceptions.count else {
            throw NativeSourceContractError.calendarLifecycleInconsistent
        }
        return result
    }
}
