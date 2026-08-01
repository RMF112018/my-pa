"""Scan text artefacts for personal data (OD-004, P10-AC-06).

The campaign's standing rule is that counts, table names, column names, type
names, error codes, and stable identifiers may be written down and values may
not. This module is the check on that rule, run over the evidence tree, the
migration documentation, and the reconciliation report itself.

Two properties matter more than breadth.

*A finding never quotes what it found.* A scanner that printed the email address
it caught would put the address in the very artefact that is supposed to be
clean. So a finding carries a path, a line number, and a pattern name, and
nothing else.

*The local account name is discovered, not hard-coded.* Writing the owner's
username into a source file would be the same violation this scans for, so the
token comes from the home directory at runtime and is matched on a word
boundary.

The patterns are deliberately narrow and mechanical. There is no attempt to
detect a personal name in free text: that needs a judgement a regular expression
cannot make, and claiming otherwise would report a clean scan that means less
than it appears to. What this catches is the machine-shaped identifiers -- mail
addresses, telephone numbers, and absolute home-directory paths -- and the
report says so plainly.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

#: Extensions the scan reads. Everything else is skipped and counted, because
#: reading an arbitrary binary as text produces noise rather than findings.
TEXT_SUFFIXES = frozenset({".md", ".json", ".txt", ".py", ".yml", ".yaml", ".csv", ".sql", ".toml"})

#: Directories never worth scanning: build state, not authored artefacts.
SKIPPED_DIRECTORIES = frozenset({".git", "__pycache__", ".mypy_cache", ".pytest_cache", ".venv"})

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "EMAIL_ADDRESS",
        re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    ),
    (
        # North-American shapes with a separator. A bare run of ten digits is not
        # matched: SHA prefixes, byte counts, and row counts would all trip it.
        "PHONE_NUMBER",
        re.compile(r"(?<![\d-])(?:\+1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?![\d-])"),
    ),
    (
        "HOME_DIRECTORY_PATH",
        re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+"),
    ),
)


@dataclass(frozen=True)
class Finding:
    """One suspected disclosure. Carries no matched text, by construction."""

    path: str
    line: int
    pattern: str


@dataclass(frozen=True)
class ScanResult:
    """What a scan looked at and what it found."""

    roots: tuple[str, ...]
    files_scanned: int
    files_skipped: int
    findings: tuple[Finding, ...]
    patterns: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not self.findings


def local_account_pattern(home: Path) -> tuple[str, re.Pattern[str]] | None:
    """Return a pattern matching the local account name, discovered at runtime.

    Returns ``None`` for a home directory whose name is too short or too generic
    to match without swamping the report in false positives.
    """
    name = home.name
    if len(name) < 4 or not name.isalnum():
        return None
    return ("LOCAL_ACCOUNT_NAME", re.compile(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])"))


def patterns(*, home: Path | None = None) -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Return the pattern set, including the runtime-discovered account name."""
    discovered = local_account_pattern(Path.home() if home is None else home)
    return _PATTERNS if discovered is None else (*_PATTERNS, discovered)


def _files(root: Path) -> Iterator[Path]:
    if root.is_file():
        yield root
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if SKIPPED_DIRECTORIES.intersection(path.parts):
            continue
        yield path


def scan_text(
    label: str, text: str, rules: Sequence[tuple[str, re.Pattern[str]]]
) -> tuple[Finding, ...]:
    """Return every finding in `text`, attributed to `label`."""
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for name, pattern in rules:
            if pattern.search(line):
                findings.append(Finding(path=label, line=number, pattern=name))
    return tuple(findings)


def scan(
    roots: Iterable[Path],
    *,
    base: Path,
    home: Path | None = None,
) -> ScanResult:
    """Scan every text file under `roots`, reporting paths relative to `base`."""
    rules = patterns(home=home)
    findings: list[Finding] = []
    scanned = 0
    skipped = 0
    seen: set[Path] = set()
    labels: list[str] = []
    for root in roots:
        labels.append(str(root.relative_to(base)) if root.is_relative_to(base) else root.name)
        for path in _files(root):
            if path in seen:
                continue
            seen.add(path)
            if path.suffix not in TEXT_SUFFIXES:
                skipped += 1
                continue
            scanned += 1
            label = str(path.relative_to(base)) if path.is_relative_to(base) else path.name
            findings.extend(
                scan_text(label, path.read_text(encoding="utf-8", errors="replace"), rules)
            )
    return ScanResult(
        roots=tuple(labels),
        files_scanned=scanned,
        files_skipped=skipped,
        findings=tuple(findings),
        patterns=tuple(name for name, _ in rules),
    )
