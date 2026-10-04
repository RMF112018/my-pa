# Record Event causal provenance v0.1

- **Status:** **Proposed / not implemented.** A design record only. Nothing here
  exists in the code, and implementing any of it requires the future
  writeback-plane authorization. It adds no capability, no schema, no field and
  no consumer.
- **Request:** `MYPA-RECORD-EVENT-CONSUMER-READINESS-20261001-001` (RECR-4),
  under the approved RECR plan (SHA-256
  `e1a545c4a7977b29c80d719c0257ad3e5465cec039ff5d5a0d0ee3a2b0bb9d04`, Drive
  `1QfApsSyALgwSgNjvW2ClISNsGyIDzgzu`), section (e), and Manager ruling MR-R07
  (a spec here rather than an ADR, since nothing is decided or implemented).
- **Repository basis:** `RMF112018/my-pa`, branched from `origin/main`
  `174876621c880312ee3f4e32f649520fab04aa9d`.
- **Companion:** [`record-event-consumer-contract-v0.1.md`](record-event-consumer-contract-v0.1.md),
  which is implemented and governs how a consumer reads the feed today.
- **Reconciled 2026-10-04** with the Knowledge Assertion layer
  ([ADR-014](../decisions/ADR-014-knowledge-assertion-layer.md); R5 CORR-006 as
  amended by R6 section 9) in section 10. The reconciliation is still a design
  record: nothing in section 10 is implemented yet either.

## 1. Authority, scope and non-goals

The question: when an external consumer of the feed reacts to an event by
proposing a change, and that change is reviewed and approved into a MY-PA
record, how does the resulting record -- and the event it produces -- carry
enough provenance for the consumer to tell **its own effect** from **a new
trigger**? Without that, a consumer that reacts to every event can loop on its
own writes.

Non-goals: no writeback plane, no external (Abacus) consumer, no intake
capability, no schema, no change to the feed's metadata-only rule. This record
fixes vocabulary and constraints so the future authorization starts from them.

## 2. Repository truth today

What exists, with where it lives:

- **`correlation_id`** -- each event stores the correlation id of the request
  that wrote it (`RecordEventDraft` in `src/my_pa/domain/record_events.py`). It
  is **not public**: `RecordEventItemView` in
  `src/my_pa/contracts/v1/record_events.py` omits it, because it belongs to the
  writing request, not to the caller.
- **`causation_event_id`** -- public, and names an earlier event of the same
  Principal, staged in the same batch (a derived event names its primary). A
  remote caller sees it only when the cause is itself visible to that caller;
  otherwise it is nulled (OD-12; `_visible_causes` in
  `src/my_pa/application/record_events.py`). Its meaning today is
  **within one transaction**.
- **`actor_class` and `source_capability`** -- a write that a review promotion
  performed carries `actor_class = review_promotion` and `source_capability =
  review.decide`, whichever canonical writer ran (OD-6;
  `REVIEW_PROMOTION_CAPABILITY`, `entity_source_capability` and
  `memory_source_capability` in `src/my_pa/domain/record_events.py`).
- **`source_receipt_id`** -- names the ledger row of the write (an opaque
  receipt id).
- **Review cases and proposals emit no event** (OD-3; the absent families listed
  above `IDENTITY_EFFECT_RECORD_FAMILIES` in `src/my_pa/domain/record_events.py`).
  A review case has its own identifier kind, `IdKind.REVIEW_CASE` (`rvw_`).

So today an event can say "a review promotion caused this", but not which
review case, which proposal, which external run, or which earlier event
triggered it.

## 3. The chain and its identifiers

```
trigger event (rcev_…)
  → external run          (opaque external id, the consumer's)
  → external proposal     (opaque external id, the consumer's)
  → MY-PA review case     (rvw_…)
  → approved canonical write   (ledger receipt, source_receipt_id)
  → resulting event(s)    (rcev_…, actor_class = review_promotion)
```

Each identifier is minted by the party that owns its step. MY-PA never invents
an external id, and the consumer never invents a MY-PA one.

## 4. Where each identifier lives

The proposal intake (a future capability) records one **bounded provenance
tuple** on the MY-PA proposal or review-case record -- **not on the event**:

- `trigger_event_ids` -- one or more `rcev_` ids of the same Principal; each must
  exist and be visible to the proposing client at intake, under the same grant
  intersection and withholding as `record_events.list`;
- `external_run_id` and `external_proposal_id` -- opaque, bounded, validated as
  identifiers, never free text;
- `correlation_id` -- the intake request's own.

Events stay metadata only (RE-I-007). The tuple carries identifiers, never a
value, a name or narrative.

## 5. How the resulting event points back

Three options for the link from a resulting event to its provenance:

1. **Reuse `causation_event_id` across transactions** for the trigger. Rejected
   as the primary design: it changes today's within-batch meaning, and its
   remote nulling would hide the trigger exactly when the consumer is remote.
2. **A future public, metadata-only `review_case_id`** on promotion events.
   Simple and cheap, but it discloses only one link of the chain.
3. **A future provenance read**, keyed by `event_id` or `source_receipt_id`,
   that returns the tuple of section 4 under the caller's grants.

**Recommendation:** option 3, with option 2 as the fallback. Both are future
capabilities and need their own authorization.

## 6. Self-caused versus a new trigger

For a consumer holding its own run ids:

- An event is **self-caused** iff `actor_class == review_promotion`, its
  provenance names an `external_run_id` that belongs to the consumer, and every
  `trigger_event_ids` member is an event the consumer has already processed.
- **Any other write is a new trigger** -- including a principal or system write
  to the same record that follows a promotion, and a promotion from another
  consumer's run.

A self-caused event still invalidates: the consumer rereads the record (the
consumer contract), but it does not propose again on account of it.

## 7. Loop guards

- **Idempotent intake:** the intake key is a digest of (trigger event id, rule
  id, record version), so a replayed reaction is a replay, not a second
  proposal.
- **Bounded causal depth:** the tuple carries a depth counter, and intake refuses
  past a fixed bound.
- **No self-trigger:** intake refuses a proposal whose trigger is itself
  self-caused by the same run.

## 8. Disclosure

Provenance is disclosed under the same grant intersection and remote withholding
as the feed: a provenance read never names a trigger event the caller cannot
see, and never discloses an external id to a caller other than the one that
supplied it, or the owning Principal locally. No narrative is ever part of
provenance.

## 9. Open questions for the future gate

- Which records carry the tuple: the review case only, or also the proposal?
- Is the depth bound global or per rule?
- How long is provenance retained once the review case closes?
- Does a provenance read need its own purpose, or does it ride on the feed's?
- How does a split or merge that moves a promoted record re-point its
  provenance, given that routing follows the current owner?

## 10. Reconciliation with the Knowledge Assertion layer (ADR-014)

The Knowledge Assertion layer (KLP) is the first plane to carry the chain of
section 3, with a proposing discovery client in the consumer's role. It answers
several section 9 questions for that plane. Not implemented: the schema is
KLP-WP-02, submit and Review KLP-WP-04, the provenance read KLP-WP-05.

- **`causation_event_id` is unchanged.** It keeps its same-transaction meaning
  and its remote nulling (section 2). Option 1 of section 5 stays rejected.
- **Cross-run provenance is a new metadata read** (option 3 of section 5). Every
  Knowledge Assertion Record Event names its `kamut_` mutation as
  `source_receipt_id`; the mutation names its `kasub_` submission and, for a
  Review promotion, its Review decision. Event -> mutation -> submission is the
  canonical join, and the submission holds the bounded tuple of section 4:
  trigger event ids, external run and candidate ids, correlation, causal root
  and depth. The tuple lives on the submission, not on the event, so events stay
  metadata only.
- **Disclosure (section 8, made concrete).** External run and candidate ids are
  disclosed only to the authenticated client that supplied them, or locally to
  the owning Principal. A provenance read never names a trigger event the caller
  cannot see. A caller is remote whenever `transport is REMOTE_CLIENT` or
  `capability_grants is not None`, so any grant-ceilinged composition gets the
  remote rules even over local transport.
- **Frozen Record Event mapping.** create, Review accept or correct, and a
  supersession successor -> `created`; evidence-only enrichment -> `updated`;
  classification raise, revalidation, supersession of the predecessor and
  archive -> `state_changed`, with closed changed-field tokens. Actor class:
  remote discovery `assistant`, local explicit create `principal`, Review
  promotion `review_promotion`, server maintenance `system`. Authority: the
  existing `source_backed_assertion`, `user_confirmed_assertion`,
  `review_accepted` and `system_deterministic` tokens. No new actor or authority
  token is added. The table is published as pure data in
  `src/my_pa/domain/knowledge_assertion/provenance.py`.
- **One depth ceiling: 4** (answers "global or per rule": global). No
  Knowledge-parent trigger -> a new root at depth 0; exactly one distinct root ->
  inherit it at depth 1 + max(parent depth); more than one root -> refuse
  `causal_root_ambiguous`; depth above 4 -> refuse `causal_depth_exceeded`; a
  repeated (authenticated client, subject kind, subject id, predicate) anywhere
  in the ancestor lineage -> refuse `causal_repeat`, whatever the external run.
  Non-Knowledge triggers are visible trigger evidence but start a new root.
  Review promotion inherits its proposal's origin submission, so `review.decide`
  does not reset depth. Explicit create is always a root.
- **Loop guards (section 7).** Idempotent intake is the frozen request digest
  (ADR-014 decision 6) keyed by client, source profile, run and candidate; the
  depth counter is the causal depth above; the self-trigger guard is the lineage
  repeat refusal, plus a soft per-client, per-run rate bound for submissions
  that cite no trigger.
