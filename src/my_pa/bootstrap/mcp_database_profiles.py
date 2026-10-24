"""Default-off composition of two fixed MCP data services.

Authentication/control and durable audit retain separate trusted server paths.
Neither data role is used to authenticate clients, append audit or write reports.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field, replace
from pathlib import Path

from sqlalchemy import URL, Connection, Engine, event

from my_pa.adapters.mcp.remote import RemoteAccessContext
from my_pa.application.service import ApplicationService
from my_pa.bootstrap.gateway import GatewayRuntime, build_gateway_runtime
from my_pa.bootstrap.settings import Settings, SettingsError
from my_pa.contracts.mcp_database_profiles import (
    MCP_DATABASE_TRANSPORT_QUERY_KEYS,
    McpDatabaseProfile,
    profile_capabilities,
)
from my_pa.infrastructure.database.engine import create_database_engine


def _password(path: str) -> str:
    """Read only an explicitly configured, private input; never expose its errors."""
    value = ""
    try:
        target = Path(path)
        if not target.is_absolute() or target.parent.resolve() != target.parent:
            raise ValueError
        parent = target.parent.stat()
        if parent.st_uid != os.geteuid() or stat.S_IMODE(parent.st_mode) != 0o700:
            raise ValueError
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o400
                or info.st_nlink != 1
            ):
                raise ValueError
            raw = os.read(fd, 258)
            if not 32 <= len(raw) <= 257:
                raise ValueError
            value = raw.decode("utf-8").removesuffix("\n")
            if "\n" in value or "\r" in value or len(value) < 32:
                raise ValueError
        finally:
            os.close(fd)
    except (OSError, ValueError, UnicodeError):
        pass
    else:
        return value
    raise SettingsError("MCP profile protected credential input refused")


def _bind_engine(engine: Engine, control: Engine, role: str, cluster: str, *, ro: bool) -> None:
    if ro:

        @event.listens_for(engine, "begin")
        def read_only(connection: Connection) -> None:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")

    @event.listens_for(engine, "engine_connect")
    def identity(connection: Connection) -> None:
        # A fresh attested control connection binds the same configured endpoint
        # to the cluster. Data roles never receive pg_control_system privileges.
        with control.connect() as trusted:
            target = trusted.exec_driver_sql(
                "SELECT current_database(), "
                "(SELECT system_identifier::text FROM pg_control_system()), "
                "(SELECT oid::text FROM pg_database WHERE datname=current_database()), "
                "inet_server_addr()::text, inet_server_port(), "
                "current_setting('server_version_num')"
            ).one()
            expected_oid = trusted.exec_driver_sql(
                "SELECT oid::text FROM pg_roles WHERE rolname=%s", (role,)
            ).scalar_one()
        try:
            actual = connection.exec_driver_sql(
                "SELECT current_database(), current_user, session_user, r.oid::text, "
                "(SELECT oid::text FROM pg_database WHERE datname=current_database()), "
                "inet_server_addr()::text, inet_server_port(), "
                "current_setting('server_version_num'), "
                "r.rolsuper OR r.rolinherit OR r.rolcreaterole OR r.rolcreatedb "
                "OR r.rolreplication OR r.rolbypassrls OR NOT r.rolcanlogin, "
                "EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid OR roleid=r.oid), "
                "EXISTS(SELECT 1 FROM pg_database WHERE datdba=r.oid "
                "OR has_database_privilege(r.oid,oid,'CREATE')), "
                "EXISTS(SELECT 1 FROM pg_namespace WHERE nspowner=r.oid "
                "OR (left(nspname,3)<>'pg_' AND nspname<>'information_schema' "
                "AND has_schema_privilege(r.oid,oid,'CREATE'))), "
                "EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE c.relowner=r.oid AND left(n.nspname,3)<>'pg_'), "
                "EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE p.proowner=r.oid AND left(n.nspname,3)<>'pg_') "
                "FROM pg_roles r WHERE r.rolname=current_user"
            ).one()
            if not (
                target[0] == actual[0] == "my_pa"
                and target[1] == cluster
                and actual[1] == actual[2] == role
                and actual[3] == expected_oid
                and actual[4] == target[2]
                and tuple(actual[5:8]) == tuple(target[3:6])
                and str(actual[7]).startswith("17")
                and not any(actual[8:14])
            ):
                raise SettingsError("MCP database role or target identity refused")
        finally:
            # The identity SELECT must not leave a transaction on a reused pool connection.
            connection.rollback()


@dataclass(frozen=True)
class McpDatabaseServices:
    read_service: ApplicationService = field(repr=False)
    write_service: ApplicationService = field(repr=False)
    read_clients: frozenset[str] = field(repr=False)
    write_clients: frozenset[str] = field(repr=False)
    engines: tuple[Engine, Engine] = field(repr=False)

    def access(
        self, context: RemoteAccessContext, *, write_allowed: bool
    ) -> RemoteAccessContext | None:
        if not context.principal.authenticated:
            return None
        client = context.authenticated_client_id
        if client in self.read_clients:
            profile = McpDatabaseProfile.READ_ONLY
        elif client in self.write_clients:
            profile = (
                McpDatabaseProfile.READ_WRITE if write_allowed else McpDatabaseProfile.READ_ONLY
            )
        else:
            return None
        allowed = profile_capabilities(profile) & (context.allowed_capabilities or frozenset())
        purposes = frozenset(
            (capability, purpose)
            for capability, purpose in (context.capability_purposes or ())
            if capability.value in allowed
        )
        return replace(
            context,
            allowed_capabilities=allowed,
            capability_purposes=purposes,
            service=self.write_service
            if profile is McpDatabaseProfile.READ_WRITE
            else self.read_service,
        )

    def close(self) -> None:
        for engine in self.engines:
            engine.dispose()


def build_mcp_database_services(
    settings: Settings, control: GatewayRuntime
) -> McpDatabaseServices | None:
    if not settings.mcp_database_profiles_enabled:
        return None
    engines: list[Engine] = []
    try:
        for role, path, ro in (
            ("my_pa_mcp_ro", settings.mcp_database_ro_password_file, True),
            ("my_pa_mcp_rw", settings.mcp_database_rw_password_file, False),
        ):
            # Same endpoint as the separately attested control connection, no inherited
            # URL query/options that could override the new role or connect elsewhere.
            # Reviewed TLS/channel-binding settings are preserved without weakening them.
            base = settings.parsed_database_url()
            if not base.query.keys() <= MCP_DATABASE_TRANSPORT_QUERY_KEYS:
                raise SettingsError("MCP profiles refuse unreviewed transport query options")
            url = URL.create(
                base.drivername,
                username=role,
                password=_password(path),
                host=base.host,
                port=base.port,
                database="my_pa",
                query=base.query,
            )
            engine = create_database_engine(url, statement_timeout_ms=30_000)
            engines.append(engine)
            _bind_engine(
                engine, control.work_engine, role, settings.mcp_database_expected_cluster_id, ro=ro
            )
            with engine.connect():
                pass
        # Do not introduce business re-enrichment writes through authentication,
        # reads or automatic startup observations. Managed writes are not admitted.
        data_settings = settings.model_copy(
            update={
                "relationship_reenrichment_enabled": False,
                "managed_document_root": "",
            }
        )
        services = [
            build_gateway_runtime(
                data_settings,
                data_engine=engine,
                independent_audit_engine=control.audit_engine,
                controls_engine=control.work_engine,
            ).service
            for engine in engines
        ]
        return McpDatabaseServices(
            services[0],
            services[1],
            settings.mcp_database_ro_clients(),
            settings.mcp_database_rw_clients(),
            (engines[0], engines[1]),
        )
    except Exception:
        for engine in engines:
            engine.dispose()
    raise SettingsError("MCP database profile composition refused; no legacy fallback")
