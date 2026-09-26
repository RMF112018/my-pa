"""Synthetic checks for the pre-transfer preserved-runtime environment gate."""

# Test fixtures and injected subprocess doubles intentionally use dynamic signatures.
# ruff: noqa: ANN001, ANN003, ANN201, ANN202

import hashlib
import importlib.util
import io
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "ops/nas/preserved-runtime-env-preflight.py"
SPEC = importlib.util.spec_from_file_location("preserved_runtime_env_preflight", SCRIPT)
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)
OLD_COMMIT = "a" * 40
OLD_TREE = "b" * 40
NEW_COMMIT = "c" * 40
NEW_TREE = "d" * 40
CONFIG = b'{"os":"linux","architecture":"amd64"}'
IMAGE = "sha256:" + hashlib.sha256(CONFIG).hexdigest()
OCI_DIGEST = "sha256:" + "e" * 64
SYNTHETIC_MARKER = "synthetic-private-value-1234567890"


def _decode_gate_projection(raw):
    values = json.loads(raw)
    return {name: values[index] for index, (name, _) in enumerate(GATE.GATE_INSPECT_FIELDS)}


def _encode_gate_projection(data):
    return json.dumps([data[name] for name, _ in GATE.GATE_INSPECT_FIELDS]).encode()


def _directory(path):
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def _file(path, data, mode=0o400):
    _directory(path.parent)
    path.write_bytes(data if isinstance(data, bytes) else data.encode())
    path.chmod(mode)
    return path


def _replace(path, before, after):
    original_mode = path.stat().st_mode & 0o777
    path.chmod(0o600)
    path.write_text(path.read_text().replace(before, after))
    path.chmod(original_mode)


def _toml(fields, sections=None):
    lines = [
        f"{key} = true"
        if value is True
        else f"{key} = {value}"
        if type(value) is int
        else f'{key} = "{value}"'
        for key, value in fields.items()
    ]
    for section, values in (sections or {}).items():
        lines.append(f"[{section}]")
        lines.extend(f'{key} = "{value}"' for key, value in values.items())
    return "\n".join(lines) + "\n"


def _fixture(tmp_path):
    uid = os.getuid()
    root = _directory(tmp_path / "trusted")
    new = _directory(root / "new")
    old = _directory(root / "old")
    for source in (new, old):
        git = _directory(source / ".git")
        for member in ("config", "HEAD", "index"):
            _file(git / member, "synthetic\n", 0o600)
    old_compose = _file(old / "ops/nas/compose.example.yml", "services: synthetic\n", 0o644)
    _file(old / "ops/nas/status.sh", "#!/bin/sh\nexit 0\n", 0o700)
    _file(old / "ops/nas/container-python.sh", "#!/bin/sh\nexit 0\n", 0o700)
    _file(old / "ops/nas/validate-production-env.py", "# synthetic\n", 0o644)
    _file(old / "ops/nas/production-environment.schema.toml", "# synthetic\n", 0o644)
    proxy_config = _file(old / "ops/nas/proxy-allowlist.example.caddy", "# synthetic\n", 0o644)
    etc = _directory(root / "etc")
    canonical_compose = _file(etc / "compose.yml", old_compose.read_bytes())
    manifest_text = _toml(
        {
            "schema": "my-pa.nas-image-manifest.v1",
            "status": "deployable",
            "repository_commit": OLD_COMMIT,
            "repository_tree": OLD_TREE,
            "source_clean": True,
            "target_os": "linux",
            "target_architecture": "amd64",
            "docker_engine_id": "ENGINE",
            "docker_engine_name": "NAS",
        }
    )
    manifest = _file(etc / "image-manifest.toml", manifest_text)
    artifacts = _directory(root / "artifacts")
    manifest_member = json.dumps([{"Config": IMAGE[7:] + ".json"}]).encode()
    archive_stream = io.BytesIO()
    with tarfile.open(fileobj=archive_stream, mode="w") as archive_file:
        for member_name, content in (
            ("manifest.json", manifest_member),
            (IMAGE[7:] + ".json", CONFIG),
        ):
            member = tarfile.TarInfo(member_name)
            member.size = len(content)
            archive_file.addfile(member, io.BytesIO(content))
    archive_path = _file(artifacts / "operator.tar", archive_stream.getvalue())
    metadata_path = _file(
        artifacts / "metadata.json",
        json.dumps(
            {
                "containerimage.digest": OCI_DIGEST,
                "containerimage.config.digest": IMAGE,
            }
        ),
    )
    candidate_path = _file(
        artifacts / "candidate.toml",
        _toml(
            {
                "schema": "my-pa.nas-operator-runtime-candidate.v1",
                "status": "candidate_not_admitted",
                "repository_commit": OLD_COMMIT,
                "repository_tree": OLD_TREE,
                "built_at": "2026-09-01T00:00:00Z",
                "target_os": "linux",
                "target_architecture": "amd64",
                "oci_manifest_digest": OCI_DIGEST,
                "docker_image_id": IMAGE,
                "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
                "build_metadata_sha256": hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
            }
        ),
    )
    artifact_paths = {
        "archive": archive_path,
        "candidate": candidate_path,
        "metadata": metadata_path,
    }
    operator_fields = {
        "schema": "my-pa.nas-operator-runtime-admission.v1",
        "status": "admitted",
        "repository_commit": OLD_COMMIT,
        "repository_tree": OLD_TREE,
        "repository_source_path": str(old),
        "docker_engine_id": "ENGINE",
        "docker_engine_name": "NAS",
        "operator_image_id": IMAGE,
        "operator_manifest_digest": OCI_DIGEST,
        "python_version": "3.12.0",
        "git_version": "git version 2.0",
        "openssl_version": "OpenSSL 3.0",
        "compose_version": "v2.0.0",
    }
    for name in artifact_paths:
        operator_fields["operator_" + name + "_path"] = str(artifact_paths[name])
        operator_fields["operator_" + name + "_sha256"] = hashlib.sha256(
            artifact_paths[name].read_bytes()
        ).hexdigest()
    operator = _file(etc / "operator-runtime.toml", _toml(operator_fields))
    runtime = _file(
        etc / "runtime-admission.toml",
        _toml(
            {
                "schema": "my-pa.nas-runtime-admission.v1",
                "status": "admitted",
                "docker_engine_id": "ENGINE",
                "docker_engine_name": "NAS",
                "image_manifest_sha256": hashlib.sha256(manifest_text.encode()).hexdigest(),
            },
            {
                "resolved_compose_sha256": {"smoke": "f" * 64, "pilot": "0" * 64},
                "service_images": dict.fromkeys(GATE.SERVICES, IMAGE),
                "service_image_ids": dict.fromkeys(GATE.SERVICES, IMAGE),
            },
        ),
    )
    secrets = _directory(root / "secrets")
    nas = _file(secrets / "nas.aaaaaaaa.env", "MY_PA_DATABASE_URL=synthetic\n")
    web = _file(secrets / "web.aaaaaaaa.env", "MYPA_WEBAUTHN_BFF_SECRET=synthetic\n")
    container_id = "1" * 64
    ingress = _file(
        etc / "ingress-manifest.toml",
        _toml(
            {
                "schema": "my-pa.nas-ingress-evidence.v2",
                "status": "verified",
                "docker_engine_id": "ENGINE",
                "compose_project": "my-pa-nas-contract",
                "tailnet_hostname": "nas.example.ts.net",
                "canonical_origin": "https://nas.example.ts.net",
                "loopback_target": "127.0.0.1:8443",
                "proxy_config_sha256": hashlib.sha256(proxy_config.read_bytes()).hexdigest(),
                "proxy_uid": 1026,
                "proxy_gid": 100,
                "tailscale_version": "1.90.1",
                "web_env_file": str(web),
                "web_env_owner_uid": uid,
            },
            {
                "services." + name: {
                    "container_id": container_id if name == "proxy" else f"{index:064x}",
                    "image_id": IMAGE,
                }
                for index, name in enumerate(sorted(GATE.SERVICES), start=2)
            },
        ),
    )
    production = _file(
        secrets / "production.aaaaaaaa.env",
        "\n".join(
            [
                "MYPA_SOURCE_COMMIT=" + OLD_COMMIT,
                "MYPA_SOURCE_TREE=" + OLD_TREE,
                "MY_PA_NAS_ENV_FILE=" + str(nas),
                "MY_PA_WEB_ENV_FILE=" + str(web),
                "MY_PA_NAS_ROOT=/volume1/my-pa",
                "MYPA_CANONICAL_ORIGIN=https://pa.bobby-fetting.me",
                "MY_PA_APP_IMAGE_ID=" + IMAGE,
                "MY_PA_WEB_IMAGE_ID=" + IMAGE,
                "MY_PA_POSTGRES_IMAGE_ID=" + IMAGE,
                "MYPA_SESSION_SERVICE_SECRET=" + SYNTHETIC_MARKER,
                "",
            ]
        ),
    )
    calls = []
    gate_state = {"command": None, "cid": "9" * 64, "status": "absent", "exit": b"0\n"}

    def gate_inspect():
        command = gate_state["command"]
        name = command[command.index("--name") + 1]
        labels = {
            item.split("=", 1)[0]: item.split("=", 1)[1]
            for index, item_kind in enumerate(command[:-1])
            if item_kind == "--label"
            for item in [command[index + 1]]
        }
        binds = [
            command[index + 1] for index, item in enumerate(command[:-1]) if item == "--volume"
        ]
        mounts = []
        for bind in binds:
            source, destination, *options = bind.split(":")
            mounts.append(
                {
                    "Type": "bind",
                    "Source": source,
                    "Destination": destination,
                    "RW": not options or options[0] != "ro",
                }
            )
        image_index = command.index("--entrypoint") + 2
        return {
            "Id": gate_state["cid"],
            "Name": "/" + name,
            "Image": command[image_index],
            "ConfigImage": command[image_index],
            "Entrypoint": ["python"],
            "Cmd": command[image_index + 1 :],
            "Nonce": labels["io.my-pa.preflight-nonce"],
            "Kind": labels["io.my-pa.preflight-kind"],
            "User": "0:0",
            "Binds": binds,
            "Mounts": mounts,
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "Tmpfs": {"/tmp": "rw,nosuid,nodev,noexec,size=16m"},  # noqa: S108
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "Privileged": False,
            "AutoRemove": False,
            "Restart": "no",
            "LogType": "none",
            "Status": gate_state["status"],
            "Running": gate_state["status"] == "running",
        }

    def runner(argv, cwd=None, env=None, limit=65536, discard=False):
        calls.append((argv, cwd, env))
        if argv[0] == GATE.GIT:
            source = Path(argv[argv.index("-C") + 1])
            if argv[-1] == "--show-toplevel":
                return str(source).encode()
            if argv[-1] == "HEAD":
                return (NEW_COMMIT if source == new else OLD_COMMIT).encode()
            if argv[-1] == "HEAD^{tree}":
                return (NEW_TREE if source == new else OLD_TREE).encode()
            return b""
        if argv[:2] == [GATE.DOCKER, "info"]:
            return b"ENGINE|NAS"
        if argv[:3] == [GATE.DOCKER, "image", "inspect"]:
            assert ".Config.Env" not in argv[4]
            return "|".join(
                json.dumps(field)
                for field in [
                    IMAGE,
                    "linux",
                    "amd64",
                    OLD_COMMIT,
                    "2026-09-01T00:00:00Z",
                    OLD_TREE,
                    "python-3.12",
                    "linux/amd64",
                ]
            ).encode()
        if argv[:2] == [GATE.DOCKER, "inspect"]:
            assert argv[2] == "--format"
            assert ".Config.Env" not in argv[3]
            binding = [{"HostIp": "127.0.0.1", "HostPort": "8443"}]
            fields = [
                container_id,
                IMAGE,
                True,
                "my-pa-nas-contract",
                "proxy",
                {"8080/tcp": binding, "9090/tcp": None},
                {"8080/tcp": binding},
            ]
            return "|".join(json.dumps(field) for field in fields).encode()
        if argv[:2] == [GATE.DOCKER, "create"]:
            gate_state["command"] = argv
            gate_state["status"] = "created"
            assert discard is False
            return (gate_state["cid"] + "\n").encode()
        if argv[:3] == [GATE.DOCKER, "container", "inspect"]:
            assert argv[3] == "--format"
            assert argv[4] == GATE.GATE_INSPECT_FORMAT
            assert ".Config.Env" not in argv[4] and "{{json .}}" not in argv[4]
            assert limit == 16384
            command = gate_state["command"]
            name = command[command.index("--name") + 1] if command else None
            if gate_state["status"] == "absent" or argv[-1] not in (gate_state["cid"], name):
                raise GATE.RefusalError
            data = gate_inspect()
            return json.dumps([data[key] for key, _ in GATE.GATE_INSPECT_FIELDS]).encode()
        if argv[:2] == [GATE.DOCKER, "start"]:
            assert discard is True and argv[-1] == gate_state["cid"]
            gate_state["status"] = "running"
            return b""
        if argv[:2] == [GATE.DOCKER, "wait"]:
            assert argv[-1] == gate_state["cid"]
            gate_state["status"] = "exited"
            return gate_state["exit"]
        if argv[:2] == [GATE.DOCKER, "rm"]:
            assert argv == [GATE.DOCKER, "rm", "-f", gate_state["cid"]]
            gate_state["status"] = "absent"
            return b""
        if argv[:2] == [GATE.DOCKER, "ps"]:
            assert argv[2:5] == ["-a", "--no-trunc", "--filter"]
            return b"" if gate_state["status"] == "absent" else (gate_state["cid"] + "\n").encode()
        if argv == [str(old / "ops/nas/status.sh")]:
            return b"synthetic status"
        if argv[:2] == [
            str(old / "ops/nas/container-python.sh"),
            str(old / "ops/nas/validate-production-env.py"),
        ]:
            assert argv[2:] == [
                "--env",
                str(production),
                "--schema",
                str(old / "ops/nas/production-environment.schema.toml"),
                "--compose",
                str(old_compose),
            ]
            assert discard is True
            return b""
        raise AssertionError("unexpected subprocess")

    runner.gate_state = gate_state
    runner.gate_inspect = gate_inspect
    paths = {
        "uid": uid,
        "runner": runner,
        "tool_check": lambda *_: None,
        "socket_check": lambda *_: None,
        "trust_stop": root,
        "manifest": manifest,
        "operator_admission": operator,
        "runtime_admission": runtime,
        "ingress_manifest": ingress,
        "canonical_compose": canonical_compose,
        "secrets": secrets,
    }
    return new, old, paths, calls, production, operator, runtime, ingress


@pytest.mark.parametrize(
    "text",
    [
        "export KEY=value\n",
        "KEY=$(touch /tmp/unsafe)\n",
        "KEY=`whoami`\n",
        "KEY=one\nKEY=two\n",
        "KEY='quoted'\n",
        "KEY=foo\\bar\n",
        " KEY=value\n",
        "KEY=value\r\n",
        "KEY=line\ncontinuation\n",
    ],
)
def test_literal_environment_rejects_shell_syntax_and_duplicates(text):
    with pytest.raises(GATE.RefusalError):
        GATE._literal_env(text.encode())


def test_protected_file_rejects_symlink_hardlink_mode_and_owner(tmp_path, monkeypatch):
    root = _directory(tmp_path / "trusted")
    original = _file(root / "original", "synthetic")
    assert GATE._trusted_file(original, os.getuid(), stop=root) == b"synthetic"
    link = root / "link"
    link.symlink_to(original)
    with pytest.raises(GATE.RefusalError):
        GATE._trusted_file(link, os.getuid(), stop=root)
    hardlink = root / "hardlink"
    os.link(original, hardlink)
    with pytest.raises(GATE.RefusalError):
        GATE._trusted_file(original, os.getuid(), stop=root)
    hardlink.unlink()
    original.chmod(0o644)
    with pytest.raises(GATE.RefusalError):
        GATE._trusted_file(original, os.getuid(), stop=root)
    original.chmod(0o400)
    with pytest.raises(GATE.RefusalError):
        GATE._trusted_file(original, os.getuid() + 1, stop=root)
    root.chmod(0o777)
    with pytest.raises(GATE.RefusalError):
        GATE._trusted_file(original, os.getuid(), stop=root)


def test_fixed_success_only_invokes_read_only_identities_and_old_status(tmp_path):
    new, old, paths, calls, *_ = _fixture(tmp_path)
    GATE.verify(new, NEW_COMMIT, NEW_TREE, old, **paths)
    assert calls[-1][0] == [str(old / "ops/nas/status.sh")]
    assert calls[-2][0][:2] == [
        str(old / "ops/nas/container-python.sh"),
        str(old / "ops/nas/validate-production-env.py"),
    ]
    assert calls[-1][1] == old
    assert calls[-1][2]["MY_PA_LIFECYCLE_MODE"] == "smoke"
    assert calls[-1][2]["MY_PA_NAS_COMPOSE_FILE"] == str(old / "ops/nas/compose.example.yml")
    assert calls[-1][2]["MY_PA_PROXY_PORT"] == "8443"
    assert calls[-1][2]["MY_PA_TAILNET_HOST"] == "nas.example.ts.net"
    assert calls[-1][2]["MYPA_SESSION_SERVICE_SECRET"] == SYNTHETIC_MARKER
    assert all(SYNTHETIC_MARKER not in str(argv) for argv, _cwd, _env in calls)
    commands = [argv for argv, _cwd, _env in calls]
    gate_calls = [argv for argv in commands if argv[:2] == [GATE.DOCKER, "create"]]
    assert len(gate_calls) == 1
    assert commands.index(gate_calls[0]) < len(commands) - 2
    assert [argv[1] for argv in commands if argv[0] == GATE.DOCKER].count("start") == 1
    assert [argv[1] for argv in commands if argv[0] == GATE.DOCKER].count("wait") == 1
    assert [argv[1] for argv in commands if argv[0] == GATE.DOCKER].count("rm") == 1
    assert not any(argv[:2] == [GATE.DOCKER, "logs"] for argv in commands)


def test_baked_gate_exact_argv_mount_order_and_precedes_secret_loading(tmp_path):
    new, old, paths, calls, production, operator, _runtime, _ingress = _fixture(tmp_path)
    GATE.verify(new, NEW_COMMIT, NEW_TREE, old, **paths)
    gate = next(argv for argv, _cwd, _env in calls if argv[:2] == [GATE.DOCKER, "create"])
    nonce = gate[gate.index("--name") + 1][len("my-pa-preflight-") :]
    assert len(nonce) == 32 and all(char in "0123456789abcdef" for char in nonce)
    admitted = GATE._literal_toml(operator.read_bytes())
    manifest = paths["manifest"]
    archive = Path(admitted["operator_archive_path"])
    candidate = Path(admitted["operator_candidate_path"])
    metadata = Path(admitted["operator_metadata_path"])
    expected = [
        GATE.DOCKER,
        "create",
        "--name",
        "my-pa-preflight-" + nonce,
        "--label",
        "io.my-pa.preflight-nonce=" + nonce,
        "--label",
        "io.my-pa.preflight-kind=preserved-runtime-env",
        "--pull",
        "never",
        "--restart",
        "no",
        "--log-driver",
        "none",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=16m",  # noqa: S108 - container tmpfs
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "0:0",
        "--volume",
        "/run/docker.sock:/var/run/docker.sock",
        "--volume",
        str(GATE.DOCKER_REAL) + ":/usr/local/bin/docker:ro",
        "--volume",
        str(GATE.COMPOSE_REAL) + ":/usr/local/lib/docker/cli-plugins/docker-compose:ro",
        "--volume",
        str(operator) + ":/run/my-pa-input/admission.toml:ro",
        "--volume",
        str(archive) + ":/run/my-pa-input/operator.tar:ro",
        "--volume",
        str(candidate) + ":/run/my-pa-input/operator-candidate.toml:ro",
        "--volume",
        str(metadata) + ":/run/my-pa-input/operator-metadata.json:ro",
        "--volume",
        str(old) + ":/run/my-pa-input/current-source:ro",
        "--volume",
        str(manifest) + ":/run/my-pa-input/current-manifest.toml:ro",
        "--env",
        "MY_PA_NAS_DOCKER=/usr/local/bin/docker",
        "--env",
        "DOCKER_CLI_PLUGIN_EXTRA_DIRS=/usr/local/lib/docker/cli-plugins",
        "--entrypoint",
        "python",
        IMAGE,
        "/usr/local/libexec/my-pa-operator-pre-source-gate.py",
        "/run/my-pa-input/admission.toml",
        "/run/my-pa-input/current-source",
        "/run/my-pa-input/current-manifest.toml",
        str(operator),
        str(old),
        str(manifest),
        str(archive),
        str(candidate),
        str(metadata),
        "/run/my-pa-input/operator.tar",
        "/run/my-pa-input/operator-candidate.toml",
        "/run/my-pa-input/operator-metadata.json",
    ]
    assert gate == expected
    assert not any(str(production) in item for item in gate)
    assert all(".Config.Env" not in item for item in gate)


def test_baked_gate_refusal_prevents_old_wrapper(tmp_path):
    new, old, paths, calls, *_ = _fixture(tmp_path)
    real_runner = paths["runner"]

    def refuse_gate(argv, **kwargs):
        if argv[:2] == [GATE.DOCKER, "create"]:
            raise GATE.RefusalError
        return real_runner(argv, **kwargs)

    paths["runner"] = refuse_gate
    with pytest.raises(GATE.RefusalError):
        GATE.verify(new, NEW_COMMIT, NEW_TREE, old, **paths)
    assert not any(
        argv[0] == str(old / "ops/nas/container-python.sh")
        or argv == [str(old / "ops/nas/status.sh")]
        for argv, _cwd, _env in calls
    )


@pytest.mark.parametrize("stage", ["create", "start", "wait"])
def test_baked_gate_cli_timeout_cleans_authenticated_container_and_refuses(tmp_path, stage):
    new, old, paths, calls, *_ = _fixture(tmp_path)
    real_runner = paths["runner"]
    state = real_runner.gate_state
    tripped = False

    def timeout_after_daemon(argv, **kwargs):
        nonlocal tripped
        result = real_runner(argv, **kwargs)
        if argv[:2] == [GATE.DOCKER, stage] and not tripped:
            tripped = True
            raise subprocess.TimeoutExpired(argv, 1)
        return result

    paths["runner"] = timeout_after_daemon
    with pytest.raises(GATE.RefusalError):
        GATE.verify(new, NEW_COMMIT, NEW_TREE, old, **paths)
    assert state["status"] == "absent"
    commands = [argv for argv, _cwd, _env in calls]
    assert any(argv[:2] == [GATE.DOCKER, "rm"] for argv in commands)
    if stage == "create":
        assert not any(argv[:2] == [GATE.DOCKER, "start"] for argv in commands)
    assert not any(argv == [str(old / "ops/nas/status.sh")] for argv in commands)


def test_baked_gate_nonzero_exit_cleans_and_refuses(tmp_path):
    new, old, paths, calls, *_ = _fixture(tmp_path)
    paths["runner"].gate_state["exit"] = b"17\n"
    with pytest.raises(GATE.RefusalError):
        GATE.verify(new, NEW_COMMIT, NEW_TREE, old, **paths)
    assert paths["runner"].gate_state["status"] == "absent"
    assert not any(argv == [str(old / "ops/nas/status.sh")] for argv, _cwd, _env in calls)


def test_baked_gate_rm_timeout_retries_until_absence_proven(tmp_path):
    new, old, paths, calls, *_ = _fixture(tmp_path)
    real_runner = paths["runner"]
    failures = 0

    def timeout_first_remove(argv, **kwargs):
        nonlocal failures
        if argv[:2] == [GATE.DOCKER, "rm"] and failures == 0:
            failures += 1
            raise subprocess.TimeoutExpired(argv, 1)
        return real_runner(argv, **kwargs)

    paths["runner"] = timeout_first_remove
    GATE.verify(new, NEW_COMMIT, NEW_TREE, old, **paths)
    assert failures == 1
    assert real_runner.gate_state["status"] == "absent"
    assert any(argv == [str(old / "ops/nas/status.sh")] for argv, _cwd, _env in calls)


def test_baked_gate_daemon_outage_leaves_sanitized_unresolved_warning(tmp_path, capsys):
    new, old, paths, calls, *_ = _fixture(tmp_path)
    real_runner = paths["runner"]
    outage = False

    def lost_daemon(argv, **kwargs):
        nonlocal outage
        if argv[:2] == [GATE.DOCKER, "wait"]:
            outage = True
            raise subprocess.TimeoutExpired(argv, 1)
        if outage and argv[:2] == [GATE.DOCKER, "info"]:
            raise GATE.RefusalError
        return real_runner(argv, **kwargs)

    paths["runner"] = lost_daemon
    with pytest.raises(GATE.RefusalError):
        GATE.verify(new, NEW_COMMIT, NEW_TREE, old, **paths)
    warning = capsys.readouterr().err
    assert "unresolved container" in warning
    assert SYNTHETIC_MARKER not in warning
    assert real_runner.gate_state["status"] == "running"
    assert not any(argv[:2] == [GATE.DOCKER, "rm"] for argv, _cwd, _env in calls)


def test_baked_gate_late_create_is_never_started(tmp_path, capsys):
    new, old, paths, calls, *_ = _fixture(tmp_path)
    real_runner = paths["runner"]

    def lost_create(argv, **kwargs):
        if argv[:2] == [GATE.DOCKER, "create"]:
            raise subprocess.TimeoutExpired(argv, 1)
        return real_runner(argv, **kwargs)

    paths["runner"] = lost_create
    with pytest.raises(GATE.RefusalError):
        GATE.verify(new, NEW_COMMIT, NEW_TREE, old, **paths)
    assert "unresolved container" in capsys.readouterr().err
    assert not any(argv[:2] == [GATE.DOCKER, "start"] for argv, _cwd, _env in calls)


def test_baked_gate_foreign_name_collision_never_deletes_container(tmp_path, capsys):
    new, old, paths, calls, *_ = _fixture(tmp_path)
    real_runner = paths["runner"]

    def foreign_collision(argv, **kwargs):
        if argv[:2] == [GATE.DOCKER, "create"]:
            real_runner(argv, **kwargs)
            raise GATE.RefusalError
        if argv[:3] == [GATE.DOCKER, "container", "inspect"]:
            data = _decode_gate_projection(real_runner(argv, **kwargs))
            data["Nonce"] = "foreign"
            return _encode_gate_projection(data)
        return real_runner(argv, **kwargs)

    paths["runner"] = foreign_collision
    with pytest.raises(GATE.RefusalError):
        GATE.verify(new, NEW_COMMIT, NEW_TREE, old, **paths)
    assert "unresolved container" in capsys.readouterr().err
    assert real_runner.gate_state["status"] == "created"
    assert not any(argv[:2] == [GATE.DOCKER, "start"] for argv, _cwd, _env in calls)
    assert not any(argv[:2] == [GATE.DOCKER, "rm"] for argv, _cwd, _env in calls)


def test_baked_gate_repeated_rm_timeout_refuses_without_pass(tmp_path, capsys):
    new, old, paths, calls, *_ = _fixture(tmp_path)
    real_runner = paths["runner"]
    attempts = 0

    def stuck_remove(argv, **kwargs):
        nonlocal attempts
        if argv[:2] == [GATE.DOCKER, "rm"]:
            attempts += 1
            raise subprocess.TimeoutExpired(argv, 1)
        return real_runner(argv, **kwargs)

    paths["runner"] = stuck_remove
    with pytest.raises(GATE.RefusalError):
        GATE.verify(new, NEW_COMMIT, NEW_TREE, old, **paths)
    assert attempts == 3
    assert "unresolved container" in capsys.readouterr().err
    assert real_runner.gate_state["status"] == "exited"
    assert not any(argv == [str(old / "ops/nas/status.sh")] for argv, _cwd, _env in calls)


def test_baked_gate_sigterm_attempts_cleanup_and_restores_handler(tmp_path):
    new, old, paths, calls, *_ = _fixture(tmp_path)
    real_runner = paths["runner"]
    old_handler = signal.getsignal(signal.SIGTERM)

    def interrupted_wait(argv, **kwargs):
        if argv[:2] == [GATE.DOCKER, "wait"]:
            signal.raise_signal(signal.SIGTERM)
        return real_runner(argv, **kwargs)

    paths["runner"] = interrupted_wait
    with pytest.raises(GATE.RefusalError):
        GATE.verify(new, NEW_COMMIT, NEW_TREE, old, **paths)
    assert real_runner.gate_state["status"] == "absent"
    assert signal.getsignal(signal.SIGTERM) is old_handler
    assert not any(argv == [str(old / "ops/nas/status.sh")] for argv, _cwd, _env in calls)


@pytest.mark.parametrize("drift", ["name", "cid", "image", "mount", "engine"])
def test_baked_gate_identity_drift_never_starts_or_deletes_foreign_container(tmp_path, drift):
    new, old, paths, calls, *_ = _fixture(tmp_path)
    real_runner = paths["runner"]

    def drifted(argv, **kwargs):
        if (
            drift == "engine"
            and real_runner.gate_state["status"] == "created"
            and argv[:2] == [GATE.DOCKER, "info"]
        ):
            return b"FOREIGN|NAS"
        if argv[:3] == [GATE.DOCKER, "container", "inspect"]:
            data = _decode_gate_projection(real_runner(argv, **kwargs))
            if drift == "name":
                data["Name"] = "/foreign"
            elif drift == "cid":
                data["Id"] = "8" * 64
            elif drift == "image":
                data["Image"] = "sha256:" + "0" * 64
            elif drift == "mount":
                data["Mounts"][0]["Source"] = "/foreign"
            return _encode_gate_projection(data)
        return real_runner(argv, **kwargs)

    paths["runner"] = drifted
    with pytest.raises(GATE.RefusalError):
        GATE.verify(new, NEW_COMMIT, NEW_TREE, old, **paths)
    assert not any(argv[:2] == [GATE.DOCKER, "start"] for argv, _cwd, _env in calls)
    assert not any(argv[:2] == [GATE.DOCKER, "rm"] for argv, _cwd, _env in calls)
    assert real_runner.gate_state["status"] == "created"


@pytest.mark.parametrize(
    "security_options",
    [[], ["no-new-privileges:false"], ["no-new-privileges:true", "apparmor:unconfined"]],
    ids=["missing", "false", "extra"],
)
def test_baked_gate_security_options_drift_refuses_without_start_or_removal(
    tmp_path, security_options
):
    new, old, paths, calls, *_ = _fixture(tmp_path)
    real_runner = paths["runner"]

    def drifted(argv, **kwargs):
        if argv[:3] == [GATE.DOCKER, "container", "inspect"]:
            data = _decode_gate_projection(real_runner(argv, **kwargs))
            data["SecurityOpt"] = security_options
            return _encode_gate_projection(data)
        return real_runner(argv, **kwargs)

    paths["runner"] = drifted
    with pytest.raises(GATE.RefusalError):
        GATE.verify(new, NEW_COMMIT, NEW_TREE, old, **paths)
    assert not any(argv[:2] == [GATE.DOCKER, "start"] for argv, _cwd, _env in calls)
    assert not any(argv[:2] == [GATE.DOCKER, "rm"] for argv, _cwd, _env in calls)
    assert not any(argv == [str(old / "ops/nas/status.sh")] for argv, _cwd, _env in calls)
    assert real_runner.gate_state["status"] == "created"


def test_source_accepts_real_local_no_checkout_clone_after_checkout(tmp_path):
    git = shutil.which("git")
    if git is None:
        pytest.skip("Git unavailable")
    root = _directory(tmp_path / "trusted")
    origin = _directory(root / "origin")
    clone = root / "clone"

    def local(*args: str) -> str:
        return (
            subprocess.run(  # noqa: S603 - synthetic local Git fixture
                [git, *args],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            .stdout.decode()
            .strip()
        )

    local("init", "-q", str(origin))
    local("-C", str(origin), "config", "user.name", "Synthetic")
    local("-C", str(origin), "config", "user.email", "synthetic@example.invalid")
    _file(origin / "tracked.txt", "synthetic\n", 0o644)
    local("-C", str(origin), "add", "tracked.txt")
    local("-C", str(origin), "commit", "-q", "-m", "synthetic")
    commit = local("-C", str(origin), "rev-parse", "HEAD")
    tree = local("-C", str(origin), "rev-parse", "HEAD^{tree}")
    local("clone", "-q", "--no-checkout", str(origin), str(clone))
    clone.chmod(0o700)
    local("-C", str(clone), "reset", "--hard", "HEAD")
    GATE._source(clone, commit, tree, os.getuid(), GATE._run, root)


@pytest.mark.parametrize(
    "mutation",
    [
        "new_head",
        "source_dirty",
        "admission_source",
        "engine",
        "manifest",
        "runtime_hash",
        "mode",
        "environment",
        "proxy_port",
    ],
)
def test_identity_drift_refuses_before_old_status(tmp_path, mutation):
    new, old, paths, calls, production, operator, runtime, ingress = _fixture(tmp_path)
    real_runner = paths["runner"]
    if mutation == "new_head":
        paths["runner"] = lambda argv, **kw: (
            b"wrong" if argv[-1] == "HEAD" and str(new) in argv else real_runner(argv, **kw)
        )
    elif mutation == "source_dirty":
        paths["runner"] = lambda argv, **kw: (
            b"?? stray"
            if argv[-3:] == ["status", "--porcelain", "--untracked-files=all"]
            else real_runner(argv, **kw)
        )
    elif mutation == "admission_source":
        _replace(operator, str(old), str(new))
    elif mutation == "engine":
        paths["runner"] = lambda argv, **kw: (
            b"WRONG|NAS" if argv[:2] == [GATE.DOCKER, "info"] else real_runner(argv, **kw)
        )
    elif mutation == "manifest":
        _replace(paths["manifest"], 'status = "deployable"', 'status = "candidate"')
    elif mutation == "runtime_hash":
        _replace(runtime, "f" * 64, "bad")
    elif mutation == "mode":
        production.chmod(0o644)
    elif mutation == "environment":
        _replace(production, "MYPA_SOURCE_TREE=" + OLD_TREE, "MYPA_SOURCE_TREE=" + NEW_TREE)
    elif mutation == "proxy_port":
        _replace(ingress, "127.0.0.1:8443", "127.0.0.1:9443")
    with pytest.raises(GATE.RefusalError):
        GATE.verify(new, NEW_COMMIT, NEW_TREE, old, **paths)
    assert not any(argv == [str(old / "ops/nas/status.sh")] for argv, _cwd, _env in calls)


@pytest.mark.parametrize(
    "mutation",
    [
        "candidate",
        "archive",
        "metadata",
        "image_label",
        "ingress_service",
        "ingress_proxy_hash",
        "ingress_web_env",
        "mount_colon",
        "socket",
    ],
)
def test_pre_container_admission_drift_refuses_before_baked_gate(tmp_path, mutation):
    new, old, paths, calls, _production, operator, _runtime, ingress = _fixture(tmp_path)
    real_runner = paths["runner"]
    admitted = GATE._literal_toml(operator.read_bytes())
    if mutation in {"candidate", "archive", "metadata"}:
        item = Path(admitted["operator_" + mutation + "_path"])
        item.chmod(0o600)
        item.write_bytes(item.read_bytes() + b"drift")
        item.chmod(0o400)
    elif mutation == "image_label":

        def wrong_label(argv, **kwargs):
            if argv[:3] == [GATE.DOCKER, "image", "inspect"]:
                return real_runner(argv, **kwargs).replace(OLD_TREE.encode(), NEW_TREE.encode())
            return real_runner(argv, **kwargs)

        paths["runner"] = wrong_label
    elif mutation == "ingress_service":
        _replace(ingress, 'image_id = "' + IMAGE + '"', 'image_id = "sha256:' + "0" * 64 + '"')
    elif mutation == "ingress_proxy_hash":
        _replace(ingress, 'proxy_config_sha256 = "', 'proxy_config_sha256 = "bad')
    elif mutation == "ingress_web_env":
        _replace(ingress, 'web_env_file = "', 'web_env_file = "/wrong')
    elif mutation == "mount_colon":
        _replace(
            operator, admitted["operator_archive_path"], admitted["operator_archive_path"] + ":x"
        )
    else:
        paths["socket_check"] = lambda *_: (_ for _ in ()).throw(GATE.RefusalError())
    with pytest.raises(GATE.RefusalError):
        GATE.verify(new, NEW_COMMIT, NEW_TREE, old, **paths)
    assert not any(argv[:2] == [GATE.DOCKER, "create"] for argv, _cwd, _env in calls)


@pytest.mark.parametrize("mutation", ["duplicate_member", "config_digest", "duplicate_json_key"])
def test_operator_archive_parser_rejects_malformed_identity(tmp_path, mutation):
    root = _directory(tmp_path / "trusted")
    config_name = IMAGE[7:] + ".json"
    manifest = json.dumps([{"Config": config_name}]).encode()
    config = CONFIG
    if mutation == "config_digest":
        config += b" "
    if mutation == "duplicate_json_key":
        manifest = ('[{"Config":"' + config_name + '","Config":"' + config_name + '"}]').encode()
    members = [("manifest.json", manifest), (config_name, config)]
    if mutation == "duplicate_member":
        members.append(("manifest.json", manifest))
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive_file:
        for name, content in members:
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive_file.addfile(member, io.BytesIO(content))
    archive_path = _file(root / "operator.tar", stream.getvalue())
    with pytest.raises(GATE.RefusalError):
        GATE._archive_config_id(archive_path, os.getuid(), root)


def test_wrong_cli_shape_has_generic_refusal(capsys):
    assert GATE.main(["unused", "args"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Preserved runtime preflight refused\n"


def test_tool_identity_rejects_writable_and_symlink(tmp_path):
    root = _directory(tmp_path / "trusted")
    binary = _file(root / "docker", b"synthetic", 0o755)
    GATE._trusted_executable(str(binary), os.getuid(), root)
    binary.chmod(0o777)
    with pytest.raises(GATE.RefusalError):
        GATE._trusted_executable(str(binary), os.getuid(), root)
    binary.chmod(0o755)
    link = root / "docker-link"
    link.symlink_to(binary)
    with pytest.raises(GATE.RefusalError):
        GATE._trusted_executable(str(link), os.getuid(), root)


def test_physical_socket_rejects_symlink_mode_and_owner(tmp_path, monkeypatch):
    root = _directory(tmp_path / "trusted")
    endpoint = _file(root / "docker.sock", b"synthetic")
    real_lstat = Path.lstat
    attributes = {"mode": stat.S_IFSOCK | 0o660, "uid": os.getuid(), "gid": 0}

    def fake_lstat(path):
        result = real_lstat(path)
        if path != endpoint:
            return result
        fields = list(result)
        fields[0] = attributes["mode"]
        fields[4] = attributes["uid"]
        fields[5] = attributes["gid"]
        return os.stat_result(fields)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    GATE._trusted_socket(endpoint, os.getuid(), root)
    link = root / "alias.sock"
    link.symlink_to(endpoint)
    with pytest.raises(GATE.RefusalError):
        GATE._trusted_socket(link, os.getuid(), root)
    attributes["mode"] = stat.S_IFSOCK | 0o666
    with pytest.raises(GATE.RefusalError):
        GATE._trusted_socket(endpoint, os.getuid(), root)
    attributes["mode"] = stat.S_IFSOCK | 0o660
    attributes["uid"] = os.getuid() + 1
    with pytest.raises(GATE.RefusalError):
        GATE._trusted_socket(endpoint, os.getuid(), root)
    attributes["uid"] = os.getuid()
    attributes["gid"] = 1
    with pytest.raises(GATE.RefusalError):
        GATE._trusted_socket(endpoint, os.getuid(), root)


def _tool_chain(root, package, relative, links=1):
    alias = root / ("usr/local/bin/docker" if package == "ContainerManager" else "usr/bin/git")
    store = root / "volume1/@appstore" / package
    real = _file(store / relative, b"synthetic executable", 0o755)
    for index in range(links - 1):
        os.link(real, store / f"hardlink-{index}")
    store_alias = root / "var/packages" / package / "target"
    _directory(store_alias.parent)
    store_alias.symlink_to(store)
    alias_target = store_alias / relative
    _directory(alias.parent)
    alias.symlink_to(alias_target)
    return alias, alias_target, store_alias, store, real


def test_fixed_synology_docker_chain_accepts_only_exact_links(tmp_path, monkeypatch):
    root = _directory(tmp_path / "trusted")
    alias, alias_target, store_alias, store, real = _tool_chain(
        root, "ContainerManager", "usr/bin/docker"
    )
    monkeypatch.setattr(GATE, "DOCKER", str(alias))
    monkeypatch.setattr(GATE, "DOCKER_ALIAS_TARGET", alias_target)
    monkeypatch.setattr(GATE, "DOCKER_STORE_ALIAS", store_alias)
    monkeypatch.setattr(GATE, "DOCKER_STORE_TARGET", store)
    monkeypatch.setattr(GATE, "DOCKER_REAL", real)
    GATE._trusted_executable(str(alias), os.getuid(), root)
    alias.unlink()
    alias.symlink_to(store / "usr/bin/docker")
    with pytest.raises(GATE.RefusalError):
        GATE._trusted_executable(str(alias), os.getuid(), root)
    alias.unlink()
    alias.symlink_to(alias_target)
    store_alias.unlink()
    store_alias.symlink_to(root / "other-package")
    with pytest.raises(GATE.RefusalError):
        GATE._trusted_executable(str(alias), os.getuid(), root)
    store_alias.unlink()
    store_alias.symlink_to(store)
    real.chmod(0o777)
    with pytest.raises(GATE.RefusalError):
        GATE._trusted_executable(str(alias), os.getuid(), root)
    real.chmod(0o755)
    alias.parent.chmod(0o777)
    with pytest.raises(GATE.RefusalError):
        GATE._trusted_executable(str(alias), os.getuid(), root)


def test_fixed_synology_git_chain_accepts_only_reviewed_hardlink_count(tmp_path, monkeypatch):
    root = _directory(tmp_path / "trusted")
    alias, alias_target, store_alias, store, real = _tool_chain(root, "Git", "bin/git", 142)
    monkeypatch.setattr(GATE, "GIT", str(alias))
    monkeypatch.setattr(GATE, "GIT_ALIAS_TARGET", alias_target)
    monkeypatch.setattr(GATE, "GIT_STORE_ALIAS", store_alias)
    monkeypatch.setattr(GATE, "GIT_STORE_TARGET", store)
    monkeypatch.setattr(GATE, "GIT_REAL", real)
    GATE._trusted_executable(str(alias), os.getuid(), root)
    (store / "hardlink-0").unlink()
    with pytest.raises(GATE.RefusalError):
        GATE._trusted_executable(str(alias), os.getuid(), root)


@pytest.mark.parametrize("key", ["PATH", "DOCKER_HOST", "PYTHONPATH", "GIT_CONFIG_GLOBAL"])
def test_environment_cannot_override_process_controls(key):
    with pytest.raises(GATE.RefusalError):
        GATE._literal_env((key + "=synthetic\n").encode(), GATE.PRODUCTION_KEYS)
    with pytest.raises(GATE.RefusalError):
        GATE._safe_environment({key: "synthetic"})


def test_streaming_capture_caps_live_producer_and_kills_descendant_group(
    tmp_path, monkeypatch, capsys
):
    real_popen = subprocess.Popen
    real_killpg = os.killpg
    launched = []
    killed = []

    def launch(argv, **kwargs):
        process = real_popen(argv, **kwargs)
        launched.append((process, kwargs))
        return process

    def kill_group(pgid, sig):
        killed.append((pgid, sig))
        return real_killpg(pgid, sig)

    monkeypatch.setattr(GATE.subprocess, "Popen", launch)
    monkeypatch.setattr(GATE.os, "killpg", kill_group)
    ready = tmp_path / "descendant-ready"
    survived = tmp_path / "descendant-survived"
    program = (
        "import os,sys,time\nfrom pathlib import Path\n"
        f"ready=Path({str(ready)!r}); survived=Path({str(survived)!r})\n"
        "if os.fork() == 0:\n"
        "    ready.write_text('ready')\n"
        "    time.sleep(0.5)\n"
        "    survived.write_text('survived')\n"
        "    os._exit(0)\n"
        "while not ready.exists(): time.sleep(0.01)\n"
        "sys.stdout.buffer.write(b'x' * 4096); sys.stdout.flush(); time.sleep(20)\n"
    )
    with pytest.raises(GATE.RefusalError):
        GATE._run([sys.executable, "-c", program], limit=32, timeout_seconds=2)
    assert launched[0][1]["start_new_session"] is True
    assert ready.exists()
    assert launched[0][0].returncode is not None
    assert killed == [(launched[0][0].pid, signal.SIGKILL)]
    time.sleep(0.7)
    assert not survived.exists()
    assert capsys.readouterr() == ("", "")


def test_streaming_capture_timeout_kills_process_group(monkeypatch):
    real_popen = subprocess.Popen
    real_killpg = os.killpg
    launched = []
    killed = []

    def launch(argv, **kwargs):
        process = real_popen(argv, **kwargs)
        launched.append(process)
        return process

    def kill_group(pgid, sig):
        killed.append((pgid, sig))
        return real_killpg(pgid, sig)

    monkeypatch.setattr(GATE.subprocess, "Popen", launch)
    monkeypatch.setattr(GATE.os, "killpg", kill_group)
    with pytest.raises(subprocess.TimeoutExpired):
        GATE._run(
            [sys.executable, "-c", "import time; time.sleep(20)"],
            timeout_seconds=0.1,
        )
    assert launched[0].returncode is not None
    assert killed == [(launched[0].pid, signal.SIGKILL)]


def test_capture_within_limit_and_status_output_discarded(capsys):
    assert GATE._run([sys.executable, "-c", "print('ok', end='')"], limit=2) == b"ok"
    program = "import sys; print('private'); print('private', file=sys.stderr)"
    assert GATE._run([sys.executable, "-c", program], discard=True) == b""
    assert capsys.readouterr() == ("", "")
