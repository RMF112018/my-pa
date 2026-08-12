import Foundation

/// Immutable synthetic mechanism used by tests and local-candidate evidence.
public struct FixtureTasksMechanism: TasksMechanism, Sendable {
    public let descriptor: TasksMechanismDescriptor
    private let authorization: TasksAuthorizationState
    private let accountValues: [NativeSourceAccount]
    private let listValues: [TaskListDescriptor]
    private let taskValues: [TaskObservation]

    public init(
        authorization: TasksAuthorizationState,
        accounts: [NativeSourceAccount],
        lists: [TaskListDescriptor],
        tasks: [TaskObservation],
        publishesStableIdentifiers: Bool = true
    ) {
        self.authorization = authorization
        self.accountValues = accounts
        self.listValues = lists
        self.taskValues = tasks
        self.descriptor = TasksMechanismDescriptor(
            publishesStableIdentifiers: publishesStableIdentifiers,
            requiresOperatorConsent: true
        )
    }

    public func authorizationState() throws -> TasksAuthorizationState { authorization }
    public func accounts() throws -> [NativeSourceAccount] { accountValues }
    public func lists() throws -> [TaskListDescriptor] { listValues }
    public func tasks(
        list: NativeSourceOpaqueID,
        after: String?,
        limit: Int
    ) throws -> TasksTraversalResult {
        let matching = taskValues
            .filter { $0.listID == list && (after == nil || $0.id.rawValue > after!) }
            .sorted { $0.id.rawValue < $1.id.rawValue }
        return TasksTraversalResult(
            tasks: Array(matching.prefix(limit)),
            moreAvailable: matching.count > limit
        )
    }
}
