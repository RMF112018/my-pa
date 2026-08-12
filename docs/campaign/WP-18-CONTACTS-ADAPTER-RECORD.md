# WP-18 — Apple Contacts Live Adapter

> **Current-head correction (2026-08-12 pilot remediation).** This historical
> record accurately describes WP-18's original proof, but its statements that no
> Contacts mechanism exists in the repository are no longer current. The
> separately bounded `AppleSourceHostPlatform` product now contains an injected,
> minimum-key Contacts mechanism and inert composition. It creates no store,
> requests no TCC grant, names no save surface, and repository validation reads
> no live contact. The identity epoch remains application-supplied because the
> framework publishes none. Current scope and external gates are recorded in
> `PILOT-BLOCKER-REMEDIATION-20260812.md`.

Branch: `bf/wp-18-apple-contacts-adapter`. Base: `06282a3d29e978ef8ec4ddd1fa79d2eedef67c0a`.

This record states what WP-18 proved, **at what level it proved it**, and what it
could not prove without an operator. It follows WP-15's, WP-16's and WP-17's
shape because that shape is the point: a compiled guarantee, a link-time
guarantee, a runtime observation and a document are four different things, and a
package that blurs them is worth nothing.

**The headline is not the framework, it is the key set.**

> Contacts **is** a real, documented, public read API, exactly as EventKit is. It
> enumerates containers, groups and contacts; it bounds a query to a container or
> a group with a predicate; it publishes a stable-by-documentation identifier and
> a person-versus-organization discriminator.
> `Compatibility/AppleContactsShapeProbe` makes the compiler re-prove all of that
> on every build.
>
> What makes this package different from WP-17 is not that the mechanism is
> harder to reach — it is what a mistake costs. A calendar read is bounded by a
> **horizon**, and the failure mode is reading too much *time*. A contacts read
> is bounded by a **key set**, and the failure mode is reading too much *about a
> person*. One line — `keysToFetch` gaining a name key — turns a structural
> adapter into somebody's address book in a public repository, and no page
> ceiling, cursor bound or horizon catches it. So the first control is the key
> set, and it is a privacy control rather than an optimisation.
>
> What is missing is **consent**. Reaching a contact store needs a TCC grant only
> a human can give, and this package must not obtain one, ask for one, or read a
> contact. So the adapter is built and proved against a **mechanism seam** driven
> by a store this harness seeded itself, in one process, with no contact store
> ever constructed.
>
> **No contact belonging to anyone was read to produce any line of this record,
> and nothing here may be read as if one had been.**

---

## A. The six controls, and the level each is proved at

**Read the "Proved at" column as the claim.** Nothing in this document upgrades a
level in a later restatement.

| # | Control | Verdict | Proved at | Where |
|---|---|---|---|---|
| 1 | **Minimum requested keys** | **Proven, and proven *structurally*: a wider key set has no spelling.** `ContactsFetchKey` has two content-free cases and the frozen minimum is all of them, so widening the request and widening the vocabulary are one edit | **Swift compile-time** for "there is no third case"; **Swift runtime** for the query, record and decode-path refusals; **Python-structural** for the frozen pair and for the tree-wide content-key scan | `AppleSourceHostContractChecks::checkContactsMinimumKeySetIsFrozenAndContentFree`; `test_the_minimum_contacts_key_set_is_frozen_and_holds_no_content_key`, `test_no_content_bearing_contacts_key_is_named_anywhere_under_native` |
| 2 | **Stable source identity** | **Proven, in the only honest form available: a re-mint is made *visible*, not prevented.** The epoch is a field of the identity, so a re-mint yields a **disjoint** key space rather than an overlapping one, and every observation states its own assurance | **Swift runtime, in-process** for the disjointness, the stability across two reads, and the two epoch refusals; **Python-structural** for the epoch being inside the composed identifier and the assurance being non-optional | `::checkContactsIdentityCarriesItsEpochAndIsBranchInjective`; `test_a_contact_identity_carries_its_epoch_and_states_its_own_assurance`, `test_the_contacts_identity_alphabet_excludes_the_composition_separator` |
| 3 | **Group / container membership preserved** | **Proven, in the existing `NativeDiscoverySnapshot` vocabulary — no parallel envelope.** A group is a bucket whose `parentID` names its container; membership rides on the observation, is bounded, is canonically ordered, and is re-checked against what discovery published | **Swift runtime, in-process**, including the zero-group and two-group cases and a *measured* comparison for the suppression that is undetectable; **Python-structural** for the three refusals and the carried field | `::checkContactsContainerAndGroupMembershipSurvivesTheRead`; `test_container_and_group_membership_survives_in_the_existing_envelope` |
| 4 | **Permission denial and revocation safe** | **Proven, both halves.** Denial fails closed exhaustively with no `default`; a grant withdrawn **between two calls** makes the second refuse, and the fixture's own counter proves the source was never touched again | **Swift runtime, in-process** for the refusals, the zero-read measurement and the revocation; **Python-structural** for the exhaustive `switch`, the two-call-sites assertion and the no-stored-state assertion | `::checkContactsAuthorizationFailsClosedAndRevocationIsNotAStalePage`; `test_contacts_authorization_fails_closed_and_cannot_degrade_to_an_empty_page`, `test_a_revoked_contacts_grant_cannot_be_served_from_a_cache` |
| 5 | **Read-only API surface** | **Proven at Swift link time, unchanged from WP-15**, plus a closed seam and a closed store-member set. `CNSaveRequest` is named nowhere in this repository, in any spelling | **Swift link-time** (the shipping target links no Apple framework — `otool -L` in §B), plus **Swift compile-time** for the probe, plus static guards over **every** Swift file under `native/` | `test_no_swift_in_the_native_tree_names_a_contacts_mutation_symbol`, `test_no_swift_in_the_native_tree_constructs_a_contact_store`, `test_the_contacts_mechanism_seam_declares_only_read_operations`, `test_the_four_probes_are_compile_only_and_never_linked_into_the_host` |
| 6 | **Observations, not truth (§22)** | **Proven for what a guard can prove**: no scoring, sentiment, trait or aggregation vocabulary exists in this package, ambiguity is carried in a non-optional `unknown` assurance, and nothing is wired to the relationship plane | **Swift compile-time** for "there is no field for a judgement"; **Python-structural** for the vocabulary scan and the ambiguity field | `test_the_contacts_adapter_judges_nobody_and_reaches_no_relationship_plane` |
| — | **A live read of real contacts** | **NOT PROVED, and nothing in this package attempts it.** No contact store is constructed anywhere in this repository, no authorization is requested, and no address book was enumerated. Every behavioural claim above is over a seeded in-process fixture | **Nowhere.** Needs an operator TCC grant on real hardware — see §F | — |
| — | **Performance** | **NOT PROVED.** The fixture's timings are the fixture's, not a contact store's, and they are not reported here for that reason | **Nowhere** | — |

---

## B. What the shipping target links after this change

`swift build` from clean (`rm -rf .build`), then `otool -L` on the two products
SwiftPM actually links. This is WP-15's control 1, re-derived at this head rather
than cited.

```
.build/arm64-apple-macosx/debug/AppleSourceHostContractChecks:
	/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1356.0.0)
	/System/Library/Frameworks/Foundation.framework/Versions/C/Foundation (compatibility version 300.0.0, current version 4040.1.255)
	/usr/lib/libobjc.A.dylib (compatibility version 1.0.0, current version 228.0.0)
	/usr/lib/swift/libswiftCore.dylib (compatibility version 0.0.0, current version 0.0.0)
	/usr/lib/swift/libswiftCoreFoundation.dylib (compatibility version 1.0.0, current version 120.100.0, weak)
	/usr/lib/swift/libswiftDarwin.dylib (compatibility version 1.0.0, current version 347.0.12)
	/usr/lib/swift/libswiftDispatch.dylib (compatibility version 1.0.0, current version 56.0.0)
	/usr/lib/swift/libswiftIOKit.dylib (compatibility version 1.0.0, current version 1.0.0, weak)
	/usr/lib/swift/libswiftObjectiveC.dylib (compatibility version 1.0.0, current version 950.0.0, weak)
	/usr/lib/swift/libswiftXPC.dylib (compatibility version 1.0.0, current version 105.0.14, weak)
```

`.build/arm64-apple-macosx/debug/AppleSourceHostFixtureExport` is the same list,
differing only in that `libswiftDispatch` is weak there. **No Contacts, no
EventKit, no MailKit, no ScriptingBridge, no ServiceManagement.** Identical to the
base head's list; adding a contacts adapter changed nothing about it.

`swift package describe --type json` at this head reports all **four** probes as
`library` targets with `product_memberships: null` and `target_dependencies:
null`, while the only two executables depend on `AppleSourceHost` alone. So
nothing links them, and the probes' claim stops at **compilation**, which is the
level stated everywhere in this document.

**This property is defended, and the defence was measured here rather than
argued.** §G's plant P1 gives the shipping target
`dependencies: ["AppleContactsShapeProbe"]`; the build still succeeds and
`otool -L` on the product then shows

```
	/System/Library/Frameworks/Contacts.framework/Versions/A/Contacts (compatibility version 0.0.0, current version 3804.100.1)
```

linked in. The guard reddens on it. Reverted and rebuilt, the line is gone.

---

## C. Control 1 — the minimum key set, and why each key earns its place

The framework requires a caller to declare `keysToFetch` up front. Every key
declared is personal data pulled out of a store and into a process, so the
enumeration is the whole budget:

| Key | Framework spelling | Justified against | Why it is content-free |
|---|---|---|---|
| `identifier` | `CNContactIdentifierKey` | acceptance's **stable source identity** | An opaque provider key. Without it there is no record, only a count. It names nobody |
| `structuralType` | `CNContactTypeKey` | acceptance's observation being an *observation* (§22) | Two cases, person and organization. A consumer that reads an organization row as a person has been handed a false statement about somebody who does not exist. It names nobody |

**And that is the whole set.** `ContactsFetchKey` has exactly two cases and
`ContactsMinimumKeySet.keys` is all of them, so there is no third key this package
knows how to ask for. That is the strongest available form of the control: a wider
request is not *refused*, it is **unspellable**. `test_…_is_frozen_and_holds_no_content_key`
pins the pair from outside Swift, and `test_no_content_bearing_contacts_key_is_named_anywhere_under_native`
scans **every** Swift file under `native/` — probes included — for thirty-two
spellings of a content key.

**Not in the set, and deliberately:** given name, family name, middle name,
nickname, name prefix and suffix, organization name, job title, department, email
addresses, phone numbers, postal addresses, URL addresses, social profiles,
instant-message addresses, birthday, dates, relations, note, image data and
thumbnail image data. None of them is named anywhere under `native/`.

**The finding worth stating.** Acceptance's third criterion — group and container
membership — sounds like the one that needs more data and needs **none**. The
framework reaches membership through `predicateForContactsInGroup(withIdentifier:)`
and `predicateForContactsInContainer(withIdentifier:)`, which are *queries*, not
fetched keys. So the structure survives at zero cost against the key budget.

**What this does not prove, stated plainly.** A mechanism that fetched a wide key
set and reported only the narrow one is **undetectable from the adapter**. The
adapter tells the mechanism what it may fetch and re-checks what every record says
it was built from; it cannot see inside a mechanism that lies. That is the same
class of limit as WP-17's undetectable truncation, and the seam documents it
rather than the adapter pretending to enforce it.

---

## D. Control 2 — identity, and the hazard that is specific to contacts

The framework's contact identifier is documented as stable, and it is — right up
to the paths where it is not. A restore from backup, an account removed and
re-added, a container re-synced from a server: each can re-mint the identifiers of
every contact it holds. **A stored identity recording only the identifier is a
correct-looking key that quietly starts pointing at somebody else, or silently
produces a second record for one person.**

Two mechanisms together, and neither alone is enough.

**1. The epoch is inside the identity**, in WP-16's shape. When the epoch changes,
every identity changes, and a reconciler is handed a *disjoint* key space instead
of a set of mismatched contents. A disjoint key space is visible; mismatched
contents under a stable-looking key are not. `::checkContactsIdentityCarriesItsEpochAndIsBranchInjective`
asserts the disjointness directly — `Set(afterReMint).isDisjoint(with: Set(before))`
— because a *partial* overlap is exactly the state in which a reconciler silently
produces a duplicate person.

**2. Every observation states its own assurance.** `ContactIdentityAssurance` has
three answers and they are never collapsed:

| Answer | Meaning |
|---|---|
| `stableWithinEpoch` | The mechanism vouches for the key for as long as the epoch is unchanged. There is deliberately no case meaning "stable forever", because no source offers one |
| `reMintedInThisEpoch` | The mechanism knows this is not the key it published for the same person before. Carried, never dropped: a re-mint reported as an ordinary new contact is how one person becomes two |
| `unknown` | The mechanism will not characterise the key. Carried rather than rounded up, which is brief §22 in one field |

The field is non-optional, and a guard asserts that no field of the observation is
optional: an absent field is read as an absent fact.

**A mechanism that cannot name its epoch is refused**
(`contactsIdentityEpochUnavailable`), in the shape WP-17 refuses a mechanism that
cannot publish an occurrence's original start. A result whose declared epoch
disagrees with the keys it minted is refused too
(`contactsIdentityEpochMismatch`).

### The identity tree, and why it needs a discriminator

Contacts branch where a calendar nests. A container holds groups **and** contacts,
and a contact belongs to zero or more of its container's groups, so two different
things sit at the same depth:

| Level | Type | Composed form | Separators |
|---|---|---|---|
| account | `ContactsAccountIdentity` | `account` | 0 |
| container | `ContactsContainerIdentity` | `account:container` | 1 |
| group | `ContactsGroupIdentity` | `account:container:group:<key>` | 3 |
| contact | `ContactIdentity` | `account:container:contact:<epoch>:<key>` | 4 |

Injectivity comes from three facts together: the component alphabet **excludes
`:`**, so a composed identifier splits back into its fields unambiguously; field 2
is a fixed discriminator drawn from a closed two-member set that no component can
forge; and each level is a strict prefix of the level below it, which is asserted
rather than assumed. The contract check builds a group and a contact with the
*same* trailing key and requires them to differ.

Composition **refuses** rather than trimming: five maximum-length components
genuinely exceed `NativeSourceOpaqueID`'s 200-byte ceiling, so
`contactsIdentityTooLong` is a reachable path and not decoration.

**A finding recorded rather than discovered later.** On this platform the local
container's contact identifiers are not bare UUIDs — they carry a suffix after a
colon. `:` is the composition separator, so a live mechanism must encode such an
identifier into this alphabet before it reaches the seam, and must **refuse**
rather than trim if the encoded form does not fit. Nothing in this repository does
that encoding, because nothing in this repository reads a contact.

---

## E. Control 3, the bounds, and what "bounded" honestly means here

`account → container → group → contact` survives the read in the vocabulary the
protocol already has. **No parallel envelope was invented**: an account is a
`NativeSourceAccount`; a container and a group are both `NativeSourceBucket`s, and
the group's `parentID` names its container. Membership rides on the observation as
a canonically ordered `groupKeys` list.

Three different failures, three refusals:

| Failure | Refusal | Why it is not the same failure |
|---|---|---|
| A group whose container discovery never published | `contactsMembershipInconsistent` | A place in the tree that does not exist. Attaching it to whichever container looks plausible is how a contact ends up filed under the wrong account |
| A contact claiming membership of a group nothing published | `contactsUnknownGroup` | A dangling edge a consumer will later resolve to whatever next takes that key |
| A mechanism that cannot report membership at all | `contactsMembershipUnavailable` | The empty-versus-unavailable distinction one level down from the page. "In no group" is a statement; a mechanism that discards membership would make that statement about everybody |

The last is the one worth dwelling on, and it is **measured rather than
asserted**: `FixtureContactsFault.forgetGroupMembership` produces a page that is
well-formed, passes every check the adapter makes, and is missing a fact. The
harness catches it by *comparing two reads*, not by the adapter noticing — which
is precisely why the seam refuses a mechanism that cannot report membership,
rather than trusting one that says it can.

### The bounds

| Bound | Value | Behaviour | Why |
|---|---|---|---|
| `maximumContactsIdentityComponentBytes` | 64 | Composition **refused** (`contactsIdentityTooLong`) | A trimmed identity aliases two people onto one record |
| `maximumContactGroupMemberships` | 64 | Observation **refused** (`contactsGroupLimitExceeded`) | A shortened membership list is indistinguishable from a person genuinely in fewer groups |
| membership ordering | strictly ascending | Observation **refused** (`contactsMembershipInconsistent`) | Two equal memberships must not encode two ways |
| `maximumPageSize` / `maximumCursorBytes` | 100 / 512 | Refused, unchanged from WP-15 | Reused rather than re-minted, so the host and the admitting application cannot drift. Asserted against the Python contract's own constants |

Every one is enforced on the initialiser **and** on the decode path. A bound that
only exists on an initialiser holds for values built in Swift and not for the same
values arriving as JSON, which is the shape a host is actually handed.

### "Bounded" — the overstatement this package refused to make

`ContactsTraversalResult.enumeratedEveryContainer` names **containers**, not
pages, and the name is the finding. The framework offers a container-scoped and a
group-scoped predicate, which are genuine source-side *scope* bounds — reading one
container does not require walking the others, and a mechanism that says otherwise
is refused (`contactsUnboundedEnumeration`). It offers **no limit and no offset at
all**: neither `unifiedContacts(matching:keysToFetch:)` nor
`enumerateContacts(with:usingBlock:)` takes one. So a *page* is necessarily a
slice a live mechanism takes after materialising a container, and calling that
"bounded" in the way WP-17's horizon is bounded would be false. It is recorded
here instead.

Truncation is declared and the declaration is cross-checked: a mechanism claiming
more must have filled the page and left an observation to resume from. Paging the
fixture container in twos is asserted to reproduce the single-page read exactly,
with no duplicate and nothing missing. Four mechanism faults exercise the
adapter's re-checks rather than leaving them written: a whole-store sweep, keys out
of order, more-available without filling the page, and another container's people.

### The other honest gap: there is no per-contact revision

The framework publishes **no per-contact modification date**. There is nothing to
put in `sourceModifiedUnixMilliseconds` and it is `nil`; `sourceRevision` is the
identity epoch, which is the only revision the source actually offers. It tells a
consumer when a whole container's keys were re-minted and tells it **nothing**
about whether one person's row changed. A synthesised per-record timestamp would
look like the second and be the first, so none is synthesised. A consumer wanting
change detection at record level will have to diff payloads; that is a limitation
of the source, and it is stated rather than papered over.

---

## F. What requires an operator, and what each would unlock

| Gate | What is missing | Would unlock |
|---|---|---|
| **EXT-04** | A TCC contacts grant for the helper on a pilot Mac | Everything this package refuses to guess at: whether a contact identifier actually survives a restore, a re-sync, or an account removed and re-added — which is the whole of control 2 and is **not** answerable from a fixture; whether a container's identifiers are re-minted together or individually; whether `unifiedContacts` unification changes identifiers across a merge; whether a CardDAV-backed container reports group membership at all; whether materialising a large container is usable at speed |
| **EXT-03** | Apple signing identity, notarization profile, and an `Info.plist` carrying `NSContactsUsageDescription` | Any of the above at all, since an unsigned helper cannot hold a durable TCC grant |
| **EXT-05** | An eligible pilot Mac and `SMAppService` registration | Lifecycle evidence for the helper that would host the mechanism |
| **EXT-06** | An approved non-personal Apple test account with seeded synthetic contacts | The only honest way to measure performance and container-scale behaviour. **No live personal address book may be used for this, and none was** |
| — | A decision, not a grant: whether a live mechanism is written at all | The seam has one implementation, `FixtureContactsMechanism`, and nothing else in this repository. Writing a live one means linking Contacts somewhere, and *where* is an architectural decision this package deliberately does not take |

**There is no read-only contacts grant on this platform.** macOS 14 split calendar
consent into `fullAccess` and `writeOnly`; contacts consent has no equivalent
split, and the framework's partial-access case is **explicitly unavailable on
macOS** in this SDK — measured, not assumed, by attempting to name it in the probe
and watching the compiler reject it. So one grant covers both directions, one
store answers both `unifiedContacts(matching:keysToFetch:)` and the execution of a
save request, and the only enforceable read-only boundary is the client not
linking the framework — which is what §B measures.

---

## G. Non-vacuity — controlled reversions

Every guard authored by this package was planted against, observed red **for the
intended reason**, and reverted; each modified file was then verified
byte-identical by SHA-256 and each created file removed. **The campaign's own
lesson applies to this table: a guard you author is not a guard you are subject
to**, so §G3 attacks this module's own new guards with the shapes that historically
defeated WP-16's and WP-17's, and includes **controls that must stay green**.

A red Swift check traps at top level; the driver reports the signal (`-5`), which
a shell reports as exit **133**. A healthy architecture plant is `1 failed, 18
passed` in `tests/architecture/test_wp18_contacts_adapter.py`, which holds **19**
tests; a plant that trips two guards reads `2 failed, 17 passed`.

### G1. The link surface — the plant whose *consequence* was measured

| # | Plant | What went red | Measured consequence |
|---|---|---|---|
| P1 | `.target(name: "AppleSourceHost", dependencies: ["AppleContactsShapeProbe"])` | `test_the_four_probes_are_compile_only_and_never_linked_into_the_host`: *"AppleContactsShapeProbe is named 2 times in Package.swift as a quoted token… assert 2 == 1"* | The build **succeeds**, and `otool -L` on `AppleSourceHostContractChecks` then shows `/System/Library/Frameworks/Contacts.framework/Versions/A/Contacts`. Reverted and rebuilt: gone, and `otool -L \| grep -c Contacts` is `0` |

### G2. The architecture guards — nineteen plants

| # | Plant | Guard that went red, and the observed message |
|---|---|---|
| P2 | `CNSaveRequest.Type` returned from the probe, **verified to compile first** (`swift build`, `Build complete!`) | `test_no_swift_in_the_native_tree_names_a_contacts_mutation_symbol`: *"…ContactsShape.swift': ['CNSaveRequest']} name a contacts mutation symbol"* |
| P2b | `CNContactStore.execute` — **unapplied, no parentheses**, disambiguated by a return type. Compiles | `test_no_swift_in_the_native_tree_constructs_a_contact_store`: *"…names the contact-store members ['execute'], which are not in the read-only closed set…"*; and `test_the_contacts_probe_reaches_no_store_in_any_spelling` on the same closed set. **3 failed, 16 passed** |
| P3 | `case emailAddresses = "contact_email_addresses"` added to `ContactsFetchKey` | `test_the_minimum_contacts_key_set_is_frozen_and_holds_no_content_key`: *"the contacts fetch-key vocabulary is now […('emailAddresses', 'contact_email_addresses')] and the frozen minimum is…"* |
| P3b | `CNContactGivenNameKey` added to the probe's minimum key list | `test_no_content_bearing_contacts_key_is_named_anywhere_under_native`: *"…['CNContactGivenNameKey']} name a content-bearing contacts key"* |
| P4 | `extension ContactsMechanism { func purgeContact(…) }` in a **new** file, `ContactsMechanismExtras.swift` | `test_the_contacts_mechanism_seam_declares_only_read_operations`: *"the contacts mechanism seam now offers ['accounts', 'authorizationState', 'contacts', 'containers', 'groups', 'purgeContact'], declared across [ContactsMechanism.swift, ContactsMechanismExtras.swift]"* |
| P4a | The same extension appended to an **existing unrelated** file, `HostTelemetry.swift`, with a `}` hidden inside a string literal above the member — WP-17's B4 shape | same guard, naming `HostTelemetry.swift` and `saveContact`. The literal-blanking pass is why the member below the hidden brace is still seen |
| P4b | `var isFavourite: Bool` with its `{ get set }` block **on the following line** | same guard, on the settable-property assertion: *"the contacts mechanism seam declares the settable properties ['isFavourite']"* |
| P4c | **CONTROL**: `extension ContactsMechanismDescriptor` with `purgeContact`, a settable `var` and a `subscript` | correctly **GREEN — 19 passed**. It is not the seam, and `\b` is why the guard knows that |
| P4d | **CONTROL**: `extension FixtureContactsMechanism` — a conformer, not the protocol | correctly **GREEN — 19 passed** |
| P5 | The `.restricted` arm returns instead of throwing | `test_contacts_authorization_fails_closed_and_cannot_degrade_to_an_empty_page`: *"one of the three non-authorized states no longer throws… assert 2 == 3"* |
| P6 | `private let cachedPage: NativeReadPage? = nil` added to the adapter | `test_a_revoked_contacts_grant_cannot_be_served_from_a_cache`: *"the contacts adapter now stores [… 'private let cachedPage: NativeReadPage? = nil']. Its only stored property may be the mechanism"* |
| P6b | `readContacts` stops calling `requireAuthorization()` | same guard — *"authorization is called 1 times in the contacts adapter and there are two operations"* — **and** the fail-closed guard's per-entry-point assertion. **2 failed, 17 passed** |
| P7 | The undeclared-group refusal removed from the adapter | `test_container_and_group_membership_survives_in_the_existing_envelope`: *"the adapter no longer raises contactsUnknownGroup"* |
| P8 | The epoch removed from the composed contact identifier | `test_a_contact_identity_carries_its_epoch_and_states_its_own_assurance`: *"the epoch is no longer part of the composed record identifier, so a re-mint produces the same key for a different person"* |
| P8b | `:` added to the contacts identity alphabet | `test_the_contacts_identity_alphabet_excludes_the_composition_separator`: *"…would compose to one identifier and silently become one person"* |
| P9 | `maximumContactGroupMemberships` drifted to `65` | `test_the_contacts_bounds_are_frozen_in_the_protocol_and_agree_with_python` |
| P10 | `ContactObservation.init(from:)` rewritten to assign its five fields directly — WP-16's C3 shape, which keeps the literal a naive guard looks for | `test_every_invariant_bearing_contacts_value_validates_on_the_decode_path`: *"ContactObservation's decoder no longer routes through its validating initialiser"* |
| P11 | `public let affinityScore: Int` added to the observation | `test_the_contacts_adapter_judges_nobody_and_reaches_no_relationship_plane`: *"…['affinity']} name the vocabulary of a judgement about a person"* |
| P12 | `NSContactsUsageDescription` added to a string literal in the native tree | `test_no_entitlement_or_usage_declaration_was_added_for_the_contacts_mechanism` |
| P13 | A second Swift file added to the contacts probe directory | `test_the_wp18_scan_is_reading_the_contacts_adapter_at_all`, on the exemption-set floor: *"assert 2 == 1"* |

### G3. Attacks on this module's own guards

| # | Attack | Result |
|---|---|---|
| A1 | `CONTACTS_CONTENT_SURFACE` emptied to one never-occurring token **and** a real `import Contacts` / `CNContactGivenNameKey` / `CNContactEmailAddressesKey` file planted under `Sources/AppleSourceHost/` | RED on the membership floor: *"the contacts content table no longer names ['CNContactGivenNameKey']"* |
| A2 | The table padded back to **forty never-occurring** tokens, leak still present | RED for the original reason: *"…['CNContactEmailAddressesKey', 'CNContactGivenNameKey']} name a content-bearing contacts key"* |
| A3 | The table padded to forty by **repeating** one real token | RED on the no-duplicates assertion: *"…repeats a symbol… assert 32 == 72"* |
| A4 | **CONTROL**: the real leak with the table left intact | RED for the original reason. The floors are an addition to a working guard, not a replacement for one |
| A5 | `typealias Store = CNContactStore` then `Store.groups(matching:)` — the aliased spelling no member regex can see | RED on the `typealias` row |
| A6 | `func leak(_ handed: CNContactStore) {}` — a store handed in as a **parameter**, naming no member of the type and constructing nothing (WP-17's B1 shape) | RED on the parameter row, in **both** the tree-wide guard and the probe-local one. **2 failed, 17 passed** |
| A7 | **CONTROL**: `CNSaveRequest`, `CNContactStore()`, `CNContactStore.execute`, `CNContactGivenNameKey`, `requestAccess` and `import ContactsUI` — all in a **comment line only** | correctly **GREEN — 19 passed**. Deliberate: a guard that reddens on the paragraph explaining it is a guard somebody deletes |
| A8 | The probe emptied to a bare `import Contacts` plus one metatype. Every "nothing forbidden appears" assertion passes | RED on the resolution floors: *"the contacts probe names the contact-store members ['Type', 'self'] and the closed set is [seven]"*. **2 failed, 17 passed** |
| A9 | The `import Contacts` leak under `Sources/AppleSourceHost/`, run against WP-15's and WP-12D's modules too | RED in `test_wp15_native_host_admission.py::test_the_shipping_host_holds_no_write_path_into_an_apple_source`: *"…['CNContactStore', 'import Contacts']} name a mutating Apple symbol or a personal-data framework import"*. **3 failed, 36 passed** across the three modules |

### G4. The Swift contract checks — eight plants

| # | Plant | What went red | Exit |
|---|---|---|---|
| S1 | `requireAuthorization` treats `.notDetermined` as authorized — the "try it and see" change | `…failed("Expected provider failure permissionDenied")` | 133 |
| S2 | `readContacts` stops re-checking authorization — **the revocation defect** | `…failed("Expected provider failure permissionDenied")` | 133 |
| S3 | The epoch removed from the composed contact identifier | `…failed("The contacts identity levels are no longer distinguished by their shape")` | 133 |
| S4 | The observation stops refusing a key set that is not the frozen minimum | `…failed("Expected error contactsKeySetWidened")` | 133 |
| S5 | The membership ceiling removed from the observation | `…failed("Expected error contactsGroupLimitExceeded")` | 133 |
| S6 | The undeclared-group refusal removed from the adapter | `…failed("Expected error contactsUnknownGroup")` | 133 |
| S7 | `ContactObservation.init(from:)` assigns its fields directly | `…failed("Malformed ContactObservation decoded successfully")` | 133 |
| S8 | The adapter accepts a mechanism that walked every container | `…failed("Expected error contactsUnboundedEnumeration")` | 133 |

**Every plant was reverted** — `git checkout --` for modified files, `rm` for the
seven created ones — and every restored file verified **byte-identical by
SHA-256**. **No plant remains in the tree**: `git status --porcelain
--untracked-files=all` is empty at the head below, `swift build` is clean and
`AppleSourceHostContractChecks` prints `PASS (36 checks)`.

---

## H. What WP-18 deliberately did not do, and what it leaves standing

* **No live mechanism.** The seam has one implementation,
  `FixtureContactsMechanism`, and it is seeded by hand with `account-alpha`,
  `container-alpha`, `group-alpha`, `person-alpha`. Writing a live one requires the
  consent this package refuses to obtain and a decision about which target may
  link the framework.
* **No contact content.** There is no name, email address, telephone number,
  postal address, birthday, photograph or note field anywhere in the contacts
  types. A future package that needs one owns bounding it, in WP-16's shape, and
  owns arguing for it against §C.
* **Nothing is wired to the relationship plane.** Contacts data will eventually
  feed Relationship Intelligence; wiring that link is explicitly a different
  package, and WP-12's NOTEs 5/6/7 activate together the moment a capability seat
  reaches it. Nothing here reaches it.
* **No baseline plane, no migration, no schema change, no capability seat.** The
  single Alembic head remains `8f2b6c4d1a37` over 26 revisions and the capability
  set remains nineteen.
  `git diff 06282a3..HEAD -- src/ apps/ scripts/ migrations/ ops/ web/` is empty.
* **The native plane stays quarantined.** Nothing here is reachable from a
  transport and no production module references any of it.
* **Two exemption sets were widened by one directory each**, so the Contacts shape
  probe may import Contacts:
  `test_wp15_native_host_admission.py::_swift_outside_the_probe` and
  `test_wp17_calendar_adapter.py`'s `PROBES` / `PROBE_TARGETS`. The *assertions* are
  unchanged — every Swift file under `native/` outside the compile-only probes may
  still name none of `MUTATING_APPLE_SURFACE` — and the new probe is not excused: it
  is held to a closed store-member set, a closed import set, a construction list, a
  no-content-key scan and resolution floors. Both widenings are measured: the
  exemption sets are asserted at **four** in two modules, so a fifth is a decision
  somebody has to make there (plant P13).
* **`ContactsMechanismKind.platformContactStore` is declared and never
  constructed.** It names the mechanism a live implementation would declare, in the
  shape `MailMechanismKind.appleMailAutomation` and
  `CalendarMechanismKind.eventKitStore` already established. If the next owner
  judges that dead under §2, it is one line.
* **`ContactsContainerKind` is carried and nothing branches on it.** It is
  provenance for control 2 — a local container's keys survive a re-sync because
  there is no server to re-sync from, and a server-backed one's may not — and a
  consumer weighing an assurance answer needs it. It is a four-case enum on the
  container descriptor and it costs nothing; if the next owner disagrees it is also
  one line.
* **`HostTelemetry` gained two content-free failure classes**,
  `contacts_mechanism_unsupported` and `contacts_bound_refused`, mirroring the
  calendar pair. The exhaustive `switch` over `NativeSourceContractError` made this
  compulsory rather than optional, which is the point of it being exhaustive.
* **The seam guard scans from `public protocol ContactsMechanism` to the end of the
  file** for the declaration, which is safe only because that protocol is the last
  declaration in `ContactsMechanism.swift`. A declaration added below it would be
  scanned as if it were part of the seam. That direction fails safe — it reddens on
  something legal rather than passing something illegal. Protocol *extensions* are
  read to their own balanced closing brace instead, across the whole native tree,
  which is WP-17's correction adopted here from the start.
* **What is still trusted, and named as trusted rather than dressed as enforced.**
  These are **text** scans, not parses. Whole-line comments are stripped by choice,
  which makes prose invisible to them and trailing comments invisible too. A Swift
  file outside `native/apple-source-host` would be outside every scan here; none
  exists. And the strongest guarantee in the package is not a text scan at all —
  `otool -L` on both built products shows no Apple framework, which is a link-time
  fact.

---

## I. Verification at this head

Every number below was produced here, at this head, and observed rather than
inferred.

| Command | Exit | Observed |
|---|---|---|
| `swift build --package-path native/apple-source-host` (after `rm -rf .build`) | 0 | `Build complete!` — **0 warnings, 0 errors**, all **four** probes compiled (four `Compiling …Probe` lines). The run ends at `[51/51]`; SwiftPM revises that denominator mid-run, so treat it as evidence the build completed rather than as a constant |
| `otool -L` on both linked products | 0 | libSystem, Foundation, libobjc and the Swift runtime. **No Apple framework** — verbatim in §B |
| `.build/arm64-apple-macosx/debug/AppleSourceHostContractChecks` | 0 | `AppleSourceHostContractChecks: PASS (36 checks)` — was **30** at the base |
| `.build/arm64-apple-macosx/debug/AppleSourceHostFixtureExport` | 0 | unchanged export |
| `pytest tests/architecture -q` | 1 | **2080 passed, 1 failed.** Base measured at `06282a3`: **2061 passed, 1 failed**. 2061 + 19 = 2080, and the 19 are the new architecture module in full |
| `pytest tests/schema tests/database -q` | 0 | **286 passed** — identical to the base; this package adds no test there |
| `ruff check .` | 0 | All checks passed |
| `ruff format --check .` | 0 | **590 files** already formatted — 588 at the base plus **two**, and the second is worth naming rather than hand-waving: measured per directory over a clean `git archive` of each commit, `tests` moves 188 → 189 for the new architecture module and `docs` moves 92 → 93 for this record, because ruff's file count includes Markdown as well as Python. Base and head archives were both measured with `--no-cache`, since a cached run reports a different figure |
| `mypy` per repo config | 0 | no issues in **177 source files** — unchanged, because no Python source was added |
| Alembic revisions | — | single head `8f2b6c4d1a37` over **26** revision files — unchanged |
| Capability seats | — | **19** — unchanged |

**The one failure is the pre-existing, unowned one**,
`test_ci_invokes_mypy_over_the_declared_tree.py::test_every_python_root_is_type_checked_or_named`,
which is red at the base head for `web/node_modules` and is not this package's.
**No test was weakened, skipped, xfailed or deleted to reach any of these
numbers.** No existing assertion changed its expectation. Three existing files
changed for reasons named here and nowhere else: two exemption sets widened by one
directory (§H), and `docs/plans/mcv-completion-plan.md` §3 moved from one hundred
and sixty-one to one hundred and sixty-two test modules, which is what
`test_spelled_counts_match_the_sets_they_name.py` requires of the tree it counts.

**A total for the full suite is not reported.** The full run exceeds this
environment's tool ceiling, so the two selections above were run separately; adding
them would be a composed figure presented as a measured one.

---

## J. The privacy boundary, stated as a fact rather than an intention

* **No contact store was constructed, anywhere, at any point.** The string
  `CNContactStore` appears in exactly **two** Swift files — this package's probe
  and WP-15's multi-framework probe — and
  `test_no_swift_in_the_native_tree_constructs_a_contact_store` asserts that list
  by name so the scan cannot go quiet. In those two files it appears only as a
  metatype (`CNContactStore.self`, `CNContactStore.Type`), as the receiver of
  unapplied method references, and as the parameter of the curried function types
  those references necessarily have. The set of members named anywhere in the tree
  is closed at **seven**, every one a read or a metatype.
* **No authorization was requested.** `requestAccess` and every sibling are named
  nowhere in the tree, and a guard scans the **whole** native tree, probes
  included, to keep it that way.
* **`CNSaveRequest` is named nowhere in this repository**, in any spelling, nor is
  any mutable contacts type, nor `import ContactsUI`, nor any add/update/delete
  member. Twenty spellings are scanned tree-wide.
* **No content-bearing key is named anywhere under `native/`.** Thirty-two
  spellings are scanned tree-wide, probes included.
* `~/Library/Application Support/AddressBook` was not read, listed, `stat`-ed or
  searched. No `sqlite3`, `contacts` CLI or AppleScript invocation was made
  against it, at any point, by any command in this package's history.
* **Every fixture value is obviously synthetic**: `account-alpha`,
  `container-alpha`, `container-beta`, `group-alpha`, `group-beta`, `group-gamma`,
  `person-alpha`, `person-beta`, `person-gamma`, `org-delta`, `person-epsilon`,
  `epoch-one`, `epoch-two`, and the labels `Account Alpha`, `Container Alpha`,
  `Group Alpha`. There is no name, email, telephone, address, birthday or
  photograph field in any contacts type, so there is nothing here for a real one to
  be mistaken for.
* **The one place a label crosses the seam, named rather than hidden.**
  `NativeSourceBucket.displayLabel` is not optional, so a container and a group
  carry a human-readable label — as a calendar does in WP-17. A live mechanism
  would fill those from the container's and group's own names. Those are names of
  *collections*, never of a person, and they are not fetched through a key
  descriptor, so they are outside the key budget in §C. No live label was read to
  produce anything here.

---

## K. Post-review corrections — the two plants that went green

An independent review of this package raised **no BLOCKER**. It planted
twenty-four controlled violations against the guards; **twenty-two reddened
correctly and two did not.** Both are recorded here rather than absorbed, and
both corrections are **test-only**: no Swift implementation file changed, and the
adapter, the mechanism, the identity types, the fixture and the probe are
byte-identical to what the review read.

### K1. A leading block comment made every text guard fail open

**What the reviewer proved.** This line, planted in
`Compatibility/AppleContactsShapeProbe/ContactsShape.swift`, **compiled**
(`swift build`, exit 0) and passed **all 50 guards** plus
`AppleSourceHostContractChecks`:

```swift
/* shape */ public static func plantedSave() -> CNSaveRequest.Type { CNSaveRequest.self }
```

**Cause.** `_without_comments(...)` dropped any line whose first non-space token
was `/*`. A comment that ends mid-line leaves code after it, so a forbidden
symbol written that way was invisible to every text guard — a **fail-open**
direction, and the exact inverse of what §G3/A7 deliberately permits. This is
**not a defect WP-18 introduced**: the helper is copied verbatim from WP-15 and
was identical in WP-16's, WP-17's and WP-18's modules.

**What changed.** `_without_comments` now blanks closed `/* … */` **spans**
before the line filter, preserving newlines, so the code beside a comment stays
on the line it was written on. An opener with no closer still starts its line
with `/*` and is still dropped, and whole-line `//` prose is still dropped —
§G3/A7's control is untouched by design. Because the helper is shared, **the
identical correction was applied to all four modules**:
`tests/architecture/test_wp15_native_host_admission.py`,
`test_wp16_mail_adapter.py`, `test_wp17_calendar_adapter.py` and
`test_wp18_contacts_adapter.py`. No other test changed its outcome.

**Red then green.** The plant above was replanted, `swift build` exit **0**
(`Build complete!`), and
`test_no_swift_in_the_native_tree_names_a_contacts_mutation_symbol` went red:
*"{'native/apple-source-host/Compatibility/AppleContactsShapeProbe/ContactsShape.swift':
['CNSaveRequest']} name a contacts mutation symbol"* — **1 failed, 18 passed**.
Reverted: **19 passed**, and the probe verified byte-identical by SHA-256
(`91c27ec5…0565`). Run against the same source, the pre-correction helper reports
`CNSaveRequest` **absent** and the corrected helper reports it **present**, which
is the whole difference.

**Prose is still invisible, verified rather than assumed.** A `///` line naming
`CNSaveRequest` and `requestAccess` was planted in the contacts probe: `swift
build` exit 0 and **63 passed** across the WP-15/16/17/18 modules, still green.
Reverted and verified byte-identical. The tree already carries the same shape in
`AppleFrameworkCompatibilityProbe/FrameworkCompatibility.swift`, which names both
symbols in prose and is green at this head.

### K2. A new public method with no authorization check passed everything

**What the reviewer proved.** A **third** public read method in
`BoundedContactsReadAdapter.swift` reaching `mechanism.contacts(query)` with no
`try requireAuthorization()` compiled and passed everything — `50 passed`,
harness `PASS (36 checks)`.

**Cause.** `test_a_revoked_contacts_grant_cannot_be_served_from_a_cache`
asserted `count("try requireAuthorization()") == 2`. An operation that never
calls it leaves the count at two, so the guard was green on precisely the change
it existed to catch; the fail-closed guard's per-entry-point loop inspected only
the two method names it already knew.

**What changed.** The count is replaced by a quantification over **every**
`public func` in the adapter: each must **open** with `try
requireAuthorization()`, and the total number of calls must equal the number of
public operations. A fourth operation is caught by the same assertion without
anyone remembering to edit it. Control 4 itself is unchanged and remains proved
at runtime for both operations that exist; this closes a **guard-completeness**
gap ahead of a method that does not exist yet.

**Red then green.** A third public method was planted, calling
`mechanism.contacts(query)` with no authorization check. `swift build` exit
**0**. `test_a_revoked_contacts_grant_cannot_be_served_from_a_cache` went red:
*"public func plantedReadContacts opens with `let container = try
ContactsContainerIdentity(bucketID: request.bucketID)` rather than `try
requireAuthorization()`…"* — **1 failed, 18 passed**, and it was the only guard
that spoke. Reverted: **19 passed**, adapter byte-identical by SHA-256
(`599c93ae…9a68`).

### K3. Verification after the corrections

| Command | Exit | Observed |
|---|---|---|
| `pytest tests/architecture -q` | 1 | **2080 passed, 1 failed** — unchanged, including the count. The failure is the same pre-existing, unowned `test_every_python_root_is_type_checked_or_named` |
| `swift build` (after `rm -rf .build`) | 0 | `Build complete!`, **0 warnings** |
| `AppleSourceHostContractChecks` | 0 | `PASS (36 checks)` |
| `otool -L` on both built products | 0 | libSystem, Foundation, libobjc, Swift runtime. **No Apple framework** |
| `ruff check .` / `ruff format --check .` | 0 / 0 | All checks passed / **590 files** already formatted |
| `mypy` per repo config | 0 | no issues in **177 source files** |

No test was weakened, skipped, xfailed or deleted. The one existing expectation
that changed is the `== 2` count named in §K2, which is the defect itself. Every
planted file was reverted and verified byte-identical by SHA-256, and `git status
--porcelain --untracked-files=all` is empty. **No contact belonging to anyone was
read to produce any part of this correction**, and no real name, address,
number or identifier appears in it.
