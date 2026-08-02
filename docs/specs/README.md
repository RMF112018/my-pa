# Specifications

Owning index for versioned behavioral contracts in `RMF112018/my-pa`. Repository-wide routing is [`docs/00_REPOSITORY_SOURCE_INDEX.md`](/docs/00_REPOSITORY_SOURCE_INDEX.md).

| Specification | Status |
|---|---|
| [`mcv-read-only-vertical-slice.md`](mcv-read-only-vertical-slice.md) | Present — proposed for repository review; amended 2026-08-02 for the promoted scope |
| [`canonical-product-definition/`](canonical-product-definition/00_README.md) | Mirror — **ratified** canonical product definition, implementation not authorized |
| [`relationship-intelligence-v0.2.md`](relationship-intelligence-v0.2.md) | Mirror — proposed product specification, implementation not authorized |
| [`quick-capture/`](quick-capture/00_README.md) | Mirror — proposed product specification, implementation not authorized |

The MCV abbreviation follows [`AGENTS.md`](/AGENTS.md): Minimum Viable Candidate. The specification's own prose predates that wording and is preserved as authored.

A specification here describes intended capability, error, and disclosure behavior. It does not authorize runtime implementation, credentials, source-system access, database changes, background scheduling, deployment, or production activation; those require a separately approved goal.

New implementation must use the neutral `my_pa` / `MY_PA_` namespace. Legacy identities may appear only in explicit compatibility or evidence records.

## The ratified canonical product definition

On 2026-08-02 the operator ratified a whole-product definition for `my-pa` **by direct instruction**. It is mirrored at [`canonical-product-definition/`](canonical-product-definition/00_README.md) as package `MYPA-CANONICAL-PRODUCT-DEFINITION-20260802-006`, version 2.1.

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
| Repository head the package binds | `9096fa4fbe64ff1cdabc07e53a3e68c52efc8575` — current `main` at ratification |
| Verification | **Byte-exact, against three independent in-package hash sources.** All 21 numbered artifacts were re-hashed after being written here, with zero mismatches against each of: `CANONICAL-ARTIFACT-DISPOSITION-…json` (21 members), `READBACK-VERIFICATION-…json` (21 members), and `18_PACKAGE_SOURCE_MANIFEST.json` (20 — it does not hash itself, and says so in its own `self_member.result_hash_scope`). |
| Drive member count | 31, confirmed by `rclone lsf` against the folder ID and matching the retrieved set exactly. Not attestable from the repository alone. |

Twenty-four of the package's thirty-one Drive members are mirrored. The seven not mirrored are coordination correspondence and one superseded publication receipt, which remain in Drive; this follows the precedent set for `quick-capture/`, where governance correspondence was likewise left behind.

Three mirrored artifacts carry no in-package hash and are therefore held to a weaker check than the other twenty-one: `CANONICAL-ARTIFACT-DISPOSITION-…json`, `PUBLICATION-RECEIPT-…json`, and `READBACK-VERIFICATION-…json`. Nothing inside the package hashes them, so they were verified only by their Drive-reported byte counts matching the retrieved bytes exactly — 14,777, 4,079, and 7,869 respectively. They are included because they are the provenance record for the other twenty-one, and excluding the evidence while keeping the claim would be worse.

The package required no redaction. It was scanned for filesystem paths, addresses, telephone numbers, connection strings, and credential-shaped material. Three matches were reviewed and are prose about how tokens and secrets must be handled, not secrets.

### Two defects in the ratified package, disclosed rather than silently mirrored

Mirroring is byte-exact, so these are reproduced here as authored and are noted rather than corrected:

1. `00_README.md` contains an unsubstituted template placeholder, `{PACKAGE_CONTENTS_TABLE}`, where the contents table should be.
2. `00_README.md` binds the repository at `b48b1b177046637297467e661dfb1da023d49bed` in its body while its own front matter, and `18_PACKAGE_SOURCE_MANIFEST.json`, bind `9096fa4fbe64ff1cdabc07e53a3e68c52efc8575`. `b48b1b1` is two merges stale — it predates both `8274d88` and `9096fa4`. The front-matter and manifest binding is the correct one, and is what this repository relies on.

Neither defect changes the package's meaning, and neither is load-bearing for anything below. They are recorded so that a reader who notices them knows they were seen.

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
