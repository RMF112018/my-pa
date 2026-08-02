# Specifications

Owning index for versioned behavioral contracts in `RMF112018/my-pa`. Repository-wide routing is [`docs/00_REPOSITORY_SOURCE_INDEX.md`](/docs/00_REPOSITORY_SOURCE_INDEX.md).

| Specification | Status |
|---|---|
| [`mcv-read-only-vertical-slice.md`](mcv-read-only-vertical-slice.md) | Present — proposed for repository review; amended 2026-08-02 for the promoted scope |
| [`relationship-intelligence-v0.2.md`](relationship-intelligence-v0.2.md) | Mirror — proposed product specification, implementation not authorized |
| [`quick-capture/`](quick-capture/00_README.md) | Mirror — proposed product specification, implementation not authorized |

The MCV abbreviation follows [`AGENTS.md`](/AGENTS.md): Minimum Viable Candidate. The specification's own prose predates that wording and is preserved as authored.

A specification here describes intended capability, error, and disclosure behavior. It does not authorize runtime implementation, credentials, source-system access, database changes, background scheduling, deployment, or production activation; those require a separately approved goal.

New implementation must use the neutral `my_pa` / `MY_PA_` namespace. Legacy identities may appear only in explicit compatibility or evidence records.

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

The Drive owning index names **my-pa vNext** (`SPEC-MYPA-VNEXT-PRODUCT-SYNTHESIS-v1.0`, Drive `17olnyUF5oX-KJWB6owRIJBB8B4QTlRjJhkLG47gio9s`) the canonical product-vision reference, with these two feature packages governing detailed behavior beneath it and this repository governing implementation truth. Its own status is `PROPOSED_CANONICAL_PRODUCT_DIRECTION` with implementation authority not granted, and **ratifying it is an operator decision that has not been made** — see `../plans/mcv-completion-plan.md` section 14. It is recorded here because an agent reading only this repository would otherwise not know the product has a defined mental model, information architecture, and object model, and could build a shape that later has to be undone.
