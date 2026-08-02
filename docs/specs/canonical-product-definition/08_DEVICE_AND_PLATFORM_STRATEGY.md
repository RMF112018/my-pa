---
title: my-pa — Device and Platform Strategy
artifact_id: PLATFORM-MYPA-CANONICAL-002
artifact_type: Device and platform strategy
package_id: MYPA-CANONICAL-PRODUCT-DEFINITION-20260802-006
coordination_request_id: REQ-MYPA-CANONICAL-PRODUCT-MCP-INTEGRATION-20260802T095600Z
version: 2.1
status: CURRENT_CANONICAL_PRODUCT_DEFINITION
date: 2026-08-02
repository: RMF112018/my-pa
repository_head: 9096fa4fbe64ff1cdabc07e53a3e68c52efc8575
repository_tree: UNAVAILABLE_FROM_AUTHENTICATED_CONNECTOR
canonical_parent_folder_id: 1Ss71vau8phz7dvXduy7ChIwtxcU3K8Rz
package_folder_id: 1Z8Aug1_3v6ILgvopY8XpjiNMBySZOCCq
implementation_authority: NOT_GRANTED
repository_mutation: NOT_PERFORMED
revision_action: REVISE
prior_version: 2.0
feature_package_id: MYPA-FRONTIER-NAS-MCP-CONNECTOR-FEATURE-PACKAGE-20260802-086
feature_package_folder_id: 1McYcZODHhUb2k-vOQJnkHVQyqHbWRuVa
---

# Device and Platform Strategy

## MVP

Responsive web/PWA on iPhone, iPad, macOS, and Windows.

| Capability | MVP | Later |
|---|---|---|
| In-app Capture and mode routes | Required | — |
| Focused-app keyboard/command palette | Required | — |
| Home/Start installation | Platform-supported | — |
| PWA manifest shortcuts | Where supported | — |
| Text/URL share target | Near-term | Native share extension |
| Offline Capture | Required, append-only | stronger native key storage |
| Background sync | Opportunistic | native scheduling |
| System-wide hotkey | Not promised | wrapper/native |
| Floating/menu/tray | Not promised | wrapper/native |
| App Intents/Siri/Spotlight/widgets | Not promised | native Apple |
| Stored audio memo | Excluded | separate feature |
| Call interception/recording | Rejected | not implied |

### iPhone
Full-height capture, keyboard open, Save above safe area, generic notifications, mode route/shortcut, no native quick-action claim, foreground/resume sync.

### iPad
Touch/hardware keyboard, centered/full-height sheet, one canvas plus drawers, no evidence rail during minimal capture, split-view where practical.

### macOS
Browser/installed PWA, command palette, focused-app shortcut, modal/app window. Global shortcut/menu utility deferred.

### Windows
Installed PWA, Start/taskbar, supported manifest shortcuts, app-window capture. Global hotkey/tray deferred; share target near-term subject to support.

## Offline security

IndexedDB transaction; application-layer encryption; keys not plaintext beside ciphertext; no text in localStorage/cache URLs/logs/analytics; reauthentication policy; explicit browser-origin/storage-eviction limitations.

## Native evaluation triggers

Invest only when measured launch/reliability harms usage; browser key/storage blocks policy; global hotkey/native integration has material frequency; PWA background limits cause loss; or accessibility/security cannot be met.

## Testing

Keyboard/touch/screen reader; large text; reflow; orientation; safe areas; reduced motion; high contrast; offline transitions; storage pressure; session expiration; account switch; representative devices.

## Frontier clients as supplemental surfaces

Frontier clients may add interaction surfaces across iPhone, iPad, macOS, Windows, web, and other supported devices. Their availability and behavior are client-specific and must be verified per profile. They supplement rather than replace the responsive web application, PWA, Quick Capture surfaces, and first-party Review/System controls.

Device strategy rules:

- external-client access never becomes the only usable path to evidence, revocation, receipts, recovery, or Review;
- an external client may be unavailable on a device without degrading first-party continuity;
- sensitive disclosure eligibility is evaluated by application policy, not inferred from the device or client login;
- offline first-party Capture remains independent of remote MCP connectivity;
- client mobile support is conditional until verified; desktop/web protocol success does not imply mobile parity;
- production profiles document redirect behavior, background refresh support, schema caching, tool-count limits, and transport constraints by client/version.

## Remote Quick Capture MCV platform decision

The first remote capture client is an iOS Shortcut calling the authenticated `capture.create` HTTPS endpoint. Supported invocation paths include Siri, Home Screen, Share Sheet, supported Lock Screen or Action Button surfaces, and Apple Watch. The Shortcut presents one unrestricted text field and may accept dictated, pasted, or shared text.

The PWA remains the canonical cross-platform client for iPhone, iPad, macOS, Windows, and Android, and owns capture history, correction, Review, attachments, and reliable offline recovery. Browser Background Sync is a progressive enhancement rather than the correctness mechanism; locally queued payloads must replay on foreground, resume, online events, or explicit retry and remain until the server receipt is verified.

The initial Shortcut may use a narrowly scoped, independently revocable capture-only credential with no read, administrative, or external-action authority. A later native iOS helper may replace this with Keychain-backed credentials and stronger offline queueing.

