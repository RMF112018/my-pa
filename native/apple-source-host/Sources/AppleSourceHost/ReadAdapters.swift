/// Read-only Mail feasibility boundary. A future live implementation requires
/// separate authority; this protocol itself exposes discovery and reads only.
public protocol MailReadAdapter: Sendable {
    func discoverMail() throws -> NativeDiscoverySnapshot
    func readMail(_ request: NativeReadRequest) throws -> NativeReadPage
}

/// Read-only Calendar feasibility boundary.
public protocol CalendarReadAdapter: Sendable {
    func discoverCalendars() throws -> NativeDiscoverySnapshot
    func readCalendar(_ request: NativeReadRequest) throws -> NativeReadPage
}

/// Read-only Contacts feasibility boundary.
public protocol ContactsReadAdapter: Sendable {
    func discoverContactCollections() throws -> NativeDiscoverySnapshot
    func readContacts(_ request: NativeReadRequest) throws -> NativeReadPage
}
