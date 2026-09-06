"""Reusable CI fixtures and Playwright snapshots must stay synthetic.

This is a narrow static guard, not a DLP product. It fails when tracked frontend
test/snapshot text contains obvious personal-account patterns. It does not scan
the whole repository and does not authorize live data.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOTS = (
    REPO / "web/e2e",
    REPO / "web/src",
)

FORBIDDEN = re.compile(
    r"(?i)(@gmail\.com|@yahoo\.com|bobbyfetting@)",
)


def test_frontend_fixtures_do_not_embed_personal_accounts() -> None:
    hits: list[str] = []
    for root in ROOTS:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".ts", ".tsx", ".json", ".md"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if FORBIDDEN.search(text):
                rel = path.relative_to(REPO)
                hits.append(str(rel))
    assert hits == [], f"personal-account pattern in frontend fixtures: {hits}"
