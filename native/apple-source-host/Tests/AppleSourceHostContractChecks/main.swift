import AppleSourceHost

private enum ContractCheckError: Error {
    case failed(String)
}

@main
struct AppleSourceHostContractChecks {
    static func main() throws {
        try checkProtocolVersionAndValueValidation()
        try checkAllThreeSyntheticAdapters()
        try checkSyntheticDenials()
        print("AppleSourceHostContractChecks: PASS (3 checks)")
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

    private static func requireMailConformance<Adapter: MailReadAdapter>(_ adapter: Adapter) {}
    private static func requireCalendarConformance<Adapter: CalendarReadAdapter>(_ adapter: Adapter) {}
    private static func requireContactsConformance<Adapter: ContactsReadAdapter>(_ adapter: Adapter) {}

    private struct FixtureSet {
        let snapshot: NativeDiscoverySnapshot
        let fixture: SyntheticPageFixture
        let request: NativeReadRequest
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

}
