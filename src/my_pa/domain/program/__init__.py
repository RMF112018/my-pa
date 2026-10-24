"""Program reporting (record lineage S4; ADR-015, S4 contract sections 3 and 5).

The exact Program-to-Project membership rule, the server-batched Program
metrics and their reportability, and the overview digest. Pure: nothing here
reads a database, persists or grants. `vocabulary` holds the closed sets every
other S4 module names; the membership, reportability and digest modules are
added by their workers (S4 contract section 9).
"""
