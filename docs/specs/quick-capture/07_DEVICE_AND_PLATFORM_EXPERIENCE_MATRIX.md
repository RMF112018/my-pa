# Device and Platform Experience Matrix

Package: `MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005`
Coordination request: `REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081`
Date: 2026-08-01
Repository basis: `RMF112018/my-pa@40391b784ba7df2aa37f99fed86b0d4ac4723034`
Status: `PROPOSED_FOR_OPERATOR_REVIEW`
Implementation authority: `NOT_GRANTED`
Repository mutation: `NOT_PERFORMED`


## Platform strategy

The product should implement a **PWA-first capture contract** and defer native shells until a demonstrated platform gap materially harms capture speed or reliability. Platform claims below distinguish web/PWA feasibility from native requirements.

## Matrix

| Experience | Web/PWA MVP | Thin desktop wrapper | Native Apple app/extension | Notes |
|---|---|---|---|---|
| In-app global Capture action | Yes | Yes | Yes | Core MVP |
| Dedicated Quick Note / Conversation URLs | Yes | Yes | Yes | Mode supplied by route |
| Installed Home Screen / Start / Dock app | Yes, platform-dependent install flow | Yes | Yes | Core PWA |
| Manifest shortcut menu | Browser/OS-dependent | Yes through app menu | Yes | Do not rely on iOS exposure |
| In-app keyboard shortcut | Yes while app focused | Yes | Yes | Core MVP |
| System-wide global shortcut | No reliable standard web API | Yes | Yes | Tauri/Electron/native |
| Offline append-only queue | Yes | Yes | Yes | IndexedDB for PWA |
| Background synchronization | Enhancement only; availability varies | Yes with native lifecycle | Yes | Foreground sync remains authoritative |
| Windows share target | Supported by installed PWA in Edge/Windows | Yes | N/A | Validate incoming content |
| iOS/iPadOS Share Sheet target | Do not rely on PWA | Wrapper/native share extension | Yes | Defer |
| Siri/Shortcuts deep-link launch | URL-based Shortcut possible | Limited | App Intents recommended | Native for robust typed action |
| Lock Screen widget/control | No | No unless native Apple target | Yes | WidgetKit/App Intents |
| Control Center control | No | No unless native Apple target | Yes | WidgetKit/App Intents |
| macOS menu-bar utility | No | Yes | Yes | Later |
| Windows system tray | No | Yes | N/A | Later |
| Floating always-on-top capture | Browser window only, inconsistent | Yes | Yes | Later |
| Secure keychain/credential vault | Browser-bound | OS integration | OS integration | Wrapper/native advantage |
| App-switcher privacy blur | Limited web control | Possible | Possible | Sensitive enhancement |

## In-app

Required:

- persistent global Capture action;
- command palette / Reveal commands:
  - `Capture note`
  - `Log conversation`
- focused-app shortcut, recommended default `Cmd/Ctrl+Shift+Space` or operator-selected conflict-free binding;
- contextual capture in Situation, Project, Relationship, Decision, Commitment, meeting, source, and Timeline;
- touch-safe mobile floating or navigation action.

The final shortcut must be operator-configurable because system/application conflicts vary.

## iPhone and iPad

### PWA MVP

- installable Home Screen web app;
- dedicated `/capture/note` and `/capture/conversation` routes;
- standard Home Screen icon opening the minimal capture route or general app;
- optional user-created Apple Shortcut/Home Screen links to those routes;
- OS dictation into the text field;
- offline local queue;
- web push/badging only for carefully bounded, generic notifications after user permission.

Home Screen web apps on modern iOS/iPadOS can run in standalone mode and support standards-based Web Push when added to the Home Screen. That does not make them equivalent to native apps for App Intents, Lock Screen controls, Control Center, or Share extensions.

### Native-required later

- App Intents for Siri, Spotlight, and Shortcuts;
- WidgetKit control for Control Center, Lock Screen, or Action button;
- native Share extension;
- robust background execution;
- keychain-backed local encryption key;
- privacy-protected app-switcher snapshot;
- voice/audio capture beyond OS dictation.

### Explicit limitation

Do not promise app-icon long-press quick actions from the PWA on iOS/iPadOS as an MVP requirement. Manifest shortcut exposure is browser/OS discretionary. Separate mode-specific Home Screen entries can be documented as an optional setup, not treated as guaranteed platform behavior.

## macOS

### PWA MVP

- installed web app or Chromium PWA in Dock/Applications;
- focused-app shortcut;
- mode-specific links;
- offline queue;
- browser/app notifications with generic content.

### Later wrapper/native

- menu-bar item;
- system-wide shortcut;
- floating capture window;
- launch at login;
- share extension/services integration;
- keychain and app-switcher protections.

A Tauri wrapper is the preferred evaluation candidate because it can reuse the web UI and provides official global-shortcut and desktop integration plugins. Selection requires a future ADR, security review, packaging/update plan, and measured need.

## Windows

### PWA MVP

- Edge-installed PWA;
- Start menu and optional taskbar pin;
- manifest shortcuts surfaced as Windows jump-list items where supported;
- share target for selected text/links;
- protocol handler or App Action evaluation;
- offline queue and Background Sync enhancement;
- dedicated app window.

### Later wrapper

- global system shortcut;
- system tray;
- reliable always-on-top window;
- startup behavior;
- native credential protection;
- packaged Windows Share integration where PWA behavior is insufficient.

## Launch URL contract

```text
/capture                    general capture
/capture/note               Quick Note
/capture/conversation       Conversation Log
/capture?context_type=project&context_id=<opaque>
```

Sensitive context titles and text must not appear in URLs. Context IDs are opaque and server-validated. Authentication redirects must preserve a bounded return token without exposing content.

## Platform sequencing

1. Responsive in-app surface.
2. Installable PWA and route shortcuts.
3. Offline queue and foreground sync.
4. Windows PWA shortcut/share integration.
5. Apple Shortcut setup guidance using deep links.
6. Measure missed captures, launch latency, and requested integrations.
7. Consider Tauri desktop wrapper.
8. Consider native Apple target only for App Intents/widgets/controls/share extension.
