\---  
title: "FEATURE-MYPA-RELATIONSHIP-INTELLIGENCE-v0.2 — Comprehensive Product Description and Feature Specification"  
artifact\_id: "FEATURE-MYPA-RELATIONSHIP-INTELLIGENCE-001"  
feature\_name: "Relationship Intelligence"  
historical\_alias: "Personal Relationship Intelligence Engine (PRIE)"  
classification: "Internal Product and Feature Specification"  
artifact\_type: "Comprehensive Product Description and Feature Specification"  
version: "0.2"  
status: "PROPOSED\_PRODUCT\_AND\_FEATURE\_SPECIFICATION — IMPLEMENTATION\_NOT\_AUTHORIZED"  
date\_created: "2026-08-01"  
date\_updated: "2026-08-01"  
product: "my-pa"  
repository: "RMF112018/my-pa"  
repository\_branch: "main"  
repository\_head\_at\_preflight: "40391b784ba7df2aa37f99fed86b0d4ac4723034"  
repository\_tree: "UNAVAILABLE\_FROM\_AUTHENTICATED\_CONNECTOR"  
publication\_operation: "CREATE"  
canonical\_or\_mirror: "canonical\_feature\_specification\_in\_target\_folder"  
target\_drive\_folder\_id: "1MDaLiEjNN3Fdondxs4NJpK5SfwdXjzl0"  
supersedes\_for\_current\_product\_intent:  
  \- artifact\_id: "FEAT-HBPA-PRIE-001"  
    version: "0.1"  
    drive\_id: "1LukPPAU9-9BPINjXJNXYnuJhTZYDe\_MSJficqxYxEg4"  
implementation\_authority: false  
repository\_mutation\_authority: false  
deployment\_authority: false  
risk\_acceptance\_authority: false  
\---

\# Relationship Intelligence

\#\# Comprehensive Product Description and Feature Specification

\#\# 1\. Executive definition

Relationship Intelligence is the people-centered intelligence domain of \`my-pa\`. It converts source-bound identities, interactions, meetings, commitments, projects, notes, and separately approved public information into an evidence-backed, time-aware understanding of the people and organizations relevant to the user.

The feature exists to answer five practical questions:

1\. \*\*Who is this person in the present context?\*\*  
2\. \*\*What matters about the relationship now?\*\*  
3\. \*\*What have we promised each other, and what remains unresolved?\*\*  
4\. \*\*How did the current relationship state develop?\*\*  
5\. \*\*What evidence supports the system's understanding, and where is that understanding incomplete or uncertain?\*\*

Relationship Intelligence is not a standalone engine, separate application, second database, hidden model memory, or conventional CRM. It is an integrated domain within the \`my-pa\` Evidence Operating System. It shares the product's canonical identity, provenance, policy, audit, knowledge, source, review, and authority models.

The defining product statement is:

\> \*\*Relationship Intelligence in \`my-pa\` creates a continuously evolving, evidence-backed understanding of the people and organizations that matter to the user, enabling trusted recall, meeting preparation, longitudinal context, commitment follow-through, and timely human-centered action without reducing people to scores or granting models authority to act.\*\*

The public product label should be \*\*Relationships\*\* or \*\*Relationship Intelligence\*\*. The term \*\*PRIE\*\* is retained only as a historical alias for source traceability.

\#\# 2\. Status, authority, and exact implementation context

\#\#\# 2.1 Specification status

This document is a proposed product and feature specification. It defines intended behavior, product boundaries, information architecture, conceptual contracts, acceptance criteria, and sequencing. It does not authorize implementation, repository mutation, connector access, source ingestion, public research, cloud disclosure, deployment, production activation, external action, or risk acceptance.

\#\#\# 2.2 Repository identity at publication preflight

\- Repository: \`RMF112018/my-pa\`  
\- Branch: \`main\`  
\- Authenticated head: \`40391b784ba7df2aa37f99fed86b0d4ac4723034\`  
\- Exact tree identity: unavailable from the authenticated connector  
\- Current implemented foundation includes:  
  \- public contract and disclosure shapes;  
  \- domain identity, policy, audit, provenance, and configuration primitives;  
  \- canonical PostgreSQL and migrated corpus;  
  \- source registry;  
  \- bounded source enrollment;  
  \- application job, lease, and retry records;  
  \- opaque source and object identity;  
  \- read-only fixture/source provider with containment defenses.  
\- Current unavailable or incomplete product capabilities include:  
  \- extraction and quarantine;  
  \- coverage and freshness processing;  
  \- indexed full-text retrieval over enrolled content;  
  \- HTTP and MCP transports;  
  \- runnable product worker behavior;  
  \- personal-data application services;  
  \- relationship services;  
  \- GoodNotes ingestion;  
  \- frontend implementation.

\#\#\# 2.3 Current scope gates

Relationship Intelligence is not part of the currently authorized read-only MCV vertical slice. It remains deferred under repository policy until the operator explicitly reprioritizes the objective. Frontend implementation is additionally held by operator instruction recorded in the repository completion plan as D-09. Publishing this specification does not lift either gate.

\#\#\# 2.4 Invalidation rule

This specification must be reassessed before implementation if any of the following changes materially:

\- the product mental model;  
\- repository architecture or authority boundaries;  
\- the canonical database identity or data-authority model;  
\- the public capability contract family;  
\- privacy or cloud-disclosure posture;  
\- source-system mutation policy;  
\- relationship-feature scope;  
\- exact implementation base commit;  
\- frontend implementation hold;  
\- current MCV objective.

\#\# 3\. Product problem

Relationship context is distributed across contacts, email, calendar events, handwritten and typed notes, project records, meeting records, documents, financial and schedule systems, informal conversations, and individual memory. Conventional tools preserve objects but not a coherent, defensible understanding of the relationship among those objects.

The resulting failures are operational rather than merely organizational:

\- The user enters a meeting without recent context, open commitments, or unresolved questions.  
\- Commitments made by or to another person remain buried in messages, notes, or memory.  
\- Contact records diverge from current roles, organizations, aliases, and project relationships.  
\- Duplicate identities split the history of one person, while false merges contaminate unrelated histories.  
\- Private notes, source facts, public claims, and model inferences become blended into one undifferentiated summary.  
\- A relationship's development cannot be reconstructed across years or across source systems.  
\- Important follow-ups are missed because no durable social obligation was created.  
\- Public information is either absent or collected without a sufficiently narrow purpose and privacy boundary.  
\- A polished model response can appear complete despite stale data, partial source coverage, identity ambiguity, or contradictory evidence.  
\- The user must manually re-enter a call or informal conversation into multiple structured fields or loses the interaction entirely.

Relationship Intelligence addresses these failures by making people, organizations, interactions, commitments, relationship context, and evidence first-class product objects.

\#\# 4\. Product purpose and outcomes

The feature should reduce the cognitive load of maintaining complex personal and professional relationships while preserving user agency and human judgment.

The intended outcomes are:

\- faster, better-informed meeting preparation;  
\- durable recall of prior interactions and context;  
\- fewer forgotten commitments and follow-ups;  
\- defensible person and organization profiles;  
\- visible identity ambiguity and contradiction;  
\- reliable reconstruction of relationship history;  
\- controlled capture of informal conversations and observations;  
\- improved continuity across projects and organizational changes;  
\- context that remains portable across local and approved cloud models;  
\- relationship guidance that remains explainable and non-autonomous.

The system helps the user understand, maintain, and act thoughtfully within relationships. It does not automate the relationship itself.

\#\# 5\. Target users and operating context

\#\#\# 5.1 Primary user

The initial user is a construction project executive and product owner operating across multiple projects, clients, owners, consultants, contractors, vendors, internal teams, professional contacts, and personal initiatives.

The user receives relationship-relevant information through:

\- email;  
\- calendar events and meeting invitations;  
\- contacts;  
\- project-management and construction systems;  
\- financial and schedule records;  
\- handwritten GoodNotes pages;  
\- typed notes;  
\- phone calls and informal conversations;  
\- documents and correspondence;  
\- direct observations;  
\- approved public information.

\#\#\# 5.2 Secondary future roles

Potential future roles include:

\- trusted relationship steward;  
\- executive assistant;  
\- project reviewer;  
\- knowledge steward;  
\- system operator.

These are future extensibility roles. This specification does not authorize multi-user access, delegation, or sharing.

\#\#\# 5.3 Core jobs to be done

The feature must enable the user to:

\- understand who a person is in the context of the current project, organization, meeting, or decision;  
\- prepare for a meeting using cited recent interactions, relevant projects, open commitments, unresolved questions, and source freshness;  
\- record a call, conversation, or quick relationship note without completing a complex form;  
\- identify what the user owes another person and what another person owes the user;  
\- determine whether a profile statement is source fact, private note, public claim, or model inference;  
\- reconstruct a relationship timeline and understand how the current state developed;  
\- resolve duplicate or ambiguous identities without losing source history;  
\- see relationship-relevant changes without receiving a feed of every event;  
\- find people through projects, organizations, topics, commitments, meetings, and evidence;  
\- create or correct durable relationship knowledge through explicit review;  
\- understand whether data is stale, incomplete, unavailable, or contradictory;  
\- generate a bounded briefing or synthesis over a visible evidence set;  
\- prepare a follow-up or draft without allowing the system to send it autonomously.

\#\# 6\. Product principles and non-negotiable invariants

\#\#\# 6.1 People are durable entities, not contact rows

A contact record is a source observation. A canonical person is established only through governed identity resolution. One person may have multiple names, aliases, addresses, roles, organizations, source identities, and periods of validity.

\#\#\# 6.2 Evidence before synthesis

Every material profile statement, timeline item, commitment, recommendation, and briefing claim must retain source references, time, provenance, trust state, and limitations.

\#\#\# 6.3 Facts, notes, claims, and inferences remain distinct

The system must distinguish:

\- source observation;  
\- accepted assertion;  
\- user-authored private note;  
\- public-source assertion;  
\- model inference;  
\- unresolved claim;  
\- contradiction;  
\- stale or superseded assertion.

A fluent summary may synthesize these states but may not erase them.

\#\#\# 6.4 Relationships are not scores

The product must not assign a moral, reputational, compatibility, loyalty, trustworthiness, or composite relationship-health score to a person.

The product may show separate, transparent indicators such as interaction recency, frequency, active shared work, open commitments, next meeting, unresolved questions, stale evidence, source coverage, and user-pinned priority. Each indicator must state its calculation basis and time window.

\#\#\# 6.5 Commitments are social obligations

A commitment is not merely a task. It is a promise by one party to another, with evidence, a due condition, lifecycle state, and closure evidence.

\#\#\# 6.6 The user controls promotion and action

Models may identify, extract, compare, summarize, and propose. Deterministic services validate and commit. High-impact or ambiguous changes require review. External actions require separate exact authorization.

\#\#\# 6.7 Original sources remain authoritative

Email, calendar, contact, document, GoodNotes, Procore, financial, schedule, and other source records remain authoritative for their own bytes and provider-owned state. \`my-pa\` stores source-bound observations and product-owned knowledge without silently rewriting sources.

\#\#\# 6.8 Unknown and unavailable are valid states

Missing, stale, partial, inaccessible, contradicted, unresolved, and unsupported evidence must remain visible. Lack of indexed evidence must never be presented as evidence of absence.

\#\#\# 6.9 Privacy is field-level and purpose-bound

Relationship information is highly sensitive. Access, model routing, export, research, and retention must be determined by record and field classification, purpose, destination, and policy—not only by where data is stored.

\#\#\# 6.10 Incremental and reconstructable

Relationship understanding updates incrementally as new source versions and user inputs arrive. Derived summaries, indexes, context packets, and projections remain reconstructable from canonical records and source bindings.

\#\# 7\. Product boundaries and explicit non-goals

Relationship Intelligence is not:

\- a conventional CRM;  
\- a sales pipeline or lead-scoring platform;  
\- a mass-outreach or marketing-automation system;  
\- a replacement email or calendar client;  
\- an autonomous communications agent;  
\- a surveillance product;  
\- a reputation-scoring system;  
\- a people-ranking system;  
\- a background collector of unrestricted public or private information;  
\- an authority to make employment, financial, legal, or personal decisions;  
\- a source of unsupported sensitive-trait inference;  
\- a separate relationship database or graph service;  
\- a model-specific memory store;  
\- a system that requires every person to be fully researched or indexed;  
\- a mechanism for silently changing contacts, events, messages, or source records;  
\- a reason to expose personal data in logs, URLs, analytics, or model prompts.

The initial release specifically excludes:

\- autonomous message sending;  
\- automatic meeting scheduling or calendar modification;  
\- automatic contact mutation;  
\- unrestricted public-person research;  
\- continuous social-media monitoring;  
\- facial recognition or biometric matching;  
\- location or wearable tracking;  
\- protected-trait inference;  
\- composite relationship scores;  
\- automatic canonical promotion of model inferences;  
\- destructive identity merges;  
\- graph database infrastructure;  
\- multi-user sharing;  
\- native mobile applications unless later justified;  
\- production activation through this document.

\#\# 8\. Product operating model

Relationship Intelligence participates in the \`my-pa\` operating loop: \*\*Pulse → Focus → Trace → Review\*\*, supported by \*\*Reveal\*\* and \*\*Capture\*\*.

\#\#\# 8.1 Pulse — relationship attention

Pulse identifies the few relationship matters that deserve attention now. It is not an activity feed.

A relationship item may appear in Pulse only when one or more clear reasons exist:

\- an upcoming interaction requires preparation;  
\- a commitment is due, overdue, disputed, or at risk;  
\- an important follow-up is approaching;  
\- a person changed roles or organizations and the change is source-backed;  
\- a material contradiction or identity issue requires review;  
\- a dormant but explicitly important relationship meets a user-defined follow-up rule;  
\- a project or decision creates new relevance;  
\- source coverage or freshness materially affects an upcoming interaction;  
\- the user explicitly pinned the relationship or signal.

Every Pulse item must show:

\- why it appears now;  
\- affected person or organization;  
\- affected project, commitment, meeting, or decision;  
\- source freshness and coverage;  
\- trust or review state;  
\- one primary next action;  
\- controls to pin, snooze, dismiss, mute a rule, or mark the signal not useful without deleting evidence.

\#\#\# 8.2 Focus — relationship workspace and meeting preparation

Focus assembles the exact working context around a person, organization, meeting, introduction, negotiation, or other relationship mission.

A Relationship Focus must answer:

1\. Who is this person in the current context?  
2\. What matters now?  
3\. What have we promised each other?  
4\. What evidence supports the profile?

Focus supports:

\- source-backed profile summary;  
\- roles and organizations over time;  
\- active and historical projects;  
\- last and next interactions;  
\- open commitments in both directions;  
\- unresolved questions;  
\- user-authored private notes;  
\- approved preferences or concerns;  
\- recent material source changes;  
\- related documents and evidence;  
\- bounded briefing generation;  
\- context-preserving pivots to projects, meetings, commitments, decisions, and source evidence.

\#\#\# 8.3 Trace — longitudinal relationship reconstruction

Trace explains how the current relationship state developed. It is more than a chronological activity log.

Trace sequences:

\- identity and alias changes;  
\- role and organization changes;  
\- introductions;  
\- emails and meetings;  
\- calls and captured conversations;  
\- notes and observations;  
\- shared project events;  
\- commitments and fulfillment evidence;  
\- decisions involving the person;  
\- public-research assertions;  
\- contradictions and resolutions;  
\- relationship-attention transitions;  
\- user corrections and review actions.

Trace must distinguish event time, effective time, source observation time, and record creation time.

\#\#\# 8.4 Review — human authority boundary

Review handles:

\- duplicate people;  
\- candidate identity matches;  
\- merge and split proposals;  
\- contradictory profile assertions;  
\- stale or source-changed facts;  
\- extracted commitments;  
\- high-impact or sensitive relationship notes;  
\- public-research proposals;  
\- model-generated profile updates;  
\- quick-capture extraction proposals;  
\- external-action drafts when later authorized.

Review must show the proposed change, affected records, evidence, alternatives, privacy classification, downstream effects, and permitted dispositions. Identity merges, commitments, sensitive facts, and external actions are not eligible for default bulk acceptance.

\#\#\# 8.5 Reveal — person-centered retrieval

Reveal is the search and evidence exploration capability. It supports:

\- exact name and alias search;  
\- contact-method search under policy;  
\- organization, project, topic, meeting, and commitment filters;  
\- person-centered evidence results;  
\- relationship traversal;  
\- timeline construction;  
\- visible source coverage and freshness;  
\- selected-evidence synthesis;  
\- saved views that do not silently broaden indexing.

\#\#\# 8.6 Capture — low-friction relationship input

Capture is the intentional input surface for information that may never exist in a connected source, especially informal calls, hallway conversations, observations, and quick notes.

Capture must be available:

\- inside the application;  
\- from the command field;  
\- as an installable PWA shortcut;  
\- from iPhone and iPad home screens;  
\- from macOS and Windows desktop launchers where the installed PWA supports it;  
\- through a keyboard shortcut on desktop.

The initial capture flow requires only one general input field. The user may optionally select \*\*Quick Note\*\* or \*\*Call / Conversation\*\*, but no additional structured field is mandatory.

The backend may propose:

\- participants;  
\- interaction date and time;  
\- channel;  
\- summary;  
\- project and organization links;  
\- topics;  
\- commitments;  
\- follow-ups;  
\- decisions;  
\- open questions;  
\- preferences or concerns;  
\- private observations;  
\- evidence sensitivity.

The original user-authored text remains immutable evidence. Extracted data begins as proposals. Ambiguous people, commitments, sensitive facts, and high-impact records require review.

\#\# 9\. Feature inventory

\#\#\# 9.1 Person and organization directory

\- list and search people and organizations;  
\- filter by project, role, organization, interaction recency, upcoming meeting, commitments, source coverage, and review state;  
\- show duplicate and unresolved-identity warnings;  
\- support saved private views;  
\- avoid default ranking by opaque importance.

\#\#\# 9.2 Person profile

The profile header includes:

\- canonical display name;  
\- aliases and former names where appropriate;  
\- current role and organization with source and verification state;  
\- contact methods with provenance and sensitivity;  
\- last meaningful interaction;  
\- next scheduled interaction;  
\- open commitments and follow-ups;  
\- active projects;  
\- identity ambiguity or duplicate warning;  
\- profile freshness and source coverage.

Profile sections include:

1\. \*\*Overview\*\* — source-backed brief, current context, active roles, projects, commitments, concerns, preferences, and open questions.  
2\. \*\*Timeline\*\* — interactions, meetings, notes, project events, commitments, role changes, research, corrections, and review actions.  
3\. \*\*Commitments\*\* — commitments by and to the person, state, due condition, evidence, and closure evidence.  
4\. \*\*Projects\*\* — active and historical project associations.  
5\. \*\*Notes\*\* — user-authored notes with private/source-derived distinctions.  
6\. \*\*Communications\*\* — read-only source references and thread/event summaries.  
7\. \*\*Meetings\*\* — past and upcoming interactions with preparation status.  
8\. \*\*Knowledge\*\* — assertions, inferences, contradictions, confidence, freshness, and provenance.  
9\. \*\*Identity\*\* — aliases, contact methods, source identities, candidate duplicates, merge/split history.  
10\. \*\*Research\*\* — separately approved public-source assertions, sources, review state, and retention.

\#\#\# 9.3 Organization workspace

The organization workspace includes:

\- names and aliases;  
\- organizational roles and reporting relationships where evidenced;  
\- people associated with the organization;  
\- current and historical projects;  
\- interactions and meetings;  
\- commitments and decisions involving the organization;  
\- source-backed organization changes;  
\- unresolved identity and affiliation conflicts;  
\- separately approved public information.

\#\#\# 9.4 Meeting workspace

The meeting workspace supports:

\- attendees and identity resolution;  
\- organizer, time, location, recurrence, and source calendar;  
\- related project, organization, documents, and prior interactions;  
\- commitments and unresolved questions entering the meeting;  
\- cited pre-meeting briefing;  
\- quick post-meeting capture;  
\- proposed decisions, commitments, follow-ups, and notes;  
\- links to the exact source event and related evidence.

\#\#\# 9.5 Commitments and follow-ups

The feature provides separate views for:

\- commitments the user owes;  
\- commitments owed to the user;  
\- commitments involving organizations or projects;  
\- disputed or contradicted commitments;  
\- follow-ups that are desired but not yet commitments;  
\- upcoming and overdue items;  
\- fulfillment and closure evidence.

\#\#\# 9.6 Briefings

Briefing types include:

\- person briefing;  
\- organization briefing;  
\- meeting briefing;  
\- introduction briefing;  
\- negotiation or sensitive-interaction briefing;  
\- relationship history summary;  
\- commitment review.

Every briefing includes:

\- explicit purpose and evidence scope;  
\- generated time;  
\- source freshness and unavailable domains;  
\- material claims with evidence links;  
\- open commitments and questions;  
\- contradictions and uncertainty;  
\- private-note boundaries;  
\- model identity and authority class when AI is used;  
\- no source or external-system write.

\#\#\# 9.7 Relationship attention and guidance

Guidance may propose:

\- prepare for a meeting;  
\- follow up on a commitment;  
\- reconnect under a user-defined rule;  
\- review a role or organization change;  
\- resolve an identity conflict;  
\- refresh stale public research;  
\- confirm a preference or private observation;  
\- consider an introduction;  
\- review a contradiction;  
\- draft a note or message.

Each recommendation states its reason, evidence, timing, confidence or trust label, proposed outcome, privacy route, and required authority. Recommendations do not execute external actions.

\#\#\# 9.8 Quick note and call/conversation log

The capture record stores:

\- exact user-authored input;  
\- user-selected capture mode when supplied;  
\- created time and device context where permitted;  
\- optional explicit participants or project when supplied;  
\- extraction pipeline identity;  
\- proposed structured records;  
\- review state;  
\- source and derived record links;  
\- correction history.

A capture can be saved even when extraction is unavailable. The system must not block capture because a model, connector, or database enrichment step is degraded.

\#\#\# 9.9 Identity-resolution review

The identity-resolution workspace shows:

\- candidate people side by side;  
\- matching and conflicting identifiers;  
\- aliases and contact methods;  
\- source counts and freshness;  
\- shared organizations and projects;  
\- overlapping and conflicting time periods;  
\- interactions that would move after merge;  
\- commitments and notes that would be affected;  
\- retained canonical ID and aliases;  
\- reversible merge or explicit split plan;  
\- negative evidence when candidates should remain separate.

No destructive auto-merge is allowed.

\#\#\# 9.10 Private observations

Private observations support user-authored relationship context that may not be appropriate for external disclosure or broad search. They must:

\- be visually distinct from source facts;  
\- carry field-level classification;  
\- default to local-only;  
\- remain excluded from public research and cloud contexts unless separately permitted;  
\- avoid unsupported protected-trait labels;  
\- support correction, supersession, retention, and deletion policy;  
\- never silently become source-backed fact.

\#\# 10\. Core workflows

\#\#\# 10.1 Pre-meeting preparation

1\. Calendar event enters the approved source frontier.  
2\. Attendees are resolved or left as unresolved identities.  
3\. The system identifies relevant projects, recent interactions, commitments, questions, decisions, notes, and source changes.  
4\. Coverage and freshness are evaluated.  
5\. Deterministic data appears immediately.  
6\. A cited synthesis may be generated over the visible evidence set.  
7\. The user can open any claim to exact evidence.  
8\. Missing or unavailable domains remain visible.  
9\. No message, calendar, or contact record is changed.

\#\#\# 10.2 Post-meeting capture

1\. The user opens the meeting or global Capture.  
2\. The user enters one freeform summary.  
3\. The system records the original text immediately.  
4\. Extraction proposes participants, decisions, commitments, follow-ups, questions, and notes.  
5\. High-risk or ambiguous proposals enter Review.  
6\. Accepted records become canonical product knowledge with source and capture bindings.  
7\. External actions remain separate proposals.

\#\#\# 10.3 Call or informal conversation log

1\. The user launches \*\*Call / Conversation\*\* from the application or device shortcut.  
2\. One text field is presented.  
3\. The user enters a summary and saves.  
4\. The system acknowledges durable capture before enrichment.  
5\. Backend enrichment identifies candidate participants and context.  
6\. Ambiguous identity matches remain unresolved.  
7\. Commitments and sensitive facts require review.  
8\. The interaction appears in the relevant timeline only after a valid identity link is established.

\#\#\# 10.4 Person lookup and relationship Focus

1\. The user searches a name, alias, organization, project, or commitment.  
2\. Reveal displays source coverage and candidate identities.  
3\. The user opens Relationship Focus.  
4\. The profile shows deterministic current state and evidence.  
5\. AI synthesis is optional and scoped.  
6\. The user pivots to Trace, a project, meeting, or commitment without losing context.

\#\#\# 10.5 Commitment creation and closure

1\. A source or capture proposes a commitment.  
2\. The proposal identifies obligor, beneficiary, promised outcome, due condition, and evidence.  
3\. The user reviews or corrects the proposal.  
4\. Acceptance creates the commitment; it does not send a message.  
5\. State changes preserve history.  
6\. Closure requires fulfillment evidence or explicit user confirmation.  
7\. Contradictory evidence creates a review case rather than silent overwrite.

\#\#\# 10.6 Identity merge and split

1\. The system detects duplicate candidates.  
2\. A review case shows evidence and impact.  
3\. The user accepts, rejects, defers, links without merging, or requests split.  
4\. Accepted merge preserves source identities, aliases, prior canonical IDs, and audit history.  
5\. The operation is reversible through a governed correction path.  
6\. Later source evidence may reopen the identity case.

\#\#\# 10.7 Role or organization change

1\. A source reports a changed role or organization.  
2\. The system creates a time-bounded candidate assertion.  
3\. Existing assertions remain historical rather than overwritten.  
4\. Conflicts are shown.  
5\. Review policy determines whether the change can be accepted automatically or requires confirmation.  
6\. Pulse may surface the change only when relevant to an active meeting, project, commitment, or user rule.

\#\#\# 10.8 Dormant relationship follow-up

1\. The user explicitly pins a relationship or creates a follow-up rule.  
2\. The system evaluates the rule using transparent interaction and commitment indicators.  
3\. A follow-up suggestion appears with reason and evidence.  
4\. The user may snooze, dismiss, change the rule, or create a task/follow-up.  
5\. The system does not infer that inactivity is negative or that outreach is always desirable.

\#\#\# 10.9 Introduction preparation

1\. The user selects two people or an existing introduction proposal.  
2\. The system displays shared projects, organizations, topics, and relevant commitments.  
3\. Sensitive or private context is excluded unless the user explicitly includes it.  
4\. A draft introduction may be generated as a proposal.  
5\. Sending remains a separate external action requiring exact authorization.

\#\#\# 10.10 Public research request

1\. The user selects a person and a defined research purpose.  
2\. The system displays allowed source classes, budget, provider route, privacy boundary, and retention.  
3\. Research runs only when separately enabled and authorized.  
4\. Results remain public-source assertions with citations.  
5\. Identity match and contradictions are reviewed.  
6\. Public assertions do not silently overwrite private or source-system facts.  
7\. Unsupported sensitive inferences are prohibited.

\#\#\# 10.11 Contradiction review

1\. Two or more relevant assertions conflict.  
2\. The system preserves all evidence.  
3\. The review shows effective dates, source authority, freshness, and identity match.  
4\. The user may accept one for current use, retain multiple time-bounded truths, mark disputed, or defer.  
5\. No record is silently deleted.

\#\#\# 10.12 Relationship history reconstruction

1\. The user opens Trace for a person or organization and a time range.  
2\. The system combines interactions, meetings, calls, notes, projects, commitments, role changes, and review events.  
3\. Entries disclose source and trust state.  
4\. A synthesis can identify turning points, unresolved branches, and evidence gaps.  
5\. The synthesis remains read-only unless the user explicitly creates a reviewable knowledge record.

\#\# 11\. Information architecture and user experience

\#\#\# 11.1 Navigation

Relationship Intelligence is accessed through:

\- Pulse relationship items;  
\- Focus workspaces;  
\- Reveal search;  
\- Trace timelines;  
\- Review queues;  
\- Capture;  
\- contextual links from projects, meetings, commitments, notes, documents, and source records.

It does not require a permanently separate CRM-style application hierarchy. A \*\*Relationships\*\* saved surface may exist for browsing and administration, but the product remains organized around the operating loop.

\#\#\# 11.2 Desktop layout

The default Relationship Focus uses:

\- a compact context header;  
\- central profile or mission content;  
\- a right-side evidence rail;  
\- optional left context/history navigation;  
\- resizable panes;  
\- persistent query, filter, and return state;  
\- keyboard navigation.

\#\#\# 11.3 Mobile layout

Mobile prioritizes:

\- upcoming meeting briefing;  
\- person context;  
\- quick note and call/conversation capture;  
\- commitment review and closure;  
\- one-item review;  
\- bounded notifications;  
\- source evidence preview.

Complex identity merges, policy editing, bulk review, and broad research controls remain desktop-oriented.

\#\#\# 11.4 Tablet layout

Tablet supports:

\- meeting preparation;  
\- split-view profile and evidence;  
\- GoodNotes-linked relationship review;  
\- field capture;  
\- one-item or small-batch review.

\#\#\# 11.5 Visual language

The experience should be professional, calm, dense where useful, and evidence-oriented.

Required visual distinctions include:

\- source fact;  
\- user-authored private note;  
\- public assertion;  
\- model inference;  
\- unresolved claim;  
\- contradiction;  
\- stale or unavailable evidence;  
\- accepted and proposed state.

Color may support meaning but must never be the only indicator. Avoid AI sparkles, anthropomorphic assistant theater, gamified relationship meters, card walls, and unexplained scores.

\#\#\# 11.6 Evidence interaction

Evidence must be one interaction away. The evidence control shows:

\- source system and object;  
\- exact source location or region where safe;  
\- source version or fingerprint;  
\- event, effective, observed, and processed times;  
\- extraction or model identity;  
\- classification and disclosure route;  
\- confidence or trust basis;  
\- contradictions and unavailable evidence;  
\- current lifecycle state.

\#\# 12\. Conceptual domain model

\#\#\# 12.1 Person

A stable product identity representing one human being after governed resolution.

Minimum properties:

\- opaque person ID;  
\- canonical display name;  
\- lifecycle state;  
\- sensitivity;  
\- created and updated times;  
\- identity-resolution status;  
\- current profile version;  
\- supersession and correction lineage.

\#\#\# 12.2 Person identity observation

A source-bound observation that may refer to a person.

Examples:

\- contact row;  
\- email address;  
\- phone number;  
\- calendar attendee;  
\- email sender or recipient;  
\- note mention;  
\- Procore participant;  
\- public profile identifier.

The observation retains provider identity, source object, version, timestamps, and confidence. It does not become the canonical person by itself.

\#\#\# 12.3 Alias and identifier

Aliases and identifiers include names, initials, email addresses, phone numbers, source-native IDs, usernames, and former names. They are time-aware, source-bound, classified, and may be active, historical, disputed, or invalid.

\#\#\# 12.4 Organization

A stable organization identity with names, aliases, type, lifecycle, source observations, and person affiliations.

\#\#\# 12.5 Role and affiliation

A time-bounded relationship among a person, organization, project, and role. It includes effective dates, source evidence, confidence, and review state.

\#\#\# 12.6 Project association

A time-aware link among a person or organization and a project. It includes role, source, status, and effective dates.

\#\#\# 12.7 Interaction

A meaningful contact or exchange, including:

\- email thread or message;  
\- meeting;  
\- call;  
\- informal conversation;  
\- introduction;  
\- captured note;  
\- approved public appearance when relevant.

An interaction retains participants, direction, channel, event time, source, project context, topics, and derived proposals.

\#\#\# 12.8 Event

A dated occurrence that may affect relationship context. Interactions are events, but events also include role changes, project milestones, commitment changes, and research refreshes.

\#\#\# 12.9 Commitment

A promise with:

\- obligor;  
\- beneficiary or counterparty;  
\- promised outcome;  
\- due date or condition;  
\- project or context;  
\- evidence;  
\- lifecycle state;  
\- risk state;  
\- fulfillment or waiver evidence;  
\- supersession history.

\#\#\# 12.10 Follow-up

A desired future interaction or check that is not necessarily a promise. It includes person, reason, trigger or date, desired outcome, context, and state.

\#\#\# 12.11 Relationship note

A user-authored or accepted note linked to people, organizations, interactions, projects, or commitments. The record distinguishes raw user input from derived extraction.

\#\#\# 12.12 Private observation

A classified user-authored observation that may be relevant to preparation but is not source-backed fact. It must not be blended into confirmed assertions.

\#\#\# 12.13 Assertion

A source-bound or user-confirmed statement with:

\- subject;  
\- predicate or assertion type;  
\- value;  
\- effective time;  
\- source references;  
\- authority state;  
\- confidence or trust basis;  
\- classification;  
\- lifecycle;  
\- contradictions;  
\- supersession.

\#\#\# 12.14 Inference

A model- or rule-generated conclusion that remains explicitly inferential and cannot self-promote.

\#\#\# 12.15 Relationship

A typed, directional, time-aware connection among entities. Examples include:

\- works-for;  
\- worked-for;  
\- reports-to;  
\- collaborates-with;  
\- introduced-by;  
\- participates-in;  
\- advises;  
\- represents;  
\- communicated-with;  
\- met-with;  
\- committed-to;  
\- associated-with-project;  
\- shares-user-confirmed-interest-in.

Every relationship retains supporting evidence, confidence, effective dates, and review state.

\#\#\# 12.16 Briefing

A purpose-bound, regenerable synthesis over an explicit evidence set. It stores source selection, model identity, generation time, disclosure decision, citations, limitations, and whether it was saved as derived knowledge.

\#\#\# 12.17 Recommendation

A proposal for user consideration with reason, evidence, timing, confidence, desired outcome, and required authority. It cannot execute itself.

\#\#\# 12.18 Review case

A bounded authority checkpoint containing proposed changes, affected objects, evidence, risk class, alternatives, permitted dispositions, actor, and audit history.

\#\#\# 12.19 Coverage snapshot

A record of which source domains and scopes were searched, their freshness, exclusions, failures, unsupported content, and unavailable evidence for a profile, briefing, query, or timeline.

\#\#\# 12.20 Source reference

An opaque reference to authoritative evidence, its version or fingerprint, and a safe navigation locator. Provider-native IDs and physical paths remain internal where required.

\#\# 13\. Lifecycle and state models

\#\#\# 13.1 Identity-resolution state

\- \`unresolved\_mention\`  
\- \`candidate\_match\`  
\- \`provisionally\_linked\`  
\- \`confirmed\_person\`  
\- \`duplicate\_candidate\`  
\- \`merge\_proposed\`  
\- \`merged\`  
\- \`split\_proposed\`  
\- \`split\`  
\- \`disputed\`  
\- \`superseded\`

Only governed transitions may create or alter a canonical person link.

\#\#\# 13.2 Assertion state

\- \`observed\`  
\- \`derived\`  
\- \`proposed\`  
\- \`accepted\`  
\- \`confirmed\`  
\- \`disputed\`  
\- \`contradicted\`  
\- \`stale\`  
\- \`superseded\`  
\- \`rejected\`  
\- \`quarantined\`  
\- \`unavailable\`

\#\#\# 13.3 Relationship activity state

Relationship activity states support retrieval and attention only; they do not judge the person.

\- \`observed\`  
\- \`active\_context\`  
\- \`watching\`  
\- \`follow\_up\_due\`  
\- \`dormant\_by\_user\_rule\`  
\- \`reactivated\`  
\- \`archived\`

Terms such as \*\*strategic\*\* may be user-assigned or project-derived context labels, but must not be inferred as a hidden person score.

\#\#\# 13.4 Commitment state

\- \`proposed\`  
\- \`accepted\`  
\- \`open\`  
\- \`at\_risk\`  
\- \`blocked\`  
\- \`fulfilled\`  
\- \`waived\`  
\- \`disputed\`  
\- \`superseded\`  
\- \`canceled\`

\#\#\# 13.5 Follow-up state

\- \`proposed\`  
\- \`planned\`  
\- \`snoozed\`  
\- \`due\`  
\- \`completed\`  
\- \`dismissed\`  
\- \`superseded\`

\#\#\# 13.6 Recommendation state

\- \`generated\`  
\- \`presented\`  
\- \`accepted\_as\_task\`  
\- \`accepted\_as\_follow\_up\`  
\- \`dismissed\`  
\- \`snoozed\`  
\- \`expired\`  
\- \`invalidated\`

\#\#\# 13.7 Briefing state

\- \`assembling\`  
\- \`ready\_with\_complete\_disclosure\`  
\- \`ready\_partial\`  
\- \`stale\`  
\- \`unavailable\`  
\- \`superseded\`

\#\# 14\. Source integration

\#\#\# 14.1 General source rule

Source adapters are read-only by default. They expose normalized observations while preserving source identity, version, classification, retrieval limits, and authority.

The feature must not share writable ownership of source-system tables or provider records.

\#\#\# 14.2 Contacts

Contacts provide:

\- names and aliases;  
\- contact methods;  
\- organizations and roles;  
\- source revisions;  
\- candidate duplicate indicators;  
\- provider-owned identifiers.

Contact data is evidence for identity resolution, not automatic canonical truth.

\#\#\# 14.3 Email

Email provides:

\- message and thread identity;  
\- sender and recipient observations;  
\- timestamps;  
\- subject and bounded body content under policy;  
\- attachment references;  
\- interaction direction;  
\- project and topic candidates;  
\- commitment and follow-up proposals;  
\- source links.

The feature is not an email client and does not send or alter messages.

\#\#\# 14.4 Calendar

Calendar provides:

\- event identity;  
\- organizers and attendees;  
\- time range and recurrence;  
\- location and meeting links;  
\- bounded description;  
\- cancellation state;  
\- source calendar;  
\- person, project, and commitment links.

The feature does not change events without a separately authorized external-action contract.

\#\#\# 14.5 GoodNotes

GoodNotes may provide:

\- handwritten person mentions;  
\- meeting and interaction notes;  
\- commitments;  
\- preferences and concerns;  
\- decisions and questions;  
\- project context.

GoodNotes-derived relationship data follows the exact-page-version and source-region proposal workflow. Raw OCR never silently updates a profile.

\#\#\# 14.6 Quick typed capture and conversation logs

Capture is a product-owned source. The original user input is authoritative as a user-authored record. Structured extraction remains derived and reviewable.

\#\#\# 14.7 Documents and NAS

Documents may provide person, organization, role, project, decision, and commitment observations. Indexing remains bounded by approved enrollment and coverage disclosure.

\#\#\# 14.8 Procore, financial, and schedule systems

These systems may create relationship context such as project participation, responsibility, correspondence, approvals, cost or schedule commitments, and issue involvement. Relationship Intelligence must not turn project-system involvement into personal judgment or hidden scoring.

\#\#\# 14.9 Public sources

Public sources are excluded by default and require a separately enabled research capability. Public assertions retain separate provenance and classification.

\#\#\# 14.10 Future sources

Potential future sources include voice notes, call metadata, SMS, Teams, Slack, Zoom, travel, expenses, conferences, associations, and CRM exports. Each requires a bounded source contract and privacy review. This list does not authorize integration.

\#\# 15\. Identity resolution specification

\#\#\# 15.1 Resolution evidence

Candidate resolution may consider:

\- exact and normalized names;  
\- aliases and initials;  
\- email addresses and domains;  
\- phone numbers;  
\- source-native identifiers;  
\- organization and role overlap;  
\- project-team membership;  
\- calendar attendees;  
\- email participants;  
\- introduction chains;  
\- time compatibility;  
\- user confirmation;  
\- negative evidence.

\#\#\# 15.2 Resolution rules

\- Exact identifiers are strong evidence but remain source- and time-aware.  
\- Names alone are insufficient for automatic merge.  
\- Conflicting immutable identifiers prevent automatic merge.  
\- Time-incompatible roles or locations may reduce confidence but do not prove distinct identity alone.  
\- Public and private identities require explicit match evidence.  
\- Ambiguous mentions remain unresolved rather than forced into the nearest person.  
\- A user correction becomes authoritative for the reviewed linkage but retains prior evidence.

\#\#\# 15.3 Merge requirements

A merge must:

\- name the retained canonical ID;  
\- preserve all source identities and aliases;  
\- preserve prior canonical IDs as lineage;  
\- preview affected interactions, commitments, notes, and assertions;  
\- record actor, reason, evidence, and time;  
\- support a governed split or correction path;  
\- invalidate cached summaries and context packets;  
\- trigger bounded re-enrichment where appropriate.

\#\#\# 15.4 Split requirements

A split must:

\- identify which observations move;  
\- preserve shared and ambiguous evidence;  
\- avoid duplicating commitments silently;  
\- mark affected summaries stale;  
\- create audit and review records;  
\- retain the pre-split lineage.

\#\#\# 15.5 Quality metrics

Track:

\- confirmed false-merge rate;  
\- unresolved-mention rate;  
\- duplicate detection precision;  
\- merge correction rate;  
\- time to resolve a review case;  
\- downstream records affected by corrections;  
\- negative-evidence reuse.

\#\# 16\. Relationship intelligence and transparent indicators

\#\#\# 16.1 Permitted indicators

The feature may calculate separate indicators for a defined time window:

\- days since last meaningful interaction;  
\- interaction count by channel;  
\- response direction and cadence where source coverage supports it;  
\- upcoming meeting;  
\- active shared projects;  
\- open commitments by and to the person;  
\- overdue commitments;  
\- unresolved questions;  
\- recent role or organization changes;  
\- source coverage and freshness;  
\- user-pinned priority;  
\- follow-up rule state;  
\- contradiction or review burden.

\#\#\# 16.2 Prohibited indicators

Do not calculate or display:

\- overall human worth;  
\- trustworthiness score;  
\- loyalty score;  
\- reputational score;  
\- compatibility score;  
\- relationship-health score;  
\- personality diagnosis;  
\- protected-trait probability;  
\- manipulation likelihood;  
\- employability or creditworthiness.

\#\#\# 16.3 Attention ranking

Pulse ranking may consider urgency, meeting proximity, commitment impact, business risk, user priority, source change, uncertainty, and review age. Ranking must expose reason labels and must not be optimized for engagement.

\#\#\# 16.4 Longitudinal intelligence

Trace and briefings may identify evidence-backed patterns such as:

\- recurring interaction topics;  
\- periods of collaboration;  
\- role transitions;  
\- periods of inactivity under a user-defined rule;  
\- repeated unresolved commitments;  
\- introduction history;  
\- shared project progression;  
\- changes in communication channels;  
\- contradictions across time.

Patterns remain descriptive. They must not be presented as psychological diagnosis or moral judgment.

\#\# 17\. Commitments, follow-ups, and relationship obligations

\#\#\# 17.1 Commitment schema

Required fields:

\- stable ID;  
\- obligor;  
\- beneficiary or counterparty;  
\- promised outcome;  
\- source evidence;  
\- lifecycle state;  
\- created and updated times.

Optional fields:

\- due date or condition;  
\- project;  
\- organization;  
\- dependencies;  
\- risk reason;  
\- fulfillment evidence;  
\- dispute evidence;  
\- privacy classification;  
\- originating interaction.

\#\#\# 17.2 Extraction and review

Commitments extracted from email, notes, meetings, or calls begin as proposals. Initial policy requires review for commitments unless deterministic source structure and explicit operator policy later permit a narrower auto-accept class.

\#\#\# 17.3 Closure

A commitment is fulfilled only when:

\- source evidence proves fulfillment; or  
\- the user explicitly confirms fulfillment.

Completion of a related task does not automatically prove fulfillment.

\#\#\# 17.4 Follow-ups

Follow-ups remain distinct from commitments. They may be created manually, derived from a recommendation, or proposed from an interaction. A follow-up can become a task but retains its relationship purpose and person context.

\#\# 18\. Meeting intelligence

\#\#\# 18.1 Briefing assembly

Briefings combine:

\- attendee identities;  
\- current roles and organizations;  
\- recent interactions;  
\- active projects;  
\- open commitments;  
\- unresolved questions;  
\- recent material changes;  
\- relevant notes and documents;  
\- source coverage and freshness;  
\- contradictions and identity ambiguity.

\#\#\# 18.2 Briefing limits

\- The briefing is purpose-bound to the meeting.  
\- Sensitive private observations are excluded by default from cloud processing.  
\- Public research is not triggered automatically unless a separately approved rule exists.  
\- The briefing must not imply global completeness.  
\- The briefing must preserve citations and provide exact-source navigation.

\#\#\# 18.3 Post-meeting processing

Post-meeting capture may propose:

\- interaction summary;  
\- commitments;  
\- follow-ups;  
\- decisions;  
\- open questions;  
\- profile assertions;  
\- project links;  
\- private notes.

High-impact and ambiguous proposals require review.

\#\# 19\. Quick Capture specification

\#\#\# 19.1 User experience

The default capture interface contains:

\- one required text area;  
\- optional mode: Quick Note or Call / Conversation;  
\- Save;  
\- optional attachment or context controls hidden behind progressive disclosure;  
\- visible privacy classification default;  
\- offline or degraded-state behavior.

The user must not be forced to provide participant, project, date, category, or commitment fields before saving.

\#\#\# 19.2 Durability

Save must first create a durable product-owned capture record. Enrichment is asynchronous. A model outage must not lose or block the note.

\#\#\# 19.3 Extraction

The system may propose:

\- people and organizations;  
\- interaction time;  
\- call or conversation channel;  
\- project;  
\- summary;  
\- topics;  
\- commitments;  
\- follow-ups;  
\- decisions;  
\- questions;  
\- preferences or concerns;  
\- sensitivity.

\#\#\# 19.4 Review policy

\- Low-risk topic and project suggestions may be accepted under configured thresholds.  
\- Person identity, commitments, financial or schedule facts, critical dates, and sensitive observations require review in the initial posture.  
\- Unresolved participants remain mentions.  
\- Corrections create durable feedback evidence.

\#\#\# 19.5 Device access

The responsive PWA should support:

\- installable home-screen icon;  
\- direct quick-note shortcut;  
\- direct call/conversation shortcut;  
\- share-target integration where supported and safe;  
\- desktop keyboard shortcut;  
\- cached capture shell for degraded connectivity.

Offline writes require a separately approved conflict-safe contract. Until then, a disconnected shell may retain an explicitly local pending capture only if encryption, device storage, conflict handling, and recovery are approved. Otherwise the UI must disclose that capture is unavailable rather than pretending success.

\#\#\# 19.6 Performance targets

Proposed product targets:

\- capture surface interactive within 800 ms from installed shell;  
\- durable save acknowledgment within 500 ms under normal local operation;  
\- enrichment begins within 5 seconds when the worker is available;  
\- capture remains usable when enrichment is unavailable;  
\- no duplicate structured output on retry.

Targets require measurement before acceptance.

\#\# 20\. Governed public research

\#\#\# 20.1 Default posture

Public research is disabled by default and excluded from the Relationship Intelligence MVP unless the operator separately enables it.

\#\#\# 20.2 Research request

A request must specify:

\- person or organization identity;  
\- purpose;  
\- source classes;  
\- maximum depth and budget;  
\- provider and model route;  
\- retention period;  
\- classification;  
\- review requirement;  
\- invalidation or refresh rule.

\#\#\# 20.3 Permitted sources

Potential source classes include company websites, professional profiles, news, press releases, conference sites, public filings, publications, patents, association directories, podcasts, and interviews. Each class requires policy approval. Restricted or access-controlled sources are not scraped merely because a browser can display them.

\#\#\# 20.4 Research controls

\- Public availability does not imply relevance or permission to retain.  
\- Sensitive-trait inference is prohibited.  
\- Identity matching must be explicit.  
\- Sources and quotes retain citations.  
\- Contradictions remain visible.  
\- Public assertions remain distinct from private observations.  
\- Research output begins as proposed or observed public assertions.  
\- No autonomous recurring research on every contact.  
\- No public research against real people is authorized by this specification.

\#\# 21\. AI responsibilities and authority classes

\#\#\# 21.1 Appropriate AI uses

AI may assist with:

\- extraction from notes and communications;  
\- entity-match suggestions;  
\- topic and project suggestions;  
\- commitment and follow-up proposals;  
\- contradiction candidates;  
\- briefing and timeline synthesis;  
\- selected-evidence comparison;  
\- public research when separately authorized;  
\- draft preparation;  
\- review prioritization;  
\- query expansion.

\#\#\# 21.2 Deterministic responsibilities

Deterministic services control:

\- authentication and authorization;  
\- source and identity resolution state transitions;  
\- database writes and constraints;  
\- idempotency;  
\- version checks;  
\- policy and classification;  
\- audit;  
\- search filters and pagination;  
\- review lifecycle;  
\- source mutation prohibitions;  
\- external-action approval boundaries;  
\- deletion and retention enforcement.

\#\#\# 21.3 Authority classes

\- \*\*A — Read-only synthesis:\*\* transient or saved derived output with citations; no knowledge write.  
\- \*\*B — Proposed relationship write:\*\* candidate assertion, identity link, note extraction, commitment, follow-up, or profile update.  
\- \*\*C — Accepted relationship write:\*\* deterministic service validates and commits after policy and review.  
\- \*\*D — External-system action:\*\* send, schedule, update, or contact mutation; excluded unless separately authorized.  
\- \*\*E — Operator action:\*\* connector enablement, research enablement, policy change, model promotion, deployment, cleanup; operator-only.

\#\#\# 21.4 Model non-authority

A model may not:

\- create a canonical person without governed identity rules;  
\- merge identities autonomously;  
\- promote an inference to fact;  
\- hide conflicting evidence;  
\- send a message;  
\- change a calendar event;  
\- update a contact;  
\- authorize public research;  
\- widen source scope;  
\- disclose local-only content;  
\- accept risk;  
\- promote its own model version.

\#\# 22\. Data authority, provenance, and trust

\#\#\# 22.1 Authority hierarchy within the feature

\- Source bytes and provider-owned state are source-authoritative.  
\- Product-owned identity mappings, accepted assertions, commitments, notes, review cases, and audit records are canonical within \`my-pa\`.  
\- Extracted text and summaries are derived.  
\- Model proposals and recommendations are proposed or inferred.  
\- Search indexes and caches are rebuildable.  
\- Frontend state is a projection and control surface, not authority.

\#\#\# 22.2 Mandatory provenance

Every observed, derived, proposed, accepted, or projected relationship record includes as applicable:

\- opaque record identity;  
\- source, object, and version identities;  
\- source fingerprint;  
\- event, effective, observed, and processed times;  
\- adapter, extractor, rule, or model identity and version;  
\- principal and purpose;  
\- classification and policy decision;  
\- operation and audit references;  
\- confidence or trust basis;  
\- coverage and freshness;  
\- contradiction and supersession lineage;  
\- unavailable evidence;  
\- review actor and disposition.

\#\#\# 22.3 Trust vocabulary

User-facing trust labels:

\- Confirmed;  
\- Strongly Supported;  
\- Probable;  
\- Possible;  
\- Unverified;  
\- Contradicted;  
\- Unknown.

A numeric value may appear in technical detail only when calibrated and explained. Risk and confidence remain separate concepts.

\#\# 23\. Security, privacy, and sensitive-data controls

\#\#\# 23.1 Default posture

\- local-first;  
\- least privilege;  
\- fail closed;  
\- read-only source access;  
\- local-only relationship content by default;  
\- no personal content in logs;  
\- no raw private cloud disclosure without a separate decision.

\#\#\# 23.2 Sensitive categories

The following require heightened controls and may be prohibited from inference or broad processing:

\- health;  
\- finances;  
\- family and intimate relationships;  
\- legal matters;  
\- political activity;  
\- religion;  
\- sexual orientation;  
\- protected characteristics;  
\- biometric data;  
\- precise location;  
\- private communications;  
\- credentials and secrets;  
\- employment or performance judgments.

Unsupported sensitive-trait inference is prohibited.

\#\#\# 23.3 Field-level classification

Each field or record may carry:

\- classification;  
\- sensitivity;  
\- allowed processing route;  
\- cloud eligibility;  
\- export eligibility;  
\- retention rule;  
\- training eligibility;  
\- disclosure restrictions.

\#\#\# 23.4 Private-note controls

Private notes:

\- default local-only;  
\- are hidden or blurred in compact views when policy requires;  
\- require explicit reveal where appropriate;  
\- are not included in public research;  
\- are not used for model training by default;  
\- are excluded from cloud context unless separately permitted;  
\- remain distinct from source fact.

\#\#\# 23.5 Authentication and session UX

Future implementation should support:

\- clear lock and timeout;  
\- reauthentication for high-impact actions;  
\- privacy-preserving notifications;  
\- no sensitive data in URLs;  
\- no sensitive client analytics;  
\- safe copy and export controls;  
\- audit of relationship-data disclosures.

\#\#\# 23.6 Deletion and retention

The product must distinguish:

\- source deletion;  
\- derived-record deletion;  
\- de-indexing;  
\- exclusion;  
\- archive;  
\- identity correction;  
\- retention expiry;  
\- audit preservation.

This specification grants no destructive authority.

\#\# 24\. Proposed architecture

\#\#\# 24.1 Architectural placement

Relationship Intelligence is a bounded domain inside the existing Python modular monolith. It must reuse common \`my-pa\` identity, policy, provenance, audit, job, source, knowledge, and disclosure primitives.

It must not create:

\- a standalone microservice;  
\- a separate canonical database;  
\- a model-host authority store;  
\- a graph database;  
\- a second policy engine;  
\- a second audit ledger;  
\- a second public contract family without a reviewed versioning decision.

\#\#\# 24.2 Process model

\- \*\*Gateway process:\*\* browser-safe API, future MCP mapping, authentication, authorization, read models, review commands, capture, and briefing requests.  
\- \*\*Worker process:\*\* incremental enrichment, extraction, identity candidate generation, contradiction detection, briefing assembly, bounded research when enabled, re-enrichment, and indexing.  
\- \*\*Operator CLI:\*\* bounded administrative inspection, reprocessing, review support, and diagnostics; no bypass of policy.  
\- \*\*PostgreSQL:\*\* canonical structured authority, transactional state, provenance, jobs, audit, full-text search, and relational relationship traversal.

\#\#\# 24.3 Package responsibility proposal

The exact repository paths require implementation planning, but responsibilities should remain equivalent to:

\- \`domain/relationships\` — identities, people, organizations, affiliations, interactions, commitments, follow-ups, assertions, lifecycle invariants;  
\- \`application/relationships\` — profile, timeline, briefing, capture, resolution, review, and commitment use cases;  
\- \`infrastructure/persistence/relationships\` — private ORM and query implementations;  
\- \`adapters/sources/\*\` — contacts, email, calendar, GoodNotes, and approved sources;  
\- \`adapters/http/relationships\` — browser-safe transport mapping;  
\- \`adapters/mcp/relationships\` — future model-facing mapping with equivalent semantics;  
\- \`apps/worker\` — asynchronous enrichment and indexing;  
\- frontend feature module — projection and control surface only.

A directory does not create authority. Only modules required by an authorized work package should be implemented.

\#\#\# 24.4 Storage model

PostgreSQL is canonical. Relational tables and recursive queries support the initial relationship graph. \`pgvector\` or a graph database is not required for the MVP and remains benchmark-gated.

Any cache:

\- is bounded;  
\- contains only policy-eligible fields;  
\- is non-authoritative;  
\- has explicit expiry and invalidation;  
\- is rebuildable;  
\- is deleted or refreshed after identity correction, supersession, or policy change.

\#\# 25\. Proposed service and capability contracts

The current repository exposes twelve capabilities: eight source and knowledge, and — since WP-6 — four `capture.*`. Relationship Intelligence must not be forced into those contracts without a versioned decision. The following is a proposed future semantic capability family, not an accepted public API:

\#\#\# 25.1 Read capabilities

\- \`relationships.people.search\`  
\- \`relationships.people.read\`  
\- \`relationships.organizations.read\`  
\- \`relationships.timeline.read\`  
\- \`relationships.commitments.list\`  
\- \`relationships.briefings.read\`  
\- \`relationships.coverage.read\`  
\- \`relationships.evidence.read\`

\#\#\# 25.2 Command capabilities

\- \`relationships.capture.create\`  
\- \`relationships.identity.propose\_resolution\`  
\- \`relationships.identity.review\_resolution\`  
\- \`relationships.commitments.propose\`  
\- \`relationships.commitments.review\`  
\- \`relationships.followups.create\`  
\- \`relationships.notes.create\`  
\- \`relationships.research.request\`  
\- \`relationships.review.decide\`

\#\#\# 25.3 Common request requirements

\- contract version;  
\- request and correlation identity;  
\- authenticated principal;  
\- explicit purpose;  
\- person, organization, meeting, project, or source scope;  
\- requested fields;  
\- destination and model route where applicable;  
\- idempotency key for writes;  
\- expected record version for updates.

\#\#\# 25.4 Common response requirements

\- result;  
\- source references;  
\- coverage;  
\- freshness;  
\- trust;  
\- classification;  
\- partial and unavailable evidence;  
\- limitations;  
\- review or lifecycle state;  
\- permitted actions;  
\- audit or receipt reference;  
\- explicit error.

\#\#\# 25.5 Transport parity

Future browser API and MCP mappings must invoke the same application semantics, policy checks, lifecycle transitions, and disclosure rules. MCP is not a privileged bypass.

\#\# 26\. Search, retrieval, and context assembly

\#\#\# 26.1 Retrieval modes

\- exact and alias matching;  
\- lexical full-text search;  
\- structured filters;  
\- time filtering;  
\- relationship traversal;  
\- evidence-only mode;  
\- later semantic retrieval behind a benchmark gate.

\#\#\# 26.2 Ranking inputs

Ranking may consider:

\- exact identity match;  
\- source authority;  
\- current project or meeting context;  
\- recency;  
\- interaction relevance;  
\- commitment relation;  
\- trust state;  
\- accepted lifecycle state;  
\- user pinning;  
\- coverage and freshness.

Ranking must not silently infer personal worth.

\#\#\# 26.3 Context packets

A context packet includes:

\- purpose;  
\- selected person, organization, meeting, or project;  
\- included sources and records;  
\- excluded or unavailable sources;  
\- sensitivity and model-route decision;  
\- redactions;  
\- token or size budget;  
\- citations;  
\- generation identity;  
\- expiration or invalidation rule.

\#\#\# 26.4 Search honesty

Every result or synthesis must disclose:

\- indexed versus live retrieval;  
\- source domains searched;  
\- stale or unavailable connectors;  
\- scope exclusions;  
\- truncation;  
\- unresolved identity;  
\- proposal versus accepted state.

\#\# 27\. Processing, jobs, idempotency, and re-enrichment

\#\#\# 27.1 Processing stages

Potential stages include:

\- observe source version;  
\- normalize observation;  
\- detect mentions;  
\- generate identity candidates;  
\- extract interaction;  
\- extract commitment and follow-up proposals;  
\- generate relationship assertions;  
\- detect contradictions;  
\- route review;  
\- accept or reject proposals;  
\- update search;  
\- invalidate summaries;  
\- generate briefing;  
\- re-enrich affected records.

\#\#\# 27.2 Idempotency

Each stage must use stable idempotency binding to source version, record identity, pipeline version, and configuration. Retry must not duplicate interactions, assertions, commitments, review cases, or audit records.

\#\#\# 27.3 Version binding

Derived output binds to exact source versions. If the source changes during processing, results are rejected, marked stale, or retried against the new version.

\#\#\# 27.4 Re-enrichment triggers

\- corrected identity;  
\- new alias;  
\- project mapping;  
\- role or organization change;  
\- source version change;  
\- model or rule version change;  
\- accepted quick-capture correction;  
\- contradiction resolution;  
\- policy change.

Re-enrichment should reuse stable extraction where possible rather than repeating expensive processing unnecessarily.

\#\#\# 27.5 Failure behavior

\- Retryable failures remain retryable and visible.  
\- Permanent failures retain evidence and reason.  
\- Quarantined records are excluded from normal synthesis.  
\- Partial processing never appears complete.  
\- Failed enrichment does not erase the original capture or source observation.

\#\# 28\. Notifications and attention contract

Notifications are limited to actionable events:

\- upcoming meeting lacking a usable briefing;  
\- commitment due, overdue, or at risk;  
\- required identity or contradiction review;  
\- source change affecting an upcoming interaction;  
\- failed critical processing requiring user action;  
\- explicit relationship subscription or follow-up rule.

Notifications must not expose sensitive details on locked screens unless policy permits. Activity history is not a notification feed.

\#\# 29\. Accessibility and responsive requirements

Target WCAG 2.2 AA.

Required:

\- complete keyboard navigation;  
\- visible focus;  
\- semantic headings, tables, lists, and forms;  
\- no color-only states;  
\- screen-reader announcements for review and save state;  
\- touch-safe targets;  
\- 200% zoom and reflow;  
\- reduced motion;  
\- accessible evidence lists paired with visual timelines;  
\- discoverable and disableable shortcuts;  
\- accessible error recovery;  
\- density and text scaling.

The person profile, timeline, capture, commitment review, and identity-resolution flows must be usable without canvas-only or pointer-only interactions.

\#\# 30\. Performance, reliability, and degraded-state targets

Proposed targets require implementation measurement and may be revised through evidence.

\#\#\# 30.1 Read performance

\- cached Relationship Focus critical content: under 800 ms p95;  
\- cold local Relationship Focus critical content: under 1.5 seconds p95;  
\- first-page person search: under 1.5 seconds p95;  
\- evidence preview: under 1 second p95 for indexed local content;  
\- Pulse critical relationship content: under 1 second p95.

\#\#\# 30.2 Write and review performance

\- quick capture save acknowledgment: under 500 ms p95 under normal local operation;  
\- review action commit: under 1 second p95;  
\- idempotent retry after transient failure;  
\- no silent optimistic acceptance for identity, commitment, or sensitive writes.

\#\#\# 30.3 Briefing performance

\- deterministic profile state appears before model synthesis;  
\- local briefing target: under 10 seconds for bounded evidence;  
\- longer research or synthesis returns operation status rather than blocking the interface;  
\- unavailable models do not prevent deterministic profile use.

\#\#\# 30.4 Degraded states

The feature must differentiate:

\- zero results;  
\- source unavailable;  
\- source stale;  
\- partial coverage;  
\- extraction failed;  
\- model unavailable;  
\- policy denied;  
\- unresolved identity;  
\- offline;  
\- database degraded.

\#\# 31\. Observability and audit

\#\#\# 31.1 Operational metrics

\- connector freshness;  
\- processing queue depth and age;  
\- identity-review backlog;  
\- contradiction backlog;  
\- commitment-extraction acceptance and correction;  
\- quick-capture enrichment latency;  
\- briefing generation latency and failure;  
\- search latency and coverage;  
\- cache effectiveness;  
\- model route and cost where applicable.

\#\#\# 31.2 Audit events

Audit:

\- relationship knowledge writes;  
\- identity merges and splits;  
\- commitment acceptance and closure;  
\- review decisions;  
\- public research requests and disclosures;  
\- cloud-context exports;  
\- private-note reveals where policy requires;  
\- policy changes;  
\- external-action proposals and receipts;  
\- deletion and retention actions.

Logs and audit events must avoid raw personal content by default and use stable opaque identities.

\#\# 32\. Relationship Intelligence MVP

The Relationship Intelligence MVP is a future product increment after the current read-only MCV substrate and required operator reprioritization. It is not currently authorized.

\#\#\# 32.1 MVP scope

\- read-only contacts, email, and calendar observations through approved contracts;  
\- user-authored quick note and call/conversation capture;  
\- person and organization identities;  
\- explicit unresolved mentions and duplicate review;  
\- read-only person search and profiles;  
\- interaction timeline;  
\- active project and organization context;  
\- commitments in both directions;  
\- follow-ups;  
\- source-backed meeting briefing;  
\- Pulse relationship signals;  
\- private notes with local-only defaults;  
\- evidence, coverage, freshness, contradictions, and audit;  
\- responsive PWA relationship briefing and capture;  
\- optional GoodNotes relationship proposals when GoodNotes ingestion is independently available;  
\- AI read-only synthesis and proposal generation under explicit authority classes.

\#\#\# 32.2 MVP exclusions

\- public research enabled by default;  
\- autonomous communication;  
\- contact or calendar mutation;  
\- graph database;  
\- relationship scoring;  
\- native mobile applications;  
\- broad multi-user sharing;  
\- continuous social monitoring;  
\- automatic identity merge;  
\- automatic commitment acceptance;  
\- cloud processing of private notes by default.

\#\#\# 32.3 MVP success demonstration

A credible MVP demonstration should allow the user to:

1\. find one person from approved contact, email, and calendar observations;  
2\. resolve or defer one ambiguous identity;  
3\. view a cited profile and timeline;  
4\. prepare for one meeting with coverage disclosure;  
5\. record one call using a single text field;  
6\. review and accept one extracted commitment;  
7\. see that commitment in both the person profile and Pulse;  
8\. close the commitment with evidence;  
9\. inspect the complete source and audit chain;  
10\. verify that no source record was modified and no external action occurred.

\#\# 33\. Roadmap and staged formation

\#\#\# R0 — Product normalization and governance

\- publish this current \`my-pa\`-native specification;  
\- register the feature in the owning product index;  
\- mark PRIE v0.1 as historical/superseded for current product intent without deleting it;  
\- resolve naming and public terminology;  
\- define operator decisions and implementation gate;  
\- conduct independent product/specification review.

\#\#\# R1 — Identity and read-only relationship profiles

Prerequisites:

\- current MCV substrate completed;  
\- relationship scope explicitly reprioritized;  
\- personal-source contracts approved;  
\- privacy and classification decisions approved.

Capabilities:

\- contacts, email, and calendar read models;  
\- person and organization identity;  
\- unresolved mentions;  
\- duplicate review;  
\- source-backed profile and timeline;  
\- coverage and evidence.

\#\#\# R2 — Commitments, meetings, and Capture

\- commitments and follow-ups;  
\- pre-meeting briefing;  
\- post-meeting capture;  
\- one-field quick note and call/conversation log;  
\- responsive mobile capture;  
\- review and correction loop;  
\- optional GoodNotes relationship proposals.

\#\#\# R3 — Governed synthesis and attention

\- Pulse relationship signals;  
\- cited profile and meeting synthesis;  
\- contradiction detection;  
\- stale-profile detection;  
\- user-defined follow-up rules;  
\- draft generation as proposals;  
\- context packets for approved models.

\#\#\# R4 — Governed public enrichment

\- explicit research requests;  
\- source-class controls;  
\- public/private provenance separation;  
\- identity validation;  
\- research review, retention, and refresh;  
\- no unrestricted recurring research.

\#\#\# R5 — Guarded external assistance

Potential later scope:

\- draft messages;  
\- proposed meeting changes;  
\- proposed contact corrections;  
\- introduction drafts;  
\- exact-target external-action receipts.

Every external action remains separately authorized and audited.

\#\# 34\. Acceptance criteria

\#\#\# Product and terminology

\- \`RI-AC-001\`: Public product language uses Relationships or Relationship Intelligence; PRIE is historical only.  
\- \`RI-AC-002\`: The feature is integrated into \`my-pa\`, not represented as a standalone engine.  
\- \`RI-AC-003\`: The product clearly states that relationships are not scores.  
\- \`RI-AC-004\`: The feature provides value without requiring the user to start a chat.

\#\#\# Identity

\- \`RI-AC-005\`: Contact and source rows remain observations rather than automatic canonical people.  
\- \`RI-AC-006\`: Unresolved mentions are first-class and searchable where permitted.  
\- \`RI-AC-007\`: No identity merge occurs without satisfying governed policy.  
\- \`RI-AC-008\`: Merge preview shows all materially affected records.  
\- \`RI-AC-009\`: Merge and split history is preserved and correctable.  
\- \`RI-AC-010\`: Negative identity evidence can prevent repeated false matches.

\#\#\# Evidence and trust

\- \`RI-AC-011\`: Every material profile statement links to evidence or is clearly marked user-authored or inferred.  
\- \`RI-AC-012\`: Source facts, private notes, public assertions, inferences, unresolved claims, and contradictions are visually and structurally distinct.  
\- \`RI-AC-013\`: Coverage, freshness, exclusions, and unavailable sources appear before synthesis.  
\- \`RI-AC-014\`: Stale evidence is never presented as current.  
\- \`RI-AC-015\`: Contradictory evidence is preserved rather than silently collapsed.  
\- \`RI-AC-016\`: Every generated briefing retains its evidence scope and model identity.

\#\#\# Profiles and timelines

\- \`RI-AC-017\`: A person profile exposes identity, roles, organizations, projects, interactions, commitments, notes, knowledge, and evidence.  
\- \`RI-AC-018\`: Timeline entries distinguish event, effective, observed, and recorded times.  
\- \`RI-AC-019\`: Profile navigation preserves context and return state.  
\- \`RI-AC-020\`: Organization profiles support time-aware people and project associations.

\#\#\# Commitments and follow-ups

\- \`RI-AC-021\`: Commitments retain obligor, beneficiary, outcome, source, and lifecycle.  
\- \`RI-AC-022\`: Commitments and tasks remain distinct.  
\- \`RI-AC-023\`: Extracted commitments require review in the initial posture.  
\- \`RI-AC-024\`: Fulfillment retains evidence or explicit user confirmation.  
\- \`RI-AC-025\`: Commitments by and to a person are separately visible.  
\- \`RI-AC-026\`: Follow-ups remain distinct from commitments.

\#\#\# Meetings and briefings

\- \`RI-AC-027\`: A meeting briefing identifies attendee ambiguity and unavailable evidence.  
\- \`RI-AC-028\`: Deterministic meeting context remains usable when AI is unavailable.  
\- \`RI-AC-029\`: Briefing claims navigate to source evidence.  
\- \`RI-AC-030\`: Post-meeting capture creates proposals without changing source events.

\#\#\# Quick Capture

\- \`RI-AC-031\`: Quick Note and Call / Conversation can be launched inside the app and from supported installed-device shortcuts.  
\- \`RI-AC-032\`: Only one general input field is required before save.  
\- \`RI-AC-033\`: Original user input is durably stored before enrichment.  
\- \`RI-AC-034\`: Enrichment failure does not lose or block the capture.  
\- \`RI-AC-035\`: Participants, commitments, sensitive facts, and critical dates follow review policy.  
\- \`RI-AC-036\`: Repeated processing does not duplicate structured records.  
\- \`RI-AC-037\`: Capture corrections retain immutable before/after evidence.

\#\#\# AI and action authority

\- \`RI-AC-038\`: AI output carries an authority class.  
\- \`RI-AC-039\`: Models cannot merge identities or promote inferences autonomously.  
\- \`RI-AC-040\`: No external action occurs through a relationship knowledge write.  
\- \`RI-AC-041\`: Browser and MCP surfaces enforce equivalent policy and lifecycle semantics.  
\- \`RI-AC-042\`: Cloud disclosure is purpose-, field-, and destination-bound.

\#\#\# Privacy and safety

\- \`RI-AC-043\`: Private notes default local-only.  
\- \`RI-AC-044\`: Unsupported sensitive-trait inference is prohibited and tested.  
\- \`RI-AC-045\`: Sensitive content is absent from logs, URLs, and ordinary analytics.  
\- \`RI-AC-046\`: Public research remains disabled until separately authorized.  
\- \`RI-AC-047\`: Public-source assertions remain distinct from private and source-system records.  
\- \`RI-AC-048\`: Deletion, de-indexing, exclusion, archive, and source deletion are distinct operations.

\#\#\# Relationship indicators and attention

\- \`RI-AC-049\`: No composite relationship-health, loyalty, reputation, or trust score is displayed.  
\- \`RI-AC-050\`: Every relationship attention signal states why it appears.  
\- \`RI-AC-051\`: Indicator calculations disclose time window and source basis.  
\- \`RI-AC-052\`: User dismissal or snooze does not delete underlying evidence.  
\- \`RI-AC-053\`: Zero results and unavailable evidence remain distinct.

\#\#\# Architecture and reliability

\- \`RI-AC-054\`: PostgreSQL is the only canonical structured relationship store.  
\- \`RI-AC-055\`: Source adapters expose no mutation operations by default.  
\- \`RI-AC-056\`: Relationship domain code preserves repository dependency direction.  
\- \`RI-AC-057\`: Derived records bind to exact source and processing versions.  
\- \`RI-AC-058\`: Retry and replay are idempotent.  
\- \`RI-AC-059\`: Identity correction invalidates affected summaries and indexes.  
\- \`RI-AC-060\`: Partial or failed processing cannot look complete.

\#\#\# UX, accessibility, and performance

\- \`RI-AC-061\`: Desktop profile and review workflows are keyboard operable.  
\- \`RI-AC-062\`: Mobile supports briefing, capture, commitment follow-through, and lightweight review.  
\- \`RI-AC-063\`: Status is never color-only.  
\- \`RI-AC-064\`: Core surfaces meet WCAG 2.2 AA acceptance testing.  
\- \`RI-AC-065\`: Performance budgets are measured rather than asserted.  
\- \`RI-AC-066\`: Degraded states preserve available deterministic content.

\#\#\# Governance

\- \`RI-AC-067\`: Implementation cannot begin without explicit operator reprioritization of relationship scope.  
\- \`RI-AC-068\`: Frontend implementation cannot begin until the separate D-09 hold is lifted.  
\- \`RI-AC-069\`: Implementation planning reauthenticates current repository head, tree, worktree, and runtime identity.  
\- \`RI-AC-070\`: Independent exact-head review is required before merge of any implementation work.

\#\# 35\. Success metrics

\#\#\# 35.1 Utility

\- meeting preparation time saved;  
\- time to source evidence;  
\- commitment recall and fulfillment;  
\- follow-up completion;  
\- person-profile usefulness;  
\- quick-capture frequency and completion time;  
\- relationship Focus open-to-action rate;  
\- cited timeline reconstruction success;  
\- reduction in missed context.

\#\#\# 35.2 Trust and quality

\- attribution completeness;  
\- unsupported-claim rate;  
\- false identity merge rate;  
\- identity correction rate;  
\- contradiction detection precision;  
\- stale-profile detection;  
\- commitment extraction precision and correction;  
\- exact-source navigation rate;  
\- coverage disclosure accuracy;  
\- unauthorized actions blocked.

\#\#\# 35.3 Privacy and safety

\- local-only disclosure violations;  
\- sensitive-data leakage in logs or analytics;  
\- unauthorized public-research attempts blocked;  
\- protected-trait inference violations;  
\- deletion and retention compliance;  
\- external-action attempts requiring approval.

\#\#\# 35.4 System performance

\- profile latency;  
\- person search latency;  
\- quick-capture durability latency;  
\- enrichment latency;  
\- briefing latency;  
\- job retry and recovery;  
\- source freshness;  
\- index freshness;  
\- cache invalidation correctness.

Metrics are evidence for improvement, not gamification of relationships or the user.

\#\# 36\. Risks and mitigations

\#\#\# \`RI-RISK-001\` — False identity merge

\*\*Impact:\*\* contaminates profile, timeline, commitments, and briefings.    
\*\*Mitigation:\*\* unresolved mentions, conservative rules, review, merge preview, reversible lineage, negative evidence, precision-first metrics.

\#\#\# \`RI-RISK-002\` — Polished synthesis creates false trust

\*\*Impact:\*\* user relies on incomplete or incorrect relationship context.    
\*\*Mitigation:\*\* evidence links, coverage, freshness, contradiction state, deterministic profile before synthesis, authority labels.

\#\#\# \`RI-RISK-003\` — Surveillance-like product behavior

\*\*Impact:\*\* intrusive collection and harmful user behavior.    
\*\*Mitigation:\*\* purpose limitation, no scoring, no unrestricted research, user-defined follow-up rules, bounded notifications, sensitive-trait prohibition.

\#\#\# \`RI-RISK-004\` — Private note disclosure

\*\*Impact:\*\* highly sensitive context reaches an unintended model, export, or screen.    
\*\*Mitigation:\*\* field-level classification, local-only default, explicit reveal, cloud denial, safe notification and logging.

\#\#\# \`RI-RISK-005\` — Recommendation overreach

\*\*Impact:\*\* system pressures user into contact or treats inactivity as negative.    
\*\*Mitigation:\*\* reason labels, user-defined rules, no engagement optimization, snooze/dismiss controls, no autonomous outreach.

\#\#\# \`RI-RISK-006\` — Commitment false positive

\*\*Impact:\*\* creates obligations that were never made.    
\*\*Mitigation:\*\* proposal-first extraction, mandatory review, exact evidence, correction and dispute states.

\#\#\# \`RI-RISK-007\` — Source incompleteness

\*\*Impact:\*\* profile appears comprehensive despite missing email, calendar, notes, or other sources.    
\*\*Mitigation:\*\* coverage snapshots, unavailable-state UX, no complete-looking zero, synthesis warnings.

\#\#\# \`RI-RISK-008\` — Public/private identity mismatch

\*\*Impact:\*\* public research attaches to the wrong person.    
\*\*Mitigation:\*\* explicit identity seed, separate research review, strong identifiers, contradiction handling, no automatic promotion.

\#\#\# \`RI-RISK-009\` — Frontend outruns backend

\*\*Impact:\*\* polished screens invent unsupported behavior.    
\*\*Mitigation:\*\* capability discovery, typed contracts, honest unavailable states, D-09 hold, backend-first implementation sequence.

\#\#\# \`RI-RISK-010\` — Review backlog

\*\*Impact:\*\* proposals remain stale or overwhelm user.    
\*\*Mitigation:\*\* risk-aware prioritization, conservative auto-accept only for low-risk deterministic metadata, keyboard/mobile review, threshold tuning, no critical bulk acceptance.

\#\#\# \`RI-RISK-011\` — Quick-capture data loss

\*\*Impact:\*\* informal relationship context is lost.    
\*\*Mitigation:\*\* durable record before enrichment, idempotency, explicit offline posture, recovery tests.

\#\#\# \`RI-RISK-012\` — Premature architecture complexity

\*\*Impact:\*\* separate services, graph stores, and caches duplicate authority.    
\*\*Mitigation:\*\* modular monolith, PostgreSQL, no graph DB, benchmark gates, current-use-only abstractions.

\#\#\# \`RI-RISK-013\` — Legacy schema misuse

\*\*Impact:\*\* migrated tables become an accidental public or writable contract.    
\*\*Mitigation:\*\* read-oriented service boundaries, current product schemas, no direct frontend or model database access, explicit migration/disposition review.

\#\#\# \`RI-RISK-014\` — Cloud-model privacy failure

\*\*Impact:\*\* private relationship context is disclosed externally.    
\*\*Mitigation:\*\* default local-only, policy preflight, exact context manifest, redaction, audit, provider approval, local alternative.

\#\# 37\. Open decisions requiring operator resolution

\- \`RI-OD-001\`: Final public feature name: Relationships or Relationship Intelligence.  
\- \`RI-OD-002\`: When Relationship Intelligence should be promoted into implementation scope relative to the current MCV.  
\- \`RI-OD-003\`: Whether and when to lift the D-09 frontend implementation hold.  
\- \`RI-OD-004\`: First personal source set: contacts, email, calendar, manual capture, and/or GoodNotes.  
\- \`RI-OD-005\`: Authentication posture for relationship data.  
\- \`RI-OD-006\`: Default private-note classification and reveal behavior.  
\- \`RI-OD-007\`: Cloud model eligibility for relationship briefings.  
\- \`RI-OD-008\`: Whether public research is excluded from the first release or available only by explicit one-time request.  
\- \`RI-OD-009\`: Retention and deletion defaults for quick captures and private notes.  
\- \`RI-OD-010\`: Offline capture posture.  
\- \`RI-OD-011\`: Which low-risk extracted metadata may auto-accept.  
\- \`RI-OD-012\`: Which commitment classes always require review.  
\- \`RI-OD-013\`: Whether user-assigned importance labels are supported and how they are named.  
\- \`RI-OD-014\`: Initial browser and installed-PWA device matrix.  
\- \`RI-OD-015\`: Voice capture timing and privacy posture.  
\- \`RI-OD-016\`: External-action scope, if any, after the read-only and proposal stages.  
\- \`RI-OD-017\`: Independent usability and privacy review gate before release.

No default in this document resolves an operator-only decision.

\#\# 38\. Implementation entry gate and sequencing constraints

Implementation may begin only after all of the following are true:

1\. The operator explicitly reprioritizes Relationship Intelligence under current repository governance.  
2\. The exact current repository head, tree, branch, worktree, runtime, and database identity are authenticated.  
3\. The current MCV completion state and dependencies are reassessed.  
4\. The D-09 frontend hold remains respected or is explicitly lifted for a bounded scope.  
5\. Personal-source access is separately authorized by exact connector/account/scope.  
6\. Privacy, cloud, research, retention, and authentication decisions needed by the first work package are resolved.  
7\. A bounded implementation plan maps requirements to work packages, tests, and evidence.  
8\. A separate implementation authorization names exact paths, actions, acceptance criteria, and prohibitions.  
9\. Implementation and independent exact-head review use separate contexts.  
10\. No implementation agent self-approves, self-merges, accepts risk, or activates production.

The recommended implementation order is:

1\. specification and contract freeze;  
2\. identity observations and canonical person model;  
3\. read-only contacts/email/calendar integration;  
4\. person profile and timeline read models;  
5\. identity-resolution review;  
6\. commitments and follow-ups;  
7\. quick capture and call/conversation log;  
8\. meeting briefings;  
9\. Pulse attention signals;  
10\. responsive frontend after its hold is lifted;  
11\. governed public research;  
12\. guarded external-action proposals.

\#\# 39\. Source manifest and evidence basis

\#\#\# Primary product sources

1\. Historical PRIE product description    
   Drive ID: \`1LukPPAU9-9BPINjXJNXYnuJhTZYDe\_MSJficqxYxEg4\`    
   Exported text SHA-256: \`7d6a8f534157e7ffa66c179d3d784d89ff6df4782d92c3c6e544e44b0551a478\`    
   Use: historical product intent; obsolete repository and architecture identity.

2\. PRIE formation evaluation and integration recommendation    
   Drive ID: \`1al6qCKMVGMbOHHLVZg-vGHwEnZyE-maRK3XKIWsokFM\`    
   Exported text SHA-256: \`92295777b68c72aa1951eff451aebf950dfa6b8868e50e7dccc8df056d2bc487\`    
   Use: current integration recommendation and gap analysis.

3\. Evidence Operating System product vision    
   Drive ID: \`14W9Csoq6vBOVqE6Vflx\_w7NIwNCblC7Cpc9WCFS64IY\`    
   Exported text SHA-256: \`b64eaae757135190dbc74e1199a57fc44a0746afc41b41e05aa2e5bcef6bdc9b\`    
   Use: Pulse, Focus, Trace, Review product shell and relationship principles.

4\. Comprehensive frontend product and UX specification    
   Drive ID: \`17mrP2WHNCMLpCgUbE-x9NJ4dD1CCe07eZUuKd6iCQMs\`    
   Exported text SHA-256: \`cdce6a15ed543dcb2f97f28ac3e9681d6457d03d6662deb7ad17d655bba8bf48\`    
   Use: detailed person profile, timelines, commitments, review, privacy, responsive, and evidence UX.

5\. GoodNotes knowledge-ingestion specification    
   Drive ID: \`111zA3Osva\_tdi7oW-8TIBcC0uS9\_cQ6VZ-w3pqmGhCA\`    
   Use: assertion-first source-region proposal and review model.

6\. Current MY-PA owning index    
   Drive ID: \`1i9r6pDI8jZQnD526\_o\_aFl8WWUliWX0h1ANLh\_gtelE\`    
   Use: current publication routing and product artifact status.

\#\#\# Repository sources

\- \`AGENTS.md\`  
\- \`AI\_OPERATING\_MANUAL.md\`  
\- \`CLAUDE.md\`  
\- \`.ai/project-sources/00\_AEOS\_MASTER\_INDEX.md\`  
\- \`docs/00\_REPOSITORY\_SOURCE\_INDEX.md\`  
\- \`README.md\`  
\- \`docs/specs/mcv-read-only-vertical-slice.md\`  
\- \`docs/plans/mcv-completion-plan.md\`  
\- \`docs/architecture/module-boundaries.md\`  
\- \`docs/architecture/data-authority.md\`  
\- Commit \`40391b784ba7df2aa37f99fed86b0d4ac4723034\`

\#\#\# Operator requirements incorporated

\- Quick typed note capture must require only one general field.  
\- Call and conversation logging must use the same low-friction capture model.  
\- Capture must be launchable from the application and supported iPhone, iPad, macOS, and Windows installed surfaces.  
\- Backend extraction should identify structured relationship data and route uncertain or high-risk results for review.

\#\#\# Unavailable or unverified evidence

\- Exact repository tree SHA and operator-local worktree state.  
\- Independent usability study.  
\- Live relationship-service behavior.  
\- Full semantic quality audit of every migrated personal-data table.  
\- Final selected frontend direction as an operator-approved implementation authority.  
\- Final authentication, cloud, public-research, retention, and offline-capture decisions.

\#\# 40\. Supersession and preservation

This specification supersedes \`FEAT-HBPA-PRIE-001 v0.1\` only as the current product-intent description for Relationship Intelligence in \`my-pa\`. The historical document remains preserved as evidence of concept formation and must not be deleted or silently rewritten.

Concepts intentionally removed or constrained from the historical formation include:

\- standalone-engine architecture;  
\- separate authoritative NAS relationship database;  
\- ambiguous model-host hot-store authority;  
\- composite relationship-strength or strategic-value scoring;  
\- unrestricted or automatically recurring public research;  
\- identity resolution as a background implementation detail;  
\- blended facts, private notes, and model inferences;  
\- autonomous recommendation execution.

Concepts intentionally retained and strengthened include:

\- people-centered longitudinal intelligence;  
\- evidence-backed profiles;  
\- identity and alias resolution;  
\- interaction timelines;  
\- commitments and follow-through;  
\- pre-meeting briefing;  
\- private observations with strict controls;  
\- governed public research;  
\- model-independent durable knowledge;  
\- source preservation;  
\- human decision authority.

\#\# 41\. Final disposition

\*\*Recommended disposition:\*\* \`RELATIONSHIP\_INTELLIGENCE\_SPECIFICATION\_READY\_FOR\_OPERATOR\_AND\_INDEPENDENT\_PRODUCT\_REVIEW\`

\*\*Implementation status:\*\* \`NOT\_AUTHORIZED\`

\*\*Repository mutation:\*\* \`NOT\_PERFORMED\`

\*\*Independent validation:\*\* \`NOT\_PERFORMED\`

\*\*Current implementation gate:\*\* Relationship Intelligence remains deferred under repository policy, and frontend implementation remains separately held by D-09.

\*\*Exact operator-only next action:\*\* review this specification, resolve or prioritize the first-stage open decisions, and—only when intended—issue a bounded reprioritization and planning authorization for R0/R1. No implementation begins through publication alone.  
