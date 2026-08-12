import AppleSourceHostPlatform
import Darwin
import Foundation

private let maximumInputBytes = 1_048_576

private enum HostError: Error {
    case usage
    case inputNotBounded
}

private func readBounded<T: Decodable>(_ path: String, as type: T.Type) throws -> T {
    let url = URL(fileURLWithPath: path)
    let values = try url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
    guard values.isRegularFile == true,
          values.isSymbolicLink != true,
          let size = values.fileSize,
          0 < size, size <= maximumInputBytes
    else { throw HostError.inputNotBounded }
    return try JSONDecoder().decode(T.self, from: Data(contentsOf: url))
}

private func run(_ arguments: [String]) throws {
    guard arguments.count >= 4,
          arguments[1] == "validate",
          arguments[2] == "--configuration"
    else { throw HostError.usage }
    let configuration = try readBounded(
        arguments[3], as: PlatformAppleSourceConfiguration.self
    )
    var checkpoints: [PlatformSourceCheckpoint] = []
    var offset = 4
    while offset < arguments.count {
        guard offset + 1 < arguments.count, arguments[offset] == "--checkpoint" else {
            throw HostError.usage
        }
        checkpoints.append(
            try readBounded(arguments[offset + 1], as: PlatformSourceCheckpoint.self)
        )
        offset += 2
    }
    let summary = try PlatformHostAdmission.validate(
        configuration: configuration,
        checkpoints: checkpoints
    )
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
