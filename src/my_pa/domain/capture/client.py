"""A registered remote capture client: an identifier, a hashed secret, a binding.

`RegisteredCaptureClient` is the record `domain/capture/submission.py` said was
deferred (`D-74`). It is deferred no longer, and the three premises that deferred
it are named rather than quietly dropped: `D-30` issued no credential, `O-21` had
decided no issuance, and `P00-OD-010` had selected no mechanism. WP-05 answered
the mechanism for *people* (`entra`); this module answers it for *devices*, which
is a different question and gets a different answer — a client credential minted
by the operator, bound at minting time to exactly one Principal, and never a
browser session.

**What a client is, and what it is not.** It is a bearer of one long random
secret that lets a device submit a capture on behalf of the one Principal it was
bound to. It is not an identity, it is not a Principal, and it grants no
authority of its own: the Principal it resolves to is the Principal the operator
bound it to, and everything downstream — authorization, partition, audit — is
that Principal's, unchanged. A client that could *name* the Principal it acts for
would be a caller-supplied identity, which is the one thing `D-13`/`D-14` keep
out of this tree.

**The secret is stored hashed and returned exactly once.** `issue_client_secret`
is the only thing that produces plaintext, and it produces it in the same
expression that produces the digest, so there is no window in which a stored
secret could be read back. Nothing in this package writes a plaintext secret to a
row, a log, an error, or a response body — `RegisteredCaptureClient` has no field
one could go in, which is a property of the type rather than of care.

**SHA-256 rather than a password KDF, and the reason is the input.** A KDF exists
to make a *low-entropy, human-chosen* secret expensive to guess. This secret is
`SECRET_ENTROPY_BYTES` of `secrets.token_urlsafe` — 256 bits from the operating
system's CSPRNG — so an offline attacker holding the digest faces preimage
resistance on a uniformly random 256-bit value, which no iteration count improves
upon. Adding a KDF here would cost every ingress request a deliberate delay and
buy nothing measurable. The reasoning is *specific to a machine-generated
secret*: it does not transfer to anything a person types, and a future path that
let an operator choose a secret would have to revisit it.

**Comparison is constant-time** (`hmac.compare_digest`), because the digest is
compared against one derived from an attacker-supplied string and a byte-by-byte
comparison leaks a prefix.
"""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Final

from my_pa.domain.capture.errors import CaptureError
from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "SECRET_DIGEST_CHARACTERS",
    "SECRET_ENTROPY_BYTES",
    "ClientBindingRefusedError",
    "ClientCredential",
    "ClientState",
    "RegisteredCaptureClient",
    "admit_client_binding",
    "hash_client_secret",
    "issue_client_secret",
    "parse_client_credential",
    "secret_matches",
]

#: How much entropy one client secret carries. 32 bytes from the operating
#: system's CSPRNG, rendered URL-safe, so the value survives a shell, a text
#: field on a phone, and an HTTP header without escaping.
SECRET_ENTROPY_BYTES: Final = 32

#: A SHA-256 as it is stored: 64 lowercase hexadecimal characters.
SECRET_DIGEST_CHARACTERS: Final = 64

#: The separator between the client identifier and the secret inside one
#: credential. A colon, because an opaque identifier admits only alphanumerics
#: and one underscore and `token_urlsafe` emits only `[A-Za-z0-9_-]`, so neither
#: half can contain it and the split is unambiguous at the first occurrence.
_CREDENTIAL_SEPARATOR: Final = ":"

#: What an absent client's stored digest is compared against, so the comparison
#: takes the same path whether or not the client exists. It is the digest of a
#: value no `issue_client_secret` can produce.
_ABSENT_CLIENT_DIGEST: Final = sha256(b"\x00no such registered capture client").hexdigest()


class ClientState(StrEnum):
    """Whether a registered client may still present its credential.

    Two values, and the second is the whole of revocation: a revoked client is a
    state on the row rather than a deleted row, so it stays legible to an
    operator reading the table and its refusal is a recorded fact rather than an
    absence that could equally mean "never existed".
    """

    ACTIVE = "active"
    REVOKED = "revoked"


class ClientBindingRefusedError(CaptureError):
    """A client names a Principal this process may not act as. Fail closed."""


@dataclass(frozen=True, slots=True)
class ClientCredential:
    """One presented credential, split into the identifier and the secret.

    `secret` is `repr=False` for the reason `CreateCapture.text` is: a dataclass
    `repr` reaches a traceback, a log record, and a pytest assertion message
    without anybody deciding it should, and this is the one field in this module
    that is a credential.
    """

    client_id: str
    secret: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class RegisteredCaptureClient:
    """One minted client: what it is, whose it is, and whether it still works.

    There is **no secret field and no digest field**, and that is structural
    rather than tidy: this is the object every reader of the client plane
    receives, so a value that cannot be represented here cannot be returned by a
    listing, printed by the operator command, or rendered into an error.
    """

    client_id: str
    principal_id: str
    state: ClientState
    created_at: datetime
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.client_id, IdKind.CAPTURE_CLIENT)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not isinstance(self.state, ClientState):
            raise CaptureError("a registered client records one known state")
        ensure_utc(self.created_at)
        if self.revoked_at is not None:
            ensure_utc(self.revoked_at)
        if (self.state is ClientState.REVOKED) is not (self.revoked_at is not None):
            raise CaptureError(
                "a revoked client records when it was revoked and an active one records nothing"
            )

    @property
    def usable(self) -> bool:
        """Whether this client may still authenticate a submission."""
        return self.state is ClientState.ACTIVE


def issue_client_secret() -> tuple[str, str]:
    """Mint one secret and its digest together, as `(plaintext, sha256)`.

    Returned as a pair from one expression so that no caller can obtain a digest
    without the plaintext or a plaintext without the digest, and so the only
    plaintext that exists anywhere is the one this return value carries. The
    operator command prints it once; nothing stores it.
    """
    secret = secrets.token_urlsafe(SECRET_ENTROPY_BYTES)
    return secret, hash_client_secret(secret)


def hash_client_secret(secret: str) -> str:
    """The digest one client secret is stored as.

    Refuses a non-string and an empty secret rather than digesting them: an empty
    string has a perfectly good SHA-256, and storing it would make the credential
    `<client_id>:` a working one.
    """
    # Two statements rather than one `or`, for the reason
    # `domain.common.identifiers.validate_identifier` keeps its own runtime type
    # check: a domain model here is a plain dataclass with no runtime type
    # enforcement, so a non-string can reach this and must fail as a domain error
    # rather than as an incidental `AttributeError` from `.encode`.
    if not isinstance(secret, str):
        raise CaptureError("a client secret is a non-empty string")
    if not secret:
        raise CaptureError("a client secret is a non-empty string")
    return sha256(secret.encode("utf-8")).hexdigest()


def secret_matches(presented: str, stored_digest: str | None) -> bool:
    """Whether `presented` is the secret `stored_digest` was derived from.

    `stored_digest` may be `None`, which is how an absent client is answered: the
    comparison still runs, against a digest no minted secret can produce, so "no
    such client" and "wrong secret" take the same path through this function. The
    database lookup that preceded it is not equalised, and that residue is stated
    rather than papered over — a client identifier is CSPRNG output, so an
    attacker able to time the difference still has nothing to enumerate.
    """
    if not presented:
        return False
    candidate = sha256(presented.encode("utf-8")).hexdigest()
    return hmac.compare_digest(candidate, stored_digest or _ABSENT_CLIENT_DIGEST)


def parse_client_credential(presented: str) -> ClientCredential:
    """Split `<client_id>:<secret>` into its two halves, or refuse.

    Shape only. Whether the client exists, whether the secret is right, and
    whether the client is still active are all decided elsewhere and all answered
    with the same refusal, so nothing here may distinguish them either.

    **Every refusal is a `CaptureError`, including a malformed identifier.**
    `validate_identifier` raises `InvalidIdentifierError`, which is a
    `ValueError` and not a `CaptureError`, so letting it out would have given the
    composition root a second exception type to catch — and the one it did not
    catch escaped a transport as a server fault rather than as a refusal. Raised
    outside the handler, so the original does not sit on `__context__` for a
    rendered traceback to read the caller's string out of.
    """
    client_id, separator, secret = presented.partition(_CREDENTIAL_SEPARATOR)
    if not separator or not secret:
        raise CaptureError("a client credential is <client_id>:<secret>")
    named = False
    try:
        validate_identifier(client_id, IdKind.CAPTURE_CLIENT)
    except InvalidIdentifierError:
        named = True
    if named:
        raise CaptureError("a client credential is <client_id>:<secret>")
    return ClientCredential(client_id=client_id, secret=secret)


def admit_client_binding(*, bound: str, admissible: str | None) -> None:
    """Refuse a client bound to a Principal this process may not act as.

    `admissible` is the single Principal this process is allowed to mint and
    authenticate clients for, or `None` when the process authenticates real
    Principals itself and a client may therefore be bound to whichever one was
    authenticated when it was minted.

    **This is the whole of the WP-08 NOTE 1 avoidance.** Under
    `MY_PA_AUTH_MODE=local_operator` the gateway serves exactly one Principal,
    and the failure this forecloses is a client credential quietly introducing a
    *second* one holding real data — the condition that would turn WP-08's
    rendered-identity replay check into a release blocker. It is applied at
    minting *and* at every authentication, so a row written before a mode change,
    or by hand, is refused rather than served.
    """
    if admissible is not None and bound != admissible:
        raise ClientBindingRefusedError(
            "this process binds capture clients to exactly one Principal and the "
            "client names another; there is no inference and no rebinding"
        )
