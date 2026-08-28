"""Which capabilities reach a relationship-memory row, and which rows, derived.

`evidence/acceptance/RELATIONSHIP-MEMORY-RM-AC-20260822.md`'s `RM-API-AC-002`
carries the criterion "each capability has a grant boundary appropriate to the
rows it reaches". A grant boundary is only appropriate to a reach someone has
measured, and that row got the reach wrong in prose three times running, at
three successive heads, each time caught by a different independent review.

The first version named the eight `relationship_memory.*` capabilities and
stopped, so `entities.context` — which puts every carried memory's `statement`
verbatim on a card served under `entity_read` — was disclosed by nothing. The
correction added `entities.context` and `review.decide` and then asserted that
"the enumeration of capabilities outside the eight is complete at two". It is
three: `review.list` reads `relationship_memory_proposals` and correlates two
subqueries over `relationship_memory_review_decisions`, so a `capture_review`
grant learns a `subject_entity_id`, a `proposed_kind` and — after promotion — an
`accepted_memory_id`, for a subject the grant never named.

**The third failure is what gave this module its present shape.** The commit
that fixed the second derived *which capabilities* reach a memory row — the walk
below — and left *which tables each one reaches* beside it as prose. That prose
was wrong in the sentence announcing the fix. It said `review.decide` "reads four
of the eight" and, "on promotion, writes three". It reads three and writes five:
the fourth read was `relationship_memory_proposals` counted twice, `_copy_evidence`'s
own read of `relationship_memory_proposal_evidence` went unnamed, and `_promote`'s
three writes were quoted as the capability's when two more are issued outside the
promotion branch.

**The fourth failure moved the unchecked claim from the digits to the
quantifier.** The commit that added the table derivation said, in the sentence
announcing it, that those two non-promotion writes fire "on *every* disposition,
a reject included", and that a grant "writes two memory-plane tables whatever it
decides". False for one branch of five: `_STORED_STATE[Disposition.MARK_UNRESOLVED]`
is `None` and the `update(relationship_memory_proposals)` is guarded by
`if stored_state is not None`, so `mark_unresolved` writes one table where a
reject writes two. The derivation could not catch it and was not asked to: a
derived table set is a union over branches — a bound, not an itinerary — and the
sentence made a per-branch claim about it. The digits were bound and the
quantifier beside them was not.

Three false enumerations of the capabilities, a fourth of their tables, a fifth
of their branches, one criterion. **So none of it is prose here.** This module
derives the capabilities, their tables *and* the per-branch split, compares each
to a declaration, *and parses `RM-API-AC-002` for its own digits* so the row
cannot restate a claim the walk contradicts. The declared sets are literals
because a declaration is the thing under review; everything they are measured
against is derived.

Ten claims, separated because they fail for different reasons:

1. **The eight tables are the schema's, not this file's.** They are read off the
   `Table` objects in `infrastructure.persistence.tables`, and the count is
   asserted, so a ninth memory table cannot join the plane without being seen.
2. **Only the declared modules name one.** Exact set equality, so a third module
   that starts building a statement over a memory table has to be argued about
   here. This is the claim that keeps the walk below cheap: the whole
   memory-touching surface of `src/` is two files.
3. **The capability set is derived by a reachability walk and matches the
   declaration.** Exact set equality over `Capability` members, so a capability
   that starts reaching a memory row either updates the declaration or reddens.
4. **Every capability beyond the eight carries a written reason.** The eight are
   derived off the enum's own `relationship_memory.` prefix; the residue is the
   part `RM-API-AC-002` has to disclose, and each entry says what it discloses
   and under which purpose.
5. **Each capability's *tables* are derived too, split into reads and writes.**
   The same walk, carrying a table set along its edges instead of only a boolean,
   with `select` told apart from `insert`/`update`/`delete` by the statement
   constructor at the root of the expression the table name sits in. Exact set
   equality against `DECLARED_TABLE_REACH`, which is what a changed reach has to
   be re-argued against.
6. **Every mention of a memory table lands in one of those two sets.** A name
   that appears outside any statement chain is counted as a read — the
   conservative direction — *and* has to be in `UNCLASSIFIED_TABLE_MENTIONS` with
   a reason, so a statement shape this derivation cannot read is a redness rather
   than a silent omission.
7. **`RM-API-AC-002`'s own "N of the eight (…)" claims are checked against the
   walk**, count and membership both, for every capability the row has to
   disclose. Prose failed three times; it is now parsed.
   `test_claimed_test_counts_match_collection.py` is the precedent, and its
   lesson is taken with it: the pattern that matches
   nothing passes everything, so the parse asserts it found claims, asserts both
   verbs appear, and asserts every capability beyond the eight carries one.
8. **The port crossings that reach memory are the two planes**, which is
   anti-vacuity for claim 9 and a statement worth making on its own.
9. **The walk's demonstrated blind spots are closed or declared.** Seven of them,
   each found by an independent review constructing a reach that slipped past the
   walk *and* past the untyped-receiver sweep: an unannotated receiver at a call
   site (`UNTYPED_PORT_CALL_SITES`), a port method referenced without being called
   — `functools.partial`, a callback, an assignment (`UNCALLED_PORT_METHOD_REFERENCES`),
   a call dispatched through a subscript (`DISPATCH_THROUGH_A_SUBSCRIPT`), a
   table reached as `tables.<name>` rather than by a bare imported name, which
   claim 2 now sees, a method named by a string through `getattr`
   (`DYNAMIC_ATTRIBUTE_LOOKUPS`), a table named inside a SQL string rather than by
   a `Table` object (`RAW_SQL_TABLE_MENTIONS`), and a *relative* import of a
   memory-reaching function, which `_imported_names()` used to drop on the floor
   while `_import_targets()` resolved it — an inconsistency, now gone.
10. **What each *branch* writes is derived, and the row's per-branch sentences
   are parsed against it.** Claims 5 and 7 bound a union; this one bounds the
   itinerary. The same walk is re-run once per member of the enum the guards
   branch on, evaluating each `if` against that member, and the enum itself is
   discovered from the guards rather than named here. An `if` that mentions the
   axis and that this evaluation cannot read is a redness
   (`UNREADABLE_BRANCH_GUARDS`), never a quiet union — an `if` and nothing else,
   and a guard it reads *wrongly* is neither, which the open list below now says
   rather than implies.

**Why a walk and not a grep.** The reach is four hops long and no hop is
spelled: `ApplicationService._entities_context` constructs an
`EntityContextService`, whose `_memory_summary` calls `summaries_for_context` on
a `RelationshipMemoryRepository` it holds as `self._memories`, which
`SqlRelationshipMemoryRepository` implements over `relationship_memories` and
`relationship_memory_versions`. Nothing on that path contains both a capability
name and a table name, which is exactly why three hand-written enumerations in a
row missed a hop.

**How receivers are typed.** A parameter's annotation, a `self` in a method
body, a `self._x` assigned in `__init__` from an annotated parameter, a local
assigned from a constructor call, and a property's return annotation. Where the
receiver types to an abstract port, every implementation of that port is
followed — which is how `unit_of_work.reviews.cases(...)` reaches `_Reviews`.
This over-approximates towards *more* reach, never less, and claim 9 is what
says the approximation is not silently going the other way.

**A derived table set is a bound, not an itinerary.** Claims 5, 6 and 7 say which
of the eight a capability's code path *can* touch, unioned over every branch.
`relationship_memory.archive` writes no statement, but it shares `_insert_version`
with `revise`, so `relationship_memory_versions` and
`relationship_memory_context_links` are in its write set. That is the right side
to err on for a disclosure claim and the wrong side for a description of one
request. Claim 10 is the itinerary, per branch of the axis the code branches on,
and `RM-API-AC-002` has to say which of the two any given sentence is making —
because the fourth failure above was a sentence that said the second while the
guard checked the first.

**What is still open — the ones known, which is a weaker sentence than the one
this paragraph used to make.** It said "four escapes are closed above; these are
not" and listed four, and a later review demonstrated three more that left every
test here green. Those three are now closed: a method named by a *string* through
`getattr` (claim 9 sweeps `getattr` and declares the five dynamic lookups that do
exist), a table named inside a SQL *string* rather than by a `Table` object
(claim 9 sweeps every non-docstring string constant in the package, which also
closes the `metadata.tables["…"]` spelling this paragraph used to list as open),
and a *relative* import of a memory-reaching function, which `_imported_names()`
dropped while `_import_targets()` resolved it — the two now resolve imports the
same way. What remains open is this, and the list is the ones found rather than
the ones there are:

* A *call* whose receiver this walk cannot type is caught only inside a module
  that imports `contracts.ports`, so a module reaching a repository handed to it
  by some other route is unswept. **This is the sharpest of the ones nothing
  covers**, which is the rank `RM-API-AC-002` gives it; the sharpest full stop is
  the seventh below, and it is the only one on this list held by a test.
* An uncalled reference to a port method whose receiver types to something
  *other* than a port implementation is allowed through, which is what lets
  `receipt.history` sit in a declaration rather than in the sweep — a genuine
  port hidden behind a misleading annotation would ride out on the same rule.
* A statement built by a helper that takes the table as a *parameter* attributes
  the table to the helper and the operation to whatever the helper does, which is
  correct; a helper that took the *operation* as a parameter too would not
  classify, and would land in `UNCLASSIFIED_TABLE_MENTIONS` as a read.
* A `getattr` whose attribute name is *computed* rather than a literal cannot be
  read at all. Five exist and each is declared with what it looks up, so the
  claim is that they have been read — not that a sixth could not hide a reach.
  This bullet said four for as long as there were five.
* Claim 10 splits on an enum member and assumes one member flows down the whole
  path. Nothing in the package passes an axis member as a call argument, and
  `test_the_branch_split_reads_every_guard_it_meets` asserts that; a call that
  started to would make the split describe the caller's branch rather than the
  callee's.
* Claim 10 reads a guard on an axis member, and a guard on a value *derived* from
  one — `stored_state is not None`, where `stored_state` came out of a
  member-keyed map. A guard on a value derived some other way (a boolean set in
  an earlier branch, say) reads as unknown, and unknown means both branches are
  unioned, which is claim 5's answer rather than claim 10's: the conservative
  direction for a bound and the wrong one for an itinerary. This bullet used to
  end by calling that the escape here that matters most to `RM-API-AC-002`. It is
  not, and the bullet below is why — the derived-value shape has a second mode,
  and that mode is neither unknown nor conservative.
* **A guard this evaluation decides *wrongly*, which every sentence above assumes
  cannot happen.** The `nulls` state `_evaluate_guard` consults for
  `stored_state is not None` is seeded where a local is assigned from the
  member-keyed subscript, and is never invalidated when that local is reassigned.
  So `stored_state = _STORED_STATE[request.disposition]` followed by
  `if stored_state is None: stored_state = MemoryProposalState.NEEDS_REVIEW`
  leaves the guard below it reading `False` for `mark_unresolved` while it is
  `True` at runtime, and the pruned branch's `update(relationship_memory_proposals)`
  drops out of the itinerary. The answer is confident, so it is not `None` and
  never reaches `UNREADABLE_BRANCH_GUARDS`; it is *narrowing*, so the "unknown
  unions both branches" argument does not reach it either. An independent review
  wrote those two lines and left all forty tests in this module green, alongside
  all twenty-four then in `tests/database/test_relationship_memory_review.py` —
  the stray UPDATE stamps `needs_review`, which is the state that module reads
  back and accepts. **This is the escape on the list that matters most to
  `RM-API-AC-002`, and it is the only one on the list a test holds.** Nothing in
  this module can hold it, because everything here reads the same source the
  claim is about; what holds it is
  `tests/database/test_relationship_memory_review.py::test_every_disposition_writes_exactly_the_memory_tables_it_is_declared_to`,
  which drives every member of the axis enum against a real server and reads the
  memory-plane tables off the statements the server is actually sent.
  Two weaker relatives are open and uncovered. A `match` on the axis is unioned
  across every one of its cases with no evaluation at all, and
  `_guard_names_the_axis` is consulted only inside the `ast.If` arm of the branch
  walk — so a `match`, a ternary, or `request.disposition.value == "accept"` (a
  comparison against the member's *string* rather than against the member) reads
  as unknown **and** never reaches `UNREADABLE_BRANCH_GUARDS` to say that it did.
  Those are the conservative direction, and they are silent about being in it,
  which is the half of the previous bullet's claim that survives.

Each is a way the derived sets could be narrower, or less specific, than the
truth without anything reddening — the seventh by being wrong rather than by
being coarse — and `RM-API-AC-002` therefore cites this module for what it
derives rather than for completeness.

**What the declarations cost, written down rather than left to be discovered.**
`UNCLASSIFIED_TABLE_MENTIONS`, `UNREADABLE_BRANCH_GUARDS`,
`DISPATCH_THROUGH_A_SUBSCRIPT` and `DYNAMIC_ATTRIBUTE_LOOKUPS` are keyed on the
*unparsed source* of the construct each declares, so renaming a local, a table
binding or a dispatch table reddens them and the repair is to re-key the entry
rather than to widen the rule. That is a real cost and it is deliberate. Keying
them on `(module, function)` and a count would survive the rename — and would
also survive a declared construct being *replaced* by a different one in the same
place, which is the only thing these four actually claim: that each declared text
has been read. The rename cost is paid loudly, by whoever renames; the
replacement cost would be paid silently, by whoever replaces. They stay keyed on
the text, and a rename here is a re-declaration and not a finding.

`UNCALLED_PORT_METHOD_REFERENCES` carries a different cost, and a worse one,
because it scales with the port surface rather than with this plane. It sweeps by
bare method *name* over every module that imports `contracts.ports`, which is
most of the application layer, so adding a `get`, a `list` or a `search` to
`ReviewRepository` would pull in every same-named attribute in all of them at
once and the declaration would have to absorb the lot. The narrower rule that
would avoid it — sweep only receivers that type to a port — drops the receiver
this walk *cannot* type, which is the escape the sweep exists for. So the cost
stands. What is corrected is the claim beside it: its own note said the price is
"one collision", and one is this head's count rather than the rule's bound.

Nothing here opens a connection, reaches a source, or touches a database. It
parses the source tree and imports the table declarations for their names.
"""

from __future__ import annotations

import ast
import collections
import re
from functools import cache
from pathlib import Path
from typing import Final

import pytest
from sqlalchemy import Table

from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.infrastructure.persistence import tables as declarations

ROOT: Final = Path(__file__).resolve().parents[2]
PACKAGE: Final = ROOT / "src" / "my_pa"

#: Where the table declarations live, and the one module excluded from the
#: "issues SQL against a memory table" census below: declaring a table is not
#: querying one.
DECLARATIONS: Final = PACKAGE / "infrastructure" / "persistence" / "tables.py"

#: Where the port protocols live. Claim 5 scopes its blind-spot sweep to the
#: modules that import from here, because a module that holds no port reference
#: cannot be calling a repository through one.
PORTS: Final = PACKAGE / "contracts" / "ports.py"

#: The application registry that says what a capability executes. Read as source
#: rather than imported, so a capability wired to a handler is visible here even
#: if importing the service in this tier were ever to become expensive.
SERVICE: Final = PACKAGE / "application" / "service.py"

#: The acceptance package, parsed for the digits `RM-API-AC-002` states about the
#: rows each capability reaches. Claim 7 is the whole reason this path is here: a
#: number in that row has been wrong three times and checked by nothing.
ACCEPTANCE: Final = ROOT / "evidence" / "acceptance" / "RELATIONSHIP-MEMORY-RM-AC-20260822.md"
IDENTITY_ACCESS_DELTA: Final = (
    ROOT / "evidence" / "acceptance" / "RI-FINAL-COMPLETION-RM-AC-DELTA-20260828.md"
)

#: The row whose digits are bound.
ROW: Final = "RM-API-AC-002"

#: The prefix the memory plane's table names share. Stops one letter short of
#: `relationship_memory_` on purpose, because `relationship_memories` is one of
#: the eight. It is a *selector* and not a list: the names, the count and the
#: membership all come from the `Table` objects it selects.
TABLE_PREFIX: Final = "relationship_memor"

#: The prefix the plane's own capability values share, used to split the derived
#: set into "the eight" and the residue that has to carry a reason. Matched
#: against `Capability` rather than against a hand-written list of the plane's
#: members, so a further `relationship_memory.*` capability is counted as one of
#: the plane's own rather than surfacing as an undocumented exception.
CAPABILITY_PREFIX: Final = "relationship_memory."

#: The modules that build a statement over one of the eight. Exact, so a third
#: joining the plane is argued about here rather than merged quietly — and the
#: two-file answer is what lets claim 3 walk callers instead of grepping.
MEMORY_SQL_MODULES: Final = frozenset(
    {
        "infrastructure/persistence/relationship_memory.py",
        "infrastructure/persistence/relationship_memory_proposals.py",
        "infrastructure/persistence/relationship_memory_review.py",
    }
)

#: The third arrived with `WP-RI-B-07` and is one insert wide. It could not have
#: arrived earlier: this module asserts exact set equality over the modules above
#: and could not admit a third until `Capability.RELATIONSHIP_MEMORY_PROPOSE`
#: existed, which is why `RelationshipMemoryProposalService` shipped against a
#: port with no implementor for two waves. The interlock worked.

#: Every capability whose handler can read or write one of the eight memory
#: tables. Compared for exact equality against the walk, so this is the sentence
#: `RM-API-AC-002` cites and the walk is what makes it checkable.
DECLARED: Final = frozenset(
    {
        Capability.RELATIONSHIP_MEMORY_CREATE,
        Capability.RELATIONSHIP_MEMORY_REVISE,
        Capability.RELATIONSHIP_MEMORY_ARCHIVE,
        Capability.RELATIONSHIP_MEMORY_RESTORE,
        Capability.RELATIONSHIP_MEMORY_GET,
        Capability.RELATIONSHIP_MEMORY_LIST,
        Capability.RELATIONSHIP_MEMORY_SEARCH,
        Capability.RELATIONSHIP_MEMORY_HISTORY,
        Capability.ENTITIES_CONTEXT,
        Capability.REVIEW_LIST,
        Capability.REVIEW_DECIDE,
        # `WP-RI-B-05`: the producer path, which is the only name on the plane's
        # own prefix that cannot reach `relationship_memories`.
        Capability.RELATIONSHIP_MEMORY_PROPOSE,
        # `WP-RI-B-06`: the governed merge reads the memory plane to decide
        # whether it may proceed, and writes nothing on it. Both are beyond the
        # plane's own prefix and both carry a reason below.
        Capability.ENTITIES_MERGE_PREVIEW,
        Capability.ENTITIES_MERGE,
        Capability.ENTITIES_SPLIT_PREVIEW,
        Capability.ENTITIES_SPLIT,
    }
)

#: The seven that are *not* `relationship_memory.*`, and what each one discloses
#: under a purpose issued for something else. This is the part of
#: `RM-API-AC-002` that is a disclosure rather than a design, so each entry says
#: the purpose, the rows and the fields rather than only the name.
#:
#: **Every table set stated here is parsed and checked, by the same functions
#: that parse `RM-API-AC-002`.** These strings used to be the one place in this
#: module where a derived fact was restated in unchecked prose — and the
#: `review.decide` entry restated the false quantifier that blocked the fourth
#: correction, one file further in than the row it was policing. An enumeration
#: in a reason is written in the `N of the eight (…)` form on purpose: that form
#: is what `_claims_in()` reads, and anything written another way is prose again.
BEYOND_THE_EIGHT: Final = {
    Capability.ENTITIES_SPLIT_PREVIEW: (
        "purpose `entity_identity_correction`. `entities.split.preview` reads three of the "
        "eight (`relationship_memories`, `relationship_memory_context_links`, "
        "`relationship_memory_proposals`) and writes none of the eight while proving every "
        "opaque binding still matches the completed merge ledger. It reads no memory text, "
        "classification, or evidence payload."
    ),
    Capability.ENTITIES_SPLIT: (
        "purpose `entity_identity_correction`. `entities.split` reads three of the eight "
        "(`relationship_memories`, `relationship_memory_context_links`, "
        "`relationship_memory_proposals`) and writes three of the eight "
        "(`relationship_memories`, `relationship_memory_context_links`, "
        "`relationship_memory_proposals`) to restore only exact opaque before-state bindings "
        "under after-state guards. It reads or writes no memory text, classification, or "
        "evidence payload."
    ),
    Capability.ENTITIES_CONTEXT: (
        "purpose `entity_read`. `entities.context` reads two of the eight "
        "(`relationship_memories`, `relationship_memory_versions`) through "
        "`summaries_for_context` and writes none of the eight, and it carries "
        "each surviving memory's `statement` verbatim on the card — so an "
        "`entity_read` grant does return memory text. Bounded by the "
        "classification filter, the 25-memory card limit and `_mine`, not by "
        "the purpose name; `RM-API-AC-013` carries the card's own bound."
    ),
    Capability.REVIEW_LIST: (
        "purpose `capture_review`. `review.list` reads two of the eight "
        "(`relationship_memory_proposals`, `relationship_memory_review_decisions`) "
        "and writes none of the eight: `relationship_memory_review_cases` selects "
        "the first with two correlated subqueries over the second, so the listing "
        "discloses a `subject_entity_id`, a `proposed_kind` and, once promoted, an "
        "`accepted_memory_id` and `accepted_memory_version_id` — for a subject "
        "the grant never named. It carries no statement text: "
        "`RelationshipMemoryReviewCase` has no statement field. Gated by the "
        "plane composition rather than by the capability name, which is what "
        "`RM-API-AC-011` and `RM-API-AC-018` carry."
    ),
    Capability.REVIEW_DECIDE: (
        "purpose `review_disposition`, and it reads as well as writes. "
        "`review.decide` reads three of the eight "
        "(`relationship_memory_proposals`, `relationship_memory_review_decisions`, "
        "`relationship_memory_proposal_evidence`) and writes seven of the eight "
        "(`relationship_memories`, `relationship_memory_versions`, "
        "`relationship_memory_context_links`, `relationship_memory_evidence_links`, "
        "`relationship_memory_review_decisions`, `relationship_memory_proposals`, "
        "`relationship_memory_proposal_evidence`). "
        "**That seven is a union over branches and no request writes it.** This "
        "string previously said the two non-promotion writes happen on every "
        "disposition; they do not, and claim 10 is what now says so. "
        "`review.decide` on `reject` writes two of the eight "
        "(`relationship_memory_review_decisions`, `relationship_memory_proposals`), "
        "while `review.decide` on `mark_unresolved` writes one of the eight "
        "(`relationship_memory_review_decisions`) — `_STORED_STATE` maps that one "
        "disposition to `None` and the proposal UPDATE is guarded on it. Bounded "
        "by what `_promotion_authority` can author and by the plane composition; "
        "`RM-API-AC-011` carries the promotion path."
    ),
    Capability.ENTITIES_MERGE_PREVIEW: (
        "purpose `entity_identity_correction`, and it is operator-only. "
        "`entities.merge.preview` reads three of the eight "
        "(`relationship_memories`, `relationship_memory_context_links`, "
        "`relationship_memory_proposals`) and writes "
        "none of the eight: `IdentityCorrectionService` asks the memory port "
        "which affected input Entities are a canonical memory subject, a proposal "
        "subject, or the Entity target of a current canonical version's context "
        "link, because `WP-08` owns the Relationship Memory side of an identity "
        "change and this phase refuses rather than guesses. The privacy-safe "
        "answer is only the subset and count of affected input Entity identifiers: "
        "`subject_entity_ids` returns the subset, and merge analysis derives its "
        "aggregate count. Neither returns a memory identifier, per-Entity memory "
        "count, or statement. "
        "Bounded by the operator gate, by "
        "`MY_PA_RELATIONSHIP_IDENTITY_CORRECTION_ENABLED`, and by the plane "
        "composition."
    ),
    Capability.ENTITIES_MERGE: (
        "purpose `entity_identity_correction`, and it is operator-only. "
        "`entities.merge` reads three of the eight "
        "(`relationship_memories`, `relationship_memory_context_links`, "
        "`relationship_memory_proposals`) and writes three of the eight "
        "(`relationship_memories`, `relationship_memory_context_links`, "
        "`relationship_memory_proposals`). Apply revalidates and changes only opaque "
        "subject/context bindings while retaining immutable origin subjects; it reads or "
        "writes no memory text, classification, or evidence payload."
    ),
}

#: Per capability, the memory tables it can read and the ones it can write.
#:
#: The declaration claim 5 is measured against, and the reason it exists rather
#: than a count: the row's third false enumeration got the *count* of
#: `review.decide`'s reads wrong by naming the same table twice, so a number on
#: its own would have absorbed the defect. Membership is what is declared; the
#: count follows from it.
#:
#: A capability's set is the union over every branch its handler can reach, which
#: is a bound and not an itinerary — see this module's docstring on
#: `relationship_memory.archive`.
DECLARED_TABLE_REACH: Final[dict[Capability, tuple[frozenset[str], frozenset[str]]]] = {
    Capability.RELATIONSHIP_MEMORY_CREATE: (
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_context_links",
                "relationship_memory_submissions",
                "relationship_memory_versions",
            }
        ),
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_context_links",
                "relationship_memory_submissions",
                "relationship_memory_versions",
            }
        ),
    ),
    Capability.RELATIONSHIP_MEMORY_REVISE: (
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_context_links",
                "relationship_memory_evidence_links",
                "relationship_memory_submissions",
                "relationship_memory_versions",
            }
        ),
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_context_links",
                "relationship_memory_submissions",
                "relationship_memory_versions",
            }
        ),
    ),
    Capability.RELATIONSHIP_MEMORY_ARCHIVE: (
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_context_links",
                "relationship_memory_submissions",
                "relationship_memory_versions",
            }
        ),
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_context_links",
                "relationship_memory_submissions",
                "relationship_memory_versions",
            }
        ),
    ),
    Capability.RELATIONSHIP_MEMORY_RESTORE: (
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_context_links",
                "relationship_memory_submissions",
                "relationship_memory_versions",
            }
        ),
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_context_links",
                "relationship_memory_submissions",
                "relationship_memory_versions",
            }
        ),
    ),
    # `WP-RI-B-05`. Two writes and two reads. The reads arbitrate an
    # open-equivalent retry and merge its exact evidence; neither exposes a
    # review decision or canonical memory to the producer.
    Capability.RELATIONSHIP_MEMORY_PROPOSE: (
        frozenset(
            {
                "relationship_memory_proposal_evidence",
                "relationship_memory_proposals",
            }
        ),
        frozenset(
            {
                "relationship_memory_proposal_evidence",
                "relationship_memory_proposals",
            }
        ),
    ),
    # `WP-RI-B-06`. Both halves of the governed merge read the same three tables to
    # decide whether they may proceed and write neither. The empty write set is
    # the Phase B boundary: a merge naming a memory subject, proposal subject or
    # current canonical Entity context target is refused, because `WP-08` owns
    # the redistribution and this phase will not guess it.
    Capability.ENTITIES_MERGE_PREVIEW: (
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_context_links",
                "relationship_memory_proposals",
            }
        ),
        frozenset(),
    ),
    Capability.ENTITIES_SPLIT_PREVIEW: (
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_context_links",
                "relationship_memory_proposals",
            }
        ),
        frozenset(),
    ),
    Capability.ENTITIES_SPLIT: (
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_context_links",
                "relationship_memory_proposals",
            }
        ),
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_context_links",
                "relationship_memory_proposals",
            }
        ),
    ),
    Capability.ENTITIES_MERGE: (
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_context_links",
                "relationship_memory_proposals",
            }
        ),
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_context_links",
                "relationship_memory_proposals",
            }
        ),
    ),
    Capability.RELATIONSHIP_MEMORY_GET: (
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_context_links",
                "relationship_memory_evidence_links",
                "relationship_memory_versions",
            }
        ),
        frozenset(),
    ),
    Capability.RELATIONSHIP_MEMORY_LIST: (
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_context_links",
                "relationship_memory_versions",
            }
        ),
        frozenset(),
    ),
    Capability.RELATIONSHIP_MEMORY_SEARCH: (
        frozenset({"relationship_memories", "relationship_memory_versions"}),
        frozenset(),
    ),
    Capability.RELATIONSHIP_MEMORY_HISTORY: (
        frozenset({"relationship_memories", "relationship_memory_versions"}),
        frozenset(),
    ),
    Capability.ENTITIES_CONTEXT: (
        frozenset({"relationship_memories", "relationship_memory_versions"}),
        frozenset(),
    ),
    Capability.REVIEW_LIST: (
        frozenset({"relationship_memory_proposals", "relationship_memory_review_decisions"}),
        frozenset(),
    ),
    Capability.REVIEW_DECIDE: (
        frozenset(
            {
                "relationship_memory_proposal_evidence",
                "relationship_memory_proposals",
                "relationship_memory_review_decisions",
            }
        ),
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_context_links",
                "relationship_memory_evidence_links",
                "relationship_memory_proposal_evidence",
                "relationship_memory_proposals",
                "relationship_memory_review_decisions",
                "relationship_memory_versions",
            }
        ),
    ),
}

#: Where a memory table is named outside any statement this derivation can read.
#:
#: Each of these binds a table or a column expression to a local for a statement
#: built further down, so the operation is decided somewhere the name is not.
#: They are folded into the *read* set — the conservative direction — and listed
#: here as well, because a statement shape this walk cannot classify is exactly
#: how a write would come to be reported as a read.
UNCLASSIFIED_TABLE_MENTIONS: Final[dict[tuple[str, str, str], str]] = {
    (
        "infrastructure/persistence/relationship_memory.py",
        "page_for_entity",
        "current = relationship_memory_versions.alias('current')",
    ): "the version alias the page joins; the join is in the `select` below it",
    (
        "infrastructure/persistence/relationship_memory.py",
        "page_for_entity",
        "rank: ColumnElement[bool] = not_(relationship_memories.c.pinned)",
    ): "a sort key held in a local for the `order_by` below it, annotated because "
    "the declared SQLAlchemy floor cannot infer it",
    (
        "infrastructure/persistence/relationship_memory.py",
        "search",
        "current = relationship_memory_versions.alias('current')",
    ): "the same alias, for the search page",
    (
        "infrastructure/persistence/relationship_memory.py",
        "search",
        "vector = func.to_tsvector(text(f\"'{_SEARCH_CONFIG}'\"), current.c.statement_text)",
    ): "the tsvector over the aliased version's statement, matched in the `select` below it",
    (
        "infrastructure/persistence/relationship_memory.py",
        "summaries_for_context",
        "current = relationship_memory_versions.alias('current')",
    ): "the same alias, for the context card",
    (
        "infrastructure/persistence/relationship_memory.py",
        "subject_entity_ids",
        "proposal_context = func.jsonb_array_elements(relationship_memory_proposals.c."
        "context_links).table_valued(column('value', relationship_memory_proposals.c."
        "context_links.type)).lateral()",
    ): "the lateral JSONB row source is held in a local and joined into the `select` "
    "below it; this assignment only derives rows from the proposal table and cannot write it",
    (
        "infrastructure/persistence/relationship_memory.py",
        "_memory_identity_effect_read_subject",
        "subjects = {IdentityEffectFamily.RELATIONSHIP_MEMORY: (relationship_memories, "
        "'memory_id', {'subject_entity_id', 'origin_subject_entity_id', 'version'}), "
        "IdentityEffectFamily.MEMORY_PROPOSAL: (relationship_memory_proposals, "
        "'memory_proposal_id', {'subject_entity_id', 'origin_subject_entity_id', "
        "'expected_subject_version', 'context_links'}), "
        "IdentityEffectFamily.MEMORY_CONTEXT_LINK: (relationship_memory_context_links, "
        "'context_link_id', {'target_id', 'origin_subject_entity_id'})}",
    ): "the closed identity-effect family map selects one table for the guarded update or "
    "after-state comparison issued by its caller; no content column is admitted",
    (
        "infrastructure/persistence/relationship_memory.py",
        "_memory_identity_effect_write_subject",
        "subjects = {IdentityEffectFamily.RELATIONSHIP_MEMORY: (relationship_memories, "
        "'memory_id', {'subject_entity_id', 'origin_subject_entity_id', 'version'}), "
        "IdentityEffectFamily.MEMORY_PROPOSAL: (relationship_memory_proposals, "
        "'memory_proposal_id', {'subject_entity_id', 'origin_subject_entity_id', "
        "'expected_subject_version', 'context_links'}), "
        "IdentityEffectFamily.MEMORY_CONTEXT_LINK: (relationship_memory_context_links, "
        "'context_link_id', {'target_id', 'origin_subject_entity_id'})}",
    ): "the separately named closed map feeds only guarded merge/split updates; no content "
    "column is admitted",
}

UNCLASSIFIED_WRITE_TABLE_MENTIONS: Final = frozenset(
    key for key in UNCLASSIFIED_TABLE_MENTIONS if key[1] == "_memory_identity_effect_write_subject"
)

#: The enums whose members the walk splits a capability's writes by.
#:
#: A *declaration*, and the only thing about claim 10 that is written down: the
#: axis is discovered by `_branch_axes()` from the guards the code actually
#: branches on, and this is what that discovery is compared to. Every population
#: underneath it is the enum's own — the members come off the `class Disposition`
#: body, not off a list here, so a ninth disposition joins the split by existing
#: and a disposition that no literal happens to mention is still one of them.
#: Two axes since `WP-RI-B-05`. `EntityStatus` joined when
#: `relationship_memory.propose` landed: `RelationshipMemoryProposalService.propose`
#: refuses a subject that has been merged away, so that one member of the status
#: vocabulary writes nothing while the other four write the producer's two
#: tables. It is a real split rather than an artefact of the scan -- the whole
#: point of that refusal is that a candidate raised about a historical identity
#: is not silently rebound onto the current person.
DECLARED_BRANCH_AXES: Final = frozenset({"Disposition", "EntityStatus"})

#: Per axis, per capability, per member: the memory tables that member's branch
#: can write. Only the capabilities whose write set actually *varies* by member
#: are here; for every other one the split is uniform and claim 5's set is the
#: whole answer, which `test_the_branch_split_reads_every_guard_it_meets`
#: asserts rather than assumes.
#:
#: This is the itinerary `DECLARED_TABLE_REACH` deliberately is not. The union of
#: the rows below is that declaration's write set, and the difference between
#: them is exactly the false sentence this claim exists to have caught: six
#: tables is what `review.decide` can write, one table is what `mark_unresolved`
#: does write, and the row is now required to say both.
DECLARED_BRANCH_WRITES: Final[dict[str, dict[Capability, dict[str, frozenset[str]]]]] = {
    "Disposition": {
        Capability.REVIEW_DECIDE: {
            "accept": frozenset(
                {
                    "relationship_memories",
                    "relationship_memory_context_links",
                    "relationship_memory_evidence_links",
                    "relationship_memory_proposals",
                    "relationship_memory_review_decisions",
                    "relationship_memory_versions",
                }
            ),
            "correct_and_accept": frozenset(
                {
                    "relationship_memories",
                    "relationship_memory_context_links",
                    "relationship_memory_evidence_links",
                    "relationship_memory_proposals",
                    "relationship_memory_review_decisions",
                    "relationship_memory_versions",
                }
            ),
            "reject": frozenset(
                {"relationship_memory_proposals", "relationship_memory_review_decisions"}
            ),
            "defer": frozenset(
                {"relationship_memory_proposals", "relationship_memory_review_decisions"}
            ),
            "mark_unresolved": frozenset({"relationship_memory_review_decisions"}),
            # `WP-RI-B-05`, Manager ruling R-8. The two tables `reject` writes,
            # and the same two acts — append the decision, stamp the proposal —
            # reaching no promotion table, which is "creates no canonical record"
            # measured rather than asserted. What the two branches do *not* share
            # is the state stamped and the reason recorded, and no table set can
            # express that: `REV::test_an_invalidation_is_not_a_rejection_and_
            # leaves_no_negative_finding` is what holds it.
            "invalidate": frozenset(
                {"relationship_memory_proposals", "relationship_memory_review_decisions"}
            ),
            "reprocess": frozenset(
                {
                    "relationship_memory_proposal_evidence",
                    "relationship_memory_proposals",
                    "relationship_memory_review_decisions",
                }
            ),
            "escalate": frozenset({"relationship_memory_review_decisions"}),
        }
    },
    "EntityStatus": {
        Capability.RELATIONSHIP_MEMORY_PROPOSE: {
            # Four statuses write the producer's two tables and one writes
            # nothing. `merged_redirect` is refused rather than followed: a
            # candidate raised about a historical identity, rebound onto the
            # entity that identity now redirects to, would put a different
            # statement in front of the reviewer than the evidence supports.
            "active": frozenset(
                {"relationship_memory_proposal_evidence", "relationship_memory_proposals"}
            ),
            "inactive": frozenset(
                {"relationship_memory_proposal_evidence", "relationship_memory_proposals"}
            ),
            "historical": frozenset(
                {"relationship_memory_proposal_evidence", "relationship_memory_proposals"}
            ),
            "archived": frozenset(
                {"relationship_memory_proposal_evidence", "relationship_memory_proposals"}
            ),
            "merged_redirect": frozenset(),
        }
    },
}

#: Guards that name the branch axis and that claim 10's evaluation cannot read.
#:
#: An unreadable guard is unioned over both of its branches, which turns claim
#: 10's itinerary back into claim 5's bound *for that branch* without saying so —
#: so each one is declared here with why reading it would change nothing, in the
#: same shape and for the same reason as `UNCLASSIFIED_TABLE_MENTIONS`. Only
#: guards inside a function that reaches a memory row are collected; the capture
#: and GoodNotes review planes branch on the same enum and reach none of the
#: eight, so their guards are not this row's business.
#:
#: **Keyed by axis since `WP-RI-B-07`, and the nesting is not bookkeeping.** A
#: guard is unreadable *for one axis*: `any(Disposition(...) in _ACCEPTING ...)`
#: is unreadable when the split is asking about a `Disposition` member and is not
#: a guard on `EntityStatus` at all. One flat dict compared against every axis
#: would have declared it on both and so declared, for the second axis, an escape
#: that does not exist there — which is the same class of false claim this module
#: exists to prevent, made about itself.
#:
#: `EntityStatus` has one deliberately unreadable guard: the persistence-layer
#: merged-subject safety check compares the stored string value with the enum
#: member's value. The split conservatively unions both arms; the application
#: service's readable status guard and its unit coverage hold the actual refusal.
UNREADABLE_BRANCH_GUARDS: Final[dict[str, dict[tuple[str, str, str], str]]] = {
    "Disposition": {
        (
            "my_pa.infrastructure.persistence.relationship_memory_review",
            "decide_relationship_memory_review",
            "any((Disposition(row.disposition) in _ACCEPTING for row in decisions))",
        ): "the terminal-acceptance test, and the one place `_ACCEPTING` is asked about a "
        "disposition that is *not* the request's — it reads the dispositions already on "
        "the decision chain. Reading it against the requested member would be wrong, not "
        "merely imprecise; it raises on the true branch, so leaving it unread costs the "
        "split nothing",
        (
            "my_pa.infrastructure.persistence.relationship_memory_review",
            "decide_relationship_memory_review",
            "request.disposition in _ACCEPTING and escalated and (not has_operator_authority)",
        ): "the accepting-after-escalation authority guard combines the requested "
        "Disposition with stored escalation state; the split conservatively unions it",
        (
            "my_pa.infrastructure.persistence.relationship_memory_review",
            "decide_relationship_memory_review",
            "request.disposition is Disposition.ESCALATE and escalated",
        ): "the repeated-escalation guard combines the requested Disposition with "
        "stored escalation state; the split conservatively unions it",
    },
    "EntityStatus": {
        (
            "my_pa.infrastructure.persistence.relationship_memory_proposals",
            "record_proposal",
            "subject.status == EntityStatus.MERGED_REDIRECT.value",
        ): "the persistence backstop compares a stored string with the enum member's "
        "value, a guard shape the branch evaluator cannot reduce. Conservatively "
        "unioning both arms does not weaken the runtime refusal; the application-layer "
        "EntityStatus guard supplies the readable branch split and the repository guard "
        "remains a fail-closed defense against bypass",
    },
}


#: Calls dispatched through a subscript, in a module that holds a port.
#:
#: `_edges()` cannot follow one: the call's `func` is a `Subscript`, so there is
#: no name to look up and no receiver to type, and a reach behind one would be
#: absent from the derived answer with nothing to say so. **This is the
#: codebase's own dominant dispatch idiom**, which is why it is declared with a
#: reason each rather than assumed not to happen.
DISPATCH_THROUGH_A_SUBSCRIPT: Final[dict[tuple[str, str], str]] = {
    ("my_pa.application.service", "_HANDLERS[command.capability]"): (
        "the capability registry, and the one subscript this module does resolve — "
        "by reading the table rather than the call. `_handlers()` parses `_HANDLERS` "
        "out of the source and maps every capability to the `(class, method)` it "
        "dispatches to, which is where the walk starts."
    ),
    ("my_pa.infrastructure.persistence.entity", "_DIRECTIONS[direction]"): (
        "three lambdas over `entity_relationships`, selected by an edge direction. "
        "It reaches no memory table — `entity.py` names none of the eight — and it "
        "returns a predicate rather than calling a repository."
    ),
}

#: References to a memory-reaching port method that are not calls of it.
#:
#: `functools.partial(repository.summaries_for_context, …)`, a callback handed to
#: a registry, `handler = repository.cases` — each reaches a memory row through a
#: name `_edges()` never sees in call position. Sweeping for the *name* rather
#: than for the call catches all three, at the price of one collision at this
#: head, which is what this declaration holds. **One is a measurement and not a
#: bound.** The sweep runs over every module that imports `contracts.ports`, so
#: the price is however many same-named attributes those modules happen to hold,
#: and a `get`, a `list` or a `search` added to `ReviewRepository` would collect
#: dozens at a stroke. The module docstring says why the narrower rule that would
#: avoid that is not available.
UNCALLED_PORT_METHOD_REFERENCES: Final[dict[tuple[str, str], str]] = {
    ("my_pa.application.service", "receipt.history"): (
        "not a port method. `receipt` is bound from `conflict.receipt` on a caught "
        "conflict, which this walk cannot type, and `history` there is the task "
        "write receipt's own history field. It collides with "
        "`RelationshipMemoryRepository.history`, with which it shares nothing but "
        "the word."
    ),
}

#: Call sites in a port-holding module whose method name is one a memory-reaching
#: port declares, and whose receiver this walk cannot type. Empty, and asserted
#: empty rather than left implicit: an entry here is a place claim 3 could be
#: narrower than the truth without saying so, and the honest repair is an
#: annotation rather than a line in this registry.
UNTYPED_PORT_CALL_SITES: Final[frozenset[tuple[str, str]]] = frozenset()

#: Attribute lookups by name rather than by syntax, in a module that holds a port
#: or builds memory SQL.
#:
#: `getattr(repository, "summaries_for_context")(…)` reaches a memory row through
#: a *string*. It is not an `Attribute`, so neither sibling sweep sees it, and it
#: is not a `Name` either, so `_edges()` records nothing — an independent review
#: built one inside the declared population and watched every one of the
#: eighteen tests this module then held stay green. A literal name that matches a
#: memory-reaching port method is therefore a redness, and a *computed* name is
#: declared with what it looks up: those cannot be read at all, and the claim
#: about them is only that each has been.
DYNAMIC_ATTRIBUTE_LOOKUPS: Final[dict[tuple[str, str], str]] = {
    ("my_pa.application.context.providers", "getattr(continuity, method_name, None)"): (
        "`method_name` comes from the three-tuple `listers` immediately above it — "
        "`commitments`, `decisions`, `tasks` — none of which is a method of any port "
        "that reaches a memory row, and the receiver is the continuity projection "
        "rather than a repository."
    ),
    ("my_pa.application.context.providers", "getattr(record, id_attr)"): (
        "the identifier field of a continuity record, named by the same `listers` "
        "tuple. It reads a value off a row, not a method off a port."
    ),
    ("my_pa.application.context.providers", "getattr(record, text_attr, '')"): (
        "the label field of the same continuity record, from the same tuple."
    ),
    ("my_pa.application.service", "getattr(command, field_name)"): (
        "the task-update command's optional fields, named by the literal tuple "
        "immediately above it. A command is a dataclass of values; it holds no port."
    ),
    ("my_pa.infrastructure.persistence.relationship_memory", "getattr(self._row, f'v_{name}')"): (
        "`_VersionRow.__getattr__`, which re-labels one already-fetched SQLAlchemy "
        "`Row` so `_to_version` can read it. The receiver is a row, the lookup issues "
        "no statement, and the module it sits in is already declared as one of the "
        "two that build memory SQL."
    ),
    (
        "my_pa.infrastructure.persistence.entity",
        "getattr(self._row, f'{_CHILD_PREFIX}{name}')",
    ): (
        "`_ChildRow.__getattr__`, the same mechanism one entry above and for the same "
        "reason: the entity plane's two joined resolution lookups label their child "
        "table's columns so `entities.version` cannot shadow the identifier's or the "
        "alias's, and this reads one already-fetched `Row` back under those labels. The "
        "receiver is a row, the lookup issues no statement, and the entity plane reaches "
        "no memory table at all."
    ),
    ("my_pa.infrastructure.persistence.entity", "getattr(row, name)"): (
        "the closed identity-effect subject declaration supplies column names from an exact "
        "allowlist; this reads one already-fetched row to compare the stored after-state"
    ),
    ("my_pa.infrastructure.persistence.relationship_memory", "getattr(row, name)"): (
        "the three-family memory identity-effect map supplies only opaque binding columns; "
        "this reads one already-fetched row to compare the stored after-state"
    ),
}

#: Memory table names appearing inside a string constant anywhere in the package.
#:
#: Empty, and asserted empty. `_memory_bindings()` reads `Table` *objects* through
#: three import spellings, so `connection.execute(text("SELECT … FROM "
#: "relationship_memory_versions"))` reaches a memory row past every claim here —
#: as would `metadata.tables["relationship_memories"]`, which this module's
#: docstring used to list as an open escape. Both are strings, and a string is
#: what this sweep reads. Docstrings are excluded because four of them discuss the
#: tables by name, which is the documentation working rather than a reach.
RAW_SQL_TABLE_MENTIONS: Final[frozenset[tuple[str, int, str]]] = frozenset()


# --- the source tree, parsed once --------------------------------------------


@cache
def _sources() -> tuple[tuple[Path, ast.Module], ...]:
    return tuple((path, ast.parse(path.read_text(encoding="utf-8"))) for path in _paths())


@cache
def _paths() -> tuple[Path, ...]:
    return tuple(sorted(PACKAGE.rglob("*.py")))


def _module_name(path: Path) -> str:
    dotted = path.relative_to(PACKAGE).with_suffix("").as_posix().replace("/", ".")
    if dotted == "__init__":
        return "my_pa"
    return "my_pa." + dotted.removesuffix(".__init__")


def _relative(path: Path) -> str:
    return path.relative_to(PACKAGE).as_posix()


def _methods(node: ast.ClassDef) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        child.name: child
        for child in node.body
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
    }


# --- claim 1: the eight tables -----------------------------------------------


@cache
def memory_tables() -> frozenset[str]:
    """The names `tables.py` binds the memory plane's `Table` objects to.

    Read off the objects rather than typed here, so the set this whole module
    measures is the schema's own and a ninth table joins it by existing.
    """
    return frozenset(
        name
        for name, value in vars(declarations).items()
        if isinstance(value, Table) and value.name.startswith(TABLE_PREFIX)
    )


def test_the_memory_plane_declares_exactly_eight_tables() -> None:
    """Anti-vacuity, and the one number `RM-P-AC-018` and this module share.

    A selector that matched nothing would make every other claim here pass over
    an empty set, and a selector that matched a table the plane does not own
    would widen the walk silently. The count is the check on both.
    """
    tables = memory_tables()
    assert len(tables) == 8, (
        f"the memory plane now declares {len(tables)} tables ({sorted(tables)}), not eight. "
        "If a table joined the plane, the walk below and `RM-P-AC-018` both move"
    )
    for name in tables:
        assert getattr(declarations, name).name == name, (
            f"{name} is bound to a table named {getattr(declarations, name).name}; this "
            "module assumes the binding name and the SQL name agree"
        )


# --- claim 2: which modules issue SQL against them ---------------------------


def _dotted(node: ast.expr) -> str | None:
    """`a.b.c` for a pure name/attribute chain, or `None` for anything else."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted(node.value)
        return None if prefix is None else f"{prefix}.{node.attr}"
    return None


def _table_expressions(
    node: ast.AST, names: dict[str, frozenset[str]]
) -> list[tuple[ast.expr, frozenset[str]]]:
    """Every expression inside `node` that this walk reads as a memory table."""
    found: list[tuple[ast.expr, frozenset[str]]] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Name | ast.Attribute):
            continue
        key = _dotted(child)
        if key is not None and key in names:
            found.append((child, names[key]))
    return found


@cache
def _memory_bindings() -> dict[Path, dict[str, frozenset[str]]]:
    """Per module, every expression this walk reads as one of the eight tables.

    Three spellings, because for a while only the first was recognised and the
    other two were demonstrated escapes:

    * `from …tables import relationship_memories` binds a bare name. This was
      the whole of it, and it is the spelling both persistence modules use.
    * `from . import tables`, or `import ….tables as t`, binds the *module*, and
      `tables.relationship_memories` then reaches a row through an attribute no
      bare-name scan sees. Applied to an already-declared module it changes
      nothing; applied to a **new** one it let a module join the plane without
      appearing in the census below, which is the claim that keeps the walk
      cheap.
    * A module-level aggregate — `_MEMORY_COLUMNS` — carries the table into
      every statement that splats it, which is how `detail` and `history` name
      their columns and how `page_for_entity` names none of them directly.

    A fourth spelling, a table fetched out of `metadata.tables[…]` by string, is
    invisible *to this function* — there is no `Table` object in the expression
    for it to bind. It is not an open escape, and this paragraph said it was for
    exactly one commit: the string is what
    `test_no_string_constant_names_a_memory_table_outside_the_declarations`
    sweeps, and that sweep is why the module docstring stopped carrying the
    spelling on its open list. The commit that closed it corrected the docstring
    and left the sibling here saying the opposite, which is the species of defect
    this whole module is a response to, one file in from the document it polices.
    """
    tables = memory_tables()
    found: dict[Path, dict[str, frozenset[str]]] = {}
    for path, tree in _sources():
        if path == DECLARATIONS:
            continue
        names: dict[str, frozenset[str]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if (node.module or "").endswith("tables") and alias.name in tables:
                        names[alias.asname or alias.name] = frozenset({alias.name})
                    elif alias.name == "tables":
                        local = alias.asname or alias.name
                        names.update({f"{local}.{table}": frozenset({table}) for table in tables})
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.endswith(".tables"):
                        local = alias.asname or alias.name
                        names.update({f"{local}.{table}": frozenset({table}) for table in tables})
        for statement in tree.body:
            target = _assigned_name(statement)
            value = getattr(statement, "value", None)
            if target is None or value is None:
                continue
            carried = frozenset[str]().union(
                *(tables for _child, tables in _table_expressions(value, names))
            )
            if carried:
                names[target] = carried
        found[path] = names
    return found


def _assigned_name(statement: ast.stmt) -> str | None:
    """The single bare name a statement assigns to, or `None`."""
    targets = (
        statement.targets
        if isinstance(statement, ast.Assign)
        else [statement.target]
        if isinstance(statement, ast.AnnAssign)
        else []
    )
    if len(targets) != 1 or not isinstance(targets[0], ast.Name):
        return None
    return targets[0].id


def test_only_the_declared_modules_issue_sql_against_a_memory_table() -> None:
    """Exact set equality, because the walk's cost assumes this answer is small.

    Two modules is what makes claim 3 a call-graph walk rather than a grep over
    six thousand lines of service: everything that touches a memory row bottoms
    out in one of these files, so the walk only has to find the callers.

    The census is over modules that *name* a table, not over modules that import
    one: `from . import tables` imports the whole declaration module, so an
    import-shaped census would have counted a module that never touched a memory
    row, and — worse — a bare-name census missed one that did.
    """
    naming = frozenset(
        _relative(path)
        for path, tree in _sources()
        if path != DECLARATIONS and _table_expressions(tree, _memory_bindings().get(path, {}))
    )
    assert naming == MEMORY_SQL_MODULES, (
        f"{sorted(naming ^ MEMORY_SQL_MODULES)} builds statements over a memory table "
        "but is not declared, or is declared and no longer does. A third module on this "
        "plane changes what `RM-API-AC-002` has to enumerate"
    )


# --- the reachability walk ---------------------------------------------------
#
# A node is one function: `("C", class, method)` or `("M", module, function)`.
# A node *reaches* a memory row if it names one of the eight table bindings, or
# calls a node that does. Nested `def`s are walked as part of the function that
# encloses them, which is deliberate — `_Reviews.cases` builds its whole query
# inside a nested `statement()` handed to `_read`, and attributing it to the
# enclosing method is what makes the port crossing visible.


def _annotated(node: ast.expr | None) -> str | None:
    """Reduce an annotation to a bare class name, or `None` if it is not one."""
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            node = ast.parse(node.value, mode="eval").body
        except SyntaxError:
            return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        # `Repository | None`: the union's one real member is the type.
        for side in (node.left, node.right):
            if isinstance(side, ast.Constant) and side.value is None:
                continue
            resolved = _annotated(side)
            if resolved is not None:
                return resolved
        return None
    if isinstance(node, ast.Subscript) and _annotated(node.value) == "Optional":
        return _annotated(node.slice)
    return None


@cache
def _classes() -> dict[str, tuple[Path, ast.ClassDef]]:
    """Module-level classes by bare name, first definition wins.

    Bare names because an annotation gives a bare name; twelve names are defined
    twice across the tree (`Disposition`, `EntityType` and ten others, domain
    models mirrored by adapters), and none of them is a repository or an
    application service, so the collision cannot merge a memory-reaching node
    into an unrelated one.
    """
    found: dict[str, tuple[Path, ast.ClassDef]] = {}
    for path, tree in _sources():
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                found.setdefault(node.name, (path, node))
    return found


@cache
def _subclasses() -> dict[str, frozenset[str]]:
    """Direct subclass names, by base name."""
    found: dict[str, set[str]] = collections.defaultdict(set)
    for name, (_path, node) in _classes().items():
        for base in node.bases:
            if isinstance(base, ast.Name):
                found[base.id].add(name)
            elif isinstance(base, ast.Attribute):
                found[base.attr].add(name)
    return {base: frozenset(names) for base, names in found.items()}


def _implementations(name: str) -> frozenset[str]:
    """A class and everything below it, so a port call reaches its implementors."""
    seen = {name}
    pending = [name]
    while pending:
        for child in _subclasses().get(pending.pop(), frozenset()):
            if child not in seen:
                seen.add(child)
                pending.append(child)
    return frozenset(seen)


@cache
def _module_functions() -> dict[tuple[str, str], ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        (_module_name(path), node.name): node
        for path, tree in _sources()
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


@cache
def _imported_names() -> dict[str, dict[str, tuple[str, str]]]:
    """Per module, `local name -> (source module, original name)`.

    Every `from … import …`, relative or absolute, plus module-level assignment
    aliases. An aliased *import* (`import … as x`) was followed from the start; an
    aliased *assignment* (`_aliased = relationship_memory_review_cases`) was not,
    and a call through the second name resolved to no edge at all — a reach that
    reddened nothing because the walk simply did not see the call.

    **Relative imports resolve here the same way they resolve in
    `_import_targets()`.** They did not: this function filtered on
    `node.level == 0` and dropped `from .relationship_memory_review import …` on
    the floor, so a call through a relatively imported memory-reaching function
    produced no edge and no complaint, while the sibling that scopes the
    blind-spot sweep handled the same statement correctly. There are no relative
    imports in `src/my_pa` today and nothing enforces that — no `TID` rule in
    ruff's `select`, no architecture test — so the inconsistency was one import
    statement away from mattering. Making the two agree costs one call and closes
    it without a new rule about how imports may be spelled.
    """
    found: dict[str, dict[str, tuple[str, str]]] = {}
    for path, tree in _sources():
        module = _module_name(path)
        bound: dict[str, tuple[str, str]] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            source = _import_source(path, node)
            if source is None:
                continue
            for alias in node.names:
                bound[alias.asname or alias.name] = (source, alias.name)
        for statement in tree.body:
            target = _assigned_name(statement)
            value = getattr(statement, "value", None)
            if target is None or not isinstance(value, ast.Name):
                continue
            if value.id in bound:
                bound[target] = bound[value.id]
            elif (module, value.id) in _module_functions():
                bound[target] = (module, value.id)
        found[module] = bound
    return found


#: `("C", class, method)` or `("M", module, function)`.
Node = tuple[str, str, str]


@cache
def _nodes() -> dict[Node, tuple[Path, str | None, ast.FunctionDef | ast.AsyncFunctionDef]]:
    found: dict[Node, tuple[Path, str | None, ast.FunctionDef | ast.AsyncFunctionDef]] = {}
    for path, tree in _sources():
        module = _module_name(path)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                found[("M", module, node.name)] = (path, None, node)
            elif isinstance(node, ast.ClassDef):
                for method in _methods(node).values():
                    found[("C", node.name, method.name)] = (path, node.name, method)
    return found


@cache
def _self_attributes() -> dict[str, dict[str, str]]:
    """Per class, `self._x -> type name`, from `__init__` and class-level annotations."""
    found: dict[str, dict[str, str]] = {}
    for name, (_path, node) in _classes().items():
        attributes: dict[str, str] = {}
        for statement in node.body:
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                annotated = _annotated(statement.annotation)
                if annotated is not None:
                    attributes[statement.target.id] = annotated
        initialiser = _methods(node).get("__init__")
        if initialiser is not None:
            arguments = initialiser.args
            parameters = {
                argument.arg: _annotated(argument.annotation)
                for argument in [
                    *arguments.posonlyargs,
                    *arguments.args,
                    *arguments.kwonlyargs,
                ]
            }
            for statement in ast.walk(initialiser):
                if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
                    continue
                target = statement.targets[0]
                if not isinstance(target, ast.Attribute):
                    continue
                if not (isinstance(target.value, ast.Name) and target.value.id == "self"):
                    continue
                value = statement.value
                if isinstance(value, ast.Name) and parameters.get(value.id):
                    attributes[target.attr] = str(parameters[value.id])
                elif (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id in _classes()
                ):
                    attributes[target.attr] = value.func.id
        found[name] = attributes
    return found


def _attribute_type(owner: str, attribute: str) -> str | None:
    """`owner.attribute`, resolved through a property's return type or `self._x`."""
    entry = _classes().get(owner)
    if entry is not None:
        method = _methods(entry[1]).get(attribute)
        if method is not None:
            return _annotated(method.returns)
    return _self_attributes().get(owner, {}).get(attribute)


def _environment(
    enclosing: str | None, function: ast.FunctionDef | ast.AsyncFunctionDef
) -> dict[str, str]:
    """The names inside one function this walk can put a type to."""
    known: dict[str, str] = {}
    if enclosing is not None:
        known["self"] = enclosing
    arguments = function.args
    for argument in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]:
        annotated = _annotated(argument.annotation)
        if annotated is not None:
            known[argument.arg] = annotated
    for statement in ast.walk(function):
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            annotated = _annotated(statement.annotation)
            if annotated is not None:
                known[statement.target.id] = annotated
        elif (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name)
            and statement.value.func.id in _classes()
        ):
            known[statement.targets[0].id] = statement.value.func.id
    return known


def _expression_type(node: ast.expr, known: dict[str, str]) -> str | None:
    """The class an expression evaluates to, or `None` where the walk cannot say."""
    if isinstance(node, ast.Name):
        return known.get(node.id) or (node.id if node.id in _classes() else None)
    if isinstance(node, ast.Attribute):
        owner = _expression_type(node.value, known)
        return None if owner is None else _attribute_type(owner, node.attr)
    if isinstance(node, ast.Call):
        function = node.func
        if isinstance(function, ast.Name) and function.id in _classes():
            return function.id
        if isinstance(function, ast.Attribute):
            owner = _expression_type(function.value, known)
            if owner is not None:
                entry = _classes().get(owner)
                if entry is not None:
                    method = _methods(entry[1]).get(function.attr)
                    if method is not None:
                        return _annotated(method.returns)
        return None
    if isinstance(node, ast.IfExp):
        # `unit_of_work.relationship_memory if composed else None`.
        return _expression_type(node.body, known) or _expression_type(node.orelse, known)
    if isinstance(node, ast.Await):
        return _expression_type(node.value, known)
    return None


def _callees(call: ast.Call, module: str, known: dict[str, str]) -> frozenset[Node]:
    """The nodes one call site can reach, over everything this walk can resolve.

    Shared with claim 10, which walks the same edges a statement at a time so it
    can tell which branch a call sits in — the whole-function edge map below
    cannot, because it has thrown the branch away by the time it is built.
    """
    called = call.func
    if isinstance(called, ast.Name):
        if (module, called.id) in _module_functions():
            return frozenset({("M", module, called.id)})
        imported = _imported_names()[module].get(called.id)
        if imported is not None and imported in _module_functions():
            return frozenset({("M", imported[0], imported[1])})
        return frozenset()
    if isinstance(called, ast.Attribute):
        owner = _expression_type(called.value, known)
        if owner is None:
            return frozenset()
        return frozenset(
            ("C", implementation, called.attr)
            for implementation in _implementations(owner)
            if ("C", implementation, called.attr) in _nodes()
        )
    return frozenset()


@cache
def _edges() -> dict[Node, frozenset[Node]]:
    """Caller to callee, over everything this walk can resolve."""
    found: dict[Node, set[Node]] = collections.defaultdict(set)
    for node, (path, enclosing, function) in _nodes().items():
        module = _module_name(path)
        known = _environment(enclosing, function)
        for call in ast.walk(function):
            if isinstance(call, ast.Call):
                found[node] |= _callees(call, module, known)
    return {caller: frozenset(callees) for caller, callees in found.items()}


@cache
def _directly_naming_a_memory_table() -> frozenset[Node]:
    return frozenset(
        node
        for node, (path, _enclosing, function) in _nodes().items()
        if _table_expressions(function, _memory_bindings().get(path, {}))
    )


@cache
def reaching_nodes() -> frozenset[Node]:
    """Every function that can read or write one of the eight, transitively."""
    callers: dict[Node, set[Node]] = collections.defaultdict(set)
    for caller, callees in _edges().items():
        for callee in callees:
            callers[callee].add(caller)
    reached = set(_directly_naming_a_memory_table())
    pending = list(reached)
    while pending:
        for caller in callers.get(pending.pop(), set()):
            if caller not in reached:
                reached.add(caller)
                pending.append(caller)
    return frozenset(reached)


# --- claim 3: the capability set ---------------------------------------------


@cache
def _handlers() -> dict[Capability, tuple[str, str]]:
    """`_HANDLERS` in `service.py`, as `capability -> (class, method)`.

    Read from the registry rather than from a list here, for the reason the
    registry's own comment gives: a capability is available exactly when
    something there can execute it, so there is no second place to edit.
    """
    tree = ast.parse(SERVICE.read_text(encoding="utf-8"))
    found: dict[Capability, tuple[str, str]] = {}
    for node in ast.walk(tree):
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, ast.AnnAssign)
            else []
        )
        if not any(isinstance(target, ast.Name) and target.id == "_HANDLERS" for target in targets):
            continue
        for mapping in ast.walk(node):
            if not isinstance(mapping, ast.Dict):
                continue
            for key, value in zip(mapping.keys, mapping.values, strict=True):
                if (
                    isinstance(key, ast.Attribute)
                    and isinstance(key.value, ast.Name)
                    and key.value.id == "Capability"
                    and isinstance(value, ast.Attribute)
                    and isinstance(value.value, ast.Name)
                ):
                    found[Capability[key.attr]] = (value.value.id, value.attr)
    return found


@cache
def reaching_capabilities() -> frozenset[Capability]:
    """The derived answer `RM-API-AC-002` needs: who can reach a memory row."""
    reached = reaching_nodes()
    return frozenset(
        capability
        for capability, (owner, method) in _handlers().items()
        if ("C", owner, method) in reached
    )


def test_the_walk_finds_a_registry_a_population_and_a_path() -> None:
    """Anti-vacuity, in the three places this walk can silently find nothing.

    An empty handler registry, an empty set of functions naming a table, or a
    reaching set no larger than the functions that name one directly would each
    make claim 3 an assertion about nothing — and the third is the one that
    matters, because it is what says the *call graph* resolved rather than just
    the two persistence modules.
    """
    assert len(_handlers()) >= 60, (
        f"only {len(_handlers())} capabilities were read out of `_HANDLERS`; the "
        "registry moved or this parse went stale"
    )
    direct = _directly_naming_a_memory_table()
    assert len(direct) >= 12, (
        f"only {len(direct)} functions name a memory table binding; the two "
        "persistence modules hold more than that, so the scan is not reaching them"
    )
    reached = reaching_nodes()
    assert len(reached) > len(direct) + 8, (
        f"the walk reached {len(reached)} functions from {len(direct)} that name a "
        "table directly. The callers did not resolve, so claim 3 is measuring the "
        "persistence layer and calling it the capability surface"
    )
    nine = frozenset(
        capability for capability in Capability if capability.value.startswith(CAPABILITY_PREFIX)
    )
    # Nine since `WP-RI-B-05`. The count is asserted rather than derived on
    # purpose -- it is what tells a reader the prefix scan found the plane and
    # not a substring -- and it moved when `relationship_memory.propose` was
    # published, which is a change to the plane and not to this scan.
    assert len(nine) == 9, f"the plane now publishes {len(nine)} capabilities of its own, not 9"
    assert nine <= reaching_capabilities(), (
        f"{sorted(capability.value for capability in nine - reaching_capabilities())} are "
        "`relationship_memory.*` capabilities the walk did not find reaching a memory row. "
        "That is not a finding about the code; it is this walk failing"
    )


def test_every_capability_that_reaches_a_memory_row_is_declared() -> None:
    """The derived enumeration, against the one `RM-API-AC-002` cites.

    Exact set equality in both directions. A capability that starts reaching a
    memory row is a new disclosure surface and has to be argued about in the
    acceptance row; a capability that stops reaching one leaves a claim in that
    row describing something the code no longer does, which is the same defect
    pointing the other way.
    """
    derived = reaching_capabilities()
    assert derived == DECLARED, (
        f"{sorted(capability.value for capability in derived ^ DECLARED)} reaches a "
        "relationship-memory table without being declared, or is declared and no "
        "longer reaches one. If the code moved, update `DECLARED`, "
        "`BEYOND_THE_EIGHT`, `DECLARED_TABLE_REACH` and `RM-API-AC-002` together — "
        "the acceptance row cites this test by name. If the code did not move, this "
        "is not a finding about the code; it is this walk failing, and the repair is "
        "in the walk"
    )


def test_every_capability_beyond_the_eight_says_what_it_discloses() -> None:
    """The residue is the disclosure, so the residue is what carries a reason.

    The eight are derived off the enum's own prefix rather than subtracted from
    a list here, so a ninth `relationship_memory.*` capability joins the plane
    without landing in `BEYOND_THE_EIGHT` and being described as an exception.
    """
    eight = frozenset(
        capability for capability in Capability if capability.value.startswith(CAPABILITY_PREFIX)
    )
    residue = reaching_capabilities() - eight
    assert residue == frozenset(BEYOND_THE_EIGHT), (
        f"{sorted(capability.value for capability in residue ^ frozenset(BEYOND_THE_EIGHT))} "
        "reaches a memory row from outside the eight with no written reason, or "
        "carries a reason and no longer reaches one"
    )
    for capability, reason in BEYOND_THE_EIGHT.items():
        purposes = permitted_purposes(capability)
        assert any(f"`{purpose.value}`" in reason for purpose in purposes), (
            f"{capability.value}'s reason names no purpose it actually holds "
            f"({sorted(purpose.value for purpose in purposes)}); the purpose is the "
            "grant boundary the criterion is about"
        )


# --- claims 5 and 6: which tables, and read or written -----------------------
#
# The same nodes and the same edges, carrying a pair of table sets instead of a
# boolean. A table name is attributed to the statement it sits in, and the
# statement's operation is read off the constructor at the root of the
# expression chain — `select(...).select_from(t).where(_mine(t, p))` is one
# chain rooted at `select`, so both mentions of `t` are reads, and
# `insert(t).values(_bound(t, p, {...}))` is one chain rooted at `insert`.
# Attributing by chain root rather than by nearest call is what makes
# `_mine`/`_bound` — the partition wrappers every statement here goes through —
# transparent instead of opaque.

#: What each statement constructor does to a row. `select` is the only read, and
#: the split is the whole content of claim 5: `RM-API-AC-002` has to disclose
#: what a grant can *learn* separately from what it can *change*.
STATEMENT_CONSTRUCTORS: Final = {
    "select": "read",
    "insert": "write",
    "update": "write",
    "delete": "write",
}


def _chain_root(call: ast.Call, statements: dict[str, str]) -> str | None:
    """The constructor a call's expression chain is rooted at, if any.

    `select(a).where(b).limit(c)` is a `Call` whose `func` is an `Attribute` on a
    `Call` whose `func` is an `Attribute` on `select(a)`, so the root is found by
    walking down the `func` side. Where the chain is rooted at a *name* instead —
    `statement = select(...)` and then `statement.order_by(...)`, which both
    persistence modules do — the name is looked up in the statement locals this
    function is given.
    """
    function = call.func
    if isinstance(function, ast.Name):
        return function.id if function.id in STATEMENT_CONSTRUCTORS else None
    if isinstance(function, ast.Attribute):
        if isinstance(function.value, ast.Call):
            return _chain_root(function.value, statements)
        if isinstance(function.value, ast.Name):
            return statements.get(function.value.id)
    return None


def _statement_locals(function: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, str]:
    """Locals holding a half-built statement, as `name -> constructor`."""
    found: dict[str, str] = {}
    for statement in ast.walk(function):
        target = _assigned_name(statement)
        value = getattr(statement, "value", None)
        if target is None or not isinstance(value, ast.Call):
            continue
        root = _chain_root(value, found)
        if root is not None:
            found[target] = root
    return found


def _local_table_names(
    function: ast.FunctionDef | ast.AsyncFunctionDef, names: dict[str, frozenset[str]]
) -> dict[str, frozenset[str]]:
    """`names`, plus the locals a function aliases a memory table under.

    `current = relationship_memory_versions.alias("current")` is the only shape
    that occurs, and it occurs three times; without it every predicate written
    against the alias would be attributed to no table at all.
    """
    found = dict(names)
    for statement in ast.walk(function):
        target = _assigned_name(statement)
        value = getattr(statement, "value", None)
        if target is None or not isinstance(value, ast.Call):
            continue
        if not isinstance(value.func, ast.Attribute) or value.func.attr not in {
            "alias",
            "join",
            "outerjoin",
        }:
            continue
        carried = frozenset[str]().union(
            *(tables for _child, tables in _table_expressions(value, found))
        )
        if carried:
            found[target] = carried
    return found


#: `(reads, writes, unclassified)`, where `unclassified` names the enclosing
#: statement so a shape this derivation cannot read is legible.
TableReach = tuple[frozenset[str], frozenset[str], frozenset[tuple[str, str, str]]]


@cache
def _direct_table_reach() -> dict[Node, TableReach]:
    """Per function, the memory tables its own statements read and write."""
    found: dict[Node, TableReach] = {}
    for node, (path, _enclosing, function) in _nodes().items():
        names = _local_table_names(function, _memory_bindings().get(path, {}))
        mentions = _table_expressions(function, names)
        if not mentions:
            continue
        statements = _statement_locals(function)
        parents = {
            child: parent for parent in ast.walk(function) for child in ast.iter_child_nodes(parent)
        }
        reads: set[str] = set()
        writes: set[str] = set()
        unclassified: set[tuple[str, str, str]] = set()
        for child, tables in mentions:
            if isinstance(child.ctx, ast.Store | ast.Del):
                continue
            operation = None
            cursor: ast.AST = child
            while cursor in parents:
                cursor = parents[cursor]
                if isinstance(cursor, ast.Call):
                    root = _chain_root(cursor, statements)
                    if root is not None:
                        operation = STATEMENT_CONSTRUCTORS[root]
                        break
            if operation == "read":
                reads |= tables
            elif operation == "write":
                writes |= tables
            else:
                # Conservative unless the exact registered declaration is the
                # closed write-only identity-effect table map.
                key = (_relative(path), function.name, _enclosing_statement(child, parents))
                if key in UNCLASSIFIED_WRITE_TABLE_MENTIONS:
                    writes |= tables
                else:
                    reads |= tables
                unclassified.add(key)
        found[node] = (frozenset(reads), frozenset(writes), frozenset(unclassified))
    return found


def _enclosing_statement(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    """The source of the smallest statement holding `node`, for a legible registry."""
    cursor = node
    while cursor in parents and not isinstance(cursor, ast.stmt):
        cursor = parents[cursor]
    return ast.unparse(cursor)


@cache
def _reachable_from(node: Node) -> frozenset[Node]:
    """`node` and everything it can call, transitively."""
    edges = _edges()
    seen = {node}
    pending = [node]
    while pending:
        for callee in edges.get(pending.pop(), frozenset()):
            if callee not in seen:
                seen.add(callee)
                pending.append(callee)
    return frozenset(seen)


@cache
def capability_table_reach() -> dict[Capability, tuple[frozenset[str], frozenset[str]]]:
    """The derived answer `RM-API-AC-002` needs: which rows, and read or written."""
    direct = _direct_table_reach()
    found: dict[Capability, tuple[frozenset[str], frozenset[str]]] = {}
    for capability, (owner, method) in _handlers().items():
        reached = _reachable_from(("C", owner, method))
        reads = frozenset[str]().union(*(direct[node][0] for node in reached if node in direct))
        writes = frozenset[str]().union(*(direct[node][1] for node in reached if node in direct))
        if reads or writes:
            found[capability] = (reads, writes)
    return found


def test_every_capability_reaches_exactly_the_tables_it_declares() -> None:
    """The derived table sets, against the declaration `RM-API-AC-002` restates.

    Exact set equality per capability and in both directions, for the reason the
    row's own history gives: a capability that starts reading a new memory table
    discloses something new under a purpose already granted, and a capability
    that stops leaves the row describing a reach the code no longer has.

    Membership rather than a count, because the defect this replaces was a count.
    "It reads four of the eight" was arrived at by counting
    `relationship_memory_proposals` twice and missing
    `relationship_memory_proposal_evidence` once; the two errors nearly cancelled
    and a bare number would have hidden the fact that they had not.
    """
    derived = capability_table_reach()
    assert set(derived) == set(DECLARED_TABLE_REACH), (
        f"{sorted(capability.value for capability in set(derived) ^ set(DECLARED_TABLE_REACH))} "
        "reaches a memory table without a declared table set, or declares one and "
        "reaches nothing"
    )
    wrong = [
        f"{capability.value} reads {sorted(derived[capability][0])} and writes "
        f"{sorted(derived[capability][1])}; it is declared to read "
        f"{sorted(DECLARED_TABLE_REACH[capability][0])} and write "
        f"{sorted(DECLARED_TABLE_REACH[capability][1])}"
        for capability in sorted(derived, key=lambda member: member.value)
        if derived[capability] != DECLARED_TABLE_REACH[capability]
    ]
    assert not wrong, (
        "the tables these capabilities reach are not the tables declared for them. "
        "Update `DECLARED_TABLE_REACH` and the matching `RM-API-AC-002` sentence "
        "together, or repair the walk if the code did not move:\n" + "\n".join(wrong)
    )


def test_the_table_derivation_reads_every_statement_shape_it_meets() -> None:
    """Anti-vacuity for claim 5, and the registry of what it could not classify.

    Three floors. Both persistence modules must be represented, or the split is
    measuring one plane; every one of the eight must be reached by something, or
    a table is being disclosed by a claim that never mentions it; and the
    unclassified mentions must be exactly the declared ones, because those are
    the places a write could be reported as a read.
    """
    direct = _direct_table_reach()
    assert direct, "no function names a memory table in a statement; the derivation went empty"
    reads = frozenset[str]().union(*(entry[0] for entry in direct.values()))
    writes = frozenset[str]().union(*(entry[1] for entry in direct.values()))
    assert reads | writes == memory_tables(), (
        f"{sorted(memory_tables() - (reads | writes))} is one of the eight and no "
        "derived statement reads or writes it; the derivation is not seeing the plane"
    )
    assert writes, "nothing writes a memory table; `insert`/`update` are not being seen"
    unclassified = frozenset[tuple[str, str, str]]().union(*(entry[2] for entry in direct.values()))
    assert unclassified == frozenset(UNCLASSIFIED_TABLE_MENTIONS), (
        f"{sorted(unclassified ^ frozenset(UNCLASSIFIED_TABLE_MENTIONS))} names a memory "
        "table outside any statement this derivation can read. It has been counted as a "
        "read; if it is a write, the derived set is wrong in the direction that matters"
    )


# --- claim 10: what each branch writes ---------------------------------------
#
# Claims 5 and 6 union a capability's writes over every branch its handler can
# reach. That is the right answer to "what may this grant change" and the wrong
# answer to "what does a reject change", and `RM-API-AC-002` has now been wrong
# about the second while the first was checked.
#
# So the same walk runs again, once per member of the enum the guards branch on,
# with two differences. It walks statements in order instead of `ast.walk`-ing a
# whole function, so a write inside `if disposition in _ACCEPTING:` is attributed
# to that branch and a statement after `if …: raise` is attributed to the branch
# that did not raise. And it evaluates each `if` against the member, so a branch
# that cannot be taken contributes nothing.
#
# The axis is discovered, not named: `_branch_axes()` finds every enum whose
# members the guards on a memory-reaching path actually mention, splits by each,
# and keeps the ones that change an answer. `DECLARED_BRANCH_AXES` is what that
# discovery is compared to.

#: The bases a class carries when its members can be a branch axis.
_ENUM_BASES: Final = frozenset({"Enum", "StrEnum", "IntEnum"})


@cache
def _enum_members(name: str) -> tuple[tuple[str, str], ...] | None:
    """`((MEMBER, "value"), …)` for an enum class in the tree, or `None`.

    Read off the class body, so the population is the enum's own. A member the
    guards never mention is still a member, which is the whole point: the false
    sentence this claim replaces was true of four dispositions out of five, and a
    population drawn from the literals the guards happen to name would have
    contained all five anyway — by luck, this time.
    """
    entry = _classes().get(name)
    if entry is None:
        return None
    node = entry[1]
    bases = {
        base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", None)
        for base in node.bases
    }
    if not bases & _ENUM_BASES:
        return None
    found = tuple(
        (statement.targets[0].id, statement.value.value)
        for statement in node.body
        if isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )
    return found or None


def _member_collection(node: ast.expr) -> tuple[str, frozenset[str]] | None:
    """`(enum, {MEMBER, …})` for a literal collection of one enum's members."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"frozenset", "set", "tuple", "list"}
    ):
        if not node.args:
            return None
        node = node.args[0]
    if not isinstance(node, ast.Set | ast.List | ast.Tuple):
        return None
    enum: str | None = None
    members: set[str] = set()
    for element in node.elts:
        if not (isinstance(element, ast.Attribute) and isinstance(element.value, ast.Name)):
            return None
        if enum is not None and element.value.id != enum:
            return None
        enum = element.value.id
        members.add(element.attr)
    if enum is None or _enum_members(enum) is None:
        return None
    return enum, frozenset(members)


def _member_mapping(node: ast.expr) -> tuple[str, frozenset[str]] | None:
    """`(enum, {MEMBER whose value is literally `None`, …})` for a member-keyed dict.

    Only "is the value `None`" is carried, because that is the one thing a guard
    downstream can ask about a value pulled out of such a map without this walk
    having to model the value itself — and it is what `_STORED_STATE` is for.
    """
    if not isinstance(node, ast.Dict):
        return None
    enum: str | None = None
    nulls: set[str] = set()
    for key, value in zip(node.keys, node.values, strict=True):
        if not (isinstance(key, ast.Attribute) and isinstance(key.value, ast.Name)):
            return None
        if enum is not None and key.value.id != enum:
            return None
        enum = key.value.id
        if isinstance(value, ast.Constant) and value.value is None:
            nulls.add(key.attr)
    if enum is None or _enum_members(enum) is None:
        return None
    return enum, frozenset(nulls)


#: `("collection" | "mapping", enum, members)`.
EnumLiteral = tuple[str, str, frozenset[str]]


@cache
def _enum_literals() -> dict[str, dict[str, EnumLiteral]]:
    """Per module, every module-level name bound to a literal over one enum.

    Found by shape, and deliberately not counted: this docstring said "thirty-odd
    of these exist" against a measurement of fifty-five, and a figure here would
    be one more number in prose bound to nothing — which is the defect the rest
    of this module exists to have caught.
    `_ACCEPTING` and `_STORED_STATE` are two of them and are named nowhere
    in this module: a guard is read by resolving whatever name it references, so
    renaming either one changes nothing here and deleting one changes the derived
    answer rather than hiding a change to it.
    """
    found: dict[str, dict[str, EnumLiteral]] = {}
    for path, tree in _sources():
        bound: dict[str, EnumLiteral] = {}
        for statement in tree.body:
            target = _assigned_name(statement)
            value = getattr(statement, "value", None)
            if target is None or value is None:
                continue
            collection = _member_collection(value)
            if collection is not None:
                bound[target] = ("collection", *collection)
                continue
            mapping = _member_mapping(value)
            if mapping is not None:
                bound[target] = ("mapping", *mapping)
        found[_module_name(path)] = bound
    return found


def _resolve_literal(module: str, name: str) -> EnumLiteral | None:
    """A name in `module`, resolved to an enum literal here or where it came from."""
    local = _enum_literals().get(module, {}).get(name)
    if local is not None:
        return local
    imported = _imported_names().get(module, {}).get(name)
    if imported is None:
        return None
    return _enum_literals().get(imported[0], {}).get(imported[1])


def _axis_expression(node: ast.expr, enum: str, known: dict[str, str]) -> bool:
    """Whether `node` is a name or attribute this walk types to `enum`.

    A `Call` is excluded deliberately. `Disposition(row.disposition)` types to
    `Disposition` and is a *different* disposition — the one already on the
    decision chain — so treating it as the request's would not be imprecise, it
    would be wrong. Excluding calls leaves that guard unreadable, which is a
    declared redness rather than a silent misreading.
    """
    if isinstance(node, ast.Call) or not isinstance(node, ast.Name | ast.Attribute):
        return False
    return _expression_type(node, known) == enum


def _evaluate_guard(
    test: ast.expr,
    enum: str,
    member: str,
    *,
    known: dict[str, str],
    module: str,
    nulls: dict[str, frozenset[str]],
) -> bool | None:
    """`test` decided for one member of `enum`, or `None` where it cannot be.

    Four shapes, which is every shape the guards on a memory-reaching path use:
    membership of a literal collection, identity against one member, `is
    None`/`is not None` on a local pulled out of a member-keyed mapping, and the
    boolean combinations of those. Anything else is `None`, and `None` unions the
    branches, which costs precision and not soundness;
    `UNREADABLE_BRANCH_GUARDS` is where the ones that mention the axis in an `if`
    are made to be visible.

    **The third shape is the exception, and this docstring used to say there was
    none.** It read "an unreadable guard costs precision, never soundness", which
    is true of every `None` this function returns and false of the one answer it
    gets confidently wrong. `nulls` is seeded by the branch walk where a local is
    assigned from a member-keyed subscript, and it is not invalidated when that
    local is reassigned — so

        stored_state = _STORED_STATE[request.disposition]
        if stored_state is None:
            stored_state = MemoryProposalState.NEEDS_REVIEW
        if stored_state is not None:        # always true at runtime

    has this function answer `False` for `mark_unresolved` to a guard that is
    `True`, pruning a branch that runs. That is *narrowing*, not conservative,
    and it is invisible: the answer is not `None`, so it never reaches the
    registry. The module docstring's seventh open escape is this, and what holds
    it is a database test that reads the statements the server is sent rather
    than anything that reads this source.
    """
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = _evaluate_guard(test.operand, enum, member, known=known, module=module, nulls=nulls)
        return None if inner is None else not inner
    if isinstance(test, ast.BoolOp):
        values = [
            _evaluate_guard(value, enum, member, known=known, module=module, nulls=nulls)
            for value in test.values
        ]
        if isinstance(test.op, ast.And):
            if any(value is False for value in values):
                return False
            return True if all(value is True for value in values) else None
        if any(value is True for value in values):
            return True
        return False if all(value is False for value in values) else None
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return None
    operator = test.ops[0]
    right = test.comparators[0]
    if isinstance(operator, ast.In | ast.NotIn):
        if not _axis_expression(test.left, enum, known):
            return None
        collection = _member_collection(right)
        if collection is None and isinstance(right, ast.Name):
            resolved = _resolve_literal(module, right.id)
            if resolved is not None and resolved[0] == "collection":
                collection = (resolved[1], resolved[2])
        if collection is None or collection[0] != enum:
            return None
        inside = member in collection[1]
        return inside if isinstance(operator, ast.In) else not inside
    if not isinstance(operator, ast.Is | ast.IsNot | ast.Eq | ast.NotEq):
        return None
    affirmative = isinstance(operator, ast.Is | ast.Eq)
    if isinstance(right, ast.Constant) and right.value is None:
        if not isinstance(test.left, ast.Name) or test.left.id not in nulls:
            return None
        is_null = member in nulls[test.left.id]
        return is_null if affirmative else not is_null
    if isinstance(right, ast.Attribute) and isinstance(right.value, ast.Name):
        if right.value.id != enum or not _axis_expression(test.left, enum, known):
            return None
        same = member == right.attr
        return same if affirmative else not same
    return None


def _guard_names_the_axis(test: ast.expr, enum: str, module: str) -> bool:
    """Whether a guard mentions the axis at all, directly or through a literal."""
    for node in ast.walk(test):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == enum:
                return True
        elif isinstance(node, ast.Name):
            resolved = _resolve_literal(module, node.id)
            if resolved is not None and resolved[1] == enum:
                return True
    return False


def _writes_in(
    node: ast.AST,
    names: dict[str, frozenset[str]],
    statements: dict[str, str],
    parents: dict[ast.AST, ast.AST],
) -> frozenset[str]:
    """The memory tables `node`'s own statements write, by claim 5's rule.

    The same classification `_direct_table_reach` performs, applied to one
    statement rather than to a whole function, and against the same
    function-wide parent map so the two cannot disagree about a chain root.
    """
    found: set[str] = set()
    for child, tables in _table_expressions(node, names):
        if isinstance(child.ctx, ast.Store | ast.Del):
            continue
        cursor: ast.AST = child
        while cursor in parents:
            cursor = parents[cursor]
            if isinstance(cursor, ast.Call):
                root = _chain_root(cursor, statements)
                if root is not None:
                    if STATEMENT_CONSTRUCTORS[root] == "write":
                        found |= tables
                    break
    return frozenset(found)


#: `(module, function, the guard's source)`.
Guard = tuple[str, str, str]


@cache
def _branch_scan(enum: str, member: str) -> tuple[dict[Node, frozenset[str]], frozenset[Guard]]:
    """Per function, the memory tables one member of `enum` can make it write.

    Computed for every node the handlers reach, with the call graph followed a
    statement at a time so a callee inherits the branch it was called from.
    `_promote` writes three tables unconditionally *within itself*; it is the call
    site that is guarded, and that is a fact this walk can only see by keeping the
    statements in order.
    """
    memo: dict[Node, frozenset[str]] = {}
    unreadable: set[Guard] = set()

    def visit(node: Node, stack: frozenset[Node]) -> frozenset[str]:
        if node in memo:
            return memo[node]
        if node in stack:
            return frozenset()
        entry = _nodes().get(node)
        if entry is None:
            return frozenset()
        path, enclosing, function = entry
        module = _module_name(path)
        known = _environment(enclosing, function)
        names = _local_table_names(function, _memory_bindings().get(path, {}))
        statements = _statement_locals(function)
        parents = {
            child: parent for parent in ast.walk(function) for child in ast.iter_child_nodes(parent)
        }
        deeper = stack | {node}
        collected = node in reaching_nodes()

        def expression(source: ast.AST | None) -> frozenset[str]:
            if source is None:
                return frozenset()
            found = set(_writes_in(source, names, statements, parents))
            for call in ast.walk(source):
                if isinstance(call, ast.Call):
                    for callee in _callees(call, module, known):
                        found |= visit(callee, deeper)
            return frozenset(found)

        def block(
            body: list[ast.stmt], nulls: dict[str, frozenset[str]]
        ) -> tuple[frozenset[str], bool]:
            nulls = dict(nulls)
            found: set[str] = set()
            alive = True
            for statement in body:
                if not alive:
                    break
                if isinstance(statement, ast.If):
                    found |= expression(statement.test)
                    decided = _evaluate_guard(
                        statement.test, enum, member, known=known, module=module, nulls=nulls
                    )
                    if (
                        decided is None
                        and collected
                        and _guard_names_the_axis(statement.test, enum, module)
                    ):
                        unreadable.add((module, function.name, ast.unparse(statement.test)))
                    if decided is True:
                        taken, alive = block(statement.body, nulls)
                        found |= taken
                    elif decided is False:
                        taken, alive = block(statement.orelse, nulls)
                        found |= taken
                    else:
                        yes, yes_alive = block(statement.body, nulls)
                        no, no_alive = block(statement.orelse, nulls)
                        found |= yes | no
                        alive = yes_alive or no_alive
                    continue
                if isinstance(statement, ast.Try | ast.TryStar):
                    for part in (statement.body, statement.orelse, statement.finalbody):
                        found |= block(part, nulls)[0]
                    for handler in statement.handlers:
                        found |= block(handler.body, nulls)[0]
                    continue
                if isinstance(statement, ast.With | ast.AsyncWith):
                    for item in statement.items:
                        found |= expression(item.context_expr)
                    found |= block(statement.body, nulls)[0]
                    continue
                if isinstance(statement, ast.For | ast.AsyncFor):
                    found |= expression(statement.iter)
                    found |= block(statement.body, nulls)[0]
                    found |= block(statement.orelse, nulls)[0]
                    continue
                if isinstance(statement, ast.While):
                    found |= expression(statement.test)
                    found |= block(statement.body, nulls)[0]
                    found |= block(statement.orelse, nulls)[0]
                    continue
                if isinstance(statement, ast.Match):
                    found |= expression(statement.subject)
                    for case in statement.cases:
                        found |= block(case.body, nulls)[0]
                    continue
                if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                    # A nested `def` is walked as part of its enclosing function,
                    # for the reason the header above `_edges()` gives, and it
                    # cannot end the enclosing function's flow.
                    found |= block(statement.body, nulls)[0]
                    continue
                target = _assigned_name(statement)
                value = getattr(statement, "value", None)
                if (
                    target is not None
                    and isinstance(value, ast.Subscript)
                    and isinstance(value.value, ast.Name)
                ):
                    resolved = _resolve_literal(module, value.value.id)
                    if (
                        resolved is not None
                        and resolved[0] == "mapping"
                        and resolved[1] == enum
                        and _axis_expression(value.slice, enum, known)
                    ):
                        nulls[target] = resolved[2]
                found |= expression(statement)
                if isinstance(statement, ast.Raise | ast.Return):
                    alive = False
            return frozenset(found), alive

        memo[node] = frozenset()
        result = block(function.body, {})[0]
        memo[node] = result
        return result

    for owner, method in _handlers().values():
        visit(("C", owner, method), frozenset())
    return memo, frozenset(unreadable)


@cache
def branch_writes(enum: str) -> dict[Capability, dict[str, frozenset[str]]]:
    """Per capability, per member of `enum`, the memory tables that branch writes."""
    members = _enum_members(enum) or ()
    found: dict[Capability, dict[str, frozenset[str]]] = {}
    for capability, (owner, method) in _handlers().items():
        split = {
            value: _branch_scan(enum, name)[0].get(("C", owner, method), frozenset())
            for name, value in members
        }
        if any(split.values()):
            found[capability] = split
    return found


@cache
def _branch_axes() -> frozenset[str]:
    """The enums a guard on a memory-reaching path branches an answer on.

    Discovery in two steps, both derived. Every enum whose members a guard
    mentions anywhere the walk reaches a memory row is a candidate — two are, and
    only one of them changes an answer. An enum whose split is uniform for every
    capability is telling this claim nothing that claim 5 did not already say, so
    it is not an axis.
    """
    candidates: set[str] = set()
    for node in reaching_nodes():
        entry = _nodes().get(node)
        if entry is None:
            continue
        path, _enclosing, function = entry
        module = _module_name(path)
        for statement in ast.walk(function):
            if not isinstance(statement, ast.If):
                continue
            for child in ast.walk(statement.test):
                if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
                    if _enum_members(child.value.id) is not None:
                        candidates.add(child.value.id)
                elif isinstance(child, ast.Name):
                    resolved = _resolve_literal(module, child.id)
                    if resolved is not None:
                        candidates.add(resolved[1])
    return frozenset(
        enum
        for enum in candidates
        if any(len(set(split.values())) > 1 for split in branch_writes(enum).values())
    )


@cache
def branching_capabilities(enum: str) -> frozenset[Capability]:
    """The capabilities whose write set is not the same on every branch of `enum`."""
    return frozenset(
        capability
        for capability, split in branch_writes(enum).items()
        if len(set(split.values())) > 1
    )


def test_the_walk_branches_on_the_axis_it_is_declared_to() -> None:
    """The axis is discovered from the guards, and this is the comparison.

    Two enums reach a guard on a memory-reaching path and one of them decides
    nothing, so the discovery is doing work rather than restating a name. If the
    code stops branching on `Disposition`, or starts branching on something else,
    this is where it is argued about — and `RM-API-AC-002`'s per-branch sentences
    move with it.
    """
    axes = _branch_axes()
    assert axes == DECLARED_BRANCH_AXES, (
        f"the walk now splits an answer on {sorted(axes)}, not {sorted(DECLARED_BRANCH_AXES)}. "
        "A new axis is a new way one grant's branches differ from each other, which is "
        "what `RM-API-AC-002` has to disclose per branch"
    )
    for axis in axes:
        members = _enum_members(axis)
        assert members, f"{axis} is a declared branch axis with no members to split on"


def test_the_branch_split_reads_every_guard_it_meets() -> None:
    """Anti-vacuity for claim 10, in the four places it can go quiet.

    The split must find a capability whose branches differ, or it is claim 5 run
    seven times. Its union must be claim 5's own write set, or a branch has been
    lost rather than separated — this is the check that would catch the walk
    silently dropping the promotion. Every guard that names the axis and cannot be
    read must be declared, because an unread guard unions its branches and quietly
    turns an itinerary back into a bound. And no call may hand an axis member to a
    callee, because the split assumes the member in a callee's guards is the one
    the caller was asked about.
    """
    for axis in DECLARED_BRANCH_AXES:
        branching = branching_capabilities(axis)
        declared = frozenset(DECLARED_BRANCH_WRITES.get(axis, {}))
        assert branching == declared, (
            f"{sorted(capability.value for capability in branching ^ declared)} writes "
            f"different tables on different {axis} branches without a declared split, or "
            "declares one and no longer branches"
        )
        assert branching, f"no capability's writes differ by {axis}; the split found nothing"
        for capability, split in branch_writes(axis).items():
            union = frozenset[str]().union(*split.values())
            declared = DECLARED_TABLE_REACH[capability][1]
            assert union == declared, (
                f"{capability.value}'s {axis} branches write {sorted(union)} between them, "
                f"but claim 5 derives {sorted(declared)} for it. A branch has been lost, "
                "not separated, and the per-branch claims below are measuring a shorter walk"
            )
        unreadable = frozenset[Guard]().union(
            *(_branch_scan(axis, name)[1] for name, _value in _enum_members(axis) or ())
        )
        declared_unreadable = frozenset(UNREADABLE_BRANCH_GUARDS.get(axis, {}))
        assert unreadable == declared_unreadable, (
            f"{sorted(unreadable ^ declared_unreadable)} guards a "
            f"memory-reaching path on {axis} in a shape this split cannot read, so its "
            "branches are unioned and the per-branch claim over it is a bound wearing an "
            "itinerary's words"
        )
    # **Scoped to the functions the walk actually reaches**, which is the scope
    # this module states for every other rule about branches: "only guards inside
    # a function that reaches a memory row are collected". It was unscoped while
    # `Disposition` was the only axis, and that cost nothing because the memory
    # review plane is the only place a `Disposition` member is written down.
    # `EntityStatus` is not like that: `EntityStatus.ACTIVE` and
    # `EntityStatus.ARCHIVED` are handed to frozen *record constructors* all over
    # the entity plane -- `Entity(...)`, `_Outcome(...)` -- in functions that
    # reach no memory table at all. Reporting those would be this rule finding a
    # true fact about a call site and drawing a false conclusion about a branch
    # split that never runs there.
    reaching = {(module, enclosing) for module, enclosing, _name in reaching_nodes()}
    handed_on = {
        (module, ast.unparse(call))
        for node, (path, _enclosing, function) in _nodes().items()
        for module in [_module_name(path)]
        if (module, node[1]) in reaching or node in reaching_nodes()
        for call in ast.walk(function)
        if isinstance(call, ast.Call)
        for argument in [*call.args, *(keyword.value for keyword in call.keywords)]
        if isinstance(argument, ast.Attribute)
        and isinstance(argument.value, ast.Name)
        and argument.value.id in DECLARED_BRANCH_AXES
    }
    assert not handed_on, (
        f"{sorted(handed_on)} passes a branch-axis member as an argument from a "
        "function that reaches a memory row. The split assumes the member a callee's "
        "guards ask about is the one the capability was asked about, and a member "
        "handed in at a call site breaks that"
    )


@pytest.mark.parametrize("axis", sorted(DECLARED_BRANCH_AXES))
def test_every_branch_writes_exactly_the_tables_it_declares(axis: str) -> None:
    """The derived per-branch write sets, against the declaration the row restates.

    Exact set equality per member and in both directions. A branch that starts
    writing a table writes it under a grant already issued for the branches beside
    it, which is the disclosure `RM-API-AC-002` is for; a branch that stops leaves
    the row describing a write the code no longer performs.
    """
    derived = {
        capability: split
        for capability, split in branch_writes(axis).items()
        if capability in branching_capabilities(axis)
    }
    declared = DECLARED_BRANCH_WRITES.get(axis, {})
    wrong = [
        f"{capability.value} on {member} writes {sorted(derived[capability][member])}; it is "
        f"declared to write {sorted(declared[capability].get(member, frozenset()))}"
        for capability in sorted(derived, key=lambda member: member.value)
        for member in sorted(set(derived[capability]) | set(declared.get(capability, {})))
        if derived[capability].get(member, frozenset())
        != declared.get(capability, {}).get(member, frozenset())
    ]
    assert not wrong, (
        f"the tables these {axis} branches write are not the tables declared for them. "
        "Update `DECLARED_BRANCH_WRITES` and the matching `RM-API-AC-002` sentences "
        "together, or repair the split if the code did not move:\n" + "\n".join(wrong)
    )


# --- claim 7: the acceptance row's own digits --------------------------------
#
# `test_claimed_test_counts_match_collection.py` is the precedent: parse a
# document's figures and check them against a derived truth. Its lesson is taken
# with its idiom — a pattern that stops matching is a guard that passes over
# nothing, which happened there twice — so the parse asserts what it found before
# anything asserts that what it found is right.

#: `` `review.decide` reads three of the eight (`a`, `b`, `c`) ``. The count is
#: spelled rather than in digits because the prose is spelled throughout, and the
#: tables are carried in the same clause rather than somewhere in the surrounding
#: paragraph: the defect being closed was a *correct* count beside a wrong
#: membership, and a pattern that read only the number would have passed it.
#:
#: **`of the eight` ends on a word boundary.** Without one it also matched the
#: first eight letters of "of the eighteen", a phrase this acceptance package
#: uses of its own criteria. That phrase is outside the parsed row today, so the
#: bug cost nothing and would have cost a loud false failure rather than a silent
#: pass — but "the row happens not to say eighteen" is not a property anyone is
#: maintaining.
#:
#: The capability is optional because the second half of a reach is written with
#: the subject elided — "reads two of the eight (…) and writes none of the
#: eight" — and requiring the name would have bound the read of every capability
#: here and the write of none. That is the precedent module's own lesson about
#: punctuation, in a different costume: a pattern that insists on one spelling
#: silently guards the sentences written the other way.
#:
#: **Only the `writes` half may elide.** The carry-over used to apply to either
#: verb, so a stray `reads` anywhere later in a very long row was attributed to
#: whichever capability was named last and reported as a claim that sentence had
#: never made — a failure message naming text that does not exist is worse than
#: no message, because it sends the reader to the wrong place. A `reads` with no
#: subject of its own now belongs to the document's default subject, which for
#: `RM-API-AC-002` is nothing, and every message quotes the text it matched.
TABLE_SET_CLAIM: Final = re.compile(
    r"(?:`(?P<capability>[a-z_]+(?:\.[a-z_]+)+)`\s+)?(?P<verb>reads|writes)\s+"
    r"(?P<count>[a-z]+)\s+of the eight\b(?:\s*\((?P<tables>[^)]*)\))?"
)

#: `` `review.decide` on `mark_unresolved` writes one of the eight (`a`) ``.
#:
#: Claim 10's sentence, and the subject is never optional in it: a per-branch
#: claim that borrowed its capability from the sentence before it would be the
#: elision defect again, in the one place the row has already been wrong about a
#: branch. Matched *before* `TABLE_SET_CLAIM` and cut out of the text, so
#: "writes one of the eight" inside a branch claim is not also read as a claim
#: about the capability's whole reach — which it would contradict, and should.
BRANCH_WRITE_CLAIM: Final = re.compile(
    r"`(?P<capability>[a-z_]+(?:\.[a-z_]+)+)`\s+on\s+`(?P<member>[a-z_]+)`\s+"
    r"(?P<verb>reads|writes)\s+(?P<count>[a-z]+)\s+of the eight\b"
    r"(?:\s*\((?P<tables>[^)]*)\))?"
)

#: The row spells its numbers, and only these can be meant by "of the eight".
_SPELLED: Final = {
    "none": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
}

_BACKTICKED_TABLE: Final = re.compile(r"`(relationship_memor\w+)`")


@cache
def _acceptance_row() -> tuple[str, int]:
    """The `RM-API-AC-002` row and its line number, so a failure can be found."""
    text = ACCEPTANCE.read_text(encoding="utf-8")
    rows = [
        (line, number)
        for number, line in enumerate(text.splitlines(), start=1)
        if line.startswith(f"| {ROW} ")
    ]
    assert len(rows) == 1, (
        f"{ACCEPTANCE.name} holds {len(rows)} rows starting `| {ROW} `; this guard "
        "reads exactly one"
    )
    return rows[0]


def _documents() -> list[tuple[str, str, str]]:
    """`(label, text, default subject)` for everything parsed for a table set.

    Two sources, because `BEYOND_THE_EIGHT`'s reason strings were the second
    place this repository restated a derived enumeration in unchecked prose — and
    the `review.decide` reason restated the exact false quantifier that blocked
    the correction the row was making. A guard that polices a document and not
    itself has moved the defect one file, not closed it. The reasons default to
    the capability they are keyed by, since a reader has that from the key; the
    row defaults to nothing, so an unattributed claim there fails by name.
    """
    row, line = _acceptance_row()
    # The original row is immutable historical evidence. Its two Phase-B merge
    # clauses are superseded by the additive final-completion delta.
    row = re.sub(
        r"`entities\.merge\.preview` reads three of the eight .*?"
        r"`entities\.merge` reads three of the eight .*?writes none of the eight\.",
        "",
        row,
    )
    row = f"{row} {IDENTITY_ACCESS_DELTA.read_text(encoding='utf-8')}"
    return [
        (f"{ACCEPTANCE.name}:{line}+{IDENTITY_ACCESS_DELTA.name}", row, ""),
        *(
            (f"BEYOND_THE_EIGHT[{capability.value}]", reason, capability.value)
            for capability, reason in BEYOND_THE_EIGHT.items()
        ),
    ]


#: `(label, capability, verb, count word, table list, the text matched)`.
Claim = tuple[str, str, str, str, str | None, str]

#: `(label, capability, member, verb, count word, table list, the text matched)`.
BranchClaim = tuple[str, str, str, str, str, str | None, str]


def _branch_claims_in(label: str, text: str) -> list[BranchClaim]:
    """`(label, capability, member, verb, count, tables, quoted)` for claim 10's sentences."""
    return [
        (
            label,
            match.group("capability"),
            match.group("member"),
            match.group("verb"),
            match.group("count"),
            match.group("tables"),
            match.group(0),
        )
        for match in BRANCH_WRITE_CLAIM.finditer(text)
    ]


def _claims_in(label: str, text: str, default: str) -> list[Claim]:
    """`(label, capability, verb, count, tables, quoted)` for every table-set claim.

    Branch claims are cut out first — replaced by blanks rather than deleted, so
    nothing either side of one is joined into a phrase that was never written.
    An elided subject on a `writes` takes the capability of the claim before it,
    which is what "reads two of the eight and writes none of the eight" means to
    a reader; an elided subject on a `reads` takes the document's default, which
    for the acceptance row is the empty string, so it fails below by name.
    """
    text = BRANCH_WRITE_CLAIM.sub(lambda match: " " * len(match.group(0)), text)
    found: list[Claim] = []
    carried = default
    for match in TABLE_SET_CLAIM.finditer(text):
        explicit = match.group("capability")
        verb = match.group("verb")
        if explicit is not None:
            carried = explicit
            subject = explicit
        else:
            subject = carried if verb == "writes" else default
        found.append(
            (label, subject, verb, match.group("count"), match.group("tables"), match.group(0))
        )
    return found


def _all_claims() -> list[Claim]:
    return [claim for document in _documents() for claim in _claims_in(*document)]


def _all_branch_claims() -> list[BranchClaim]:
    return [
        claim for label, text, _default in _documents() for claim in _branch_claims_in(label, text)
    ]


def test_the_acceptance_row_states_a_table_set_for_every_capability_it_discloses() -> None:
    """Anti-vacuity for claim 7, then the coverage requirement, both derived.

    A regular expression that matched nothing would make the parametrized check
    below a guard over an empty list, which is the exact failure the precedent
    module records twice. So: claims exist, both verbs appear, and — the part
    that is derived rather than a floor — every capability in
    `BEYOND_THE_EIGHT` carries both, in the row *and* in its own reason string.
    Those three are what the row exists to disclose, and they are the three whose
    prose has been wrong.
    """
    _row, line = _acceptance_row()
    for label, text, default in _documents():
        claims = _claims_in(label, text, default)
        assert claims, (
            f"no `` `capability` reads|writes N of the eight `` claim found in {label}; "
            "either it changed shape or this pattern went stale, and a stale pattern here "
            "checks nothing at all"
        )
        assert {verb for _l, _c, verb, _n, _t, _q in claims} == {"reads", "writes"}, (
            f"{label} states only {sorted({verb for _l, _c, verb, _n, _t, _q in claims})}; "
            "a reach is two claims"
        )
    row_claims = _claims_in(*_documents()[0])
    stated = {(capability, verb) for _l, capability, verb, _n, _t, _q in row_claims}
    required = {
        (capability.value, verb) for capability in BEYOND_THE_EIGHT for verb in ("reads", "writes")
    }
    assert required <= stated, (
        f"{sorted(required - stated)} is a capability `RM-API-AC-002` has to disclose "
        f"and {ACCEPTANCE.name}:{line} states no table set for it. The three outside the "
        "eight are the disclosure; leaving one's reach in unparsed prose is how it was "
        "wrong three times"
    )
    for capability, reason in BEYOND_THE_EIGHT.items():
        label = f"BEYOND_THE_EIGHT[{capability.value}]"
        own = {
            verb
            for _l, subject, verb, _n, _t, _q in _claims_in(label, reason, capability.value)
            if subject == capability.value
        }
        assert own == {"reads", "writes"}, (
            f"{label} states {sorted(own)} for its own capability; a reason that names a "
            "table set states both halves of it, in the form this module parses, or states "
            "neither and leaves the enumeration to the row"
        )


def test_the_acceptance_row_states_a_write_set_for_every_branch() -> None:
    """Claim 10's coverage requirement, with the population taken from the code.

    Not a floor and not a list: the capabilities come from
    `branching_capabilities()` and the members off the axis enum's own class body,
    so a disposition added to `Disposition` puts an unstated branch in this set
    and reddens the build. That is the property the previous correction lacked —
    it stated a quantifier over branches, and nothing anywhere counted them.

    **The population it is satisfied by is the acceptance row alone**, which
    `RM-API-AC-002` says of it and this test did not do. It read
    `_all_branch_claims()`, which spans the row *and* `BEYOND_THE_EIGHT`'s reason
    strings, and the `review.decide` reason states the `reject` and
    `mark_unresolved` branches itself — so deleting the `mark_unresolved`
    sentence from the row, or spelling its count in digits, or writing `of the 8`,
    each left this green while the row no longer made the claim the row is cited
    for. Its sibling
    `test_the_acceptance_row_states_a_table_set_for_every_capability_it_discloses`
    already restricted itself to `_documents()[0]`, and the two now agree.

    A branch claim written *inside* a reason string is still parsed and still
    checked against the split by
    `test_every_branch_table_set_a_document_claims_matches_the_walk`, because that
    one is parametrized over both documents. It is checked when present and not
    required to be present, and that asymmetry is deliberate rather than an
    omission: the row is the disclosure `RM-API-AC-002` is cited for, and a reason
    string that chose to say less would be saying less about a claim the row is
    already required to make in full.
    """
    label, text, _default = _documents()[0]
    stated = {
        (capability, member)
        for _l, capability, member, verb, _n, _t, _q in _branch_claims_in(label, text)
        if verb == "writes"
    }
    required = {
        (capability.value, value)
        for axis in DECLARED_BRANCH_AXES
        for capability in branching_capabilities(axis)
        for _name, value in _enum_members(axis) or ()
    }
    assert required, "no capability branches its writes; claim 10's population went empty"
    assert required <= stated, (
        f"{sorted(required - stated)} is a branch whose write set differs from its "
        f"siblings' and {label} states nothing for it. The union is a "
        "bound; a sentence about one disposition is a claim about one branch, and this "
        "row has already shipped one of those that was false. A reason string in "
        "`BEYOND_THE_EIGHT` stating the same branch does not satisfy this: the row is "
        "what `RM-API-AC-002` is cited for"
    )


@pytest.mark.parametrize(
    ("label", "capability", "verb", "count", "tables", "quoted"), _all_claims()
)
def test_every_table_set_a_document_claims_matches_the_walk(
    label: str, capability: str, verb: str, count: str, tables: str | None, quoted: str
) -> None:
    """One claim, against the walk. Count and membership both.

    Every message quotes what was matched, so a claim this parse read differently
    from the way a human reads it sends the reader to the text rather than to a
    sentence the document does not contain.
    """
    members = {member.value: member for member in Capability}
    assert capability in members, (
        f"{label} states a table set for `{capability}`, which is no capability this "
        f"build publishes. The claim read was {quoted!r}"
    )
    assert count in _SPELLED, (
        f"{label} spells `{capability}`'s {verb} count as {count!r}, which this guard "
        f"cannot read. Spell it as one of {sorted(_SPELLED)}. The claim read was {quoted!r}"
    )
    claimed = _SPELLED[count]
    reads, writes = capability_table_reach().get(members[capability], (frozenset(), frozenset()))
    derived = reads if verb == "reads" else writes
    assert claimed == len(derived), (
        f"{label} says `{capability}` {verb} {count} of the eight; the walk derives "
        f"{len(derived)} ({sorted(derived)}). Correct the document rather than this test. "
        f"The claim read was {quoted!r}"
    )
    if claimed == 0:
        assert tables is None, (
            f"{label} says `{capability}` {verb} none of the eight and then lists "
            f"{tables!r}. The claim read was {quoted!r}"
        )
        return
    assert tables is not None, (
        f"{label} says `{capability}` {verb} {count} of the eight and names none of them. "
        f"Put the {claimed} in parentheses after the count — the count was right and the "
        f"membership wrong the last time this row was corrected. The claim read was {quoted!r}"
    )
    named = frozenset(_BACKTICKED_TABLE.findall(tables))
    assert named == derived, (
        f"{label} says `{capability}` {verb} {sorted(named)}; the walk derives "
        f"{sorted(derived)}. Correct the document rather than this test. The claim read "
        f"was {quoted!r}"
    )


@pytest.mark.parametrize(
    ("label", "capability", "member", "verb", "count", "tables", "quoted"), _all_branch_claims()
)
def test_every_branch_table_set_a_document_claims_matches_the_walk(
    label: str,
    capability: str,
    member: str,
    verb: str,
    count: str,
    tables: str | None,
    quoted: str,
) -> None:
    """One per-branch claim, against the split. Member, count and membership."""
    published = {published.value: published for published in Capability}
    assert capability in published, (
        f"{label} states a per-branch table set for `{capability}`, which is no capability "
        f"this build publishes. The claim read was {quoted!r}"
    )
    assert verb == "writes", (
        f"{label} states what `{capability}` {verb} on `{member}`; claim 10 derives writes "
        f"per branch and not reads, so this sentence is bound by nothing. The claim read "
        f"was {quoted!r}"
    )
    axis = next(
        (
            axis
            for axis in DECLARED_BRANCH_AXES
            if member in {value for _name, value in _enum_members(axis) or ()}
        ),
        None,
    )
    assert axis is not None, (
        f"{label} states a table set for `{capability}` on `{member}`, which is no member "
        f"of any declared branch axis ({sorted(DECLARED_BRANCH_AXES)}). The claim read was "
        f"{quoted!r}"
    )
    assert count in _SPELLED, (
        f"{label} spells the `{member}` branch's count as {count!r}, which this guard "
        f"cannot read. Spell it as one of {sorted(_SPELLED)}. The claim read was {quoted!r}"
    )
    claimed = _SPELLED[count]
    derived = branch_writes(axis).get(published[capability], {}).get(member, frozenset())
    assert claimed == len(derived), (
        f"{label} says `{capability}` on `{member}` writes {count} of the eight; the split "
        f"derives {len(derived)} ({sorted(derived)}). Correct the document rather than this "
        f"test. The claim read was {quoted!r}"
    )
    if claimed == 0:
        assert tables is None, (
            f"{label} says `{capability}` on `{member}` writes none of the eight and then "
            f"lists {tables!r}. The claim read was {quoted!r}"
        )
        return
    assert tables is not None, (
        f"{label} says `{capability}` on `{member}` writes {count} of the eight and names "
        f"none of them. The claim read was {quoted!r}"
    )
    named = frozenset(_BACKTICKED_TABLE.findall(tables))
    assert named == derived, (
        f"{label} says `{capability}` on `{member}` writes {sorted(named)}; the split "
        f"derives {sorted(derived)}. Correct the document rather than this test. The claim "
        f"read was {quoted!r}"
    )


def test_no_reason_names_a_memory_table_outside_the_reach_it_describes() -> None:
    """Every table a reason names, in or out of a parsed claim, is one it reaches.

    The claims above bind the enumerations; this binds the prose around them, so a
    reason cannot name `relationship_memory_submissions` in a sentence about
    `review.decide` and have the count beside it still add up.
    """
    for capability, reason in BEYOND_THE_EIGHT.items():
        reads, writes = capability_table_reach().get(capability, (frozenset(), frozenset()))
        named = frozenset(_BACKTICKED_TABLE.findall(reason)) & memory_tables()
        assert named <= reads | writes, (
            f"BEYOND_THE_EIGHT[{capability.value}] names "
            f"{sorted(named - (reads | writes))}, which the walk says it never reaches"
        )


# --- claim 9: the walk has no blind spot on the names that matter ------------


@cache
def _memory_reaching_port_methods() -> dict[str, frozenset[str]]:
    """Per port protocol, the methods whose implementations reach a memory row.

    This is the boundary the application layer actually crosses, and it is where
    an untyped receiver would hide a reach — so it is what claim 5 sweeps for.
    """
    reached = reaching_nodes()
    ports = ast.parse(PORTS.read_text(encoding="utf-8"))
    found: dict[str, frozenset[str]] = {}
    for node in ports.body:
        if not isinstance(node, ast.ClassDef):
            continue
        crossing = frozenset(
            method
            for method in _methods(node)
            for implementation in _implementations(node.name) - {node.name}
            if ("C", implementation, method) in reached
        )
        if crossing:
            found[node.name] = crossing
    return found


def _package(path: Path) -> str:
    """The package a relative import inside `path` is relative to."""
    module = _module_name(path)
    return module if path.name == "__init__.py" else module.rpartition(".")[0]


def _import_source(path: Path, node: ast.ImportFrom) -> str | None:
    """The one module a `from … import …` draws its names out of, absolute.

    `from my_pa.contracts.ports import X` and `from ..contracts.ports import X`
    both answer `my_pa.contracts.ports`. This is the resolution `_import_targets`
    does for the sweep's population, lifted out so `_imported_names` cannot drift
    from it again.
    """
    if node.level == 0:
        return node.module
    parts = _package(path).split(".")
    base = ".".join(parts[: max(len(parts) - node.level + 1, 0)])
    if node.module:
        return f"{base}.{node.module}" if base else node.module
    return base or None


def _import_targets(path: Path, node: ast.Import | ast.ImportFrom) -> frozenset[str]:
    """Every dotted module an import statement names, absolute or relative.

    `from my_pa.contracts.ports import X`, `from my_pa.contracts import ports`,
    `import my_pa.contracts.ports`, `from ..contracts import ports` and
    `from .ports import X` all name the same module and are all returned as
    `my_pa.contracts.ports`. The first spelling was the only one recognised, and
    an independent review reached a repository from a module using the second.
    """
    if isinstance(node, ast.Import):
        return frozenset(alias.name for alias in node.names)
    base = _import_source(path, node) or ""
    return frozenset({base}) | {f"{base}.{alias.name}" for alias in node.names}


@cache
def _port_holding_modules() -> frozenset[str]:
    """Modules naming `contracts.ports` in an import — the ones holding a repository.

    The sweep is scoped to these because the port method names include `search`,
    `get` and `history`, which every dictionary and regular expression in the
    tree also answers to. Scoping by *who could hold a port* rather than by
    which names look distinctive keeps the population derived: a module that
    starts holding a port joins the sweep by importing one.

    Scoped by the module an import *names*, not by the exact string
    `from my_pa.contracts.ports import …`. `from my_pa.contracts import ports`
    reaches the same protocols and, before this, joined no sweep at all — a
    helper taking a repository as an unannotated parameter was invisible to the
    one claim that says the walk is not silently narrow.
    """
    return frozenset(
        _module_name(path)
        for path, tree in _sources()
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        and "my_pa.contracts.ports" in _import_targets(path, node)
    )


def test_the_port_crossings_that_reach_a_memory_row_are_the_two_planes() -> None:
    """Anti-vacuity for claim 5, and a statement worth making on its own.

    Two ports carry the whole reach: the memory repository, which is the plane's
    own, and the review repository, which is the shared capture-plane surface the
    memory plane joined. That second one is the entire content of the
    `review.list` and `review.decide` findings — a capability can reach memory
    rows through a port that has nothing to do with memory in its name.
    """
    crossings = _memory_reaching_port_methods()
    assert set(crossings) == {
        "RelationshipMemoryProposalRepository",
        "RelationshipMemoryRepository",
        "ReviewRepository",
    }, (
        f"the ports reaching a memory row are now {sorted(crossings)}. A fourth one is a "
        "new way for a capability to reach memory without naming it"
    )
    assert crossings["RelationshipMemoryProposalRepository"] == frozenset({"record_proposal"}), (
        "the producer's crossing is now "
        f"{sorted(crossings['RelationshipMemoryProposalRepository'])}; the whole claim about "
        "that port is that it has exactly one method and a producer can call nothing else"
    )
    assert crossings["ReviewRepository"] == frozenset({"cases", "decide"}), (
        f"the review-plane crossings are now {sorted(crossings['ReviewRepository'])}; "
        "`RM-API-AC-002` enumerates exactly these"
    )


def test_no_call_to_a_memory_reaching_port_method_has_an_untyped_receiver() -> None:
    """The walk's own blind spot, asserted rather than assumed away.

    Claim 3 resolves a call by typing its receiver, so a receiver it cannot type
    is a call it does not follow — and an unfollowed call to `summaries_for_context`
    or `cases` would narrow the derived set without anything saying so. Every such
    call in a module that holds a port reference is required to resolve. There are
    none today; a first one is repaired with an annotation, not with an entry here.
    """
    names = {method for methods in _memory_reaching_port_methods().values() for method in methods}
    assert names, "no port method reaches a memory row; the crossing map went empty"
    holders = _port_holding_modules()
    assert len(holders) >= 20, (
        f"only {len(holders)} modules import from `contracts.ports`; the sweep's "
        "population collapsed and it now checks almost nothing"
    )
    untyped: set[tuple[str, str]] = set()
    for _node, (path, enclosing, function) in _nodes().items():
        module = _module_name(path)
        if module not in holders:
            continue
        known = _environment(enclosing, function)
        for call in ast.walk(function):
            if not isinstance(call, ast.Call):
                continue
            called = call.func
            if not isinstance(called, ast.Attribute) or called.attr not in names:
                continue
            if _expression_type(called.value, known) is None:
                untyped.add((module, ast.unparse(called)))
    assert untyped == UNTYPED_PORT_CALL_SITES, (
        f"{sorted(untyped - UNTYPED_PORT_CALL_SITES)} call a port method that reaches a "
        "memory row through a receiver this walk cannot type, so the derived capability "
        "set may be narrower than the truth. Annotate the receiver"
    )


def test_no_reference_to_a_memory_reaching_port_method_escapes_uncalled() -> None:
    """A port method handed around as a value, which no call-site sweep can see.

    `functools.partial(repository.summaries_for_context, …)`, a callback put in a
    registry, `handler = repository.cases` — each reaches a memory row, and in
    none of them is the method ever the `func` of a `Call`, so `_edges()` records
    no edge and the sibling sweep above finds no call site. An independent review
    built one and watched every test here stay green.

    Swept by *name* rather than by shape, so `partial` is not privileged over the
    next construct that takes a callable. The price is one collision with a data
    attribute of the same name, and the price is paid in a declaration that says
    which one and why rather than in a narrower rule.
    """
    names = {method for methods in _memory_reaching_port_methods().values() for method in methods}
    ports = frozenset[str]().union(
        *(_implementations(port) for port in _memory_reaching_port_methods())
    )
    holders = _port_holding_modules()
    escaping: set[tuple[str, str]] = set()
    for _node, (path, enclosing, function) in _nodes().items():
        module = _module_name(path)
        if module not in holders:
            continue
        known = _environment(enclosing, function)
        called = {id(call.func) for call in ast.walk(function) if isinstance(call, ast.Call)}
        for reference in ast.walk(function):
            if not isinstance(reference, ast.Attribute) or reference.attr not in names:
                continue
            if id(reference) in called:
                continue
            owner = _expression_type(reference.value, known)
            if owner is None or owner in ports:
                escaping.add((module, ast.unparse(reference)))
    assert escaping == frozenset(UNCALLED_PORT_METHOD_REFERENCES), (
        f"{sorted(escaping ^ frozenset(UNCALLED_PORT_METHOD_REFERENCES))} names a port "
        "method that reaches a memory row without calling it, so the walk records no "
        "edge and the derived capability set may be narrower than the truth. Call it "
        "through a name this walk can follow, or declare why it is not one"
    )


def test_no_dispatch_through_a_subscript_hides_a_memory_reach() -> None:
    """The codebase's own dispatch idiom, declared rather than assumed away.

    `_HANDLERS[command.capability](…)` is how this application routes every
    request, and `_edges()` cannot follow it: the call's `func` is a `Subscript`,
    which has neither a name to resolve nor a receiver to type. A second table of
    callables — `_MEMORY_READS["ctx"](repository, …)` — would reach memory rows
    and appear in no derived set, and an independent review demonstrated exactly
    that.

    Two exist, both declared with what they dispatch to. The claim is not that
    the idiom is absent; it is that each use of it has been read.
    """
    holders = _port_holding_modules()
    found: set[tuple[str, str]] = set()
    for _node, (path, _enclosing, function) in _nodes().items():
        module = _module_name(path)
        if module not in holders and _relative(path) not in MEMORY_SQL_MODULES:
            continue
        for call in ast.walk(function):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Subscript):
                found.add((module, ast.unparse(call.func)))
    assert found == frozenset(DISPATCH_THROUGH_A_SUBSCRIPT), (
        f"{sorted(found ^ frozenset(DISPATCH_THROUGH_A_SUBSCRIPT))} dispatches a call "
        "through a subscript in a module that holds a port or builds memory SQL. This "
        "walk follows no such call, so anything it reaches is missing from the derived "
        "sets. Say what it dispatches to, or route it through a name"
    )


def test_no_attribute_named_by_a_string_hides_a_memory_reach() -> None:
    """`getattr(repository, "summaries_for_context")` — a reach spelled as data.

    Neither sibling sweep above can see one. It is not an `Attribute`, so the
    uncalled-reference sweep finds no name; its `func` is `getattr` rather than
    the method, so `_edges()` records no edge and the untyped-receiver sweep has
    no receiver to fail to type. An independent review built one inside a
    port-importing module — inside the declared population, past every claim —
    and watched every one of the eighteen tests this module then held stay green.

    A *literal* name that a memory-reaching port declares is a redness with no
    registry entry available: the repair is to call the method. A *computed* name
    cannot be read at all, and the five that exist are declared with what they
    look up, so the claim about them is that they have been read rather than that
    a sixth could not hide a reach. This docstring and the module docstring both
    said four while `DYNAMIC_ATTRIBUTE_LOOKUPS` held five.
    """
    names = {method for methods in _memory_reaching_port_methods().values() for method in methods}
    assert names, "no port method reaches a memory row; the crossing map went empty"
    holders = _port_holding_modules()
    found: set[tuple[str, str]] = set()
    for _node, (path, _enclosing, function) in _nodes().items():
        module = _module_name(path)
        if module not in holders and _relative(path) not in MEMORY_SQL_MODULES:
            continue
        for call in ast.walk(function):
            if not isinstance(call, ast.Call):
                continue
            if not (isinstance(call.func, ast.Name) and call.func.id == "getattr"):
                continue
            if len(call.args) < 2:
                continue
            attribute = call.args[1]
            if (
                isinstance(attribute, ast.Constant)
                and isinstance(attribute.value, str)
                and attribute.value not in names
            ):
                continue
            found.add((module, ast.unparse(call)))
    assert found == frozenset(DYNAMIC_ATTRIBUTE_LOOKUPS), (
        f"{sorted(found ^ frozenset(DYNAMIC_ATTRIBUTE_LOOKUPS))} names an attribute with a "
        "string in a module that holds a port or builds memory SQL. If the name is a port "
        "method that reaches a memory row, call it through a name this walk can follow; if "
        "it is computed, say what it can look up"
    )


def _docstrings(tree: ast.Module) -> frozenset[int]:
    """The identity of every docstring node, which discusses tables rather than reaching one."""
    return frozenset(
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    )


def test_no_string_constant_names_a_memory_table_outside_the_declarations() -> None:
    """A table reached by its name rather than by its `Table` object.

    `connection.execute(text("SELECT statement_text FROM relationship_memory_versions"))`
    reads a memory row, and every claim in this module is blind to it: there is no
    `Table` object for `_memory_bindings()` to bind, so the module does not join
    claim 2's census, no function joins the reaching set, and no capability's
    derived table set moves. An independent review wrote one and every one of the
    eighteen tests this module then held stayed green.
    `metadata.tables["relationship_memories"]` — the fourth import spelling this
    module's docstring used to carry as an open escape — is the same hole with
    different punctuation, and the same sweep closes it.

    The population is every string constant in the package, matched on the
    schema's own table names at word boundaries, which is why an index name like
    `relationship_memories_by_subject` is not a hit and `FROM relationship_memories`
    is. `tables.py` is excluded, as it is from claim 2, because declaring a table
    means naming it; docstrings are excluded because four of them discuss the
    tables by name, and prose about a table is the documentation working.
    """
    tables = memory_tables()
    pattern = re.compile(r"(?<!\w)(" + "|".join(sorted(tables)) + r")(?!\w)")
    found: set[tuple[str, int, str]] = set()
    for path, tree in _sources():
        if path == DECLARATIONS:
            continue
        docstrings = _docstrings(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if id(node) in docstrings or not pattern.search(node.value):
                continue
            found.add((_relative(path), node.lineno, node.value[:120]))
    assert found == RAW_SQL_TABLE_MENTIONS, (
        f"{sorted(found ^ RAW_SQL_TABLE_MENTIONS)} names one of the eight inside a string. "
        "If it is SQL, the statement reaches a memory row past every claim in this module; "
        "build it from the `Table` object instead"
    )
