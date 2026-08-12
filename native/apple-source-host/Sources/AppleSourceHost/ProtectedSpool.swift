import Darwin
import Foundation

public struct NativeSpoolItem: Codable, Hashable, Sendable {
    public let envelopeID: NativeSourceOpaqueID
    public let protocolVersion: String
    public let kind: NativeSourceKind
    public let accountID: NativeSourceOpaqueID
    public let bucketID: NativeSourceOpaqueID
    public let payload: [UInt8]

    public init(
        envelopeID: NativeSourceOpaqueID,
        protocolVersion: String = NativeSourceProtocolV1.identifier,
        kind: NativeSourceKind,
        accountID: NativeSourceOpaqueID,
        bucketID: NativeSourceOpaqueID,
        payload: [UInt8]
    ) throws {
        guard protocolVersion == NativeSourceProtocolV1.identifier else {
            throw NativeSourceContractError.unsupportedVersion
        }
        self.envelopeID = envelopeID
        self.protocolVersion = protocolVersion
        self.kind = kind
        self.accountID = accountID
        self.bucketID = bucketID
        self.payload = payload
    }

    public init(admissionEnvelope: NativeAdmissionEnvelope) throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        try self.init(
            envelopeID: admissionEnvelope.metadata.envelopeID,
            protocolVersion: admissionEnvelope.metadata.protocolVersion,
            kind: admissionEnvelope.kind,
            accountID: admissionEnvelope.accountID,
            bucketID: admissionEnvelope.bucketID,
            payload: Array(try encoder.encode(admissionEnvelope))
        )
    }

    private enum CodingKeys: String, CodingKey {
        case envelopeID, protocolVersion, kind, accountID, bucketID, payload
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            envelopeID: values.decode(NativeSourceOpaqueID.self, forKey: .envelopeID),
            protocolVersion: values.decode(String.self, forKey: .protocolVersion),
            kind: values.decode(NativeSourceKind.self, forKey: .kind),
            accountID: values.decode(NativeSourceOpaqueID.self, forKey: .accountID),
            bucketID: values.decode(NativeSourceOpaqueID.self, forKey: .bucketID),
            payload: values.decode([UInt8].self, forKey: .payload)
        )
    }
}

public struct ProtectedSpoolLimits: Hashable, Sendable {
    public let maximumItems: Int
    public let maximumBytes: Int64
    public let maximumPayloadBytes: Int
    public let maximumQuarantineItems: Int
    public let maximumQuarantineBytes: Int64

    public init(
        maximumItems: Int,
        maximumBytes: Int64,
        maximumPayloadBytes: Int,
        maximumQuarantineItems: Int? = nil,
        maximumQuarantineBytes: Int64? = nil
    ) throws {
        let quarantineItems = maximumQuarantineItems ?? maximumItems
        let quarantineBytes = maximumQuarantineBytes ?? maximumBytes
        guard maximumItems > 0, maximumBytes > 0, maximumPayloadBytes > 0,
              quarantineItems > 0, quarantineBytes > 0
        else {
            throw ProtectedSpoolError.invalidLimits
        }
        self.maximumItems = maximumItems
        self.maximumBytes = maximumBytes
        self.maximumPayloadBytes = maximumPayloadBytes
        self.maximumQuarantineItems = quarantineItems
        self.maximumQuarantineBytes = quarantineBytes
    }
}

public enum ProtectedSpoolState: String, Codable, Hashable, Sendable {
    case pending
    case quarantine
    case crashResidue = "crash_residue"
}

public struct ProtectedSpoolInventoryItem: Codable, Hashable, Sendable {
    public let envelopeID: NativeSourceOpaqueID
    public let state: ProtectedSpoolState
    public let byteCount: Int64
}

public struct ProtectedSpoolInventory: Codable, Hashable, Sendable {
    public let items: [ProtectedSpoolInventoryItem]
    public let totalBytes: Int64

    public var itemCount: Int { items.count }
}

public enum ProtectedSpoolEnqueueResult: Equatable, Sendable {
    case enqueued
    case alreadyPresent
}

public enum ProtectedSpoolFault: Sendable {
    case none
    case afterTemporarySync
    case afterEnqueueDestinationSync
    case afterQuarantineDestinationSync
    case afterRecoveryDestinationSync
    case whileExclusivelyLocked(@Sendable () throws -> Void)
}

public enum ProtectedSpoolError: Error, Equatable, Sendable {
    case invalidLimits
    case unsafeDirectory
    case pathCollision
    case itemCapacityExceeded
    case byteCapacityExceeded
    case quarantineItemCapacityExceeded
    case quarantineByteCapacityExceeded
    case payloadTooLarge
    case itemNotFound
    case itemAlreadyQuarantined
    case corruptItem
    case filesystemFailure(Int32)
    case injectedCrash
}

private struct ProtectedDirectoryIdentity: Hashable {
    let device: dev_t
    let inode: ino_t
    let owner: uid_t
    let mode: mode_t

    init(_ information: stat) {
        self.device = information.st_dev
        self.inode = information.st_ino
        self.owner = information.st_uid
        self.mode = information.st_mode
    }
}

private final class ProtectedSharedProcessLock: @unchecked Sendable {
    let descriptor: Int32
    let identity: ProtectedDirectoryIdentity
    /// `lockf` locks belong to a process rather than a thread. Same-process
    /// operations therefore need their own per-root mutex, separate from the
    /// registry mutex used by retain/release during peer deinitialization.
    let operationMutex = NSLock()
    var referenceCount: Int

    init(descriptor: Int32, identity: ProtectedDirectoryIdentity) {
        self.descriptor = descriptor
        self.identity = identity
        self.referenceCount = 1
    }
}

/// Owner-only, local, atomic and bounded handoff storage. Security-sensitive
/// operations are relative to pinned directory descriptors, never re-resolved
/// through mutable intermediate path components.
public final class ProtectedSpool: @unchecked Sendable {
    private static let processMutex = NSLock()
    private nonisolated(unsafe) static var sharedProcessLocks: [
        ProtectedDirectoryIdentity: ProtectedSharedProcessLock
    ] = [:]
    private let rootPath: String
    private let rootDescriptor: Int32
    private let sharedProcessLock: ProtectedSharedProcessLock
    private let pendingDescriptor: Int32
    private let quarantineDescriptor: Int32
    private let rootIdentity: ProtectedDirectoryIdentity
    private let pendingIdentity: ProtectedDirectoryIdentity
    private let quarantineIdentity: ProtectedDirectoryIdentity
    private let limits: ProtectedSpoolLimits
    private let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return encoder
    }()
    private let decoder = JSONDecoder()

    /// The bounds this spool refuses at. Exposed so a health report can state the
    /// headroom rather than an unanchored occupancy count.
    public var configuredLimits: ProtectedSpoolLimits { limits }

    public init(directory: URL, limits: ProtectedSpoolLimits) throws {
        let rootPath = directory.standardizedFileURL.path
        var rootDescriptor: Int32 = -1
        var sharedProcessLock: ProtectedSharedProcessLock?
        var rootIdentityForCleanup: ProtectedDirectoryIdentity?
        var pendingDescriptor: Int32 = -1
        var quarantineDescriptor: Int32 = -1
        do {
            let expectedRoot = try Self.ensureRootDirectory(rootPath)
            rootIdentityForCleanup = expectedRoot
            rootDescriptor = try Self.openDirectory(path: rootPath, expected: expectedRoot)
            let pending = try Self.ensureChildDirectory(parent: rootDescriptor, name: "pending")
            pendingDescriptor = pending.descriptor
            let quarantine = try Self.ensureChildDirectory(
                parent: rootDescriptor,
                name: "quarantine"
            )
            quarantineDescriptor = quarantine.descriptor
            let acquiredProcessLock = try Self.acquireSharedProcessLock(
                root: rootDescriptor,
                rootIdentity: expectedRoot
            )
            sharedProcessLock = acquiredProcessLock

            try Self.validateNamespace(
                rootPath: rootPath,
                rootDescriptor: rootDescriptor,
                rootIdentity: expectedRoot,
                sharedProcessLock: acquiredProcessLock,
                pendingDescriptor: pendingDescriptor,
                pendingIdentity: pending.identity,
                quarantineDescriptor: quarantineDescriptor,
                quarantineIdentity: quarantine.identity
            )

            self.rootPath = rootPath
            self.rootDescriptor = rootDescriptor
            self.sharedProcessLock = acquiredProcessLock
            self.pendingDescriptor = pendingDescriptor
            self.quarantineDescriptor = quarantineDescriptor
            self.rootIdentity = expectedRoot
            self.pendingIdentity = pending.identity
            self.quarantineIdentity = quarantine.identity
            self.limits = limits
        } catch {
            if let sharedProcessLock, let rootIdentityForCleanup {
                Self.releaseSharedProcessLock(
                    sharedProcessLock,
                    rootIdentity: rootIdentityForCleanup
                )
            }
            if quarantineDescriptor >= 0 { _ = Darwin.close(quarantineDescriptor) }
            if pendingDescriptor >= 0 { _ = Darwin.close(pendingDescriptor) }
            if rootDescriptor >= 0 { _ = Darwin.close(rootDescriptor) }
            throw error
        }
    }

    deinit {
        _ = Darwin.close(quarantineDescriptor)
        _ = Darwin.close(pendingDescriptor)
        _ = Darwin.close(rootDescriptor)
        Self.releaseSharedProcessLock(sharedProcessLock, rootIdentity: rootIdentity)
    }

    public func enqueue(
        _ item: NativeSpoolItem,
        fault: ProtectedSpoolFault = .none
    ) throws -> ProtectedSpoolEnqueueResult {
        try locked {
            try validateNamespace()
            if case let .whileExclusivelyLocked(operation) = fault {
                try operation()
            }
            guard item.payload.count <= limits.maximumPayloadBytes else {
                throw ProtectedSpoolError.payloadTooLarge
            }
            let bytes = try encoder.encode(item)
            let pendingName = item.envelopeID.rawValue + ".pending"
            let quarantineName = item.envelopeID.rawValue + ".quarantine"
            for (descriptor, name) in [
                (pendingDescriptor, pendingName),
                (quarantineDescriptor, quarantineName),
            ] where try entryExists(in: descriptor, name: name) {
                guard try safeBytes(in: descriptor, name: name) == bytes else {
                    throw ProtectedSpoolError.pathCollision
                }
                return .alreadyPresent
            }

            let current = try inventoryUnlocked()
            let active = current.items.filter { $0.state != .quarantine }
            guard active.count < limits.maximumItems else {
                throw ProtectedSpoolError.itemCapacityExceeded
            }
            let activeBytes = active.reduce(0, { $0 + $1.byteCount })
            guard activeBytes <= limits.maximumBytes - Int64(bytes.count) else {
                throw ProtectedSpoolError.byteCapacityExceeded
            }

            let temporaryName = item.envelopeID.rawValue + ".tmp"
            let descriptor = Darwin.openat(
                rootDescriptor,
                temporaryName,
                O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW,
                S_IRUSR | S_IWUSR
            )
            guard descriptor >= 0 else {
                throw ProtectedSpoolError.filesystemFailure(errno)
            }
            var closed = false
            do {
                try appendAll(bytes, to: descriptor)
                guard Darwin.fsync(descriptor) == 0 else {
                    throw ProtectedSpoolError.filesystemFailure(errno)
                }
                guard Darwin.close(descriptor) == 0 else {
                    throw ProtectedSpoolError.filesystemFailure(errno)
                }
                closed = true
                if case .afterTemporarySync = fault {
                    throw ProtectedSpoolError.injectedCrash
                }
                try syncDirectory(rootDescriptor)
                guard renameatx_np(
                    rootDescriptor,
                    temporaryName,
                    pendingDescriptor,
                    pendingName,
                    UInt32(RENAME_EXCL)
                ) == 0 else {
                    throw ProtectedSpoolError.filesystemFailure(errno)
                }
                try syncDirectory(pendingDescriptor)
                if case .afterEnqueueDestinationSync = fault {
                    throw ProtectedSpoolError.injectedCrash
                }
                try syncDirectory(rootDescriptor)
                return .enqueued
            } catch {
                if !closed { _ = Darwin.close(descriptor) }
                throw error
            }
        }
    }

    public func inventory() throws -> ProtectedSpoolInventory {
        try locked {
            try validateNamespace()
            return try inventoryUnlocked()
        }
    }

    public func item(_ envelopeID: NativeSourceOpaqueID) throws -> NativeSpoolItem {
        try locked {
            try validateNamespace()
            return try decodeItem(
                in: pendingDescriptor,
                name: envelopeID.rawValue + ".pending"
            )
        }
    }

    public func acknowledge(_ envelopeID: NativeSourceOpaqueID) throws {
        try locked {
            try validateNamespace()
            let name = envelopeID.rawValue + ".pending"
            _ = try safeBytes(in: pendingDescriptor, name: name)
            guard Darwin.unlinkat(pendingDescriptor, name, 0) == 0 else {
                throw errno == ENOENT ? ProtectedSpoolError.itemNotFound
                    : ProtectedSpoolError.filesystemFailure(errno)
            }
            try syncDirectory(pendingDescriptor)
        }
    }

    public func quarantine(
        _ envelopeID: NativeSourceOpaqueID,
        fault: ProtectedSpoolFault = .none
    ) throws {
        try locked {
            try validateNamespace()
            let source = envelopeID.rawValue + ".pending"
            let destination = envelopeID.rawValue + ".quarantine"
            guard try entryExists(in: pendingDescriptor, name: source) else {
                if try entryExists(in: quarantineDescriptor, name: destination) {
                    throw ProtectedSpoolError.itemAlreadyQuarantined
                }
                throw ProtectedSpoolError.itemNotFound
            }
            let sourceBytes = try safeBytes(in: pendingDescriptor, name: source)
            let current = try inventoryUnlocked()
            let quarantine = current.items.filter { $0.state == .quarantine }
            guard quarantine.count < limits.maximumQuarantineItems else {
                throw ProtectedSpoolError.quarantineItemCapacityExceeded
            }
            let quarantineBytes = quarantine.reduce(0, { $0 + $1.byteCount })
            guard quarantineBytes <= limits.maximumQuarantineBytes - Int64(sourceBytes.count)
            else {
                throw ProtectedSpoolError.quarantineByteCapacityExceeded
            }
            try syncDirectory(pendingDescriptor)
            guard renameatx_np(
                pendingDescriptor,
                source,
                quarantineDescriptor,
                destination,
                UInt32(RENAME_EXCL)
            ) == 0 else {
                throw ProtectedSpoolError.filesystemFailure(errno)
            }
            try syncDirectory(quarantineDescriptor)
            if case .afterQuarantineDestinationSync = fault {
                throw ProtectedSpoolError.injectedCrash
            }
            try syncDirectory(pendingDescriptor)
        }
    }

    /// Moves complete or partial synchronized temporary files into retained
    /// quarantine. Recovery never admits or removes a crash residue.
    public func recoverResidues(
        fault: ProtectedSpoolFault = .none
    ) throws -> ProtectedSpoolInventory {
        try locked {
            try validateNamespace()
            let names = try directoryNames(rootDescriptor)
                .filter { $0.hasSuffix(".tmp") }
                .sorted()
            let current = try inventoryUnlocked()
            let quarantine = current.items.filter { $0.state == .quarantine }
            var projectedQuarantineCount = quarantine.count
            var projectedQuarantineBytes = quarantine.reduce(0, { $0 + $1.byteCount })
            var recovery: [(source: String, destination: String)] = []
            for source in names {
                let stem = String(source.dropLast(".tmp".count))
                guard let envelopeID = NativeSourceOpaqueID(rawValue: stem) else {
                    throw ProtectedSpoolError.corruptItem
                }
                let destination = envelopeID.rawValue + ".quarantine"
                guard try !entryExists(in: quarantineDescriptor, name: destination) else {
                    throw ProtectedSpoolError.pathCollision
                }
                let sourceBytes = try safeBytes(in: rootDescriptor, name: source)
                projectedQuarantineCount += 1
                guard projectedQuarantineCount <= limits.maximumQuarantineItems else {
                    throw ProtectedSpoolError.quarantineItemCapacityExceeded
                }
                projectedQuarantineBytes += Int64(sourceBytes.count)
                guard projectedQuarantineBytes <= limits.maximumQuarantineBytes else {
                    throw ProtectedSpoolError.quarantineByteCapacityExceeded
                }
                recovery.append((source: source, destination: destination))
            }
            for candidate in recovery {
                // The injected-crash path fsyncs file bytes but deliberately
                // does not sync this directory entry. Establish the recoverable
                // source name before replacing it across directories.
                try syncDirectory(rootDescriptor)
                guard renameatx_np(
                    rootDescriptor,
                    candidate.source,
                    quarantineDescriptor,
                    candidate.destination,
                    UInt32(RENAME_EXCL)
                ) == 0 else {
                    throw ProtectedSpoolError.filesystemFailure(errno)
                }
                // Establish the evidence-bearing destination before committing
                // removal of the already-durable source name. A crash or error
                // between these syncs can duplicate a name, but cannot lose the
                // only durable name.
                try syncDirectory(quarantineDescriptor)
                if case .afterRecoveryDestinationSync = fault {
                    throw ProtectedSpoolError.injectedCrash
                }
                try syncDirectory(rootDescriptor)
            }
            return try inventoryUnlocked()
        }
    }

    private func inventoryUnlocked() throws -> ProtectedSpoolInventory {
        var entries: [ProtectedSpoolInventoryItem] = []
        try collect(
            from: pendingDescriptor,
            suffix: ".pending",
            state: .pending,
            into: &entries
        )
        try collect(
            from: quarantineDescriptor,
            suffix: ".quarantine",
            state: .quarantine,
            into: &entries
        )
        try collect(
            from: rootDescriptor,
            suffix: ".tmp",
            state: .crashResidue,
            into: &entries
        )
        entries.sort {
            ($0.envelopeID.rawValue, $0.state.rawValue)
                < ($1.envelopeID.rawValue, $1.state.rawValue)
        }
        return ProtectedSpoolInventory(
            items: entries,
            totalBytes: entries.reduce(0, { $0 + $1.byteCount })
        )
    }

    private func collect(
        from descriptor: Int32,
        suffix: String,
        state: ProtectedSpoolState,
        into entries: inout [ProtectedSpoolInventoryItem]
    ) throws {
        for name in try directoryNames(descriptor).filter({ $0.hasSuffix(suffix) }) {
            let identity = String(name.dropLast(suffix.count))
            guard let envelopeID = NativeSourceOpaqueID(rawValue: identity) else {
                throw ProtectedSpoolError.corruptItem
            }
            let information = try regularFileInformation(in: descriptor, name: name)
            entries.append(
                ProtectedSpoolInventoryItem(
                    envelopeID: envelopeID,
                    state: state,
                    byteCount: information.st_size
                )
            )
        }
    }

    private func decodeItem(in descriptor: Int32, name: String) throws -> NativeSpoolItem {
        do {
            return try decoder.decode(
                NativeSpoolItem.self,
                from: safeBytes(in: descriptor, name: name)
            )
        } catch let error as ProtectedSpoolError {
            throw error
        } catch {
            throw ProtectedSpoolError.corruptItem
        }
    }

    private func safeBytes(in directory: Int32, name: String) throws -> Data {
        let descriptor = Darwin.openat(directory, name, O_RDONLY | O_NOFOLLOW)
        guard descriptor >= 0 else {
            throw errno == ENOENT ? ProtectedSpoolError.itemNotFound
                : ProtectedSpoolError.filesystemFailure(errno)
        }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        var information = stat()
        guard fstat(descriptor, &information) == 0 else {
            throw ProtectedSpoolError.filesystemFailure(errno)
        }
        try Self.requireSafeRegularFile(information)
        return handle.readDataToEndOfFile()
    }

    private func regularFileInformation(in directory: Int32, name: String) throws -> stat {
        var information = stat()
        guard fstatat(directory, name, &information, AT_SYMLINK_NOFOLLOW) == 0 else {
            throw errno == ENOENT ? ProtectedSpoolError.itemNotFound
                : ProtectedSpoolError.filesystemFailure(errno)
        }
        try Self.requireSafeRegularFile(information)
        return information
    }

    private func entryExists(in directory: Int32, name: String) throws -> Bool {
        var information = stat()
        if fstatat(directory, name, &information, AT_SYMLINK_NOFOLLOW) == 0 { return true }
        if errno == ENOENT { return false }
        throw ProtectedSpoolError.filesystemFailure(errno)
    }

    private func directoryNames(_ descriptor: Int32) throws -> [String] {
        let duplicate = Darwin.openat(descriptor, ".", O_RDONLY | O_DIRECTORY | O_NOFOLLOW)
        guard duplicate >= 0 else {
            throw ProtectedSpoolError.filesystemFailure(errno)
        }
        guard let directory = fdopendir(duplicate) else {
            _ = Darwin.close(duplicate)
            throw ProtectedSpoolError.filesystemFailure(errno)
        }
        defer { closedir(directory) }
        var names: [String] = []
        errno = 0
        while let entry = readdir(directory) {
            var buffer = entry.pointee.d_name
            let capacity = MemoryLayout.size(ofValue: buffer)
            let name = withUnsafePointer(to: &buffer) { pointer in
                pointer.withMemoryRebound(to: CChar.self, capacity: capacity) {
                    String(cString: $0)
                }
            }
            if name != "." && name != ".." { names.append(name) }
        }
        guard errno == 0 else {
            throw ProtectedSpoolError.filesystemFailure(errno)
        }
        return names
    }

    private func locked<T>(_ operation: () throws -> T) throws -> T {
        sharedProcessLock.operationMutex.lock()
        defer { sharedProcessLock.operationMutex.unlock() }
        while Darwin.lockf(sharedProcessLock.descriptor, F_LOCK, 0) != 0 {
            if errno == EINTR { continue }
            throw ProtectedSpoolError.filesystemFailure(errno)
        }
        defer { _ = Darwin.lockf(sharedProcessLock.descriptor, F_ULOCK, 0) }
        return try operation()
    }

    private func validateNamespace() throws {
        try Self.validateNamespace(
            rootPath: rootPath,
            rootDescriptor: rootDescriptor,
            rootIdentity: rootIdentity,
            sharedProcessLock: sharedProcessLock,
            pendingDescriptor: pendingDescriptor,
            pendingIdentity: pendingIdentity,
            quarantineDescriptor: quarantineDescriptor,
            quarantineIdentity: quarantineIdentity
        )
    }

    private static func validateNamespace(
        rootPath: String,
        rootDescriptor: Int32,
        rootIdentity: ProtectedDirectoryIdentity,
        sharedProcessLock: ProtectedSharedProcessLock,
        pendingDescriptor: Int32,
        pendingIdentity: ProtectedDirectoryIdentity,
        quarantineDescriptor: Int32,
        quarantineIdentity: ProtectedDirectoryIdentity
    ) throws {
        var rootPathInformation = stat()
        guard lstat(rootPath, &rootPathInformation) == 0,
              ProtectedDirectoryIdentity(rootPathInformation) == rootIdentity
        else {
            throw ProtectedSpoolError.unsafeDirectory
        }
        try validateDescriptor(rootDescriptor, expected: rootIdentity)
        try validateChild(
            ".spool.lock",
            rootDescriptor: rootDescriptor,
            expected: sharedProcessLock.identity
        )
        try validateDescriptor(sharedProcessLock.descriptor, expected: sharedProcessLock.identity)
        try validateChild("pending", rootDescriptor: rootDescriptor, expected: pendingIdentity)
        try validateChild("quarantine", rootDescriptor: rootDescriptor, expected: quarantineIdentity)
        try validateDescriptor(pendingDescriptor, expected: pendingIdentity)
        try validateDescriptor(quarantineDescriptor, expected: quarantineIdentity)
    }

    private static func validateChild(
        _ name: String,
        rootDescriptor: Int32,
        expected: ProtectedDirectoryIdentity
    ) throws {
        var information = stat()
        guard fstatat(rootDescriptor, name, &information, AT_SYMLINK_NOFOLLOW) == 0,
              ProtectedDirectoryIdentity(information) == expected
        else {
            throw ProtectedSpoolError.unsafeDirectory
        }
    }

    private static func validateDescriptor(
        _ descriptor: Int32,
        expected: ProtectedDirectoryIdentity
    ) throws {
        var information = stat()
        guard fstat(descriptor, &information) == 0,
              ProtectedDirectoryIdentity(information) == expected
        else {
            throw ProtectedSpoolError.unsafeDirectory
        }
    }

    private static func ensureRootDirectory(_ path: String) throws -> ProtectedDirectoryIdentity {
        var information = stat()
        if lstat(path, &information) != 0 {
            guard errno == ENOENT else {
                throw ProtectedSpoolError.filesystemFailure(errno)
            }
            do {
                try FileManager.default.createDirectory(
                    atPath: path,
                    withIntermediateDirectories: false,
                    attributes: [.posixPermissions: 0o700]
                )
            } catch {
                throw ProtectedSpoolError.filesystemFailure(EIO)
            }
            guard lstat(path, &information) == 0 else {
                throw ProtectedSpoolError.filesystemFailure(errno)
            }
        }
        try requireSafeDirectory(information)
        return ProtectedDirectoryIdentity(information)
    }

    private static func openDirectory(
        path: String,
        expected: ProtectedDirectoryIdentity
    ) throws -> Int32 {
        let descriptor = Darwin.open(path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW)
        guard descriptor >= 0 else {
            throw ProtectedSpoolError.filesystemFailure(errno)
        }
        do {
            var information = stat()
            guard fstat(descriptor, &information) == 0,
                  ProtectedDirectoryIdentity(information) == expected
            else {
                throw ProtectedSpoolError.unsafeDirectory
            }
            return descriptor
        } catch {
            _ = Darwin.close(descriptor)
            throw error
        }
    }

    private static func ensureChildDirectory(
        parent: Int32,
        name: String
    ) throws -> (descriptor: Int32, identity: ProtectedDirectoryIdentity) {
        var information = stat()
        if fstatat(parent, name, &information, AT_SYMLINK_NOFOLLOW) != 0 {
            guard errno == ENOENT else {
                throw ProtectedSpoolError.filesystemFailure(errno)
            }
            guard mkdirat(parent, name, S_IRWXU) == 0 else {
                throw ProtectedSpoolError.filesystemFailure(errno)
            }
            guard fstatat(parent, name, &information, AT_SYMLINK_NOFOLLOW) == 0 else {
                throw ProtectedSpoolError.filesystemFailure(errno)
            }
        }
        try requireSafeDirectory(information)
        let expected = ProtectedDirectoryIdentity(information)
        let descriptor = Darwin.openat(parent, name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW)
        guard descriptor >= 0 else {
            throw ProtectedSpoolError.filesystemFailure(errno)
        }
        do {
            var opened = stat()
            guard fstat(descriptor, &opened) == 0,
                  ProtectedDirectoryIdentity(opened) == expected
            else {
                throw ProtectedSpoolError.unsafeDirectory
            }
            return (descriptor, expected)
        } catch {
            _ = Darwin.close(descriptor)
            throw error
        }
    }

    private static func ensureLockFile(
        parent: Int32
    ) throws -> (descriptor: Int32, identity: ProtectedDirectoryIdentity) {
        let descriptor = Darwin.openat(
            parent,
            ".spool.lock",
            O_RDWR | O_CREAT | O_NOFOLLOW,
            S_IRUSR | S_IWUSR
        )
        guard descriptor >= 0 else {
            throw ProtectedSpoolError.filesystemFailure(errno)
        }
        do {
            var information = stat()
            guard fstat(descriptor, &information) == 0 else {
                throw ProtectedSpoolError.filesystemFailure(errno)
            }
            try requireSafeRegularFile(information)
            return (descriptor, ProtectedDirectoryIdentity(information))
        } catch {
            _ = Darwin.close(descriptor)
            throw error
        }
    }

    private static func acquireSharedProcessLock(
        root: Int32,
        rootIdentity: ProtectedDirectoryIdentity
    ) throws -> ProtectedSharedProcessLock {
        processMutex.lock()
        defer { processMutex.unlock() }
        if let shared = sharedProcessLocks[rootIdentity] {
            var visible = stat()
            var opened = stat()
            guard fstatat(root, ".spool.lock", &visible, AT_SYMLINK_NOFOLLOW) == 0,
                  ProtectedDirectoryIdentity(visible) == shared.identity,
                  fstat(shared.descriptor, &opened) == 0,
                  ProtectedDirectoryIdentity(opened) == shared.identity
            else {
                throw ProtectedSpoolError.unsafeDirectory
            }
            shared.referenceCount += 1
            return shared
        }
        let opened = try ensureLockFile(parent: root)
        let shared = ProtectedSharedProcessLock(
            descriptor: opened.descriptor,
            identity: opened.identity
        )
        sharedProcessLocks[rootIdentity] = shared
        return shared
    }

    private static func releaseSharedProcessLock(
        _ shared: ProtectedSharedProcessLock,
        rootIdentity: ProtectedDirectoryIdentity
    ) {
        processMutex.lock()
        defer { processMutex.unlock() }
        guard let registered = sharedProcessLocks[rootIdentity], registered === shared else {
            return
        }
        registered.referenceCount -= 1
        if registered.referenceCount == 0 {
            sharedProcessLocks.removeValue(forKey: rootIdentity)
            _ = Darwin.close(registered.descriptor)
        }
    }

    private static func requireSafeDirectory(_ information: stat) throws {
        guard (information.st_mode & S_IFMT) == S_IFDIR,
              information.st_uid == getuid(),
              information.st_mode & (S_IRWXG | S_IRWXO) == 0,
              information.st_mode & (S_IRUSR | S_IWUSR | S_IXUSR)
                == (S_IRUSR | S_IWUSR | S_IXUSR)
        else {
            throw ProtectedSpoolError.unsafeDirectory
        }
    }

    private static func requireSafeRegularFile(_ information: stat) throws {
        guard (information.st_mode & S_IFMT) == S_IFREG,
              information.st_uid == getuid(),
              information.st_mode & (S_IRWXG | S_IRWXO) == 0,
              information.st_mode & (S_IRUSR | S_IWUSR) == (S_IRUSR | S_IWUSR)
        else {
            throw ProtectedSpoolError.unsafeDirectory
        }
    }

    private func appendAll(_ data: Data, to descriptor: Int32) throws {
        try data.withUnsafeBytes { rawBuffer in
            guard let base = rawBuffer.baseAddress else { return }
            var offset = 0
            while offset < rawBuffer.count {
                let count = Darwin.write(
                    descriptor,
                    base.advanced(by: offset),
                    rawBuffer.count - offset
                )
                if count < 0 {
                    if errno == EINTR { continue }
                    throw ProtectedSpoolError.filesystemFailure(errno)
                }
                guard count > 0 else {
                    throw ProtectedSpoolError.filesystemFailure(EIO)
                }
                offset += count
            }
        }
    }

    private func syncDirectory(_ descriptor: Int32) throws {
        guard Darwin.fsync(descriptor) == 0 else {
            throw ProtectedSpoolError.filesystemFailure(errno)
        }
    }
}
