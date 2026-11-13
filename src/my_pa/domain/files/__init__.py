"""The file workspace plane (`files.*`, ADR-019): the pure domain half.

Stdlib and domain only: nothing here reads a row, a clock or a file, or imports
an application or infrastructure module. The frozen input is
`docs/architecture/files-workspace-contract.md`.

`vocabulary` holds the section 8 limits and the section 7 reason tokens;
`paths` the section 3 path rules; `versions` the entry kinds and `fv1_` version
tokens; `transfer` the ticket tokens, upload declaration, offset and header
grammars, `Range` parsing and write intent digests; `errors` the refusals,
none of which carries the value it refused.
"""
