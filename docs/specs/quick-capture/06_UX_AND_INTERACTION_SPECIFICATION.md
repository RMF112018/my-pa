# UX and Interaction Specification

Package: `MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005`
Coordination request: `REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081`
Date: 2026-08-01
Repository basis: `RMF112018/my-pa@40391b784ba7df2aa37f99fed86b0d4ac4723034`
Status: `PROPOSED_FOR_OPERATOR_REVIEW`
Implementation authority: `NOT_GRANTED`
Repository mutation: `NOT_PERFORMED`


## Surface

The primary capture surface is a modal overlay on desktop, a bottom sheet or full-height sheet on mobile/tablet, and a dedicated minimal route for PWA/shortcut launch.

### Required elements

1. Mode label: Quick Note or Conversation Log.
2. One unrestricted multiline text field.
3. Save button.
4. Close button.
5. Passive persistence/connection state.
6. Optional deterministic context chip.

### Optional secondary elements

Hidden behind an overflow or secondary row; none are required:

- switch mode;
- attach current context;
- sensitivity override;
- dictate using OS input;
- add attachment (deferred from MVP);
- save without AI processing;
- processing/privacy explanation.

## Default interaction

- Focus lands in text field.
- No title field.
- No placeholder that teaches the user to write a structured form.
- Placeholder examples are brief and mode-specific:
  - Quick Note: “Write what you need to remember…”
  - Conversation Log: “Summarize what was discussed…”
- `Cmd/Ctrl+Enter` saves.
- `Escape` closes; a non-empty draft remains recoverable.
- Tab order is field → Save → secondary controls → Close.
- Save is disabled only for empty/whitespace-only input or explicit client limits.
- User may paste long text within configured limits; oversized input is preserved as a draft and receives a clear bounded error.

## Save versus autosave

Recommendation:

- **Explicit Save commits evidence.**
- **Autosave protects drafts only.**

This prevents incomplete text from becoming source evidence or triggering processing while preserving crash recovery.

## Confirmation

Online:

> Saved

Offline:

> Saved on this device — sync pending

Partial server acceptance:

> Saved — processing setup needs attention

No “AI complete” wait is shown. Processing status may update later, but completion is not a blocking success condition.

## Dismissal

After durable acknowledgment:

- surface closes by default;
- focus returns to invoking element;
- toast remains 2–4 seconds;
- undo is not a destructive delete; it opens the just-saved capture or archives it with confirmation.

For dedicated PWA/window launch, the app may close the window only where platform policy permits. Otherwise it shows a quiet saved state and a Close action.

## Context behavior

- Context is automatically included only when supplied by the launch surface.
- Context chip names object type and title without exposing sensitive data on locked surfaces.
- User can remove the chip before save.
- The capture persists even if context validation fails.
- Model-inferred contexts appear after save as suggestions, never as hidden metadata.

## Processing display

Capture list/detail shows:

- Saved;
- Waiting;
- Processing;
- Ready;
- Needs review;
- Partial;
- Failed;
- Sync pending.

Do not show model percentages as primary status. Detail may show calibrated confidence and reasons.

## Accessibility

Target WCAG 2.2 AA for web surfaces.

- Programmatic label and instructions for the text field.
- Screen-reader announcement for saved/offline/error state.
- Visible focus and focus restoration.
- Full keyboard operation.
- Minimum 44×44 CSS-pixel touch targets where practical.
- Reflow at 400% zoom.
- System text scaling and mobile safe-area support.
- No status communicated by color alone.
- Reduced motion removes entrance/exit animation.
- High-contrast themes preserve boundaries and focus.
- Dictation works through OS text input without requiring a custom recorder.
- Errors preserve typed text and state the recovery action.
- Shortcut discoverability in command palette and Help.

## Performance budgets

| Measure | Target |
|---|---|
| Warm in-app launch to focused cursor | p75 ≤100 ms; p95 ≤250 ms |
| Installed PWA cold launch to cursor | p75 ≤1.5 s; p95 ≤2.5 s |
| Keypress-to-paint | p95 ≤50 ms |
| Draft local persistence | p95 ≤100 ms after debounce |
| Save local acknowledgment | p95 ≤200 ms |
| Online server durable acknowledgment | p95 ≤750 ms on target local network |
| Exit after acknowledgment | ≤100 ms |
| Foreground offline-sync start after connectivity | p95 ≤5 s |
| Exact-text search eligibility | p95 ≤10 s online |
| Standard extraction for ≤10,000 characters | p95 ≤30 s, excluding policy-blocked external processing |

These are validation goals for the future implementation.

## Error behavior

- Network failure: convert to offline queue if local durability succeeds.
- Local storage failure: do not claim save; keep text in memory and offer copy/retry.
- Authentication stale: store locally only if policy permits, label authentication required.
- Server conflict: preserve local item and show conflict; never overwrite.
- Policy denial: original may remain saved locally/server-side according to policy, but prohibited processing is not attempted.
- Unsupported attachment: text persists; attachment is rejected separately.
