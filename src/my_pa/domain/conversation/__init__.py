"""Conversation events seeded from a capture.

`docs/specs/quick-capture/09_LOGICAL_DATA_MODEL.md:202-224` makes a Conversation
a first-class specialized event, and requires an explicit Conversation Log to
seed a *skeletal* event while a conversation inferred from a Quick Note stays a
proposal. That difference is the whole reason this package exists: the two need
a mode discriminator at the moment the capture is created, because a Quick Note
may never be relabelled a Conversation Log afterwards.

**The discriminator is the row, not a column.** `09_LOGICAL_DATA_MODEL.md:53`
specifies a `capture_kind` on the capture itself, and adding one is refused:
`captures` is emitted by already-merged revision `1a4c9e77b2d5`, and the freeze
that protects that revision replaces only its named check constraints — columns,
foreign keys, unique constraints and indexes are still read off the live
declaration, so a new column there changes what a merged revision emits. A
conversation-log create writes a `capture_conversations` row in the same
transaction as the capture instead, and the presence of that row *is* the mode.
One new table rather than a column on a merged one, and no capture can acquire
the mode later.

`ConversationParticipant` is deferred with evidence rather than built. It
requires a participant to bind either an entity or an `unresolved_mention_text`,
and this repository has already refused to store surface text beside a span —
the span re-derives on read, so a second copy would be a fourth place capture
content sits. There is also no person mention to bind: the frozen entity-type
vocabulary admits documents, projects and URLs, and people and organisations
were excluded because they need an alias table that does not exist. No
acceptance criterion straddles the boundary, so the deferral is a partition
rather than a gap.
"""
