import Foundation

/// Authorization observed without prompting. Only `authorized` permits reads.
public enum TasksAuthorizationState: String, Codable, Sendable {
    case authorized
    case denied
    case restricted
    case notDetermined = "not_determined"
}

public struct TasksMechanismDescriptor: Codable, Hashable, Sendable {
    public let publishesStableIdentifiers: Bool
    public let requiresOperatorConsent: Bool

    public init(publishesStableIdentifiers: Bool, requiresOperatorConsent: Bool) {
        self.publishesStableIdentifiers = publishesStableIdentifiers
        self.requiresOperatorConsent = requiresOperatorConsent
    }
}

public struct TaskListDescriptor: Hashable, Sendable {
    public let id: NativeSourceOpaqueID
    public let accountID: NativeSourceOpaqueID
    public let displayLabel: String
    public let isSelectable: Bool

    public init(
        id: NativeSourceOpaqueID,
        accountID: NativeSourceOpaqueID,
        displayLabel: String,
        isSelectable: Bool = true
    ) {
        self.id = id
        self.accountID = accountID
        self.displayLabel = displayLabel
        self.isSelectable = isSelectable
    }
}

/// One source observation. It is evidence about a task in Reminders, not an
/// instruction to mutate it or an accepted canonical task.
public struct TaskObservation: Codable, Hashable, Sendable {
    public let id: NativeSourceOpaqueID
    public let listID: NativeSourceOpaqueID
    public let sourceRevision: String
    public let sourceModifiedUnixMilliseconds: Int64
    public let title: String
    public let notes: String?
    public let dueUnixMilliseconds: Int64?
    public let completedUnixMilliseconds: Int64?

    public init(
        id: NativeSourceOpaqueID,
        listID: NativeSourceOpaqueID,
        sourceRevision: String,
        sourceModifiedUnixMilliseconds: Int64,
        title: String,
        notes: String? = nil,
        dueUnixMilliseconds: Int64? = nil,
        completedUnixMilliseconds: Int64? = nil
    ) throws {
        guard !sourceRevision.isEmpty, !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else { throw NativeSourceContractError.tasksIdentityInconsistent }
        self.id = id
        self.listID = listID
        self.sourceRevision = sourceRevision
        self.sourceModifiedUnixMilliseconds = sourceModifiedUnixMilliseconds
        self.title = title
        self.notes = notes
        self.dueUnixMilliseconds = dueUnixMilliseconds
        self.completedUnixMilliseconds = completedUnixMilliseconds
    }
}

public struct TasksTraversalResult: Hashable, Sendable {
    public let tasks: [TaskObservation]
    public let moreAvailable: Bool

    public init(tasks: [TaskObservation], moreAvailable: Bool) {
        self.tasks = tasks
        self.moreAvailable = moreAvailable
    }
}

/// Read-only seam in front of EventKit Reminders. A live implementation remains
/// operator-gated because obtaining its TCC grant is pilot setup.
public protocol TasksMechanism: Sendable {
    var descriptor: TasksMechanismDescriptor { get }
    func authorizationState() throws -> TasksAuthorizationState
    func accounts() throws -> [NativeSourceAccount]
    func lists() throws -> [TaskListDescriptor]
    func tasks(list: NativeSourceOpaqueID, after: String?, limit: Int) throws -> TasksTraversalResult
}
