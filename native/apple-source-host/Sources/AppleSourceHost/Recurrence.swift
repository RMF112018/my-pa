public struct NativeRecurrenceException: Codable, Hashable, Sendable {
    public let scheduledStartUnixMilliseconds: Int64
    public let replacementStartUnixMilliseconds: Int64?
    public let replacementEndUnixMilliseconds: Int64?

    public init(
        scheduledStartUnixMilliseconds: Int64,
        replacementStartUnixMilliseconds: Int64?,
        replacementEndUnixMilliseconds: Int64?
    ) throws {
        let bothAbsent = replacementStartUnixMilliseconds == nil && replacementEndUnixMilliseconds == nil
        let bothPresent = replacementStartUnixMilliseconds != nil && replacementEndUnixMilliseconds != nil
        guard bothAbsent || bothPresent else {
            throw NativeSourceContractError.invalidRecurrence
        }
        if let start = replacementStartUnixMilliseconds, let end = replacementEndUnixMilliseconds {
            guard start <= end else {
                throw NativeSourceContractError.invalidRecurrence
            }
        }
        self.scheduledStartUnixMilliseconds = scheduledStartUnixMilliseconds
        self.replacementStartUnixMilliseconds = replacementStartUnixMilliseconds
        self.replacementEndUnixMilliseconds = replacementEndUnixMilliseconds
    }

    private enum CodingKeys: String, CodingKey {
        case scheduledStartUnixMilliseconds
        case replacementStartUnixMilliseconds
        case replacementEndUnixMilliseconds
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            scheduledStartUnixMilliseconds: values.decode(
                Int64.self,
                forKey: .scheduledStartUnixMilliseconds
            ),
            replacementStartUnixMilliseconds: values.decodeIfPresent(
                Int64.self,
                forKey: .replacementStartUnixMilliseconds
            ),
            replacementEndUnixMilliseconds: values.decodeIfPresent(
                Int64.self,
                forKey: .replacementEndUnixMilliseconds
            )
        )
    }
}

/// A synthetic recurrence definition. Timezone is preserved as source evidence;
/// expansion uses the already-normalized UTC interval and never queries a live calendar.
public struct NativeRecurrenceSeries: Codable, Hashable, Sendable {
    public let seriesID: NativeSourceOpaqueID
    public let bucketID: NativeSourceOpaqueID
    public let timezoneIdentifier: String
    public let firstStartUnixMilliseconds: Int64
    public let durationMilliseconds: Int64
    public let intervalMilliseconds: Int64
    public let occurrenceCount: Int?
    public let exceptions: [NativeRecurrenceException]
    public let payload: [UInt8]

    public init(
        seriesID: NativeSourceOpaqueID,
        bucketID: NativeSourceOpaqueID,
        timezoneIdentifier: String,
        firstStartUnixMilliseconds: Int64,
        durationMilliseconds: Int64,
        intervalMilliseconds: Int64,
        occurrenceCount: Int?,
        exceptions: [NativeRecurrenceException],
        payload: [UInt8]
    ) throws {
        let schedules = exceptions.map(\.scheduledStartUnixMilliseconds)
        let countIsValid: Bool
        if let occurrenceCount {
            countIsValid = occurrenceCount > 0
        } else {
            countIsValid = true
        }
        let exceptionsAreValid = intervalMilliseconds > 0 && exceptions.allSatisfy { exception in
            let schedule = exception.scheduledStartUnixMilliseconds
            guard schedule >= firstStartUnixMilliseconds else { return false }
            let (distance, overflow) = schedule.subtractingReportingOverflow(
                firstStartUnixMilliseconds
            )
            guard !overflow, distance % intervalMilliseconds == 0 else { return false }
            return occurrenceCount.map({ distance / intervalMilliseconds < Int64($0) }) ?? true
        }
        guard !timezoneIdentifier.isEmpty,
              !timezoneIdentifier.contains(where: { $0.isNewline }),
              durationMilliseconds >= 0,
              intervalMilliseconds > 0,
              countIsValid,
              Set(schedules).count == schedules.count,
              schedules == schedules.sorted(),
              exceptionsAreValid
        else {
            throw NativeSourceContractError.invalidRecurrence
        }
        self.seriesID = seriesID
        self.bucketID = bucketID
        self.timezoneIdentifier = timezoneIdentifier
        self.firstStartUnixMilliseconds = firstStartUnixMilliseconds
        self.durationMilliseconds = durationMilliseconds
        self.intervalMilliseconds = intervalMilliseconds
        self.occurrenceCount = occurrenceCount
        self.exceptions = exceptions
        self.payload = payload
    }

    private enum CodingKeys: String, CodingKey {
        case seriesID, bucketID, timezoneIdentifier, firstStartUnixMilliseconds
        case durationMilliseconds, intervalMilliseconds, occurrenceCount, exceptions, payload
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            seriesID: values.decode(NativeSourceOpaqueID.self, forKey: .seriesID),
            bucketID: values.decode(NativeSourceOpaqueID.self, forKey: .bucketID),
            timezoneIdentifier: values.decode(String.self, forKey: .timezoneIdentifier),
            firstStartUnixMilliseconds: values.decode(
                Int64.self,
                forKey: .firstStartUnixMilliseconds
            ),
            durationMilliseconds: values.decode(Int64.self, forKey: .durationMilliseconds),
            intervalMilliseconds: values.decode(Int64.self, forKey: .intervalMilliseconds),
            occurrenceCount: values.decodeIfPresent(Int.self, forKey: .occurrenceCount),
            exceptions: values.decode([NativeRecurrenceException].self, forKey: .exceptions),
            payload: values.decode([UInt8].self, forKey: .payload)
        )
    }
}

public struct NativeOccurrenceIdentity: Codable, Hashable, Sendable {
    public let seriesID: NativeSourceOpaqueID
    public let scheduledStartUnixMilliseconds: Int64

    public init(seriesID: NativeSourceOpaqueID, scheduledStartUnixMilliseconds: Int64) {
        self.seriesID = seriesID
        self.scheduledStartUnixMilliseconds = scheduledStartUnixMilliseconds
    }
}

public struct NativeCalendarOccurrence: Codable, Hashable, Sendable {
    public let identity: NativeOccurrenceIdentity
    public let bucketID: NativeSourceOpaqueID
    public let timezoneIdentifier: String
    public let startUnixMilliseconds: Int64
    public let endUnixMilliseconds: Int64
    public let isException: Bool
    public let payload: [UInt8]
}

public enum NativeRecurrenceExpander {
    public static func expand(
        _ series: NativeRecurrenceSeries,
        in range: NativeTimeRange,
        maximumOccurrences: Int
    ) throws -> [NativeCalendarOccurrence] {
        guard maximumOccurrences > 0 else {
            throw NativeSourceContractError.recurrenceLimitExceeded
        }
        guard series.exceptions.count <= maximumOccurrences else {
            throw NativeSourceContractError.recurrenceLimitExceeded
        }
        let (evaluationLimit, evaluationLimitOverflow) = maximumOccurrences.addingReportingOverflow(
            series.exceptions.count
        )
        guard !evaluationLimitOverflow else {
            throw NativeSourceContractError.recurrenceLimitExceeded
        }
        var result: [NativeCalendarOccurrence] = []
        var index = try firstCandidateIndex(for: series, in: range)
        var scheduled = try schedule(for: index, in: series)
        var evaluated = 0
        let exceptionBySchedule = Dictionary(
            uniqueKeysWithValues: series.exceptions.map { ($0.scheduledStartUnixMilliseconds, $0) }
        )

        while scheduled <= range.endUnixMilliseconds {
            if let count = series.occurrenceCount, index >= Int64(count) {
                break
            }
            guard evaluated < evaluationLimit else {
                throw NativeSourceContractError.recurrenceLimitExceeded
            }
            evaluated += 1
            let baseEnd = try adding(series.durationMilliseconds, to: scheduled)
            let exception = exceptionBySchedule[scheduled]
            let actualStart = exception?.replacementStartUnixMilliseconds ?? scheduled
            let actualEnd = exception?.replacementEndUnixMilliseconds ?? baseEnd
            let cancelled = exception != nil && exception?.replacementStartUnixMilliseconds == nil
            let overlaps = actualStart <= range.endUnixMilliseconds && actualEnd >= range.startUnixMilliseconds
            if !cancelled && overlaps {
                guard result.count < maximumOccurrences else {
                    throw NativeSourceContractError.recurrenceLimitExceeded
                }
                result.append(
                    NativeCalendarOccurrence(
                        identity: NativeOccurrenceIdentity(
                            seriesID: series.seriesID,
                            scheduledStartUnixMilliseconds: scheduled
                        ),
                        bucketID: series.bucketID,
                        timezoneIdentifier: series.timezoneIdentifier,
                        startUnixMilliseconds: actualStart,
                        endUnixMilliseconds: actualEnd,
                        isException: exception != nil,
                        payload: series.payload
                    )
                )
            }
            let (nextIndex, indexOverflow) = index.addingReportingOverflow(1)
            let (nextSchedule, scheduleOverflow) = scheduled.addingReportingOverflow(
                series.intervalMilliseconds
            )
            if indexOverflow || scheduleOverflow { break }
            index = nextIndex
            scheduled = nextSchedule
        }
        return result
    }

    private static func adding(_ delta: Int64, to value: Int64) throws -> Int64 {
        let (sum, overflow) = value.addingReportingOverflow(delta)
        guard !overflow else {
            throw NativeSourceContractError.invalidRecurrence
        }
        return sum
    }

    private static func firstCandidateIndex(
        for series: NativeRecurrenceSeries,
        in range: NativeTimeRange
    ) throws -> Int64 {
        let (threshold, underflow) = range.startUnixMilliseconds
            .subtractingReportingOverflow(series.durationMilliseconds)
        let lowerBound = underflow ? Int64.min : threshold
        var index: Int64 = 0
        if series.firstStartUnixMilliseconds < lowerBound {
            let (distance, overflow) = lowerBound
                .subtractingReportingOverflow(series.firstStartUnixMilliseconds)
            guard !overflow else {
                throw NativeSourceContractError.invalidRecurrence
            }
            index = distance / series.intervalMilliseconds
            if try schedule(for: index, in: series) < lowerBound {
                index += 1
            }
        }
        for exception in series.exceptions {
            guard let start = exception.replacementStartUnixMilliseconds,
                  let end = exception.replacementEndUnixMilliseconds,
                  start <= range.endUnixMilliseconds,
                  end >= range.startUnixMilliseconds
            else {
                continue
            }
            let exceptionIndex = (exception.scheduledStartUnixMilliseconds
                - series.firstStartUnixMilliseconds) / series.intervalMilliseconds
            index = min(index, exceptionIndex)
        }
        return index
    }

    private static func schedule(
        for index: Int64,
        in series: NativeRecurrenceSeries
    ) throws -> Int64 {
        let (offset, overflow) = index.multipliedReportingOverflow(by: series.intervalMilliseconds)
        guard !overflow else {
            throw NativeSourceContractError.invalidRecurrence
        }
        return try adding(offset, to: series.firstStartUnixMilliseconds)
    }
}
