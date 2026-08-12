import Foundation

/// WP-17's time representation, and the one place this package disagrees with
/// the obvious design.
///
/// **An all-day event is not an instant, and a timed event is not a wall clock.**
/// Calendar adapters usually break by picking one representation and converting
/// the other into it, and both directions lose something a consumer cannot
/// recover:
///
/// * rendering an all-day event as "midnight local" makes it a different day for
///   a reader in a different zone, and there is no way to tell afterwards that a
///   whole day was meant. So `CalendarAllDaySpan` holds *dates* and has no
///   instant field at all — the invariant is enforced by there being nowhere to
///   put one;
/// * storing a timed event as a wall clock loses the DST answer, because a wall
///   clock can name an instant that does not exist (the spring-forward gap) or
///   two instants that do (the fall-back repeated hour). So
///   `CalendarTimedInterval` holds the **instant as the authority** and the wall
///   clock as a *derived, verified* companion: the initialiser recomputes the
///   wall clock from the instant and refuses the value if the two disagree.
///
/// The civil arithmetic below is integer-only and uses no `Calendar` and no
/// locale. A Gregorian date is a total function of a day number, and routing it
/// through a locale-sensitive type would make the all-day representation depend
/// on the reader after all.

// MARK: - Civil date arithmetic

public enum CalendarCivil {
    public static let millisecondsPerDay: Int64 = 86_400_000
    public static let secondsPerDay: Int64 = 86_400

    /// Widest UTC offset any zone on Earth uses, east and west. Used only to
    /// bound an all-day span outward — never to place one.
    public static let widestEastwardOffsetSeconds: Int64 = 14 * 3600
    public static let widestWestwardOffsetSeconds: Int64 = 12 * 3600

    /// Floor division, so instants and days before 1970 round down rather than
    /// toward zero. Swift's `/` truncates toward zero, which moves a negative
    /// instant into the wrong day.
    public static func floorDivide(_ value: Int64, by divisor: Int64) -> Int64 {
        let quotient = value / divisor
        let remainder = value % divisor
        return remainder < 0 ? quotient - 1 : quotient
    }

    public static func floorModulo(_ value: Int64, by divisor: Int64) -> Int64 {
        value - (floorDivide(value, by: divisor) * divisor)
    }

    public static func isLeapYear(_ year: Int) -> Bool {
        (year % 4 == 0 && year % 100 != 0) || year % 400 == 0
    }

    public static func daysInMonth(year: Int, month: Int) -> Int {
        switch month {
        case 1, 3, 5, 7, 8, 10, 12: return 31
        case 4, 6, 9, 11: return 30
        case 2: return isLeapYear(year) ? 29 : 28
        default: return 0
        }
    }

    /// Days since 1970-01-01 in the proleptic Gregorian calendar.
    public static func daysFromCivil(year: Int, month: Int, day: Int) -> Int64 {
        var shiftedYear = Int64(year)
        if month <= 2 { shiftedYear -= 1 }
        let era = (shiftedYear >= 0 ? shiftedYear : shiftedYear - 399) / 400
        let yearOfEra = shiftedYear - era * 400
        let shiftedMonth = Int64(month) + (month > 2 ? -3 : 9)
        let dayOfYear = (153 * shiftedMonth + 2) / 5 + Int64(day) - 1
        let dayOfEra = yearOfEra * 365 + yearOfEra / 4 - yearOfEra / 100 + dayOfYear
        return era * 146_097 + dayOfEra - 719_468
    }

    /// The inverse of `daysFromCivil`.
    public static func civilFromDays(_ epochDay: Int64) -> (year: Int, month: Int, day: Int) {
        let shifted = epochDay + 719_468
        let era = (shifted >= 0 ? shifted : shifted - 146_096) / 146_097
        let dayOfEra = shifted - era * 146_097
        let yearOfEra =
            (dayOfEra - dayOfEra / 1460 + dayOfEra / 36_524 - dayOfEra / 146_096) / 365
        let dayOfYear = dayOfEra - (365 * yearOfEra + yearOfEra / 4 - yearOfEra / 100)
        let shiftedMonth = (5 * dayOfYear + 2) / 153
        let day = dayOfYear - (153 * shiftedMonth + 2) / 5 + 1
        let month = shiftedMonth + (shiftedMonth < 10 ? 3 : -9)
        let year = yearOfEra + era * 400 + (month <= 2 ? 1 : 0)
        return (Int(year), Int(month), Int(day))
    }
}

// MARK: - A calendar date

/// One Gregorian date. No zone, no instant, no hour.
public struct CalendarDate: Codable, Hashable, Sendable, Comparable {
    public let year: Int
    public let month: Int
    public let day: Int

    public init(year: Int, month: Int, day: Int) throws {
        guard year >= 1, year <= 9999,
              month >= 1, month <= 12,
              day >= 1, day <= CalendarCivil.daysInMonth(year: year, month: month)
        else {
            throw NativeSourceContractError.calendarScheduleInconsistent
        }
        self.year = year
        self.month = month
        self.day = day
    }

    /// Non-failing construction from a day number, for derivation paths.
    /// `civilFromDays` is a total function whose output is always a real date,
    /// so this cannot produce a value the throwing initialiser would reject —
    /// but it is deliberately not `public`, so nothing outside this module can
    /// route around the validation.
    init(epochDay: Int64) {
        let civil = CalendarCivil.civilFromDays(epochDay)
        self.year = civil.year
        self.month = civil.month
        self.day = civil.day
    }

    private enum CodingKeys: String, CodingKey { case year, month, day }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            year: values.decode(Int.self, forKey: .year),
            month: values.decode(Int.self, forKey: .month),
            day: values.decode(Int.self, forKey: .day)
        )
    }

    public var epochDay: Int64 {
        CalendarCivil.daysFromCivil(year: year, month: month, day: day)
    }

    /// The zero-offset day number this date composes to, in milliseconds.
    ///
    /// **This is an identity anchor and not a time the event happens.** It is a
    /// pure function of the date, so it is the same integer for every reader in
    /// every zone, which is exactly what an occurrence key needs. Nothing may
    /// read it as "the event starts at UTC midnight"; `CalendarAllDaySpan` has no
    /// start instant to read.
    public var identityAnchorUnixMilliseconds: Int64 {
        epochDay * CalendarCivil.millisecondsPerDay
    }

    public static func < (lhs: CalendarDate, rhs: CalendarDate) -> Bool {
        (lhs.year, lhs.month, lhs.day) < (rhs.year, rhs.month, rhs.day)
    }
}

// MARK: - A wall clock

/// A local date and time-of-day, with no zone and therefore no instant.
public struct CalendarWallClock: Codable, Hashable, Sendable {
    public let date: CalendarDate
    public let hour: Int
    public let minute: Int
    public let second: Int

    public init(date: CalendarDate, hour: Int, minute: Int, second: Int) throws {
        guard hour >= 0, hour <= 23, minute >= 0, minute <= 59, second >= 0, second <= 59 else {
            throw NativeSourceContractError.calendarScheduleInconsistent
        }
        self.date = date
        self.hour = hour
        self.minute = minute
        self.second = second
    }

    init(date: CalendarDate, secondsOfDay: Int64) {
        self.date = date
        self.hour = Int(secondsOfDay / 3600)
        self.minute = Int((secondsOfDay % 3600) / 60)
        self.second = Int(secondsOfDay % 60)
    }

    private enum CodingKeys: String, CodingKey { case date, hour, minute, second }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            date: values.decode(CalendarDate.self, forKey: .date),
            hour: values.decode(Int.self, forKey: .hour),
            minute: values.decode(Int.self, forKey: .minute),
            second: values.decode(Int.self, forKey: .second)
        )
    }

    public var secondsOfDay: Int64 { Int64(hour) * 3600 + Int64(minute) * 60 + Int64(second) }

    /// The instant this wall clock would name **if it were UTC**. Only used as
    /// the search origin when resolving it in a real zone; it is not the answer.
    public var secondsIfZoneless: Int64 {
        date.epochDay * CalendarCivil.secondsPerDay + secondsOfDay
    }
}

// MARK: - Zone resolution, including the two DST answers that are not "an instant"

/// What a wall clock resolves to in a named zone.
///
/// Three cases and not one, because a DST transition genuinely produces three
/// answers and collapsing them is how an hour goes missing or an event lands an
/// hour off once a year.
public enum CalendarWallClockResolution: Hashable, Sendable {
    /// The spring-forward gap: this local time never happens on this date.
    case skipped
    case unique(Int64)
    /// The fall-back repeated hour: this local time happens twice.
    case ambiguous(earlier: Int64, later: Int64)
}

public enum CalendarZone {
    public static func resolve(_ identifier: String) throws -> TimeZone {
        guard let zone = TimeZone(identifier: identifier) else {
            throw NativeSourceContractError.calendarUnknownTimezone
        }
        return zone
    }

    public static func offsetSeconds(atUnixMilliseconds instant: Int64, in zone: TimeZone) -> Int64 {
        let seconds = CalendarCivil.floorDivide(instant, by: 1000)
        return Int64(zone.secondsFromGMT(for: Date(timeIntervalSince1970: Double(seconds))))
    }

    /// The wall clock an instant shows in a zone. Total: every instant has one.
    public static func wallClock(
        atUnixMilliseconds instant: Int64,
        in zone: TimeZone
    ) -> CalendarWallClock {
        let utcSeconds = CalendarCivil.floorDivide(instant, by: 1000)
        let localSeconds = utcSeconds + offsetSeconds(atUnixMilliseconds: instant, in: zone)
        let epochDay = CalendarCivil.floorDivide(localSeconds, by: CalendarCivil.secondsPerDay)
        let secondsOfDay = CalendarCivil.floorModulo(localSeconds, by: CalendarCivil.secondsPerDay)
        return CalendarWallClock(date: CalendarDate(epochDay: epochDay), secondsOfDay: secondsOfDay)
    }

    /// The instants a wall clock names in a zone — zero, one or two of them.
    ///
    /// Each candidate offset is confirmed by round-tripping it: an offset is
    /// only accepted if the instant it produces is genuinely at that offset.
    /// That is what makes the gap answer `skipped` rather than a plausible-
    /// looking instant an hour away.
    public static func resolve(
        _ wallClock: CalendarWallClock,
        in zone: TimeZone
    ) -> CalendarWallClockResolution {
        let origin = wallClock.secondsIfZoneless
        var candidates: Set<Int64> = []
        for probe in [origin - CalendarCivil.secondsPerDay, origin, origin + CalendarCivil.secondsPerDay] {
            let offset = Int64(zone.secondsFromGMT(for: Date(timeIntervalSince1970: Double(probe))))
            let candidate = origin - offset
            let confirmed = Int64(
                zone.secondsFromGMT(for: Date(timeIntervalSince1970: Double(candidate)))
            )
            if confirmed == offset { candidates.insert(candidate * 1000) }
        }
        let sorted = candidates.sorted()
        switch sorted.count {
        case 0: return .skipped
        case 1: return .unique(sorted[0])
        default: return .ambiguous(earlier: sorted[0], later: sorted[sorted.count - 1])
        }
    }
}

// MARK: - The two schedule shapes

/// An all-day event: whole calendar days, and no instant anywhere in the type.
///
/// The bounds below exist so a UTC-windowed read can decide overlap without
/// choosing a zone. They are the widest offsets any zone on Earth uses, applied
/// outward, so the window can never *drop* an all-day event that might belong in
/// it. Outward only, exactly as `MailDayWindow.widening` is: narrowing here would
/// be silent loss and widening is at worst an extra record the caller can see.
public struct CalendarAllDaySpan: Codable, Hashable, Sendable {
    public let firstDay: CalendarDate
    /// Inclusive. A one-day event has `firstDay == lastDay`.
    public let lastDay: CalendarDate

    public init(firstDay: CalendarDate, lastDay: CalendarDate) throws {
        guard firstDay <= lastDay else {
            throw NativeSourceContractError.calendarScheduleInconsistent
        }
        self.firstDay = firstDay
        self.lastDay = lastDay
    }

    private enum CodingKeys: String, CodingKey { case firstDay, lastDay }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            firstDay: values.decode(CalendarDate.self, forKey: .firstDay),
            lastDay: values.decode(CalendarDate.self, forKey: .lastDay)
        )
    }

    public var earliestPossibleStartUnixMilliseconds: Int64 {
        firstDay.identityAnchorUnixMilliseconds
            - (CalendarCivil.widestEastwardOffsetSeconds * 1000)
    }

    public var latestPossibleEndUnixMilliseconds: Int64 {
        (lastDay.epochDay + 1) * CalendarCivil.millisecondsPerDay
            + (CalendarCivil.widestWestwardOffsetSeconds * 1000)
    }
}

/// A timed event: the instant is the authority and the wall clock is verified
/// against it.
public struct CalendarTimedInterval: Codable, Hashable, Sendable {
    public let startUnixMilliseconds: Int64
    public let endUnixMilliseconds: Int64
    /// The zone the event is *defined* in, which is frequently not the reader's.
    public let timezoneIdentifier: String
    public let startWallClock: CalendarWallClock
    public let endWallClock: CalendarWallClock

    public init(
        startUnixMilliseconds: Int64,
        endUnixMilliseconds: Int64,
        timezoneIdentifier: String,
        startWallClock: CalendarWallClock,
        endWallClock: CalendarWallClock
    ) throws {
        guard startUnixMilliseconds <= endUnixMilliseconds else {
            throw NativeSourceContractError.calendarScheduleInconsistent
        }
        let zone = try CalendarZone.resolve(timezoneIdentifier)
        let derivedStart = CalendarZone.wallClock(
            atUnixMilliseconds: startUnixMilliseconds,
            in: zone
        )
        let derivedEnd = CalendarZone.wallClock(atUnixMilliseconds: endUnixMilliseconds, in: zone)
        guard derivedStart == startWallClock, derivedEnd == endWallClock else {
            throw NativeSourceContractError.calendarScheduleInconsistent
        }
        self.startUnixMilliseconds = startUnixMilliseconds
        self.endUnixMilliseconds = endUnixMilliseconds
        self.timezoneIdentifier = timezoneIdentifier
        self.startWallClock = startWallClock
        self.endWallClock = endWallClock
    }

    private enum CodingKeys: String, CodingKey {
        case startUnixMilliseconds, endUnixMilliseconds, timezoneIdentifier
        case startWallClock, endWallClock
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            startUnixMilliseconds: values.decode(Int64.self, forKey: .startUnixMilliseconds),
            endUnixMilliseconds: values.decode(Int64.self, forKey: .endUnixMilliseconds),
            timezoneIdentifier: values.decode(String.self, forKey: .timezoneIdentifier),
            startWallClock: values.decode(CalendarWallClock.self, forKey: .startWallClock),
            endWallClock: values.decode(CalendarWallClock.self, forKey: .endWallClock)
        )
    }

    /// Builds an interval from instants, deriving the wall clocks rather than
    /// being told them. The initialiser then re-derives and compares, so this
    /// convenience cannot smuggle an unverified pair through.
    public static func at(
        startUnixMilliseconds: Int64,
        endUnixMilliseconds: Int64,
        timezoneIdentifier: String
    ) throws -> CalendarTimedInterval {
        let zone = try CalendarZone.resolve(timezoneIdentifier)
        return try CalendarTimedInterval(
            startUnixMilliseconds: startUnixMilliseconds,
            endUnixMilliseconds: endUnixMilliseconds,
            timezoneIdentifier: timezoneIdentifier,
            startWallClock: CalendarZone.wallClock(
                atUnixMilliseconds: startUnixMilliseconds,
                in: zone
            ),
            endWallClock: CalendarZone.wallClock(atUnixMilliseconds: endUnixMilliseconds, in: zone)
        )
    }
}

/// What an occurrence is scheduled for: one shape or the other, never both and
/// never a lossy conversion between them.
public enum CalendarSchedule: Codable, Hashable, Sendable {
    case timed(CalendarTimedInterval)
    case allDay(CalendarAllDaySpan)

    public var isAllDay: Bool {
        if case .allDay = self { return true }
        return false
    }

    /// The occurrence key anchor for this schedule, which is a *date-derived*
    /// integer for an all-day span and the start instant for a timed interval.
    public var scheduleAnchorUnixMilliseconds: Int64 {
        switch self {
        case let .timed(interval): return interval.startUnixMilliseconds
        case let .allDay(span): return span.firstDay.identityAnchorUnixMilliseconds
        }
    }

    /// Overlap against a UTC window, computed outward for an all-day span so no
    /// reader's zone can exclude one.
    public func overlaps(startUnixMilliseconds: Int64, endUnixMilliseconds: Int64) -> Bool {
        switch self {
        case let .timed(interval):
            return interval.startUnixMilliseconds <= endUnixMilliseconds
                && interval.endUnixMilliseconds >= startUnixMilliseconds
        case let .allDay(span):
            return span.earliestPossibleStartUnixMilliseconds <= endUnixMilliseconds
                && span.latestPossibleEndUnixMilliseconds >= startUnixMilliseconds
        }
    }

    private enum CodingKeys: String, CodingKey { case form, timed, allDay }

    private enum Form: String, Codable { case timed, allDay = "all_day" }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        switch try values.decode(Form.self, forKey: .form) {
        case .timed:
            self = .timed(try values.decode(CalendarTimedInterval.self, forKey: .timed))
        case .allDay:
            self = .allDay(try values.decode(CalendarAllDaySpan.self, forKey: .allDay))
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case let .timed(interval):
            try container.encode(Form.timed, forKey: .form)
            try container.encode(interval, forKey: .timed)
        case let .allDay(span):
            try container.encode(Form.allDay, forKey: .form)
            try container.encode(span, forKey: .allDay)
        }
    }
}
