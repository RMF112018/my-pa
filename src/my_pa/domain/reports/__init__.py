"""The general report plane: reports a caller authors and versions in `my-pa`.

Distinct from the Intelligence Artifact plane (`rpt`/`rrc`), whose reports a
producer cycle commits. This package is the pure domain half and stdlib only:
nothing here reads or writes a row, talks to a clock or imports an application
or infrastructure module.

`vocabulary` holds the frozen bounds and enumerations the schema restates as
literals; `values` the validators for every caller-supplied field; `lifecycle`
the pure archive / delete / restore transition rule; `catalog` the WP04 plane
selector, catalog filters, bound keyset cursor and search-text projection;
`errors` the refusals,
none of which carries the value it refused.
"""
