"""The one home of the files workspace audit vocabulary (files-workspace contract 1.1, 1.2).

Revision `640aaacc78e8` (WP4) restates `capability_is_known` and
`purpose_is_known` with the 17 `files.*` capability names and the 2 files
purposes. The domain enums gain the same names in WP5, so between the two the
head audit vocabulary is the domain's **union** these sets; every head-equality
test spells that as `declared | FILES_CAPABILITIES` (and an earlier revision's
`declared - FILES_CAPABILITIES`), which holds both before and after WP5.
Frozen literals copied from the contract, never derived from the enums they are
checked against. This is a helper module, not a test module: pytest does not
collect it.
"""

from __future__ import annotations

from typing import Final

#: The new head revision and the revision it is additive on.
FILES_WORKSPACE_REVISION: Final = "640aaacc78e8"
FILES_WORKSPACE_PREVIOUS: Final = "b77334135653"

FILES_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "files.workspaces.list",
        "files.list",
        "files.stat",
        "files.search",
        "files.preview",
        "files.history",
        "files.download.begin",
        "files.mkdir",
        "files.copy",
        "files.upload.begin",
        "files.upload.abort",
        "files.rename",
        "files.move",
        "files.trash",
        "files.restore",
        "files.upload.finalize",
        "files.write_text",
    }
)
FILES_PURPOSES: Final[frozenset[str]] = frozenset(
    {"file_workspace_authoring", "file_workspace_read"}
)
