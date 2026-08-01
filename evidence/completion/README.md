# Application-completion evidence

## `PLAN-MYPA-APPLICATION-COMPLETION-20260801-078.md`

A mirror of the dispatched completion plan, placed here so that the sections
cited by [`docs/plans/mcv-completion-plan.md`](../../docs/plans/mcv-completion-plan.md)
can be checked against a file in this repository instead of a Drive link a
reviewer cannot open.

This mirror is evidence of what was dispatched. It is not repository authority.
`AGENTS.md` governs, and `CONTRIBUTING.md` is explicit that Drive mirrors are
review surfaces rather than a competing ledger. Where this document and
repository policy disagree, repository policy wins; `docs/plans/mcv-completion-plan.md`
section 5 records one such disagreement and how it was resolved.

### Provenance

| Field | Value |
|---|---|
| Drive file ID | `1-jfuAm3p1bQSC3l-37rFw6wk82HFQ9MKalR-LZm_U3Q` |
| Title | `PLAN-MYPA-APPLICATION-COMPLETION-20260801-078.md` |
| Parent folder ID | `1uwSWSmc6spavDkYfMEi0w3KKh_kxMYs-` |
| Drive representation | native Google Doc |
| Retrieved | 2026-08-01, exported to Markdown via `rclone backend copyid --drive-export-formats md` |
| Export SHA-256 | `d090f216ee6d7c53b070ad1306cfbe331ccaa274345b5975d24c268c1b3c74df` |
| File SHA-256 as committed | `9a0462541fccc636687ae470567931e78eb0dae035bb7c01c4a44e7eed5d0428` |

### The two hashes differ, deliberately

One line was redacted before committing. Line 213 of the export carried a
`configured_source_root_claim` naming a personal NAS directory path. `AGENTS.md`
section 5 forbids committing personal data or unredacted source evidence, so the
path was replaced with a marker rather than committed.

The redaction is named here rather than performed silently, and only that one
value was touched. The export hash above lets the operator reproduce the
original from Drive and confirm that nothing else changed.

### The dispatch's own hash does not match, and could not

The dispatch declared `expected_source_bytes: 35988` and
`expected_source_sha256: 3e74426e6d7fa1f09f8c2b0f9a784b620c3263b47cc183558872b161af1a20eb`,
describing the Markdown source before it was converted to a Google Doc. It also
declared `expected_representation: native_google_doc`.

Those two declarations cannot both be satisfied. A native Google Doc does not
preserve the bytes of the Markdown it was converted from, so no export can
reproduce that hash. Every available export format was hashed — Markdown, plain
text, HTML, DOCX, ODT, RTF — and none matched, which is the expected result
rather than a sign of tampering.

The plan was therefore accepted on identity: file ID, title, parent folder,
owner, and native MIME type all verified against the dispatch. This is a weaker
check than a byte hash and is recorded as such in
`docs/plans/mcv-completion-plan.md` section 9, decision D-01.
