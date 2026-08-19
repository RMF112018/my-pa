# Specifications

Owning index for versioned behavioral contracts in `RMF112018/my-pa`. Repository-wide routing is [`docs/00_REPOSITORY_SOURCE_INDEX.md`](/docs/00_REPOSITORY_SOURCE_INDEX.md).

| Specification | Status |
|---|---|
| [`mcv-read-only-vertical-slice.md`](mcv-read-only-vertical-slice.md) | Present — proposed for repository review; amended 2026-08-02 for the promoted scope |
| [`canonical-product-definition/`](canonical-product-definition/00_README.md) | Mirror — **ratified** canonical product definition, version 2.3 after the 2026-08-04 Apple Mail, Calendar & Contacts revision; implementation not authorized |
| [`relationship-intelligence-v0.2.md`](relationship-intelligence-v0.2.md) | Mirror — **the current requirements source** for Relationship Intelligence; see the successor notice at the top of the file; implementation not authorized |
| [`relationship-intelligence-v0.3.md`](relationship-intelligence-v0.3.md) | Mirror — **proposed successor** to v0.2, `status: PROPOSED_SUCCESSOR_READY_FOR_OPERATOR_REVIEW`, `implementation_authority: false`; **not controlling**, and no operator decision superseding v0.2 has been recorded |
| [`relationship-intelligence-v0.3-acceptance.md`](relationship-intelligence-v0.3-acceptance.md) | Disposition against `relationship-intelligence-v0.3.md` `RI-AC-001..040`, filed 2026-08-19 alongside `AUDIT-MYPA-RELATIONSHIP-INTELLIGENCE-PR135-20260819-001`. It scores a proposal, not a requirement in force, and carries no status of its own |
| [`quick-capture/`](quick-capture/00_README.md) | Mirror — proposed product specification, implementation not authorized |

The MCV abbreviation follows [`AGENTS.md`](/AGENTS.md): Minimum Viable Candidate. The specification's own prose predates that wording and is preserved as authored.

A specification here describes intended capability, error, and disclosure behavior. It does not authorize runtime implementation, credentials, source-system access, database changes, background scheduling, deployment, or production activation; those require a separately approved goal.

New implementation must use the neutral `my_pa` / `MY_PA_` namespace. Legacy identities may appear only in explicit compatibility or evidence records.

## The ratified canonical product definition

On 2026-08-02 the operator ratified a whole-product definition for `my-pa` **by direct instruction**. It is mirrored at [`canonical-product-definition/`](canonical-product-definition/00_README.md) as package `MYPA-CANONICAL-PRODUCT-DEFINITION-20260802-006`, now version 2.3 after the 2026-08-04 revision.

The instrument is the operator's instruction, not the package. `CURRENT_CANONICAL_PRODUCT_DEFINITION` is a status the package declares about itself, and a self-declared status is not ratification — it is the same class of evidence the repository previously ruled insufficient for the predecessor. See [`../plans/mcv-completion-plan.md`](../plans/mcv-completion-plan.md) `D-19` and section 15.

**What ratification changed.** The repository previously recorded the product direction as *proposed* and named its ratification the largest open operator decision. That question is answered. The direction is now settled product meaning, and the plan's open-decision list is correspondingly shorter.

**What ratification did not change.** Three things, and conflating any of them with acceptance would be the error this section exists to prevent.

- **It grants no implementation authority.** All 20 markdown artifacts carry `implementation_authority: NOT_GRANTED` and `repository_mutation: NOT_PERFORMED` in YAML front matter, and `18_PACKAGE_SOURCE_MANIFEST.json` carries the same under its `authority` object rather than as front matter. The publication receipt independently records `NOT_GRANTED` for implementation, deployment, production activation, and risk acceptance. Ratifying a definition of the product is not authorizing anyone to build it.
- **It does not outrank repository policy.** Under [`AGENTS.md`](/AGENTS.md) section 1, indexed Workspace publications sit at precedence rank 4, below accepted repository specifications, ADRs, and policy at rank 3, and below authenticated runtime and repository state above those. A ratified Drive package is authoritative for *what the product means*, not for what this repository may do. Where it and policy disagree, policy still wins.
- **It does not enlarge the active objective.** The package agrees, and says so itself: its own `OP-05` recommends completing the MCV before an explicit transition, and its roadmap step `R10.1` names finishing repository WP-4 and WP-5 as the prerequisite to everything else. Ratification endorsed the existing sequence rather than displacing it.

### Relationship to `my-pa vNext`

The predecessor, `my-pa vNext` (`SPEC-MYPA-VNEXT-PRODUCT-SYNTHESIS-v1.0`, Drive `17olnyUF5oX-KJWB6owRIJBB8B4QTlRjJhkLG47gio9s`), is **superseded for current whole-product definition and preserved as source history**. This is supersession within one lineage, not a replacement from outside it: the vNext document and the ratified package folder are siblings under the same Drive parent `1Ss71vau8phz7dvXduy7ChIwtxcU3K8Rz`, and the package's own README states the prior package "remains preserved and authoritative source history."

Evidence strength improved across that supersession, which is worth stating because it rarely does. vNext is a native Google Doc and could only ever be verified on identity. The ratified package is stored raw bytes with per-file hashes, so it can be verified byte-for-byte — see the table below.

The owning Quick Capture and Relationship Intelligence specifications below **remain current** where they are more detailed and not explicitly reconciled; the package says so directly. Ratification did not supersede them.

### Version 2.3 raw re-mirror

On 2026-08-04,
`REQ-MYPA-CANONICAL-PRODUCT-APPLE-MCC-MOSS-INTEGRATION-20260804T214700Z`
revised 17 of the 21 numbered artifacts in place and advanced the package from
2.2 to 2.3. Direct raw-file readback verified 21/21 preserved Drive identities,
21/21 parent bindings, and 21/21 byte matches against the new manifest and
readback record. The 17 revised files are replaced byte-for-byte here; the four
unchanged numbered files remain byte-identical.

The selected v2.3 controls follow the Native Apple Reminders mirror policy:
canonical disposition, publication receipt, readback verification, and
coordination-roundtrip receipt are mirrored; the coordination request and
response remain external. Their control folder is
`1PLw2r7MmNXKi2pZxaIRiXTNVg-itiZ99`.

Version 2.3 adds a subordinate feature definition,
`MYPA-NATIVE-APPLE-PERSONAL-DATA-CAPTURE-BRIDGE-FEATURE-PACKAGE-20260804-087`
(Drive folder `13jS8vmsWHvwQQqPksNlwW5r2whH8V8Z5`), user-facing **Apple Mail,
Calendar & Contacts**. It is indexed by identity only. Its inclusion in product
meaning grants no repository implementation, live-personal-data, TCC,
credential, source-mutation, deployment, production, disclosure, retention, or
risk authority. The operator has identified it as a provisional WP-12 after
WP-10 and WP-11, while reserving WP-12 implementation planning to a separate
authorization. It has no pre-MCV or post-MCV disposition yet; that unresolved
sequence boundary is recorded by `D-105` and section 17 of the completion plan.

### Provenance and how strongly it can be trusted

| Field | Value |
|---|---|
| Package folder | `1Z8Aug1_3v6ILgvopY8XpjiNMBySZOCCq`, parent `1Ss71vau8phz7dvXduy7ChIwtxcU3K8Rz` |
| Representation | `stored_raw_bytes` (`text/markdown` and `application/json`) |
| Retrieved | 2026-08-04 by direct `rclone` stored-raw-file readback |
| Repository head the package binds | `195fa54206996dddd6c6e0b6da0872781aa4f5f0`; current reconciliation base is `7ae3917b7d95548883211aa64a12edf99351e59a`, so the publisher's basis is evidence identity rather than a claim of current-head parity |
| Verification | Version 2.3: 21 numbered artifacts, 17 revised and 4 unchanged; 21/21 Drive IDs preserved, 21/21 parent bindings verified, and 21/21 raw readbacks match. Manifest Drive ID `1xxQG_fsUlTxX7VRXOCm8SSCjYF2xPV1j`, 13,899 bytes, SHA-256 `d1b3f7a91fbe07d11f9100346f0ef65f0e3576d35dcf27708f585bb5e6ca038a`. Four mirrored control artifacts are independently pinned by repository tests. |
| Drive member count | The canonical artifact universe is the 21 numbered direct children recorded by the manifest. The v2.3 control folder has 6 direct files, of which 4 are mirrored and 2 are coordination correspondence. Other subfolders under the same Drive folder contain campaign evidence and are not counted as canonical package members. |

**Historical v2.2 inventory.** At version 2.2, thirty-one of forty-two then-counted package members were mirrored here: the 21 numbered artifacts, the 3 MCP-integration control artifacts, the 3 RQC-integration control artifacts, and the 4 Native Apple Reminders control artifacts. The other eleven remained in Drive:

- the coordination **request** and **response** for each of the four roundtrips — Reconciliation, MCP-integration, RQC-integration, and Native Apple Reminders — eight files;
- `COORDINATION-ROUNDTRIP-RECEIPT-…MCP-INTEGRATION-20260802T095600Z.json`, which publishes a SHA-256 for the MCP disposition, the MCP publication receipt, and the MCP readback, and is therefore in-package hash evidence for three mirrored members that the mirror itself does not hold;
- `COORDINATION-ROUNDTRIP-RECEIPT-…RECONCILIATION-20260802-083.json`;
- `PUBLICATION-RECEIPT-MYPA-CANONICAL-PRODUCT-RECONCILIATION-20260802-001.json`, the superseded publication receipt.

The three empty RQC evidence subfolders are also left behind; they are folders rather than files and so are not among the 42 members. Leaving correspondence in Drive follows the precedent set for `quick-capture/`, where governance correspondence was likewise left behind, and `../plans/mcv-completion-plan.md` `D-22`. The two coordination-roundtrip receipts left behind match no stated rule — they are receipts rather than correspondence — and their omission from this inventory is what let the hash-coverage count below be computed over the mirror instead of over the package.

At version 2.2 the declared `repository_head` was `f18e7e3`; version 2.3 moves it to `195fa542`. Both remain historical evidence identities rather than a binding to current repository state.

At version 2.2, ten of the thirty-one mirrored members were control artifacts rather than specifications. The four v2.3 controls add to that historical set and are hash-bound in the current table above and in architecture tests.

**The historical v2.2 controls had uneven hash coverage.** Recomputed across that cycle's 42-member universe, the split was six hashed and four unhashed:

- **All three MCP-integration control artifacts are hashed, two of them twice.** `PUBLICATION-RECEIPT-…MCP-INTEGRATION-…json` hashes the MCP disposition and the MCP readback. `COORDINATION-ROUNDTRIP-RECEIPT-…MCP-INTEGRATION-…json` hashes all three — disposition, publication receipt, and readback. That roundtrip receipt is a package member that is **not mirrored here**, which is exactly why a sweep bounded by the mirror could not see it and recorded the MCP publication receipt as unhashed.
- **Three of the four Native Apple Reminders control artifacts are hashed.** The disposition, the publication receipt, and the readback are all hashed by `COORDINATION-ROUNDTRIP-RECEIPT-…NATIVE-REMINDERS-…json`, which is itself hashed by nothing.

The four with no hash anywhere in the package rest on the Drive-reported byte count alone: all three RQC control artifacts, and the Native Apple Reminders coordination-roundtrip receipt.

**The two cycles have the same shape, and the mirror hides it.** In the package, MCP and Native Apple Reminders are structurally identical — a coordination-roundtrip receipt that hashes its cycle's disposition, publication receipt, and readback, and is itself unattested. The only difference is which artifacts were mirrored: the Native Apple Reminders roundtrip receipt is here and the MCP one is not, so read from the mirror alone the MCP set looks like a partially hashed set with no root, when it is a fully hashed set whose root is in Drive.

The remedy therefore differs by artifact. For the four genuinely unhashed ones it is upstream, and only the publisher can supply it — a published hash for those control artifacts. For the MCP publication receipt it is repository-side: the hash already exists, and mirroring `COORDINATION-ROUNDTRIP-RECEIPT-…MCP-INTEGRATION-…json` would bring it here.

A byte count is a weak check in a specific way that matters: a same-length substitution passes it. All ten are included because they are the provenance record for the twenty-one, and excluding the evidence while keeping the claim would be worse.

The package required no redaction at ratification or in the two 2026-08-02
revision cycles. Version 2.3 is mirrored as publisher-authored product and
control material, not runtime evidence; its own authority block grants no
credential, TCC, live-data, deployment, disclosure, or activation action.

### Two historical package defects closed by version 2.3

Versions through 2.2 carried an unsubstituted `{PACKAGE_CONTENTS_TABLE}` marker
and a stale body-level repository binding. Version 2.3 removes the marker and
aligns the body, front matter, and manifest on
`195fa54206996dddd6c6e0b6da0872781aa4f5f0`. The defects are preserved here as
history rather than stated as current limitations.

### The package was revised in place on 2026-08-02 for Remote Quick Capture

A second coordination roundtrip, `REQ-MYPA-CANONICAL-PRODUCT-RQC-INTEGRATION-20260802T114700Z`, revised eight of the mirrored artifacts at approximately 11:49–11:50Z to fold **Remote Quick Capture** into the MCV: `00_README.md`, `01_EXECUTIVE_PRODUCT_DESCRIPTION.md`, `02_CANONICAL_PRODUCT_SYNTHESIS_SPECIFICATION.md`, `08_DEVICE_AND_PLATFORM_STRATEGY.md`, `09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md`, `12_MVP_DEFINITION.md`, `13_ROADMAP_AND_DEPENDENCY_SEQUENCE.md`, and `14_DECISION_LOG.md`. The mirror here has been refreshed from Drive and re-verified. The reconciliation is [`../plans/mcv-completion-plan.md`](../plans/mcv-completion-plan.md) section 16, and the decisions it produced are `D-29` through `D-33`.

**Read the hash, not the version.** Every revised artifact still declares `version: 2.1` and still names the *earlier* roundtrip in its `coordination_request_id`, so the package's own version fields report no change. This is one of three defects the revision carries, all recorded in section 16 and summarized at `D-33`; the other two are that the RQC control folder's `revised-artifact-readbacks/`, `publication-controls/`, and `noop/` subfolders are empty while the publication receipt asserts `canonical_specification_readback_observed: true`, and that no readback-verification artifact was published at all.

**Verification, and how it compares to the check above.** Each revised artifact was retrieved with `rclone`, re-hashed against `PUBLICATION-RECEIPT-REQ-MYPA-CANONICAL-PRODUCT-RQC-INTEGRATION-20260802T114700Z.json` — eight of eight, zero mismatches — and separately confirmed to be a pure **byte-prefix append**: the new bytes begin with the previously mirrored bytes, verified against the blobs committed at `ef08ddd`. That second property is what carries the integrity claim here, because it is the only check not derived from the RQC roundtrip's own output. This is a weaker position than the three-source verification recorded above: there is one hash source rather than three, and no independent readback. It is stated plainly rather than described as byte-exact and left there.

Because the revisions are prefix-appends, everything verified in the earlier three-source check is unchanged and remains verified.

Three RQC control artifacts are mirrored beside the specifications they attest, following the precedent set by the MCP-integration control set: `CANONICAL-ARTIFACT-DISPOSITION-…RQC-INTEGRATION-…json`, `PUBLICATION-RECEIPT-…RQC-INTEGRATION-…json`, and `COORDINATION-ROUNDTRIP-RECEIPT-…RQC-INTEGRATION-…json`. Nothing anywhere in the 42-member package hashes any of these three — unlike **all three** MCP-integration control artifacts, each of which some package member does hash: the MCP publication receipt hashes the MCP disposition and readback, and the unmirrored MCP coordination-roundtrip receipt hashes all three. So the RQC set was verified only by Drive-reported byte count matching the retrieved bytes exactly: 3,356, 3,805, and 786 respectively. It is the only one of the three control sets with no hash evidence at all.

**Indexed by reference, not mirrored**, following the `D-22` precedent for material that supports no citation: the RQC coordination request (`1yhkRgk6qcd2V-PWucS7WuRrbCO72FVAn`) and coordination response (`1qVhuUeeApFEGQQrq22lUzQwYhkQWyXN7`), both in control subfolder `RQC-INTEGRATION-20260802T114700Z` (`1t6fzDfHVrLQe6Wd2qjAtZ2ll--fYNPaF`). Also not mirrored and not examined: the governing feature package `MYPA-REMOTE-QUICK-CAPTURE-FEATURE-PACKAGE-20260802-001` (Drive folder `1lDSkTldgSkaRfJ3v9h-U10lCe-Lmwzsv`), named by `MYPA-RQC-D-007`.

The revision granted nothing. `implementation_authority: NOT_GRANTED` is present in all eight revised artifacts, the RQC disposition carries `"implementation": "NOT_GRANTED"` in its authority block, and the RQC publication receipt lists repository mutation, credential creation, ingress activation, deployment, production activation, and risk acceptance as blocked. The package's own `MYPA-RQC-D-008` says the same. The three limits recorded above all survive.

`15_OPEN_OPERATOR_DECISIONS.md` was **not** revised, so the new material's operator decisions are tracked by no package ledger. Two are now carried by the plan as `O-21` and `O-22`; see section 16.

### The package was revised in place again on 2026-08-02 for Native Apple Reminders

A third coordination roundtrip, `REQ-MYPA-CANONICAL-PRODUCT-NATIVE-REMINDERS-INTEGRATION-20260802T150100Z`, revised **ten** of the mirrored artifacts at approximately 15:04–15:09Z to admit **Native Apple Reminders Integration** to the MCV and take the package from version 2.1 to 2.2: the eight the RQC roundtrip revised, plus `15_OPEN_OPERATOR_DECISIONS.md` and `18_PACKAGE_SOURCE_MANIFEST.json`. The mirror here has been refreshed from Drive and re-verified. The reconciliation is [`../plans/mcv-completion-plan.md`](../plans/mcv-completion-plan.md) `D-38` and `D-39`, and the new work package is `WP-11`.

**Still read the hash, not the version — for a different reason this time.** This revision *did* bump `version:` from 2.1 to 2.2, updated `coordination_request_id` to name itself, and moved `repository_head` to `f18e7e3`. That is the correct behaviour and the opposite of the RQC defect `D-33` records. It is not evidence the hazard is retired: the revision was found by SHA-256 against the mirror, and a hash check would have found it whether or not the field moved. One revision behaving correctly does not make the version field a detector.

**The append shape changed, and the earlier integrity argument does not carry over.** The RQC revision was a whole-file byte-prefix append, which is what let the earlier three-source verification stand unchanged. This one is not. Recomputed against the blobs committed at `77ed807`: each of the nine revised Markdown artifacts has **six front-matter fields edited in place** (`version`, `prior_version`, `coordination_request_id`, `repository_head`, `feature_package_id`, `feature_package_folder_id`), and its body equals the previous body **minus its final newline**, followed by the appended section. So it is an append that consumed one byte of what came before, not a prefix-append, and the prefix property is not claimed for it. `18_PACKAGE_SOURCE_MANIFEST.json` is a structural in-place rewrite rather than an append at all: it gains a `canonical_amendments` array and re-states every member's `source_*` and `result_*` values.

**Verification, and why it is the strongest position the mirror has held.** Recomputed here on 2026-08-02, not inherited: the ten revised artifacts match `PUBLICATION-RECEIPT-…NATIVE-REMINDERS-…json` 10/10, `READBACK-VERIFICATION-…NATIVE-REMINDERS-…json` 10/10, and `CANONICAL-ARTIFACT-DISPOSITION-…NATIVE-REMINDERS-…json` 10/10 — three independent sources, including the independent readback the RQC roundtrip never published. The rewritten manifest covers all twenty non-self numbered artifacts, and all twenty match. The manifest itself matches `manifest_sha256` in the publication receipt. Losing the prefix-append property therefore cost nothing: what replaced it is stronger than what it replaced.

Four Native Apple Reminders control artifacts are mirrored beside the specifications they attest, following the MCP-integration and RQC precedent — disposition, publication receipt, readback verification, and coordination roundtrip receipt, at 4,477, 4,330, 4,110, and 2,744 Drive-reported bytes, each matching the retrieved bytes exactly. This set is better attested than the RQC one, which carries no hash at all, and — measured across the whole 42-member package rather than across the mirror — attested the same way as the MCP one rather than better: the coordination roundtrip receipt publishes a SHA-256 for the disposition, the publication receipt, and the readback, and all three were recomputed here and match. The coordination roundtrip receipt itself is hashed by nothing, so the set is hash-checked everywhere except at its own root. That is precisely the MCP shape too; the difference is only that this roundtrip receipt is mirrored and the MCP one is not. A claim that this set is the best-attested holds only inside the mirror, and is what the hash-coverage paragraph above had to correct.

**Indexed by reference, not mirrored**, on the same rule the two earlier roundtrips followed — the coordination request and response are correspondence, not specification: both sit in control subfolder `NATIVE-REMINDERS-INTEGRATION-20260802T150100Z`. Also not mirrored and not examined: the governing feature package `MYPA-NATIVE-APPLE-REMINDERS-INTEGRATION-FEATURE-PACKAGE-20260802-001` (Drive folder `1qDE49KcJ8GSqFlljukYgGlq3eikeTnWq`), named by `MYPA-NAR-D-011`.

**One internal inconsistency, mirrored as authored.** The rewritten manifest's `self_member` declares `source_bytes: 20367` and `source_sha256: 77b52d66…` for the manifest it replaced. The manifest it actually replaced is 19,096 bytes with SHA-256 `4b8a9159…`, and the *previous* manifest carried the identical 20367/`77b52d66…` pair — so the field is carried forward rather than recomputed, and has been wrong across at least two publications. It is reproduced here exactly and corrected nowhere; the manifest's `members` array, which is what the verification above rests on, is unaffected and matched 20/20.

The revision granted nothing. `implementation_authority: NOT_GRANTED` is present in all nine revised Markdown artifacts and the manifest carries the same under `authority`; the Native Apple Reminders disposition carries `"implementation": "NOT_GRANTED"`; and the package's own `MYPA-NAR-D-012` states that product inclusion authorizes no repository mutation, EventKit permission, credential, code signing, deployment, production activation, or risk acceptance. Worth noting as a difference rather than a defect: unlike the RQC publication receipt, this one records no authority block at all — the authority statement lives in the disposition and in `14_DECISION_LOG.md` instead.

`15_OPEN_OPERATOR_DECISIONS.md` **was** revised this time, adding `NAR-OP-001` through `NAR-OP-009`. The gap the RQC roundtrip left — new operator questions tracked by no package ledger — is not repeated here, so the plan opens no `O-` row of its own for Native Apple Reminders.

## The two mirrored feature specifications

Both were admitted to scope by operator reprioritization on 2026-08-01 and are mirrored here so that the citations in [`../plans/mcv-completion-plan.md`](../plans/mcv-completion-plan.md) section 12 can be checked against files in this repository rather than a Drive link a reviewer cannot open. They are `my-pa`-native product design, not third-party proposals: both were authored against this repository at `40391b78`, and the Relationship Intelligence document supersedes the HBPA-branded `FEAT-HBPA-PRIE-001` v0.1 for current product intent.

**A mirror is a review surface, not repository authority.** `AGENTS.md` governs, and `CONTRIBUTING.md` is explicit that Drive mirrors are not a competing ledger. Where a mirror and repository policy disagree, policy wins. Admitting a specification to scope is not accepting it in full — section 5.2 of the MCV specification bounds what was admitted.

### Provenance and how strongly each can be trusted

| Artifact | Drive identity | Representation | Verification |
|---|---|---|---|
| `relationship-intelligence-v0.2.md` | `1Ew5wVddlpcN1OFKkh5ox45zK5gVrDziz7KwTwQ7Jlfo`, parent `1MDaLiEjNN3Fdondxs4NJpK5SfwdXjzl0` | native Google Doc, exported to Markdown via `rclone backend copyid --drive-export-formats md` | **Identity only.** A native Doc does not preserve the bytes it was converted from, so no export can reproduce a declared source hash. File ID, title, parent, owner, and MIME type were verified. Export SHA-256 `3f50c0197d76824111e1596de5c6a47a12150f4e7d0571f7ebf8b74a920fbaec`. This is the same weaker check recorded as `D-01` for the completion plan. |
| `relationship-intelligence-v0.3.md` | none recorded — the document carries no Drive file ID and no publisher receipt | transcribed, not retrieved: `/tmp/ri-v03/FEATURE-v0.3.md`, SHA-256 `4aa380e094596cc8471d9f3ef16860741a03924dab15fd14b082d9cc2fc1b71c` over 49,720 UTF-8 bytes, with the Google Docs export shape normalized into ordinary Markdown | **Weakest of the three, and the document says so itself** — see its own "Provenance and how strongly this mirror can be trusted" section. There is no receipt to check against and no Drive identity to verify, so the only durable claim is the source hash it records. This is a proposed successor, not a current requirements source; see the status table at the top of this file. |
| `quick-capture/` | package folder `1KEdp_BbeJhVFNwCCTEDN7f3zqh83Z9cN` | `stored_raw_bytes` with per-file SHA-256 in `PUBLICATION-RECEIPT-MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005.json` | **Byte-exact.** All 25 mirrored artifacts were re-hashed against that receipt after being written here: 25 verified, zero mismatches. |

The receipt lists 27 artifacts. The two not mirrored are the coordination request and response — governance correspondence rather than specification — and they remain in Drive.

Neither package required redaction. Both were scanned for filesystem paths, addresses, telephone numbers, connection strings, and credential-shaped material, and both are clean. That is a stronger position than `evidence/completion/README.md`, where one personal path had to be removed before committing.

### What governs above them

The ratified canonical product definition described at the top of this file governs whole-product meaning above both feature packages, and this repository governs implementation truth above all three. The two specifications below remain the more detailed authority for their own features wherever the canonical package does not explicitly reconcile them.

This section previously named `my-pa vNext` the canonical product-vision reference and said ratifying it was "an operator decision that has not been made." The operator made it on 2026-08-02. The statement is corrected rather than deleted so that a reader comparing this file against the pull requests that preceded it can see what changed and when.

Ratification did not make any of this repository-accepted direction on its own; see the three limits recorded above, and [`../plans/mcv-completion-plan.md`](../plans/mcv-completion-plan.md) section 15 for how the plan was reconciled against it.
