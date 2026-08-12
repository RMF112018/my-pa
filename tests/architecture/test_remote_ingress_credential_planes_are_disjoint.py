"""The two credential planes stay disjoint, and the `D-15` pin stays pinned.

**This module exists because of a discharge condition, not because of a rule.**
WP-08's NOTE 1 recorded that `replayQueuedCaptures` compared an entry's stored
`principalId` against a rendered identity while the transport authenticated with
the current cookie. The offline replay principal-isolation correction closes
that gap with replay-time session introspection, an opaque check/send binding,
and Principal-bound receipt verification. The `D-15` single-Principal pin still
holds independently and is not weakened by that defense in depth.

WP-10 mints credentials, which is the cheapest imaginable way to create that
condition. The decision was to **avoid creating it**, and a decision that lives
only in a report is a decision the next package does not inherit. So the
avoidance is expressed here as four executable claims:

1. **The remote ingress mints no browser session and reads no cookie.** The
   Python gateway holds no session store, no signing secret, and no `Set-Cookie`;
   a credential plane that could issue a session would be the web tier's plane
   wearing a different name.
2. **The web tier cannot present a client credential.** No module under
   `web/src` names the ingress path, the credential scheme, the client table, or
   the client identifier prefix — so a browser cannot obtain one, and a session
   cookie cannot become one.
3. **The two schemes are mutually exclusive.** The bearer parser and the client
   parser each reject the other's scheme, read off the composition root itself.
4. **`D-15`'s pin and the corrected queue semantics are change-detected.** Four web
   files carry the property that exactly one Principal is admissible under
   `local_operator` and that the offline queue behaves as WP-08 left it. Their
   SHA-256 digests are pinned here, so an edit to any of them fails the build and
   has to be argued about — which is the WP-04 quarantine-registry mechanism
   applied to the one condition this package promised not to create.

**What claim 4 is and is not.** It is a change detector, not a proof of
behaviour: it fails on a whitespace edit and it would not notice a behavioural
change made somewhere else. The behavioural claim lives where it belongs, in
`web/src/lib/auth/admissible-principals.test.ts`, which asserts that
`synthetic-b` cannot sign in under `local_operator`. This module is the second
lock — it makes the *quiet* version of the change impossible, which is the
version that would actually happen.

Nothing here opens a connection, reaches a network, or runs a request. It reads
the tree.
"""

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import Final

import pytest

ROOT: Final = Path(__file__).resolve().parents[2]
PACKAGE: Final = ROOT / "src" / "my_pa"
WEB: Final = ROOT / "web" / "src"

#: The composition root that resolves both credentials, and the transport that
#: routes both. Read rather than described.
GATEWAY: Final = PACKAGE / "bootstrap" / "gateway.py"
TRANSPORT: Final = PACKAGE / "adapters" / "http" / "app.py"
CLIENT_PLANE: Final = PACKAGE / "infrastructure" / "persistence" / "capture_clients.py"

#: Everything a browser session is made of. None of it may appear anywhere on the
#: Python side of the ingress: this process reads no cookie, issues none, and
#: holds no secret one could be signed with.
SESSION_MACHINERY: Final = (
    "set-cookie",
    "setcookie",
    "session_secret",
    "sessionsecret",
    "mypa_session",
    "signed_session",
    "verifysession",
)

#: The values that identify the remote credential plane. A `web/src` module
#: naming any of them would mean the browser tier had learned how to present a
#: device credential — which is precisely how the two planes would become one.
INGRESS_MARKERS: Final = (
    "/remote/v1/capture.create",
    "ClientCredential",
    "capture_clients",
    "cclt_",
)

#: The four web files whose current behaviour this package depends on. Queue
#: hashes were deliberately re-derived for the replay Principal-isolation fix.
#:
#: * `synthetic.ts` holds `admissibleSyntheticPrincipals()`, the `D-15` narrowing
#:   to exactly one Principal under `local_operator`;
#: * `mode.ts` decides which auth mode is in force and refuses synthetic sign-in
#:   in production;
#: * `replay.ts` and `queue.ts` are WP-08's offline queue, whose NOTE 1 this
#:   package exists not to trigger.
#:
#: Changing any of them is legitimate — and must be *deliberate*. Re-derive the
#: digest with `shasum -a 256`, and say in the same change why the condition
#: WP-08 named is still not created.
PINNED: Final = {
    "lib/auth/synthetic.ts": "3d5c196ac3475433aa3a391507ded753b942d51f6b383180ae93db3c43d87f60",
    "lib/auth/mode.ts": "31a0c3322f0dd4751fd06841f54634825ead770ce5b3c654bdaef0d1ad0e04fc",
    "lib/offline/replay.ts": "d50531075de6019a5be503fb36fbfa0fb97faf42136fdd5fec6b85b167c51e5d",
    "lib/offline/queue.ts": "c4bf1cd90ff88696583aa9e377eedcf1f3e16169868dee4e08ff711ae3792ead",
}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _web_modules() -> list[Path]:
    return sorted(
        path
        for pattern in ("*.ts", "*.tsx")
        for path in WEB.rglob(pattern)
        if "node_modules" not in path.parts
    )


def test_the_scan_reaches_both_trees() -> None:
    """Guards every zero below against being a walk that found nothing."""
    assert GATEWAY.is_file() and TRANSPORT.is_file() and CLIENT_PLANE.is_file()
    assert len(_web_modules()) >= 40, "the web tree is not being read"
    assert WEB.is_dir()


# ---- claim 1: the ingress mints no session ------------------------------------


@pytest.mark.parametrize(
    "path", [GATEWAY, TRANSPORT, CLIENT_PLANE], ids=lambda p: str(Path(p).name)
)
def test_the_remote_credential_path_holds_no_session_machinery(path: Path) -> None:
    """A credential plane that could issue a session would be the other plane.

    Case-insensitive over the whole file, including comments and docstrings, so a
    reference introduced in a comment first — which is how these things arrive —
    is caught with the code.
    """
    source = path.read_text(encoding="utf-8").lower()
    offending = sorted(name for name in SESSION_MACHINERY if name in source)
    assert offending == [], (
        f"{path.relative_to(ROOT)} names {offending}. The Python gateway reads no "
        "cookie, issues none, and holds no session secret; a remote credential "
        "that could mint a browser session would put two identities on one plane, "
        "which is the condition WP-08's NOTE 1 names as release-blocking"
    )


#: The two framing headers this transport reads on every route, which are about
#: the body rather than about the caller. Named so the assertion below is an
#: exact set rather than a subset test that a third header would slip through.
FRAMING_HEADERS: Final = frozenset({"'content-length'", "'content-type'"})


def test_the_transport_reads_exactly_one_credential_header() -> None:
    """The framing headers, and the credential header. Nothing else.

    Measured off the transport's own calls: `request.headers.get(...)` is how a
    header reaches this module, and the arguments it is given are the two framing
    names and the credential constant. A third caller-supplied header would be a
    third thing a caller can influence on the one route a device reaches — a
    `x-principal-id`, say, which is exactly the shape `D-14` keeps out of the web
    tier and which nothing may reintroduce here.
    """
    tree = ast.parse(TRANSPORT.read_text(encoding="utf-8"))
    read = {
        ast.unparse(node.args[0])
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and ast.unparse(node.func.value).endswith("headers")
        and node.args
    }
    assert read == FRAMING_HEADERS | {"_CREDENTIAL_HEADER"}, (
        f"the transport reads {sorted(read)} off the request headers; only the "
        "two framing headers and the credential header may be read, and the "
        "credential one by name"
    )


# ---- claim 2: the web tier cannot present a client credential ------------------


def test_no_web_module_can_present_a_client_credential() -> None:
    """The browser has no way to obtain, hold, or send a device credential.

    Exact set equality against the empty set rather than a spot check: any
    `web/src` module naming the ingress path, the scheme, the table, or the
    identifier prefix would mean the two credential planes had met.
    """
    offending = {
        str(path.relative_to(ROOT)): sorted(
            marker for marker in INGRESS_MARKERS if marker in path.read_text(encoding="utf-8")
        )
        for path in _web_modules()
    }
    naming = {path: markers for path, markers in offending.items() if markers}
    assert naming == {}, (
        f"{naming} name the remote credential plane. A browser that could present "
        "a client credential would collapse the two planes into one, and a session "
        "cookie would become a device credential"
    )


def test_the_detector_finds_a_marker_when_one_is_present(tmp_path: Path) -> None:
    """The control for the claim above: a zero from a scan that matched nothing.

    Without this the assertion would keep passing if `INGRESS_MARKERS` were
    emptied, renamed, or narrowed to a string that appears nowhere — which is the
    vacuous-guard shape this campaign has caught repeatedly.
    """
    planted = tmp_path / "planted.ts"
    planted.write_text(
        'const header = "ClientCredential " + id + ":" + secret;\n', encoding="utf-8"
    )
    found = [marker for marker in INGRESS_MARKERS if marker in planted.read_text(encoding="utf-8")]
    assert found == ["ClientCredential"]


# ---- claim 3: the schemes are mutually exclusive -------------------------------


def test_the_two_schemes_are_distinct_and_each_parser_refuses_the_other() -> None:
    """Read off the composition root, not asserted about it.

    Both scheme constants are declared in one module, so this compares the two
    values that are actually compared at run time. Equal values would mean a
    bearer token and a client secret arrive under one scheme, and the mutual
    refusal the transport tests observe would be an accident of parsing.
    """
    from my_pa.bootstrap.gateway import _BEARER, _CLIENT_CREDENTIAL_SCHEME

    assert _BEARER != _CLIENT_CREDENTIAL_SCHEME
    assert _BEARER.lower() == _BEARER and _CLIENT_CREDENTIAL_SCHEME.lower() == (
        _CLIENT_CREDENTIAL_SCHEME
    ), "both parsers lowercase the presented scheme, so both constants must be lowercase"
    assert not _CLIENT_CREDENTIAL_SCHEME.startswith(_BEARER)
    assert not _BEARER.startswith(_CLIENT_CREDENTIAL_SCHEME)


def test_the_remote_authenticator_cannot_read_a_request_document() -> None:
    """Identity on the ingress comes from the credential, provably.

    `entra_authenticator` takes the document because it has to refuse an identity
    field inside it. The remote authenticator's type takes only the header, so
    there is no argument through which a payload could influence which Principal
    a submission runs as. Asserted off the declared alias rather than off a
    docstring.
    """
    source = GATEWAY.read_text(encoding="utf-8")
    match = re.search(r"RemoteClientAuthenticator = Callable\[\[([^\]]*)\]", source)
    assert match is not None, "the remote authenticator's type alias is no longer readable here"
    assert match.group(1).strip() == "str | None", (
        f"the remote authenticator now takes {match.group(1)!r}; a second argument "
        "is a second thing a caller could influence its identity with"
    )


# ---- claim 4: the pin --------------------------------------------------------


@pytest.mark.parametrize("relative", sorted(PINNED), ids=lambda value: str(value))
def test_the_pinned_web_files_are_unchanged(relative: str) -> None:
    """`D-15` and WP-08's queue, byte for byte.

    This package holds that no second Principal can hold a session while the
    backend serves. Two of these files are what make that true today and two are
    what would be unsafe if it stopped being true. A change to any of them is
    allowed and must be deliberate: re-derive the digest, and say why the
    condition WP-08 named is still not created.
    """
    path = WEB / relative
    assert path.is_file(), f"{relative} is gone; the pin describes a file that no longer exists"
    assert _digest(path) == PINNED[relative], (
        f"web/src/{relative} changed. It carries either the `D-15` pin (exactly "
        "one admissible Principal under `local_operator`) or WP-08's offline "
        "queue semantics, and WP-10's whole position is that the condition "
        "WP-08's NOTE 1 names — two identities holding sessions while the backend "
        "serves — is not created. Re-derive the digest here and argue the change"
    )


def test_the_pin_covers_the_file_that_narrows_the_admissible_set() -> None:
    """The digests are of the right files, which a digest alone cannot say.

    A pin over four arbitrary files would pass forever and mean nothing. This
    reads the pinned source and requires the narrowing function to be in it, so
    the pin is attached to the property rather than to a path somebody typed.
    """
    synthetic = (WEB / "lib/auth/synthetic.ts").read_text(encoding="utf-8")
    assert "admissibleSyntheticPrincipals" in synthetic
    assert "local_operator" in synthetic

    replay = (WEB / "lib/offline/replay.ts").read_text(encoding="utf-8")
    assert "currentPrincipalId" in replay, (
        "the rendered-identity comparison WP-08 NOTE 1 describes is no longer in "
        "`replay.ts`; if it was fixed, this pin and that NOTE both need revisiting"
    )
