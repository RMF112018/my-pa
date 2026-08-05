public struct SyntheticPageFixture: Hashable, Sendable {
    public let bucketID: NativeSourceOpaqueID
    public let requestCursor: NativeReadCursor?
    public let page: NativeReadPage

    public init(
        bucketID: NativeSourceOpaqueID,
        requestCursor: NativeReadCursor?,
        page: NativeReadPage
    ) {
        self.bucketID = bucketID
        self.requestCursor = requestCursor
        self.page = page
    }
}

private struct SyntheticCatalog: Sendable {
    let snapshot: NativeDiscoverySnapshot
    let pages: [SyntheticPageFixture]

    init(
        kind: NativeSourceKind,
        snapshot: NativeDiscoverySnapshot,
        pages: [SyntheticPageFixture]
    ) throws {
        guard snapshot.kind == kind,
              pages.allSatisfy({ fixture in
                  snapshot.buckets.contains(where: { $0.id == fixture.bucketID })
                      && fixture.page.records.allSatisfy({
                          $0.kind == kind && $0.bucketID == fixture.bucketID
                      })
              })
        else {
            throw NativeSourceContractError.mismatchedSourceKind
        }
        for (offset, fixture) in pages.enumerated() {
            guard !pages.dropFirst(offset + 1).contains(where: {
                $0.bucketID == fixture.bucketID && $0.requestCursor == fixture.requestCursor
            }) else {
                throw NativeSourceContractError.duplicateSyntheticPage
            }
        }
        self.snapshot = snapshot
        self.pages = pages
    }

    func page(for request: NativeReadRequest) throws -> NativeReadPage {
        guard snapshot.buckets.contains(where: {
            $0.id == request.bucketID && $0.isSelectable
        }) else {
            throw NativeSourceContractError.unknownBucket
        }
        guard let fixture = pages.first(where: {
            $0.bucketID == request.bucketID && $0.requestCursor == request.cursor
        }) else {
            throw NativeSourceContractError.missingSyntheticPage
        }
        return fixture.page
    }
}

public struct SyntheticMailReadAdapter: MailReadAdapter, Sendable {
    private let catalog: SyntheticCatalog

    public init(snapshot: NativeDiscoverySnapshot, pages: [SyntheticPageFixture]) throws {
        self.catalog = try SyntheticCatalog(kind: .mail, snapshot: snapshot, pages: pages)
    }

    public func discoverMail() throws -> NativeDiscoverySnapshot {
        catalog.snapshot
    }

    public func readMail(_ request: NativeReadRequest) throws -> NativeReadPage {
        try catalog.page(for: request)
    }
}

public struct SyntheticCalendarReadAdapter: CalendarReadAdapter, Sendable {
    private let catalog: SyntheticCatalog

    public init(snapshot: NativeDiscoverySnapshot, pages: [SyntheticPageFixture]) throws {
        self.catalog = try SyntheticCatalog(kind: .calendar, snapshot: snapshot, pages: pages)
    }

    public func discoverCalendars() throws -> NativeDiscoverySnapshot {
        catalog.snapshot
    }

    public func readCalendar(_ request: NativeReadRequest) throws -> NativeReadPage {
        try catalog.page(for: request)
    }
}

public struct SyntheticContactsReadAdapter: ContactsReadAdapter, Sendable {
    private let catalog: SyntheticCatalog

    public init(snapshot: NativeDiscoverySnapshot, pages: [SyntheticPageFixture]) throws {
        self.catalog = try SyntheticCatalog(kind: .contacts, snapshot: snapshot, pages: pages)
    }

    public func discoverContactCollections() throws -> NativeDiscoverySnapshot {
        catalog.snapshot
    }

    public func readContacts(_ request: NativeReadRequest) throws -> NativeReadPage {
        try catalog.page(for: request)
    }
}
