import AppleSourceHost
import AppleSourceHostPlatform
import Contacts
import Darwin
import EventKit
import Foundation

private let maximumInputFileBytes = 262_144
private let maximumAggregateInputBytes = 1_048_576
private let maximumConfiguredSpoolItems = 4_096
private let maximumConfiguredSpoolBytes: Int64 = 67_108_864
private let maximumConfiguredPayloadBytes = 1_048_576

private enum HostError: Error {
    case usage
    case inputNotBounded
}

private func composition(
    _ configuration: PlatformAppleSourceConfiguration
) throws -> PlatformAppleSourceComposition {
    try PlatformAppleSourceComposition(
        eventStore: EKEventStore(),
        contactStore: CNContactStore(),
        contactsIdentityEpoch: configuration.contactsIdentityEpoch,
        mailGeneration: configuration.mailGeneration
    )
}

private func runProbe(_ arguments: [String]) throws -> Bool {
    guard arguments.count >= 8, arguments[1] == "probe",
          arguments[2] == "--preflight" || arguments[2] == "--discover"
    else { return false }
    let preflight = arguments[2] == "--preflight"
    var configurationPath: String?
    var bridgeID: NativeSourceOpaqueID?
    var requestID: NativeSourceOpaqueID?
    var kind: NativeSourceKind?
    var offset = 3
    while offset < arguments.count {
        guard offset + 1 < arguments.count else { throw HostError.usage }
        switch arguments[offset] {
        case "--configuration" where configurationPath == nil:
            configurationPath = arguments[offset + 1]
        case "--bridge-id" where bridgeID == nil:
            bridgeID = NativeSourceOpaqueID(rawValue: arguments[offset + 1])
        case "--request-id" where requestID == nil:
            requestID = NativeSourceOpaqueID(rawValue: arguments[offset + 1])
        case "--kind" where kind == nil:
            kind = NativeSourceKind(rawValue: arguments[offset + 1])
        default: throw HostError.usage
        }
        offset += 2
    }
    guard let configurationPath, let bridgeID, let requestID,
          preflight == (kind == nil)
    else { throw HostError.usage }
    var remainingAggregateBytes = maximumAggregateInputBytes
    let configuration = try readBounded(
        configurationPath,
        as: PlatformAppleSourceConfiguration.self,
        remainingAggregateBytes: &remainingAggregateBytes
    )
    _ = try PlatformHostAdmission.validate(configuration: configuration, checkpoints: [])
    let platform = try composition(configuration)
    let now = Int64(Date().timeIntervalSince1970 * 1_000)
    let metadata = try NativeEnvelopeMetadata(
        envelopeID: requestID,
        hostInstanceID: bridgeID,
        emittedAtUnixMilliseconds: now
    )
    let output: Data
    if preflight {
        let selections = configuration.selections.sorted {
            ($0.kind.rawValue, $0.accountID.rawValue, $0.bucketID.rawValue) <
                ($1.kind.rawValue, $1.accountID.rawValue, $1.bucketID.rawValue)
        }.map {
            NativeBucketSelection(kind: $0.kind, accountID: $0.accountID, bucketID: $0.bucketID)
        }
        let request = try NativePreflightRequest(requestID: requestID, selections: selections)
        output = try JSONEncoder().encode(
            NativePreflightEnvelope(
                metadata: metadata,
                request: request,
                results: try platform.preflight(selections)
            )
        )
    } else {
        output = try JSONEncoder().encode(
            NativeDiscoveryEnvelope(metadata: metadata, snapshot: try platform.discover(kind!))
        )
    }
    guard output.count <= maximumInputFileBytes else { throw HostError.inputNotBounded }
    FileHandle.standardOutput.write(output)
    FileHandle.standardOutput.write(Data([0x0a]))
    return true
}

private func runSpoolCommand(_ arguments: [String]) throws -> Bool {
    guard arguments.count >= 7, arguments[1] == "spool",
          arguments[2] == "--acknowledge"
    else { return false }
    var spoolPath: String?
    var envelopeID: NativeSourceOpaqueID?
    var maximumSpoolItems: Int?
    var maximumSpoolBytes: Int64?
    var maximumPayloadBytes: Int?
    var offset = 3
    while offset < arguments.count {
        guard offset + 1 < arguments.count else { throw HostError.usage }
        switch arguments[offset] {
        case "--spool-directory" where spoolPath == nil:
            spoolPath = arguments[offset + 1]
        case "--envelope-id" where envelopeID == nil:
            envelopeID = NativeSourceOpaqueID(rawValue: arguments[offset + 1])
        case "--maximum-spool-items" where maximumSpoolItems == nil:
            maximumSpoolItems = Int(arguments[offset + 1])
        case "--maximum-spool-bytes" where maximumSpoolBytes == nil:
            maximumSpoolBytes = Int64(arguments[offset + 1])
        case "--maximum-payload-bytes" where maximumPayloadBytes == nil:
            maximumPayloadBytes = Int(arguments[offset + 1])
        default: throw HostError.usage
        }
        offset += 2
    }
    guard let spoolPath, spoolPath.hasPrefix("/"), let envelopeID,
          let maximumSpoolItems,
          1...maximumConfiguredSpoolItems ~= maximumSpoolItems,
          let maximumSpoolBytes,
          1...maximumConfiguredSpoolBytes ~= maximumSpoolBytes,
          let maximumPayloadBytes,
          1...maximumConfiguredPayloadBytes ~= maximumPayloadBytes
    else { throw HostError.inputNotBounded }
    let spool = try ProtectedSpool(
        directory: URL(fileURLWithPath: spoolPath, isDirectory: true),
        limits: try ProtectedSpoolLimits(
            maximumItems: maximumSpoolItems,
            maximumBytes: maximumSpoolBytes,
            maximumPayloadBytes: maximumPayloadBytes
        )
    )
    try spool.acknowledge(envelopeID)
    FileHandle.standardOutput.write(Data("{\"state\":\"acknowledged\"}\n".utf8))
    return true
}

private func readBounded<T: Decodable>(
    _ path: String,
    as type: T.Type,
    remainingAggregateBytes: inout Int
) throws -> T {
    let components = path.split(separator: "/", omittingEmptySubsequences: true).map(String.init)
    guard path.hasPrefix("/"), !components.isEmpty,
          !components.contains(where: { $0 == "." || $0 == ".." })
    else { throw HostError.inputNotBounded }
    var parent = Darwin.open("/", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
    guard parent >= 0 else { throw HostError.inputNotBounded }
    defer { _ = Darwin.close(parent) }
    for component in components.dropLast() {
        let child = Darwin.openat(
            parent, component, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC
        )
        guard child >= 0 else { throw HostError.inputNotBounded }
        _ = Darwin.close(parent)
        parent = child
    }
    let descriptor = Darwin.openat(
        parent, components.last!, O_RDONLY | O_NONBLOCK | O_NOFOLLOW | O_CLOEXEC
    )
    guard descriptor >= 0 else { throw HostError.inputNotBounded }
    defer { _ = Darwin.close(descriptor) }
    var information = stat()
    guard fstat(descriptor, &information) == 0,
          information.st_mode & S_IFMT == S_IFREG,
          information.st_size > 0,
          information.st_size <= maximumInputFileBytes,
          information.st_size <= remainingAggregateBytes
    else { throw HostError.inputNotBounded }
    let initialDevice = information.st_dev
    let initialInode = information.st_ino
    let initialSize = information.st_size
    var bytes: [UInt8] = []
    bytes.reserveCapacity(Int(information.st_size))
    var buffer = [UInt8](repeating: 0, count: 65_536)
    let readCeiling = min(maximumInputFileBytes, remainingAggregateBytes)
    while bytes.count <= readCeiling {
        let count = Darwin.read(
            descriptor,
            &buffer,
            min(buffer.count, readCeiling + 1 - bytes.count)
        )
        guard count >= 0 else {
            if errno == EINTR { continue }
            throw HostError.inputNotBounded
        }
        if count == 0 { break }
        bytes.append(contentsOf: buffer.prefix(Int(count)))
    }
    var finalInformation = stat()
    guard !bytes.isEmpty,
          bytes.count <= readCeiling,
          fstat(descriptor, &finalInformation) == 0,
          finalInformation.st_dev == initialDevice,
          finalInformation.st_ino == initialInode,
          finalInformation.st_size == initialSize,
          bytes.count == Int(initialSize)
    else {
        throw HostError.inputNotBounded
    }
    remainingAggregateBytes -= bytes.count
    return try JSONDecoder().decode(T.self, from: Data(bytes))
}

private func run(_ arguments: [String]) throws {
    if try runProbe(arguments) { return }
    if try runSpoolCommand(arguments) { return }
    guard arguments.count >= 13,
          arguments[1] == "handoff",
          arguments[2] == "--dry-run" || arguments[2] == "--authorized-single-pass"
    else { throw HostError.usage }
    let authorizedRead = arguments[2] == "--authorized-single-pass"
    var configurationPath: String?
    var spoolPath: String?
    var maximumSpoolItems: Int?
    var maximumSpoolBytes: Int64?
    var maximumPayloadBytes: Int?
    var authorizationGrantPath: String?
    var checkpointPaths: [String] = []
    var offset = 3
    while offset < arguments.count {
        guard offset + 1 < arguments.count else { throw HostError.usage }
        let option = arguments[offset]
        let value = arguments[offset + 1]
        switch option {
        case "--configuration" where configurationPath == nil:
            configurationPath = value
        case "--spool-directory" where spoolPath == nil:
            spoolPath = value
        case "--maximum-spool-items" where maximumSpoolItems == nil:
            maximumSpoolItems = Int(value)
        case "--maximum-spool-bytes" where maximumSpoolBytes == nil:
            maximumSpoolBytes = Int64(value)
        case "--maximum-payload-bytes" where maximumPayloadBytes == nil:
            maximumPayloadBytes = Int(value)
        case "--authorization-grant" where authorizationGrantPath == nil:
            authorizationGrantPath = value
        case "--checkpoint":
            guard checkpointPaths.count < PlatformHostAdmission.maximumCheckpoints else {
                throw HostError.inputNotBounded
            }
            checkpointPaths.append(value)
        default:
            throw HostError.usage
        }
        offset += 2
    }
    guard let configurationPath,
          let spoolPath,
          spoolPath.hasPrefix("/"),
          let maximumSpoolItems,
          1...maximumConfiguredSpoolItems ~= maximumSpoolItems,
          let maximumSpoolBytes,
          1...maximumConfiguredSpoolBytes ~= maximumSpoolBytes,
          let maximumPayloadBytes,
          1...maximumConfiguredPayloadBytes ~= maximumPayloadBytes,
          authorizedRead == (authorizationGrantPath != nil)
    else { throw HostError.inputNotBounded }
    var remainingAggregateBytes = maximumAggregateInputBytes
    let configuration = try readBounded(
        configurationPath,
        as: PlatformAppleSourceConfiguration.self,
        remainingAggregateBytes: &remainingAggregateBytes
    )
    var checkpoints: [PlatformSourceCheckpoint] = []
    for checkpointPath in checkpointPaths {
        checkpoints.append(
            try readBounded(
                checkpointPath,
                as: PlatformSourceCheckpoint.self,
                remainingAggregateBytes: &remainingAggregateBytes
            )
        )
    }
    let composition = try composition(configuration)
    let spool = try ProtectedSpool(
        directory: URL(fileURLWithPath: spoolPath, isDirectory: true),
        limits: try ProtectedSpoolLimits(
            maximumItems: maximumSpoolItems,
            maximumBytes: maximumSpoolBytes,
            maximumPayloadBytes: maximumPayloadBytes
        )
    )
    let summary: PlatformHostAdmissionSummary
    if let authorizationGrantPath {
        let grant = try readBounded(
            authorizationGrantPath,
            as: PlatformAuthorizedReadGrant.self,
            remainingAggregateBytes: &remainingAggregateBytes
        )
        summary = try PlatformHostAdmission.authorizedSinglePassHandoff(
            configuration: configuration,
            checkpoints: checkpoints,
            grant: grant,
            nowUnixMilliseconds: Int64(Date().timeIntervalSince1970 * 1_000),
            composition: composition,
            spool: spool
        )
    } else {
        summary = try PlatformHostAdmission.protectedNonLiveHandoff(
            configuration: configuration,
            checkpoints: checkpoints,
            composition: composition,
            spool: spool
        )
    }
    FileHandle.standardOutput.write(try JSONEncoder().encode(summary))
    FileHandle.standardOutput.write(Data([0x0a]))
}

do {
    try run(CommandLine.arguments)
} catch {
    // Content-free failure: configuration/checkpoint paths and decoded values
    // may identify a user's local source layout and are never echoed.
    FileHandle.standardError.write(Data("apple source host admission refused\n".utf8))
    Darwin.exit(2)
}
