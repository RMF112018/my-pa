"""Run one outbound Apple grant handoff on the Mac.

Required environment: ``MYPA_APPLE_CONTROL_ORIGIN``, ``MYPA_APPLE_PRINCIPAL_ID``,
``MYPA_APPLE_BRIDGE_ID``, ``MYPA_APPLE_BRIDGE_CREDENTIAL``,
``MYPA_APPLE_HOST_EXECUTABLE``, ``MYPA_APPLE_SPOOL_DIRECTORY``,
``MYPA_APPLE_GRANT_JOURNAL``, ``MYPA_APPLE_CONTACTS_IDENTITY_EPOCH``, and
``MYPA_APPLE_MAIL_GENERATION``. This process opens no listener and refuses any
environment containing a database URL or DSN.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from my_pa.infrastructure.apple_source_host import AppleSourceHostProcess
from my_pa.infrastructure.apple_transport_agent import (
    AppleGrantJournal,
    AppleTransportAgent,
    HttpsAppleControlClient,
)


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ValueError(f"{name} is required")
    return value


def main() -> int:
    host = AppleSourceHostProcess(
        executable=Path(_required("MYPA_APPLE_HOST_EXECUTABLE")),
        spool_directory=Path(_required("MYPA_APPLE_SPOOL_DIRECTORY")),
        contacts_identity_epoch=_required("MYPA_APPLE_CONTACTS_IDENTITY_EPOCH"),
        mail_generation=_required("MYPA_APPLE_MAIL_GENERATION"),
    )
    agent = AppleTransportAgent(
        principal_id=_required("MYPA_APPLE_PRINCIPAL_ID"),
        bridge_id=_required("MYPA_APPLE_BRIDGE_ID"),
        credential=_required("MYPA_APPLE_BRIDGE_CREDENTIAL"),
        client=HttpsAppleControlClient(_required("MYPA_APPLE_CONTROL_ORIGIN")),
        host=host,
        journal=AppleGrantJournal(Path(_required("MYPA_APPLE_GRANT_JOURNAL"))),
        environment=os.environ,
    )
    return 0 if agent.run_once(at=datetime.now(UTC)) else 3


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as refusal:
        print(f"refused     {refusal}", file=sys.stderr)
        sys.exit(1)
