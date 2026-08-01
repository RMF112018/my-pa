# MCV source-provider fixtures

`root/` is the synthetic source tree the fixture `SourceProvider` reads in the
MCV read-only vertical slice. Everything under it was invented for this test
corpus: no personal data, no real person, project, organisation, or address, and
nothing copied from the migrated legacy corpus or from any live source.

The tree exists to exercise provider behaviour, so its shape is the point:

| Path | Purpose |
|---|---|
| `root/handbook.pdf` | a media type that is reported but not extracted here; extraction is a later work package and `P00-OD-003` is open |
| `root/notes.md` | `text/markdown`, one of the two supported baseline types |
| `root/opaque.bin` | an unsupported type, and deliberately not valid UTF-8, so a provider that silently coerced or skipped it would be visible |
| `root/readme.txt` | `text/plain`, the other supported baseline type |
| `root/nested/` | proves `list_children` returns immediate children only |
| `root/nested/deeper/log.txt` | two levels down, so a recursive listing of the root would surface it and fail the test |

`handbook.pdf` carries a PDF header and trailer and is not a renderable
document. It is a media-type fixture, not a parser fixture; nothing in this work
package opens it as a PDF.

No symlink is committed here. The escaping-symlink cases are built in `tmp_path`
at test time by `tests/security/test_containment_denial.py`: a symlink that
resolves outside the repository is a hazard to carry in a checkout, and not every
checkout or archive preserves one faithfully, which would silently turn a
containment test vacuous.
