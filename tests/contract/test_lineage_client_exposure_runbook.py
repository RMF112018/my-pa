"""Record lineage P1: the runbook's client-exposure statements equal the code (FAST).

Client exposure contract (`docs/architecture/record-lineage-client-exposure-contract.md`)
sections 6.2-6.5 and 10 (DV-10): the operator's P2 procedure lives in
`ops/runbooks/remote-mcp-cloudflare.md`, section "Record lineage client exposure (P1)",
and every value an operator would copy out of it is pinned here, fail closed in both
directions:

* the documented restricted-profile opt-in value is exactly the admissible set,
  appears exactly once, is labelled documentation only, and refuses to start a
  process whose database profiles are off;
* the 2 environment blocks name real `Settings` fields whose code defaults are
  off, carry no opt-in or database-profile variable, and equal the contract's
  section 6.3 blocks;
* the grant table is exactly the 34 exposed names with their one ChatLLM purpose
  and write flag; the companion table is exactly the family reads and composite
  native grants a 34-only client lacks;
* none of the 6 section 6.5 files states `chatllm-data-v9` as the current
  profile, and none offers a grant on a withheld lineage name.

The expected sets are derived from the code (the service's switch sets, the
lineage vocabulary, the opt-in contract), never from the runbook. What it cannot
prove: that an operator runs the commands in the stated order, or that the
production environment matches the block (the P2 read-only recon does that).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from my_pa.application.chatllm_data_profile import chatllm_grant_purpose
from my_pa.application.service import (
    _COMPOSITE_NATIVE_GRANTS,
    _LINEAGE_CAPABILITIES,
    _PROGRAM_REPORTING_CAPABILITIES,
)
from my_pa.bootstrap.settings import ENV_PREFIX, Settings, SettingsError, load_settings
from my_pa.contracts.mcp_database_profiles import MCP_PROFILE_OPT_IN_CAPABILITY_NAMES
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    CHATLLM_DATA_PROFILE_VERSION,
    ChatLLMCapabilityClass,
)
from my_pa.domain.identity.operation import (
    Capability,
    is_write_capability,
    permitted_purposes,
)
from my_pa.domain.lineage.vocabulary import (
    ATTESTED_LINEAGE_WRITE_CAPABILITIES,
    LINEAGE_BACKFILL_CAPABILITIES,
    LINEAGE_FAMILY_READS,
    RecordFamily,
)

ROOT: Final = Path(__file__).resolve().parents[2]
RUNBOOK: Final = ROOT / "ops" / "runbooks" / "remote-mcp-cloudflare.md"
CONTRACT: Final = ROOT / "docs" / "architecture" / "record-lineage-client-exposure-contract.md"
#: Contract section 6.5: every file whose profile-version or exposure statements P1 moves.
SECTION_65_FILES: Final = (
    "ops/runbooks/remote-mcp-cloudflare.md",
    "ops/runbooks/gateway-operations.md",
    "ops/runbooks/mcp-and-cli-operations.md",
    "ops/runbooks/managed-knowledge-context.md",
    "docs/operations/mcv-limitations.md",
    "docs/operations/record-lineage-client-guidance.md",
)
SECTION_HEADING: Final = "## Record lineage client exposure (P1)"
OPT_IN_VARIABLE: Final = f"{ENV_PREFIX}MCP_DATABASE_PROFILE_OPT_INS"
DOCUMENTATION_ONLY: Final = "**Documentation only — do not set.**"
GRANT_HEADER: Final = "| Canonical capability | Purpose | Write |"
COMPANION_HEADER: Final = "| Companion | Purpose | Write | Needed for |"
_A_URL: Final = "postgresql+psycopg://synthetic@db.invalid/my_pa"
#: Placeholders only: the profile validator checks presence and shape, never reads them.
_PROFILE_SETTINGS: Final = {
    f"{ENV_PREFIX}DATABASE_URL": _A_URL,
    f"{ENV_PREFIX}MCP_DATABASE_PROFILES_ENABLED": "true",
    f"{ENV_PREFIX}MCP_DATABASE_RO_PASSWORD_FILE": "/synthetic/ro/password",
    f"{ENV_PREFIX}MCP_DATABASE_RW_PASSWORD_FILE": "/synthetic/rw/password",
    f"{ENV_PREFIX}MCP_DATABASE_EXPECTED_CLUSTER_ID": "7000000000000000001",
}


def _members(names: frozenset[str]) -> frozenset[Capability]:
    return frozenset(capability for capability in Capability if capability.value in names)


#: The 7 withheld names and the 34 exposed ones, derived as the policy test derives them.
WITHHELD: Final = _members(ATTESTED_LINEAGE_WRITE_CAPABILITIES | LINEAGE_BACKFILL_CAPABILITIES)
EXPOSED: Final = (_LINEAGE_CAPABILITIES - WITHHELD) | _PROGRAM_REPORTING_CAPABILITIES


def _section(text: str, heading: str) -> str:
    """The text from `heading` to the next heading of the same level."""
    level = heading.split(" ", 1)[0]
    start = text.index(f"\n{heading}\n")
    end = text.find(f"\n{level} ", start + len(heading) + 1)
    return text[start : end if end != -1 else len(text)]


def _p1_section() -> str:
    return _section(RUNBOOK.read_text(encoding="utf-8"), SECTION_HEADING)


def _table(text: str, header: str) -> list[list[str]]:
    """The body rows of the one table under `header`, cells stripped."""
    lines = text.splitlines()
    assert lines.count(header) == 1, f"expected exactly 1 table headed {header!r}"
    first = lines.index(header)
    rows: list[list[str]] = []
    for line in lines[first + 2 :]:
        if not line.startswith("| "):
            break
        rows.append([cell.strip() for cell in line.strip().strip("|").split(" | ")])
    assert rows, f"the table headed {header!r} has no rows"
    return rows


def _fenced_blocks(text: str, language: str) -> list[list[str]]:
    """The non-empty lines of every fenced block of `language`, in order."""
    return [
        [line for line in block.splitlines() if line.strip()]
        for block in re.findall(rf"^```{language}\n(.*?)^```$", text, re.M | re.S)
    ]


def _env_blocks(text: str) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    for lines in _fenced_blocks(text, "env"):
        block: dict[str, str] = {}
        for line in lines:
            name, separator, value = line.partition("=")
            assert separator == "=", line
            assert name not in block, name
            block[name] = value
        blocks.append(block)
    return blocks


def _canonical_opt_in_value() -> str:
    return ",".join(sorted(MCP_PROFILE_OPT_IN_CAPABILITY_NAMES))


def _documented_opt_in_lines() -> list[str]:
    return [
        line
        for line in RUNBOOK.read_text(encoding="utf-8").splitlines()
        if line.startswith(f"{OPT_IN_VARIABLE}=")
    ]


# ---- the opt-in value ------------------------------------------------------------


def test_the_documented_opt_in_value_equals_the_admissible_set() -> None:
    (line,) = _documented_opt_in_lines()
    value = line.partition("=")[2]
    # Exact string equality: sorted, comma-joined, no spaces, nothing extra.
    assert value == _canonical_opt_in_value()
    names = value.split(",")
    assert set(names) == MCP_PROFILE_OPT_IN_CAPABILITY_NAMES
    assert len(names) == len(set(names)) == 31
    # Never a withheld name, a Program read or the manifest (S4 D-46, S3.1 D-21).
    assert not set(names) & {capability.value for capability in WITHHELD}
    assert not {"programs.members.resolve", "programs.overview", "reports.manifest"} & set(names)
    # The contract's section 6.2 value is the same string.
    contract = [
        line
        for line in CONTRACT.read_text(encoding="utf-8").splitlines()
        if line.startswith(f"{OPT_IN_VARIABLE}=")
    ]
    assert contract == [line]


def test_the_documented_opt_in_value_needs_the_database_profiles() -> None:
    (line,) = _documented_opt_in_lines()
    value = line.partition("=")[2]
    # The deployed shape (profiles off): the process refuses to start.
    with pytest.raises(SettingsError, match="require MCP database profiles"):
        load_settings({f"{ENV_PREFIX}DATABASE_URL": _A_URL, OPT_IN_VARIABLE: value})
    # With the profiles on (placeholder files and cluster id) it is accepted whole.
    settings = load_settings({**_PROFILE_SETTINGS, OPT_IN_VARIABLE: value})
    assert settings.mcp_database_profile_opt_in_set() == MCP_PROFILE_OPT_IN_CAPABILITY_NAMES


def test_the_documented_opt_in_line_occurs_exactly_once_and_is_labelled_documentation_only() -> (
    None
):
    lines = _documented_opt_in_lines()
    assert len(lines) == 1, f"{len(lines)} opt-in value lines in {RUNBOOK.name}"
    section = _p1_section()
    assert lines[0] in section.splitlines(), "the opt-in value is outside the P1 section"
    # The value sits in a `text` block, never an `env` block an operator would paste.
    (block,) = [block for block in _fenced_blocks(section, "text") if lines[0] in block]
    assert block == [lines[0]]
    # The label precedes the value inside the same subsection.
    subsection = _section(section, "### The restricted-profile opt-in value (documentation only)")
    assert subsection.index(DOCUMENTATION_ONLY) < subsection.index(lines[0])
    assert "not part of the P2" in subsection


# ---- the environment blocks ------------------------------------------------------


def test_the_documented_env_blocks_name_real_settings_whose_defaults_are_off() -> None:
    blocks = _env_blocks(_p1_section())
    assert len(blocks) == 2, "expected the remote MCP and gateway env blocks"
    remote, gateway = blocks
    fields = Settings.model_fields
    for block in blocks:
        for name, value in block.items():
            assert name.startswith(ENV_PREFIX), name
            field = name[len(ENV_PREFIX) :].lower()
            assert field in fields, f"{name} names no Settings field"
            # Every switch the block turns on is default-off in code.
            assert fields[field].default is False, name
            assert value == "true", name
            # No restricted-profile variable is ever part of the P2 environment.
            assert not name.startswith(f"{ENV_PREFIX}MCP_DATABASE_"), name
        # A real Settings load accepts the block (no unknown MY_PA_ name).
        settings = load_settings({f"{ENV_PREFIX}DATABASE_URL": _A_URL, **block})
        assert settings.lineage_enabled
        assert settings.mcp_database_profile_opt_in_set() == frozenset()
    assert set(remote) == {
        f"{ENV_PREFIX}LINEAGE_ENABLED",
        f"{ENV_PREFIX}PROGRAM_REPORTING_ENABLED",
        f"{ENV_PREFIX}LINEAGE_BACKFILL_ENABLED",
        f"{ENV_PREFIX}REMOTE_WRITES_ENABLED",
    }
    assert set(gateway) == set(remote) - {f"{ENV_PREFIX}REMOTE_WRITES_ENABLED"}
    # The runbook's blocks are the contract's section 6.3 blocks, in order.
    contract = CONTRACT.read_text(encoding="utf-8")
    assert (
        _env_blocks(
            _section(
                contract, "### 6.3 Production environment block (names and values; no secrets)"
            )
        )
        == blocks
    )


# ---- the grant and companion tables ----------------------------------------------


def test_the_documented_grant_table_equals_the_v10_lineage_set() -> None:
    rows = _table(_p1_section(), GRANT_HEADER)
    documented: dict[Capability, tuple[str, str]] = {}
    for row in rows:
        assert len(row) == 3, row
        capability = Capability(row[0])
        assert capability not in documented, capability
        documented[capability] = (row[1], row[2])
    assert set(documented) == EXPOSED
    assert len(documented) == 34
    writes = 0
    for capability, (purpose, write) in documented.items():
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is ChatLLMCapabilityClass.DATA_CONDITIONAL, capability
        assert permitted_purposes(capability) == {purpose}, capability
        assert chatllm_grant_purpose(capability).value == purpose, capability
        assert write == ("yes" if is_write_capability(capability) else "no"), capability
        writes += write == "yes"
    assert writes == 16
    # The contract's section 3 table states the same purpose and kind per name.
    section_3 = CONTRACT.read_text(encoding="utf-8").split("## 3. Exposure table", 1)[1]
    for capability, (purpose, write) in documented.items():
        kind = "W" if write == "yes" else "R"
        assert f"| `{capability.value}` | {kind} | `{purpose}` |" in section_3, capability


def _expected_companions() -> dict[Capability, tuple[str, bool]]:
    expected: dict[Capability, tuple[str, bool]] = {}
    for family, reads in LINEAGE_FAMILY_READS.items():
        if family is RecordFamily.SITUATION:
            continue  # issues.read / issues.list are among the 34
        for name in reads:
            capability = Capability(name)
            expected[capability] = (chatllm_grant_purpose(capability).value, False)
    for native, purpose in _COMPOSITE_NATIVE_GRANTS.values():
        expected[native] = (purpose.value, True)
    return expected


def test_the_documented_companion_table_equals_the_family_reads_and_composite_grants() -> None:
    documented: dict[Capability, tuple[str, bool]] = {}
    for row in _table(_p1_section(), COMPANION_HEADER):
        assert len(row) == 4, row
        names = re.findall(r"`([^`]+)`", row[0])
        assert names, row
        (purpose,) = re.findall(r"`([^`]+)`", row[1])
        assert row[2] in {"yes", "no"}, row
        for name in names:
            capability = Capability(name)
            assert capability not in documented, capability
            documented[capability] = (purpose, row[2] == "yes")
    expected = _expected_companions()
    assert documented == expected
    for capability, (purpose, write) in documented.items():
        assert permitted_purposes(capability) == {purpose}, capability
        assert is_write_capability(capability) is write, capability
        assert capability not in EXPOSED, capability
    # The contract's section 6.4 table is the same table.
    assert _table(CONTRACT.read_text(encoding="utf-8"), COMPANION_HEADER) == _table(
        _p1_section(), COMPANION_HEADER
    )


# ---- the 6 section 6.5 files -----------------------------------------------------

#: The only ways a section 6.5 file may still name v9: as history ("since v9",
#: "v9 adds", "v9's ...", "a client converged on v9").
_V9: Final = "chatllm-data-v9"
_V10: Final = "chatllm-data-v10"
_V9_HISTORICAL: Final = re.compile(
    r"since `chatllm-data-v9`|`chatllm-data-v9` adds|`chatllm-data-v9`'s|"
    r"converged on `chatllm-data-v9`"
)


@pytest.mark.parametrize("path", SECTION_65_FILES)
def test_the_runbooks_state_the_v10_profile_version(path: str) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    # The version the runbooks state is the version the code plans.
    assert CHATLLM_DATA_PROFILE_VERSION == _V10
    assert _V10 in text, f"{path} never states {_V10}"
    # Strip the historical forms; any v9 left is a current-version statement.
    current = _V9_HISTORICAL.sub("", text)
    assert _V9 not in current, f"{path} still states {_V9} as current: " + repr(
        current[max(current.index(_V9) - 80, 0) : current.index(_V9) + 40]
    )


_WITHHELD_NAMES: Final = tuple(sorted(capability.value for capability in WITHHELD))
_TABLE_ROW: Final = re.compile(r"^\|\s*`?([a-z0-9_.]+)`?\s*\|", re.M)


def test_no_runbook_offers_a_withheld_lineage_grant() -> None:
    assert len(_WITHHELD_NAMES) == 7
    for path in SECTION_65_FILES:
        text = (ROOT / path).read_text(encoding="utf-8")
        # No table row is headed by a withheld name.
        rows = set(_TABLE_ROW.findall(text))
        assert not rows & set(_WITHHELD_NAMES), (path, rows & set(_WITHHELD_NAMES))
        # No `grant` command names one.
        for name in _WITHHELD_NAMES:
            assert re.search(rf"--capability[\s\\]+{re.escape(name)}(?![\w.])", text) is None, (
                path,
                name,
            )
    # The full-inventory paragraph names all 7 as never granted.
    runbook = RUNBOOK.read_text(encoding="utf-8")
    start = runbook.index("For a full inventory, reconcile the ordinary profile first.")
    paragraph = runbook[start : runbook.index("\n\n", start)]
    for name in _WITHHELD_NAMES:
        assert f"`{name}`" in paragraph, name
    assert "**never** part of an inventory grant" in paragraph
    # So does the P1 section.
    section = _p1_section()
    for name in _WITHHELD_NAMES:
        assert f"`{name}`" in section, name
    assert "Never grant a withheld name" in section
