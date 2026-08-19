---
title: "FEATURE-MYPA-RELATIONSHIP-INTELLIGENCE-v0.3 — Program-Scale Stakeholder & Business Entity Intelligence"
artifact_id: "FEATURE-MYPA-RELATIONSHIP-INTELLIGENCE-001"
feature_name: "Relationship Intelligence"
classification: "FEATURE_SPECIFICATION"
version: "0.3"
status: "PROPOSED_SUCCESSOR_READY_FOR_OPERATOR_REVIEW"
date_created: "2026-08-17"
date_mirrored: "2026-08-19"
product: "my-pa"
repository: "RMF112018/my-pa"
planning_branch: "main"
planning_head: "f3bffc2549d1ca466ee5fa08b7f9879870ae488e"
planning_tree: "733007094164f3f07ca62026ff43c4b64d407873"
predecessor:
  - artifact_id: "FEATURE-MYPA-RELATIONSHIP-INTELLIGENCE-001"
    version: "0.2"
    path: "relationship-intelligence-v0.2.md"
implementation_authority: false
repository_mutation_authority: false
deployment_authority: false
risk_acceptance_authority: false
governing_plan: "PLAN-MYPA-RELATIONSHIP-INTELLIGENCE-v0.3-20260817-001"
governing_audit: "AUDIT-MYPA-RELATIONSHIP-INTELLIGENCE-PR135-20260819-001"
---

# Relationship Intelligence v0.3

## Program-Scale Stakeholder & Business Entity Intelligence

## Provenance and how strongly this mirror can be trusted

This is a mirror, not an original composition. It is not, however, mirrored the
way `relationship-intelligence-v0.2.md` and `canonical-product-definition/`
were: those were retrieved by `rclone` from a live Drive file or package and
independently hashed against a publisher-issued receipt. This document has no
such receipt to check against. It was transcribed from the exact text handed
into this remediation cycle as the controlling requirements source —
`/tmp/ri-v03/FEATURE-v0.3.md`, SHA-256
`4aa380e094596cc8471d9f3ef16860741a03924dab15fd14b082d9cc2fc1b71c` over
49,720 UTF-8 bytes — with the source file's paragraph-per-line, backslash-escaped
Markdown export shape (a Google Docs export artifact, the same shape
`relationship-intelligence-v0.2.md` preserves literally) normalized into
ordinary Markdown: escape characters removed, doubled blank lines collapsed to
one. No wording, heading, list item, or acceptance criterion was reworded,
reordered, or dropped in that normalization. This is a weaker evidence tier
than the byte-exact hash checks recorded elsewhere in `docs/specs/` — **content
identity by direct transcription, not an independently re-hashed export** —
and is stated plainly rather than described as byte-exact.

**Why this document exists.** Independent audit
`AUDIT-MYPA-RELATIONSHIP-INTELLIGENCE-PR135-20260819-001` (disposition
`CORRECTIONS_REQUIRED`, bound to head `d5861e928b0f6da48cf32f0445292b694879aaac`)
found that pull request #135 named `relationship-intelligence-v0.2.md` as its
requirements source, then defined its own `WP-RI-01..13` and evaluated its own
first-forty acceptance ledger — both materially different from the controlling
v0.3 plan (`PLAN-MYPA-RELATIONSHIP-INTELLIGENCE-v0.3-20260817-001`) and its
`RI-AC-001..040` (section 21 below). That substitution is
`RI-PR135-BLOCKER-001`. This mirror closes it by making the actual controlling
v0.3 text a repository artifact that
[`docs/plans/relationship-intelligence-implementation-plan.md`](../plans/relationship-intelligence-implementation-plan.md)
and
[`relationship-intelligence-v0.3-acceptance.md`](relationship-intelligence-v0.3-acceptance.md)
can cite directly, instead of a document a reviewer would have to take on
report.

**What mirroring does not do.** As the front matter states, and as the
document's own section 27 restates: this specification authorizes no
repository mutation, database migration, connector or source traversal, live
program-data ingestion, OAuth/client/grant change, scheduled-task mutation,
remote-write activation, merge, deployment, production activation, destructive
action, or risk acceptance. Publishing this mirror is not the operator decision
section 25 asks for.

## Lineage — this document supersedes nothing by itself

`relationship-intelligence-v0.2.md` is **not deleted, not rewritten, and not
demoted to an error**. Section 5.1 below states plainly that v0.3 "extends and
operationalizes" the v0.2 direction rather than introducing a competing identity
subsystem, and the canonicality note the source document carries is preserved
in the front matter above: v0.3 is a *proposed* current successor, and v0.2
"remains lineage evidence until an operator-approved product/documentation
transition makes v0.3 controlling." A forward-pointing header has been added to
the top of `relationship-intelligence-v0.2.md` itself so a reader who opens that
file first is not left to discover this document by accident.

For this remediation cycle specifically, `RI-PR135-BLOCKER-001` is about which
document a *pull request* may cite as its requirements source and evaluate its
work packages and acceptance criteria against — v0.3, not v0.2, per the
controlling brief for this cycle — not about which document is the whole
product's permanently settled specification. That broader operator decision
(section 25, item 1 below) remains open and is not decided by this mirror.

---

## 1. Executive conclusion

`my-pa` needs a first-class, durable **Relationship Intelligence** domain that can identify and reason about hundreds of project and business stakeholders without relying on LLM memory, display names, ad hoc contact lists, or a single Microsoft source.

The core product decision is:

> **Every real-world stakeholder or business entity receives a durable `entity_id`; names, email addresses, nicknames, directory IDs, company affiliations, project assignments, roles, and source-system identifiers are evidence-bearing attributes or relationships—not identity itself.**

This feature expands Relationship Intelligence v0.2 into a program-scale business-entity registry and identity-resolution substrate designed for both Bobby and connected LLM clients such as ChatLLM through `my-pa-mcp`.

It is deliberately **not** a generic CRM, not a parallel graph database, and not an autonomous profile-building system. PostgreSQL remains canonical. The graph is a logical domain model expressed through relational records, typed temporal edges, evidence, provenance, and deterministic application services.

The feature must enable questions such as:

- Who is this “Mike” in the current Boca thread?
- Which Michael Johnson is the electrical PM versus the owner representative?
- Who works for Arquitectonica and is active on the Tower scope?
- Who is the current decision maker for permanent power?
- Which commitments and meetings involve a particular person or organization?
- Which stakeholder records are ambiguous, stale, inferred, or awaiting confirmation?
- What changed about a person’s company, title, project assignment, or responsibility over time?
- What compact context should ChatLLM receive when a person or organization is mentioned?

The system must answer with identity, scope, confidence, provenance, alternatives when ambiguous, and temporal validity—not merely a guessed name match.

---

## 2. Problem statement

Large construction programs create an identity problem before they create a retrieval problem. The Boca Raton program can involve hundreds of people across owner, operator, Moss, design teams, consultants, subcontractors, vendors, authorities, specialty partners, and internal support functions. The same stakeholder can appear in:

- Outlook email and calendar;
- Microsoft Teams conversations and meeting attendance;
- SharePoint documents and meeting minutes;
- OneDrive files;
- GoodNotes-derived notes;
- `my-pa` Tasks, Commitments, Situations, Decisions, Captures, managed knowledge, and future intelligence reports;
- ChatLLM conversations and scheduled/self-improving Agent Tasks.

Those sources use inconsistent identifiers. A single person can appear as:

- `Michael Johnson`;
- `Mike Johnson`;
- `M. Johnson`;
- `Mike`;
- an email address;
- a Teams/Entra object ID;
- “ABC electrical PM”;
- an attendee identity;
- an abbreviated name in minutes;
- a handwritten reference.

The inverse problem is equally important: two different people can share the same name. An LLM that guesses based on lexical similarity can silently attach the wrong company, project, commitment, or statement to the wrong person.

The required product capability is therefore not “contacts.” It is **durable business-entity identity, scoped relationship intelligence, evidence-backed resolution, and human-correctable ambiguity management**.

---

## 3. Product goals

### 3.1 Primary goals

1. Maintain one durable canonical identity for each known stakeholder or business entity within a Principal’s `my-pa` scope.

2. Resolve aliases and external identifiers to canonical entities deterministically whenever sufficient evidence exists.

3. Preserve ambiguity rather than silently selecting a weak match.

4. Represent organizational, program, project, work-package, team, role, and responsibility relationships separately from a person’s identity.

5. Preserve history when a person changes company, title, project, role, or responsibility.

6. Preserve evidence and provenance for every material identity or relationship assertion.

7. Distinguish confirmed facts, direct observations, derived/inferred hypotheses, proposals, rejected hypotheses, and superseded facts.

8. Provide compact, bounded, agent-oriented context cards for ChatLLM and other model clients.

9. Support conversational maintenance such as “remember that Chris Davidson is the owner’s AV consultant for Boca” through governed application services.

10. Allow multi-source discovery and enrichment without granting autonomous agents unrestricted canonical profile mutation.

11. Make Relationship Intelligence reusable by Meeting Intelligence, Action & Commitment Intelligence, Watch List Intelligence, Morning Brief, context preparation, search, and future executive-continuity workflows.

12. Scale comfortably to at least program-scale synthetic fixtures containing hundreds of people and organizations while preserving deterministic identity boundaries.

### 3.2 Secondary goals

- Give Bobby a concise stakeholder directory that is more useful than an alphabetical contact list.
- Make “who is this?” and “who owns this?” questions first-class product workflows.
- Reduce duplicated contact/person records created by different ingestion sources.
- Make role changes and stale assignments reviewable.
- Support explainable identity resolution for agent use.
- Support future stakeholder-network and topic-affinity views without requiring a graph database in v1.

---

## 4. Non-goals

The first release does **not** attempt to:

- replace Outlook/Apple/enterprise contacts as authoritative source systems;
- become an enterprise CRM, HRIS, vendor master, or procurement system;
- infer sensitive personal traits, protected characteristics, personality profiles, or speculative private attributes;
- autonomously rate people as “good,” “bad,” “difficult,” “unreliable,” or similar subjective judgments;
- infer reporting relationships or decision authority from one weak observation and silently make them canonical;
- create a separate graph database or vector database;
- expose unrestricted entity merge/delete authority to scheduled agents;
- scrape external social networks or personal-data sources merely to enrich profiles;
- make project assignments timeless properties on a Person record;
- treat an LLM-generated summary as independent corroboration of the evidence that generated it;
- replace existing `my-pa` Task, Commitment, Situation, Capture, Knowledge, Review, audit, or context domains.

---

## 5. Relationship to existing my-pa product direction

### 5.1 Relationship Intelligence v0.2 lineage

Relationship Intelligence v0.2 already established the correct product family: canonical persons, aliases/identifiers, program/project membership, organization relationships, role assignments, relationship edges, observations/sources, provenance, confidence, conflict handling, and a prohibition on silent inference.

v0.3 **extends and operationalizes that direction at program scale**. It does not introduce a competing identity subsystem.

Material v0.3 additions include:

- generalized `Entity` identity beyond only Person;
- explicit source-system identifiers and identifier namespaces;
- temporal, scoped membership/assignment records;
- formal resolution outcomes and collision handling;
- candidate/proposal workflows for agent-discovered changes;
- entity merge/split/redirect semantics;
- compact model context cards;
- stakeholder classification dimensions for construction programs;
- first-class MCP read/resolve/context contracts;
- explicit integration with the current managed-knowledge/context architecture;
- program-scale test fixtures and resolution-quality metrics.

### 5.2 Current repository alignment

At the planning baseline, `my-pa` is a Python 3.12 application using:

- a layered package structure under `src/my_pa/` including `domain`, `application`, `contracts`, `infrastructure`, and `adapters`;
- PostgreSQL through SQLAlchemy/psycopg;
- Alembic migrations;
- official MCP SDK integration through adapters;
- existing context, identity, continuity, capture, knowledge, GoodNotes, authorization, and audit concepts;
- current remote ChatLLM-facing Task read/write work on `main`.

Relationship Intelligence must therefore be implemented as a native application domain and adapter surface, not as a sidecar service.

### 5.3 Managed Knowledge / context alignment

The current product direction uses application-owned context assembly (`context.prepare`) to provide bounded, Principal-scoped context to model clients. Relationship Intelligence should become an authorized structured context plane for that path.

The recommended division of responsibility is:

- Relationship Intelligence owns canonical entity identity, aliases, identifiers, assignments, relationships, observations, proposals, and entity context summaries.
- Managed Knowledge owns source-backed evidence and broader retrieval.
- Review owns promotion/rejection of consequential proposals when review is required.
- `context.prepare` may compose Relationship Intelligence facts and references with other authorized evidence planes.
- ChatLLM performs reasoning/presentation over returned context; it does not become the identity database.

---

## 6. Design principles and invariants

### RI-I-001 — Durable identity

Every canonical entity has an opaque durable `entity_id`. Renaming a person or changing a company does not change that ID.

### RI-I-002 — Names are not identities

A canonical/display name is an attribute. Aliases and abbreviated references are identifiers only within explicit evidence and scope.

### RI-I-003 — Stable external IDs outrank fuzzy text

When an authorized source provides a stable external identifier—such as directory object ID or source-system contact ID—that exact identifier has higher resolution authority than lexical matching.

### RI-I-004 — Scope matters

“Mike” in a Boca Tower electrical coordination meeting has different contextual evidence than “Mike” in an unrelated personal context. Resolution must consider Principal, program, project, organization, meeting/thread, source, role, and participant context where available.

### RI-I-005 — Ambiguity is data

If two plausible entities remain, the system returns `AMBIGUOUS` with alternatives rather than inventing certainty.

### RI-I-006 — Temporal truth

Employment, title, program membership, project assignment, role, responsibility, and many relationships are effective-dated. Historical truth must remain queryable.

### RI-I-007 — Evidence before canonicalization

Every material fact has provenance. Model-derived facts remain observations/proposals until the governing promotion rule is satisfied.

### RI-I-008 — No silent merge

Entity merges are consequential. Ambiguous or potentially destructive merges require an explicit governed operation with preview, audit, reversibility/redirect semantics, and operator/reviewer authorization.

### RI-I-009 — Principal isolation

All entity records and derived context are Principal-scoped according to existing `my-pa` identity and authorization architecture. Caller-supplied Principal selection must not bypass that architecture.

### RI-I-010 — Least necessary PII

Store only identifiers and stakeholder facts needed for the product’s continuity/identity use cases. Avoid speculative or sensitive profiling.

### RI-I-011 — Explainable resolution

Every nontrivial resolution response must be able to report the evidence dimensions that produced the result without exposing forbidden source content.

### RI-I-012 — One business logic plane

MCP, HTTP, CLI/PWA, scheduled tasks, and future clients call the same application services and policy gates; adapters do not reimplement identity logic.

---

## 7. Canonical domain model

The logical model is relational. “Graph” refers to typed connections between entities, not a database technology requirement.

### 7.1 Entity

`Entity` is the stable root object.

Recommended initial types:

- `PERSON`
- `ORGANIZATION`
- `PROGRAM`
- `PROJECT`
- `WORK_PACKAGE`
- `TEAM_OR_GROUP`
- `LOCATION`

Roles, disciplines, responsibility classes, topics, and attention levels should begin as controlled values/records rather than universal entities unless implementation evidence justifies promotion.

Suggested core fields:

- `entity_id`
- `principal_id`
- `entity_type`
- `canonical_name`
- `display_name`
- `status` (`ACTIVE`, `INACTIVE`, `HISTORICAL`, `MERGED_REDIRECT`, `ARCHIVED`)
- `created_at`, `created_by`
- `updated_at`
- `version`
- `merged_into_entity_id` nullable

### 7.2 Person profile

Person-specific attributes should be separated from general identity where useful:

- preferred/given/family names;
- optional honorific/suffix;
- current descriptive title as a convenience projection only;
- preferred reference name;
- optional business phone(s), subject to source/provenance policy.

Current employer/title are **derived current views** over effective-dated assignments, not the permanent Person identity.

### 7.3 Organization profile

Recommended attributes:

- legal or canonical organization name;
- commonly used name;
- organization type;
- parent/affiliate relationships when known;
- active/inactive status;
- source identifiers.

### 7.4 Entity alias

Aliases capture textual references.

Fields should include:

- `alias_id`
- `entity_id`
- normalized value
- display/raw value
- alias type (`FULL_NAME`, `PREFERRED_NAME`, `NICKNAME`, `INITIALS`, `ABBREVIATION`, `DOCUMENT_REFERENCE`, `OTHER`)
- optional scope (`PROGRAM`, `PROJECT`, `ORGANIZATION`, source-specific)
- provenance/evidence reference
- confidence/status
- effective dates when applicable

An alias such as “Mike” must not become globally unique merely because it points to one person in one project.

### 7.5 External identifier

External identifiers are namespace-qualified exact identifiers.

Examples:

- email address;
- Microsoft Entra object ID;
- Teams user identity;
- Outlook/Graph contact ID;
- Apple contact stable identifier where supported;
- source-system participant ID;
- organization vendor/contact system ID.

Fields:

- `identifier_id`
- `entity_id`
- `namespace`
- normalized value
- display/raw value if required
- source account/source system
- verified status
- effective dates
- provenance

Uniqueness constraints must be namespace- and Principal-aware, with explicit handling for recycled or historical identifiers.

### 7.6 Assignment / membership

A person’s relationship to an organization/program/project/work package is not embedded permanently on the Person row.

Recommended assignment record:

- `assignment_id`
- subject entity (usually Person or Organization)
- scope entity (`ORGANIZATION`, `PROGRAM`, `PROJECT`, `WORK_PACKAGE`, `TEAM_OR_GROUP`)
- assignment type (`EMPLOYMENT`, `MEMBERSHIP`, `PROJECT_ASSIGNMENT`, `WORK_PACKAGE_ASSIGNMENT`, `TEAM_MEMBERSHIP`)
- role/title
- discipline
- responsibility class
- start/end/effective timestamps
- status
- source/provenance
- confidence/promotion state

This allows “worked for Suffolk, now Turner” or “Tower through June, Yacht Club starting July” without rewriting history.

### 7.7 Typed entity relationship

Relationships are directed typed edges with scope and time.

Examples:

- `WORKS_FOR`
- `REPORTS_TO`
- `REPRESENTS`
- `MANAGES`
- `LEADS`
- `RESPONSIBLE_FOR`
- `APPROVER_FOR`
- `DECISION_MAKER_FOR`
- `PRIMARY_CONTACT_FOR`
- `MEMBER_OF`
- `CONSULTANT_TO`
- `CONTRACTOR_ON`
- `SUBCONTRACTOR_TO`
- `VENDOR_FOR`
- `AFFILIATED_WITH`

Fields:

- `relationship_id`
- source entity ID
- relationship type
- target entity ID
- optional scope entity ID
- effective dates
- state/status
- evidence/provenance
- confidence
- version

The relation vocabulary must be bounded and documented. Free-form relationship labels can be accepted only as notes/proposals until normalized.

### 7.8 Entity observation

An observation records evidence-derived information without necessarily changing canonical truth.

Examples:

- “Jane appears in six Yacht Club commissioning meetings.”
- “Document dated 2026-08-11 lists Chris as AV consultant.”
- “Three recent emails use title Senior PM.”

Fields:

- observation ID
- entity or candidate reference
- observation type
- structured payload
- source/evidence reference
- event time and observed/captured time
- actor/process identity
- confidence
- derivation lineage
- status

### 7.9 Entity proposal

A proposal is a reviewable requested mutation such as:

- create a new entity;
- add alias;
- add external identifier;
- change/add employment assignment;
- change role/title;
- add relationship;
- mark assignment stale/end-dated;
- merge possible duplicates;
- split an incorrectly merged entity.

The proposal must contain before/after or proposed payload, evidence references, reason, confidence, dedupe/idempotency key, and lifecycle state.

### 7.10 Source/provenance binding

Material records should bind to existing product provenance primitives wherever practical rather than inventing an isolated source model.

At minimum, preserve:

- source type/system;
- source stable identifier or evidence pointer;
- source account/tenant context where required;
- event time;
- capture/observation time;
- content hash/version reference where available;
- actor/process identity;
- derivation lineage;
- confidence and promotion status.

### 7.11 User relationship/attention facet

A Principal may need operational metadata about their relationship with an entity:

- attention level: `CRITICAL`, `HIGH`, `NORMAL`, `LOW`;
- interaction frequency as observed metadata;
- last known interaction timestamp;
- typical active topics derived from evidence;
- current open linked commitments/tasks/watch items;
- preferred communication or preparation notes **only when explicitly recorded or defensibly factual**.

Do not persist unsupported personality judgments.

### 7.12 Entity context card

The context card is a bounded projection, not a separate truth store.

It should summarize:

- canonical identity and disambiguators;
- current organization/title/role with dates/confidence;
- active program/project/work-package scopes;
- critical relationships/responsibilities;
- relevant current Task/Commitment/Situation/Watch links when requested and authorized;
- ambiguity warnings;
- key evidence/provenance references;
- “do not confuse with” collisions when useful.

Context cards should be generated deterministically from current authorized records, optionally with bounded model summarization only if that summarization remains explicitly derived and refreshable.

---

## 8. Construction-program stakeholder taxonomy

The product should support a construction-friendly multi-dimensional classification without forcing one global hierarchy.

### 8.1 Organization type

Initial controlled values should cover at least:

- Owner
- Operator
- Owner Representative
- Construction Manager / General Contractor
- Architect
- Interior Designer
- Engineer / Consultant
- Program Manager
- Subcontractor / Trade Contractor
- Vendor / Supplier
- Specialty Consultant
- Testing / Inspection
- Authority Having Jurisdiction / Utility
- Legal / Finance / Insurance
- Other

### 8.2 Discipline / function

Examples:

- Executive
- Project Management
- Field Operations
- Architecture
- Interiors
- Structural
- Civil
- MEP
- Mechanical / HVAC
- Electrical
- Plumbing
- Fire Protection
- Controls
- AV
- IT / Network
- Security
- Procurement
- Cost
- Scheduling
- Contracts
- Finance
- Legal
- Quality
- Safety
- Commissioning
- Operations / Facilities

### 8.3 Scope hierarchy

A stakeholder can be classified simultaneously against:

- Program-wide
- Project
- Building/area/location
- Work package/contract
- Topic/system

The exact Boca project/location taxonomy must come from operator/product data; this package does not invent a complete Boca hierarchy.

### 8.4 Responsibility class

Recommended controlled values:

- `DECISION_MAKER`
- `APPROVER`
- `ACCOUNTABLE_LEAD`
- `LEAD`
- `CONTRIBUTOR`
- `COORDINATOR`
- `SUBJECT_MATTER_EXPERT`
- `INFORMATION_ONLY`

Responsibility class is scope-specific and temporal.

### 8.5 Attention level

Bobby-facing prioritization:

- `CRITICAL`
- `HIGH`
- `NORMAL`
- `LOW`

This is a user-controlled or policy-derived attention aid, not an objective quality rating of the person.

---

## 9. Identity-resolution contract

Identity resolution is a first-class application use case.

### 9.1 Inputs

A resolution request may include:

- raw reference text;
- external identifier namespace/value;
- program/project/work-package context;
- organization context;
- source message/thread/meeting ID;
- co-participants;
- role/discipline hint;
- event time;
- requested entity types.

### 9.2 Resolution stages

#### Stage 1 — exact stable identifier

Exact authorized namespace/value match. If unique and valid for the event time, resolve deterministically.

#### Stage 2 — verified alias/name match

Match normalized canonical name/aliases inside relevant scope. Do not collapse same-name entities.

#### Stage 3 — contextual ranking

Rank candidates using explicit features such as:

- active program/project membership;
- organization match;
- role/discipline match;
- meeting/thread co-participation;
- recent interaction within the same scope;
- source account or participant identity;
- effective date validity;
- exact/partial alias quality.

#### Stage 4 — ambiguity decision

Return one of:

- `RESOLVED_EXACT`
- `RESOLVED_CONTEXTUAL`
- `AMBIGUOUS`
- `NOT_FOUND`
- `CONFLICTED_IDENTIFIER`
- `HISTORICAL_MATCH`

Confidence must be calibrated against test fixtures; this package does not hard-code a universal numeric threshold without evaluation evidence.

### 9.3 Resolution response

A model-facing resolution result should include:

- canonical `entity_id`;
- canonical/display label;
- entity type;
- short disambiguators (organization, current role, active project);
- outcome and confidence;
- evidence reasons/features;
- alternatives if ambiguous;
- warnings/conflicts;
- optional context-card handle or bounded card;
- provenance references appropriate to caller authorization.

### 9.4 Manual correction

If Bobby says “the Mike I meant is Mike Rodriguez from Moss,” the correction should:

1. resolve the selected canonical entity;

2. bind the local reference/context to that entity;

3. optionally create a scoped alias or disambiguation rule if safe;

4. preserve the original ambiguity/resolution evidence;

5. avoid creating a global “Mike → Mike Rodriguez” rule.

---

## 10. Entity merge, split, redirect, and duplicate handling

Duplicate identity correction is consequential and must be reversible/auditable.

### 10.1 Merge preview

Before merge, show:

- both canonical entities;
- external identifiers;
- aliases;
- assignments;
- linked Tasks/Commitments/Situations/evidence;
- conflicts;
- proposed surviving entity;
- exact references to be redirected;
- records that cannot safely reconcile automatically.

### 10.2 Merge behavior

Preferred behavior:

- preserve both historical entity IDs;
- mark loser as `MERGED_REDIRECT` to survivor;
- rewrite/link references transactionally where safe;
- preserve immutable audit and provenance;
- reject cyclic or conflicting merges;
- use optimistic concurrency and idempotency.

### 10.3 Split behavior

A split workflow is required for incorrect merges. It may be more constrained than merge in v1, but the data model must not make recovery impossible.

### 10.4 Automatic merge prohibition

Scheduled/self-improving agents may propose duplicate matches; they must not autonomously execute a consequential merge in the initial release.

---

## 11. Fact, inference, proposal, and trust model

Each material relationship-intelligence statement must have an explicit epistemic status.

Recommended states:

- `CONFIRMED` — explicitly confirmed by Bobby or a policy-authoritative source.
- `SOURCE_OBSERVED` — directly represented in source evidence.
- `DERIVED` — deterministic derivation from confirmed/observed records.
- `INFERRED` — model/statistical inference with evidence and confidence.
- `PROPOSED` — pending review/promotion.
- `REJECTED` — reviewed and rejected.
- `SUPERSEDED` — historically true or previously accepted but no longer current.
- `CONFLICTED` — incompatible evidence remains unresolved.

Rules:

1. Inferred is never silently relabeled confirmed.

2. Repeated appearances can raise confidence but do not erase provenance.

3. A generated summary cannot independently corroborate its own source lineage.

4. Source-authoritative stable identifiers may update deterministic technical metadata subject to policy.

5. Role/company/title changes with material downstream consequences should normally enter as proposal/review unless source-authority policy explicitly allows direct acceptance.

---

## 12. Discovery and enrichment

### 12.1 Sources

Authorized discovery may use:

- existing `my-pa` source/capture/knowledge records;
- email/calendar/contact ingestion available through authorized connectors;
- Teams/meeting data made available through authorized connectors or managed evidence;
- SharePoint/OneDrive managed knowledge;
- GoodNotes-derived evidence;
- Tasks, Commitments, Situations, meeting records, and intelligence reports;
- explicit user statements.

No single source is treated as sufficient merely because it contains a display name.

### 12.2 Discovery outcomes

For each encountered reference:

- known entity → link/update low-risk interaction metadata;
- probable existing entity → propose alias/identifier link;
- unknown high-confidence exact identity → propose entity creation unless direct creation policy allows it;
- ambiguous reference → preserve ambiguity and request/contextualize resolution;
- possible role/company change → create change proposal with evidence;
- possible duplicate → duplicate candidate, not merge.

### 12.3 Automatic low-risk updates

Subject to implementation review, safe automatic updates may include:

- last-seen timestamp;
- source occurrence count;
- interaction event references;
- deterministic exact external-ID sightings;
- recalculated derived current-view projections.

These updates must remain idempotent and auditable.

### 12.4 Review-gated changes

Initial release should review-gate at least:

- merge/split;
- employer changes inferred from content;
- authoritative title/role changes based on inference;
- decision-maker/approver/responsibility assertions;
- subjective/relationship judgments;
- external identifiers that conflict with an existing entity;
- anything with meaningful downstream routing or disclosure consequences.

---

## 13. Bobby-facing UX and workflows

The feature must work even if Bobby never behaves like a CRM administrator.

### 13.1 Global entity search

Search by:

- person/company name;
- email/identifier;
- alias;
- program/project;
- organization;
- discipline;
- work package;
- role/responsibility;
- attention level;
- active/historical status.

Results must show enough disambiguation to distinguish same-name people.

### 13.2 Entity detail

Recommended views:

- Overview / context card
- Identity & aliases
- Organizations & assignments
- Programs/projects/work packages
- Roles/responsibilities
- Relationships
- Activity / interactions
- Linked continuity objects
- Evidence / provenance
- Proposed changes / conflicts
- History

### 13.3 Review inbox

A focused queue for:

- new entity candidates;
- alias/link candidates;
- role/company changes;
- duplicate candidates;
- conflicts;
- stale assignment suggestions.

Bulk review may be allowed only where each item is previewable and fail-closed.

### 13.4 Conversational maintenance

Examples:

- “Remember that Chris Davidson is the owner’s AV consultant for Boca.”
- “The Mike I mean is Mike Rodriguez from Moss.”
- “Jen left Suffolk and is now with Turner.”
- “Show me the high-attention external decision makers for Tower.”
- “Who is the architect I’ve been discussing guestrooms with?”

The LLM translates intent into typed application commands; the application validates scope, ambiguity, authorization, concurrency, and evidence.

---

## 14. MCP / ChatLLM capability contract

The exact public tool names must follow current `my-pa` MCP naming and description conventions at implementation time. The following semantic surface is recommended.

### 14.1 Read capabilities

#### `entities.search`

Purpose: search canonical entities using bounded filters and text.

Returns concise identity rows with canonical ID, type, label, disambiguators, active scopes, and confidence/match reason.

#### `entities.get`

Purpose: retrieve one canonical entity by ID with bounded detail sections.

#### `entities.resolve`

Purpose: resolve a raw reference or exact external identifier using contextual hints.

Must return ambiguity explicitly.

#### `entities.context`

Purpose: return a bounded agent-oriented context card for one or more entity IDs, optionally including linked current continuity state when caller grants allow it.

#### `entities.relationships`

Purpose: list typed, scoped, effective-dated relationships for an entity.

### 14.2 Contribution/proposal capabilities

#### `entities.observe`

Purpose: persist a provenance-rich source observation without directly changing consequential canonical relationship truth.

Suitable for trusted scheduled-task profiles only after separate activation.

#### `entities.propose_update`

Purpose: propose create/link/assignment/relationship/change actions with evidence.

### 14.3 Human/operator-governed mutation capabilities

Potential later/interactive capabilities:

- `entities.confirm_update`
- `entities.merge`
- `entities.split`
- `entities.archive`

These must be independently authorized. They should not be placed in a broad scheduled-agent write profile by default.

### 14.4 Tool design rules

1. Names/descriptions must make identity-resolution behavior obvious to an LLM.

2. Schemas must be typed and bounded; no arbitrary Principal selector.

3. Mutations require existing application authorization, idempotency, version/expected-version, audit, and durable receipt patterns.

4. Bulk mutation must support preview/apply or equivalent fail-closed behavior.

5. `entities.resolve` must expose alternatives; the client must not be forced to infer from opaque confidence alone.

6. Tool output must not dump excessive PII or full source documents.

7. Remote exposure must remain grant-filtered under current MCP authorization architecture.

---

## 15. Agent operating rules

Connected LLM clients and scheduled tasks should follow these product rules:

1. When a business reference is materially ambiguous, call entity resolution before asserting identity.

2. Prefer durable `entity_id` links in internal records once resolved.

3. Do not invent an entity because search did not find one; use candidate/proposal semantics.

4. Do not treat a same-name match as proof.

5. Do not merge entities autonomously.

6. Preserve “unknown” and “ambiguous” outcomes.

7. When presenting an inferred role or relationship, label it as inferred unless canonical status says otherwise.

8. Cite or expose provenance handles when the user needs to understand why the system believes something.

9. Do not autonomously expand source scope or disclosure boundaries to improve an entity profile.

10. Do not use subjective character assessments as operational facts.

---

## 16. Integration with intelligence task family

### 16.1 Meeting Intelligence

Before producing a meeting dossier:

- resolve attendees and mentioned stakeholders;
- attach canonical entity IDs;
- use active project/organization roles to disambiguate research;
- include relevant current assignments/relationships in preparation context;
- propose unknown/changed stakeholder facts discovered during research.

### 16.2 Action & Commitment Intelligence

Link task/commitment subjects and counterparties to canonical entities where resolvable. This enables queries such as:

- commitments owed by/through a person or company;
- actions involving a project decision maker;
- overdue items with high-attention stakeholders.

### 16.3 Watch List Intelligence

Watch items can reference canonical entities and relationships without becoming actions. Entity context can explain why a stakeholder or organization matters.

### 16.4 Morning Brief

The final brief should consume canonical entity references from upstream reports rather than independently guessing identities.

### 16.5 Managed Knowledge / `context.prepare`

Relationship Intelligence becomes a structured context plane that can be included when the query contains person/company/project/entity intent. The context manifest should preserve entity IDs, evidence pointers, and ambiguity/conflict status.

---

## 17. Security, privacy, and authorization

### 17.1 Principal isolation

All reads/writes must use the current repository’s Principal and authorization framework. Identity-resolution queries may not leak another Principal’s entities.

### 17.2 Data minimization

Store business-relevant contact/role/context data needed for continuity. Avoid unnecessary personal details.

### 17.3 Sensitive inference prohibition

The system must not infer or store protected/sensitive traits merely because an LLM could derive them.

### 17.4 Source disclosure

Context cards should expose only what the calling client is authorized to receive. A tool may say that a role is source-backed without embedding entire confidential source text.

### 17.5 Audit

Consequential mutation events must record:

- Principal;
- actor/client/process identity;
- command/tool;
- before/after or proposed state;
- evidence/provenance;
- idempotency key;
- request/receipt identifiers;
- timestamp;
- authorization result.

### 17.6 Remote clients

ChatLLM or other remote MCP clients receive no inherent authority. Their visible tool surface and write permissions remain determined by existing client/profile grants and product gates.

---

## 18. Data lifecycle

### 18.1 Create

New canonical entity creation is allowed only through an authorized application command and requires adequate minimum identity data.

### 18.2 Update

Updates preserve version history or audit-diff evidence. Temporal facts should be end-dated/superseded rather than erased.

### 18.3 Archive/inactivate

Inactive stakeholders remain historical and resolvable for old meetings/documents.

### 18.4 Merge redirect

Merged IDs remain resolvable through redirects for historical links.

### 18.5 Deletion

Hard deletion of canonical relationship intelligence should not be a routine v1 workflow. Privacy/legal deletion, if needed, must follow separately governed retention/privacy rules.

---

## 19. Performance and scale expectations

The initial engineering target is program scale, not internet-scale identity resolution.

Validation must include a synthetic dataset of at least:

- 500 Person entities;
- 100 Organization entities;
- multiple Programs/Projects/Work Packages;
- 5,000+ aliases/identifiers/assignments/relationships/observations combined;
- intentionally duplicated names;
- historical company changes;
- ambiguous first-name-only references;
- conflicting identifiers;
- merged redirects.

The implementation team must benchmark and record p50/p95 behavior for search, exact resolution, contextual resolution, and context-card assembly under a defined fixture. This specification does not invent a production SLA before repository/runtime evidence exists.

---

## 20. Quality and operational metrics

Recommended metrics:

- exact identifier resolution success rate;
- contextual resolution precision/coverage;
- ambiguous-reference rate;
- false-resolution rate on labeled fixture;
- same-name collision protection rate;
- unknown-entity candidate rate;
- duplicate-candidate acceptance/rejection rate;
- merge reversal/split rate;
- stale-assignment proposal count;
- proposal review backlog and age;
- percentage of material facts with valid provenance;
- unresolved conflicts;
- context-card size and assembly latency;
- scheduled-agent proposal volume versus accepted changes.

Metrics must not pressure the system into reducing ambiguity by guessing.

---

## 21. Acceptance criteria

The feature is not acceptable merely because tables and tools exist. The following behavioral criteria are required.

### Identity and resolution

- **RI-AC-001:** Every canonical entity has a durable opaque ID independent of its name.
- **RI-AC-002:** Two people with the same canonical name remain distinct entities and can be resolved by stable identifiers/context.
- **RI-AC-003:** Exact verified external identifiers resolve deterministically when unique and temporally valid.
- **RI-AC-004:** First-name-only ambiguous references return `AMBIGUOUS` rather than a silent guess.
- **RI-AC-005:** Contextual resolution returns ranked alternatives and explainable match features.
- **RI-AC-006:** Historical identifiers/assignments can resolve historical evidence without being presented as current truth.
- **RI-AC-007:** Manual clarification can persist a scoped resolution without globally corrupting aliases.

### Temporal organization/project truth

- **RI-AC-008:** Employment/company changes preserve prior assignments.
- **RI-AC-009:** Project/program/work-package assignments are effective-dated and independently queryable.
- **RI-AC-010:** Current role/title is a derived current view over temporal facts, not destructive replacement.
- **RI-AC-011:** A stakeholder may simultaneously hold multiple scoped roles.

### Provenance and trust

- **RI-AC-012:** Every material accepted relationship/assignment has provenance or an explicit user-confirmation event.
- **RI-AC-013:** Inferred facts remain labeled inferred/proposed until promoted.
- **RI-AC-014:** Conflicting evidence is preserved and surfaced.
- **RI-AC-015:** Generated summaries cannot independently corroborate their source lineage.
- **RI-AC-016:** Rejected proposals remain auditable without polluting current canonical views.

### Duplicate management

- **RI-AC-017:** Duplicate candidates can be proposed without merging.
- **RI-AC-018:** Merge requires preview, authorization, idempotency, audit, and a deterministic survivor.
- **RI-AC-019:** Merged entity IDs continue resolving through a redirect.
- **RI-AC-020:** The design supports correction/split of an erroneous merge without erasing provenance.

### MCP and client behavior

- **RI-AC-021:** An authenticated authorized client can search entities through the application/MCP path.
- **RI-AC-022:** An authenticated authorized client can resolve an ambiguous business reference and receive alternatives.
- **RI-AC-023:** An authorized client can request a bounded entity context card.
- **RI-AC-024:** Remote tool exposure remains capability/grant filtered.
- **RI-AC-025:** Scheduled-task profiles do not receive merge/split/direct consequential canonicalization authority by default.
- **RI-AC-026:** Entity tools use the same application services and policy checks as non-MCP clients.

### Security/privacy

- **RI-AC-027:** Principal isolation tests demonstrate no cross-Principal entity read/write leakage.
- **RI-AC-028:** Caller-supplied Principal impersonation is rejected.
- **RI-AC-029:** Tool responses do not unnecessarily disclose full source contents or unrelated PII.
- **RI-AC-030:** Consequential writes produce durable audit/receipt evidence consistent with current repository patterns.

### Program-scale behavior

- **RI-AC-031:** Synthetic program-scale fixture contains at least 500 persons and 100 organizations with deliberate collisions and historical changes.
- **RI-AC-032:** The full identity-resolution acceptance suite passes against that fixture.
- **RI-AC-033:** Search/resolution/context performance is benchmarked and results recorded; unacceptable regressions block activation.

### Intelligence integration

- **RI-AC-034:** Meeting Intelligence can attach canonical entity IDs to resolved attendees/mentions.
- **RI-AC-035:** Action/Commitment intelligence can link counterparties to canonical entities without changing Task/Commitment truth semantics.
- **RI-AC-036:** `context.prepare` or its then-current successor can include relationship/entity context with provenance and ambiguity status.
- **RI-AC-037:** Unknown or changed entities discovered by scheduled tasks enter bounded observation/proposal paths rather than unrestricted canonical writes.

### Human usability

- **RI-AC-038:** Bobby can search and distinguish same-name stakeholders using organization/project/role disambiguators.
- **RI-AC-039:** Bobby can correct an incorrect or ambiguous identity conversationally through an authorized path.
- **RI-AC-040:** Bobby can inspect why a material current role/relationship is believed and locate its provenance.

---

## 22. Rollout model

Recommended staged activation:

1. **Schema + internal contracts only** — no remote exposure.

2. **Read-only synthetic fixture** — search/get/resolve/context tests.

3. **Interactive local read pilot** — known entities only.

4. **Interactive proposal workflows** — explicit user updates/corrections.

5. **Remote ChatLLM read-only canary** — grant-filtered search/resolve/context.

6. **Bounded remote interactive proposals** — separately authorized.

7. **Scheduled-task observation/proposal contribution** — separate task identity/grant and operator gate.

8. **Real program backfill** — separate authorization for live source traversal and disclosure.

9. **Broader intelligence-task integration** — only after resolution-quality and provenance gates pass.

No stage implies the next.

---

## 23. Migration / compatibility strategy

1. Treat v0.2 concepts as lineage requirements; do not duplicate them under incompatible names.

2. Reconcile current repository truth before implementation because v0.2 was published against an older repository state.

3. Prefer additive schema changes in the first release.

4. Avoid destructive conversion of existing continuity/knowledge/person references until a mapping/backfill has been validated.

5. Where existing records carry person-like references, introduce explicit entity links as nullable/additive until backfill confidence is sufficient.

6. Preserve old IDs or identifiers through mapping/redirect tables when importing predecessor data.

7. Feature-flag model-facing context and remote MCP exposure independently from persistence.

8. Do not require graph-database migration.

---

## 24. Risks and mitigations

### Risk: false identity joins

**Impact:** severe; can contaminate meeting prep, commitments, and stakeholder history.

**Mitigation:** stable-ID priority, ambiguity states, same-name fixtures, no silent merge, explainable resolution.

### Risk: profile drift / stale roles

**Impact:** agent confidently presents outdated organization/role.

**Mitigation:** effective dates, source timestamps, stale-candidate detection, current-view derivation, conflict surfacing.

### Risk: agent overreach

**Impact:** automated task makes consequential relationship judgments canonical.

**Mitigation:** observation/proposal boundary, restricted grants, Review, no merge authority, explicit promotion rules.

### Risk: duplicate identity proliferation

**Impact:** fragmented stakeholder history.

**Mitigation:** exact identifier matching, candidate dedupe, scoped aliases, duplicate review.

### Risk: privacy creep

**Impact:** relationship system becomes an unnecessary personal dossier.

**Mitigation:** business-purpose minimization, sensitive-inference prohibition, source-bound evidence, bounded context cards.

### Risk: schema over-generalization

**Impact:** an abstract graph becomes difficult to operate and query.

**Mitigation:** small initial entity/relationship vocabulary, typed assignments, relational indexes, performance fixtures.

### Risk: LLM tool confusion

**Impact:** ChatLLM skips resolution or misuses mutation tools.

**Mitigation:** compact semantic tool family, precise descriptions, contract tests, synthetic ChatLLM canary, no broad generic mutation tool.

---

## 25. Operator decisions required before implementation activation

The implementation plan can be reviewed without answering these immediately, but activation should settle them where they materially affect scope:

1. Whether v0.3 becomes the controlling Relationship Intelligence feature definition and formally supersedes v0.2 for current product direction.

2. Which initial entity types beyond Person/Organization/Program/Project/Work Package are MVP versus deferred.

3. Which source systems may directly establish exact external identifiers versus only propose them.

4. Which role/title/company changes may auto-accept from authoritative source data versus always requiring review.

5. Whether the first Bobby-facing management surface is PWA/UI, conversational MCP only, or both.

6. Whether real Boca backfill is part of the first pilot or follows a synthetic/limited pilot.

7. Which scheduled intelligence task identities will eventually receive `entities.observe` / proposal capabilities.

8. The approved construction-program taxonomy for actual Boca projects/work packages/organization categories.

---

## 26. Invalidation rules

This feature package must be reconciled before implementation if any of the following materially changes:

- current `my-pa` repository HEAD/tree or Relationship Intelligence implementation state;
- PostgreSQL/Alembic persistence architecture;
- Principal/authentication/authorization architecture;
- MCP tool registration, remote grant model, or ChatLLM task contract;
- `context.prepare` / managed-knowledge context architecture;
- Review/proposal/audit/receipt architecture;
- source-authority policy for contacts/calendar/email/Teams/SharePoint/OneDrive/GoodNotes;
- operator decision on Relationship Intelligence v0.3 scope or canonicality.

A later repository commit invalidates the exact-head binding for implementation even if the product design remains useful.

---

## 27. Disposition

**Disposition:** `RELATIONSHIP_INTELLIGENCE_V0_3_FEATURE_PACKAGE_READY_FOR_OPERATOR_REVIEW`.

This specification defines the intended product behavior and implementation target. It authorizes **no repository mutation, database migration, connector/source traversal, live program-data ingestion, OAuth/client/grant change, scheduled-task mutation, remote-write activation, merge, deployment, production activation, destructive action, or risk acceptance**.
