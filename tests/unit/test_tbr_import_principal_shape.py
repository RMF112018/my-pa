"""WP-RE-08 MR-10: the legacy import's `--principal` is the durable bound form.

`apps/cli/tbr_import.py` is the one enumerated exception to Amendment 02 (1): the
only path where an operator-typed principal reaches Record Event staging. MR-10
narrows it: the value must be `prn_` + exactly 32 lowercase hex characters, the
output shape of `capture_principal_id`, so it names a durable identity-plane
partition and never an arbitrary token.

FAST: the refusal happens in `_check_identifiers`, before settings are loaded or
any database is opened, so no test here touches one.
"""

from __future__ import annotations

import argparse
import uuid
from pathlib import Path

import apps.cli.tbr_import as tool
import pytest

from my_pa.application.constraint_legacy_import import LegacyImportError
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID, capture_principal_id

PROJECT = "prj_" + "a" * 32


def _args(principal: str) -> argparse.Namespace:
    return argparse.Namespace(principal=principal, project_id=PROJECT, register_id="tbr-register")


@pytest.mark.parametrize(
    "principal",
    [capture_principal_id(LOCAL_OPERATOR_UUID), capture_principal_id(uuid.uuid4())],
    ids=["local-operator", "account"],
)
def test_the_bound_form_is_accepted(principal: str) -> None:
    tool._check_identifiers(_args(principal))


@pytest.mark.parametrize(
    "principal",
    [
        "prn_tbrimportoperator01",  # a valid `IdKind.PRINCIPAL`, but not the bound form
        "prn_" + "A" * 32,  # uppercase hex: a second spelling of one partition
        "prn_" + "a" * 31,  # one short
        "prn_" + "a" * 33,  # one long
        "prn_" + "g" * 32,  # not hex
    ],
    ids=["unbound", "uppercase", "short", "long", "not-hex"],
)
def test_any_other_principal_is_refused(principal: str) -> None:
    with pytest.raises(LegacyImportError) as refused:
        tool._check_identifiers(_args(principal))
    assert refused.value.code == "principal_shape"


def test_the_cli_refuses_an_unbound_principal_before_reading_anything(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = tool.main(
        [
            "dry-run",
            "--source",
            str(tmp_path / "absent.xlsm"),
            "--sheet",
            "Register",
            "--project-id",
            PROJECT,
            "--principal",
            "prn_tbrimportoperator01",
            "--register-id",
            "tbr-register",
            "--output",
            str(tmp_path / "out"),
        ]
    )
    assert code == tool.EXIT_FAILED
    assert capsys.readouterr().err.strip() == "failed: principal_shape"
    assert not (tmp_path / "out").exists()
