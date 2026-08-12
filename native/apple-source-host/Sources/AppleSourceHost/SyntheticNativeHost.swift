public struct SyntheticPreflightFixture: Hashable, Sendable {
    public let selection: NativeBucketSelection
    public let state: NativePreflightState
    public let failure: NativeProviderFailure?

    public init(
        selection: NativeBucketSelection,
        state: NativePreflightState,
        failure: NativeProviderFailure? = nil
    ) throws {
        _ = try NativePreflightResult(selection: selection, state: state, failure: failure)
        self.selection = selection
        self.state = state
        self.failure = failure
    }
}

/// Deterministic, synthetic-only implementation of the future application-facing
/// host boundary. It composes the protocol-v1 fixture adapters and performs
/// no I/O other than a separately invoked protected spool.
public struct SyntheticNativeHost: NativeHostApplicationBoundary, Sendable {
    public let hostInstanceID: NativeSourceOpaqueID
    private let mail: SyntheticMailReadAdapter
    private let calendar: SyntheticCalendarReadAdapter
    private let contacts: SyntheticContactsReadAdapter
    private let tasks: SyntheticTasksReadAdapter?
    private let preflightFixtures: [NativeBucketSelection: SyntheticPreflightFixture]

    public init(
        hostInstanceID: NativeSourceOpaqueID,
        mail: SyntheticMailReadAdapter,
        calendar: SyntheticCalendarReadAdapter,
        contacts: SyntheticContactsReadAdapter,
        preflightFixtures: [SyntheticPreflightFixture],
        tasks: SyntheticTasksReadAdapter? = nil
    ) throws {
        let selections = preflightFixtures.map(\.selection)
        guard Set(selections).count == selections.count else {
            throw NativeSourceContractError.duplicateIdentity
        }
        var snapshots = [
            try mail.discoverMail(),
            try calendar.discoverCalendars(),
            try contacts.discoverContactCollections(),
        ]
        if let tasks { snapshots.append(try tasks.discoverTaskLists()) }
        guard selections.allSatisfy({ selection in
            snapshots.contains(where: { snapshot in
                snapshot.kind == selection.kind
                    && snapshot.buckets.contains(where: {
                        $0.id == selection.bucketID && $0.accountID == selection.accountID
                    })
            })
        }) else {
            throw NativeSourceContractError.inconsistentDiscovery
        }
        self.hostInstanceID = hostInstanceID
        self.mail = mail
        self.calendar = calendar
        self.contacts = contacts
        self.tasks = tasks
        self.preflightFixtures = Dictionary(uniqueKeysWithValues: preflightFixtures.map {
            ($0.selection, $0)
        })
    }

    public func negotiate(_ offer: NativeProtocolOffer) throws -> NativeProtocolAgreement {
        try NativeProtocolAgreement(offer: offer)
    }

    public func discover(
        _ kind: NativeSourceKind,
        metadata: NativeEnvelopeMetadata
    ) throws -> NativeDiscoveryEnvelope {
        try requireHost(metadata)
        let observed: NativeDiscoverySnapshot
        switch kind {
        case .mail:
            observed = try mail.discoverMail()
        case .calendar:
            observed = try calendar.discoverCalendars()
        case .contacts:
            observed = try contacts.discoverContactCollections()
        case .tasks:
            guard let tasks else { throw NativeSourceContractError.unknownBucket }
            observed = try tasks.discoverTaskLists()
        }
        let canonical = try NativeDiscoverySnapshot(
            kind: kind,
            accounts: observed.accounts.sorted(by: { $0.id.rawValue < $1.id.rawValue }),
            buckets: observed.buckets.sorted(by: { $0.id.rawValue < $1.id.rawValue })
        )
        return try NativeDiscoveryEnvelope(metadata: metadata, snapshot: canonical)
    }

    public func preflight(
        _ request: NativePreflightRequest,
        metadata: NativeEnvelopeMetadata
    ) throws -> NativePreflightEnvelope {
        try requireHost(metadata)
        let results = try request.selections.map { selection in
            if let fixture = preflightFixtures[selection] {
                return try NativePreflightResult(
                    selection: selection,
                    state: fixture.state,
                    failure: fixture.failure
                )
            }
            return try NativePreflightResult(
                selection: selection,
                state: .identityDrift,
                failure: .bucketUnavailable
            )
        }
        return try NativePreflightEnvelope(metadata: metadata, request: request, results: results)
    }

    public func read(
        _ request: NativeReadEnvelopeRequest,
        metadata: NativeEnvelopeMetadata
    ) throws -> NativeAdmissionEnvelope {
        try requireHost(metadata)
        let snapshot: NativeDiscoverySnapshot
        let page: NativeReadPage
        switch request.kind {
        case .mail:
            snapshot = try mail.discoverMail()
            page = try mail.readMail(request.request)
        case .calendar:
            snapshot = try calendar.discoverCalendars()
            page = try calendar.readCalendar(request.request)
        case .contacts:
            snapshot = try contacts.discoverContactCollections()
            page = try contacts.readContacts(request.request)
        case .tasks:
            guard let tasks else { throw NativeSourceContractError.unknownBucket }
            snapshot = try tasks.discoverTaskLists()
            page = try tasks.readTasks(request.request)
        }
        guard snapshot.buckets.contains(where: {
            $0.id == request.request.bucketID && $0.accountID == request.accountID
        }) else {
            throw NativeSourceContractError.inconsistentEnvelope
        }
        return try NativeAdmissionEnvelope(metadata: metadata, request: request, page: page)
    }

    private func requireHost(_ metadata: NativeEnvelopeMetadata) throws {
        guard metadata.hostInstanceID == hostInstanceID else {
            throw NativeSourceContractError.inconsistentEnvelope
        }
    }
}
