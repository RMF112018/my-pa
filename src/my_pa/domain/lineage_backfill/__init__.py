"""The record lineage S3 backfill dry run's vocabulary (S3 contract sections 3 and 8.3).

Kept beside `domain.lineage` rather than inside it: the dry run classifies the
native shapes legacy rows carry -- a Task's follow-up, a Constraint
relationship, a Meeting's Series, a Project link, an origin reference -- which
the lineage traversal itself never reads (S2 contract: a Series is native
metadata and never propagates). Pure data.
"""
