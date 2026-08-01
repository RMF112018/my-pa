"""Extraction domain: derived text, quarantine, and coverage.

Three modules, one rule between them: a thing that did not become text says so,
and says it as itself. `text` produces derived text bound to the observed
version; `quarantine` records that processing stopped and why, without recording
what stopped it; `coverage` states how much of a named enrollment was covered at
a named snapshot, including what was left out.

`docs/specs` section 12 is explicit that unsupported and malformed media are
reported explicitly and never as empty text, and that the ten coverage states are
distinct with none collapsing into "empty". Nothing here returns an empty string
to mean a failure.
"""
