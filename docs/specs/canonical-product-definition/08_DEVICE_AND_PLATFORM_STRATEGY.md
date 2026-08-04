---
title: my-pa — Device and Platform Strategy
artifact_id: PLATFORM-MYPA-CANONICAL-002
artifact_type: Device and platform strategy
package_id: MYPA-CANONICAL-PRODUCT-DEFINITION-20260802-006
coordination_request_id: REQ-MYPA-CANONICAL-PRODUCT-APPLE-MCC-MOSS-INTEGRATION-20260804T214700Z
version: 2.3
status: CURRENT_CANONICAL_PRODUCT_DEFINITION
date: 2026-08-04
repository: RMF112018/my-pa
repository_head: 195fa54206996dddd6c6e0b6da0872781aa4f5f0
repository_tree: UNAVAILABLE_FROM_AUTHENTICATED_CONNECTOR
canonical_parent_folder_id: 1Ss71vau8phz7dvXduy7ChIwtxcU3K8Rz
package_folder_id: 1Z8Aug1_3v6ILgvopY8XpjiNMBySZOCCq
implementation_authority: NOT_GRANTED
repository_mutation: NOT_PERFORMED
revision_action: REVISE
prior_version: 2.2
feature_package_id: MYPA-NATIVE-APPLE-PERSONAL-DATA-CAPTURE-BRIDGE-FEATURE-PACKAGE-20260804-087
feature_package_folder_id: 13jS8vmsWHvwQQqPksNlwW5r2whH8V8Z5
feature_package_manifest_id: 1gBPfHAtPClqFoT7skQJlpp9Sf2L72q_J
feature_package_publication_receipt_id: 1ATS9ONwZmA9Ar1_-sHaxCKcRUUwvoOqT
integration_control_folder_id: 1PLw2r7MmNXKi2pZxaIRiXTNVg-itiZ99
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
## Native Apple Reminders MCV platform decision

The always-on Mac hosts a signed Swift bridge that runs in the logged-in user session, registers through `SMAppService`, authenticates to my-pa over loopback, and uses EventKit to manage one dedicated iCloud Reminders list. The bridge supplies the native permission, onboarding, list-selection, health, safe-mode, and diagnostics surface.

The PWA remains the canonical my-pa task, history, correction, Review, conflict, and provenance surface. Apple Reminders is the native execution surface across iPhone, iPad, Mac, and Apple Watch. No native iOS my-pa application is required for this feature. The Mac bridge may be offline or asleep without invalidating the Task; pending projection state remains visible and reconciles when the bridge returns.

AppleScript, Shortcuts-based synchronization, direct Reminders database access, LaunchDaemon execution, MCP as an internal bridge protocol, and a separate XPC service are rejected for the MCV. Shortcuts remains an explicit Remote Quick Capture client, not the reminder synchronization engine.

## Native macOS source bridge

Apple Mail, Calendar, and Contacts require a native macOS component because provider discovery, TCC permissions, EventKit, Contacts, and Mail automation are not browser capabilities. The target is a signed and notarized app-bundled helper running in the logged-in user session and registered through the supported macOS service lifecycle.

The bridge is a narrow integration host, not a second backend. It performs permission checks, inventory discovery, bounded read-only export, source normalization, protected spooling, and authenticated submission. Product policy, durable authority, Review, provenance, and canonical persistence remain in my-pa.

Calendar uses EventKit with the broad OS permission structurally constrained to read-only behavior by the adapter and tests. Contacts uses `CNContactStore` with field minimization and selected collection scope. Mail requires an implementation feasibility gate: MailKit is extension-oriented, so a bounded read-only Apple Events/Scripting Bridge path may be required and must be proven against current macOS/TCC/sandbox behavior before commitment.

The MCV does not require iPhone or iPad source adapters. Those devices consume synchronized my-pa results and configuration status through the first-party interface; the always-on Mac is the Apple source-access host. Cloud-hosted Macs and direct local database access are excluded.
