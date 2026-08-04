---
title: my-pa — Canonical Information Architecture
artifact_id: IA-MYPA-CANONICAL-002
artifact_type: Information architecture
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

# Canonical Information Architecture

## Primary navigation

| Destination | Primary job | Not |
|---|---|---|
| Today | Understand what deserves attention | generic feed/dashboard |
| Situations | Work in preserved context | folder hierarchy |
| Review | Exercise authority over consequential proposals | inbox for every tag |
| Library | Browse source/domain collections and saved views | destination per object |
| System | Understand capability, source, queue, privacy, failure | hidden admin console |

## Persistent global actions

**Reveal** searches/reconstructs with scope, coverage, freshness, authority, completeness, unavailable sources, and references.

**Capture** creates Quick Notes or Conversation Logs from shell, command palette, keyboard, routes, and contextual workspaces.

## Today

Pulse; due/at-risk commitments; decisions awaiting Review; relationship follow-ups; project exceptions; active Situations; explicit reminders; failures requiring action; accepted changes affecting priority.

## Situation

May center Project, Person/Relationship, Meeting, Decision, Commitment, Risk/Issue, Open Question, or mission. Contains scope, Frame, contextual Pulse, evidence rail, commitments, decisions, tasks, questions, risks/issues, timeline/Trace, Review links, Capture, saved state, receipts.

## Library

Sources; Captures; Notes; Conversations; Relationships; Organizations; Projects; Commitments; Decisions; Tasks; Knowledge; Saved Views.

## Review taxonomy

Extraction; identity; commitment; decision; financial/date; relationship observation; contradiction; source change/revalidation; duplicate/merge; privacy/model eligibility; deletion/retention; action proposal later.

## System taxonomy

Sources/enrollment; coverage; processing; search/index; models/policy; database/storage; offline devices/sync; review backlog; audit/receipts; capabilities/build/schema; incidents/recovery.

## Routing rule

Unresolved consequential items belong in Review. Processing/sync/coverage failures belong in System. Source records remain in Library even when enrichment fails. Timelines remain contextual to Projects, Relationships, Conversations, Meetings, Decisions, Commitments, and Situations.

## Frontier-client integration

MCP is not a primary destination and does not alter the canonical navigation. Connector administration belongs under **System**; product-owned artifacts created through a client appear under **Library** and enter **Review** when their content or lifecycle requires it.

### System > Connected Clients

- client profile, vendor/display name, protocol/profile version, verification status;
- connection/session state and last successful invocation;
- authenticated actor and client attribution;
- granted capabilities, scopes, purposes, classifications, roots, and side-effect classes;
- read/write/global enablement and independent kill switches;
- authorization expiry, refresh/revocation state, and reauthorization action;
- capability availability and degraded/unavailable reasons;
- safe mode, ingress/origin health, and policy version;
- invocation trace, denials, audit events, and mutation receipts.

### Library > Managed Documents

- managed root/folder hierarchy and document identity;
- current immutable version, history, lineage, source references, classification, and client/model provenance;
- active, conflict, archived, restored, quarantined, or unavailable state;
- comments and Review links.

A source object never appears as a writable managed object. A managed document may cite a source version but does not inherit source authority. Physical NAS paths and protected infrastructure metadata never become navigation labels.

## Apple source configuration placement

The primary navigation remains **Today, Situations, Review, Library, System**. Apple source setup is not a new primary destination.

```text
System
  Sources
    Apple Mail, Calendar & Contacts
      Bridge and permissions
      Accounts
        Mailboxes
        Calendars
        Contact collections
      Initial sync
      Watchers and freshness
      Failures and reconciliation
      Configuration history
```

Library exposes source-backed Mail, Calendar, and Contact lenses only where useful for retrieval and evidence inspection. Relationship and Situation views may surface derived context with citations to source objects. Review receives ambiguous identity links, conflicting derived assertions, and consequential promotions; it does not receive routine duplicate observations.

The source configuration surface SHALL expose exact scope, reachability, permission, baseline progress, watcher state, freshness, limitations, and retry/reconfiguration actions. It SHALL NOT expose provider-native opaque identifiers as the primary user label or imply that a display name is a stable identity.
