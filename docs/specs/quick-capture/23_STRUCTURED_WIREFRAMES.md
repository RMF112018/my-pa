# Structured Wireframes and Interaction Concepts

Package: `MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005`
Coordination request: `REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081`
Date: 2026-08-01
Repository basis: `RMF112018/my-pa@40391b784ba7df2aa37f99fed86b0d4ac4723034`
Status: `PROPOSED_FOR_OPERATOR_REVIEW`
Implementation authority: `NOT_GRANTED`
Repository mutation: `NOT_PERFORMED`


These are implementation-neutral structural concepts. They define hierarchy, interaction, trust labels, and states—not final visual design.

## 1. In-app Quick Capture

```text
┌────────────────────────────────────────────────────┐
│ Capture                                      [×]   │
│ [Quick Note ▾]  [Project: Riverfront Tower ×]      │
│                                                    │
│ Write what you need to remember…                   │
│ ┌────────────────────────────────────────────────┐ │
│ │                                                │ │
│ │                                                │ │
│ └────────────────────────────────────────────────┘ │
│ Private · Local processing             [Save]      │
│ Cmd/Ctrl+Enter to save                              │
└────────────────────────────────────────────────────┘
```

Behavior:

- cursor begins in field;
- context chip passive/removable;
- privacy state visible but not a form;
- secondary controls under mode/privacy menu;
- save closes after durable acknowledgment.

## 2. Quick Note

```text
┌────────────────────────────────────────────────────┐
│ Quick Note                                  [×]    │
│                                                    │
│ ┌────────────────────────────────────────────────┐ │
│ │ Water was visible at the north stair after     │ │
│ │ today’s storm. Ask waterproofing contractor    │ │
│ │ to inspect before Monday.                      │ │
│ └────────────────────────────────────────────────┘ │
│ Draft saved locally                   [Save Note]  │
└────────────────────────────────────────────────────┘
```

No title, project, date, task form, or tags.

## 3. Conversation Log

```text
┌────────────────────────────────────────────────────┐
│ Conversation Log                            [×]    │
│                                                    │
│ Summarize what was discussed…                      │
│ ┌────────────────────────────────────────────────┐ │
│ │ Called Jordan. I will send the revised buyout  │ │
│ │ Friday. Jordan will confirm steel lead time.   │ │
│ └────────────────────────────────────────────────┘ │
│ Private · Participants/details extracted later    │
│                                      [Save Log]    │
└────────────────────────────────────────────────────┘
```

A dedicated mode may create a skeletal Conversation after save.

## 4. iPhone Home Screen launch

```text
Home Screen

[ my-pa ]       [ Note ]
                Quick Note URL/Shortcut

[ Conversation ]
Conversation Log URL/Shortcut
```

MVP reality:

- one installed PWA icon is guaranteed only within platform support;
- separate mode-specific entries may be user-created shortcuts/web clips;
- do not represent these as native app-icon quick actions.

## 5. iPhone capture

```text
┌──────────────────────────────┐
│ 9:41                  [Done] │
│ Conversation Log             │
│                              │
│ ┌──────────────────────────┐ │
│ │ Summarize what was       │ │
│ │ discussed…               │ │
│ │                          │ │
│ └──────────────────────────┘ │
│                              │
│ Saved draft · Private        │
│ ┌──────────────────────────┐ │
│ │         Save Log         │ │
│ └──────────────────────────┘ │
│ Home indicator safe area     │
└──────────────────────────────┘
```

Keyboard remains open; Save stays visible above safe area.

## 6. iPad capture

```text
┌───────────────────────────────────────────────────────┐
│ App context dimmed                                    │
│   ┌───────────────────────────────────────────────┐   │
│   │ Quick Note                              [×]   │   │
│   │ [Situation: Steel Buyout ×]                   │   │
│   │                                               │   │
│   │ ┌───────────────────────────────────────────┐ │   │
│   │ │                                           │ │   │
│   │ └───────────────────────────────────────────┘ │   │
│   │ Private · Local               [Save Note]     │   │
│   └───────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────┘
```

Supports hardware keyboard and touch; evidence rail not shown during capture.

## 7. macOS floating capture — later wrapper

```text
          Global shortcut
               ↓
┌──────────────────────────────────────────────┐
│ Quick Capture                         [×]    │
│ [Note] [Conversation]                       │
│ ┌──────────────────────────────────────────┐ │
│ │                                          │ │
│ └──────────────────────────────────────────┘ │
│ Private · Sync ready       [Save ⌘↵]        │
└──────────────────────────────────────────────┘
```

Always-on-top/global shortcut requires wrapper/native work, not PWA baseline.

## 8. Windows floating capture — later wrapper

```text
Win/global shortcut
┌──────────────────────────────────────────────┐
│ my-pa — Conversation Log              [_][×]│
│ ┌──────────────────────────────────────────┐ │
│ │                                          │ │
│ └──────────────────────────────────────────┘ │
│ Local · Connected             [Save Ctrl↵] │
└──────────────────────────────────────────────┘
```

Windows PWA MVP instead opens a dedicated app window from Start/taskbar/jump list.

## 9. Offline saved state

```text
┌────────────────────────────────────────────┐
│ ✓ Saved on this device                    │
│ Sync pending · Last attempt 4:12 PM       │
│                                            │
│ Your note is encrypted locally. Reopen    │
│ my-pa after connecting to synchronize.    │
│                                            │
│ [Close]                         [Retry]     │
└────────────────────────────────────────────┘
```

No server receipt is claimed.

## 10. Processing-complete state

```text
Toast:
✓ Capture ready
2 suggestions · 1 item needs review
[Open]

Capture row:
Conversation Log · Ready
Jordan / Steel lead time (proposed)
Saved 4:05 PM
```

No system notification by default for ordinary completion.

## 11. Capture detail

```text
┌──────────────┬───────────────────────────┬──────────────┐
│ Library      │ Capture                    │ Evidence     │
│ Captures     │ Conversation Log · Active  │ Authority    │
│ Notes        │ Saved Aug 1, 4:05 PM       │ Original     │
│ Conversations│                           │ user evidence│
│              │ Original text              │              │
│              │ ┌───────────────────────┐  │ Version 1    │
│              │ │ Called Jordan…        │  │ Hash / time  │
│              │ └───────────────────────┘  │              │
│              │ Suggestions                │ Processing   │
│              │ • Jordan [person?]         │ Local model  │
│              │ • Send buyout [commitment] │ v…           │
│              │ • Steel lead [commitment]  │              │
│              │ [Review 2] [Edit] [Archive]│ Receipt      │
└──────────────┴───────────────────────────┴──────────────┘
```

## 12. Conversation detail

```text
┌────────────────────────────────────────────────────────────┐
│ Conversation · Aug 1 · Channel: Phone (proposed)           │
│ Jordan Lee (?) · Riverfront Tower                          │
│                                                            │
│ Accepted summary                                           │
│ ...                                                        │
│                                                            │
│ Commitments                                                │
│ You → Send revised buyout · Due Fri · Needs review         │
│ Jordan → Confirm steel lead time · Needs review            │
│                                                            │
│ Decisions | Tasks | Questions | Risks                      │
│                                                            │
│ [Open original capture] [Review]                            │
└────────────────────────────────────────────────────────────┘
```

Unknown/ambiguous fields are visually explicit.

## 13. Notes Library

```text
Library / Captures / Notes
[Search notes…] [Date] [Project] [Situation] [Status]

Today
4:31 PM  Water at north stair…       Project suggested
3:10 PM  Idea: simplify weekly…      Ready

Yesterday
...
```

Columns/rows show authority and processing state without clutter.

## 14. Conversations Library

```text
Library / Captures / Conversations
[Search conversations…] [Person] [Project] [Channel] [Review]

Aug 1  Jordan Lee (?)    Phone?    2 commitments need review
Aug 1  Site walk team    In person Ready
Jul 31 Unknown           Unknown   Participant unresolved
```

Question marks indicate proposals/unknowns.

## 15. Relationship timeline integration

```text
Relationship: Jordan Lee

Aug 1 · Conversation (accepted)
Phone · Riverfront Tower
“Called Jordan…”
You owe: Revised buyout by Fri
Jordan owes: Confirm steel lead time
[Evidence] [Open conversation]

Pending suggestion
Possible preference/concern extracted — [Review]
```

Private notes have a distinct label and are not blended with external-source facts.

## 16. Project timeline integration

```text
Project: Riverfront Tower / Trace

Aug 1 4:05 PM · Conversation
Steel lead-time confirmation requested
Source: User-authored Conversation Log
Status: commitments pending review
[Open evidence]

Aug 1 3:10 PM · Field observation
Water at north stair
Source: User-authored Quick Note
[Open evidence]
```

Recorded time and occurred time are separate when known.

## 17. Review case — commitment or decision

```text
┌──────────────────────┬────────────────────────┬────────────┐
│ Original evidence    │ Proposed transition    │ Impact     │
│                      │                        │            │
│ “…I will send the    │ Create Commitment      │ Today      │
│ revised buyout by    │ Obligor: You           │ Project    │
│ Friday…”             │ Counterparty: Jordan?  │ Relationship│
│   highlighted        │ Action: Send buyout    │            │
│                      │ Due: Aug 7              │            │
│ Source v1            │ Confidence: High       │            │
│ Model/rule v…        │ Identity unresolved    │            │
├──────────────────────┴────────────────────────┴────────────┤
│ [Reject] [Defer] [Correct] [Accept]                        │
└────────────────────────────────────────────────────────────┘
```

Accept remains disabled if required identity/authority fields are unresolved unless policy permits an explicitly unresolved canonical object.

## Responsive rules

- Desktop: modal/floating overlay; later three-pane details.
- Tablet: centered sheet; one canvas plus drawers.
- Mobile: full-height capture; stacked detail with evidence drawer.
- Reduced motion: no scale/slide effects.
- High contrast: explicit borders and text labels.
- Keyboard: mode switch, save, close, and review controls reachable without pointer.
