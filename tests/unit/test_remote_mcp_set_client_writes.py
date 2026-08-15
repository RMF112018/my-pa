"""The operator CLI can toggle an existing client's writes_enabled flag."""

from __future__ import annotations

import pytest
from apps.cli.remote_mcp import main


def test_set_client_writes_is_a_supported_command() -> None:
    with pytest.raises(SystemExit) as raised:
        main(["set-client-writes", "--help"])
    assert raised.value.code == 0
