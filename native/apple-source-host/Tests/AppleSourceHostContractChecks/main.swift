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
        try checkMailAttachmentDescriptorBoundsHoldOffTheWire()
        try checkMailPageCursorAndOrderingBounds()
        try checkCalendarAuthorizationFailsClosedAndIsNotAnEmptyPage()
        try checkCalendarIdentityIsFourLevelInjectiveAndAnchoredToTheOriginal()
        try checkCalendarRecurrenceExpandsAndCancellationIsNotAnAbsence()
        try checkCalendarAllDayAndForeignZoneSemantics()
        try checkCalendarDaylightSavingGapRepeatedHourAndStableWallClock()
        try checkCalendarHorizonBoundsAndHonestTruncation()
        try checkCalendarCancellationSurvivesTheAdapterAndIsNotFilterable()
        try checkCalendarValueBoundsHoldOffTheWire()
        try checkContactsMinimumKeySetIsFrozenAndContentFree()
        try checkContactsIdentityCarriesItsEpochAndIsBranchInjective()
        try checkContactsContainerAndGroupMembershipSurvivesTheRead()
        try checkContactsAuthorizationFailsClosedAndRevocationIsNotAStalePage()
        try checkContactsPageBoundsAndHonestTruncation()
        try checkContactsValueBoundsHoldOffTheWire()
        try checkTasksReadIsBoundedReadOnlyAndConsentGated()
        print("AppleSourceHostContractChecks: PASS (37 checks)")
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
        // **WP-17 changed the expectations in this block, and the change is a
        // correction rather than an accommodation.** Until WP-17 this expander
        // dropped a cancelled occurrence from its output, so this series of four
        // expanded to three and the cancelled slot at `first + 2*day` was simply
        // missing — indistinguishable from an occurrence the series never had.
        // Cancellation and absence are different facts, so the cancelled
        // occurrence is now emitted carrying `.cancelled`, the count is four
        // rather than three, and the missing slot is asserted to be present.
        // The old expectations were `maximumOccurrences: 3`, `count == 3` and
        // `[first, first + day, first + (3 * day)]`.
        let occurrences = try NativeRecurrenceExpander.expand(
            series,
            in: range,
            maximumOccurrences: 4
        )
        try require(occurrences.count == 4, "Cancellation did not preserve bounded expansion")
        try require(
            occurrences.map(\.identity.scheduledStartUnixMilliseconds)
                == [first, first + day, first + (2 * day), first + (3 * day)],
            "Occurrence identity did not remain anchored to scheduled series time"
        )
        try require(
            occurrences.map(\.lifecycle) == [.confirmed, .detached, .cancelled, .confirmed],
            "A cancelled occurrence was reported as an absence, or a detached one as confirmed"
        )
        try require(
            occurrences[2].startUnixMilliseconds == first + (2 * day)
                && occurrences[2].endUnixMilliseconds == first + (2 * day) + 3_600_000,
            "The cancelled occurrence lost the slot it was cancelled from"
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

        let fullQuarantineDirectory = temporaryDirectory("crash-quarantine-count")
        defer { try? FileManager.default.removeItem(at: fullQuarantineDirectory) }
        let fullQuarantineSpool = try ProtectedSpool(
            directory: fullQuarantineDirectory,
            limits: try ProtectedSpoolLimits(
                maximumItems: 1,
                maximumBytes: 32_000,
                maximumPayloadBytes: 4,
                maximumQuarantineItems: 1,
                maximumQuarantineBytes: 32_000
            )
        )
        let retained = try spoolItem("crash-retained", payload: [1])
        try require(
            try fullQuarantineSpool.enqueue(retained) == .enqueued,
            "Crash count fixture did not enqueue"
        )
        try fullQuarantineSpool.quarantine(retained.envelopeID)
        let countResidue = try spoolItem("crash-count", payload: [2])
        try requireSpoolError(.injectedCrash) {
            try fullQuarantineSpool.enqueue(countResidue, fault: .afterTemporarySync)
        }
        try requireSpoolError(.quarantineItemCapacityExceeded) {
            try fullQuarantineSpool.recoverResidues()
        }
        try require(
            try fullQuarantineSpool.inventory().items.contains(where: {
                $0.envelopeID == countResidue.envelopeID && $0.state == .crashResidue
            }),
            "Count-refused recovery did not retain the crash residue"
        )

        let fullQuarantineBytesDirectory = temporaryDirectory("crash-quarantine-bytes")
        defer { try? FileManager.default.removeItem(at: fullQuarantineBytesDirectory) }
        let byteRetained = try spoolItem("crash-bytes-a", payload: [1])
        let retainedSize = try JSONEncoder().encode(byteRetained).count
        let fullQuarantineBytesSpool = try ProtectedSpool(
            directory: fullQuarantineBytesDirectory,
            limits: try ProtectedSpoolLimits(
                maximumItems: 1,
                maximumBytes: 32_000,
                maximumPayloadBytes: 4,
                maximumQuarantineItems: 2,
                maximumQuarantineBytes: Int64(retainedSize)
            )
        )
        try require(
            try fullQuarantineBytesSpool.enqueue(byteRetained) == .enqueued,
            "Crash byte fixture did not enqueue"
        )
        try fullQuarantineBytesSpool.quarantine(byteRetained.envelopeID)
        let byteResidue = try spoolItem("crash-bytes-b", payload: [2])
        try requireSpoolError(.injectedCrash) {
            try fullQuarantineBytesSpool.enqueue(byteResidue, fault: .afterTemporarySync)
        }
        try requireSpoolError(.quarantineByteCapacityExceeded) {
            try fullQuarantineBytesSpool.recoverResidues()
        }
        try require(
            try fullQuarantineBytesSpool.inventory().items.contains(where: {
                $0.envelopeID == byteResidue.envelopeID && $0.state == .crashResidue
            }),
            "Byte-refused recovery did not retain the crash residue"
        )
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
                maximumPayloadBytes: 4,
                maximumQuarantineItems: 1
            )
        )
        try require(
            try capacitySpool.enqueue(try spoolItem("capacity-01", payload: [1])) == .enqueued,
            "Capacity fixture did not enqueue"
        )
        try requireSpoolError(.itemCapacityExceeded) {
            try capacitySpool.enqueue(try spoolItem("capacity-02", payload: [2]))
        }
        try capacitySpool.quarantine(try opaque("capacity-01"))
        try require(
            try capacitySpool.enqueue(try spoolItem("capacity-02", payload: [2])) == .enqueued,
            "Quarantine did not free the bounded pending capacity"
        )
        try requireSpoolError(.quarantineItemCapacityExceeded) {
            try capacitySpool.quarantine(try opaque("capacity-02"))
        }
        try require(
            try capacitySpool.item(try opaque("capacity-02")).envelopeID.rawValue == "capacity-02",
            "Refused quarantine did not retain the pending item"
        )

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
                    try require(
                        destroyStarted.wait(timeout: .now() + 2) == .success,
                        "Peer destruction did not start within its lifecycle bound"
                    )
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
        try require(
            destroyFinished.wait(timeout: .now() + 2) == .success,
            "Peer deinitialization deadlocked against an active spool operation"
        )
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
                    "bodyByteSize": omitted.completeness.bodyByteSize!,
                    "attachmentCount": 0,
                    "attachmentsDescribed": 0,
                ]
            }
        )
    }

    /// Control 4's attachment bound, on the decode path, at runtime.
    ///
    /// **The gap this closes.** `MailAttachmentDescriptor` is where the
    /// attachment ceiling turns into a *label*: over `maximumMailAttachmentBytes`
    /// the descriptor must say `omittedOversize`, because a descriptor that says
    /// `metadataOnly` about a 26 MB attachment tells a consumer the bytes are
    /// fetchable when the host has already decided they are not. The throwing
    /// initialiser enforces that, and until this check existed **nothing
    /// enforced it off the wire**. The architecture guard covering the decode
    /// path asserted that a decoder *existed*; a decoder rewritten to assign its
    /// four fields directly instead of routing through `try self.init(…)`
    /// compiles, keeps that literal string, and admits exactly the mislabelled
    /// descriptor above. That guard now asserts the routing too — but a static
    /// assertion about the shape of a decoder is a weaker thing than decoding
    /// the malformed bytes and requiring the failure, so this is the check that
    /// carries the claim.
    ///
    /// Every case is asserted in both directions. A descriptor that *is*
    /// correctly labelled must still decode, or this check would pass by
    /// refusing everything and would prove nothing about the bound.
    private static func checkMailAttachmentDescriptorBoundsHoldOffTheWire() throws {
        let ceiling = NativeSourceProtocolV1.maximumMailAttachmentBytes
        let described = try MailAttachmentDescriptor(
            id: try opaque("attachment-wire-000"),
            mimeType: "application/octet-stream",
            byteSize: ceiling,
            disposition: .metadataOnly
        )

        // The positive control first: an unmutated descriptor round-trips, so a
        // refusal below is a refusal of the mutation and not of the encoding.
        let roundTripped = try JSONDecoder().decode(
            MailAttachmentDescriptor.self,
            from: try JSONEncoder().encode(described)
        )
        try require(roundTripped == described, "A valid attachment descriptor did not round-trip")

        // Over the ceiling and still labelled fetchable: the mislabel the
        // initialiser refuses, arriving as JSON instead.
        try requireDecodeFailure(
            MailAttachmentDescriptor.self,
            data: try mutatedJSON(described) { object in
                object["byteSize"] = ceiling + 1
            }
        )
        // A negative size is not a size.
        try requireDecodeFailure(
            MailAttachmentDescriptor.self,
            data: try mutatedJSON(described) { object in
                object["byteSize"] = -1
            }
        )
        // The same value, honestly labelled, is admitted — which is what makes
        // the two refusals above statements about the label rather than about
        // the number.
        let labelled = try JSONDecoder().decode(
            MailAttachmentDescriptor.self,
            from: try mutatedJSON(described) { object in
                object["byteSize"] = ceiling + 1
                object["disposition"] = MailAttachmentDisposition.omittedOversize.rawValue
            }
        )
        try require(
            labelled.byteSize == ceiling + 1 && labelled.disposition == .omittedOversize,
            "An oversize attachment labelled omitted_oversize was not admitted off the wire"
        )

        // And nested, which is the shape that actually reaches the host: a
        // descriptor never arrives alone, it arrives inside a record's payload.
        // A record decoder that validated its own fields and took its
        // attachments on trust would pass every check above.
        let identity = MailMessageIdentity(
            mailboxID: try fixtureMailbox(),
            generation: try mailComponent("gen-0001"),
            providerKey: try providerKey(1)
        )
        let content = try MailRecordContent(
            identity: identity,
            receivedUnixMilliseconds: 1_700_000_000_000,
            sentUnixMilliseconds: nil,
            headers: mailHeaders(1),
            body: nil,
            attachments: [described],
            completeness: try MailContentCompleteness(
                bodyIncluded: false,
                bodyByteSize: 0,
                attachmentCount: 1,
                attachmentsDescribed: 1
            )
        )
        try requireDecodeFailure(
            MailRecordContent.self,
            data: try mutatedJSON(content) { object in
                var attachments = try jsonDictionaryArray(object["attachments"])
                attachments[0]["byteSize"] = ceiling + 1
                object["attachments"] = attachments
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


    // MARK: - WP-17 — the calendar adapter
    //
    // Level of proof for everything below: **Swift runtime, in one process, over
    // a mechanism seam driven by a store this harness seeds itself.** No
    // EventKit event store is constructed anywhere in this repository, no TCC grant is
    // held or requested, and no calendar belonging to anyone is read. What the
    // seam buys is that every refusal lives in `BoundedCalendarReadAdapter`, so
    // these properties hold for any mechanism satisfying it.
    //
    // Every fixture value is obviously synthetic: `Calendar Beta`, `Event
    // Alpha`, `account-alpha`. There is no title, location, attendee or note
    // field anywhere in the calendar record types, so there is nothing for a
    // real one to be mistaken for.

    private static func component(_ value: String) throws -> CalendarIdentityComponent {
        try requireValue(
            CalendarIdentityComponent(rawValue: value),
            "The probe identity component \(value) is not admissible"
        )
    }

    private static func bucket(_ account: String, _ calendar: String) throws
        -> CalendarBucketIdentity {
        CalendarBucketIdentity(
            accountKey: try component(account),
            calendarKey: try component(calendar)
        )
    }

    private static func seriesIdentity(_ account: String, _ calendar: String, _ series: String)
        throws -> CalendarSeriesIdentity {
        CalendarSeriesIdentity(
            bucket: try bucket(account, calendar),
            seriesKey: try component(series)
        )
    }

    /// The instant a local wall clock names, or a harness failure if it names
    /// none. Used to seed fixtures at real local times rather than at instants
    /// somebody computed by hand and cannot re-derive.
    private static func instant(
        year: Int,
        month: Int,
        day: Int,
        hour: Int,
        minute: Int,
        zone identifier: String
    ) throws -> Int64 {
        let zone = try CalendarZone.resolve(identifier)
        let wallClock = try CalendarWallClock(
            date: try CalendarDate(year: year, month: month, day: day),
            hour: hour,
            minute: minute,
            second: 0
        )
        switch CalendarZone.resolve(wallClock, in: zone) {
        case let .unique(value):
            return value
        case let .ambiguous(earlier, _):
            return earlier
        case .skipped:
            throw ContractCheckError.failed(
                "The probe wall clock does not exist in \(identifier)"
            )
        }
    }

    private static let calendarZone = "America/New_York"

    /// A five-occurrence 09:00 weekday-shaped series in `Calendar Beta`, with one
    /// occurrence moved and one cancelled.
    private static func probeSeries() throws -> CalendarRecurringSeries {
        let firstStart = try instant(
            year: 2026, month: 3, day: 3, hour: 9, minute: 0, zone: calendarZone
        )
        let movedOriginal = try instant(
            year: 2026, month: 3, day: 4, hour: 9, minute: 0, zone: calendarZone
        )
        let cancelledOriginal = try instant(
            year: 2026, month: 3, day: 6, hour: 9, minute: 0, zone: calendarZone
        )
        _ = firstStart
        return try CalendarRecurringSeries(
            identity: try seriesIdentity("account-alpha", "calendar-beta", "series-alpha"),
            timezoneIdentifier: calendarZone,
            firstWallClock: try CalendarWallClock(
                date: try CalendarDate(year: 2026, month: 3, day: 3),
                hour: 9,
                minute: 0,
                second: 0
            ),
            durationSeconds: 1800,
            intervalDays: 1,
            occurrenceCount: 5,
            exceptions: [
                CalendarRecurrenceException(
                    originalStartUnixMilliseconds: movedOriginal,
                    replacement: try CalendarTimedInterval.at(
                        startUnixMilliseconds: movedOriginal + 7_200_000,
                        endUnixMilliseconds: movedOriginal + 9_000_000,
                        timezoneIdentifier: calendarZone
                    )
                ),
                CalendarRecurrenceException(
                    originalStartUnixMilliseconds: cancelledOriginal,
                    replacement: nil
                ),
            ],
            lastModifiedUnixMilliseconds: 1_770_000_000_000
        )
    }

    /// A whole-day occurrence, represented as dates and carrying no instant.
    private static func probeAllDayOccurrence() throws -> CalendarOccurrence {
        let day = try CalendarDate(year: 2026, month: 3, day: 5)
        return try CalendarOccurrence(
            identity: CalendarOccurrenceIdentity(
                series: try seriesIdentity("account-alpha", "calendar-beta", "series-whole-day"),
                originalStartUnixMilliseconds: day.identityAnchorUnixMilliseconds
            ),
            lifecycle: .confirmed,
            schedule: .allDay(try CalendarAllDaySpan(firstDay: day, lastDay: day)),
            lastModifiedUnixMilliseconds: 1_770_000_000_001
        )
    }

    /// One occurrence in a *different* calendar, so that a mechanism answering
    /// with somebody else's calendar can be caught rather than assumed away.
    private static func probeOtherCalendarOccurrence() throws -> CalendarOccurrence {
        let start = try instant(
            year: 2026, month: 3, day: 4, hour: 14, minute: 0, zone: calendarZone
        )
        return try CalendarOccurrence(
            identity: CalendarOccurrenceIdentity(
                series: try seriesIdentity("account-alpha", "calendar-gamma", "series-gamma"),
                originalStartUnixMilliseconds: start
            ),
            lifecycle: .confirmed,
            schedule: .timed(
                try CalendarTimedInterval.at(
                    startUnixMilliseconds: start,
                    endUnixMilliseconds: start + 1_800_000,
                    timezoneIdentifier: calendarZone
                )
            ),
            lastModifiedUnixMilliseconds: 1_770_000_000_002
        )
    }

    private static func calendarDescriptor(
        publishesOriginalOccurrenceStart: Bool = true
    ) -> CalendarMechanismDescriptor {
        CalendarMechanismDescriptor(
            mechanism: .fixtureSeeded,
            publishesOriginalOccurrenceStart: publishesOriginalOccurrenceStart,
            requiresOperatorConsent: false
        )
    }

    private static func calendarMechanism(
        occurrences: [CalendarOccurrence],
        publishesOriginalOccurrenceStart: Bool = true
    ) throws -> FixtureCalendarMechanism {
        try FixtureCalendarMechanism(
            descriptor: calendarDescriptor(
                publishesOriginalOccurrenceStart: publishesOriginalOccurrenceStart
            ),
            accounts: [
                CalendarAccountDescriptor(
                    accountKey: try component("account-alpha"),
                    displayLabel: "Account Alpha"
                )
            ],
            calendars: [
                CalendarBucketDescriptor(
                    identity: try bucket("account-alpha", "calendar-beta"),
                    displayLabel: "Calendar Beta",
                    isSelectable: true
                ),
                CalendarBucketDescriptor(
                    identity: try bucket("account-alpha", "calendar-gamma"),
                    displayLabel: "Calendar Gamma",
                    isSelectable: true
                ),
            ],
            occurrences: occurrences
        )
    }

    /// One occurrence in `Calendar Beta` but well outside every window this
    /// harness asks for, so that a mechanism which ignores its window has
    /// something to return that the adapter can catch. Without it the
    /// `ignoreTheWindow` fault is undetectable and the guard against it is
    /// vacuous.
    private static func probeOutOfWindowOccurrence() throws -> CalendarOccurrence {
        let start = try instant(
            year: 2027, month: 1, day: 15, hour: 9, minute: 0, zone: calendarZone
        )
        return try CalendarOccurrence(
            identity: CalendarOccurrenceIdentity(
                series: try seriesIdentity("account-alpha", "calendar-beta", "series-later"),
                originalStartUnixMilliseconds: start
            ),
            lifecycle: .confirmed,
            schedule: .timed(
                try CalendarTimedInterval.at(
                    startUnixMilliseconds: start,
                    endUnixMilliseconds: start + 1_800_000,
                    timezoneIdentifier: calendarZone
                )
            ),
            lastModifiedUnixMilliseconds: 1_770_000_000_003
        )
    }

    private static func probeOccurrences() throws -> [CalendarOccurrence] {
        try CalendarSeriesExpander.expand(try probeSeries())
            + [
                try probeAllDayOccurrence(),
                try probeOtherCalendarOccurrence(),
                try probeOutOfWindowOccurrence(),
            ]
    }

    private static func calendarRequest(
        calendar: String = "calendar-beta",
        limit: Int = 100,
        cursor: NativeReadCursor? = nil,
        bounded: Bool = true
    ) throws -> NativeReadRequest {
        let range = try NativeTimeRange(
            startUnixMilliseconds: try instant(
                year: 2026, month: 3, day: 1, hour: 0, minute: 0, zone: "UTC"
            ),
            endUnixMilliseconds: try instant(
                year: 2026, month: 3, day: 20, hour: 0, minute: 0, zone: "UTC"
            )
        )
        return try NativeReadRequest(
            bucketID: try (bucket("account-alpha", calendar)).recordIdentifier(),
            timeRange: bounded ? range : nil,
            cursor: cursor,
            limit: limit
        )
    }

    private static func decodedOccurrence(_ record: NativeSourceRecord) throws
        -> CalendarOccurrence {
        try JSONDecoder().decode(CalendarOccurrence.self, from: Data(record.payload))
    }

    /// Control 2. Authorization fails closed, before any read, and a refusal is
    /// a **different value** from a successful read of an empty calendar.
    ///
    /// This is the distinction the campaign has enforced since WP-09 and it is
    /// the one a calendar gets wrong most expensively: a page of zero records
    /// means "nothing is scheduled", and returning that when the real answer is
    /// "we were never allowed to look" is a lie a scheduler will act on.
    private static func checkCalendarAuthorizationFailsClosedAndIsNotAnEmptyPage() throws {
        let mechanism = try calendarMechanism(occurrences: try probeOccurrences())
        let adapter = BoundedCalendarReadAdapter(mechanism: mechanism)

        try require(
            CalendarAuthorizationState.allCases.count == 4,
            "The authorization vocabulary is no longer the four states EventKit distinguishes"
        )

        // Every state that is not `authorized` stops the adapter before it reads,
        // and that is measured by the fixture's own call counters rather than
        // argued from the adapter's source.
        for state in CalendarAuthorizationState.allCases where state != .authorized {
            mechanism.setAuthorization(state)
            mechanism.resetCallCounters()
            try requireProviderFailure(.permissionDenied) { try adapter.discoverCalendars() }
            try requireProviderFailure(.permissionDenied) {
                try adapter.readCalendar(try calendarRequest())
            }
            try require(
                mechanism.readCalls == 0,
                "The adapter made \(mechanism.readCalls) reads with authorization \(state.rawValue)"
            )
            try require(
                mechanism.authorizationCalls == 2,
                "Authorization was not consulted once per operation"
            )
        }

        // The other half, and the half that makes the first one mean something:
        // an authorized read of a calendar that genuinely holds nothing produces
        // a *page*. A refusal produces no page at all — the call above cannot
        // return one, because it throws. Empty and unavailable are therefore
        // different kinds of thing and not two spellings of one.
        mechanism.setAuthorization(.authorized)
        let empty = try calendarMechanism(occurrences: [])
        let emptyPage = try BoundedCalendarReadAdapter(mechanism: empty)
            .readCalendar(try calendarRequest())
        try require(
            emptyPage.records.isEmpty && emptyPage.nextCursor == nil,
            "An empty calendar did not read as an empty page"
        )

        let snapshot = try adapter.discoverCalendars()
        try require(snapshot.kind == .calendar, "Calendar discovery returned the wrong kind")
        try require(snapshot.accounts.count == 1, "Calendar discovery lost the account")
        try require(snapshot.buckets.count == 2, "Calendar discovery lost a calendar")
        try require(
            snapshot.buckets.allSatisfy { bucket in
                snapshot.accounts.contains { $0.id == bucket.accountID }
            },
            "A discovered calendar names an account discovery did not report"
        )

        // A mechanism that cannot name where an occurrence was originally
        // scheduled cannot anchor an occurrence identity, and is refused rather
        // than read from with a best guess.
        let unanchored = try calendarMechanism(
            occurrences: try probeOccurrences(),
            publishesOriginalOccurrenceStart: false
        )
        try requireError(.calendarOriginalStartUnavailable) {
            try BoundedCalendarReadAdapter(mechanism: unanchored)
                .readCalendar(try calendarRequest())
        }
    }

    /// Control 1. Four levels, injective composition, and an occurrence key
    /// anchored to the start the series scheduled rather than the start the
    /// occurrence currently has.
    private static func checkCalendarIdentityIsFourLevelInjectiveAndAnchoredToTheOriginal() throws {
        let account = CalendarAccountIdentity(accountKey: try component("account-alpha"))
        let bucketIdentity = try bucket("account-alpha", "calendar-beta")
        let series = try seriesIdentity("account-alpha", "calendar-beta", "series-alpha")
        let occurrence = CalendarOccurrenceIdentity(
            series: series,
            originalStartUnixMilliseconds: 1_770_000_000_000
        )

        let identifiers = [
            try account.recordIdentifier().rawValue,
            try bucketIdentity.recordIdentifier().rawValue,
            try series.recordIdentifier().rawValue,
            try occurrence.recordIdentifier().rawValue,
        ]
        try require(
            Set(identifiers).count == 4,
            "Two of the four identity levels compose to the same identifier"
        )
        try require(
            identifiers.map { $0.filter { $0 == ":" }.count } == [0, 1, 2, 3],
            "The identity levels are no longer distinguished by their separator count"
        )
        try require(
            identifiers[3].hasPrefix(identifiers[2] + ":")
                && identifiers[2].hasPrefix(identifiers[1] + ":")
                && identifiers[1].hasPrefix(identifiers[0] + ":"),
            "An identity level is no longer a prefix of the level below it"
        )

        // Injectivity. The separator is excluded from the component alphabet, so
        // two different component tuples cannot join to one identifier — the
        // classic collision, where a hyphen is moved across the boundary, is not
        // representable.
        try require(
            CalendarIdentityComponent(rawValue: "calendar:beta") == nil,
            "A colon in an identity component would make composition ambiguous"
        )
        let left = try seriesIdentity("account-alpha", "calendar-beta", "series-alpha")
        let right = try seriesIdentity("account", "alpha-calendar", "beta-series-alpha")
        try require(
            try left.recordIdentifier() != right.recordIdentifier(),
            "Two distinct series composed to one identifier"
        )

        // **The anchor.** A detached occurrence moved two hours later keeps the
        // identifier it had before the move; a *different* occurrence that
        // genuinely starts at the moved time does not share it. Anchoring to the
        // actual start instead would make every move read as a delete and a
        // create.
        let moved = try CalendarOccurrence(
            identity: occurrence,
            lifecycle: .detached,
            schedule: .timed(
                try CalendarTimedInterval.at(
                    startUnixMilliseconds: 1_770_000_000_000 + 7_200_000,
                    endUnixMilliseconds: 1_770_000_000_000 + 9_000_000,
                    timezoneIdentifier: calendarZone
                )
            ),
            lastModifiedUnixMilliseconds: 1
        )
        try require(
            try moved.identity.recordIdentifier() == occurrence.recordIdentifier(),
            "Moving an occurrence changed its identity; the move now reads as a delete and a create"
        )
        let unrelated = CalendarOccurrenceIdentity(
            series: series,
            originalStartUnixMilliseconds: 1_770_000_000_000 + 7_200_000
        )
        try require(
            try unrelated.recordIdentifier() != moved.identity.recordIdentifier(),
            "A moved occurrence collided with an occurrence scheduled at its new time"
        )

        // The occurrence key is order-preserving, which is what makes the cursor
        // resume in the right place. Raw decimal rendering is not: `-1` sorts
        // before `-2` and after `10`.
        let instants: [Int64] = [Int64.min, -86_400_000, -1, 0, 1, 1_770_000_000_000, Int64.max]
        let keys = instants.map(CalendarIdentityComposition.orderPreservingKey)
        try require(keys == keys.sorted(), "The occurrence key is no longer order-preserving")
        try require(
            Set(keys.map(\.count)).count == 1,
            "The occurrence key is no longer fixed-width, so lexicographic order is not numeric order"
        )

        // Refused, never trimmed. Four maximum-length components genuinely
        // exceed the opaque identifier's ceiling, and a trimmed identity is the
        // one truncation with no honest partial form: it aliases two occurrences.
        let long = String(
            repeating: "a",
            count: NativeSourceProtocolV1.maximumCalendarIdentityComponentBytes
        )
        let longOccurrence = CalendarOccurrenceIdentity(
            series: CalendarSeriesIdentity(
                bucket: CalendarBucketIdentity(
                    accountKey: try component(long),
                    calendarKey: try component(long)
                ),
                seriesKey: try component(long)
            ),
            originalStartUnixMilliseconds: 0
        )
        try requireError(.calendarIdentityTooLong) { try longOccurrence.recordIdentifier() }
        try require(
            CalendarIdentityComponent(rawValue: long + "a") == nil,
            "The identity component ceiling no longer refuses an over-long component"
        )

        // A bucket identifier is read back into its two levels, or refused. A
        // guessed decomposition files an occurrence under the wrong account.
        let parsed = try CalendarBucketIdentity(bucketID: try bucketIdentity.recordIdentifier())
        try require(parsed == bucketIdentity, "A bucket identifier did not round-trip")
        for malformed in ["account-alpha", "a:b:c"] {
            let identifier = try requireValue(
                NativeSourceOpaqueID(rawValue: malformed),
                "The malformed bucket probe is not a valid opaque identifier"
            )
            try requireError(.calendarInvalidIdentityComponent) {
                try CalendarBucketIdentity(bucketID: identifier)
            }
        }
    }

    /// Control 3 and control 4. A rule expands into occurrences, exceptions and
    /// detached instances — and a cancellation is expanded into an occurrence
    /// that says it was cancelled, never into a gap.
    private static func checkCalendarRecurrenceExpandsAndCancellationIsNotAnAbsence() throws {
        let series = try probeSeries()
        let occurrences = try CalendarSeriesExpander.expand(series)

        try require(
            occurrences.count == 5,
            "The expansion produced \(occurrences.count) occurrences; a cancelled one was dropped"
        )
        try require(
            occurrences.map(\.lifecycle)
                == [.confirmed, .detached, .confirmed, .cancelled, .confirmed],
            "The expansion lost a lifecycle state"
        )

        // The cancelled occurrence is present, is marked, and still carries the
        // slot it was cancelled from. Absence would carry none of that.
        let cancelled = occurrences[3]
        guard case let .timed(cancelledInterval) = cancelled.schedule else {
            throw ContractCheckError.failed("The cancelled occurrence lost its schedule")
        }
        try require(
            cancelledInterval.startUnixMilliseconds
                == cancelled.identity.originalStartUnixMilliseconds,
            "The cancelled occurrence lost the slot it was cancelled from"
        )

        // The detached occurrence moved, and kept its identity.
        let detached = occurrences[1]
        guard case let .timed(detachedInterval) = detached.schedule else {
            throw ContractCheckError.failed("The detached occurrence lost its schedule")
        }
        try require(
            detachedInterval.startUnixMilliseconds
                == detached.identity.originalStartUnixMilliseconds + 7_200_000,
            "The detached occurrence did not move"
        )
        try require(
            detached.identity.series == series.identity,
            "The detached occurrence left its series"
        )
        try require(
            Set(try occurrences.map { try $0.identity.recordIdentifier().rawValue }).count == 5,
            "Two expanded occurrences share an identifier"
        )

        // An exception that names a start the series never scheduled is a
        // statement about an occurrence that does not exist. Accepting it would
        // leave the series and its exception list disagreeing silently.
        let phantom = try CalendarRecurringSeries(
            identity: series.identity,
            timezoneIdentifier: series.timezoneIdentifier,
            firstWallClock: series.firstWallClock,
            durationSeconds: series.durationSeconds,
            intervalDays: series.intervalDays,
            occurrenceCount: series.occurrenceCount,
            exceptions: [
                CalendarRecurrenceException(
                    originalStartUnixMilliseconds: 1,
                    replacement: nil
                )
            ],
            lastModifiedUnixMilliseconds: 0
        )
        try requireError(.calendarLifecycleInconsistent) {
            try CalendarSeriesExpander.expand(phantom)
        }

        // The expansion ceiling refuses rather than truncating.
        try requireError(.recurrenceLimitExceeded) {
            try CalendarRecurringSeries(
                identity: series.identity,
                timezoneIdentifier: series.timezoneIdentifier,
                firstWallClock: series.firstWallClock,
                durationSeconds: 0,
                intervalDays: 1,
                occurrenceCount: NativeSourceProtocolV1.maximumCalendarSeriesOccurrences + 1,
                exceptions: [],
                lastModifiedUnixMilliseconds: 0
            )
        }

        // A confirmed occurrence that has moved is an identity that has silently
        // re-pointed, and it cannot be built.
        try requireError(.calendarLifecycleInconsistent) {
            try CalendarOccurrence(
                identity: CalendarOccurrenceIdentity(
                    series: series.identity,
                    originalStartUnixMilliseconds: 1_770_000_000_000
                ),
                lifecycle: .confirmed,
                schedule: .timed(
                    try CalendarTimedInterval.at(
                        startUnixMilliseconds: 1_770_000_003_600,
                        endUnixMilliseconds: 1_770_000_007_200,
                        timezoneIdentifier: "UTC"
                    )
                ),
                lastModifiedUnixMilliseconds: 0
            )
        }
    }

    /// Control 5, first half: an all-day event stays a whole calendar day for
    /// every reader, and an event in a foreign zone keeps that zone.
    private static func checkCalendarAllDayAndForeignZoneSemantics() throws {
        let day = try CalendarDate(year: 2026, month: 3, day: 5)
        let span = try CalendarAllDaySpan(firstDay: day, lastDay: day)

        // The representation is dates. There is no start instant on the type to
        // read, so "midnight local" is not a value this span can take, in any
        // zone, for any reader.
        try require(
            span.firstDay == day && span.lastDay == day,
            "The all-day span lost its dates"
        )

        // Its window bounds are the widest offsets any zone on Earth uses,
        // applied outward. A reader in Kiritimati and a reader in Baker Island
        // both see the day; neither can exclude it by being in a different zone.
        try require(
            span.earliestPossibleStartUnixMilliseconds
                == day.identityAnchorUnixMilliseconds - (14 * 3_600_000),
            "The all-day span narrowed its eastward bound"
        )
        try require(
            span.latestPossibleEndUnixMilliseconds
                == day.identityAnchorUnixMilliseconds + 86_400_000 + (12 * 3_600_000),
            "The all-day span narrowed its westward bound"
        )
        let schedule = CalendarSchedule.allDay(span)
        try require(schedule.isAllDay, "An all-day schedule stopped reporting itself as one")
        for zoneOffsetHours in [-12, -5, 0, 1, 9, 14] {
            let midnightThere =
                day.identityAnchorUnixMilliseconds - Int64(zoneOffsetHours) * 3_600_000
            try require(
                schedule.overlaps(
                    startUnixMilliseconds: midnightThere,
                    endUnixMilliseconds: midnightThere + 86_399_999
                ),
                "The all-day event fell out of its own day for a reader at UTC\(zoneOffsetHours)"
            )
        }

        // An all-day occurrence must be anchored to a whole day. Anchoring one to
        // some mid-afternoon instant is a value that has already lost the fact
        // that a whole day was meant.
        try requireError(.calendarLifecycleInconsistent) {
            try CalendarOccurrence(
                identity: CalendarOccurrenceIdentity(
                    series: try seriesIdentity("account-alpha", "calendar-beta", "series-whole-day"),
                    originalStartUnixMilliseconds: day.identityAnchorUnixMilliseconds + 1
                ),
                lifecycle: .detached,
                schedule: schedule,
                lastModifiedUnixMilliseconds: 0
            )
        }

        // A foreign zone. The same instant shows a different wall clock in Paris
        // and in New York, and the interval keeps the event's zone rather than
        // the reader's — the expected values below are Paris values, so a host
        // zone leaking in cannot pass this.
        let start = try instant(year: 2026, month: 6, day: 15, hour: 14, minute: 30, zone: "Europe/Paris")
        let paris = try CalendarTimedInterval.at(
            startUnixMilliseconds: start,
            endUnixMilliseconds: start + 3_600_000,
            timezoneIdentifier: "Europe/Paris"
        )
        try require(
            paris.startWallClock.hour == 14 && paris.startWallClock.minute == 30,
            "A Paris event did not keep Paris local time"
        )
        try require(
            paris.endWallClock.hour == 15 && paris.endWallClock.minute == 30,
            "A Paris event's end did not keep Paris local time"
        )
        let newYork = try CalendarTimedInterval.at(
            startUnixMilliseconds: start,
            endUnixMilliseconds: start + 3_600_000,
            timezoneIdentifier: calendarZone
        )
        try require(
            newYork.startWallClock.hour == 8,
            "The same instant did not render differently in a different zone"
        )
        try require(
            paris.startUnixMilliseconds == newYork.startUnixMilliseconds,
            "Two renderings of one instant disagreed about the instant"
        )

        // The instant is the authority and the wall clock is verified against it,
        // so a declared pair that disagrees is refused rather than believed.
        try requireError(.calendarScheduleInconsistent) {
            try CalendarTimedInterval(
                startUnixMilliseconds: start,
                endUnixMilliseconds: start + 3_600_000,
                timezoneIdentifier: "Europe/Paris",
                startWallClock: try CalendarWallClock(
                    date: try CalendarDate(year: 2026, month: 6, day: 15),
                    hour: 9,
                    minute: 30,
                    second: 0
                ),
                endWallClock: paris.endWallClock
            )
        }
        try requireError(.calendarUnknownTimezone) {
            try CalendarTimedInterval.at(
                startUnixMilliseconds: start,
                endUnixMilliseconds: start,
                timezoneIdentifier: "Nowhere/Invented"
            )
        }

        // Both schedule shapes survive the wire without becoming the other one.
        for value in [CalendarSchedule.allDay(span), .timed(paris)] {
            let round = try JSONDecoder().decode(
                CalendarSchedule.self,
                from: try JSONEncoder().encode(value)
            )
            try require(round == value, "A schedule did not round-trip through JSON")
        }
    }

    /// Control 5, second half: the two DST answers that are not "an instant",
    /// and a series whose local time is stable while its instants are not.
    private static func checkCalendarDaylightSavingGapRepeatedHourAndStableWallClock() throws {
        let zone = try CalendarZone.resolve(calendarZone)

        // Spring forward, 2026-03-08. 02:30 local does not happen.
        let gap = try CalendarWallClock(
            date: try CalendarDate(year: 2026, month: 3, day: 8),
            hour: 2,
            minute: 30,
            second: 0
        )
        guard case .skipped = CalendarZone.resolve(gap, in: zone) else {
            throw ContractCheckError.failed(
                "A wall clock inside the spring-forward gap resolved to an instant"
            )
        }
        // And a series defined at that local time is refused rather than shifted
        // to a nearby instant nobody can tell from a real one.
        try requireError(.calendarScheduleInconsistent) {
            try CalendarSeriesExpander.expand(
                try CalendarRecurringSeries(
                    identity: try seriesIdentity("account-alpha", "calendar-beta", "series-gap"),
                    timezoneIdentifier: calendarZone,
                    firstWallClock: try CalendarWallClock(
                        date: try CalendarDate(year: 2026, month: 3, day: 7),
                        hour: 2,
                        minute: 30,
                        second: 0
                    ),
                    durationSeconds: 1800,
                    intervalDays: 1,
                    occurrenceCount: 3,
                    exceptions: [],
                    lastModifiedUnixMilliseconds: 0
                )
            )
        }

        // Fall back, 2026-11-01. 01:30 local happens twice, an hour apart, at two
        // different offsets.
        let repeated = try CalendarWallClock(
            date: try CalendarDate(year: 2026, month: 11, day: 1),
            hour: 1,
            minute: 30,
            second: 0
        )
        guard case let .ambiguous(earlier, later) = CalendarZone.resolve(repeated, in: zone) else {
            throw ContractCheckError.failed(
                "The fall-back repeated hour resolved to a single instant"
            )
        }
        try require(
            later - earlier == 3_600_000,
            "The two instants of the repeated hour are not an hour apart"
        )
        try require(
            CalendarZone.offsetSeconds(atUnixMilliseconds: earlier, in: zone)
                - CalendarZone.offsetSeconds(atUnixMilliseconds: later, in: zone) == 3600,
            "The repeated hour's two instants are at the same UTC offset"
        )
        try require(
            CalendarZone.wallClock(atUnixMilliseconds: earlier, in: zone) == repeated
                && CalendarZone.wallClock(atUnixMilliseconds: later, in: zone) == repeated,
            "One of the repeated hour's instants does not show the wall clock it was resolved from"
        )
        try require(
            CalendarSeriesExpander.ambiguousWallClockTakesTheEarlierInstant,
            "The ambiguous-wall-clock choice is no longer stated"
        )

        // **The load-bearing case.** A 09:00 series is stable in local time
        // across a DST transition, so its UTC instants are *not* evenly spaced.
        // A fixed-millisecond expander walks such a series an hour off for half
        // the year, which is why this expander is defined on wall clocks.
        for (month, day, transitionStep) in [(3, 7, 82_800_000), (10, 31, 90_000_000)] {
            let series = try CalendarRecurringSeries(
                identity: try seriesIdentity("account-alpha", "calendar-beta", "series-dst"),
                timezoneIdentifier: calendarZone,
                firstWallClock: try CalendarWallClock(
                    date: try CalendarDate(year: 2026, month: month, day: day),
                    hour: 9,
                    minute: 0,
                    second: 0
                ),
                durationSeconds: 1800,
                intervalDays: 1,
                occurrenceCount: 3,
                exceptions: [],
                lastModifiedUnixMilliseconds: 0
            )
            let expanded = try CalendarSeriesExpander.expand(series)
            let starts = expanded.map(\.identity.originalStartUnixMilliseconds)
            try require(
                starts[1] - starts[0] == Int64(transitionStep),
                "A wall-clock series stepped \(starts[1] - starts[0]) ms across a DST transition"
            )
            try require(
                starts[2] - starts[1] == 86_400_000,
                "A wall-clock series stopped stepping a whole day away from the transition"
            )
            try require(
                expanded.allSatisfy { occurrence in
                    guard case let .timed(interval) = occurrence.schedule else { return false }
                    return interval.startWallClock.hour == 9 && interval.startWallClock.minute == 0
                },
                "A wall-clock series lost its local time across a DST transition"
            )
        }
    }

    /// The bounded horizon, honest truncation, and every re-check the adapter
    /// makes of a mechanism that could be wrong.
    private static func checkCalendarHorizonBoundsAndHonestTruncation() throws {
        let mechanism = try calendarMechanism(occurrences: try probeOccurrences())
        let adapter = BoundedCalendarReadAdapter(mechanism: mechanism)

        // The horizon refuses rather than narrowing, on the initialiser and on
        // the decode path.
        let overWide = try NativeTimeRange(
            startUnixMilliseconds: 0,
            endUnixMilliseconds: Int64(NativeSourceProtocolV1.maximumCalendarHorizonDays)
                * 86_400_000 + 1
        )
        try requireError(.calendarHorizonExceeded) { try CalendarHorizonWindow(overWide) }
        try requireDecodeFailure(
            CalendarHorizonWindow.self,
            data: try mutatedJSON(
                try CalendarHorizonWindow(startUnixMilliseconds: 0, endUnixMilliseconds: 0)
            ) { object in
                object["endUnixMilliseconds"] =
                    Int64(NativeSourceProtocolV1.maximumCalendarHorizonDays) * 86_400_000 + 1
            }
        )
        // A calendar has no natural end, so an unbounded read is not a wider
        // read — it is the unbounded enumeration the horizon exists to prevent.
        try requireError(.calendarHorizonExceeded) {
            try adapter.readCalendar(try calendarRequest(bounded: false))
        }

        // Truncation is declared, and the declaration is cross-checked. Paging
        // the whole calendar in twos must produce every occurrence exactly once.
        var collected: [String] = []
        var cursor: NativeReadCursor?
        var pages = 0
        repeat {
            let page = try adapter.readCalendar(try calendarRequest(limit: 2, cursor: cursor))
            pages += 1
            collected.append(contentsOf: page.records.map(\.id.rawValue))
            cursor = page.nextCursor
            try require(pages <= 8, "Paging the fixture calendar did not terminate")
        } while cursor != nil
        let whole = try adapter.readCalendar(try calendarRequest())
        try require(
            collected == whole.records.map(\.id.rawValue),
            "Paging in twos did not reproduce the single-page read exactly"
        )
        try require(
            Set(collected).count == collected.count,
            "Paging returned an occurrence twice"
        )
        try require(whole.nextCursor == nil, "A complete page still declared more available")

        // Now the faults, which is how the adapter's re-checks are exercised
        // rather than merely written.
        for (fault, expected) in [
            (FixtureCalendarFault.declareWholeStoreEnumeration, NativeSourceContractError
                .calendarUnboundedEnumeration),
            (.ignoreTheWindow, .calendarHorizonViolated),
            (.returnKeysOutOfOrder, .nonCanonicalOrder),
            (.claimMoreAvailableWithoutFillingThePage, .calendarTruncationUndeclared),
            (.leakAnotherCalendarsOccurrence, .unknownBucket),
        ] {
            mechanism.setFault(fault)
            try requireError(expected) {
                try adapter.readCalendar(try calendarRequest())
            }
        }
        mechanism.setFault(.none)

        // The page and cursor ceilings are the protocol's, not this adapter's,
        // and they still refuse rather than clamp.
        try requireError(.invalidPageLimit) {
            try calendarRequest(limit: NativeSourceProtocolV1.maximumPageSize + 1)
        }
        try require(
            NativeReadCursor(
                rawValue: String(
                    repeating: "c",
                    count: NativeSourceProtocolV1.maximumCursorBytes + 1
                )
            ) == nil,
            "The frozen cursor ceiling no longer refuses an over-long cursor"
        )
    }

    /// Control 4 at the adapter boundary, measured rather than asserted.
    ///
    /// The mechanism-level fault that drops cancellations is **not detectable by
    /// the adapter** — nothing downstream of a source can tell a suppressed
    /// cancellation from an occurrence that never existed — so this compares the
    /// two reads directly. The suppressed page is well-formed, passes every
    /// check, and is missing a fact. That is the whole argument for representing
    /// a cancellation instead of omitting it.
    private static func checkCalendarCancellationSurvivesTheAdapterAndIsNotFilterable() throws {
        let mechanism = try calendarMechanism(occurrences: try probeOccurrences())
        let adapter = BoundedCalendarReadAdapter(mechanism: mechanism)

        let honest = try adapter.readCalendar(try calendarRequest())
        let cancelledRecords = try honest.records.filter {
            try decodedOccurrence($0).lifecycle == .cancelled
        }
        try require(
            cancelledRecords.count == 1,
            "The adapter carried \(cancelledRecords.count) cancelled occurrences; it must carry one"
        )
        let cancelled = try decodedOccurrence(cancelledRecords[0])
        guard case let .timed(interval) = cancelled.schedule else {
            throw ContractCheckError.failed("The cancelled occurrence lost its schedule")
        }
        try require(
            interval.startUnixMilliseconds == cancelled.identity.originalStartUnixMilliseconds,
            "The cancelled occurrence no longer names the slot it was cancelled from"
        )
        try require(
            cancelledRecords[0].kind == .calendar,
            "A calendar record was admitted under another source kind"
        )

        mechanism.setFault(.dropCancelledOccurrences)
        let suppressed = try adapter.readCalendar(try calendarRequest())
        mechanism.setFault(.none)
        try require(
            suppressed.records.count == honest.records.count - 1,
            "Suppressing the cancellation did not remove exactly one record"
        )
        try require(
            Set(honest.records.map(\.id.rawValue))
                .subtracting(suppressed.records.map(\.id.rawValue))
                == [cancelledRecords[0].id.rawValue],
            "The suppressed page differs from the honest one somewhere other than the cancellation"
        )
    }

    /// Every calendar invariant, re-checked on the decode path.
    ///
    /// WP-15's lesson and WP-16's correction, applied to WP-17: a bound that
    /// exists only on an initialiser holds for values built in Swift and not for
    /// the same values arriving as JSON, which is the shape a host is actually
    /// handed. A decoder that *exists* is not a decoder that *validates*, so each
    /// case below is a malformed document that must be refused.
    private static func checkCalendarValueBoundsHoldOffTheWire() throws {
        let series = try seriesIdentity("account-alpha", "calendar-beta", "series-alpha")
        let start: Int64 = 1_770_000_000_000
        let confirmed = try CalendarOccurrence(
            identity: CalendarOccurrenceIdentity(
                series: series,
                originalStartUnixMilliseconds: start
            ),
            lifecycle: .confirmed,
            schedule: .timed(
                try CalendarTimedInterval.at(
                    startUnixMilliseconds: start,
                    endUnixMilliseconds: start + 1_800_000,
                    timezoneIdentifier: calendarZone
                )
            ),
            lastModifiedUnixMilliseconds: 1
        )

        // A confirmed occurrence whose identity no longer matches where it sits.
        try requireDecodeFailure(
            CalendarOccurrence.self,
            data: try mutatedJSON(confirmed) { object in
                var identity = try jsonDictionary(object["identity"])
                identity["originalStartUnixMilliseconds"] = start + 3_600_000
                object["identity"] = identity
            }
        )
        // An all-day occurrence anchored to something that is not a whole day.
        try requireDecodeFailure(
            CalendarOccurrence.self,
            data: try mutatedJSON(try probeAllDayOccurrence()) { object in
                var identity = try jsonDictionary(object["identity"])
                identity["originalStartUnixMilliseconds"] = 1
                object["identity"] = identity
                object["lifecycle"] = "detached"
            }
        )
        // A wall clock that disagrees with the instant it claims to render.
        try requireDecodeFailure(
            CalendarTimedInterval.self,
            data: try mutatedJSON(
                try CalendarTimedInterval.at(
                    startUnixMilliseconds: start,
                    endUnixMilliseconds: start + 1_800_000,
                    timezoneIdentifier: calendarZone
                )
            ) { object in
                var wallClock = try jsonDictionary(object["startWallClock"])
                wallClock["hour"] = 3
                object["startWallClock"] = wallClock
            }
        )
        // A component carrying the composition separator, off the wire.
        try requireDecodeFailure(
            CalendarIdentityComponent.self,
            data: Data(#""calendar:beta""#.utf8)
        )
        // A date that does not exist.
        try requireDecodeFailure(
            CalendarDate.self,
            data: Data(#"{"year":2026,"month":2,"day":30}"#.utf8)
        )
        // An all-day span running backwards.
        try requireDecodeFailure(
            CalendarAllDaySpan.self,
            data: try mutatedJSON(
                try CalendarAllDaySpan(
                    firstDay: try CalendarDate(year: 2026, month: 3, day: 5),
                    lastDay: try CalendarDate(year: 2026, month: 3, day: 6)
                )
            ) { object in
                object["firstDay"] = ["year": 2026, "month": 3, "day": 7]
            }
        )
        // A series whose interval is not a positive number of days.
        try requireDecodeFailure(
            CalendarRecurringSeries.self,
            data: try mutatedJSON(try probeSeries()) { $0["intervalDays"] = 0 }
        )

        // **Lead B**: the WP-14 occurrence type had a synthesized `Codable` and
        // therefore no invariant off the wire at all. It now refuses a confirmed
        // occurrence that has moved, exactly as its WP-17 sibling does.
        let legacy = try NativeCalendarOccurrence(
            identity: NativeOccurrenceIdentity(
                seriesID: try opaque("series-legacy"),
                scheduledStartUnixMilliseconds: start
            ),
            bucketID: try opaque("calendar-beta"),
            timezoneIdentifier: "UTC",
            startUnixMilliseconds: start,
            endUnixMilliseconds: start + 1,
            lifecycle: .confirmed,
            payload: []
        )
        try requireDecodeFailure(
            NativeCalendarOccurrence.self,
            data: try mutatedJSON(legacy) { $0["startUnixMilliseconds"] = start + 1_000 }
        )
        try requireDecodeFailure(
            NativeCalendarOccurrence.self,
            data: try mutatedJSON(legacy) { $0["endUnixMilliseconds"] = start - 1 }
        )
        try requireDecodeFailure(
            NativeCalendarOccurrence.self,
            data: try mutatedJSON(legacy) { $0["lifecycle"] = nil }
        )
    }

    // MARK: - WP-18 contacts
    //
    // Every value below is obviously synthetic and no contact belonging to
    // anyone was read to write any of it. `Person Alpha` is not a person, and
    // there is no field in any contacts type for a name, an address, a number or
    // a photograph, so there is nothing here for a real one to be mistaken for.

    private static let contactsEpoch = "epoch-one"

    private static func contactsComponent(_ value: String) throws -> ContactsIdentityComponent {
        try requireValue(
            ContactsIdentityComponent(rawValue: value),
            "The probe contacts identity component \(value) is not admissible"
        )
    }

    private static func contactsContainer(_ account: String, _ container: String) throws
        -> ContactsContainerIdentity {
        ContactsContainerIdentity(
            accountKey: try contactsComponent(account),
            containerKey: try contactsComponent(container)
        )
    }

    private static func contactsGroup(
        _ account: String,
        _ container: String,
        _ group: String
    ) throws -> ContactsGroupIdentity {
        ContactsGroupIdentity(
            container: try contactsContainer(account, container),
            groupKey: try contactsComponent(group)
        )
    }

    private static func contactsIdentity(
        _ account: String,
        _ container: String,
        _ contact: String,
        epoch: String = contactsEpoch
    ) throws -> ContactIdentity {
        ContactIdentity(
            container: try contactsContainer(account, container),
            identityEpoch: try contactsComponent(epoch),
            contactKey: try contactsComponent(contact)
        )
    }

    private static func contactsObservation(
        container: String = "container-alpha",
        contact: String,
        epoch: String = contactsEpoch,
        structuralType: ContactStructuralType = .person,
        assurance: ContactIdentityAssurance = .stableWithinEpoch,
        groups: [String] = []
    ) throws -> ContactObservation {
        try ContactObservation(
            identity: try contactsIdentity("account-alpha", container, contact, epoch: epoch),
            structuralType: structuralType,
            identityAssurance: assurance,
            groupKeys: try groups.map { try contactsComponent($0) },
            observedKeys: ContactsMinimumKeySet.keys
        )
    }

    /// Four observations in `Container Alpha` and one in `Container Beta`, the
    /// last so that a mechanism which answers with another container's people
    /// has something to leak that the adapter can catch.
    ///
    /// The three assurance answers are all present on purpose: a page in which
    /// every record claims the strongest one would exercise nothing, and
    /// `unknown` is the one a consumer must not be able to mistake for
    /// `stableWithinEpoch`.
    private static func contactsObservations(epoch: String = contactsEpoch) throws
        -> [ContactObservation] {
        [
            try contactsObservation(
                contact: "org-delta",
                epoch: epoch,
                structuralType: .organization,
                groups: ["group-beta"]
            ),
            try contactsObservation(contact: "person-alpha", epoch: epoch, groups: ["group-alpha"]),
            try contactsObservation(
                contact: "person-beta",
                epoch: epoch,
                assurance: .unknown,
                groups: ["group-alpha", "group-beta"]
            ),
            try contactsObservation(
                contact: "person-gamma",
                epoch: epoch,
                assurance: .reMintedInThisEpoch
            ),
            try contactsObservation(
                container: "container-beta",
                contact: "person-epsilon",
                epoch: epoch
            ),
        ]
    }

    private static func contactsDescriptor(
        publishesIdentityEpoch: Bool = true,
        publishesGroupMembership: Bool = true
    ) -> ContactsMechanismDescriptor {
        ContactsMechanismDescriptor(
            mechanism: .fixtureSeeded,
            publishesIdentityEpoch: publishesIdentityEpoch,
            publishesGroupMembership: publishesGroupMembership,
            requiresOperatorConsent: true
        )
    }

    private static func contactsMechanism(
        observations: [ContactObservation]? = nil,
        epoch: String = contactsEpoch,
        publishesIdentityEpoch: Bool = true,
        publishesGroupMembership: Bool = true,
        groups: [ContactsGroupDescriptor]? = nil
    ) throws -> FixtureContactsMechanism {
        try FixtureContactsMechanism(
            descriptor: contactsDescriptor(
                publishesIdentityEpoch: publishesIdentityEpoch,
                publishesGroupMembership: publishesGroupMembership
            ),
            accounts: [
                ContactsAccountDescriptor(
                    accountKey: try contactsComponent("account-alpha"),
                    displayLabel: "Account Alpha"
                )
            ],
            containers: [
                ContactsContainerDescriptor(
                    identity: try contactsContainer("account-alpha", "container-alpha"),
                    kind: .local,
                    displayLabel: "Container Alpha",
                    isSelectable: true
                ),
                ContactsContainerDescriptor(
                    identity: try contactsContainer("account-alpha", "container-beta"),
                    kind: .cardDAV,
                    displayLabel: "Container Beta",
                    isSelectable: true
                ),
            ],
            groups: try groups ?? [
                ContactsGroupDescriptor(
                    identity: try contactsGroup("account-alpha", "container-alpha", "group-alpha"),
                    displayLabel: "Group Alpha"
                ),
                ContactsGroupDescriptor(
                    identity: try contactsGroup("account-alpha", "container-alpha", "group-beta"),
                    displayLabel: "Group Beta"
                ),
                ContactsGroupDescriptor(
                    identity: try contactsGroup("account-alpha", "container-beta", "group-gamma"),
                    displayLabel: "Group Gamma"
                ),
            ],
            observations: try observations ?? contactsObservations(epoch: epoch),
            identityEpoch: try contactsComponent(epoch)
        )
    }

    private static func contactsRequest(
        container: String = "container-alpha",
        limit: Int = 100,
        cursor: NativeReadCursor? = nil
    ) throws -> NativeReadRequest {
        try NativeReadRequest(
            bucketID: try contactsContainer("account-alpha", container).recordIdentifier(),
            cursor: cursor,
            limit: limit
        )
    }

    private static func decodedObservation(_ record: NativeSourceRecord) throws
        -> ContactObservation {
        try JSONDecoder().decode(ContactObservation.self, from: Data(record.payload))
    }

    /// Control 1. The minimum key set, frozen, content-free, and **closed by the
    /// type rather than by a refusal**.
    ///
    /// The strongest statement available here is not "a wider key set is
    /// rejected" — it is that a wider key set has no spelling. The fetch-key
    /// vocabulary is two cases and the minimum is all of them, so widening the
    /// request and widening the vocabulary are one edit. The rest of this check
    /// is what happens when somebody makes that edit off the wire instead.
    private static func checkContactsMinimumKeySetIsFrozenAndContentFree() throws {
        try require(
            ContactsFetchKey.allCases.count == 2,
            "The contacts fetch-key vocabulary is no longer two cases"
        )
        try require(
            ContactsMinimumKeySet.keys == ContactsFetchKey.allCases,
            "The minimum key set is no longer the whole fetch-key vocabulary, so there is now "
                + "a key this package can ask for and does not"
        )
        try require(
            ContactsFetchKey.allCases.map(\.rawValue)
                == ["contact_identifier", "contact_structural_type"],
            "The contacts fetch-key vocabulary drifted from the two frozen keys"
        )
        try require(
            ContactsMinimumKeySet.isTheMinimum(ContactsMinimumKeySet.keys),
            "The frozen minimum no longer recognises itself"
        )
        // Narrower and reordered are both refused. Narrower matters as much as
        // wider: a record built from fewer keys than the contract names carries
        // a field the consumer reads as absent when it was merely unfetched.
        for wrong in [[ContactsFetchKey.identifier], [.structuralType, .identifier], []] {
            try require(
                !ContactsMinimumKeySet.isTheMinimum(wrong),
                "The key set \(wrong.map(\.rawValue)) was accepted as the frozen minimum"
            )
            try requireError(.contactsKeySetWidened) {
                try ContactsTraversalQuery(
                    container: try contactsContainer("account-alpha", "container-alpha"),
                    requestedKeys: wrong,
                    afterCursorKey: nil,
                    limit: 10
                )
            }
            try requireError(.contactsKeySetWidened) {
                try ContactObservation(
                    identity: try contactsIdentity(
                        "account-alpha", "container-alpha", "person-alpha"
                    ),
                    structuralType: .person,
                    identityAssurance: .stableWithinEpoch,
                    groupKeys: [],
                    observedKeys: wrong
                )
            }
        }

        // The record the adapter actually produces. Its payload is asserted
        // field by field rather than spot-checked, because "no content field"
        // is a claim about the *whole* value and a spot check cannot make it.
        let adapter = BoundedContactsReadAdapter(mechanism: try contactsMechanism())
        let page = try adapter.readContacts(try contactsRequest())
        try require(!page.records.isEmpty, "The contacts fixture read produced no record")
        for record in page.records {
            try require(
                try decodedObservation(record).observedKeys == ContactsMinimumKeySet.keys,
                "A contact observation declared a key set that is not the frozen minimum"
            )
            let payload = try jsonDictionary(
                try JSONSerialization.jsonObject(with: Data(record.payload))
            )
            try require(
                payload.keys.sorted() == [
                    "groupKeys", "identity", "identityAssurance", "observedKeys", "structuralType",
                ],
                "A contact record's payload carries the fields \(payload.keys.sorted())"
            )
        }

        // Off the wire, a content key is not a key this vocabulary can decode.
        // The record would have to name it, and there is no case to name.
        try requireDecodeFailure(
            ContactsFetchKey.self,
            data: Data(#""contact_email_address""#.utf8)
        )
        try requireDecodeFailure(
            ContactObservation.self,
            data: try mutatedJSON(try contactsObservation(contact: "person-alpha")) { object in
                object["observedKeys"] = ["contact_identifier", "contact_email_address"]
            }
        )
    }

    /// Control 2. Identity is five levels, injective across the branch, and
    /// carries the epoch it is only stable within — so an identifier that
    /// changes produces a **visibly disjoint key space** rather than a second
    /// record for the same person under a stable-looking key.
    private static func checkContactsIdentityCarriesItsEpochAndIsBranchInjective() throws {
        let account = ContactsAccountIdentity(accountKey: try contactsComponent("account-alpha"))
        let container = try contactsContainer("account-alpha", "container-alpha")
        // The same trailing key on both branches at the same depth. This is the
        // collision the discriminator exists to prevent, and it is asserted
        // rather than assumed.
        let group = try contactsGroup("account-alpha", "container-alpha", "shared-key")
        let contact = try contactsIdentity("account-alpha", "container-alpha", "shared-key")

        let identifiers = [
            try account.recordIdentifier().rawValue,
            try container.recordIdentifier().rawValue,
            try group.recordIdentifier().rawValue,
            try contact.recordIdentifier().rawValue,
        ]
        try require(
            Set(identifiers).count == 4,
            "Two contacts identity levels compose to the same identifier"
        )
        try require(
            identifiers.map { $0.filter { $0 == ":" }.count } == [0, 1, 3, 4],
            "The contacts identity levels are no longer distinguished by their shape"
        )
        try require(
            identifiers[1].hasPrefix(identifiers[0] + ":")
                && identifiers[2].hasPrefix(identifiers[1] + ":")
                && identifiers[3].hasPrefix(identifiers[1] + ":"),
            "A contacts identity level is no longer a prefix of the level below it"
        )
        try require(
            !identifiers[3].hasPrefix(identifiers[2]),
            "A contact identifier is a prefix-extension of a group identifier, so a group and a "
                + "contact at the same depth can be confused"
        )
        try require(
            ContactsIdentityBranch.allCases.map(\.rawValue).sorted() == ["contact", "group"],
            "The identity branch discriminator is no longer a closed two-member set"
        )
        try require(
            ContactsIdentityComponent(rawValue: "container:alpha") == nil,
            "A colon in a contacts identity component would make composition ambiguous"
        )
        // Refused, never trimmed: five maximum-length components genuinely
        // exceed the opaque identifier's ceiling.
        let longest = String(
            repeating: "k",
            count: NativeSourceProtocolV1.maximumContactsIdentityComponentBytes
        )
        try requireError(.contactsIdentityTooLong) {
            try ContactIdentity(
                container: ContactsContainerIdentity(
                    accountKey: try contactsComponent(longest),
                    containerKey: try contactsComponent(longest)
                ),
                identityEpoch: try contactsComponent(longest),
                contactKey: try contactsComponent(longest)
            ).recordIdentifier()
        }

        // Stability across reads, and visible change across an epoch. The second
        // half is the one that matters: the key spaces must be **disjoint**, not
        // overlapping, because a partial overlap is exactly the state in which a
        // reconciler silently produces a duplicate person.
        let adapter = BoundedContactsReadAdapter(mechanism: try contactsMechanism())
        let first = try adapter.readContacts(try contactsRequest()).records.map(\.id.rawValue)
        let again = try adapter.readContacts(try contactsRequest()).records.map(\.id.rawValue)
        try require(first == again, "A contacts read produced different identifiers second time")

        let reMinted = BoundedContactsReadAdapter(
            mechanism: try contactsMechanism(epoch: "epoch-two")
        )
        let afterReMint = try reMinted.readContacts(try contactsRequest())
        try require(
            Set(afterReMint.records.map(\.id.rawValue)).isDisjoint(with: Set(first)),
            "A re-minted epoch produced identifiers that overlap the previous epoch's, so a "
                + "changed identifier is not detectable"
        )
        try require(
            afterReMint.records.count == first.count,
            "The re-minted read lost or gained a record"
        )
        try require(
            afterReMint.records.allSatisfy { $0.sourceRevision == "epoch-two" },
            "A contact record's revision is not the epoch its identity is keyed with"
        )
        try require(
            afterReMint.records.allSatisfy { $0.sourceModifiedUnixMilliseconds == nil },
            "A contact record carries a modification time the source does not publish"
        )

        // Assurance is carried per record, all three answers survive, and
        // `unknown` is never rounded up to a claim the mechanism did not make.
        try require(
            ContactIdentityAssurance.allCases.count == 3,
            "The identity assurance vocabulary is no longer three answers"
        )
        let assurances = try afterReMint.records.map { try decodedObservation($0).identityAssurance }
        try require(
            Set(assurances) == [.stableWithinEpoch, .unknown, .reMintedInThisEpoch],
            "The read did not carry all three assurance answers through to the records"
        )

        // A mechanism that cannot name its epoch is refused rather than read
        // from with a best guess, and one whose declared epoch disagrees with
        // the keys it minted is caught.
        try requireError(.contactsIdentityEpochUnavailable) {
            try BoundedContactsReadAdapter(
                mechanism: try contactsMechanism(publishesIdentityEpoch: false)
            ).readContacts(try contactsRequest())
        }
        let drifting = try contactsMechanism()
        drifting.setFault(.driftTheIdentityEpoch)
        try requireError(.contactsIdentityEpochMismatch) {
            try BoundedContactsReadAdapter(mechanism: drifting)
                .readContacts(try contactsRequest())
        }
    }

    /// Control 3. `account → container → group → contact` survives the read, in
    /// the vocabulary the protocol already has, and membership is re-checked
    /// against what discovery published rather than believed.
    private static func checkContactsContainerAndGroupMembershipSurvivesTheRead() throws {
        let mechanism = try contactsMechanism()
        let adapter = BoundedContactsReadAdapter(mechanism: mechanism)

        let snapshot = try adapter.discoverContactCollections()
        try require(snapshot.kind == .contacts, "Contacts discovery returned the wrong kind")
        try require(snapshot.accounts.count == 1, "Contacts discovery lost the account")
        try require(snapshot.buckets.count == 5, "Contacts discovery lost a container or a group")
        let containers = snapshot.buckets.compactMap { $0.parentID == nil ? $0 : nil }
        let groups = snapshot.buckets.compactMap { $0.parentID == nil ? nil : $0 }
        try require(containers.count == 2, "Contacts discovery lost a container")
        try require(groups.count == 3, "Contacts discovery lost a group")
        try require(
            groups.allSatisfy { group in containers.contains { $0.id == group.parentID } },
            "A discovered group names a container discovery did not report"
        )
        try require(
            snapshot.buckets.allSatisfy { bucket in
                snapshot.accounts.contains { $0.id == bucket.accountID }
            },
            "A discovered bucket names an account discovery did not report"
        )
        try require(
            groups.allSatisfy { !$0.isSelectable } && containers.allSatisfy(\.isSelectable),
            "A group became selectable, or a container stopped being; a bounded contacts read is "
                + "scoped to a container and a group is a membership view of one"
        )

        // A group whose container was never published has no place in the tree,
        // and is refused rather than attached to whichever container looks
        // plausible.
        try requireError(.contactsMembershipInconsistent) {
            try BoundedContactsReadAdapter(
                mechanism: try contactsMechanism(groups: [
                    ContactsGroupDescriptor(
                        identity: try contactsGroup(
                            "account-alpha", "container-omega", "group-alpha"
                        ),
                        displayLabel: "Group Alpha"
                    )
                ])
            ).discoverContactCollections()
        }

        // Membership survives to the record, including the two facts that are
        // easiest to lose: a contact in more than one group, and a contact in
        // none.
        let page = try adapter.readContacts(try contactsRequest())
        var memberships: [String: [String]] = [:]
        for record in page.records {
            let observation = try decodedObservation(record)
            memberships[observation.identity.contactKey.rawValue] =
                observation.groupKeys.map(\.rawValue)
        }
        try require(
            memberships["person-beta"] == ["group-alpha", "group-beta"],
            "A contact in two groups did not keep both memberships"
        )
        try require(
            memberships["person-gamma"] == [],
            "A contact in no group did not survive the read as a contact in no group"
        )
        try require(
            memberships["org-delta"] == ["group-beta"],
            "An organization row lost its membership"
        )

        // A membership naming a group nothing published is a dangling edge, and
        // is refused.
        mechanism.setFault(.claimAnUndeclaredGroup)
        try requireError(.contactsUnknownGroup) {
            try adapter.readContacts(try contactsRequest())
        }
        mechanism.setFault(.none)

        // **Measured, not asserted.** A mechanism that discards membership is
        // undetectable from the adapter — nothing downstream of a source can
        // tell "in no group" from "I did not look" — so the two reads are
        // compared directly. The suppressed page is well-formed, passes every
        // check, and is missing a fact. That is the whole argument for the seam
        // refusing a mechanism that cannot report membership at all.
        mechanism.setFault(.forgetGroupMembership)
        let suppressed = try adapter.readContacts(try contactsRequest())
        mechanism.setFault(.none)
        try require(
            suppressed.records.map(\.id.rawValue) == page.records.map(\.id.rawValue),
            "Suppressing membership changed which records were returned, so the comparison below "
                + "is measuring something other than the membership"
        )
        try require(
            try suppressed.records.allSatisfy { try decodedObservation($0).groupKeys.isEmpty },
            "The suppressed page kept a membership"
        )
        try requireError(.contactsMembershipUnavailable) {
            try BoundedContactsReadAdapter(
                mechanism: try contactsMechanism(publishesGroupMembership: false)
            ).readContacts(try contactsRequest())
        }

        // The membership ceiling refuses rather than shortening, and a
        // membership list with no canonical order is refused too: two equal
        // memberships must not encode two ways.
        let overFull = try (0...NativeSourceProtocolV1.maximumContactGroupMemberships)
            .map { try contactsComponent("group-\(String(format: "%03d", $0))") }
        try requireError(.contactsGroupLimitExceeded) {
            try ContactObservation(
                identity: try contactsIdentity(
                    "account-alpha", "container-alpha", "person-alpha"
                ),
                structuralType: .person,
                identityAssurance: .stableWithinEpoch,
                groupKeys: overFull,
                observedKeys: ContactsMinimumKeySet.keys
            )
        }
        for disordered in [["group-beta", "group-alpha"], ["group-alpha", "group-alpha"]] {
            try requireError(.contactsMembershipInconsistent) {
                try contactsObservation(contact: "person-alpha", groups: disordered)
            }
        }
    }

    /// Control 4. Authorization fails closed before any read, a refusal is a
    /// **different value** from an empty container, and a grant withdrawn
    /// mid-session refuses the next call rather than serving the last one again.
    ///
    /// The revocation half is the one WP-17 did not have to answer. A contacts
    /// grant can be taken away in System Settings while this process is running,
    /// and an adapter that consulted authorization once at construction would
    /// keep reading afterwards. This one re-checks on every operation and holds
    /// no state a revoked grant could leave behind.
    private static func checkContactsAuthorizationFailsClosedAndRevocationIsNotAStalePage() throws {
        let mechanism = try contactsMechanism()
        let adapter = BoundedContactsReadAdapter(mechanism: mechanism)

        try require(
            ContactsAuthorizationState.allCases.count == 4,
            "The contacts authorization vocabulary is no longer the four states macOS distinguishes"
        )

        for state in ContactsAuthorizationState.allCases where state != .authorized {
            mechanism.setAuthorization(state)
            mechanism.resetCallCounters()
            try requireProviderFailure(.permissionDenied) {
                try adapter.discoverContactCollections()
            }
            try requireProviderFailure(.permissionDenied) {
                try adapter.readContacts(try contactsRequest())
            }
            try require(
                mechanism.readCalls == 0,
                "The adapter made \(mechanism.readCalls) reads with authorization \(state.rawValue)"
            )
            try require(
                mechanism.authorizationCalls == 2,
                "Authorization was not consulted once per operation"
            )
        }

        // The other half, and the half that makes the first one mean something:
        // an authorized read of a container that genuinely holds nobody produces
        // a *page*. A refusal produces no page at all, because it throws.
        mechanism.setAuthorization(.authorized)
        let empty = try contactsMechanism(observations: [])
        let emptyPage = try BoundedContactsReadAdapter(mechanism: empty)
            .readContacts(try contactsRequest())
        try require(
            emptyPage.records.isEmpty && emptyPage.nextCursor == nil,
            "An empty contacts container did not read as an empty page"
        )

        // **Revocation mid-session.** The first read is honest; the grant is
        // withdrawn between the two calls; the second must throw. The fixture's
        // own counter is what proves the mechanism was never asked a second
        // time, so "no stale page was served" is a measurement rather than an
        // argument about the adapter's source.
        let revoking = try contactsMechanism()
        let revokingAdapter = BoundedContactsReadAdapter(mechanism: revoking)
        revoking.setFault(.revokeAuthorizationAfterTheFirstCheck)
        revoking.resetCallCounters()
        let served = try revokingAdapter.readContacts(try contactsRequest())
        try require(!served.records.isEmpty, "The pre-revocation read returned nothing to go stale")
        try require(revoking.contactCalls == 1, "The pre-revocation read did not reach the source")
        let servedCalls = revoking.readCalls
        for attempt in 1...2 {
            try requireProviderFailure(.permissionDenied) {
                try revokingAdapter.readContacts(try contactsRequest())
            }
            try require(
                revoking.contactCalls == 1,
                "Read attempt \(attempt) after revocation reached the source"
            )
        }
        try requireProviderFailure(.permissionDenied) {
            try revokingAdapter.discoverContactCollections()
        }
        try require(
            revoking.readCalls == servedCalls,
            "Discovery after revocation reached the source"
        )
    }

    /// The page bounds, the honest truncation signal, and the mechanism faults
    /// that exercise the adapter's re-checks rather than leaving them written.
    private static func checkContactsPageBoundsAndHonestTruncation() throws {
        let mechanism = try contactsMechanism()
        let adapter = BoundedContactsReadAdapter(mechanism: mechanism)

        var collected: [String] = []
        var cursor: NativeReadCursor?
        var pages = 0
        repeat {
            let page = try adapter.readContacts(try contactsRequest(limit: 2, cursor: cursor))
            pages += 1
            collected.append(contentsOf: page.records.map(\.id.rawValue))
            cursor = page.nextCursor
            try require(pages <= 8, "Paging the contacts fixture did not terminate")
        } while cursor != nil
        let whole = try adapter.readContacts(try contactsRequest())
        try require(
            collected == whole.records.map(\.id.rawValue),
            "Paging in twos did not reproduce the single-page contacts read exactly"
        )
        try require(Set(collected).count == collected.count, "Paging returned a contact twice")
        try require(whole.nextCursor == nil, "A complete contacts page still declared more available")
        try require(
            whole.records.allSatisfy { $0.kind == .contacts },
            "A contact record was admitted under another source kind"
        )
        try require(
            whole.records.count == 4,
            "The container-scoped read returned \(whole.records.count) records; the other "
                + "container's contact must not be in it"
        )

        for (fault, expected) in [
            (FixtureContactsFault.declareEveryContainerSweep, NativeSourceContractError
                .contactsUnboundedEnumeration),
            (.returnKeysOutOfOrder, .nonCanonicalOrder),
            (.claimMoreAvailableWithoutFillingThePage, .contactsTruncationUndeclared),
            (.leakAnotherContainersContact, .unknownBucket),
        ] {
            mechanism.setFault(fault)
            try requireError(expected) { try adapter.readContacts(try contactsRequest()) }
        }
        mechanism.setFault(.none)

        // A container identifier the adapter cannot decompose is refused rather
        // than guessed at.
        try requireError(.contactsInvalidIdentityComponent) {
            try adapter.readContacts(
                try NativeReadRequest(bucketID: try opaque("account-alpha"), limit: 10)
            )
        }

        // The page and cursor ceilings are the protocol's, not this adapter's,
        // and they still refuse rather than clamp.
        try requireError(.invalidPageLimit) {
            try contactsRequest(limit: NativeSourceProtocolV1.maximumPageSize + 1)
        }
        try require(
            NativeReadCursor(
                rawValue: String(
                    repeating: "c",
                    count: NativeSourceProtocolV1.maximumCursorBytes + 1
                )
            ) == nil,
            "The frozen cursor ceiling no longer refuses an over-long cursor"
        )
    }

    /// Every contacts invariant, re-checked on the decode path.
    ///
    /// WP-15's lesson through WP-17's: a bound that exists only on an
    /// initialiser holds for values built in Swift and not for the same values
    /// arriving as JSON, which is the shape a host is actually handed.
    private static func checkContactsValueBoundsHoldOffTheWire() throws {
        let observation = try contactsObservation(
            contact: "person-alpha",
            groups: ["group-alpha", "group-beta"]
        )

        // A key set widened, narrowed, or merely reordered.
        for keys in [
            ["contact_identifier"],
            ["contact_structural_type", "contact_identifier"],
            [String](),
        ] {
            try requireDecodeFailure(
                ContactObservation.self,
                data: try mutatedJSON(observation) { $0["observedKeys"] = keys }
            )
        }
        // A membership list that is unordered, repeated, or over the ceiling.
        for groups in [
            ["group-beta", "group-alpha"],
            ["group-alpha", "group-alpha"],
            (0...NativeSourceProtocolV1.maximumContactGroupMemberships)
                .map { "group-\(String(format: "%03d", $0))" },
        ] {
            try requireDecodeFailure(
                ContactObservation.self,
                data: try mutatedJSON(observation) { $0["groupKeys"] = groups }
            )
        }
        // An observation with no assurance at all. A consumer handed one would
        // assume the strongest answer.
        try requireDecodeFailure(
            ContactObservation.self,
            data: try mutatedJSON(observation) { $0["identityAssurance"] = nil }
        )
        // A component carrying the composition separator, off the wire.
        try requireDecodeFailure(
            ContactsIdentityComponent.self,
            data: Data(#""container:alpha""#.utf8)
        )
        // A component over the frozen byte ceiling.
        try requireDecodeFailure(
            ContactsIdentityComponent.self,
            data: Data(
                "\"\(String(repeating: "k", count: NativeSourceProtocolV1.maximumContactsIdentityComponentBytes + 1))\""
                    .utf8
            )
        )
    }

    /// Reminders/Tasks is an observed source plane, not a mutation plane.
    /// Completion survives as source evidence, pagination is deterministic, and
    /// denial is a refusal rather than an empty successful list.
    private static func checkTasksReadIsBoundedReadOnlyAndConsentGated() throws {
        let account = try opaque("tasks-account")
        let list = try opaque("tasks-list")
        let first = try TaskObservation(
            id: opaque("task-0001"), listID: list, sourceRevision: "revision-1",
            sourceModifiedUnixMilliseconds: 1, title: "Synthetic open task"
        )
        let second = try TaskObservation(
            id: opaque("task-0002"), listID: list, sourceRevision: "revision-2",
            sourceModifiedUnixMilliseconds: 2, title: "Synthetic completed task",
            completedUnixMilliseconds: 2
        )
        let mechanism = FixtureTasksMechanism(
            authorization: .authorized,
            accounts: [
                NativeSourceAccount(id: account, kind: .tasks, displayLabel: "Synthetic")
            ],
            lists: [
                TaskListDescriptor(id: list, accountID: account, displayLabel: "Synthetic")
            ],
            tasks: [second, first]
        )
        let adapter = BoundedTasksReadAdapter(mechanism: mechanism)
        try require(
            try adapter.discoverTaskLists().kind == .tasks,
            "Tasks discovery changed source kind"
        )
        let page = try adapter.readTasks(try NativeReadRequest(bucketID: list, limit: 1))
        try require(
            page.records.map(\.id.rawValue) == ["task-0001"],
            "Tasks page was not canonical"
        )
        let resumed = try adapter.readTasks(
            try NativeReadRequest(bucketID: list, cursor: page.nextCursor, limit: 1)
        )
        let observed = try JSONDecoder().decode(
            TaskObservation.self, from: Data(resumed.records[0].payload)
        )
        try require(
            observed.completedUnixMilliseconds == 2,
            "Task completion was filtered instead of preserved as evidence"
        )

        let denied = BoundedTasksReadAdapter(
            mechanism: FixtureTasksMechanism(
                authorization: .denied, accounts: [], lists: [], tasks: []
            )
        )
        do {
            _ = try denied.discoverTaskLists()
            throw ContractCheckError.failed("Denied Tasks access returned an empty success")
        } catch NativeProviderFailure.permissionDenied {
            // Expected: authorization is distinct from an empty source.
        }

        let unstable = BoundedTasksReadAdapter(
            mechanism: FixtureTasksMechanism(
                authorization: .authorized, accounts: [], lists: [], tasks: [],
                publishesStableIdentifiers: false
            )
        )
        try requireError(.tasksIdentityInconsistent) {
            try unstable.discoverTaskLists()
        }
    }

}
