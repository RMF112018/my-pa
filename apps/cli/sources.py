"""Operator command: configure a source, and observe its root.

    .venv/bin/python apps/cli/sources.py register \\
        --provider fixture --root fixtures/mcv/root \\
        --label "MCV fixture corpus" --classification private_local
    .venv/bin/python apps/cli/sources.py list

This is the bootstrap the rest of the product needs and could not previously be
given. `sources.enroll` names a source by `src_…` and a root by `obj_…`, both of
which have to exist before an enrollment can, and until this command existed
`register_source` and `observe_object` had no production caller at all. Nothing
else here is new: the two writers are the ones `infrastructure.persistence` has
had since WP-3.

**It is configuration, not a grant, and it is not a capability.** The current
set is thirty (`domain/identity/operation.py`), and the reason source
registration is not one of them is not the size of that set: `D-42` records that
it is named by no canonical capability, and `D-68` narrows that ruling's general
premise for the capture family alone. Creating a source authorizes nobody to
read anything: every read still requires an
enrollment, which requires `sources.enroll`, which is operator-only, goes through
`authorize`, and writes a durable audit event. This command builds no
`ApplicationService`, no `Principal`, and no `SourceProviders`, so it could not
list, fetch, search, read, or enroll even if somebody wanted it to.
`tests/architecture/test_operator_commands_are_not_capabilities.py` asserts that
by reading this file rather than by trusting this paragraph.

**It writes no audit event, and that is a decision rather than an omission.**
`audit_events.capability` is constrained to the ninety-five `Capability` values,
so recording a registration would mean a hundredth member — exactly what
makes an operator command look like the capability it is not. WP-6 widened that
constraint by an explicit `ALTER` in its own revision rather than by re-deriving
it from the enum (`D-69`), so the argument here is unchanged: adding a member is
a deliberate migration, not a side effect of a name. The `sources` row is its
own evidence: `configured_at` is `NOT NULL` with a server default, the row is
unique on `(provider_kind, native_root)`, and `register_source` is idempotent, so
"when was this configured" has one answer and re-running the command does not
change it.

**Its runtime is one engine, deliberately not the gateway's.** `invoke.py` shares
`build_gateway_runtime` because it invokes a *capability* and must be provably the
same request path. This invokes none, so sharing that runtime would be sharing an
object it has no use for. It composes what `migration.py` composes — one engine
from validated settings, one transaction, `dispose()` in a `finally` — and it is
allowed to choose an implementation because `module-boundaries.md` section 5.10
makes `apps.cli` a composition root.

**`--root` is never echoed back, on any path including a failure.** `migration.py`
prints `source_sha256` and `source_bytes` and never the `--source` path; the same
rule holds here, and `validate_source_label` already refuses a label that could
carry a path. A refusal names the defect and never the value. Exit `0` on
success, `1` on refusal.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine

from my_pa.bootstrap.settings import load_settings
from my_pa.domain.common.classification import Classification
from my_pa.domain.source.provider import ObjectKind
from my_pa.domain.source.registry import SourceProviderKind
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.registry import all_sources, observe_object, register_source
from my_pa.infrastructure.providers.fixture import FixtureSourceProvider

#: What a refusal is worth to a shell. `0` and `1` and nothing finer: a caller
#: scripting this needs "did it work", and a richer status would be a vocabulary
#: nobody asked for.
EXIT_OK = 0
EXIT_REFUSED = 1


def _engine() -> Engine:
    return create_database_engine(
        load_settings().parsed_database_url(), statement_timeout_ms=30_000
    )


def _register(args: argparse.Namespace) -> int:
    """Configure one root as a source and observe it, in one transaction.

    The order is register, validate, observe, and each step is where it is for a
    reason.

    `register_source` first, because the observation needs the `src_…` it issues
    and because it is the idempotent half: running this twice over the same root
    is one source, by `sources_native_root_is_configured_once`.

    Then `FixtureSourceProvider`, constructed and discarded. It is the validator,
    and reusing the adapter rather than writing a second existence check here is
    what makes it impossible for this command to admit a root the provider would
    afterwards refuse — its `__init__` resolves the path, `stat`s it, and raises
    `ValueError` unless the result is an existing directory. It is built with its
    default identity, which touches no database: this command's business is the
    root, and letting the adapter also issue identifiers here would give the root
    observation two writers.

    Then `observe_object`, which issues the `obj_…` an enrollment names as its
    root. Its fingerprint is this command's own observation of the directory and
    is deliberately not the provider's: a container's version is never fetched,
    extracted, or compared against anything — `enrollment_objects` holds files
    only — so matching the adapter's formula would be copying a definition to
    make two values equal that nothing compares. The *object* identity is what
    has to agree, and it does, because both are keyed on the same resolved
    locator.

    The whole of it is one transaction, so a root that cannot be observed leaves
    no source row behind.

    The root is resolved once, here, and the resolved form is what is stored:
    `RegisteredSourceProviders` builds the adapter from the stored value, and a
    relative path would resolve against whatever directory that process happened
    to start in.
    """
    root = Path(args.root).resolve()
    engine = _engine()
    try:
        with engine.begin() as connection:
            source = register_source(
                connection,
                provider_kind=SourceProviderKind(args.provider),
                label=args.label,
                classification=Classification(args.classification),
                native_root=str(root),
            )
            # Constructed for its refusal, then dropped. Nothing below uses it.
            FixtureSourceProvider(root, source.source_id)
            status = root.stat()
            observed = observe_object(
                connection,
                source_id=source.source_id,
                native_locator=str(root),
                kind=ObjectKind.CONTAINER,
                fingerprint=f"{status.st_dev}:{status.st_ino}:{status.st_mtime_ns}",
                modified_at=datetime.fromtimestamp(status.st_mtime, UTC),
            )
    finally:
        engine.dispose()

    print(f"source_id        {source.source_id}")
    print(f"root_object_id   {observed.source_object_id}")
    print(f"provider_kind    {source.provider_kind.value}")
    print(f"classification   {source.classification.value}")
    print(f"label            {source.label}")
    print(f"configured       {source.configured_at.isoformat()}")
    return EXIT_OK


def _list(args: argparse.Namespace) -> int:
    """Print one line per configured source, and no root.

    `native_root` is a column of the rows behind this and is deliberately not
    reachable from here: `all_sources` returns
    `domain.source.registry.ConfiguredSource` values, which have no locator
    field, so a listing that carried one would take a domain change to write. A
    listing that did carry one would put every configured path into any
    terminal, shell history, or evidence file that ran this.

    It reads through `all_sources` rather than selecting from the `sources`
    table here, and the difference is not stylistic. Importing the table
    declaration into an operator command admits a **write** surface in order to
    perform a read — `insert()` and `update()` are as reachable through a
    `Table` as `select()` is — and
    `tests/architecture/test_operator_commands_are_not_capabilities.py` would
    have had to widen its permitted-name allowlist by exactly that to let it
    through.
    """
    engine = _engine()
    try:
        with engine.connect() as connection:
            configured = all_sources(connection)
    finally:
        engine.dispose()

    for source in configured:
        print(
            f"{source.source_id}  {source.provider_kind.value:<8s}  "
            f"{source.classification.value:<18s}  "
            f"{source.configured_at.isoformat()}  {source.label}"
        )
    print(f"sources     {len(configured)}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sources", description="Configure my-pa sources.")
    commands = parser.add_subparsers(dest="command", required=True)

    register = commands.add_parser("register", help="configure a root as a source")
    register.add_argument(
        "--provider",
        choices=[kind.value for kind in SourceProviderKind],
        required=True,
        help="which provider serves this source",
    )
    register.add_argument(
        "--root", type=Path, required=True, help="the directory to configure, by exact path"
    )
    register.add_argument("--label", required=True, help="an operator-facing name for the source")
    register.add_argument(
        "--classification",
        choices=[value.value for value in Classification],
        required=True,
        help="how the content of this source is classified",
    )

    commands.add_parser("list", help="print the configured sources")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse, dispatch, and turn a refusal into an exit status.

    The refusals this command can produce are a label that is not one
    (`InvalidSourceLabelError`, which is a `ValueError`) and a root that is not an
    existing directory. Both messages name the defect and neither carries the
    value, which is what makes printing them consistent with `--root` never being
    echoed.

    An `OSError` is caught separately and its text is *not* printed. It is the
    one exception here that renders with the filename it failed on, so passing it
    through would disclose the root by the back door on the one path nobody
    tests by hand. What is printed instead is the fact, which is all an operator
    can act on: the configured root could not be read.

    Anything else propagates. A driver failure is not a refusal and reporting it
    as one would tell an operator to fix their arguments.
    """
    args = build_parser().parse_args(argv)
    try:
        match args.command:
            case "register":
                return _register(args)
            case "list":
                return _list(args)
            case unknown:  # pragma: no cover - argparse rejects an unknown command first
                raise SystemExit(f"unhandled command {unknown!r}")
    except ValueError as refusal:
        print(f"refused     {refusal}")
        return EXIT_REFUSED
    except OSError:
        print("refused     the configured root could not be read")
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
