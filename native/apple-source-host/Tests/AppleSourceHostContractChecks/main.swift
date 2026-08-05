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
        try checkAllThreeSyntheticAdapters()
        try checkSyntheticDenials()
        try checkIntegratedHostBoundary()
        try checkRecurrenceIdentityAndBounds()
        try checkFailClosedWireDecoding()
        try checkProtectedSpoolLifecycle()
        try checkProtectedSpoolFaultsAndBounds()
        try checkProtectedSpoolNamespaceSubstitution()
        try checkProtectedSpoolLockLifecycle()
        print("AppleSourceHostContractChecks: PASS (10 checks)")
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
        let page = NativeReadPage(records: [record], nextCursor: nil)
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
                page: NativeReadPage(records: [record], nextCursor: nil)
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

}
