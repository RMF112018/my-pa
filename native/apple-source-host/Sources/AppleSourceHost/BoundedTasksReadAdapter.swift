import Foundation

/// Bounded, read-only Tasks/Reminders adapter. Authorization is rechecked on
/// every operation; over-bound, unordered, cross-list, or unstable input is
/// refused rather than filtered or acknowledged as empty.
public struct BoundedTasksReadAdapter: TasksReadAdapter, Sendable {
    private let mechanism: any TasksMechanism

    public init(mechanism: any TasksMechanism) { self.mechanism = mechanism }

    public var descriptor: TasksMechanismDescriptor { mechanism.descriptor }

    public func discoverTaskLists() throws -> NativeDiscoverySnapshot {
        try requireAuthorization()
        guard mechanism.descriptor.publishesStableIdentifiers else {
            throw NativeSourceContractError.tasksIdentityInconsistent
        }
        let accounts = try mechanism.accounts()
        let lists = try mechanism.lists()
        let accountIDs = Set(accounts.map(\.id))
        guard lists.allSatisfy({ accountIDs.contains($0.accountID) }) else {
            throw NativeSourceContractError.inconsistentDiscovery
        }
        return try NativeDiscoverySnapshot(
            kind: .tasks,
            accounts: accounts.sorted { $0.id.rawValue < $1.id.rawValue },
            buckets: lists.map {
                NativeSourceBucket(
                    id: $0.id,
                    accountID: $0.accountID,
                    kind: .tasks,
                    displayLabel: $0.displayLabel,
                    isSelectable: $0.isSelectable
                )
            }.sorted { $0.id.rawValue < $1.id.rawValue }
        )
    }

    public func readTasks(_ request: NativeReadRequest) throws -> NativeReadPage {
        try requireAuthorization()
        guard mechanism.descriptor.publishesStableIdentifiers else {
            throw NativeSourceContractError.tasksIdentityInconsistent
        }
        let result = try mechanism.tasks(
            list: request.bucketID,
            after: request.cursor?.rawValue,
            limit: request.limit
        )
        guard result.tasks.count <= request.limit,
              result.tasks.allSatisfy({ $0.listID == request.bucketID })
        else { throw NativeSourceContractError.inconsistentEnvelope }
        var previous = request.cursor?.rawValue
        for task in result.tasks {
            guard previous == nil || task.id.rawValue > previous! else {
                throw NativeSourceContractError.nonCanonicalOrder
            }
            previous = task.id.rawValue
        }
        let next: NativeReadCursor?
        if result.moreAvailable {
            guard result.tasks.count == request.limit,
                  let key = result.tasks.last?.id.rawValue,
                  let cursor = NativeReadCursor(rawValue: key)
            else { throw NativeSourceContractError.tasksTruncationUndeclared }
            next = cursor
        } else {
            next = nil
        }
        let records = try result.tasks.map {
            NativeSourceRecord(
                id: $0.id,
                bucketID: $0.listID,
                kind: .tasks,
                sourceRevision: $0.sourceRevision,
                sourceModifiedUnixMilliseconds: $0.sourceModifiedUnixMilliseconds,
                payload: Array(try JSONEncoder().encode($0))
            )
        }
        return try NativeReadPage(records: records, nextCursor: next)
    }

    private func requireAuthorization() throws {
        switch try mechanism.authorizationState() {
        case .authorized: return
        case .denied, .restricted, .notDetermined:
            throw NativeProviderFailure.permissionDenied
        }
    }
}
