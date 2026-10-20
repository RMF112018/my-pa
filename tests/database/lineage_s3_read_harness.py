"""Shared helpers for the record lineage S3 read tests (package L3).

A helper module, not a test module: pytest does not collect it. It extends the
S3 write harness (`lineage_s3_harness.S3Runtime`) with what the as-of,
paging, cursor, visibility and history tests need:

* `S3ReadRuntime.invoke(..., grants=...)` -- a remote caller with an exact grant
  set (section 6.4 visibility is derived from it), beside the S1 harness's
  single-grant `remote_client`;
* `horizon` -- the Principal's committed lineage horizon `H`, as the
  microsecond RFC 3339 token every S3 answer reports a cut in;
* `lineage` / `pages` -- `records.lineage`, one page or followed to the end;
* `timeline` / `timeline_pages` -- `issues.timeline` likewise (package L4);
* cursor surgery for the tamper tests (`decoded`, `reencoded`).

Every identity and every body here is synthetic.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from sqlalchemy import Engine, text

from my_pa.application.commands import Command, ReadIssueTimeline, ReadRecordLineage
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import issue_identifier
from tests.database.lineage_issue_harness import PRINCIPAL, REMOTE_CLIENT, WHEN
from tests.database.lineage_s3_harness import S3Runtime

__all__ = [
    "READS",
    "S3ReadRuntime",
    "decoded",
    "edge_ids",
    "grant",
    "horizon",
    "instant",
    "lineage_request",
    "node_set",
    "reencoded",
    "union",
    "virtual_set",
]

#: Every family read a remote reader may be granted (S3 section 6.4).
READS: Final = (
    "issues.read",
    "meetings.read",
    "tasks.read",
    "commitments.read",
    "constraints.read",
    "capture.read",
)

type Grants = frozenset[tuple[Capability, Purpose | None]]


def grant(*capabilities: str) -> Grants:
    """Each named capability granted for its first permitted purpose."""
    return frozenset(
        (Capability(name), sorted(permitted_purposes(Capability(name)))[0]) for name in capabilities
    )


class S3ReadRuntime(S3Runtime):
    """`S3Runtime` whose remote calls may carry an exact grant set."""

    def invoke(  # type: ignore[override]
        self,
        command: Command,
        *,
        principal_id: str = PRINCIPAL,
        purpose: Purpose | None = None,
        remote_client: str | None = None,
        grants: Grants | None = None,
        surface: Any = None,  # noqa: ANN401
    ) -> ResponseEnvelope:
        if grants is None:
            return super().invoke(
                command,
                principal_id=principal_id,
                purpose=purpose,
                remote_client=remote_client,
                surface=surface,
            )
        capability = command.capability
        chosen = purpose or sorted(permitted_purposes(capability))[0]
        return self.service.invoke(
            RequestMetadata(
                request_id=issue_identifier(IdKind.CORRELATION),
                capability=capability,
                purpose=chosen,
                principal_id=principal_id,
                requested_at=WHEN,
            ),
            command,
            principal=Principal(
                principal_id=principal_id, kind=PrincipalKind.OPERATOR, authenticated=True
            ),
            transport=CaptureTransport.REMOTE_CLIENT,
            capability_grants=grants,
            authenticated_client_id=remote_client or REMOTE_CLIENT,
            operator_surface=None,
        )

    def lineage(self, root: tuple[str, str], **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """`records.lineage` from `root`; keyword arguments go to the command, then `invoke`."""
        command, rest = lineage_request(root, kwargs)
        return self.ok(command, **rest)

    def pages(self, root: tuple[str, str], **kwargs: Any) -> list[dict[str, Any]]:  # noqa: ANN401
        """Every page of a paged `records.lineage`, following `next_cursor` to `null`."""
        found: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            page = self.lineage(root, cursor=cursor, **kwargs)
            found.append(page)
            cursor = page["next_cursor"]
            if cursor is None:
                return found
            assert len(found) < 200, "paging did not end"

    def timeline(self, issue_id: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """`issues.timeline` of `issue_id`; keyword arguments go to the command, then `invoke`."""
        fields = {key: value for key, value in kwargs.items() if key in _TIMELINE_FIELDS}
        rest = {key: value for key, value in kwargs.items() if key not in _TIMELINE_FIELDS}
        return self.ok(ReadIssueTimeline(issue_id=issue_id, **fields), **rest)

    def timeline_pages(self, issue_id: str, **kwargs: Any) -> list[dict[str, Any]]:  # noqa: ANN401
        """Every page of `issues.timeline`, following `next_cursor` to `null`.

        A cursor needs its page size (section 7.5), so the default 25 is stated.
        """
        kwargs.setdefault("page_size", 25)
        found: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            page = self.timeline(issue_id, cursor=cursor, **kwargs)
            found.append(page)
            cursor = page["next_cursor"]
            if cursor is None:
                return found
            assert len(found) < 200, "paging did not end"


_TIMELINE_FIELDS: Final = frozenset({"known_at", "valid_at", "page_size", "cursor"})
_COMMAND_FIELDS: Final = frozenset(
    {"issue_id", "max_depth", "known_at", "valid_at", "page_size", "cursor"}
)


def lineage_request(
    root: tuple[str, str], kwargs: dict[str, Any]
) -> tuple[ReadRecordLineage, dict[str, Any]]:
    fields = {key: value for key, value in kwargs.items() if key in _COMMAND_FIELDS}
    rest = {key: value for key, value in kwargs.items() if key not in _COMMAND_FIELDS}
    return ReadRecordLineage(origin={"family": root[0], "record_id": root[1]}, **fields), rest


def horizon(engine: Engine, principal_id: str = PRINCIPAL) -> str:
    """`H`: the Principal's committed `last_marked_at`, as a microsecond token."""
    with engine.connect() as connection:
        value = connection.execute(
            text(
                "SELECT last_marked_at FROM knowledge.lineage_commit_sequences "
                "WHERE principal_id = :p"
            ),
            {"p": principal_id},
        ).scalar_one()
    return instant(value)


def instant(value: datetime, *, plus: timedelta = timedelta(0)) -> str:
    """An aware instant as the microsecond RFC 3339 token S3 answers use."""
    return (value + plus).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def node_set(answer: dict[str, Any]) -> set[tuple[str, str]]:
    return {(node["family"], node["record_id"]) for node in answer["nodes"]}


def edge_ids(answer: dict[str, Any]) -> set[str]:
    return {edge["link_id"] for edge in answer["typed_edges"]}


def virtual_set(answer: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (edge["from"]["record_id"], edge["to"]["record_id"])
        for edge in answer["virtual_native_edges"]
    }


def union(pages: Iterable[dict[str, Any]]) -> dict[str, list[Any]]:
    """The items of every page, in page order."""
    merged: dict[str, list[Any]] = {"nodes": [], "typed_edges": [], "virtual_native_edges": []}
    for page in pages:
        for key in merged:
            merged[key].extend(page[key])
    return merged


def decoded(token: str) -> dict[str, Any]:
    """A cursor's JSON document (it is unsigned base64url, section 5)."""
    raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    document = json.loads(raw)
    assert isinstance(document, dict)
    return document


def reencoded(document: dict[str, Any]) -> str:
    """A cursor document back as a token, canonical as the server writes it."""
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return base64.urlsafe_b64encode(payload.encode("ascii")).decode("ascii").rstrip("=")
