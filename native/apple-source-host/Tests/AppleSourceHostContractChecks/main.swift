import AppleSourceHost
import Darwin
import Foundation

private enum ContractCheckError: Error {
    case failed(String)
}

private final class SpoolInstanceBox: @unchecked Sendable {
    private var value: ProtectedSpool?

    init(_ value: ProtectedSpool) {
        self.value = value
    }

    func destroy(after signal: DispatchSemaphore) {
        let doomed = value
        value = nil
        signal.signal()
        withExtendedLifetime(doomed) {}
    }
}

private final class WeakSpoolReference: @unchecked Sendable {
    weak var value: ProtectedSpool?

    init(_ value: ProtectedSpool) {
        self.value = value
    }
}

@main
struct AppleSourceHostContractChecks {
    static func main() throws {
        if CommandLine.arguments.count == 3,
           CommandLine.arguments[1] == "--lock-probe"
        {
            Darwin._exit(lockProbeExitStatus(path: CommandLine.arguments[2]))
        }
        try checkProtocolVersionAndValueValidation()
        try checkFrozenPageAndCursorBoundsRefuseRatherThanClamp()
        try checkAllThreeSyntheticAdapters()
        try checkSyntheticDenials()
        try checkIntegratedHostBoundary()
        try checkRecurrenceIdentityAndBounds()
        try checkFailClosedWireDecoding()
        try checkProtectedSpoolLifecycle()
        try checkProtectedSpoolFaultsAndBounds()
        try checkProtectedSpoolNamespaceSubstitution()
        try checkProtectedSpoolLockLifecycle()
        try checkSpoolItemsAreOwnerOnlyRegularFiles()
        try checkHostLifecycleRefusesIllegalTransitionsAndVersionDrift()
        try checkOperationalTelemetryIsContentFree()
        try checkMailDiscoveryIsConsentGatedBeforeAnyRead()
        try checkMailIdentityCompositionIsInjectiveAndRefusesToTrim()
        try checkMailIdentityIsStableAcrossReadsAndChangesWithTheGeneration()
        try checkMailReadRefusesAMechanismThatPublishesNoGeneration()
        try checkMailDateBoundIsSourceSideOrRefused()
        try checkMailBodyAndAttachmentBoundsOmitMarkAndRefuse()
        try checkMailPageCursorAndOrderingBounds()
        print("AppleSourceHostContractChecks: PASS (21 checks)")
    }

    private static func require(_ condition: Bool, _ message: String) throws {
        guard condition else {
            throw ContractCheckError.failed(message)
        }
    }

    private static func requireValue<Value>(_ value: Value?, _ message: String) throws -> Value {
        guard let value else {
            throw ContractCheckError.failed(message)
        }
        return value
    }

    private static func requireError(
        _ expected: NativeSourceContractError,
        operation: () throws -> some Any
    ) throws {
        do {
            _ = try operation()
            throw ContractCheckError.failed("Expected error \(expected)")
        } catch let error as NativeSourceContractError {
            try require(error == expected, "Expected \(expected), received \(error)")
        }
    }

    private static func requireSpoolError(
        _ expected: ProtectedSpoolError,
        operation: () throws -> some Any
    ) throws {
        do {
            _ = try operation()
            throw ContractCheckError.failed("Expected spool error \(expected)")
        } catch let error as ProtectedSpoolError {
            try require(error == expected, "Expected \(expected), received \(error)")
        }
    }

    private static func requireDecodeFailure<Value: Decodable>(
        _ type: Value.Type,
        data: Data
    ) throws {
        do {
            _ = try JSONDecoder().decode(type, from: data)
            throw ContractCheckError.failed("Malformed \(type) decoded successfully")
        } catch is ContractCheckError {
            throw ContractCheckError.failed("Malformed \(type) decoded successfully")
        } catch {
            return
        }
    }

    private static func mutatedJSON<Value: Encodable>(
        _ value: Value,
        mutation: (inout [String: Any]) throws -> Void
    ) throws -> Data {
        let encoded = try JSONEncoder().encode(value)
        guard var object = try JSONSerialization.jsonObject(with: encoded) as? [String: Any] else {
            throw ContractCheckError.failed("Expected keyed JSON for \(Value.self)")
        }
        try mutation(&object)
        return try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
    }

    private static func jsonDictionary(_ value: Any?) throws -> [String: Any] {
        guard let dictionary = value as? [String: Any] else {
            throw ContractCheckError.failed("Expected JSON dictionary")
        }
        return dictionary
    }

    private static func jsonDictionaryArray(_ value: Any?) throws -> [[String: Any]] {
        guard let dictionaries = value as? [[String: Any]] else {
            throw ContractCheckError.failed("Expected JSON dictionary array")
        }
        return dictionaries
    }

    private static func checkProtocolVersionAndValueValidation() throws {
        try require(
            NativeSourceProtocolV1.identifier == "my-pa.native-source.v1",
            "Protocol identifier drifted"
        )
        try require(NativeSourceOpaqueID(rawValue: "") == nil, "Empty identifier admitted")
        try require(
            NativeSourceOpaqueID(rawValue: "private locator") == nil,
            "Whitespace-bearing identifier admitted"
        )
        try require(
            NativeSourceOpaqueID(rawValue: "person@example.test") == nil,
            "Locator-shaped identifier admitted"
        )
        try require(NativeSourceOpaqueID(rawValue: ".hidden") == nil, "Hidden identifier admitted")
        try require(NativeReadCursor(rawValue: "") == nil, "Empty cursor admitted")
        try requireError(.invalidTimeRange) {
            try NativeTimeRange(startUnixMilliseconds: 2, endUnixMilliseconds: 1)
        }
        let bucketID = try requireValue(
            NativeSourceOpaqueID(rawValue: "bucket"),
            "Synthetic bucket identifier rejected"
        )
        try requireError(.invalidPageLimit) {
            try NativeReadRequest(bucketID: bucketID, limit: 0)
        }
    }

    /// The frozen page and cursor bounds, checked at the boundary that would be
    /// tempted to clamp them.
    ///
    /// The failure mode this exists for is not "the bound is missing" — that is
    /// visible by reading — it is "the bound is honoured by truncation". A host
    /// that answers a `limit: 5000` read with the first 100 records and no signal
    /// has silently lost 4900 records, and the caller cannot tell that from a
    /// bucket that genuinely held 100. So every over-bound input below is
    /// asserted to *throw*, and every at-bound input is asserted to survive with
    /// its full size intact.
    private static func checkFrozenPageAndCursorBoundsRefuseRatherThanClamp() throws {
        try require(
            NativeSourceProtocolV1.maximumPageSize == 100,
            "Frozen page size drifted from 100"
        )
        try require(
            NativeSourceProtocolV1.maximumCursorBytes == 512,
            "Frozen cursor byte ceiling drifted from 512"
        )

        let bucketID = try opaque("bounded-bucket")

        // The request limit: accepted at the ceiling, refused above it, never
        // rewritten down to it.
        let atCeiling = try NativeReadRequest(
            bucketID: bucketID,
            limit: NativeSourceProtocolV1.maximumPageSize
        )
        try require(
            atCeiling.limit == NativeSourceProtocolV1.maximumPageSize,
            "Request limit at the ceiling was altered"
        )
        try requireError(.invalidPageLimit) {
            try NativeReadRequest(
                bucketID: bucketID,
                limit: NativeSourceProtocolV1.maximumPageSize + 1
            )
        }
        try requireError(.invalidPageLimit) {
            try NativeReadRequest(bucketID: bucketID, limit: 5000)
        }
        // …and the same refusal off the wire, where a clamp would be invisible.
        try requireDecodeFailure(
            NativeReadRequest.self,
            data: try mutatedJSON(atCeiling) { $0["limit"] = 5000 }
        )

        // The cursor ceiling is counted in UTF-8 bytes, not characters, so a
        // multi-byte cursor is bounded by what it actually costs to store.
        let ascii = String(repeating: "c", count: NativeSourceProtocolV1.maximumCursorBytes)
        let atCursorCeiling = try requireValue(
            NativeReadCursor(rawValue: ascii),
            "Cursor at the byte ceiling rejected"
        )
        try require(
            atCursorCeiling.rawValue == ascii,
            "Cursor at the byte ceiling was truncated rather than kept whole"
        )
        try require(
            NativeReadCursor(rawValue: ascii + "c") == nil,
            "Over-long cursor admitted"
        )
        let multibyte = String(
            repeating: "\u{00E9}",
            count: NativeSourceProtocolV1.maximumCursorBytes / 2
        )
        try require(
            multibyte.count < multibyte.utf8.count,
            "The multi-byte cursor probe is not actually multi-byte"
        )
        try require(
            NativeReadCursor(rawValue: multibyte) != nil,
            "Multi-byte cursor at exactly the byte ceiling rejected"
        )
        try require(
            NativeReadCursor(rawValue: multibyte + "\u{00E9}") == nil,
            "Multi-byte cursor one character — two bytes — over the ceiling admitted"
        )

        // The page itself. An over-bound page is refused whole; it is not served
        // as its first `maximumPageSize` records.
        let record = NativeSourceRecord(
            id: try opaque("bounded-record"),
            bucketID: bucketID,
            kind: .mail,
            sourceRevision: "synthetic-v1",
            sourceModifiedUnixMilliseconds: nil,
            payload: [0x73]
        )
        let full = try NativeReadPage(
            records: Array(repeating: record, count: NativeSourceProtocolV1.maximumPageSize),
            nextCursor: atCursorCeiling
        )
        try require(
            full.records.count == NativeSourceProtocolV1.maximumPageSize,
            "A page at the ceiling lost records"
        )
        try requireError(.invalidPageLimit) {
            try NativeReadPage(
                records: Array(
                    repeating: record,
                    count: NativeSourceProtocolV1.maximumPageSize + 1
                ),
                nextCursor: nil
            )
        }
        // Decoding refuses too, so the bound cannot be walked around by handing
        // the host a JSON page instead of building one.
        let encodedPage = try JSONEncoder().encode(full)
        var pageObject = try jsonDictionary(
            try JSONSerialization.jsonObject(with: encodedPage)
        )
        var records = try jsonDictionaryArray(pageObject["records"])
        records.append(records[0])
        pageObject["records"] = records
        try requireDecodeFailure(
            NativeReadPage.self,
            data: try JSONSerialization.data(withJSONObject: pageObject, options: [.sortedKeys])
        )
        pageObject["records"] = try jsonDictionaryArray(
            try jsonDictionary(try JSONSerialization.jsonObject(with: encodedPage))["records"]
        )
        pageObject["nextCursor"] = ascii + "c"
        try requireDecodeFailure(
            NativeReadPage.self,
            data: try JSONSerialization.data(withJSONObject: pageObject, options: [.sortedKeys])
        )
    }

    private static func checkAllThreeSyntheticAdapters() throws {
        let mail = try makeFixture(kind: .mail)
        let calendar = try makeFixture(kind: .calendar)
        let contacts = try makeFixture(kind: .contacts)

        let mailAdapter = try SyntheticMailReadAdapter(
            snapshot: mail.snapshot,
            pages: [mail.fixture]
        )
        let calendarAdapter = try SyntheticCalendarReadAdapter(
            snapshot: calendar.snapshot,
            pages: [calendar.fixture]
        )
        let contactsAdapter = try SyntheticContactsReadAdapter(
            snapshot: contacts.snapshot,
            pages: [contacts.fixture]
        )

        requireMailConformance(mailAdapter)
        requireCalendarConformance(calendarAdapter)
        requireContactsConformance(contactsAdapter)

        try require(
            try mailAdapter.discoverMail().protocolVersion == NativeSourceProtocolV1.identifier,
            "Mail discovery returned a different protocol version"
        )
        try require(
            try mailAdapter.readMail(mail.request) == mail.fixture.page,
            "Mail fixture did not replay"
        )
        try require(
            try mailAdapter.readMail(mail.request) == mail.fixture.page,
            "Mail fixture replay was not deterministic"
        )
        try require(
            try calendarAdapter.readCalendar(calendar.request) == calendar.fixture.page,
            "Calendar fixture did not replay"
        )
        try require(
            try contactsAdapter.readContacts(contacts.request) == contacts.fixture.page,
            "Contacts fixture did not replay"
        )
    }

    private static func checkSyntheticDenials() throws {
        let mail = try makeFixture(kind: .mail)
        let contacts = try makeFixture(kind: .contacts)
        try requireError(.mismatchedSourceKind) {
            try SyntheticMailReadAdapter(snapshot: contacts.snapshot, pages: [contacts.fixture])
        }
        try requireError(.duplicateSyntheticPage) {
            try SyntheticMailReadAdapter(
                snapshot: mail.snapshot,
                pages: [mail.fixture, mail.fixture]
            )
        }

        let adapter = try SyntheticMailReadAdapter(
            snapshot: mail.snapshot,
            pages: [mail.fixture]
        )
        let unknownBucket = try requireValue(
            NativeSourceOpaqueID(rawValue: "unknown-bucket"),
            "Synthetic unknown bucket identifier rejected"
        )
        let unknown = try NativeReadRequest(bucketID: unknownBucket, limit: 1)
        try requireError(.unknownBucket) {
            try adapter.readMail(unknown)
        }
    }

    private static func checkIntegratedHostBoundary() throws {
        let hostID = try opaque("host-synthetic-01")
        let metadata = try NativeEnvelopeMetadata(
            envelopeID: try opaque("envelope-discovery-01"),
            hostInstanceID: hostID,
            emittedAtUnixMilliseconds: 1_700_000_000_000
        )
        let mail = try makeCollisionFixture(kind: .mail)
        let calendar = try makeFixture(kind: .calendar)
        let contacts = try makeFixture(kind: .contacts)
        let selected = NativeBucketSelection(
            kind: .mail,
            accountID: mail.snapshot.accounts[0].id,
            bucketID: mail.snapshot.buckets[0].id
        )
        let denied = NativeBucketSelection(
            kind: .mail,
            accountID: mail.snapshot.accounts[1].id,
            bucketID: mail.snapshot.buckets[1].id
        )
        try requireError(.inconsistentEnvelope) {
            try NativePreflightResult(
                selection: denied,
                state: .permissionDenied,
                failure: .bucketUnavailable
            )
        }
        let host = try SyntheticNativeHost(
            hostInstanceID: hostID,
            mail: SyntheticMailReadAdapter(snapshot: mail.snapshot, pages: mail.fixtures),
            calendar: SyntheticCalendarReadAdapter(
                snapshot: calendar.snapshot,
                pages: [calendar.fixture]
            ),
            contacts: SyntheticContactsReadAdapter(
                snapshot: contacts.snapshot,
                pages: [contacts.fixture]
            ),
            preflightFixtures: [
                try SyntheticPreflightFixture(selection: selected, state: .reachable),
                try SyntheticPreflightFixture(
                    selection: denied,
                    state: .permissionDenied,
                    failure: .permissionDenied
                ),
            ]
        )

        try require(
            try host.negotiate(NativeProtocolOffer(supportedVersions: ["future", "my-pa.native-source.v1"]))
                .selectedVersion == NativeSourceProtocolV1.identifier,
            "Version negotiation did not select the supported version"
        )
        try requireError(.unsupportedVersion) {
            try host.negotiate(NativeProtocolOffer(supportedVersions: ["future"]))
        }

        let discovery = try host.discover(.mail, metadata: metadata)
        try require(
            discovery.snapshot.accounts.map(\.id.rawValue) == ["acct-mail-a", "acct-mail-z"],
            "Discovery was not canonical across colliding display labels"
        )
        try require(
            Set(discovery.snapshot.accounts.map(\.displayLabel)).count == 1,
            "Display-label collision fixture drifted"
        )

        let request = try NativePreflightRequest(
            requestID: try opaque("preflight-01"),
            selections: [selected, denied].sorted {
                ($0.kind.rawValue, $0.accountID.rawValue, $0.bucketID.rawValue)
                    < ($1.kind.rawValue, $1.accountID.rawValue, $1.bucketID.rawValue)
            }
        )
        let preflight = try host.preflight(request, metadata: metadata)
        try require(
            preflight.results.map(\.selection) == request.selections,
            "Preflight did not preserve exact selected bucket order"
        )
        try require(
            Dictionary(uniqueKeysWithValues: preflight.results.map { ($0.selection, $0.state) })
                == [selected: .reachable, denied: .permissionDenied],
            "Preflight did not preserve independent bucket state"
        )

        let readRequest = try NativeReadEnvelopeRequest(
            requestID: try opaque("read-01"),
            kind: .mail,
            accountID: selected.accountID,
            request: try NativeReadRequest(bucketID: selected.bucketID, limit: 10)
        )
        let admission = try host.read(readRequest, metadata: metadata)
        try require(admission.bucketID == selected.bucketID, "Admission envelope lost exact bucket")
        try require(admission.records.count == 1, "Admission envelope lost fixture evidence")
        try require(
            try host.read(readRequest, metadata: metadata) == admission,
            "Integrated host boundary was not deterministic"
        )
        let handoffDirectory = temporaryDirectory("integrated-handoff")
        defer { try? FileManager.default.removeItem(at: handoffDirectory) }
        let handoff = try NativeSpoolItem(admissionEnvelope: admission)
        let handoffSpool = try ProtectedSpool(
            directory: handoffDirectory,
            limits: try ProtectedSpoolLimits(
                maximumItems: 1,
                maximumBytes: 32_000,
                maximumPayloadBytes: 16_000
            )
        )
        try require(
            try handoffSpool.enqueue(handoff) == .enqueued,
            "Versioned admission handoff was not atomically spooled"
        )
        let decodedHandoff = try JSONDecoder().decode(
            NativeAdmissionEnvelope.self,
            from: Data(handoffSpool.item(handoff.envelopeID).payload)
        )
        try require(decodedHandoff == admission, "Spool changed immutable handoff bytes")

        let wrongHost = try NativeEnvelopeMetadata(
            envelopeID: try opaque("envelope-wrong-host"),
            hostInstanceID: try opaque("host-other"),
            emittedAtUnixMilliseconds: metadata.emittedAtUnixMilliseconds
        )
        try requireError(.inconsistentEnvelope) {
            try host.discover(.mail, metadata: wrongHost)
        }
        try requireError(.inconsistentDiscovery) {
            try SyntheticNativeHost(
                hostInstanceID: hostID,
                mail: SyntheticMailReadAdapter(snapshot: mail.snapshot, pages: mail.fixtures),
                calendar: SyntheticCalendarReadAdapter(
                    snapshot: calendar.snapshot,
                    pages: [calendar.fixture]
                ),
                contacts: SyntheticContactsReadAdapter(
                    snapshot: contacts.snapshot,
                    pages: [contacts.fixture]
                ),
                preflightFixtures: [
                    try SyntheticPreflightFixture(
                        selection: NativeBucketSelection(
                            kind: .mail,
                            accountID: selected.accountID,
                            bucketID: try opaque("bucket-not-discovered")
                        ),
                        state: .reachable
                    )
                ]
            )
        }
    }

    private static func checkRecurrenceIdentityAndBounds() throws {
        let day: Int64 = 86_400_000
        let first: Int64 = 1_700_000_000_000
        let series = try NativeRecurrenceSeries(
            seriesID: try opaque("series-team-01"),
            bucketID: try opaque("bucket-calendar"),
            timezoneIdentifier: "America/New_York",
            firstStartUnixMilliseconds: first,
            durationMilliseconds: 3_600_000,
            intervalMilliseconds: day,
            occurrenceCount: 4,
            exceptions: [
                try NativeRecurrenceException(
                    scheduledStartUnixMilliseconds: first + day,
                    replacementStartUnixMilliseconds: first + day + 3_600_000,
                    replacementEndUnixMilliseconds: first + day + 7_200_000
                ),
                try NativeRecurrenceException(
                    scheduledStartUnixMilliseconds: first + (2 * day),
                    replacementStartUnixMilliseconds: nil,
                    replacementEndUnixMilliseconds: nil
                ),
            ],
            payload: [0x65, 0x76, 0x74]
        )
        let range = try NativeTimeRange(
            startUnixMilliseconds: first,
            endUnixMilliseconds: first + (4 * day)
        )
        let occurrences = try NativeRecurrenceExpander.expand(
            series,
            in: range,
            maximumOccurrences: 3
        )
        try require(occurrences.count == 3, "Cancellation did not preserve bounded expansion")
        try require(
            occurrences.map(\.identity.scheduledStartUnixMilliseconds)
                == [first, first + day, first + (3 * day)],
            "Occurrence identity did not remain anchored to scheduled series time"
        )
        try require(occurrences[1].isException, "Recurrence exception identity was lost")
        try require(
            occurrences.allSatisfy({
                $0.identity.seriesID == series.seriesID
                    && $0.timezoneIdentifier == "America/New_York"
            }),
            "Series or timezone identity drifted"
        )
        try requireError(.recurrenceLimitExceeded) {
            try NativeRecurrenceExpander.expand(series, in: range, maximumOccurrences: 2)
        }
        let distantSeries = try NativeRecurrenceSeries(
            seriesID: try opaque("series-distant"),
            bucketID: series.bucketID,
            timezoneIdentifier: "UTC",
            firstStartUnixMilliseconds: 0,
            durationMilliseconds: 1,
            intervalMilliseconds: day,
            occurrenceCount: nil,
            exceptions: [],
            payload: []
        )
        let distantStart = 1_000_000 * day
        let distant = try NativeRecurrenceExpander.expand(
            distantSeries,
            in: try NativeTimeRange(
                startUnixMilliseconds: distantStart,
                endUnixMilliseconds: distantStart
            ),
            maximumOccurrences: 1
        )
        try require(
            distant.map(\.identity.scheduledStartUnixMilliseconds) == [distantStart],
            "Distant recurrence did not fast-forward within the expansion bound"
        )
        try requireError(.invalidRecurrence) {
            try NativeRecurrenceSeries(
                seriesID: try opaque("series-misaligned"),
                bucketID: series.bucketID,
                timezoneIdentifier: "UTC",
                firstStartUnixMilliseconds: first,
                durationMilliseconds: 1,
                intervalMilliseconds: day,
                occurrenceCount: 2,
                exceptions: [
                    try NativeRecurrenceException(
                        scheduledStartUnixMilliseconds: first + 1,
                        replacementStartUnixMilliseconds: nil,
                        replacementEndUnixMilliseconds: nil
                    )
                ],
                payload: []
            )
        }
        let overflowSeries = try NativeRecurrenceSeries(
            seriesID: try opaque("series-overflow-bound"),
            bucketID: series.bucketID,
            timezoneIdentifier: "UTC",
            firstStartUnixMilliseconds: 0,
            durationMilliseconds: 1,
            intervalMilliseconds: 1,
            occurrenceCount: nil,
            exceptions: [
                try NativeRecurrenceException(
                    scheduledStartUnixMilliseconds: 0,
                    replacementStartUnixMilliseconds: nil,
                    replacementEndUnixMilliseconds: nil
                )
            ],
            payload: []
        )
        try requireError(.recurrenceLimitExceeded) {
            try NativeRecurrenceExpander.expand(
                overflowSeries,
                in: try NativeTimeRange(startUnixMilliseconds: 0, endUnixMilliseconds: Int64.max),
                maximumOccurrences: Int.max
            )
        }
    }

    private static func checkFailClosedWireDecoding() throws {
        let decoder = JSONDecoder()
        try requireDecodeFailure(
            NativeSourceOpaqueID.self,
            data: Data(#""../private""#.utf8)
        )
        try requireDecodeFailure(
            NativeReadCursor.self,
            data: Data(#""bad cursor""#.utf8)
        )
        try requireDecodeFailure(
            NativeTimeRange.self,
            data: Data(#"{"startUnixMilliseconds":2,"endUnixMilliseconds":1}"#.utf8)
        )

        let fixture = try makeFixture(kind: .mail)
        let invalidRead = try mutatedJSON(fixture.request) { $0["limit"] = 0 }
        try requireDecodeFailure(NativeReadRequest.self, data: invalidRead)

        let metadata = try NativeEnvelopeMetadata(
            envelopeID: try opaque("decode-envelope"),
            hostInstanceID: try opaque("decode-host"),
            emittedAtUnixMilliseconds: 1
        )
        try requireDecodeFailure(
            NativeEnvelopeMetadata.self,
            data: try mutatedJSON(metadata) { $0["protocolVersion"] = "unsupported" }
        )
        let agreement = try NativeProtocolAgreement(
            offer: NativeProtocolOffer(supportedVersions: [NativeSourceProtocolV1.identifier])
        )
        try requireDecodeFailure(
            NativeProtocolAgreement.self,
            data: try mutatedJSON(agreement) { $0["selectedVersion"] = "unsupported" }
        )

        try requireDecodeFailure(
            NativeDiscoverySnapshot.self,
            data: try mutatedJSON(fixture.snapshot) { object in
                object["protocolVersion"] = "unsupported"
            }
        )
        try requireDecodeFailure(
            NativeDiscoverySnapshot.self,
            data: try mutatedJSON(fixture.snapshot) { object in
                var accounts = try jsonDictionaryArray(object["accounts"])
                accounts[0]["kind"] = "contacts"
                object["accounts"] = accounts
            }
        )

        let collision = try makeCollisionFixture(kind: .mail)
        let canonicalSnapshot = try NativeDiscoverySnapshot(
            kind: .mail,
            accounts: collision.snapshot.accounts.sorted { $0.id.rawValue < $1.id.rawValue },
            buckets: collision.snapshot.buckets.sorted { $0.id.rawValue < $1.id.rawValue }
        )
        let discovery = try NativeDiscoveryEnvelope(metadata: metadata, snapshot: canonicalSnapshot)
        try requireDecodeFailure(
            NativeDiscoveryEnvelope.self,
            data: try mutatedJSON(discovery) { object in
                var snapshot = try jsonDictionary(object["snapshot"])
                let accounts = try jsonDictionaryArray(snapshot["accounts"])
                snapshot["accounts"] = [accounts[1], accounts[0]]
                object["snapshot"] = snapshot
            }
        )
        try requireDecodeFailure(
            NativeDiscoveryEnvelope.self,
            data: try mutatedJSON(discovery) { object in
                var snapshot = try jsonDictionary(object["snapshot"])
                let buckets = try jsonDictionaryArray(snapshot["buckets"])
                snapshot["buckets"] = [buckets[0], buckets[0]]
                object["snapshot"] = snapshot
            }
        )

        let selections = canonicalSnapshot.buckets.map {
            NativeBucketSelection(kind: .mail, accountID: $0.accountID, bucketID: $0.id)
        }.sorted {
            ($0.kind.rawValue, $0.accountID.rawValue, $0.bucketID.rawValue)
                < ($1.kind.rawValue, $1.accountID.rawValue, $1.bucketID.rawValue)
        }
        let preflightRequest = try NativePreflightRequest(
            requestID: try opaque("decode-preflight"),
            selections: selections
        )
        try requireDecodeFailure(
            NativePreflightRequest.self,
            data: try mutatedJSON(preflightRequest) { $0["protocolVersion"] = "unsupported" }
        )
        try requireDecodeFailure(
            NativePreflightRequest.self,
            data: try mutatedJSON(preflightRequest) { object in
                let selections = try jsonDictionaryArray(object["selections"])
                object["selections"] = [selections[1], selections[0]]
            }
        )
        try requireDecodeFailure(
            NativePreflightRequest.self,
            data: try mutatedJSON(preflightRequest) { object in
                let selections = try jsonDictionaryArray(object["selections"])
                object["selections"] = [selections[0], selections[0]]
            }
        )

        let result = try NativePreflightResult(selection: selections[0], state: .reachable)
        try requireDecodeFailure(
            NativePreflightResult.self,
            data: try mutatedJSON(result) { object in
                object["state"] = "permission_denied"
                object["failure"] = "bucket_unavailable"
            }
        )
        let preflightEnvelope = try NativePreflightEnvelope(
            metadata: metadata,
            request: preflightRequest,
            results: try selections.map {
                try NativePreflightResult(selection: $0, state: .reachable)
            }
        )
        try requireDecodeFailure(
            NativePreflightEnvelope.self,
            data: try mutatedJSON(preflightEnvelope) { object in
                let results = try jsonDictionaryArray(object["results"])
                object["results"] = [results[1], results[0]]
            }
        )

        let readEnvelopeRequest = try NativeReadEnvelopeRequest(
            requestID: try opaque("decode-read"),
            kind: .mail,
            accountID: fixture.snapshot.accounts[0].id,
            request: fixture.request
        )
        try requireDecodeFailure(
            NativeReadEnvelopeRequest.self,
            data: try mutatedJSON(readEnvelopeRequest) { $0["protocolVersion"] = "unsupported" }
        )
        let admission = try NativeAdmissionEnvelope(
            metadata: metadata,
            request: readEnvelopeRequest,
            page: fixture.fixture.page
        )
        try requireDecodeFailure(
            NativeAdmissionEnvelope.self,
            data: try mutatedJSON(admission) { object in
                var records = try jsonDictionaryArray(object["records"])
                records[0]["bucketID"] = "different-bucket"
                object["records"] = records
            }
        )

        let exception = try NativeRecurrenceException(
            scheduledStartUnixMilliseconds: 1,
            replacementStartUnixMilliseconds: nil,
            replacementEndUnixMilliseconds: nil
        )
        try requireDecodeFailure(
            NativeRecurrenceException.self,
            data: try mutatedJSON(exception) { object in
                object["replacementStartUnixMilliseconds"] = 2
            }
        )
        let series = try NativeRecurrenceSeries(
            seriesID: try opaque("decode-series"),
            bucketID: try opaque("decode-calendar"),
            timezoneIdentifier: "UTC",
            firstStartUnixMilliseconds: 0,
            durationMilliseconds: 1,
            intervalMilliseconds: 1,
            occurrenceCount: 2,
            exceptions: [],
            payload: []
        )
        try requireDecodeFailure(
            NativeRecurrenceSeries.self,
            data: try mutatedJSON(series) { $0["intervalMilliseconds"] = 0 }
        )

        let spoolItem = try self.spoolItem("decode-spool", payload: [1])
        try requireDecodeFailure(
            NativeSpoolItem.self,
            data: try mutatedJSON(spoolItem) { $0["protocolVersion"] = "unsupported" }
        )
        let validRoundTrip = try decoder.decode(
            NativeAdmissionEnvelope.self,
            from: JSONEncoder().encode(admission)
        )
        try require(validRoundTrip == admission, "Valid admission envelope failed decode")
    }

    private static func checkProtectedSpoolLifecycle() throws {
        let directory = temporaryDirectory("lifecycle")
        defer { try? FileManager.default.removeItem(at: directory) }
        let spool = try ProtectedSpool(
            directory: directory,
            limits: try ProtectedSpoolLimits(
                maximumItems: 3,
                maximumBytes: 32_000,
                maximumPayloadBytes: 32
            )
        )
        let first = try spoolItem("spool-01", payload: [1, 2, 3])
        let second = try spoolItem("spool-02", payload: [4, 5])
        try require(try spool.enqueue(first) == .enqueued, "First spool item was not enqueued")
        try require(
            try spool.enqueue(first) == .alreadyPresent,
            "Byte-identical enqueue was not idempotent"
        )
        try require(try spool.enqueue(second) == .enqueued, "Second spool item was not enqueued")
        try require(try spool.item(first.envelopeID) == first, "Pending bytes did not round trip")
        let before = try spool.inventory()
        try require(
            before.items.map(\.envelopeID.rawValue) == ["spool-01", "spool-02"],
            "Inventory was not deterministic"
        )
        try spool.quarantine(first.envelopeID)
        let retained = try spool.inventory()
        try require(
            retained.items.contains(where: {
                $0.envelopeID == first.envelopeID && $0.state == .quarantine
            }),
            "Quarantine did not retain the item"
        )
        try spool.acknowledge(second.envelopeID)
        let after = try spool.inventory()
        try require(after.itemCount == 1, "Acknowledgement did not remove only the pending item")

        var information = stat()
        try require(lstat(directory.path, &information) == 0, "Spool directory disappeared")
        try require(
            information.st_mode & (S_IRWXG | S_IRWXO) == 0,
            "Spool directory is not owner-only"
        )
    }

    private static func checkProtectedSpoolFaultsAndBounds() throws {
        let crashDirectory = temporaryDirectory("crash")
        defer { try? FileManager.default.removeItem(at: crashDirectory) }
        let crashSpool = try ProtectedSpool(
            directory: crashDirectory,
            limits: try ProtectedSpoolLimits(
                maximumItems: 2,
                maximumBytes: 32_000,
                maximumPayloadBytes: 4
            )
        )
        let crashItem = try spoolItem("spool-crash", payload: [1, 2, 3, 4])
        try requireSpoolError(.injectedCrash) {
            try crashSpool.enqueue(crashItem, fault: .afterTemporarySync)
        }
        try require(
            try crashSpool.inventory().items.first?.state == .crashResidue,
            "Synchronized crash residue was not inventoried"
        )
        let recovered = try crashSpool.recoverResidues()
        try require(
            recovered.items.first?.state == .quarantine,
            "Crash residue was not retained in quarantine"
        )
        try require(
            try crashSpool.enqueue(crashItem) == .alreadyPresent,
            "Recovered residue was not idempotently recognized"
        )
        try requireSpoolError(.payloadTooLarge) {
            try crashSpool.enqueue(try spoolItem("spool-large", payload: [1, 2, 3, 4, 5]))
        }
        let unsafeID = try opaque("unsafe-spool-json")
        let unsafeURL = crashDirectory
            .appendingPathComponent("pending", isDirectory: true)
            .appendingPathComponent(unsafeID.rawValue + ".pending", isDirectory: false)
        let unsafeBytes = try mutatedJSON(try spoolItem(unsafeID.rawValue, payload: [1])) {
            $0["protocolVersion"] = "unsupported"
        }
        try unsafeBytes.write(to: unsafeURL)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o600],
            ofItemAtPath: unsafeURL.path
        )
        try requireSpoolError(.corruptItem) {
            try crashSpool.item(unsafeID)
        }

        let capacityDirectory = temporaryDirectory("capacity")
        defer { try? FileManager.default.removeItem(at: capacityDirectory) }
        let probe = try spoolItem("probe", payload: [1])
        let encodedSize = try JSONEncoder().encode(probe).count
        let capacitySpool = try ProtectedSpool(
            directory: capacityDirectory,
            limits: try ProtectedSpoolLimits(
                maximumItems: 1,
                maximumBytes: Int64(encodedSize + 32),
                maximumPayloadBytes: 4
            )
        )
        try require(
            try capacitySpool.enqueue(try spoolItem("capacity-01", payload: [1])) == .enqueued,
            "Capacity fixture did not enqueue"
        )
        try requireSpoolError(.itemCapacityExceeded) {
            try capacitySpool.enqueue(try spoolItem("capacity-02", payload: [2]))
        }

        let byteDirectory = temporaryDirectory("bytes")
        defer { try? FileManager.default.removeItem(at: byteDirectory) }
        let byteSpool = try ProtectedSpool(
            directory: byteDirectory,
            limits: try ProtectedSpoolLimits(
                maximumItems: 2,
                maximumBytes: 1,
                maximumPayloadBytes: 4
            )
        )
        try requireSpoolError(.byteCapacityExceeded) {
            try byteSpool.enqueue(try spoolItem("bytes-01", payload: [1]))
        }

        let unsafeDirectory = temporaryDirectory("unsafe")
        try FileManager.default.createDirectory(at: unsafeDirectory, withIntermediateDirectories: false)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: unsafeDirectory.path)
        defer { try? FileManager.default.removeItem(at: unsafeDirectory) }
        try requireSpoolError(.unsafeDirectory) {
            try ProtectedSpool(
                directory: unsafeDirectory,
                limits: try ProtectedSpoolLimits(
                    maximumItems: 1,
                    maximumBytes: 10,
                    maximumPayloadBytes: 1
                )
            )
        }
    }

    private static func checkProtectedSpoolNamespaceSubstitution() throws {
        let parent = temporaryDirectory("namespace-parent")
        try FileManager.default.createDirectory(at: parent, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: parent) }
        let root = parent.appendingPathComponent("spool", isDirectory: true)
        let displaced = parent.appendingPathComponent("spool-original", isDirectory: true)
        let attacker = parent.appendingPathComponent("attacker", isDirectory: true)
        try FileManager.default.createDirectory(at: attacker, withIntermediateDirectories: false)
        try FileManager.default.createDirectory(
            at: attacker.appendingPathComponent("pending", isDirectory: true),
            withIntermediateDirectories: false
        )
        try FileManager.default.createDirectory(
            at: attacker.appendingPathComponent("quarantine", isDirectory: true),
            withIntermediateDirectories: false
        )
        let spool = try ProtectedSpool(
            directory: root,
            limits: try ProtectedSpoolLimits(
                maximumItems: 2,
                maximumBytes: 32_000,
                maximumPayloadBytes: 32
            )
        )
        try FileManager.default.moveItem(at: root, to: displaced)
        try FileManager.default.createSymbolicLink(at: root, withDestinationURL: attacker)
        try requireSpoolError(.unsafeDirectory) {
            try spool.enqueue(try spoolItem("namespace-escape", payload: [1]))
        }
        let attackerNames = try FileManager.default.contentsOfDirectory(atPath: attacker.path)
        let attackerPending = try FileManager.default.contentsOfDirectory(
            atPath: attacker.appendingPathComponent("pending").path
        )
        let attackerQuarantine = try FileManager.default.contentsOfDirectory(
            atPath: attacker.appendingPathComponent("quarantine").path
        )
        try require(
            attackerNames.sorted() == ["pending", "quarantine"]
                && attackerPending.isEmpty
                && attackerQuarantine.isEmpty,
            "Namespace substitution touched the attacker destination"
        )

        let childRoot = parent.appendingPathComponent("child-spool", isDirectory: true)
        let childSpool = try ProtectedSpool(
            directory: childRoot,
            limits: try ProtectedSpoolLimits(
                maximumItems: 1,
                maximumBytes: 32_000,
                maximumPayloadBytes: 32
            )
        )
        let childPending = childRoot.appendingPathComponent("pending", isDirectory: true)
        let childDisplaced = childRoot.appendingPathComponent("pending-original", isDirectory: true)
        try FileManager.default.moveItem(at: childPending, to: childDisplaced)
        try FileManager.default.createSymbolicLink(
            at: childPending,
            withDestinationURL: attacker.appendingPathComponent("pending", isDirectory: true)
        )
        try requireSpoolError(.unsafeDirectory) {
            try childSpool.enqueue(try spoolItem("child-escape", payload: [1]))
        }
        try require(
            try FileManager.default.contentsOfDirectory(
                atPath: attacker.appendingPathComponent("pending").path
            ).isEmpty,
            "Child-directory substitution touched the attacker destination"
        )
    }

    private static func checkProtectedSpoolLockLifecycle() throws {
        let root = temporaryDirectory("lock-lifecycle")
        defer { try? FileManager.default.removeItem(at: root) }
        let limits = try ProtectedSpoolLimits(
            maximumItems: 4,
            maximumBytes: 64_000,
            maximumPayloadBytes: 32
        )
        var primary: ProtectedSpool? = try ProtectedSpool(directory: root, limits: limits)
        let trackedSecondary = trackedSpool(
            try ProtectedSpool(directory: root, limits: limits)
        )
        let secondaryBox = trackedSecondary.box
        let weakSecondary = trackedSecondary.weak
        let destroyStarted = DispatchSemaphore(value: 0)
        let destroyFinished = DispatchSemaphore(value: 0)
        let lockURL = root.appendingPathComponent(".spool.lock", isDirectory: false)
        let weakPrimary = WeakSpoolReference(
            try requireValue(primary, "Primary spool disappeared before tracking")
        )
        do {
            let primaryValue = try requireValue(primary, "Primary spool disappeared")
            _ = try primaryValue.enqueue(
                try spoolItem("lock-lifecycle-01", payload: [1]),
                fault: .whileExclusivelyLocked {
                    DispatchQueue.global().async {
                        secondaryBox.destroy(after: destroyStarted)
                        destroyFinished.signal()
                    }
                    destroyStarted.wait()
                    var attempts = 0
                    while weakSecondary.value != nil && attempts < 10_000 {
                        usleep(100)
                        attempts += 1
                    }
                    try require(
                        weakSecondary.value == nil,
                        "Peer destruction did not reach deinitialization"
                    )
                    try require(
                        try crossProcessLockAttempt(lockURL) == 1,
                        "Destroying a peer instance released the active process lock"
                    )
                }
            )
        }
        destroyFinished.wait()
        try require(
            try crossProcessLockAttempt(lockURL) == 0,
            "External contender remained blocked after the primary operation unlocked"
        )

        primary = nil
        try require(weakPrimary.value == nil, "Final same-root reference did not clean up")
        let replacement = try ProtectedSpool(directory: root, limits: limits)
        let otherRoot = temporaryDirectory("lock-lifecycle-other")
        defer { try? FileManager.default.removeItem(at: otherRoot) }
        let otherSpool = try ProtectedSpool(directory: otherRoot, limits: limits)
        let otherLockURL = otherRoot.appendingPathComponent(".spool.lock", isDirectory: false)
        _ = try replacement.enqueue(
            try spoolItem("lock-lifecycle-02", payload: [2]),
            fault: .whileExclusivelyLocked {
                try require(
                    try crossProcessLockAttempt(lockURL) == 1,
                    "Recreated registry entry did not preserve cross-process exclusion"
                )
                try require(
                    try crossProcessLockAttempt(otherLockURL) == 0,
                    "An operation on one spool locked a different spool identity"
                )
            }
        )
        try require(
            try crossProcessLockAttempt(lockURL) == 0,
            "External contender remained blocked after recreated registry unlock"
        )
        withExtendedLifetime(otherSpool) {}
    }

    /// Returns 0 when a spawned contender acquires, 1 when the parent lock blocks
    /// it, and 2+ for an unexpected process or operating-system failure.
    private static func crossProcessLockAttempt(_ lockURL: URL) throws -> Int32 {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: CommandLine.arguments[0])
        process.arguments = ["--lock-probe", lockURL.path]
        try process.run()
        process.waitUntilExit()
        guard process.terminationReason == .exit else { return 3 }
        return process.terminationStatus
    }

    private static func lockProbeExitStatus(path: String) -> Int32 {
        let descriptor = Darwin.open(path, O_RDWR | O_NOFOLLOW)
        guard descriptor >= 0 else { return 2 }
        if Darwin.lockf(descriptor, F_TLOCK, 0) == 0 {
            _ = Darwin.lockf(descriptor, F_ULOCK, 0)
            _ = Darwin.close(descriptor)
            return 0
        }
        let blocked = errno == EACCES || errno == EAGAIN
        _ = Darwin.close(descriptor)
        return blocked ? 1 : 2
    }

    /// WP-15 control 3, the half the earlier checks left to the directory: an
    /// item file is a regular file owned by this user at mode 0600, and the
    /// directory holding it is 0700. Read by `stat` at runtime rather than
    /// inferred from the `S_IRUSR | S_IWUSR` literal in the source.
    private static func checkSpoolItemsAreOwnerOnlyRegularFiles() throws {
        let directory = temporaryDirectory("owner-modes")
        defer { try? FileManager.default.removeItem(at: directory) }
        let spool = try ProtectedSpool(
            directory: directory,
            limits: try ProtectedSpoolLimits(
                maximumItems: 4,
                maximumBytes: 64_000,
                maximumPayloadBytes: 64
            )
        )
        let item = try spoolItem("spool-modes", payload: Array("synthetic".utf8))
        try require(try spool.enqueue(item) == .enqueued, "Mode fixture did not enqueue")

        for relative in ["pending", "quarantine"] {
            var directoryInformation = stat()
            let path = directory.appendingPathComponent(relative, isDirectory: true).path
            try require(lstat(path, &directoryInformation) == 0, "\(relative) is missing")
            try require(
                directoryInformation.st_mode & 0o777 == 0o700,
                "\(relative) is not 0700"
            )
            try require(directoryInformation.st_uid == getuid(), "\(relative) is not owned by us")
        }

        var itemInformation = stat()
        let itemPath = directory
            .appendingPathComponent("pending", isDirectory: true)
            .appendingPathComponent(item.envelopeID.rawValue + ".pending", isDirectory: false)
            .path
        try require(lstat(itemPath, &itemInformation) == 0, "Spool item is missing")
        try require(
            itemInformation.st_mode & S_IFMT == S_IFREG,
            "Spool item is not a regular file"
        )
        try require(itemInformation.st_mode & 0o777 == 0o600, "Spool item is not 0600")
        try require(itemInformation.st_uid == getuid(), "Spool item is not owned by us")

        // The bound refuses; it does not evict. Everything already spooled is
        // still there after the refusal, and the refusal is an error rather than
        // a silently shortened queue.
        let saturated = try ProtectedSpool(
            directory: directory,
            limits: try ProtectedSpoolLimits(
                maximumItems: 1,
                maximumBytes: 64_000,
                maximumPayloadBytes: 64
            )
        )
        try requireSpoolError(.itemCapacityExceeded) {
            try saturated.enqueue(try spoolItem("spool-modes-2", payload: Array("synthetic".utf8)))
        }
        try require(
            try saturated.inventory().items.map(\.envelopeID.rawValue) == ["spool-modes"],
            "A refused enqueue disturbed what the spool already held"
        )
    }

    /// WP-15 control 4 at the host: the lifecycle refuses a version it does not
    /// speak instead of parsing it as best it can, and refuses a transition that
    /// would let a host hand off before it negotiated.
    private static func checkHostLifecycleRefusesIllegalTransitionsAndVersionDrift() throws {
        let hostID = try opaque("nbrg-lifecycle-0001")

        var wrongVersion = try NativeHostLifecycle(hostInstanceID: hostID)
        do {
            _ = try wrongVersion.negotiate(
                NativeProtocolOffer(supportedVersions: ["my-pa.native-source.v2"])
            )
            throw ContractCheckError.failed("A foreign protocol version negotiated")
        } catch let error as NativeSourceContractError {
            try require(error == .unsupportedVersion, "Wrong refusal for version drift")
        }
        try require(wrongVersion.state == .refused, "Version drift left the lifecycle usable")
        try require(
            NativeHostErrorClass(NativeSourceContractError.unsupportedVersion)
                == .unsupportedVersion,
            "Version drift did not classify"
        )

        var skipping = try NativeHostLifecycle(hostInstanceID: hostID)
        do {
            try skipping.readyForHandoff()
            throw ContractCheckError.failed("A host reached handoff without negotiating")
        } catch let error as NativeHostLifecycleError {
            try require(
                error == .illegalTransition(from: .constructed, to: .readyForHandoff),
                "Wrong refusal for an illegal transition"
            )
        }

        var lifecycle = try NativeHostLifecycle(hostInstanceID: hostID)
        let agreement = try lifecycle.negotiate(
            NativeProtocolOffer(supportedVersions: NativeSourceProtocolV1.supportedIdentifiers)
        )
        try require(
            agreement.selectedVersion == NativeSourceProtocolV1.identifier,
            "Negotiation selected a foreign version"
        )
        try lifecycle.openedSpool()
        try lifecycle.readyForHandoff()
        try require(lifecycle.state == .readyForHandoff, "Lifecycle did not reach handoff")
        try require(
            lifecycle.distributionModel == .unsignedDevelopmentBuild,
            "This build claimed a signed distribution model"
        )
        try require(
            !lifecycle.serviceRegistrationPerformed,
            "This build claimed a registered service"
        )
        try require(
            NativeHostLifecycle.unsatisfiedActivationPrerequisites.count
                == NativeHostActivationPrerequisite.allCases.count,
            "An activation prerequisite was marked satisfied by this build"
        )
        lifecycle.stop()
        do {
            try lifecycle.openedSpool()
            throw ContractCheckError.failed("A stopped host reopened its spool")
        } catch is NativeHostLifecycleError {}

        // Selecting the signed model from code would be a claim this build cannot
        // support, so it is refused at construction rather than recorded.
        do {
            _ = try NativeHostLifecycle(
                hostInstanceID: hostID,
                distributionModel: .signedNotarizedLoginItemService
            )
            throw ContractCheckError.failed("An unsigned build selected the signed model")
        } catch let error as NativeHostLifecycleError {
            try require(
                error == .activationNotAuthorized(.appleSigningIdentity),
                "Wrong refusal for an unauthorized distribution model"
            )
        }
    }

    /// WP-15 control 6. The marker below is an obviously-synthetic stand-in for a
    /// message body: it is spooled as real payload bytes, and then every
    /// operational value this host can emit is encoded and searched for it.
    private static func checkOperationalTelemetryIsContentFree() throws {
        let marker = "SYNTHETIC-BODY-MARKER-c0ffee"
        let directory = temporaryDirectory("telemetry")
        defer { try? FileManager.default.removeItem(at: directory) }
        let spool = try ProtectedSpool(
            directory: directory,
            limits: try ProtectedSpoolLimits(
                maximumItems: 4,
                maximumBytes: 64_000,
                maximumPayloadBytes: 128
            )
        )
        let hostID = try opaque("nbrg-telemetry-0001")
        let item = try spoolItem("spool-telemetry", payload: Array(marker.utf8))
        try require(try spool.enqueue(item) == .enqueued, "Telemetry fixture did not enqueue")

        // The marker really is held by the spool this telemetry describes —
        // otherwise "absent from telemetry" would be true for an uninteresting
        // reason.
        let stored = try spool.item(item.envelopeID)
        try require(
            stored.payload == Array(marker.utf8),
            "The spool did not retain the planted marker, so its absence proves nothing"
        )

        let health = try spool.health()
        try require(health.pendingItemCount == 1, "Health did not observe the pending item")
        try require(health.remainingItems == 3, "Health did not report headroom")
        try require(!health.atCapacity, "Health reported capacity it has not reached")

        var lifecycle = try NativeHostLifecycle(hostInstanceID: hostID)
        _ = try lifecycle.negotiate(
            NativeProtocolOffer(supportedVersions: NativeSourceProtocolV1.supportedIdentifiers)
        )
        try lifecycle.openedSpool()
        try lifecycle.readyForHandoff()

        let report = try NativeHostHealthReport(
            hostInstanceID: hostID,
            lifecycle: lifecycle,
            spool: health,
            observedAtUnixMilliseconds: 1_775_563_200_000
        )
        let enqueued = try NativeHostTelemetryEvent(
            event: .spoolEnqueued,
            hostInstanceID: hostID,
            kind: .mail,
            itemCount: health.pendingItemCount,
            byteCount: health.totalBytes,
            observedAtUnixMilliseconds: 1_775_563_200_000
        )

        // A refusal is the interesting case: this is where an implementation is
        // tempted to attach "what went wrong" and take the payload with it.
        var refusal: NativeHostTelemetryEvent?
        do {
            _ = try spool.enqueue(
                try spoolItem("spool-oversize", payload: Array(repeating: 0x41, count: 4096))
            )
        } catch {
            refusal = try NativeHostTelemetryEvent(
                refusal: error,
                event: .spoolRefusedAtCapacity,
                hostInstanceID: hostID,
                kind: .mail,
                observedAtUnixMilliseconds: 1_775_563_200_001
            )
        }
        let refused = try requireValue(refusal, "The oversize payload was not refused")
        try require(
            refused.errorClass == .spoolPayloadTooLarge,
            "The refusal did not classify as an oversize payload"
        )

        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let emissions: [Data] = [
            try encoder.encode(report),
            try encoder.encode(enqueued),
            try encoder.encode(refused),
            try encoder.encode(health),
            Data("\(report)".utf8),
            Data("\(enqueued)".utf8),
            Data("\(refused)".utf8),
            Data("\(health)".utf8),
            Data("\(lifecycle)".utf8),
        ]
        for emission in emissions {
            let rendered = String(decoding: emission, as: UTF8.self)
            try require(
                !rendered.contains(marker),
                "An operational emission carried spooled content"
            )
            try require(
                !rendered.contains(directory.path),
                "An operational emission carried a filesystem path"
            )
        }

        // Structural, not lexical: the only free `String` an emitted value holds
        // is the frozen protocol identifier. Everything else is a number, a
        // Boolean, an opaque identifier, or a closed enumeration — so there is
        // nowhere for content to go even if a future caller wanted to put it
        // there.
        for value in [try encoder.encode(enqueued), try encoder.encode(report)] {
            let object = try jsonDictionary(try JSONSerialization.jsonObject(with: value))
            for (key, entry) in object {
                guard let text = entry as? String else { continue }
                let closed = NativeHostTelemetryEventClass.allCases.map(\.rawValue)
                    + NativeHostErrorClass.allCases.map(\.rawValue)
                    + NativeHostLifecycleState.allCases.map(\.rawValue)
                    + NativeHostDistributionModel.allCases.map(\.rawValue)
                    + NativeSourceKind.allCases.map(\.rawValue)
                    + [NativeSourceProtocolV1.identifier, hostID.rawValue]
                try require(
                    closed.contains(text),
                    "Emitted field \(key) carries a string outside the closed vocabulary"
                )
            }
        }

        // A health report that claims a registered service is refused on decode:
        // this build cannot have performed one, so a wire value saying it did is
        // wrong rather than informative.
        let forged = try mutatedJSON(report) { $0["serviceRegistrationPerformed"] = true }
        try requireDecodeFailure(NativeHostHealthReport.self, data: forged)
    }

    private static func trackedSpool(
        _ spool: ProtectedSpool
    ) -> (box: SpoolInstanceBox, weak: WeakSpoolReference) {
        (SpoolInstanceBox(spool), WeakSpoolReference(spool))
    }

    private static func requireMailConformance<Adapter: MailReadAdapter>(_ adapter: Adapter) {}
    private static func requireCalendarConformance<Adapter: CalendarReadAdapter>(_ adapter: Adapter) {}
    private static func requireContactsConformance<Adapter: ContactsReadAdapter>(_ adapter: Adapter) {}

    private struct FixtureSet {
        let snapshot: NativeDiscoverySnapshot
        let fixture: SyntheticPageFixture
        let request: NativeReadRequest
    }

    private struct CollisionFixtureSet {
        let snapshot: NativeDiscoverySnapshot
        let fixtures: [SyntheticPageFixture]
    }

    private static func makeFixture(kind: NativeSourceKind) throws -> FixtureSet {
        let accountID = try requireValue(
            NativeSourceOpaqueID(rawValue: "acct-\(kind.rawValue)"),
            "Synthetic account identifier rejected"
        )
        let bucketID = try requireValue(
            NativeSourceOpaqueID(rawValue: "bucket-\(kind.rawValue)"),
            "Synthetic bucket identifier rejected"
        )
        let recordID = try requireValue(
            NativeSourceOpaqueID(rawValue: "record-\(kind.rawValue)"),
            "Synthetic record identifier rejected"
        )
        let account = NativeSourceAccount(
            id: accountID,
            kind: kind,
            displayLabel: "Synthetic account"
        )
        let bucket = NativeSourceBucket(
            id: bucketID,
            accountID: accountID,
            kind: kind,
            displayLabel: "Synthetic bucket",
            isSelectable: true
        )
        let snapshot = try NativeDiscoverySnapshot(
            kind: kind,
            accounts: [account],
            buckets: [bucket]
        )
        let record = NativeSourceRecord(
            id: recordID,
            bucketID: bucketID,
            kind: kind,
            sourceRevision: "synthetic-v1",
            sourceModifiedUnixMilliseconds: 1_700_000_000_000,
            payload: [0x73, 0x79, 0x6E]
        )
        let page = try NativeReadPage(records: [record], nextCursor: nil)
        let fixture = SyntheticPageFixture(bucketID: bucketID, requestCursor: nil, page: page)
        let request = try NativeReadRequest(bucketID: bucketID, limit: 50)
        return FixtureSet(snapshot: snapshot, fixture: fixture, request: request)
    }

    private static func makeCollisionFixture(kind: NativeSourceKind) throws -> CollisionFixtureSet {
        let accountZ = NativeSourceAccount(
            id: try opaque("acct-\(kind.rawValue)-z"),
            kind: kind,
            displayLabel: "Same label"
        )
        let accountA = NativeSourceAccount(
            id: try opaque("acct-\(kind.rawValue)-a"),
            kind: kind,
            displayLabel: "Same label"
        )
        let bucketZ = NativeSourceBucket(
            id: try opaque("bucket-\(kind.rawValue)-z"),
            accountID: accountZ.id,
            kind: kind,
            displayLabel: "Same bucket",
            isSelectable: true
        )
        let bucketA = NativeSourceBucket(
            id: try opaque("bucket-\(kind.rawValue)-a"),
            accountID: accountA.id,
            kind: kind,
            displayLabel: "Same bucket",
            isSelectable: true
        )
        let snapshot = try NativeDiscoverySnapshot(
            kind: kind,
            accounts: [accountZ, accountA],
            buckets: [bucketZ, bucketA]
        )
        let fixtures = try [bucketZ, bucketA].map { bucket -> SyntheticPageFixture in
            let record = NativeSourceRecord(
                id: try opaque("record-\(bucket.id.rawValue)"),
                bucketID: bucket.id,
                kind: kind,
                sourceRevision: "synthetic-v1",
                sourceModifiedUnixMilliseconds: nil,
                payload: [0x73]
            )
            return SyntheticPageFixture(
                bucketID: bucket.id,
                requestCursor: nil,
                page: try NativeReadPage(records: [record], nextCursor: nil)
            )
        }
        return CollisionFixtureSet(snapshot: snapshot, fixtures: fixtures)
    }

    private static func opaque(_ value: String) throws -> NativeSourceOpaqueID {
        try requireValue(NativeSourceOpaqueID(rawValue: value), "Opaque identifier rejected: \(value)")
    }

    private static func spoolItem(_ id: String, payload: [UInt8]) throws -> NativeSpoolItem {
        try NativeSpoolItem(
            envelopeID: try opaque(id),
            kind: .mail,
            accountID: try opaque("account-spool"),
            bucketID: try opaque("bucket-spool"),
            payload: payload
        )
    }

    private static func temporaryDirectory(_ suffix: String) -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("my-pa-wp12d-\(suffix)-\(UUID().uuidString)", isDirectory: true)
    }

    // MARK: - WP-16: the Mail adapter's six controls, at runtime
    //
    // Every fixture value below is obviously synthetic. `.invalid` is the
    // reserved TLD and nothing here has ever been near a mailbox.

    private static let dayMilliseconds = MailDayWindow.millisecondsPerDay

    private static func mailComponent(_ value: String) throws -> MailIdentityComponent {
        try requireValue(
            MailIdentityComponent(rawValue: value),
            "Mail identity component rejected: \(value)"
        )
    }

    /// Provider keys are compared **lexicographically**, so a mechanism whose
    /// keys are numeric has to zero-pad them or the cursor resumes in the wrong
    /// place — `10` sorts before `9`. The fixture pads, and the record says so.
    private static func providerKey(_ number: Int) throws -> MailIdentityComponent {
        try mailComponent(String(format: "uid-%06d", number))
    }

    private static func fixtureMailbox() throws -> NativeSourceOpaqueID {
        try opaque("mailbox-inbox-a")
    }

    private static func fixtureAccount() throws -> NativeSourceOpaqueID {
        try opaque("account-a")
    }

    private static func mailHeaders(_ index: Int) -> [UInt8] {
        Array(
            """
            From: person-a@example.invalid
            To: person-b@example.invalid
            Subject: Fixture Subject \(String(format: "%03d", index))
            """.utf8
        )
    }

    private static func fixtureMessage(
        _ number: Int,
        receivedUnixMilliseconds: Int64,
        bodyBytes: [UInt8]? = nil,
        attachments: [MailAttachmentDescriptor] = []
    ) throws -> FixtureMailMessage {
        FixtureMailMessage(
            providerKey: try providerKey(number),
            receivedUnixMilliseconds: receivedUnixMilliseconds,
            sentUnixMilliseconds: receivedUnixMilliseconds - 1000,
            headerBytes: mailHeaders(number),
            bodyBytes: bodyBytes ?? Array("Fixture body \(number)".utf8),
            attachments: attachments
        )
    }

    private static func mailMechanism(
        messages: [FixtureMailMessage],
        generation: String = "gen-0001",
        dateBound: MailDateBoundEnforcement = .sourceSideDayGranular,
        publishesGeneration: Bool = true,
        consent: MailConsentState = .granted
    ) throws -> FixtureMailMechanism {
        FixtureMailMechanism(
            descriptor: MailMechanismDescriptor(
                mechanism: .fixtureImapShaped,
                dateBound: dateBound,
                publishesGeneration: publishesGeneration,
                requiresOperatorConsent: false
            ),
            accounts: [
                MailAccountDescriptor(id: try fixtureAccount(), displayLabel: "Fixture Account A"),
            ],
            mailboxes: [
                MailMailboxDescriptor(
                    id: try fixtureMailbox(),
                    accountID: try fixtureAccount(),
                    displayLabel: "Fixture Inbox",
                    isSelectable: true
                ),
                MailMailboxDescriptor(
                    id: try opaque("mailbox-archive-a"),
                    accountID: try fixtureAccount(),
                    parentID: try fixtureMailbox(),
                    displayLabel: "Fixture Archive",
                    isSelectable: true
                ),
            ],
            messages: messages,
            generation: try mailComponent(generation),
            consent: consent
        )
    }

    private static func mailRequest(
        limit: Int = NativeSourceProtocolV1.maximumPageSize,
        timeRange: NativeTimeRange? = nil,
        cursor: NativeReadCursor? = nil
    ) throws -> NativeReadRequest {
        try NativeReadRequest(
            bucketID: try fixtureMailbox(),
            timeRange: timeRange,
            cursor: cursor,
            limit: limit
        )
    }

    /// Byte-level substring search. The planted marker has to be looked for in
    /// bytes, because every byte-bearing field on the wire is a JSON array of
    /// numbers and a text search over the payload can never find it.
    private static func containsSubsequence(_ haystack: [UInt8], _ needle: [UInt8]) -> Bool {
        guard !needle.isEmpty, haystack.count >= needle.count else { return false }
        for start in 0...(haystack.count - needle.count)
        where Array(haystack[start..<(start + needle.count)]) == needle {
            return true
        }
        return false
    }

    private static func decodedMailContent(_ record: NativeSourceRecord) throws -> MailRecordContent {
        try JSONDecoder().decode(MailRecordContent.self, from: Data(record.payload))
    }

    private static func requireProviderFailure(
        _ expected: NativeProviderFailure,
        operation: () throws -> some Any
    ) throws {
        do {
            _ = try operation()
            throw ContractCheckError.failed("Expected provider failure \(expected)")
        } catch let failure as NativeProviderFailure {
            try require(failure == expected, "Expected \(expected), received \(failure)")
        }
    }

    /// Control 5, and control 1's consent half. Consent is read **before** the
    /// first read, and a refusal is measured rather than argued: the fixture
    /// counts every call the adapter makes to it, so "nothing was read" is a
    /// number and not a claim about the source.
    private static func checkMailDiscoveryIsConsentGatedBeforeAnyRead() throws {
        let mechanism = try mailMechanism(messages: [
            try fixtureMessage(1, receivedUnixMilliseconds: 1_700_000_000_000),
        ])
        let adapter = BoundedMailReadAdapter(mechanism: mechanism)

        let snapshot = try adapter.discoverMail()
        try require(snapshot.kind == .mail, "Mail discovery returned the wrong kind")
        try require(snapshot.accounts.count == 1, "Mail discovery lost the account")
        try require(snapshot.buckets.count == 2, "Mail discovery lost a mailbox")
        try require(
            snapshot.buckets.contains { $0.parentID != nil },
            "Mail discovery flattened the mailbox hierarchy"
        )
        try require(
            snapshot.protocolVersion == NativeSourceProtocolV1.identifier,
            "Mail discovery drifted from the frozen protocol identifier"
        )

        // Every state that is not `granted` stops the adapter, and the two that
        // mean "we have not asked" are treated exactly like refusal — on macOS
        // the asking is what raises the dialogue, and a TCC grant is the
        // operator's to give (EXT-04).
        for state in [MailConsentState.denied, .notDetermined] {
            mechanism.setConsent(state)
            mechanism.resetCallCounters()
            try requireProviderFailure(.permissionDenied) { try adapter.discoverMail() }
            try requireProviderFailure(.permissionDenied) { try adapter.readMail(try mailRequest()) }
            try require(
                mechanism.readCalls == 0,
                "The adapter made \(mechanism.readCalls) reads with consent \(state.rawValue)"
            )
            try require(
                mechanism.consentCalls == 2,
                "Consent was not consulted once per operation"
            )
        }

        mechanism.setConsent(.targetUnavailable)
        mechanism.resetCallCounters()
        try requireProviderFailure(.accountUnavailable) { try adapter.discoverMail() }
        try require(mechanism.readCalls == 0, "An unavailable target was still read from")
    }

    /// Control 2, first half: the identifier a message composes to is injective
    /// and is refused rather than trimmed.
    private static func checkMailIdentityCompositionIsInjectiveAndRefusesToTrim() throws {
        // The component alphabet excludes `:`, which is what makes the composed
        // identifier decomposable from the right and therefore injective.
        try require(
            MailIdentityComponent(rawValue: "gen:0001") == nil,
            "A colon in an identity component would make composition ambiguous"
        )
        try require(MailIdentityComponent(rawValue: "") == nil, "Empty component admitted")
        let atCeiling = String(
            repeating: "u",
            count: NativeSourceProtocolV1.maximumMailIdentityComponentBytes
        )
        try require(
            MailIdentityComponent(rawValue: atCeiling) != nil,
            "Component at the byte ceiling rejected"
        )
        try require(
            MailIdentityComponent(rawValue: atCeiling + "u") == nil,
            "Over-long component admitted"
        )
        try requireDecodeFailure(
            MailIdentityComponent.self,
            data: Data("\"gen:0001\"".utf8)
        )

        // Injectivity, demonstrated on the pair that would collide if the
        // separator were allowed inside a component.
        let left = MailMessageIdentity(
            mailboxID: try opaque("mailbox-a:extra"),
            generation: try mailComponent("gen-0001"),
            providerKey: try providerKey(7)
        )
        let right = MailMessageIdentity(
            mailboxID: try opaque("mailbox-a"),
            generation: try mailComponent("extra"),
            providerKey: try mailComponent("gen-0001")
        )
        try require(
            try left.recordIdentifier() != right.recordIdentifier(),
            "Two distinct mail identities composed to one record identifier"
        )

        // Over the opaque identifier's own ceiling the composition is refused.
        // Trimming here would alias two messages onto one record, which is the
        // one truncation with no honest partial form.
        let longMailbox = try opaque(String(repeating: "m", count: 190))
        let overflowing = MailMessageIdentity(
            mailboxID: longMailbox,
            generation: try mailComponent("gen-0001"),
            providerKey: try providerKey(7)
        )
        try requireError(.mailIdentityTooLong) { try overflowing.recordIdentifier() }
    }

    /// Control 2, and the negative half is the point. Identity is stable across
    /// repeated reads and across a sync cycle that preserves the generation, and
    /// it **changes** when the generation changes, because a provider key means
    /// nothing outside the generation that issued it.
    private static func checkMailIdentityIsStableAcrossReadsAndChangesWithTheGeneration() throws {
        let base: Int64 = 1_700_000_000_000
        let mechanism = try mailMechanism(messages: [
            try fixtureMessage(1, receivedUnixMilliseconds: base),
            try fixtureMessage(2, receivedUnixMilliseconds: base + 60_000),
            try fixtureMessage(3, receivedUnixMilliseconds: base + 120_000),
        ])
        let adapter = BoundedMailReadAdapter(mechanism: mechanism)

        let first = try adapter.readMail(try mailRequest()).records.map(\.id.rawValue)
        let second = try adapter.readMail(try mailRequest()).records.map(\.id.rawValue)
        try require(first.count == 3, "The fixture mailbox did not traverse")
        try require(first == second, "A repeated read produced different identities")
        try require(Set(first).count == first.count, "Identities repeated inside one page")

        // A sync cycle that adds mail without re-keying: existing identities are
        // untouched, and the new message gets its own.
        mechanism.syncPreservingGeneration(adding: [
            try fixtureMessage(4, receivedUnixMilliseconds: base + 180_000),
        ])
        let afterSync = try adapter.readMail(try mailRequest()).records.map(\.id.rawValue)
        try require(
            Array(afterSync.prefix(3)) == first,
            "A sync cycle that preserved the generation moved existing identities"
        )
        try require(afterSync.count == 4, "The synced message did not appear")

        // The generation moves — IMAP's `UIDVALIDITY` bump. Every identity must
        // change; a stable identity here would be the failure, because the same
        // provider key now names a different message.
        mechanism.regenerate(as: try mailComponent("gen-0002"))
        let afterRegeneration = try adapter.readMail(try mailRequest()).records
        try require(
            Set(afterRegeneration.map(\.id.rawValue)).isDisjoint(with: Set(afterSync)),
            "A generation change left identities unchanged; a stale key would now "
                + "resolve to a different message"
        )
        try require(
            afterRegeneration.allSatisfy { $0.sourceRevision == "gen-0002" },
            "The record does not carry the generation it was read under"
        )
        try require(
            try decodedMailContent(afterRegeneration[0]).identity.generation.rawValue == "gen-0002",
            "The payload identity does not carry the generation"
        )
    }

    /// Control 1's honest half. A mechanism that cannot name its generation is
    /// refused before it is read from at all — which is exactly the position
    /// Apple Mail's scripting terminology is in, since it publishes no
    /// `UIDVALIDITY` equivalent.
    private static func checkMailReadRefusesAMechanismThatPublishesNoGeneration() throws {
        let mechanism = try mailMechanism(
            messages: [try fixtureMessage(1, receivedUnixMilliseconds: 1_700_000_000_000)],
            publishesGeneration: false
        )
        let adapter = BoundedMailReadAdapter(mechanism: mechanism)
        mechanism.resetCallCounters()
        try requireError(.mailGenerationUnavailable) { try adapter.readMail(try mailRequest()) }
        try require(
            mechanism.summaryCalls == 0 && mechanism.contentCalls == 0,
            "A generation-less mechanism was read from before being refused"
        )
        try require(
            NativeHostErrorClass(NativeSourceContractError.mailGenerationUnavailable)
                == .mailMechanismUnsupported,
            "The generation refusal is not classified for an operator"
        )
    }

    /// Control 3. The bound reaches the source, the widening is outward, the
    /// refinement is exact, and a mechanism that cannot bound at the source is
    /// refused rather than scanned.
    private static func checkMailDateBoundIsSourceSideOrRefused() throws {
        // Three days, one message per day, at midday UTC.
        let dayZero: Int64 = 1_700_000_000_000 - (1_700_000_000_000 % dayMilliseconds)
        let midday = dayMilliseconds / 2
        let messages = try (0..<3).map { offset in
            try fixtureMessage(
                offset + 1,
                receivedUnixMilliseconds: dayZero + Int64(offset) * dayMilliseconds + midday
            )
        }

        // The widening is outward and day-aligned, and a window that is not
        // day-aligned cannot be constructed at all.
        let exact = try NativeTimeRange(
            startUnixMilliseconds: dayZero + midday,
            endUnixMilliseconds: dayZero + dayMilliseconds + midday
        )
        let widened = try MailDayWindow.widening(exact)
        try require(
            widened.startUnixMilliseconds <= exact.startUnixMilliseconds
                && widened.endUnixMilliseconds >= exact.endUnixMilliseconds,
            "The day widening narrowed the requested interval"
        )
        try requireError(.mailWindowNotDayAligned) {
            try MailDayWindow(
                startUnixMilliseconds: dayZero + 1,
                endUnixMilliseconds: dayZero + dayMilliseconds - 1
            )
        }
        try requireDecodeFailure(
            MailDayWindow.self,
            data: try mutatedJSON(widened) { $0["startUnixMilliseconds"] = dayZero + 1 }
        )
        // Floor division, so an instant before 1970 rounds down rather than
        // toward zero. Truncating division would lose the boundary day.
        try require(
            MailDayWindow.dayFloor(-1) == -dayMilliseconds,
            "The day floor rounds toward zero for pre-epoch instants"
        )

        // The bound is applied at the source and refined here. Day two's message
        // is inside the widened window and outside the exact one, so it proves
        // the refinement actually refines.
        let mechanism = try mailMechanism(messages: messages)
        let adapter = BoundedMailReadAdapter(mechanism: mechanism)
        let bounded = try adapter.readMail(try mailRequest(timeRange: exact))
        try require(
            bounded.records.count == 2,
            "Date-bounded traversal returned \(bounded.records.count) records, expected 2"
        )
        try require(
            bounded.records.allSatisfy {
                ($0.sourceModifiedUnixMilliseconds ?? 0) >= exact.startUnixMilliseconds
                    && ($0.sourceModifiedUnixMilliseconds ?? 0) <= exact.endUnixMilliseconds
            },
            "A record outside the requested interval was admitted"
        )

        // A mechanism that ignores the window it was handed is caught, not
        // believed. The adapter re-checks the answer against the bound.
        mechanism.setFault(.ignoreTheWindow)
        try requireError(.mailDateBoundViolated) {
            try adapter.readMail(try mailRequest(timeRange: exact))
        }

        // A mechanism that satisfies the bound by walking the whole mailbox is
        // refused: "date-bounded without enumerating the store" is the
        // acceptance, and a full scan is precisely not it.
        mechanism.setFault(.declareWholeMailboxScan)
        try requireError(.mailDateBoundNotSourceSide) {
            try adapter.readMail(try mailRequest(timeRange: exact))
        }
        mechanism.setFault(.none)

        // …and a mechanism that declares up front that it cannot bound at the
        // source is refused before it is asked anything.
        let clientSide = try mailMechanism(
            messages: messages,
            dateBound: .clientSideAfterFullScan
        )
        let clientSideAdapter = BoundedMailReadAdapter(mechanism: clientSide)
        clientSide.resetCallCounters()
        try requireError(.mailDateBoundNotSourceSide) {
            try clientSideAdapter.readMail(try mailRequest(timeRange: exact))
        }
        try require(
            clientSide.summaryCalls == 0,
            "A client-side-only mechanism was enumerated before being refused"
        )
        // An unbounded read against the same mechanism is still allowed: the
        // refusal is about the *bound*, not about the mechanism.
        try require(
            try clientSideAdapter.readMail(try mailRequest()).records.count == 3,
            "The client-side refusal leaked into unbounded traversal"
        )
    }

    /// Control 4. A body is carried whole or omitted whole and never trimmed; an
    /// omission is marked and quantified; a header block with no honest partial
    /// form refuses the record; and attachment bytes have nowhere to live.
    private static func checkMailBodyAndAttachmentBoundsOmitMarkAndRefuse() throws {
        let base: Int64 = 1_700_000_000_000
        let marker = "OVERSIZE-BODY-MARKER-person-a-at-example-invalid"
        var oversizeBody = Array(marker.utf8)
        oversizeBody.append(
            contentsOf: Array(
                repeating: UInt8(ascii: "x"),
                count: NativeSourceProtocolV1.maximumMailBodyBytes + 1 - oversizeBody.count
            )
        )
        try require(
            oversizeBody.count == NativeSourceProtocolV1.maximumMailBodyBytes + 1,
            "The oversize body probe is not actually oversize"
        )
        let atCeiling = Array(
            repeating: UInt8(ascii: "y"),
            count: NativeSourceProtocolV1.maximumMailBodyBytes
        )

        let attachments = try (0..<40).map { index in
            try MailAttachmentDescriptor(
                id: try opaque("attachment-\(String(format: "%03d", index))"),
                mimeType: "application/octet-stream",
                byteSize: 1024,
                disposition: .metadataOnly
            )
        }
        let mechanism = try mailMechanism(messages: [
            try fixtureMessage(1, receivedUnixMilliseconds: base, bodyBytes: atCeiling),
            try fixtureMessage(2, receivedUnixMilliseconds: base + 1000, bodyBytes: oversizeBody),
            try fixtureMessage(
                3,
                receivedUnixMilliseconds: base + 2000,
                attachments: attachments
            ),
        ])
        let adapter = BoundedMailReadAdapter(mechanism: mechanism)
        let page = try adapter.readMail(try mailRequest())
        try require(page.records.count == 3, "The bounded mail page lost a record")

        // At the ceiling the body is carried whole.
        let kept = try decodedMailContent(page.records[0])
        try require(kept.completeness.bodyIncluded, "A body at the ceiling was omitted")
        try require(kept.body?.count == atCeiling.count, "A body at the ceiling was trimmed")
        try require(!kept.completeness.isPartial, "A complete record was marked partial")

        // Over the ceiling it is omitted, marked, and its true size recorded —
        // and none of it reaches the payload. The marker is planted at the front
        // of the body precisely so a `prefix`-style truncation would leak it.
        let omitted = try decodedMailContent(page.records[1])
        try require(!omitted.completeness.bodyIncluded, "An oversize body was carried")
        try require(omitted.body == nil, "An oversize body was carried in part")
        try require(
            omitted.completeness.bodyByteSize == oversizeBody.count,
            "The omission did not record the body's true size"
        )
        try require(omitted.completeness.isPartial, "An omitted body was not marked partial")
        // Searched as **bytes**, in every byte-bearing field and in the raw
        // payload. The obvious form of this check — decoding the payload as
        // UTF-8 and looking for the marker as text — is vacuous, and a planted
        // leak proved it: `[UInt8]` encodes to a JSON array of decimal numbers,
        // so the marker's characters are never present as characters no matter
        // what leaks. It is recorded in WP-16's reversion table rather than
        // quietly corrected.
        let markerBytes = Array(marker.utf8)
        try require(
            !containsSubsequence(omitted.headers, markerBytes),
            "The oversize body's first bytes reached the record's headers; an "
                + "omitted body must be omitted, not previewed somewhere else"
        )
        try require(
            !containsSubsequence(page.records[1].payload, markerBytes),
            "The oversize body's first bytes reached the payload; the bound truncated "
                + "rather than omitted"
        )

        // Attachments: descriptors bounded and the shortfall recorded, bytes
        // nowhere at any size.
        let described = try decodedMailContent(page.records[2])
        try require(
            described.attachments.count == NativeSourceProtocolV1.maximumMailAttachmentDescriptors,
            "The attachment descriptor bound was not applied"
        )
        try require(
            described.completeness.attachmentCount == 40,
            "The true attachment count was not recorded"
        )
        try require(described.completeness.isPartial, "A shortened descriptor list was not marked")
        try require(
            described.attachments.allSatisfy { $0.byteSize <= NativeSourceProtocolV1.maximumMailAttachmentBytes },
            "An oversize attachment was described as if it were fetchable"
        )
        // An attachment above the fetch ceiling must be labelled as such.
        try requireError(.mailContentInconsistent) {
            try MailAttachmentDescriptor(
                id: try opaque("attachment-huge"),
                mimeType: "application/octet-stream",
                byteSize: NativeSourceProtocolV1.maximumMailAttachmentBytes + 1,
                disposition: .metadataOnly
            )
        }
        _ = try MailAttachmentDescriptor(
            id: try opaque("attachment-huge"),
            mimeType: "application/octet-stream",
            byteSize: NativeSourceProtocolV1.maximumMailAttachmentBytes + 1,
            disposition: .omittedOversize
        )

        // A header block has no honest partial form, so the record is refused.
        let hugeHeaders = try mailMechanism(messages: [
            FixtureMailMessage(
                providerKey: try providerKey(9),
                receivedUnixMilliseconds: base,
                sentUnixMilliseconds: nil,
                headerBytes: Array(
                    repeating: UInt8(ascii: "h"),
                    count: NativeSourceProtocolV1.maximumMailHeaderBytes + 1
                ),
                bodyBytes: []
            ),
        ])
        try requireError(.mailHeaderTooLarge) {
            try BoundedMailReadAdapter(mechanism: hugeHeaders).readMail(try mailRequest())
        }

        // And the whole of it again off the wire. A bound enforced only on the
        // initialiser is a bound that can be walked around by handing the host
        // JSON — WP-15's lesson, applied to the content bounds.
        try requireDecodeFailure(
            MailRecordContent.self,
            data: try mutatedJSON(kept) { object in
                // A body trimmed to half its declared size: the truncation that
                // would otherwise be invisible.
                object["body"] = Array(atCeiling.prefix(atCeiling.count / 2)).map { Int($0) }
            }
        )
        try requireDecodeFailure(
            MailRecordContent.self,
            data: try mutatedJSON(kept) { object in
                object["completeness"] = [
                    "bodyIncluded": true,
                    "bodyByteSize": atCeiling.count,
                    "attachmentCount": 0,
                    "attachmentsDescribed":
                        NativeSourceProtocolV1.maximumMailAttachmentDescriptors + 1,
                ]
            }
        )
        try requireDecodeFailure(
            MailRecordContent.self,
            data: try mutatedJSON(omitted) { object in
                // "The body was included" with no body: an inconsistent claim.
                object["completeness"] = [
                    "bodyIncluded": true,
                    "bodyByteSize": omitted.completeness.bodyByteSize,
                    "attachmentCount": 0,
                    "attachmentsDescribed": 0,
                ]
            }
        )
    }

    /// Controls 3 and 4 where they meet the frozen protocol bounds: the page
    /// ceiling, the cursor, and the strict ordering the cursor depends on.
    private static func checkMailPageCursorAndOrderingBounds() throws {
        let base: Int64 = 1_700_000_000_000
        let messages = try (1...5).map { number in
            try fixtureMessage(number, receivedUnixMilliseconds: base + Int64(number) * 1000)
        }
        let mechanism = try mailMechanism(messages: messages)
        let adapter = BoundedMailReadAdapter(mechanism: mechanism)

        // A page at the request limit carries a cursor; a short page does not,
        // because a cursor on a short page invites an extra empty round trip and
        // makes "the bucket is exhausted" unrepresentable.
        let firstPage = try adapter.readMail(try mailRequest(limit: 2))
        try require(firstPage.records.count == 2, "The page limit was not honoured")
        let cursor = try requireValue(firstPage.nextCursor, "A full page carried no cursor")
        let secondPage = try adapter.readMail(try mailRequest(limit: 2, cursor: cursor))
        try require(secondPage.records.count == 2, "The cursor did not resume")
        try require(
            Set(firstPage.records.map(\.id)).isDisjoint(with: Set(secondPage.records.map(\.id))),
            "The cursor replayed a record it had already served"
        )
        let lastPage = try adapter.readMail(
            try mailRequest(limit: 2, cursor: try requireValue(secondPage.nextCursor, "no cursor"))
        )
        try require(lastPage.records.count == 1, "The final page is the wrong size")
        try require(lastPage.nextCursor == nil, "A short final page still carried a cursor")

        // The protocol's own page ceiling is inherited, not re-implemented.
        try requireError(.invalidPageLimit) {
            try MailTraversalQuery(
                mailboxID: try fixtureMailbox(),
                window: nil,
                afterProviderKey: nil,
                limit: NativeSourceProtocolV1.maximumPageSize + 1
            )
        }
        // A cursor the protocol admits but the identity alphabet does not is
        // refused rather than coerced.
        let punctuated = try requireValue(
            NativeReadCursor(rawValue: "uid:000001"),
            "The punctuated cursor probe is not a valid protocol cursor"
        )
        try requireError(.mailInvalidIdentityComponent) {
            try adapter.readMail(try mailRequest(cursor: punctuated))
        }

        // Order is the cursor's only guarantee, so a mechanism that returns keys
        // out of order is refused rather than paged over.
        mechanism.setFault(.returnKeysOutOfOrder)
        try requireError(.nonCanonicalOrder) { try adapter.readMail(try mailRequest(limit: 3)) }
        mechanism.setFault(.none)
    }

}
