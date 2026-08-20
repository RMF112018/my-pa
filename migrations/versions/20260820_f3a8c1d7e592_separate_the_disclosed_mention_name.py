"""Separate the mention name the queue discloses from the form it matches on.

`entities.unresolved_mentions` published `entity_observations.normalized_value`,
and an independent review established that this is not the boundary it reads as.
`normalize_name` casefolds and turns punctuation into spaces; it removes **no
content**. A writer that sets the matched form to `normalize_name(<raw lifted
text>)` therefore publishes that text with its dots turned into spaces --
``"A. Chen <a.chen@northwind.test>"`` becomes ``"a chen a chen northwind test"``,
local part and domain intact -- and the result is `is_normalized_name`-true, so
no predicate over the stored string can tell it from a long legitimate name.

The mitigation for that was a sentence on the port telling writers to supply an
extracted name. This revision replaces the sentence with a column.

`mention_display_name` is nullable and defaults to NULL. The queue reads it and
nothing else, and `normalized_value` becomes internal to matching. Three
properties follow, none of which prose could give:

* a writer that does nothing deliberate discloses **nothing** -- the failure
  mode of forgetting is an empty field rather than a published mail envelope;
* disclosing requires an affirmative write into a column whose name states what
  it is for, so "did anyone mean to publish this?" is answerable;
* an auditor greps one column's writers instead of every producer of a matched
  form.

Additive, over zero rows: nothing in `src/` writes `entity_observations`, so
there is no backfill and no existing value is reclassified. That is why it is
taken now -- after ingestion lands it is a data-migration question about text
that has already been stored, and the answer stops being free.

No capability, no purpose, and no closed set moves.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a8c1d7e592"
down_revision: str | None = "e4d7b2f9a316"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "knowledge"


def upgrade() -> None:
    op.add_column(
        "entity_observations",
        sa.Column("mention_display_name", sa.Text(), nullable=True),
        schema=SCHEMA,
    )
    # Bounded for the reason every other free-text column here is: a column with
    # no ceiling is a column an ingester can put a document in.
    op.create_check_constraint(
        "a_disclosed_mention_name_is_bounded",
        "entity_observations",
        "mention_display_name IS NULL OR ("
        "mention_display_name ~ '[^[:space:]]' "
        "AND mention_display_name = btrim(mention_display_name) "
        "AND length(mention_display_name) BETWEEN 1 AND 200)",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "a_disclosed_mention_name_is_bounded",
        "entity_observations",
        type_="check",
        schema=SCHEMA,
    )
    op.drop_column("entity_observations", "mention_display_name", schema=SCHEMA)
