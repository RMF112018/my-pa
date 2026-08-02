# Specifications

Owning index for versioned behavioral contracts in `RMF112018/my-pa`. Repository-wide routing is [`docs/00_REPOSITORY_SOURCE_INDEX.md`](/docs/00_REPOSITORY_SOURCE_INDEX.md).

| Specification | Status |
|---|---|
| [`mcv-read-only-vertical-slice.md`](mcv-read-only-vertical-slice.md) | Present — proposed for repository review; amended 2026-08-02 for the promoted scope |
| [`canonical-product-definition/`](canonical-product-definition/00_README.md) | Mirror — **ratified** canonical product definition, revised 2026-08-02 for Remote Quick Capture and again for Native Apple Reminders, implementation not authorized |
| [`relationship-intelligence-v0.2.md`](relationship-intelligence-v0.2.md) | Mirror — proposed product specification, implementation not authorized |
| [`quick-capture/`](quick-capture/00_README.md) | Mirror — proposed product specification, implementation not authorized |

The MCV abbreviation follows [`AGENTS.md`](/AGENTS.md): Minimum Viable Candidate. The specification's own prose predates that wording and is preserved as authored.

A specification here describes intended capability, error, and disclosure behavior. It does not authorize runtime implementation, credentials, source-system access, database changes, background scheduling, deployment, or production activation; those require a separately approved goal.

New implementation must use the neutral `my_pa` / `MY_PA_` namespace. Legacy identities may appear only in explicit compatibility or evidence records.

## The ratified canonical product definition

On 2026-08-02 the operator ratified a whole-product definition for `my-pa` **by direct instruction**. It is mirrored at [`canonical-product-definition/`](canonical-product-definition/00_README.md) as package `MYPA-CANONICAL-PRODUCT-DEFINITION-20260802-006`, version 2.2.

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

### Provenance and how strongly it can be trusted

| Field | Value |
|---|---|
| Package folder | `1Z8Aug1_3v6ILgvopY8XpjiNMBySZOCCq`, parent `1Ss71vau8phz7dvXduy7ChIwtxcU3K8Rz` |
| Representation | `stored_raw_bytes` (`text/markdown` and `application/json`) |
| Retrieved | 2026-08-02 via `rclone copy --drive-root-folder-id` |
| Repository head the package binds | `f18e7e3ded45f82456fbfa722443b23a004de0b3` since the version 2.2 revision, which moved this field off the `9096fa4fbe64ff1cdabc07e53a3e68c52efc8575` that was current `main` at ratification. `f18e7e3` is PR #26; `main` is two merges further on at `77ed807`, so the field is fresher than it was and still trails. |
| Verification | **Two claims in sequence, deliberately not merged into one.** *At ratification:* all 21 numbered artifacts were re-hashed after being written here — byte-exact, zero mismatches, against each of three independent in-package sources: `CANONICAL-ARTIFACT-DISPOSITION-…json` (21 members), `READBACK-VERIFICATION-…json` (21 members), and `18_PACKAGE_SOURCE_MANIFEST.json` (20 — it does not hash itself, and says so in its own `self_member.result_hash_scope`). *Since the 2026-08-02 Remote Quick Capture revision:* the **13 unrevised** numbered artifacts still hold that verification, re-confirmed 13/13 against the disposition, 13/13 against the readback verification, and 12/12 against the manifest, which does not cover itself. The **8 revised** artifacts no longer match any of those three sources, and are not claimed to. They rest on a weaker basis — 8/8 against the RQC publication receipt, plus the prefix-append property — with one hash source and no independent readback. The two are kept apart because averaging them would let the stronger claim absorb the weaker one. See the RQC subsection below and [`../plans/mcv-completion-plan.md`](../plans/mcv-completion-plan.md) section 16. *Since the 2026-08-02 Native Apple Reminders revision to version 2.2:* the split above closed rather than widening. Every one of the 21 numbered artifacts now matches a published hash, recomputed here on 2026-08-02: **20/20** against the v2.2 `18_PACKAGE_SOURCE_MANIFEST.json`, whose `members` array carries a `result_sha256` for every numbered artifact but itself, and the manifest itself **1/1** against `manifest_sha256` in the v2.2 publication receipt. The ten revised artifacts are additionally covered three times over — **10/10** against the v2.2 publication receipt, **10/10** against `READBACK-VERIFICATION-…NATIVE-REMINDERS-…json`, and **10/10** against the v2.2 disposition. The weaker RQC position is stated above as the historical fact it is, not carried forward. |
| Drive member count | 42 entries under the folder, confirmed by `rclone lsjson` against the folder ID and matching the retrieved set exactly: 31 files at the root, 5 in `RQC-INTEGRATION-20260802T114700Z` beside its 3 empty subfolders, and 6 in `NATIVE-REMINDERS-INTEGRATION-20260802T150100Z`. The 2026-08-02 Native Apple Reminders revision added no root file — it revised ten in place and added that one subfolder. Not attestable from the repository alone. |

Thirty-one members are mirrored here: the 21 numbered artifacts, the 3 MCP-integration control artifacts, the 3 RQC-integration control artifacts, and the 4 Native Apple Reminders control artifacts. Not mirrored, and remaining in Drive: coordination correspondence for all four roundtrips, one superseded publication receipt, and the empty RQC evidence subfolders. This follows the precedent set for `quick-capture/`, where governance correspondence was likewise left behind, and `../plans/mcv-completion-plan.md` `D-22`.

The `repository_head` row above is the head the package *declares*, and it still trails. The Remote Quick Capture revision left it at `9096fa4` while revising eight artifacts, which is one of the three defects `D-33` records. The Native Apple Reminders revision did move it, to `f18e7e3`, so that particular defect is not repeated — but `f18e7e3` is still two merges behind the `main` that mirrors the package, so the field remains a declaration to read rather than a binding to rely on.

Three mirrored artifacts carried no in-package hash at ratification and were therefore held to a weaker check than the other twenty-one: `CANONICAL-ARTIFACT-DISPOSITION-…json`, `PUBLICATION-RECEIPT-…json`, and `READBACK-VERIFICATION-…json`. Nothing inside the package hashes them, so they were verified only by their Drive-reported byte counts matching the retrieved bytes exactly — 14,777, 4,079, and 7,869 respectively. They are included because they are the provenance record for the twenty-one, and excluding the evidence while keeping the claim would be worse. The 2026-08-02 Remote Quick Capture revision added three more of exactly this kind, and the Native Apple Reminders revision four more — `CANONICAL-ARTIFACT-DISPOSITION-…`, `PUBLICATION-RECEIPT-…`, `READBACK-VERIFICATION-…`, and `COORDINATION-ROUNDTRIP-RECEIPT-…NATIVE-REMINDERS-…json`, verified only by Drive-reported byte counts matching the retrieved bytes exactly: 4,477, 4,330, 4,110, and 2,744 respectively. So ten of the thirty-one mirrored members rest on a byte-count check rather than on a published hash, and all ten are control artifacts rather than specifications.

The package required no redaction. It was scanned for filesystem paths, addresses, telephone numbers, connection strings, and credential-shaped material. Three matches were reviewed and are prose about how tokens and secrets must be handled, not secrets. That scan covered the package as it stood at ratification; the material added on 2026-08-02 — the eight RQC appended sections and the three RQC control artifacts, then the nine Native Apple Reminders appended sections, the rewritten `18_PACKAGE_SOURCE_MANIFEST.json`, and the four Native Apple Reminders control artifacts — was scanned the same way. The second scan returned fifteen candidate matches, every one of them a date or a package identifier read as a telephone number (`2026-08-02`, `…-20260802-001`, `…-20260802-006`), and no filesystem path, address, connection string, or credential-shaped value at all. So the claim covers the mirror as it now stands rather than only the part of it that is older.

### Two defects in the ratified package, disclosed rather than silently mirrored

Mirroring is byte-exact, so these are reproduced here as authored and are noted rather than corrected:

1. `00_README.md` contains an unsubstituted template placeholder, `{PACKAGE_CONTENTS_TABLE}`, where the contents table should be.
2. `00_README.md` binds the repository at `b48b1b177046637297467e661dfb1da023d49bed` in its body while its own front matter, and `18_PACKAGE_SOURCE_MANIFEST.json`, bind a different commit. At ratification that was `9096fa4fbe64ff1cdabc07e53a3e68c52efc8575`, two merges ahead of `b48b1b1`; since version 2.2 both say `f18e7e3ded45f82456fbfa722443b23a004de0b3`, while the body still says `b48b1b1`. Two revisions have now moved the front matter and left the body behind, so this is a persisting divergence rather than a one-off. The front-matter and manifest binding is the correct one, and is what this repository relies on.

Both defects survive the version 2.2 revision — the placeholder is still unsubstituted and the body commit is still stale — rechecked here rather than assumed. Neither changes the package's meaning, and neither is load-bearing for anything below. They are recorded so that a reader who notices them knows they were seen.

### The package was revised in place on 2026-08-02 for Remote Quick Capture

A second coordination roundtrip, `REQ-MYPA-CANONICAL-PRODUCT-RQC-INTEGRATION-20260802T114700Z`, revised eight of the mirrored artifacts at approximately 11:49–11:50Z to fold **Remote Quick Capture** into the MCV: `00_README.md`, `01_EXECUTIVE_PRODUCT_DESCRIPTION.md`, `02_CANONICAL_PRODUCT_SYNTHESIS_SPECIFICATION.md`, `08_DEVICE_AND_PLATFORM_STRATEGY.md`, `09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md`, `12_MVP_DEFINITION.md`, `13_ROADMAP_AND_DEPENDENCY_SEQUENCE.md`, and `14_DECISION_LOG.md`. The mirror here has been refreshed from Drive and re-verified. The reconciliation is [`../plans/mcv-completion-plan.md`](../plans/mcv-completion-plan.md) section 16, and the decisions it produced are `D-29` through `D-33`.

**Read the hash, not the version.** Every revised artifact still declares `version: 2.1` and still names the *earlier* roundtrip in its `coordination_request_id`, so the package's own version fields report no change. This is one of three defects the revision carries, all recorded in section 16 and summarized at `D-33`; the other two are that the RQC control folder's `revised-artifact-readbacks/`, `publication-controls/`, and `noop/` subfolders are empty while the publication receipt asserts `canonical_specification_readback_observed: true`, and that no readback-verification artifact was published at all.

**Verification, and how it compares to the check above.** Each revised artifact was retrieved with `rclone`, re-hashed against `PUBLICATION-RECEIPT-REQ-MYPA-CANONICAL-PRODUCT-RQC-INTEGRATION-20260802T114700Z.json` — eight of eight, zero mismatches — and separately confirmed to be a pure **byte-prefix append**: the new bytes begin with the previously mirrored bytes, verified against the blobs committed at `ef08ddd`. That second property is what carries the integrity claim here, because it is the only check not derived from the RQC roundtrip's own output. This is a weaker position than the three-source verification recorded above: there is one hash source rather than three, and no independent readback. It is stated plainly rather than described as byte-exact and left there.

Because the revisions are prefix-appends, everything verified in the earlier three-source check is unchanged and remains verified.

Three RQC control artifacts are mirrored beside the specifications they attest, following the precedent set by the MCP-integration control set: `CANONICAL-ARTIFACT-DISPOSITION-…RQC-INTEGRATION-…json`, `PUBLICATION-RECEIPT-…RQC-INTEGRATION-…json`, and `COORDINATION-ROUNDTRIP-RECEIPT-…RQC-INTEGRATION-…json`. As with the earlier control artifacts, nothing in the package hashes them, so they were verified only by Drive-reported byte count matching the retrieved bytes exactly — 3,356, 3,805, and 786 respectively.

**Indexed by reference, not mirrored**, following the `D-22` precedent for material that supports no citation: the RQC coordination request (`1yhkRgk6qcd2V-PWucS7WuRrbCO72FVAn`) and coordination response (`1qVhuUeeApFEGQQrq22lUzQwYhkQWyXN7`), both in control subfolder `RQC-INTEGRATION-20260802T114700Z` (`1t6fzDfHVrLQe6Wd2qjAtZ2ll--fYNPaF`). Also not mirrored and not examined: the governing feature package `MYPA-REMOTE-QUICK-CAPTURE-FEATURE-PACKAGE-20260802-001` (Drive folder `1lDSkTldgSkaRfJ3v9h-U10lCe-Lmwzsv`), named by `MYPA-RQC-D-007`.

The revision granted nothing. `implementation_authority: NOT_GRANTED` is present in all eight revised artifacts, the RQC disposition carries `"implementation": "NOT_GRANTED"` in its authority block, and the RQC publication receipt lists repository mutation, credential creation, ingress activation, deployment, production activation, and risk acceptance as blocked. The package's own `MYPA-RQC-D-008` says the same. The three limits recorded above all survive.

`15_OPEN_OPERATOR_DECISIONS.md` was **not** revised, so the new material's operator decisions are tracked by no package ledger. Two are now carried by the plan as `O-21` and `O-22`; see section 16.

### The package was revised in place again on 2026-08-02 for Native Apple Reminders

A third coordination roundtrip, `REQ-MYPA-CANONICAL-PRODUCT-NATIVE-REMINDERS-INTEGRATION-20260802T150100Z`, revised **ten** of the mirrored artifacts at approximately 15:04–15:09Z to admit **Native Apple Reminders Integration** to the MCV and take the package from version 2.1 to 2.2: the eight the RQC roundtrip revised, plus `15_OPEN_OPERATOR_DECISIONS.md` and `18_PACKAGE_SOURCE_MANIFEST.json`. The mirror here has been refreshed from Drive and re-verified. The reconciliation is [`../plans/mcv-completion-plan.md`](../plans/mcv-completion-plan.md) `D-38` and `D-39`, and the new work package is `WP-11`.

**Still read the hash, not the version — for a different reason this time.** This revision *did* bump `version:` from 2.1 to 2.2, updated `coordination_request_id` to name itself, and moved `repository_head` to `f18e7e3`. That is the correct behaviour and the opposite of the RQC defect `D-33` records. It is not evidence the hazard is retired: the revision was found by SHA-256 against the mirror, and a hash check would have found it whether or not the field moved. One revision behaving correctly does not make the version field a detector.

**The append shape changed, and the earlier integrity argument does not carry over.** The RQC revision was a whole-file byte-prefix append, which is what let the earlier three-source verification stand unchanged. This one is not. Recomputed against the blobs committed at `77ed807`: each of the nine revised Markdown artifacts has **six front-matter fields edited in place** (`version`, `prior_version`, `coordination_request_id`, `repository_head`, `feature_package_id`, `feature_package_folder_id`), and its body equals the previous body **minus its final newline**, followed by the appended section. So it is an append that consumed one byte of what came before, not a prefix-append, and the prefix property is not claimed for it. `18_PACKAGE_SOURCE_MANIFEST.json` is a structural in-place rewrite rather than an append at all: it gains a `canonical_amendments` array and re-states every member's `source_*` and `result_*` values.

**Verification, and why it is the strongest position the mirror has held.** Recomputed here on 2026-08-02, not inherited: the ten revised artifacts match `PUBLICATION-RECEIPT-…NATIVE-REMINDERS-…json` 10/10, `READBACK-VERIFICATION-…NATIVE-REMINDERS-…json` 10/10, and `CANONICAL-ARTIFACT-DISPOSITION-…NATIVE-REMINDERS-…json` 10/10 — three independent sources, including the independent readback the RQC roundtrip never published. The rewritten manifest covers all twenty non-self numbered artifacts, and all twenty match. The manifest itself matches `manifest_sha256` in the publication receipt. Losing the prefix-append property therefore cost nothing: what replaced it is stronger than what it replaced.

Four Native Apple Reminders control artifacts are mirrored beside the specifications they attest, following the MCP-integration and RQC precedent — disposition, publication receipt, readback verification, and coordination roundtrip receipt. Nothing in the package hashes them, so they were verified only by Drive-reported byte count matching the retrieved bytes exactly: 4,477, 4,330, 4,110, and 2,744.

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
| `quick-capture/` | package folder `1KEdp_BbeJhVFNwCCTEDN7f3zqh83Z9cN` | `stored_raw_bytes` with per-file SHA-256 in `PUBLICATION-RECEIPT-MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005.json` | **Byte-exact.** All 25 mirrored artifacts were re-hashed against that receipt after being written here: 25 verified, zero mismatches. |

The receipt lists 27 artifacts. The two not mirrored are the coordination request and response — governance correspondence rather than specification — and they remain in Drive.

Neither package required redaction. Both were scanned for filesystem paths, addresses, telephone numbers, connection strings, and credential-shaped material, and both are clean. That is a stronger position than `evidence/completion/README.md`, where one personal path had to be removed before committing.

### What governs above them

The ratified canonical product definition described at the top of this file governs whole-product meaning above both feature packages, and this repository governs implementation truth above all three. The two specifications below remain the more detailed authority for their own features wherever the canonical package does not explicitly reconcile them.

This section previously named `my-pa vNext` the canonical product-vision reference and said ratifying it was "an operator decision that has not been made." The operator made it on 2026-08-02. The statement is corrected rather than deleted so that a reader comparing this file against the pull requests that preceded it can see what changed and when.

Ratification did not make any of this repository-accepted direction on its own; see the three limits recorded above, and [`../plans/mcv-completion-plan.md`](../plans/mcv-completion-plan.md) section 15 for how the plan was reconciled against it.
