# TBR Staff Meeting preservation (GN-09 / WP-13)

Repository-side regression contract and dormant optional-bridge **design** for
the existing TBR Staff Meeting Task. There is no TBR runtime in this
repository. This runbook does not create, edit, enable, or disable any live
Task and does not implement a live bridge.

**Production is not activated.** No step below was executed against a live TBR
Task, SharePoint, OneDrive, Teams, email, or live personal data. Separate
Task-change authorization is **not** granted. WP-15 production activation is
out of scope.

Related:

- [`goodnotes-and-model-operations.md`](goodnotes-and-model-operations.md) —
  general GoodNotes OCR/review composition. TBR ink, SharePoint archival, and
  Teams/email must not merge into that path.
- [`goodnotes-durable-note-intelligence.md`](goodnotes-durable-note-intelligence.md)
  — dormant Durable Note Intelligence Task contract. Its GN-09 live-bridge
  exclusion still holds.
- [`../goodnotes/tbr-staff-meeting-regression.json`](../goodnotes/tbr-staff-meeting-regression.json)
  — frozen regression artifact marked `GN-09_EXTERNAL_TASK_GATE_PENDING`.

## Existing TBR Task

The existing TBR Task remains the near-term default. **Do not change it under
this dispatch.** Live Task mutation is reserved to a later, separately granted
authorization. `live_task_mutation` is `false`.

## Frozen regression expectations

Synthetic labels only. These are the expectations the repository now locks;
they are not a live processor.

- Inputs: SharePoint Staff Meeting materials and manual Staff Meeting capture.
- Included ink: red and black handwriting.
- Excluded ink: blue preparatory notes.
- Leader lines: unambiguous included ink follows its target; otherwise human
  review.
- Ambiguity (color, target, or reading) goes to human review.
- Outputs: Part A paste-ready text and Part B review DOCX.
- Destination: OneDrive `/Meetings/Meeting Notes`.
- Teams and email remain disabled unless separately authorized.
- The TBR SharePoint archive remains TBR-only. It is not a general GoodNotes
  destination.
- Corrections remain supervised operator input. Teams and email are not
  correction channels.

## General GoodNotes separation

General GoodNotes reconciliation, occurrence identity, NEW-only delivery, and
operator correction must not absorb:

- TBR red/black/blue ink rules;
- TBR SharePoint archival;
- Teams or email sending.

Those rules stay on the existing TBR Task. The general path continues to refuse
Teams and email (`operator-local` delivery) and keeps corrections as a
supervised application event.

## Optional bridge (unauthorized)

The optional bridge is a design only. `live_bridge_implemented` is `false` and
`optional_bridge.authorized` is `false`. A later bridge, if ever authorized,
would be a separately authorized Task-change — not a merge of TBR rules into
general GoodNotes, and not WP-15 activation.

After this repository-side design, status is
`GN-09_EXTERNAL_TASK_GATE_PENDING`. That marker means the contract is encoded
here; it does not authorize touching the live TBR Task.

## Synthetic canaries versus live systems

The unit suite in `tests/unit/test_goodnotes_tbr_preservation.py` locks the
frozen contract with synthetic strings such as `"synthetic red handwriting"`.
It does not call SharePoint, OneDrive, Teams, email, or a live Task.

```bash
.venv/bin/python -m pytest -q tests/unit/test_goodnotes_tbr_preservation.py
```

No command block in this runbook was executed against a live TBR Task or live
personal data.

## Activation sequence

None of these steps turns a live Task or bridge on by existing in this
document.

1. Merge the reviewed pull request.
2. Local canary: FAST synthetic suite, including
   `tests/unit/test_goodnotes_tbr_preservation.py`.
3. Confirm the frozen artifact still reads
   `GN-09_EXTERNAL_TASK_GATE_PENDING`, `live_task_mutation: false`, and
   `live_bridge_implemented: false`.
4. Live TBR Task create, edit, enable, or disable — **operator-only**, and
   **not authorized** by this change.
5. Live bridge implementation — **not authorized**.
6. Teams/email enablement — **not authorized** unless a later exact
   authorization names them.
7. WP-15 production activation — **operator-only** and out of scope here.

## Rollback

1. Leave the existing TBR Task unchanged.
2. Leave the optional bridge unimplemented and unauthorized.
3. Do not enable Teams or email from this runbook.
4. Do not point general GoodNotes delivery at the TBR SharePoint archive or at
   OneDrive `/Meetings/Meeting Notes`.
