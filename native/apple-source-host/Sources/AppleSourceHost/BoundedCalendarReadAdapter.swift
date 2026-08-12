import Foundation

/// The WP-17 Calendar adapter: bounded, read-only, and framework-free.
///
/// It implements the existing `CalendarReadAdapter` over `CalendarMechanism`.
/// Everything that makes the read safe lives here rather than in the mechanism,
/// so a future EventKit mechanism inherits the refusals instead of being trusted
/// to reimplement them:
///
/// * authorization is checked **before** the first read, and a mechanism that is
///   not authorized is never asked for anything on that request. The refusal is a
///   thrown `NativeProviderFailure.permissionDenied` and is therefore a
///   different *value* from a successful read of an empty calendar, which is an
///   empty `NativeReadPage`. "No authorization" must never arrive downstream
///   looking like "you have nothing scheduled";
/// * a mechanism that cannot publish an occurrence's original start is refused
///   outright, because occurrence identity is anchored to that start;
/// * an unbounded read is refused, and so is a window wider than the frozen
///   horizon. Neither is narrowed;
/// * the mechanism's own answer is re-checked against the window, the bucket and
///   the page limit it was given, so a mechanism that ignores its bounds is
///   caught rather than believed;
/// * a truncated page must declare itself, and the declaration is cross-checked
///   against the page it came with;
/// * **cancelled occurrences are carried, not filtered.** There is no `filter`
///   over lifecycle anywhere below, and that absence is the point: a page that
///   quietly drops cancellations reports absence where the source reported a
///   cancellation.
///
/// There is no mutation surface. The seam offers four operations and all four are
/// reads; this type adds none, and the only thing it writes is the page it
/// returns.
public struct BoundedCalendarReadAdapter: CalendarReadAdapter, Sendable {
    private let mechanism: any CalendarMechanism

    public init(mechanism: any CalendarMechanism) {
        self.mechanism = mechanism
    }

    public var descriptor: CalendarMechanismDescriptor { mechanism.descriptor }

    // MARK: Discovery

    public func discoverCalendars() throws -> NativeDiscoverySnapshot {
        try requireAuthorization()
        let accounts = try mechanism.accounts().map { descriptor in
            NativeSourceAccount(
                id: try descriptor.identity.recordIdentifier(),
                kind: .calendar,
                displayLabel: descriptor.displayLabel
            )
        }
        let buckets = try mechanism.calendars().map { descriptor in
            NativeSourceBucket(
                id: try descriptor.identity.recordIdentifier(),
                accountID: try descriptor.identity.account.recordIdentifier(),
                kind: .calendar,
                displayLabel: descriptor.displayLabel,
                isSelectable: descriptor.isSelectable
            )
        }
        return try NativeDiscoverySnapshot(
            kind: .calendar,
            accounts: accounts.sorted { $0.id.rawValue < $1.id.rawValue },
            buckets: buckets.sorted { $0.id.rawValue < $1.id.rawValue }
        )
    }

    // MARK: Traversal

    public func readCalendar(_ request: NativeReadRequest) throws -> NativeReadPage {
        try requireAuthorization()
        guard mechanism.descriptor.publishesOriginalOccurrenceStart else {
            throw NativeSourceContractError.calendarOriginalStartUnavailable
        }
        // A calendar has no natural end, so "no time range" is not a wider read —
        // it is an unbounded enumeration of something unbounded. Refused here
        // rather than passed to the mechanism to be sorted out.
        guard let range = request.timeRange else {
            throw NativeSourceContractError.calendarHorizonExceeded
        }
        let window = try CalendarHorizonWindow(range)
        let bucket = try CalendarBucketIdentity(bucketID: request.bucketID)
        let query = try CalendarTraversalQuery(
            bucket: bucket,
            window: window,
            afterCursorKey: request.cursor?.rawValue,
            limit: request.limit
        )
        let result = try mechanism.occurrences(query)

        guard !result.enumeratedWholeStore else {
            throw NativeSourceContractError.calendarUnboundedEnumeration
        }
        guard result.occurrences.count <= request.limit else {
            throw NativeSourceContractError.invalidPageLimit
        }
        try requireStrictlyAscendingUniqueKeys(result.occurrences, after: query.afterCursorKey)
        try requireEveryOccurrenceBelongsTo(bucket, result.occurrences)
        try requireEveryOccurrenceOverlaps(window, result.occurrences)

        let nextCursor = try honestNextCursor(for: result, limit: request.limit)
        let records = try result.occurrences.map { occurrence in
            try record(for: occurrence, bucketID: request.bucketID)
        }
        return try NativeReadPage(records: records, nextCursor: nextCursor)
    }

    // MARK: Internals

    /// Fail-closed, exhaustively, with no `default`.
    ///
    /// Exactly one authorization state permits a read and the other three refuse.
    /// The `switch` is exhaustive on purpose: a `default` arm would silently
    /// admit any state a later EventKit adds, and "a state we have not heard of"
    /// is not a state to read somebody's calendar on.
    private func requireAuthorization() throws {
        switch try mechanism.authorizationState() {
        case .authorized:
            return
        case .denied:
            throw NativeProviderFailure.permissionDenied
        case .restricted:
            throw NativeProviderFailure.permissionDenied
        case .notDetermined:
            throw NativeProviderFailure.permissionDenied
        }
    }

    private func requireStrictlyAscendingUniqueKeys(
        _ occurrences: [CalendarOccurrence],
        after: String?
    ) throws {
        var previous = after
        for occurrence in occurrences {
            let key = try occurrence.cursorKey()
            if let previous, key <= previous {
                throw NativeSourceContractError.nonCanonicalOrder
            }
            previous = key
        }
    }

    private func requireEveryOccurrenceBelongsTo(
        _ bucket: CalendarBucketIdentity,
        _ occurrences: [CalendarOccurrence]
    ) throws {
        guard occurrences.allSatisfy({ $0.identity.series.bucket == bucket }) else {
            throw NativeSourceContractError.unknownBucket
        }
    }

    private func requireEveryOccurrenceOverlaps(
        _ window: CalendarHorizonWindow,
        _ occurrences: [CalendarOccurrence]
    ) throws {
        guard occurrences.allSatisfy({
            $0.schedule.overlaps(
                startUnixMilliseconds: window.startUnixMilliseconds,
                endUnixMilliseconds: window.endUnixMilliseconds
            )
        }) else {
            throw NativeSourceContractError.calendarHorizonViolated
        }
    }

    /// The honest truncation signal, cross-checked rather than copied.
    ///
    /// A mechanism claiming more is available must have filled the page — a
    /// short page with more behind it is incoherent — and must have left an
    /// occurrence to resume from. Both halves are checked, because "more
    /// available" with no cursor is a caller that pages forever or stops early,
    /// depending on how charitable its loop is.
    private func honestNextCursor(
        for result: CalendarTraversalResult,
        limit: Int
    ) throws -> NativeReadCursor? {
        guard result.moreAvailable else { return nil }
        guard result.occurrences.count == limit, let last = result.occurrences.last else {
            throw NativeSourceContractError.calendarTruncationUndeclared
        }
        guard let cursor = NativeReadCursor(rawValue: try last.cursorKey()) else {
            throw NativeSourceContractError.calendarTruncationUndeclared
        }
        return cursor
    }

    private func record(
        for occurrence: CalendarOccurrence,
        bucketID: NativeSourceOpaqueID
    ) throws -> NativeSourceRecord {
        NativeSourceRecord(
            id: try occurrence.identity.recordIdentifier(),
            bucketID: bucketID,
            kind: .calendar,
            sourceRevision: String(occurrence.lastModifiedUnixMilliseconds),
            sourceModifiedUnixMilliseconds: occurrence.lastModifiedUnixMilliseconds,
            payload: Array(try JSONEncoder().encode(occurrence))
        )
    }
}
