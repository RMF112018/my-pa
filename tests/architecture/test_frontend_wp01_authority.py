from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "docs" / "plans" / "frontend-acceptance-ledger.md"
AUTHORITY = ROOT / "docs" / "plans" / "frontend-implementation-authority.md"
ADR_011 = ROOT / "docs" / "decisions" / "ADR-011-passkey-webauthn-authentication-and-opaque-server-sessions.md"
ADR_004 = ROOT / "docs" / "decisions" / "ADR-004-mossaic-frontend-nextjs-app-router.md"
ADR_008 = ROOT / "docs" / "decisions" / "ADR-008-nas-runtime-topology.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_frontend_ledger_represents_exactly_pfe_ac_001_through_250() -> None:
    text = _text(LEDGER)
    start = text.index("## ID universe — exactly 250 records")
    end = text.index("## Source reference table", start)
    ids = re.findall(r"PFE-AC-(\d{3})", text[start:end])

    assert len(ids) == 250
    assert len(set(ids)) == 250
    assert ids == [f"{number:03d}" for number in range(1, 251)]


def test_frontend_ledger_never_defaults_unknown_to_pass() -> None:
    text = _text(LEDGER)
    assert "| `implementation_disposition` | `UNRECONCILED` |" in text
    assert "Unknown is not pass" in text or "unknown is not pass" in text
    assert "FINAL_WP02_RECONCILIATION_MISSING" in text
    assert "UNRECONCILED_ACCEPTANCE_MAPPING_123_139" in text


def test_browser_native_mossaic_chatllm_is_explicitly_superseded() -> None:
    ledger = _text(LEDGER)
    authority = _text(AUTHORITY)
    expected = {
        "089",
        "090",
        "185",
        "186",
        "187",
        "188",
        "189",
        "190",
        "224",
        "225",
    }
    start = ledger.index("## Explicit current supersession overrides")
    end = ledger.index("## Known evidence limitations", start)
    actual = set(re.findall(r"PFE-AC-(\d{3})", ledger[start:end]))

    assert expected <= actual
    assert "BROWSER_NATIVE_MOSSAIC_CHATLLM_FRONTEND = SUPERSEDED" in authority
    assert "ChatLLM interaction begins from the ChatLLM UI" in authority


def test_auth_target_is_passkey_opaque_session_server_principal_without_runtime_overclaim() -> None:
    adr = _text(ADR_011)
    authority = _text(AUTHORITY)

    assert "WebAuthn/passkey" in adr
    assert "opaque random server-side session identifier" in adr
    assert "browser never selects or supplies the authoritative Principal" in adr
    assert "Microsoft Entra/MSAL is not the normal production application-authentication target" in adr
    assert "production browser shared secret or `local_operator` sign-in is not an approved recovery fallback" in adr
    assert "does not claim the replacement runtime is implemented" in adr
    assert "Current implementation truth versus target" in authority
    assert "still supports `synthetic | entra | local_operator`" in authority


def test_prior_adrs_preserve_non_auth_architecture_while_marking_auth_supersession() -> None:
    adr_004 = _text(ADR_004)
    adr_008 = _text(ADR_008)

    assert "partially superseded by ADR-011" in adr_004.lower()
    assert "Next.js App Router" in adr_004
    assert "same-origin BFF" in adr_004
    assert "browser-authentication selection partially superseded" in adr_008
    assert "NAS/process placement" in adr_008
    assert "non-authentication topology provisions remain accepted" in adr_008
