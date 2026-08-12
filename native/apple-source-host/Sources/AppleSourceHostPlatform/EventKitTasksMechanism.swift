import AppleSourceHost
import Dispatch
import EventKit
import Foundation

/// Dormant, read-only EventKit Reminders implementation of the Tasks seam.
///
/// The store is injected after separate operator admission. This type never
/// requests access and names none of EventKit's mutation methods. Reminder
/// enumeration is list-scoped, has a hard wall-clock ceiling, and returns one
/// extra item solely to prove whether a page was truncated.
public final class EventKitTasksMechanism: TasksMechanism, @unchecked Sendable {
    public let descriptor = TasksMechanismDescriptor(
        publishesStableIdentifiers: true,
        requiresOperatorConsent: true
    )

    private let store: EKEventStore
    private let fetchTimeout: DispatchTimeInterval

    public init(store: EKEventStore, fetchTimeoutSeconds: Int = 30) throws {
        guard 1...60 ~= fetchTimeoutSeconds else {
            throw NativeSourceContractError.tasksTraversalExceeded
        }
        self.store = store
        self.fetchTimeout = .seconds(fetchTimeoutSeconds)
    }

    public func authorizationState() throws -> TasksAuthorizationState {
        switch EKEventStore.authorizationStatus(for: .reminder) {
        case .authorized, .fullAccess: return .authorized
        case .denied, .writeOnly: return .denied
        case .restricted: return .restricted
        case .notDetermined: return .notDetermined
        @unknown default: return .denied
        }
    }

    public func accounts() throws -> [NativeSourceAccount] {
        let grouped = Dictionary(
            grouping: store.calendars(for: .reminder),
            by: { $0.source.sourceIdentifier }
        )
        return try grouped.map { providerKey, calendars in
            NativeSourceAccount(
                id: try PlatformIdentity.opaque("tasks-account", providerKey),
                kind: .tasks,
                displayLabel: calendars[0].source.title
            )
        }.sorted { $0.id.rawValue < $1.id.rawValue }
    }

    public func lists() throws -> [TaskListDescriptor] {
        try store.calendars(for: .reminder).map { calendar in
            TaskListDescriptor(
                id: try PlatformIdentity.opaque("tasks-list", calendar.calendarIdentifier),
                accountID: try PlatformIdentity.opaque(
                    "tasks-account", calendar.source.sourceIdentifier
                ),
                displayLabel: calendar.title
            )
        }.sorted { $0.id.rawValue < $1.id.rawValue }
    }

    public func tasks(
        list: NativeSourceOpaqueID,
        after: String?,
        limit: Int
    ) throws -> TasksTraversalResult {
        guard limit > 0, limit <= NativeSourceProtocolV1.maximumPageSize else {
            throw NativeSourceContractError.invalidPageLimit
        }
        let selected = try store.calendars(for: .reminder).filter {
            try PlatformIdentity.opaque("tasks-list", $0.calendarIdentifier) == list
        }
        guard selected.count == 1, let calendar = selected.first else {
            throw NativeSourceContractError.unknownBucket
        }
        let reminders = try fetch(
            predicate: store.predicateForReminders(in: [calendar]),
            maximumMaterialized: limit + 1
        )
        let values = try reminders.map { try observation($0, list: list) }
            .filter { after == nil || $0.id.rawValue > after! }
            .sorted { $0.id.rawValue < $1.id.rawValue }
        return TasksTraversalResult(
            tasks: Array(values.prefix(limit)),
            moreAvailable: values.count > limit
        )
    }

    private func fetch(predicate: NSPredicate, maximumMaterialized: Int) throws -> [EKReminder] {
        let state = ReminderFetchState(maximumMaterialized: maximumMaterialized)
        let signal = DispatchSemaphore(value: 0)
        let request = store.fetchReminders(matching: predicate) { reminders in
            state.finish(reminders ?? [])
            signal.signal()
        }
        guard signal.wait(timeout: .now() + fetchTimeout) == .success else {
            store.cancelFetchRequest(request)
            throw NativeSourceContractError.tasksTraversalExceeded
        }
        return try state.result()
    }

    private func observation(_ reminder: EKReminder, list: NativeSourceOpaqueID) throws
        -> TaskObservation {
        let providerID = reminder.calendarItemIdentifier
        let title = reminder.title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !providerID.isEmpty, !title.isEmpty else {
            throw NativeSourceContractError.tasksIdentityInconsistent
        }
        let modified = reminder.lastModifiedDate.map(milliseconds) ?? 0
        let due = reminder.dueDateComponents.flatMap {
            Calendar(identifier: .gregorian).date(from: $0)
        }.map(milliseconds)
        let completed = reminder.completionDate.map(milliseconds)
        return try TaskObservation(
            id: PlatformIdentity.opaque("tasks-item", providerID),
            listID: list,
            sourceRevision: PlatformIdentity.revision(
                "tasks-revision",
                providerID,
                String(modified),
                title,
                reminder.notes ?? "",
                due.map(String.init) ?? "",
                completed.map(String.init) ?? ""
            ),
            sourceModifiedUnixMilliseconds: modified,
            title: title,
            notes: reminder.notes,
            dueUnixMilliseconds: due,
            completedUnixMilliseconds: completed
        )
    }

    private func milliseconds(_ date: Date) -> Int64 {
        Int64((date.timeIntervalSince1970 * 1000).rounded())
    }
}

private final class ReminderFetchState: @unchecked Sendable {
    private let lock = NSLock()
    private let maximumMaterialized: Int
    private var reminders: [EKReminder]?

    init(maximumMaterialized: Int) { self.maximumMaterialized = maximumMaterialized }

    func finish(_ values: [EKReminder]) {
        lock.lock()
        reminders = values
        lock.unlock()
    }

    func result() throws -> [EKReminder] {
        lock.lock()
        defer { lock.unlock() }
        guard let reminders, reminders.count <= maximumMaterialized else {
            throw NativeSourceContractError.tasksTraversalExceeded
        }
        return reminders
    }
}
