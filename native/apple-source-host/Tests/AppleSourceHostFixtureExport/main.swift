import AppleSourceHost
import Foundation

private struct Export: Encodable {
    let agreement: NativeProtocolAgreement
    let discovery: NativeDiscoveryEnvelope
    let preflight: NativePreflightEnvelope
    let admission: NativeAdmissionEnvelope
}

private func opaque(_ value: String) throws -> NativeSourceOpaqueID {
    guard let result = NativeSourceOpaqueID(rawValue: value) else {
        throw NativeSourceContractError.inconsistentEnvelope
    }
    return result
}

private func fixture(
    kind: NativeSourceKind,
    account: String,
    bucket: String,
    record: String
) throws -> (NativeDiscoverySnapshot, SyntheticPageFixture) {
    let accountID = try opaque(account)
    let bucketID = try opaque(bucket)
    let snapshot = try NativeDiscoverySnapshot(
        kind: kind,
        accounts: [NativeSourceAccount(id: accountID, kind: kind, displayLabel: "Synthetic Account")],
        buckets: [NativeSourceBucket(
            id: bucketID,
            accountID: accountID,
            kind: kind,
            displayLabel: "Synthetic Bucket",
            isSelectable: true
        )]
    )
    let source = NativeSourceRecord(
        id: try opaque(record),
        bucketID: bucketID,
        kind: kind,
        sourceRevision: "synthetic-revision-1",
        sourceModifiedUnixMilliseconds: 1_775_563_200_000,
        payload: Array("synthetic-evidence".utf8)
    )
    return (
        snapshot,
        SyntheticPageFixture(
            bucketID: bucketID,
            requestCursor: nil,
            page: NativeReadPage(records: [source], nextCursor: nil)
        )
    )
}

@main
struct AppleSourceHostFixtureExport {
    static func main() throws {
        let hostID = try opaque("nbrg_0000000000000001")
        let mail = try fixture(kind: .mail, account: "account.a", bucket: "bucket.a", record: "mail.record.1")
        let calendar = try fixture(
            kind: .calendar,
            account: "calendar.account",
            bucket: "calendar.bucket",
            record: "calendar.record.1"
        )
        let contacts = try fixture(
            kind: .contacts,
            account: "contacts.account",
            bucket: "contacts.bucket",
            record: "contacts.record.1"
        )
        let selection = NativeBucketSelection(
            kind: .mail,
            accountID: mail.0.accounts[0].id,
            bucketID: mail.0.buckets[0].id
        )
        let host = try SyntheticNativeHost(
            hostInstanceID: hostID,
            mail: SyntheticMailReadAdapter(snapshot: mail.0, pages: [mail.1]),
            calendar: SyntheticCalendarReadAdapter(snapshot: calendar.0, pages: [calendar.1]),
            contacts: SyntheticContactsReadAdapter(snapshot: contacts.0, pages: [contacts.1]),
            preflightFixtures: [try SyntheticPreflightFixture(selection: selection, state: .reachable)]
        )
        let discovery = try host.discover(
            .mail,
            metadata: NativeEnvelopeMetadata(
                envelopeID: try opaque("discovery.1"),
                hostInstanceID: hostID,
                emittedAtUnixMilliseconds: 1_775_563_200_000
            )
        )
        let preflightRequest = try NativePreflightRequest(
            requestID: try opaque("request.1"),
            selections: [selection]
        )
        let preflight = try host.preflight(
            preflightRequest,
            metadata: NativeEnvelopeMetadata(
                envelopeID: try opaque("preflight.1"),
                hostInstanceID: hostID,
                emittedAtUnixMilliseconds: 1_775_563_200_000
            )
        )
        let readRequest = try NativeReadEnvelopeRequest(
            requestID: try opaque("request.1"),
            kind: .mail,
            accountID: mail.0.accounts[0].id,
            request: NativeReadRequest(bucketID: mail.0.buckets[0].id, limit: 1)
        )
        let admission = try host.read(
            readRequest,
            metadata: NativeEnvelopeMetadata(
                envelopeID: try opaque("nauth_0000000000000001"),
                hostInstanceID: hostID,
                emittedAtUnixMilliseconds: 1_775_563_200_000
            )
        )
        let exported = Export(
            agreement: try host.negotiate(NativeProtocolOffer(
                supportedVersions: [NativeSourceProtocolV1.identifier]
            )),
            discovery: discovery,
            preflight: preflight,
            admission: admission
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        FileHandle.standardOutput.write(try encoder.encode(exported))
    }
}
