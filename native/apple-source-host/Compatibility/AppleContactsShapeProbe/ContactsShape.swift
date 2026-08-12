/// WP-18 Contacts **shape** probe — compile-time only, and it reads nothing.
///
/// This is the target that makes "the contacts mechanism requires an operator
/// TCC grant" a different statement from "the contacts mechanism does not
/// exist". Contacts is a real, documented, public read API, and every symbol a
/// **minimum-key read-only** contacts adapter would need is named below,
/// resolved by the compiler on every `swift build`.
///
/// Constraints this file must keep, and which
/// `tests/architecture/test_wp18_contacts_adapter.py` enforces rather than
/// trusts — written as a closed set from the start, because WP-17's correction
/// bought the lesson at the price of a reviewer proving its first draft vacuous:
/// a *forbidden* list forbids exactly the spellings its author thought of, and
/// `CNContactStore.save` with no parentheses is as real a reference as
/// `CNContactStore.save(...)` once a type annotation disambiguates it.
///
/// * **nothing is instantiated and nothing is called.** Types are referenced as
///   metatypes, instance members as key paths, and methods as *unapplied*
///   references. Every declaration below is a function or a constant that is
///   compiled and never invoked. No contact store is constructed anywhere in
///   this repository, so no consent dialogue can be reached and no address book
///   can be enumerated;
/// * **the store's members are a closed set of seven**, held by
///   `test_the_contacts_probe_reaches_no_store_in_any_spelling` over this
///   directory and by `test_no_swift_in_the_native_tree_constructs_a_contact_store`
///   over **every** Swift file under `native/`, probes included — because the
///   type is named in two of them, WP-15's multi-framework probe being the
///   other. Every member of that set is a read or a metatype. The mutating half
///   of this framework — the save request, and the store's `execute` — is named
///   nowhere at all, in any spelling;
/// * **no authorization is requested.** The *observing* status method is named
///   as an unapplied reference and never called; the requesting API is named
///   nowhere. A TCC grant is operator-gated (EXT-04) and asking is the thing
///   this package refuses to do;
/// * **only `Contacts` is imported.** The import set is closed, and it had to
///   be: `"import Contacts" in source` is satisfied by `import ContactsUI`,
///   which is the half of this framework that exists to edit a person;
/// * **no content-bearing key is named.** The two key constants below are the
///   frozen minimum and nothing else appears: no name key, no email key, no
///   phone key, no postal key, no birthday key, no image key, no note key, no
///   organization key, no social-profile key. A probe that resolves a name key
///   is a probe that has written the name key into a public repository as a
///   thing this package knows how to ask for;
/// * **this target is a dependency of nothing.** A `swift build` compiles it, so
///   the compatibility claim is re-proved on every build, while the shipping
///   `AppleSourceHost` module keeps importing only `Foundation` and linking no
///   Apple framework. That link-time property is WP-15's control 1 and is the
///   strongest guarantee in this package.
///
/// **What is still trusted, stated plainly.** The guard reads text, not a parsed
/// Swift program: it strips whole-line comments and matches patterns. So a
/// forbidden symbol written in prose is deliberately invisible to it — a guard
/// that reddens on the paragraph explaining it is a guard somebody deletes — and
/// the price of that choice is that a *trailing* comment on a line of code is
/// not stripped either.
///
/// **What this proves:** the framework exists in this SDK, exposes these types,
/// these members, these two key constants and these read methods, and typechecks
/// against them on this toolchain. **What it does not prove:** that a live
/// enumeration works, that TCC will grant, that any of these members returns
/// what a reader expects, that the identifiers are stable across a restore, or
/// that performance is acceptable. Those need an operator and a real machine —
/// see `docs/campaign/WP-18-CONTACTS-ADAPTER-RECORD.md`.

import Contacts

public enum AppleContactsShapeProbe {
    // MARK: The types a minimum-key read-only contacts adapter would name

    public static func storeType() -> CNContactStore.Type { CNContactStore.self }
    public static func contactType() -> CNContact.Type { CNContact.self }
    public static func containerType() -> CNContainer.Type { CNContainer.self }
    public static func groupType() -> CNGroup.Type { CNGroup.self }
    public static func fetchRequestType() -> CNContactFetchRequest.Type {
        CNContactFetchRequest.self
    }

    // MARK: The enumerations that carry the semantics WP-18 is about

    /// Authorization, which is what control 4 fails closed on. Named as values;
    /// none of them is queried from a store.
    ///
    /// **Four cases and not five, and that is a measurement rather than a
    /// choice.** This SDK's enumeration carries a fifth, partial-grant case that
    /// is marked explicitly unavailable on macOS; naming it here does not
    /// compile. `ContactsAuthorizationState` therefore names four states, which
    /// is the whole vocabulary a macOS host can observe.
    public static func authorizationStates() -> [CNAuthorizationStatus] {
        [.notDetermined, .restricted, .denied, .authorized]
    }

    public static func entityType() -> CNEntityType { .contacts }

    /// **Control 3's evidence at the container level.** A container declares
    /// where its records live, and that is what decides how fragile its
    /// identifiers are — which is control 2's problem, stated by the framework
    /// itself rather than invented by this package.
    public static func containerKinds() -> [CNContainerType] {
        [.unassigned, .local, .exchange, .cardDAV]
    }

    /// **Control 1's justification for the second key.** The framework models a
    /// company as a contact row with a different *type*, not as a different
    /// object. Without this discriminator every row reads as a person.
    public static func structuralTypes() -> [CNContactType] { [.person, .organization] }

    // MARK: The minimum key set, and nothing beside it

    /// **Control 1's evidence, and the most load-bearing three lines in this
    /// file.** These are the only two key constants named anywhere in this
    /// repository. A contact read declares its keys up front, so the set named
    /// here is exactly the set this package knows how to ask for, and it holds no
    /// name, address, number, birthday, photograph or note.
    public static let minimumKeysToFetch: [String] = [CNContactIdentifierKey, CNContactTypeKey]

    /// The key list a fetch request carries, resolved as a **read-only** key
    /// path. It proves the request type has somewhere to put the minimum set
    /// above without this file ever building one.
    public static func fetchKeysKeyPath() -> KeyPath<CNContactFetchRequest, [any CNKeyDescriptor]> {
        \CNContactFetchRequest.keysToFetch
    }

    // MARK: The members, which is where a contacts adapter's assumptions live

    /// **Control 2's evidence.** The identifier is the only thing that makes a
    /// row a record. Its documented stability is what
    /// `ContactIdentityAssurance` refuses to take on trust: the framework
    /// publishes no epoch of its own, which is precisely why this package models
    /// one and why a mechanism that cannot name it is refused.
    public static func identifierKeyPath() -> KeyPath<CNContact, String> { \CNContact.identifier }

    public static func structuralTypeKeyPath() -> KeyPath<CNContact, CNContactType> {
        \CNContact.contactType
    }

    /// **Control 3's evidence at each level of the tree.** A container and a
    /// group each publish an identifier and a label, and neither is fetched
    /// through a key descriptor — which is why preserving the structure costs
    /// nothing against the minimum key set.
    public static func containerIdentifierKeyPath() -> KeyPath<CNContainer, String> {
        \CNContainer.identifier
    }

    public static func containerLabelKeyPath() -> KeyPath<CNContainer, String> {
        \CNContainer.name
    }

    public static func containerKindKeyPath() -> KeyPath<CNContainer, CNContainerType> {
        \CNContainer.type
    }

    public static func groupIdentifierKeyPath() -> KeyPath<CNGroup, String> { \CNGroup.identifier }
    public static func groupLabelKeyPath() -> KeyPath<CNGroup, String> { \CNGroup.name }

    // MARK: The read methods, referenced unapplied and never invoked

    /// **Control 3's evidence that scope is source-side.** The framework bounds
    /// a contact query by container and by group with predicates, so reading one
    /// container does not require walking the others. This is what
    /// `ContactsTraversalResult.enumeratedEveryContainer` is about.
    public static func contactsInContainerPredicate() -> (String) -> NSPredicate {
        CNContact.predicateForContactsInContainer(withIdentifier:)
    }

    public static func contactsInGroupPredicate() -> (String) -> NSPredicate {
        CNContact.predicateForContactsInGroup(withIdentifier:)
    }

    public static func groupsInContainerPredicate() -> (String) -> NSPredicate {
        CNGroup.predicateForGroupsInContainer(withIdentifier:)
    }

    /// **Control 1's evidence that the key set reaches the framework.** The
    /// keys-to-fetch argument is part of the read's signature, so a caller
    /// cannot avoid declaring what it takes.
    public static func unifiedContactsMethod()
        -> (CNContactStore) -> (NSPredicate, [any CNKeyDescriptor]) throws -> [CNContact] {
        CNContactStore.unifiedContacts(matching:keysToFetch:)
    }

    /// The streaming read, whose request carries both the predicate and the key
    /// list. **A finding rather than a convenience:** neither this method nor
    /// the one above takes a limit or an offset, so the framework offers no
    /// source-side pagination at all. A page is therefore a slice a mechanism
    /// takes after materialising a container, and the record says so instead of
    /// calling it bounded.
    public static func enumerateMethod()
        -> (CNContactStore) -> (
            CNContactFetchRequest, (CNContact, UnsafeMutablePointer<ObjCBool>) -> Void
        ) throws -> Void {
        CNContactStore.enumerateContacts(with:usingBlock:)
    }

    public static func containersMethod()
        -> (CNContactStore) -> (NSPredicate?) throws -> [CNContainer] {
        CNContactStore.containers(matching:)
    }

    public static func groupsMethod() -> (CNContactStore) -> (NSPredicate?) throws -> [CNGroup] {
        CNContactStore.groups(matching:)
    }

    /// Observing authorization is a read; *requesting* it raises the dialogue.
    /// This is the observing one, referenced and never called.
    public static func authorizationStatusMethod() -> (CNEntityType) -> CNAuthorizationStatus {
        CNContactStore.authorizationStatus(for:)
    }

    /// Names only; nothing is opened, granted, enumerated or stored by this
    /// target.
    public static let probedFrameworks = ["Contacts"]
}
