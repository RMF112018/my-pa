---
title: my-pa — Canonical Product Definition Package README
artifact_id: README-MYPA-CANONICAL-PRODUCT-DEFINITION-20260802-006
artifact_type: Package README
package_id: MYPA-CANONICAL-PRODUCT-DEFINITION-20260802-006
coordination_request_id: REQ-MYPA-CANONICAL-PRODUCT-NATIVE-REMINDERS-INTEGRATION-20260802T150100Z
version: 2.2
status: CURRENT_CANONICAL_PRODUCT_DEFINITION
date: 2026-08-02
repository: RMF112018/my-pa
repository_head: f18e7e3ded45f82456fbfa722443b23a004de0b3
repository_tree: UNAVAILABLE_FROM_AUTHENTICATED_CONNECTOR
canonical_parent_folder_id: 1Ss71vau8phz7dvXduy7ChIwtxcU3K8Rz
package_folder_id: 1Z8Aug1_3v6ILgvopY8XpjiNMBySZOCCq
implementation_authority: NOT_GRANTED
repository_mutation: NOT_PERFORMED
revision_action: REVISE
prior_version: 2.1
feature_package_id: MYPA-NATIVE-APPLE-REMINDERS-INTEGRATION-FEATURE-PACKAGE-20260802-001
feature_package_folder_id: 1qDE49KcJ8GSqFlljukYgGlq3eikeTnWq
---

# my-pa Canonical Product Definition

Disposition: `MYPA_CANONICAL_PRODUCT_MCP_INTEGRATION_COMPLETE`  
Package: `MYPA-CANONICAL-PRODUCT-DEFINITION-20260802-006`  
Folder: `1Z8Aug1_3v6ILgvopY8XpjiNMBySZOCCq`  
Parent: `1Ss71vau8phz7dvXduy7ChIwtxcU3K8Rz`  
Repository: `RMF112018/my-pa@b48b1b177046637297467e661dfb1da023d49bed`  
Implementation authority: `NOT_GRANTED`

This package is the current canonical whole-product definition for my-pa. It supersedes the prior vNext package as current whole-product description/specification while preserving that package as indexed historical source evidence.

## Canonical artifacts

- Product description: `15Umcs2JBMdFvxfRgNaA-P-Nc_iC3jDHV`
- Product specification: `18l1S2iz5v_qgKZg8iVBAw47xvuHkbOjI`
- Source manifest: `1xxQG_fsUlTxX7VRXOCm8SSCjYF2xPV1j`
- Coordination request: `1zlUe_O_eFI0Zf_7-JA7rx1QR8QQfs3P6`
- Coordination response: `1VZ-wATM_LsosCcqRBIYLNLpOUR4FLjEI`
- Publication receipt: `1NDjbDR8CVgW4bmlXBSu1-Vf1ymBMeee9`
- Roundtrip receipt: `1iuLO2wpncDl_tv15DHb6dsZX2s_sK97i`

## Package contents

{PACKAGE_CONTENTS_TABLE}

## Canonical decisions

Evidence-grounded executive continuity; operating grammar retained; Reveal/Capture persistent; Quick Capture as user-authored evidence source; RI as integrated people domain not CRM; GoodNotes through shared provenance/review; proposal-before-promotion; append-only offline Capture; PWA first; active MCV unchanged; no implementation authority.

## Supersession

Parent vNext remains preserved and authoritative source history. It is superseded only for current whole-product definition. Owning Quick Capture, RI, and GoodNotes specs remain current where more detailed and not explicitly reconciled.

## Publication status

`COMPLETE`

## Frontier NAS MCP integration

The Frontier NAS MCP Connector is now incorporated into this package as a governed external capability surface. It does not alter the product category, primary navigation, or operating loop. Authorized frontier clients invoke the same application use cases, policy decisions, source-authority rules, disclosure envelopes, audit events, review gates, managed-document lifecycle, and receipts used by first-party surfaces.

Canonical relationship:

```text
frontier client
  -> authenticated ingress
    -> thin MCP transport adapter
      -> my-pa application use case
        -> centralized policy decision
          -> source, knowledge, review, or managed-document service
            -> disclosure envelope, audit event, and receipt
```

The owning detailed definition remains `MYPA-FRONTIER-NAS-MCP-CONNECTOR-FEATURE-PACKAGE-20260802-086` in Drive folder `1McYcZODHhUb2k-vOQJnkHVQyqHbWRuVa`. This canonical package governs whole-product meaning and sequencing; the feature package governs feature-level contracts unless repository truth or an explicit operator decision supersedes it.

### Integration boundaries

- Source-provider access is read-only. No source overwrite, rename, move, delete, upload, permission change, or metadata mutation is exposed.
- Product-owned managed documents use a separate designated managed store with immutable versions, expected-version checks, idempotency, reversible archive, audit, and mutation receipts.
- Product-owned user-authored Capture records remain a third authority class under repository ADR-003; they are not managed documents and do not create source-provider write authority.
- ChatGPT, Claude, Grok, and future compatible clients are presentation and reasoning surfaces, not systems of record or independent authorities.
- MCP is not a primary navigation destination. Connection, grant, health, denial, safe-mode, invocation, and receipt controls belong under System; managed artifacts appear in Library and Review according to lifecycle.

### Scope status

The connector is canonical product scope but not silently inserted into the active repository MCV. Repository work must first complete the accepted read-only substrate, application services/transports, and local operational candidate. Remote read, standards-current OAuth, live NAS enrollment, managed-document writes, individual client enablement, private/public ingress, and production activation remain sequenced, tested, and operator-gated as defined by this package.

## 2026-08-02 Remote Quick Capture MCV amendment

Remote Quick Capture is incorporated into the current my-pa Minimum Viable Candidate product scope as the lowest-friction remote extension of Quick Capture. The selected first transport is an iOS Shortcut submitting one unrestricted text field over authenticated HTTPS to the transport-neutral `capture.create` application service. The first-party PWA remains the canonical cross-platform capture, history, correction, Review, and offline-recovery surface. Literal SMS, hosted messaging providers, new cellular service, and iMessage relay dependencies are excluded from the MCV baseline.

The governing feature package is `MYPA-REMOTE-QUICK-CAPTURE-FEATURE-PACKAGE-20260802-001`, Drive folder `1lDSkTldgSkaRfJ3v9h-U10lCe-Lmwzsv`. This amendment records product scope only. Repository implementation, credentials, ingress activation, deployment, production activation, and risk acceptance remain separately governed.
## 2026-08-02 Native Apple Reminders MCV amendment

Native Apple Reminders Integration is incorporated into the current my-pa Minimum Complete Version as an opt-in external execution projection for accepted my-pa Tasks. my-pa remains authoritative; Apple Reminders is a synchronized execution surface, never the system of record.

The selected architecture is a signed Swift macOS bridge running in the logged-in user session, registered at login through `SMAppService`, calling the transport-neutral my-pa application service over authenticated loopback HTTP and using EventKit against one dedicated iCloud Reminders list. The initial synchronization model is hybrid and field-level: my-pa owns Task identity and meaning; Apple completion is accepted as user execution evidence for the mapped Task; external edits are imported only under policy or routed to Review; deletion never deletes the canonical Task; recurrence is projected one occurrence at a time.

The governing feature package is `MYPA-NATIVE-APPLE-REMINDERS-INTEGRATION-FEATURE-PACKAGE-20260802-001`, Drive folder `1qDE49KcJ8GSqFlljukYgGlq3eikeTnWq`. This amendment admits product scope and canonical design only. Repository implementation, EventKit permissions, credentials, signing, deployment, production activation, and risk acceptance remain separately governed.
