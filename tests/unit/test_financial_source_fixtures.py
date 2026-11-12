"""Financial controlled source F-1: synthetic fixtures, their manifest and goldens (section 8).

Every fixture file and the manifest are pinned byte for byte by
`FIXTURE_FILE_SHA256` (S5a precedent); the directory holds exactly the 23 named
files, the 52 malformed files and the manifest. Every section 8.5 golden runs
end to end -- fixture bytes, parser, `admit_source_run`, evaluator -- and must
equal the manifest's golden and the overview the I11-A domain inputs give
(`tests/fixtures/financial_domain.py`), so the 2 packages agree byte for byte.
Fixtures are read with `Path.read_bytes()` only; the writer is never called.
"""

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import Final

import pytest

from my_pa.domain.project_controls.financial.canonical import loads_canonical, overview_sha256
from my_pa.domain.project_controls.financial.model import SourceRun
from my_pa.domain.project_controls.financial.reportability import (
    admit_source_run,
    evaluate_financial_overview,
)
from my_pa.infrastructure.financial.synthetic_csv import (
    BOM,
    HEADER_COLUMNS,
    parse_synthetic_finance,
)
from tests.fixtures.financial_domain import (
    DESIGNATION_A,
    DESIGNATION_C,
    REFUSALS,
    VERSIONS,
    file_sha256,
    scenario,
)

ROOT: Final = Path(__file__).resolve().parents[2]
FIXTURES: Final = ROOT / "tests" / "fixtures" / "financial_source"
WRITER: Final = ROOT / "tests" / "fixtures" / "financial_source_writer.py"
#: Section 8.1 (R11-F10): the byte-exactness rule, or its documented fallback.
GITATTRIBUTES_RULE: Final = (
    "tests/fixtures/financial_source/** -text whitespace=-blank-at-eol,-blank-at-eof,"
    "-space-before-tab,-indent-with-non-tab,-tab-in-indent"
)
GITATTRIBUTES_FALLBACK: Final = "tests/fixtures/financial_source/** binary"
_IDENTIFIER_COLUMNS: Final = (
    "ref",
    "source_system",
    "source_version_ref",
    "approved_by",
    "supersedes_ref",
    "external_project_id",
    "external_contract_id",
    "cost_code",
    "wbs_package",
    "transfer_ref",
)
_SYNTHETIC: Final = re.compile(r"\A(syn|SYN)-")
#: A malformed cell keeps its synthetic stem behind the 1 refused character.
_SYNTHETIC_MUTATED: Final = re.compile(r"\A[=+\-@\t\"]?(syn|SYN)[- ]")

#: Every fixture file and the manifest (section 8.1); frozen by I11-B (F1-U06).
FIXTURE_FILE_SHA256: Final[dict[str, str]] = {
    "malformed/amount_grammar__exponent.csv": (
        "262c197114a003010c904dd891289ddc88a28e3299cae30f3c82e51bee4c5b54"
    ),
    "malformed/amount_grammar__formula.csv": (
        "a32f3608581f5e9b3cae6252ce3acc6f9be6e27f33853146c68b4aedbf001f21"
    ),
    "malformed/amount_grammar__leading_zero.csv": (
        "2dab89ea4443d918433e04be8b275fc6f5940792a4ab6ce82937dc6bfaa0e08f"
    ),
    "malformed/amount_grammar__plus.csv": (
        "7d32375d932f4152d163284d6f65f7e7187cba74b777e0e5e8d265e11e8fc384"
    ),
    "malformed/amount_negative_zero__base.csv": (
        "82a45a9db1986d23468c4a691d813c7e3dea25ea221b06ac6093218682491a3a"
    ),
    "malformed/amount_range__base.csv": (
        "b0faa24fca709fd40fe852c92099a7d4a9f03bb3078b7c6757ee758c7dee4dab"
    ),
    "malformed/amount_scale__base.csv": (
        "20d2ee59d95ac362f070b13e342b24348f196eceac360699fc91999b8fd5d0bd"
    ),
    "malformed/amount_sign__base.csv": (
        "adf7255064296cf2c8eb0b3900fb59700711e145a5b40a0f7783dc905c7bf132"
    ),
    "malformed/bom_present__base.csv": (
        "3697ccfefb7ef7f5060386fdb59c0e6bf33677f01d5aa468d2476b92d5b7ea83"
    ),
    "malformed/carriage_return__crlf.csv": (
        "74490c2c8c7da4542af0446e2ae22f48c344992867a0476b3c524073ca6065d8"
    ),
    "malformed/cell_missing__cost_code.csv": (
        "6519390553ffbe2e897f4aaa1ddeaa1c1f1283192b851f711594969d90569a4e"
    ),
    "malformed/cell_not_empty__measure.csv": (
        "7766cd190dcd9d84ee5fbb4aa8133ea49250be2f92b3c49275a4dd961c076c9e"
    ),
    "malformed/cell_too_long__base.csv": (
        "3d2a6ddc44dc44ebf9077c5137275a724e30f174739f70c4beaf913db7de4843"
    ),
    "malformed/change_order_zero__base.csv": (
        "e5648abb90b13398ffe6c504c358a80d1ba8601d932e50db338f6cd1546e528b"
    ),
    "malformed/control_character__tab.csv": (
        "19b763d9be9478b00b432b11950bdd25c3d0b9d5f180eca77d71ab2f51456aeb"
    ),
    "malformed/count_grammar__base.csv": (
        "a46985e175aac29fbeaba098923fd268580aef0aa385fa9f76d0818bb645cdbd"
    ),
    "malformed/currency_grammar__lowercase.csv": (
        "0f106404a8818e7e1cd58c2a90df635479433ce3e134001677f2c3376e06019a"
    ),
    "malformed/currency_unknown__base.csv": (
        "d2b5e049bc07145bc60d4d1f54bdcd50bb490b2ca45a33848bc21f8685fb1b8c"
    ),
    "malformed/cutoff_before_period__base.csv": (
        "645b8230ae065f47d367b9ca94255833bb1ec156c48f29d3ec37bdaef2b4eb61"
    ),
    "malformed/digest_grammar__base.csv": (
        "44400819d283bc8f9113a8bc5f4062a599a1a0601659f2ac07cd56cad8fe9a59"
    ),
    "malformed/duplicate_column__base.csv": (
        "e890f04a3a971b86fa8ac85d2166ae8e8de16e44ad14667b3cf737266a468e81"
    ),
    "malformed/duplicate_ref__base.csv": (
        "cd771a81a1058bee2e1470b2078d26c876b9affe5d7e16ad2fa10d8e4700c65e"
    ),
    "malformed/empty_input__base.csv": (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    ),
    "malformed/enum_value__perspective.csv": (
        "53dabba1f96f3176b298a21abba1688d25ab35963f243bc75207878d4eb683eb"
    ),
    "malformed/field_count__thousands.csv": (
        "2b5b46cb30827d34e250ef61ed9633f8accbdb300d71c3f9aba557c77692f7fb"
    ),
    "malformed/format_unrecognized__base.csv": (
        "065afe8dd1710dfdfc2ae4d9c3a70545cc77c87b085a7fd85ff83a38431398a2"
    ),
    "malformed/formula_injection__at.csv": (
        "6d5551b4b8914f99b22f9ce8b8c77f09e4eebcd1f21ba4df850b3042c9e891c2"
    ),
    "malformed/formula_injection__equals.csv": (
        "e1e4c0d71dd6f584e87d9f36ff97c50a6dd2c36e07b2f62d1b8525d634aba440"
    ),
    "malformed/formula_injection__minus.csv": (
        "0b9f34eb62c2655883f05c659ce62ff801ee73ea5ee373728ee0dd87261ae1ea"
    ),
    "malformed/formula_injection__plus.csv": (
        "cc5a4b921c68afdd5b21baac607d1d4a2e2ce1fe43ddb6f888b21ca60582d106"
    ),
    "malformed/header_mismatch__order.csv": (
        "6137839f18f1b3679264e53a89834880032dacf7f8e6896eec49b5ee010a9eb1"
    ),
    "malformed/identifier_grammar__space.csv": (
        "30ffc45808217cde1d4d00d53d906bfa42cc2f0167b4f9813df6e024564d9837"
    ),
    "malformed/line_currency_mismatch__base.csv": (
        "a6c51d268918acc8361a0ae1b5b94e50b5f867a96370ad937bdccc7c69ae98b4"
    ),
    "malformed/measure_perspective_mismatch__base.csv": (
        "7361f250561b6f44c3a1f9108c3b03c1b975601d44b0f97780d44a8347d5d9f2"
    ),
    "malformed/non_ascii__cell.csv": (
        "877e5f2ae03018a33774f0debf35b7e739d296b25a326e41df8810c1908bbad2"
    ),
    "malformed/partial_export__count.csv": (
        "59554cf587a44799b0e857f6960c799fb4d76160a379d0617e755bb1700304ec"
    ),
    "malformed/partial_export__no_final_lf.csv": (
        "229689ed779717e6787652844808594e81d26043f6f28fd2078f90829cd06f56"
    ),
    "malformed/period_grammar__base.csv": (
        "6892a2203fa7f56c114083afcc42a21fd95b62401852a9f49be110838d4206d9"
    ),
    "malformed/quote_character__quoted.csv": (
        "2de6ab320e86304dd198e3b436429377500d7e2d82ec57b3bfafb0ac5d302f14"
    ),
    "malformed/record_type_unknown__base.csv": (
        "919990f44bce2d0ef4ea4e57690fea6f47e1a701378c64c95bbc694580c33dfe"
    ),
    "malformed/source_version_duplicate__base.csv": (
        "26a65040266aa2edf0c62a028f7c7f07ce6be6b57e97caaf22149850a7f08de8"
    ),
    "malformed/source_version_not_first__base.csv": (
        "40d3e3a567d744df14a5dda21fc769df3161b72ded156f154886b347cbb20d03"
    ),
    "malformed/supersedes_self__base.csv": (
        "0d48d925fbbe9ad38196447da6d62e3bdf0dc195dab03a162777f717381d8803"
    ),
    "malformed/timestamp_grammar__offset.csv": (
        "d1e02e143e172fdc47c2d94112da91a1cb398b68bd393401f89d5e98fd3d7e54"
    ),
    "malformed/transfer_leg_count__base.csv": (
        "208fb5d604af9e6b28fb17ab688c0fe66789f4a42bb0d9e06b3f0ada309e7c49"
    ),
    "malformed/transfer_leg_sides__base.csv": (
        "2b6a7cc56b04de4298d295457b779717fd2eb10a845db73304a2d73068352c39"
    ),
    "malformed/transfer_leg_sign__base.csv": (
        "02e79f6f63791e1bdbc65f63fd3ccbdec5b64876921d10f64c7129f0695bffc4"
    ),
    "malformed/transfer_same_project__base.csv": (
        "8c63d2e46741819878dcf88f2f9beba00dde2d195730720e8483f7f2a4c0eae0"
    ),
    "malformed/transfer_scope_mismatch__base.csv": (
        "47a1e13762c152e78a9fdcd13f81321175179bba94ce7955a9474223697fc67f"
    ),
    "malformed/transfer_status_mismatch__base.csv": (
        "cefb72b86e14badfa4380962dba4ecaa4414fbdfbad12efee1ac67ec7013f0a3"
    ),
    "malformed/transfer_unbalanced__base.csv": (
        "a67f235e86b27b688725994d6480ec2ed6b21670ee08e452c86c8bef70f99e77"
    ),
    "malformed/withdrawal_has_rows__base.csv": (
        "a872283f90b71568ce15e2313fb41fb103ccf5c8bb5c865d3914cb96bdd83c0a"
    ),
    "manifest.json": ("106a9262c6b87b3c8115b8125e540865239fcbb34e80df05c55199c5364871a2"),
    "syn_at020_owner_budget.csv": (
        "3cce099d9e72cf358671783f6c17905497d65ce4b5c2ea1f0daff4226b726503"
    ),
    "syn_contract_perspective.csv": (
        "d1175d515ad1ee3460f9def3235dc55e9f91abddf1e38a53e105a31e54cd55d5"
    ),
    "syn_cycle_a.csv": ("f3f85e69f8515e270f0a77742141e0f7d601c7727fb897eabf3dfcaa886a034f"),
    "syn_cycle_b.csv": ("c7caabc51f0ab1ee49a332cce3e18116fe1475da7ab0716945e72786030286fb"),
    "syn_duplicate_identity.csv": (
        "cb0f0ab149c1bae6aad373e3c1b28a33abb1d7af5aa15c3edf5e44e854059974"
    ),
    "syn_eac_conflict.csv": ("fb104a1ba65975cef823ad80dbb5294ccd348cf6d8e177f467f6d256b00a1a1a"),
    "syn_p200_eur.csv": ("b0b016dbbed1da1a549983b47ae73b3ac02cd84540484d2f1ba066e4b90ecdf2"),
    "syn_p300_second_system.csv": (
        "3696961024d0634e927dad97ea4b3082f1999d0469b576ca4095df58b140a679"
    ),
    "syn_partial_export.csv": ("b9711a80c40cce0c82a5992475a41be18e65d328f01ddabdc08deb4da6fb8642"),
    "syn_period_2026_11.csv": ("1dee3152fb547f0d8087d649b5a6dbd2586ffd5e530e23c82a56a18816c3f4e9"),
    "syn_proposed.csv": ("45d478c7e0177bc8622a43ece863ae1a3703cf2f6021df485dab91a71bebba18"),
    "syn_reconciliation_failure.csv": (
        "942d76603d532d020daa311ca057efa307ff44118ee5e026cb2537b668e9e951"
    ),
    "syn_rounding_edges.csv": ("7cc6a9f0ba8f4c2fab071dfdec611aa778037cee4503b89c226f1c582f788106"),
    "syn_second_system.csv": ("e147cbfde98e09efb8a02cb3d2bdecbe67bf25f01103475be8d1983806b4e363"),
    "syn_spoofed_system.csv": ("d63a45b6d1d884ff8a3a61ccfc4b8dccc1af3b76161314d9f7591f367a7aa9f9"),
    "syn_spoofed_system_b.csv": (
        "c154e9a2091df7724d842bf3d53e391569343f127611f1024ba76ed8cef41f47"
    ),
    "syn_stale_approval.csv": ("8215d4baffe4237ab979a9f362875cf7b7516ddce5045c9b5599da9883a6f271"),
    "syn_tampered_body.csv": ("d63120a36a94bb4cabea9403682c8f4d7aa848c8684fbfeab163d06f4e9517bd"),
    "syn_unknown_actor.csv": ("39da78e9d523cdc2eb9e2d102ec1677b6a3ee52ab2440393e3992ef0545a9376"),
    "syn_version_conflict.csv": (
        "618c85f6e62720819c0a77acb3bb8875266c59ec9d900d47b7d968ba3c8db581"
    ),
    "syn_version_conflict_late.csv": (
        "a0ba7527c3ca04fd400237b891fe5a1cc7c793bb54404dc71fd19f2399300822"
    ),
    "syn_withdrawal.csv": ("65f28fa9d41713d309acccdbc8c173ae052c903a20f2ff8c7912d54322d0a33c"),
    "syn_withdrawal_dangling.csv": (
        "4284b64022d60147bdcf8cc153d8185c8eb6e7bcc7ded6e49249ddf498efa6e5"
    ),
}


def _manifest() -> dict[str, object]:
    manifest = loads_canonical((FIXTURES / "manifest.json").read_bytes())
    assert isinstance(manifest, dict)
    return manifest


def _files() -> dict[str, dict[str, object]]:
    files = _manifest()["files"]
    assert isinstance(files, dict)
    return files


def _on_disk() -> set[str]:
    return {p.relative_to(FIXTURES).as_posix() for p in FIXTURES.rglob("*") if p.is_file()}


def test_fixture_files_match_their_pinned_sha256() -> None:
    mismatched = [
        name
        for name, digest in sorted(FIXTURE_FILE_SHA256.items())
        if hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() != digest
    ]
    assert mismatched == []
    for name, entry in _files().items():
        data = (FIXTURES / name).read_bytes()
        assert entry["file_sha256"] == FIXTURE_FILE_SHA256[name], name
        assert entry["size"] == len(data), name


def test_fixture_directory_equals_the_manifest() -> None:
    on_disk = _on_disk()
    assert on_disk == set(FIXTURE_FILE_SHA256)
    assert on_disk == set(_files()) | {"manifest.json"}
    malformed = {name for name in on_disk if name.startswith("malformed/")}
    named = on_disk - malformed - {"manifest.json"}
    assert (len(named), len(malformed), len(on_disk)) == (23, 52, 76)
    assert all(name.startswith("syn_") and name.endswith(".csv") for name in named)
    keys = {str(entry["domain_key"]) for entry in _files().values() if "domain_key" in entry}
    assert keys == set(VERSIONS) | set(REFUSALS)
    manifest = _manifest()
    assert manifest["format"] == "my-pa-synthetic-finance-v1"
    raw = (FIXTURES / "manifest.json").read_bytes()
    assert raw.endswith(b"}\n") and raw.isascii()


# --- every section 8.5 golden, end to end from the fixture bytes ----------------------

_DESIGNATIONS: Final = {d.source_system: d for d in (DESIGNATION_A, DESIGNATION_C)}


def _file_of_domain_key() -> dict[str, str]:
    return {
        str(entry["domain_key"]): name for name, entry in _files().items() if "domain_key" in entry
    }


def _from_fixture(domain_run: SourceRun, names: dict[str, str]) -> SourceRun:
    """The run the I11-A scenario builds, rebuilt from its fixture file through the parser."""
    stand_ins = {file_sha256(key): key for key in names}
    data = (FIXTURES / names[stand_ins[domain_run.file_sha256]]).read_bytes()
    outcome = parse_synthetic_finance(data)
    rebuilt = admit_source_run(
        domain_run.run_ref,
        domain_run.run_sequence,
        _DESIGNATIONS[domain_run.designated_source_system],
        outcome.file_sha256,
        outcome,
    )
    assert rebuilt.file_sha256 == hashlib.sha256(data).hexdigest()
    assert (rebuilt.outcome, rebuilt.refusal_code, rebuilt.refusal_line) == (
        domain_run.outcome,
        domain_run.refusal_code,
        domain_run.refusal_line,
    )
    assert rebuilt.content_sha256 == domain_run.content_sha256
    return rebuilt


@pytest.mark.parametrize("number", range(1, 44))
def test_every_scenario_matches_its_golden(number: int) -> None:
    goldens = _manifest()["scenarios"]
    assert isinstance(goldens, dict) and len(goldens) == 43
    golden = goldens[f"S{number:02d}"]
    chosen = scenario(number)
    names = _file_of_domain_key()
    runs = [_from_fixture(run, names) for run in chosen.runs]
    overview = evaluate_financial_overview(
        chosen.request, chosen.designations, runs, chosen.mappings, chosen.quarantine
    )
    assert overview.reportability.value == golden["reportability"]
    assert [r.value for r in overview.reasons] == golden["reasons"]
    assert [r.value for r in overview.program_reasons] == golden["program_reasons"]
    assert overview_sha256(overview) == golden["overview_sha256"]
    # The fixture path and the I11-A domain path give the same overview, field for field.
    assert overview == chosen.evaluate()


# --- synthetic data, the writer, byte exactness ---------------------------------------


def _identifier_cells(data: bytes) -> list[str]:
    text = data.removeprefix(BOM).decode("utf-8").replace("\r", "")
    cells: list[str] = []
    for line in text.split("\n")[2:]:
        row = line.split(",")
        if len(row) == len(HEADER_COLUMNS):
            cells += [
                row[HEADER_COLUMNS.index(c)]
                for c in _IDENTIFIER_COLUMNS
                if row[HEADER_COLUMNS.index(c)]
            ]
    return cells


def test_fixture_identifiers_are_synthetic() -> None:
    offenders: list[str] = []
    checked = 0
    for name in sorted(_on_disk() - {"manifest.json"}):
        pattern = _SYNTHETIC_MUTATED if name.startswith("malformed/") else _SYNTHETIC
        for cell in _identifier_cells((FIXTURES / name).read_bytes()):
            checked += 1
            if pattern.match(cell) is None:
                offenders.append(f"{name}: {cell!r}")
    assert checked > 1000
    assert offenders == []
    # Native ids anywhere in the tree are the 3 synthetic Projects only.
    for name in sorted(_on_disk()):
        data = (FIXTURES / name).read_bytes()
        assert set(re.findall(rb"prj_\w+", data)) <= {
            b"prj_SYNTHETIC0000000001",
            b"prj_SYNTHETIC0000000002",
            b"prj_SYNTHETIC0000000003",
        }


def test_no_test_calls_the_fixture_writer() -> None:
    offenders: list[str] = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        if path == WRITER or "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or "", *(alias.name for alias in node.names)]
            elif isinstance(node, ast.Name | ast.Attribute):
                names = [node.id if isinstance(node, ast.Name) else node.attr]
            if any("financial_source_writer" in name for name in names):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
    writer = ast.parse(WRITER.read_text(encoding="utf-8"))
    entry_points = {node.name for node in writer.body if isinstance(node, ast.FunctionDef)} & {
        "write",
        "main",
    }
    assert entry_points == {"write", "main"}


def test_fixtures_are_not_text_normalised() -> None:
    rules = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert GITATTRIBUTES_RULE in rules or GITATTRIBUTES_FALLBACK in rules
    crlf = (FIXTURES / "malformed" / "carriage_return__crlf.csv").read_bytes()
    assert crlf.count(b"\r\n") == crlf.count(b"\n") == 19
    assert b"\t" in (FIXTURES / "malformed" / "control_character__tab.csv").read_bytes()
    assert (FIXTURES / "malformed" / "bom_present__base.csv").read_bytes().startswith(BOM)
    no_lf = (FIXTURES / "malformed" / "partial_export__no_final_lf.csv").read_bytes()
    assert no_lf and not no_lf.endswith(b"\n")
    assert (FIXTURES / "malformed" / "empty_input__base.csv").read_bytes() == b""
    deliberate = {
        "malformed/carriage_return__crlf.csv",
        "malformed/partial_export__no_final_lf.csv",
        "malformed/empty_input__base.csv",
    }
    for name in sorted(_on_disk() - deliberate):
        data = (FIXTURES / name).read_bytes()
        assert data.endswith(b"\n") and b"\r" not in data, name
