"""Preserved-runtime backups authenticate both source roles and current firewall."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import platform
import subprocess
import sys
import tarfile
import tomllib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
CURRENT_COMMIT = "1" * 40
CURRENT_TREE = "2" * 40
PRESERVED_COMMIT = "3" * 40
PRESERVED_TREE = "4" * 40
POSTGRES_REFERENCE = (
    "postgres@sha256:dbbeb22a65db2503050cdbbe5e78f017478f10a1002a226463f049dbb017e99b"
)
POSTGRES_INDEX_DIGEST = "sha256:7958605b474b3d264a969cb3a123d6aa00ad1e1fe9da8a69984dabb704d93317"
OPERATOR_IMAGE_ID = "sha256:" + "d" * 64
OPERATOR_MANIFEST_DIGEST = "sha256:" + "e" * 64
COMPOSE_VERSION = "2.20.1"
GIT_VERSION = subprocess.run(
    ["/usr/bin/git", "--version"], check=True, capture_output=True, text=True
).stdout.strip()
OPENSSL_VERSION = "OpenSSL 3.0.0 synthetic"


def _gate() -> ModuleType:
    path = ROOT / "ops/nas/preserved_backup_gate.py"
    spec = importlib.util.spec_from_file_location("nas_preserved_backup_gate", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _pre_source_gate() -> ModuleType:
    path = ROOT / "ops/nas/operator_pre_source_gate.py"
    spec = importlib.util.spec_from_file_location("nas_operator_pre_source_gate", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _manifest(path: Path, commit: str, tree: str) -> None:
    sections: list[str] = []
    for index, name in enumerate(("app", "web", "postgres", "proxy"), start=1):
        digest = (
            POSTGRES_REFERENCE.rpartition("@")[2]
            if name == "postgres"
            else "sha256:" + str(index) * 64
        )
        image_id = "sha256:" + str(index + 4) * 64
        checksum = "89ab"[index - 1] * 64
        reference = POSTGRES_REFERENCE if name == "postgres" else f"example.invalid/{name}@{digest}"
        sections.append(
            f"\n[images.{name}]\n"
            f'reference = "{reference}"\n'
            f'load_reference = "{image_id}"\n'
            f'oci_manifest_digest = "{digest}"\n'
            f'docker_image_id = "{image_id}"\n'
            f'archive_sha256 = "{checksum}"\n'
            f'build_metadata_sha256 = "{checksum}"\n'
        )
    path.write_text(
        'schema = "my-pa.nas-image-manifest.v1"\n'
        'status = "deployable"\n'
        f'repository_commit = "{commit}"\n'
        f'repository_tree = "{tree}"\n'
        "source_clean = true\n"
        'built_at = "2026-09-06T12:00:00Z"\n'
        'target_os = "linux"\n'
        'target_architecture = "amd64"\n'
        'docker_engine_id = "engine-id"\n'
        'docker_engine_name = "engine-name"\n'
        f'python_runtime_lock_sha256 = "{"c" * 64}"\n'
        'postgres_source_tag = "postgres:17.10"\n'
        f'postgres_index_digest = "{POSTGRES_INDEX_DIGEST}"\n' + "".join(sections),
        encoding="utf-8",
    )


def _operator_artifacts(tmp_path: Path) -> tuple[Path, Path, Path]:
    config_name = OPERATOR_IMAGE_ID.removeprefix("sha256:") + ".json"
    archive = tmp_path / "operator.tar"
    archive_manifest = json.dumps([{"Config": config_name, "RepoTags": [], "Layers": []}]).encode()
    with tarfile.open(archive, "w") as stream:
        info = tarfile.TarInfo("manifest.json")
        info.size = len(archive_manifest)
        stream.addfile(info, io.BytesIO(archive_manifest))
    metadata = tmp_path / "operator.metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "containerimage.digest": OPERATOR_MANIFEST_DIGEST,
                "containerimage.config.digest": OPERATOR_IMAGE_ID,
            }
        ),
        encoding="utf-8",
    )
    candidate = tmp_path / "operator.toml"
    candidate.write_text(
        'schema = "my-pa.nas-operator-runtime-candidate.v1"\n'
        'status = "candidate_not_admitted"\n'
        f'repository_commit = "{CURRENT_COMMIT}"\n'
        f'repository_tree = "{CURRENT_TREE}"\n'
        'built_at = "2026-09-06T12:00:00Z"\n'
        'target_os = "linux"\n'
        'target_architecture = "amd64"\n'
        f'oci_manifest_digest = "{OPERATOR_MANIFEST_DIGEST}"\n'
        f'docker_image_id = "{OPERATOR_IMAGE_ID}"\n'
        f'archive_sha256 = "{hashlib.sha256(archive.read_bytes()).hexdigest()}"\n'
        f'build_metadata_sha256 = "{hashlib.sha256(metadata.read_bytes()).hexdigest()}"\n',
        encoding="utf-8",
    )
    for artifact in (archive, metadata, candidate):
        artifact.chmod(0o400)
    return archive, candidate, metadata


def _operator_admission(
    path: Path, archive: Path, candidate: Path, metadata: Path, *, source: Path
) -> None:
    path.write_text(
        'schema = "my-pa.nas-operator-runtime-admission.v1"\n'
        'status = "admitted"\n'
        f'repository_commit = "{CURRENT_COMMIT}"\n'
        f'repository_tree = "{CURRENT_TREE}"\n'
        f'repository_source_path = "{source}"\n'
        'docker_engine_id = "engine-id"\n'
        'docker_engine_name = "engine-name"\n'
        f'operator_image_id = "{OPERATOR_IMAGE_ID}"\n'
        f'operator_manifest_digest = "{OPERATOR_MANIFEST_DIGEST}"\n'
        f'operator_archive_path = "{archive}"\n'
        f'operator_archive_sha256 = "{hashlib.sha256(archive.read_bytes()).hexdigest()}"\n'
        f'operator_candidate_path = "{candidate}"\n'
        f'operator_candidate_sha256 = "{hashlib.sha256(candidate.read_bytes()).hexdigest()}"\n'
        f'operator_metadata_path = "{metadata}"\n'
        f'operator_metadata_sha256 = "{hashlib.sha256(metadata.read_bytes()).hexdigest()}"\n'
        f'python_version = "{platform.python_version()}"\n'
        f'git_version = "{GIT_VERSION}"\n'
        f'openssl_version = "{OPENSSL_VERSION}"\n'
        f'compose_version = "{COMPOSE_VERSION}"\n',
        encoding="utf-8",
    )
    path.chmod(0o400)


def _sources(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path, Path]:
    current = tmp_path / "current"
    preserved = tmp_path / "preserved"
    current.mkdir()
    (preserved / "ops/nas").mkdir(parents=True)
    compose = preserved / "ops/nas/compose.example.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    current_manifest = tmp_path / "current.toml"
    preserved_manifest = tmp_path / "preserved.toml"
    _manifest(current_manifest, CURRENT_COMMIT, CURRENT_TREE)
    _manifest(preserved_manifest, PRESERVED_COMMIT, PRESERVED_TREE)
    operator_admission = tmp_path / "operator-runtime.toml"
    _operator_admission(operator_admission, *_operator_artifacts(tmp_path), source=current)
    return current, preserved, compose, current_manifest, preserved_manifest, operator_admission


def _runner(
    current: Path,
    preserved: Path,
    *,
    current_dirty: bool = False,
    current_commit: str = CURRENT_COMMIT,
    preserved_commit: str = PRESERVED_COMMIT,
) -> Callable[[list[str]], str]:
    def run(command: list[str]) -> str:
        if command == ["git", "--version"]:
            return GIT_VERSION
        if command == ["/usr/bin/openssl", "version"]:
            return OPENSSL_VERSION
        if command[-3:] == ["compose", "version", "--short"]:
            return COMPOSE_VERSION
        if command[-3:] == ["info", "--format", "{{json .}}"]:
            return json.dumps({"ID": "engine-id", "Name": "engine-name"})
        if len(command) >= 4 and command[-3:-1] == ["image", "inspect"]:
            return json.dumps(
                [
                    {
                        "Id": OPERATOR_IMAGE_ID,
                        "Os": "linux",
                        "Architecture": "amd64",
                        "Config": {
                            "Labels": {
                                "org.opencontainers.image.revision": CURRENT_COMMIT,
                                "org.opencontainers.image.created": "2026-09-06T12:00:00Z",
                                "io.my-pa.repository-tree": CURRENT_TREE,
                                "io.my-pa.target-platform": "linux/amd64",
                                "io.my-pa.operator-runtime": "python-3.12",
                            }
                        },
                    }
                ]
            )
        source = Path(command[2])
        suffix = command[3:]
        if suffix == ["rev-parse", "HEAD"]:
            return current_commit if source == current else preserved_commit
        if suffix == ["rev-parse", "HEAD^{tree}"]:
            return CURRENT_TREE if source == current else PRESERVED_TREE
        if suffix == ["rev-parse", "--show-toplevel"]:
            return str(source)
        if suffix == ["status", "--porcelain", "--untracked-files=all"]:
            return " M ops/nas/x" if source == current and current_dirty else ""
        raise AssertionError(command)

    return run


def test_source_roles_require_full_exact_clean_manifest_identities(tmp_path: Path) -> None:
    gate = _gate()
    current, preserved, compose, current_manifest, preserved_manifest, _operator_admission_path = (
        _sources(tmp_path)
    )
    assert (
        gate.verify(
            current,
            current_manifest,
            preserved,
            preserved_manifest,
            compose,
            expected_current_source=current,
            runner=_runner(current, preserved),
        )
        == []
    )
    current_manifest.write_text(
        'schema = "my-pa.nas-image-manifest.v1"\n'
        'status = "deployable"\n'
        f'repository_commit = "{CURRENT_COMMIT}"\n'
        f'repository_tree = "{CURRENT_TREE}"\n',
        encoding="utf-8",
    )
    assert "current_gate_manifest_shape" in gate.verify(
        current,
        current_manifest,
        preserved,
        preserved_manifest,
        compose,
        expected_current_source=current,
        runner=_runner(current, preserved),
    )
    _manifest(current_manifest, CURRENT_COMMIT, CURRENT_TREE)
    _manifest(current_manifest, CURRENT_COMMIT, CURRENT_TREE)
    with current_manifest.open("a", encoding="utf-8") as stream:
        stream.write('unexpected = "refuse"\n')
    assert "current_gate_manifest_shape" in gate.verify(
        current,
        current_manifest,
        preserved,
        preserved_manifest,
        compose,
        expected_current_source=current,
        runner=_runner(current, preserved),
    )


def test_pre_source_gate_binds_complete_external_and_live_identities(tmp_path: Path) -> None:
    gate = _pre_source_gate()
    current, _preserved, _compose, current_manifest, _old_manifest, admission = _sources(tmp_path)
    runner = _runner(current, current)
    assert (
        gate.verify(admission, current, current_manifest, owner_uid=os.getuid(), runner=runner)
        == []
    )
    original = admission.read_text(encoding="utf-8")

    def replaced(name: str, value: str) -> str:
        return (
            "\n".join(
                f'{name} = "{value}"' if line.startswith(f"{name} = ") else line
                for line in original.splitlines()
            )
            + "\n"
        )

    mutations = (
        ("operator_admission_shape", "\n".join(original.splitlines()[:-1]) + "\n"),
        ("operator_admission_shape", original + 'unexpected = "refuse"\n'),
        ("operator_archive_checksum", replaced("operator_archive_sha256", "0" * 64)),
        ("operator_candidate_checksum", replaced("operator_candidate_sha256", "0" * 64)),
        ("operator_metadata_checksum", replaced("operator_metadata_sha256", "0" * 64)),
        ("operator_artifact_metadata", replaced("operator_archive_path", "/missing/archive")),
        ("operator_artifact_metadata", replaced("operator_candidate_path", "/missing/candidate")),
        ("operator_artifact_metadata", replaced("operator_metadata_path", "/missing/metadata")),
        (
            "operator_artifact_binding",
            replaced("operator_manifest_digest", "sha256:" + "9" * 64),
        ),
        ("operator_artifact_binding", replaced("operator_image_id", "sha256:" + "9" * 64)),
        ("current_engine_identity", replaced("docker_engine_id", "other")),
        ("operator_artifact_binding", replaced("repository_commit", "9" * 40)),
    )

    def no_live_command(command: list[str]) -> str:
        raise AssertionError(f"malformed admission reached live command: {command}")

    for expected, value in mutations:
        admission.chmod(0o600)
        admission.write_text(value, encoding="utf-8")
        admission.chmod(0o400)
        assert expected in gate.verify(
            admission,
            current,
            current_manifest,
            owner_uid=os.getuid(),
            runner=no_live_command if expected == "operator_admission_shape" else runner,
        )
    admission.chmod(0o600)
    admission.write_text(original, encoding="utf-8")
    admission.chmod(0o400)
    candidate_path = Path(str(tomllib.loads(original)["operator_candidate_path"]))
    candidate_original = candidate_path.read_text(encoding="utf-8")
    candidate_mutations = (
        (
            "candidate_shape",
            candidate_original.replace("my-pa.nas-operator-runtime-candidate.v1", "wrong"),
        ),
        ("candidate_shape", candidate_original.replace("candidate_not_admitted", "admitted")),
        (
            "candidate_platform",
            candidate_original.replace('target_os = "linux"', 'target_os = "darwin"'),
        ),
        (
            "candidate_platform",
            candidate_original.replace(
                'target_architecture = "amd64"', 'target_architecture = "arm64"'
            ),
        ),
        (
            "candidate_built_at",
            candidate_original.replace(
                'built_at = "2026-09-06T12:00:00Z"', 'built_at = "not-a-time"'
            ),
        ),
        (
            "operator_image_identity",
            candidate_original.replace(
                'built_at = "2026-09-06T12:00:00Z"', 'built_at = "2026-09-06T12:00:01Z"'
            ),
        ),
        ("candidate_shape", "\n".join(candidate_original.splitlines()[:-1]) + "\n"),
        ("candidate_shape", candidate_original + 'unexpected = "refuse"\n'),
    )
    for expected, candidate_value in candidate_mutations:
        candidate_path.chmod(0o600)
        candidate_path.write_text(candidate_value, encoding="utf-8")
        candidate_path.chmod(0o400)
        admission.chmod(0o600)
        admission.write_text(
            replaced(
                "operator_candidate_sha256",
                hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
            ),
            encoding="utf-8",
        )
        admission.chmod(0o400)
        assert expected in gate.verify(
            admission,
            current,
            current_manifest,
            owner_uid=os.getuid(),
            runner=runner if expected == "operator_image_identity" else no_live_command,
        )
    candidate_path.chmod(0o600)
    candidate_path.write_text(candidate_original, encoding="utf-8")
    candidate_path.chmod(0o400)
    admission.chmod(0o600)
    admission.write_text(original, encoding="utf-8")
    admission.chmod(0o400)
    current_manifest.write_text(
        current_manifest.read_text(encoding="utf-8") + 'unexpected = "refuse"\n',
        encoding="utf-8",
    )
    assert "current_gate_manifest_shape" in gate.verify(
        admission, current, current_manifest, owner_uid=os.getuid(), runner=runner
    )
    admitted = tomllib.loads(admission.read_text(encoding="utf-8"))
    host_paths = {
        "admission": admission,
        "current_source": current,
        "current_manifest": current_manifest,
        "archive": Path(str(admitted["operator_archive_path"])),
        "candidate": Path(str(admitted["operator_candidate_path"])),
        "metadata": Path(str(admitted["operator_metadata_path"])),
    }
    for hostile in (
        Path("/usr/local"),
        Path("/usr/local/bin/docker"),
        Path("/usr/local/libexec/my-pa-operator-pre-source-gate.py"),
    ):
        assert "operator_input_path_identity" in gate.verify(
            admission,
            current,
            current_manifest,
            expected_host_paths={**host_paths, "current_source": hostile},
            owner_uid=os.getuid(),
            runner=no_live_command,
        )


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("wrong_current", "current_gate_source"),
        ("missing_current_manifest", "current_gate_manifest_unreadable"),
        ("dirty_current", "current_gate_source_dirty"),
        ("drifted_current", "current_gate_source_drift"),
        ("old_identity_mismatch", "preserved_source_drift"),
    ],
)
def test_source_roles_refuse_wrong_missing_dirty_or_drifted_identity(
    tmp_path: Path, case: str, expected: str
) -> None:
    gate = _gate()
    current, preserved, compose, current_manifest, preserved_manifest, _operator_admission_path = (
        _sources(tmp_path)
    )
    expected_source = current
    runner = _runner(current, preserved)
    if case == "wrong_current":
        expected_source = tmp_path / "other"
        expected_source.mkdir()
    elif case == "missing_current_manifest":
        current_manifest.unlink()
    elif case == "dirty_current":
        runner = _runner(current, preserved, current_dirty=True)
    elif case == "drifted_current":
        runner = _runner(current, preserved, current_commit="5" * 40)
    else:
        runner = _runner(current, preserved, preserved_commit="6" * 40)
    errors = gate.verify(
        current,
        current_manifest,
        preserved,
        preserved_manifest,
        compose,
        expected_current_source=expected_source,
        runner=runner,
    )
    assert expected in errors


def _write_executable(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o755)


def _backup_environment(
    tmp_path: Path, *, firewall_passes: bool, rejected_gate: str = ""
) -> tuple[dict[str, str], Path]:
    binary = tmp_path / "bin"
    binary.mkdir()
    log = tmp_path / "commands.log"
    docker = binary / "docker"
    operator_inspect = json.dumps(
        [
            {
                "Id": OPERATOR_IMAGE_ID,
                "Os": "linux",
                "Architecture": "amd64",
                "Config": {
                    "Labels": {
                        "org.opencontainers.image.revision": CURRENT_COMMIT,
                        "org.opencontainers.image.created": "2026-09-06T12:00:00Z",
                        "io.my-pa.repository-tree": CURRENT_TREE,
                        "io.my-pa.target-platform": "linux/amd64",
                        "io.my-pa.operator-runtime": "python-3.12",
                    }
                },
            }
        ],
        separators=(",", ":"),
    )
    engine_info = json.dumps({"ID": "engine-id", "Name": "engine-name"}, separators=(",", ":"))
    network_id = "a" * 64
    network_state = (
        f"{network_id}|my-pa-nas-contract_data-plane|bridge|local|true|"
        "my-pa-nas-contract|data-plane|172.20.0.0/24"
    )
    _write_executable(
        docker,
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> '{log}'\n"
        'case "$*" in *"forged-current"*) exit 1;; esac\n'
        '[ "$1" != run ] || [ "${MY_TEST_PRE_SOURCE_REFUSE:-0}" != 1 ] || exit 1\n'
        'case "$*" in\n'
        f"  *\"image inspect {OPERATOR_IMAGE_ID}\"*) echo '{operator_inspect}';;\n"
        f"  *\"info --format {{{{json .}}}}\"*) echo '{engine_info}';;\n"
        '  *"info --format"*) echo engine-id\\|engine-name;;\n'
        f'  *"compose version --short"*) echo {COMPOSE_VERSION};;\n'
        f"  *\"network inspect --format\"*) echo '{network_state}';;\n"
        '  *compose*"ps -q postgres"*) echo pg-id;;\n'
        '  *"exec -i pg-id pg_dump"*) printf synthetic-dump;;\n'
        '  *"exec -i pg-id pg_restore --list"*) exit 0;;\n'
        '  *"exec -i pg-id sh -eu -c"*) exit 0;;\n'
        "esac\n",
    )
    compose_plugin = binary / "docker-compose"
    _write_executable(compose_plugin, "#!/bin/sh\nexit 0\n")
    python = binary / "python"
    rejected_case = f'case "$*" in *"{rejected_gate}"*) exit 1;; esac\n' if rejected_gate else ""
    _write_executable(
        python,
        "#!/bin/sh\n"
        f"printf 'python %s\\n' \"$*\" >> '{log}'\n"
        + rejected_case
        + 'case "${1:-}" in -c) exit 0;; esac\n'
        "exit 0\n",
    )
    ip = binary / "ip"
    _write_executable(ip, "#!/bin/sh\nexit 0\n")
    iptables = binary / "iptables"
    data_plane_rules = [
        "-A MY_PA_DATA_PLANE -s 172.20.0.0/24 -d 172.20.0.0/24 "
        "-i docker-aaaaaaaa -o docker-aaaaaaaa -j ACCEPT",
        "-A MY_PA_DATA_PLANE -i docker-aaaaaaaa -j DROP",
        "-A MY_PA_DATA_PLANE -o docker-aaaaaaaa -j DROP",
        "-A MY_PA_DATA_PLANE -j RETURN",
    ]
    rendered_rules = " ".join(f"'{rule}'" for rule in data_plane_rules)
    _write_executable(
        iptables,
        "#!/bin/sh\n"
        + (
            'case "$*" in\n'
            "  '-S FORWARD_FIREWALL') echo '-A FORWARD_FIREWALL -j MY_PA_DATA_PLANE';;\n"
            f"  '-S MY_PA_DATA_PLANE') printf '%s\\n' {rendered_rules};;\n"
            "esac\n"
            "exit 0\n"
            if firewall_passes
            else "exit 1\n"
        ),
    )
    iptables_save = binary / "iptables-save"
    saved_filter = [
        "*filter",
        ":FORWARD ACCEPT [0:0]",
        ":FORWARD_FIREWALL - [0:0]",
        ":MY_PA_DATA_PLANE - [0:0]",
        "-A FORWARD -j FORWARD_FIREWALL",
        "-A FORWARD_FIREWALL -j MY_PA_DATA_PLANE",
        *data_plane_rules,
        "COMMIT",
    ]
    rendered_filter = " ".join(f"'{line}'" for line in saved_filter)
    _write_executable(
        iptables_save,
        f"#!/bin/sh\nprintf '%s\\n' {rendered_filter}\n",
    )
    git = binary / "git"
    _write_executable(
        git,
        "#!/bin/sh\n"
        'case "$*" in\n'
        f'  "--version") echo "{GIT_VERSION}";;\n'
        f'  *"forged-current"*"rev-parse HEAD^{{tree}}"*) echo {"6" * 40};;\n'
        f'  *"forged-current"*"rev-parse HEAD"*) echo {"5" * 40};;\n'
        f'  *"rev-parse HEAD^{{tree}}"*) echo {CURRENT_TREE};;\n'
        f'  *"rev-parse HEAD"*) echo {CURRENT_COMMIT};;\n'
        '  *"status --porcelain --untracked-files=all"*) exit 0;;\n'
        '  *"rev-parse --show-toplevel"*) printf "%s\\n" "$2";;\n'
        "esac\n",
    )
    stat = binary / "stat"
    _write_executable(
        stat,
        f"#!{sys.executable}\n"
        "import os, stat, sys\n"
        "path = sys.argv[-1]\n"
        "if path.endswith('operator-runtime.toml'):\n"
        "    print('0:400:1')\n"
        "else:\n"
        "    value = os.lstat(path)\n"
        "    owner = value.st_uid + (1 if os.environ.get('MY_TEST_DEST_OWNER_MISMATCH') else 0)\n"
        "    print(f'{owner}:{stat.S_IMODE(value.st_mode):o}')\n",
    )
    current = tmp_path / "current"
    current_ops = current / "ops/nas"
    current_ops.mkdir(parents=True)
    for name in (
        "tooling-common.sh",
        "synology-data-plane-firewall.sh",
        "preserved_backup_gate.py",
        "image_gate.py",
        "admit-operator-runtime.py",
        "archive_image.py",
        "nas_tools.py",
    ):
        source = ROOT / "ops/nas" / name
        target = current_ops / name
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        target.chmod(source.stat().st_mode)
    pre_tooling_gate = current_ops / "pre-tooling-gate.py"
    pre_tooling_gate.write_text(
        """import importlib.util
import sys
import tomllib
from pathlib import Path

(gate, current_source, current_manifest, preserved_source, preserved_manifest, compose,
 admission) = sys.argv[1:]
ops = Path(gate).parent
sys.path.insert(0, str(ops))
spec = importlib.util.spec_from_file_location("admission", ops / "admit-operator-runtime.py")
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
from image_gate import shape_errors

admitted = tomllib.loads(Path(admission).read_text())
manifest = tomllib.loads(Path(current_manifest).read_text())
errors = module.admission_shape_errors(admitted) + shape_errors(manifest)
if admitted.get("python_version") != __import__("platform").python_version():
    errors.append("python_version")
for name in ("repository_commit", "repository_tree", "docker_engine_id", "docker_engine_name"):
    if admitted.get(name) != manifest.get(name):
        errors.append(name)
raise SystemExit(bool(errors))
""",
        encoding="utf-8",
    )
    _write_executable(
        current_ops / "container-python.sh",
        "#!/bin/sh\n"
        f"printf 'container-python %s\\n' \"$*\" >> '{log}'\n"
        + ("exit 1\n" if rejected_gate == "preserved_backup_gate.py" else "")
        + f"exec '{sys.executable}' '{pre_tooling_gate}' \"$@\"\n",
    )
    for name in (
        "lifecycle_gate.py",
        "compose.example.yml",
        "compose.pilot.example.yml",
    ):
        (current_ops / name).write_text("synthetic\n", encoding="utf-8")
    preserved = tmp_path / "preserved"
    (preserved / "ops/nas").mkdir(parents=True)
    for name in (
        "compose.example.yml",
        "compose.pilot.example.yml",
        "lifecycle_gate.py",
        "runtime_identity_gate.py",
        "postgres-bootstrap-identity-gate.py",
        "postgres_gate.py",
    ):
        (preserved / "ops/nas" / name).write_text("synthetic\n", encoding="utf-8")
    admission = tmp_path / "bootstrap.toml"
    admission.write_text(f'database_operator_image_id = "sha256:{"a" * 64}"\n')
    manifest = tmp_path / "old.toml"
    current_manifest = tmp_path / "current.toml"
    operator_admission = tmp_path / "operator-runtime.toml"
    resources = tmp_path / "resources.toml"
    for path in (manifest, resources):
        path.write_text("synthetic = true\n", encoding="utf-8")
    _manifest(current_manifest, CURRENT_COMMIT, CURRENT_TREE)
    _operator_admission(operator_admission, *_operator_artifacts(tmp_path), source=current)
    env = {
        **os.environ,
        "PATH": f"{binary}:{os.environ['PATH']}",
        "MY_PA_NAS_DOCKER": str(docker),
        "MY_PA_NAS_PYTHON": str(python),
        "MY_PA_NAS_IPTABLES": str(iptables),
        "MY_PA_NAS_IPTABLES_SAVE": str(iptables_save),
        "MY_PA_NAS_IP": str(ip),
        "MY_PA_NAS_COMPOSE_FILE": str(preserved / "ops/nas/compose.example.yml"),
        "MY_PA_POSTGRES_RESOURCES": str(resources),
        "MY_PA_IMAGE_MANIFEST": str(manifest),
        "MY_PA_CURRENT_GATE_SOURCE": str(current),
        "MY_PA_CURRENT_GATE_IMAGE_MANIFEST": str(current_manifest),
        "MY_PA_NAS_OPERATOR_ADMISSION": str(operator_admission),
        "MY_PA_PRESERVED_RUNTIME_SOURCE": str(preserved),
        "MY_PA_POSTGRES_BOOTSTRAP_ADMISSION": str(admission),
        "MY_PA_DB_PASSWORD": "synthetic",
    }
    return env, log


def _backup_script(
    tmp_path: Path, env: dict[str, str], *, deterministic_partial: bool = False
) -> Path:
    source = (ROOT / "ops/nas/backup.sh").read_text(encoding="utf-8")
    binary = Path(env["MY_PA_NAS_DOCKER"]).parent
    rendered = source.replace(
        "canonical_docker=/usr/local/bin/docker", f"canonical_docker={binary / 'docker'}"
    ).replace(
        "canonical_compose=/usr/local/bin/docker-compose",
        f"canonical_compose={binary / 'docker-compose'}",
    )
    if deterministic_partial:
        rendered = rendered.replace(
            "timestamp=$(date -u +%Y%m%dT%H%M%SZ)", "timestamp=synthetic"
        ).replace('partial="$final.partial.$$"', 'partial="$final.partial.precreated"')
    script = tmp_path / "backup-under-test.sh"
    _write_executable(script, rendered)
    return script


def test_backup_uses_current_firewall_and_preserves_byte_verification(tmp_path: Path) -> None:
    env, log = _backup_environment(tmp_path, firewall_passes=True)
    backup_script = _backup_script(tmp_path, env)
    destination = tmp_path / "backups"
    destination.mkdir(mode=0o700)
    completed = subprocess.run(  # noqa: S603 - repository script under test
        [str(backup_script), str(destination)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    receipt = Path(completed.stdout.strip().splitlines()[-1])
    dump = Path(str(receipt).removesuffix(".sha256"))
    assert dump.read_bytes() == b"synthetic-dump"
    assert receipt.is_file()
    commands = log.read_text(encoding="utf-8")
    assert "exec -i pg-id pg_dump" in commands
    assert "exec -i pg-id pg_restore --list" in commands
    assert "preserved_backup_gate.py" in commands
    current_ops = Path(env["MY_PA_CURRENT_GATE_SOURCE"]) / "ops/nas"
    assert f"{current_ops}/lifecycle_gate.py" in commands
    assert "preserved/ops/nas/lifecycle_gate.py" in commands
    assert "preserved/ops/nas/runtime_identity_gate.py" in commands
    assert "preserved/ops/nas/postgres-bootstrap-identity-gate.py" in commands
    assert "preserved/ops/nas/postgres_gate.py" in commands

    current = Path(env["MY_PA_CURRENT_GATE_SOURCE"])
    preserved = Path(env["MY_PA_PRESERVED_RUNTIME_SOURCE"])
    current_child = current / "backup-target"
    preserved_child = preserved / "backup-target"
    current.chmod(0o700)
    preserved.chmod(0o700)
    current_child.mkdir(mode=0o700)
    preserved_child.mkdir(mode=0o700)
    preserved_link = tmp_path / "linked-preserved-target"
    preserved_link.symlink_to(preserved_child, target_is_directory=True)
    for refused_destination in (
        current,
        current_child,
        preserved,
        preserved_child,
        preserved_link,
    ):
        refused = subprocess.run(  # noqa: S603 - repository script under test
            [str(backup_script), str(refused_destination)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert refused.returncode != 0
        assert "backup destination must be" in refused.stderr
    commands = log.read_text(encoding="utf-8")
    assert commands.count("exec -i pg-id pg_dump") == 1
    assert list(current_child.iterdir()) == []
    assert list(preserved_child.iterdir()) == []

    unsafe_mode = tmp_path / "unsafe-mode"
    unsafe_mode.mkdir(mode=0o777)
    unsafe_mode.chmod(0o777)
    wrong_owner = tmp_path / "wrong-owner"
    wrong_owner.mkdir(mode=0o700)
    linked_destination = tmp_path / "linked-backups"
    linked_destination.symlink_to(destination, target_is_directory=True)
    for refused_destination, refusal_env in (
        (unsafe_mode, env),
        (wrong_owner, {**env, "MY_TEST_DEST_OWNER_MISMATCH": "1"}),
        (linked_destination, env),
    ):
        refused = subprocess.run(  # noqa: S603 - repository script under test
            [str(backup_script), str(refused_destination)],
            env=refusal_env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert refused.returncode != 0
        assert list(unsafe_mode.iterdir()) == []
        assert list(wrong_owner.iterdir()) == []

    for kind in ("regular", "symlink"):
        collision_root = tmp_path / f"partial-{kind}"
        collision_root.mkdir(mode=0o700)
        collision_script = _backup_script(collision_root, env, deterministic_partial=True)
        collision_destination = collision_root / "backups"
        collision_destination.mkdir(mode=0o700)
        partial = collision_destination / "my-pa-synthetic.dump.partial.precreated"
        protected = collision_root / "protected"
        protected.write_text("untouched", encoding="utf-8")
        if kind == "regular":
            partial.write_text("preexisting", encoding="utf-8")
        else:
            partial.symlink_to(protected)
        refused = subprocess.run(  # noqa: S603 - repository script under test
            [str(collision_script), str(collision_destination)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert refused.returncode != 0
        assert protected.read_text(encoding="utf-8") == "untouched"
        if kind == "regular":
            assert partial.read_text(encoding="utf-8") == "preexisting"
        else:
            assert partial.is_symlink()
        assert not list(collision_destination.glob("*.dump.sha256"))

    for case in ("truncated", "extra", "tool_mismatch"):
        case_path = tmp_path / case
        case_path.mkdir()
        case_env, case_log = _backup_environment(case_path, firewall_passes=True)
        case_script = _backup_script(case_path, case_env)
        case_destination = case_path / "backups"
        case_destination.mkdir(mode=0o700)
        admission = Path(case_env["MY_PA_NAS_OPERATOR_ADMISSION"])
        lines = admission.read_text(encoding="utf-8").splitlines()
        if case == "truncated":
            value = "\n".join(lines[:6]) + "\n"
        elif case == "extra":
            value = "\n".join(lines) + '\nunexpected = "refuse"\n'
        else:
            value = admission.read_text(encoding="utf-8").replace(
                f'python_version = "{platform.python_version()}"',
                'python_version = "3.12.0"',
            )
        admission.chmod(0o600)
        admission.write_text(value, encoding="utf-8")
        admission.chmod(0o400)
        case_env["MY_TEST_PRE_SOURCE_REFUSE"] = "1"
        refused = subprocess.run(  # noqa: S603 - repository script under test
            [str(case_script), str(case_destination)],
            env=case_env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert refused.returncode != 0
        case_commands = case_log.read_text(encoding="utf-8") if case_log.exists() else ""
        assert "network inspect" not in case_commands
        assert "exec -i pg-id pg_dump" not in case_commands
        assert list(case_destination.iterdir()) == []


def test_backup_refuses_current_firewall_failure_before_pg_dump(tmp_path: Path) -> None:
    env, log = _backup_environment(tmp_path, firewall_passes=False)
    backup_script = _backup_script(tmp_path, env)
    destination = tmp_path / "backups"
    destination.mkdir(mode=0o700)
    completed = subprocess.run(  # noqa: S603 - repository script under test
        [str(backup_script), str(destination)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    commands = log.read_text(encoding="utf-8")
    assert "exec -i pg-id pg_dump" not in commands
    assert list(destination.iterdir()) == []


@pytest.mark.parametrize(
    "rejected_gate",
    [
        "preserved_backup_gate.py",
        "runtime_identity_gate.py",
        "postgres-bootstrap-identity-gate.py",
        "postgres_gate.py",
    ],
)
def test_backup_refuses_any_source_admission_or_resource_gate_before_pg_dump(
    tmp_path: Path, rejected_gate: str
) -> None:
    env, log = _backup_environment(tmp_path, firewall_passes=True, rejected_gate=rejected_gate)
    backup_script = _backup_script(tmp_path, env)
    destination = tmp_path / "backups"
    destination.mkdir(mode=0o700)
    completed = subprocess.run(  # noqa: S603 - repository script under test
        [str(backup_script), str(destination)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "exec -i pg-id pg_dump" not in log.read_text(encoding="utf-8")
    assert list(destination.iterdir()) == []


def test_forged_shell_zero_cannot_retain_backup_database_functions(tmp_path: Path) -> None:
    env, _log = _backup_environment(tmp_path, firewall_passes=True)
    backup_script = _backup_script(tmp_path, env)
    destination = tmp_path / "backups"
    destination.mkdir(mode=0o700)
    completed = subprocess.run(  # noqa: S603 - explicit sourced-script regression
        [
            "/bin/sh",
            "-c",
            '. "$0"; '
            "if type pg_exec >/dev/null 2>&1 || "
            "type database_operator >/dev/null 2>&1; then exit 1; fi",
            str(backup_script),
            str(destination),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert len(list(destination.glob("*.dump"))) == 1
    assert len(list(destination.glob("*.dump.sha256"))) == 1


def test_backup_refuses_forged_shell_zero_and_forged_current_repo(tmp_path: Path) -> None:
    path_case = tmp_path / "path-case"
    path_case.mkdir()
    env, log = _backup_environment(path_case, firewall_passes=False)
    backup_script = _backup_script(path_case, env)
    destination = path_case / "backups"
    destination.mkdir(mode=0o700)
    forged_ops = tmp_path / "forged/ops/nas"
    forged_ops.mkdir(parents=True)
    for name in (
        "tooling-common.sh",
        "preserved_backup_gate.py",
        "lifecycle_gate.py",
        "synology-data-plane-firewall.sh",
    ):
        _write_executable(forged_ops / name, "#!/bin/sh\nexit 0\n")
    completed = subprocess.run(  # noqa: S603 - reviewer-reproduced forged $0 path
        [
            "/bin/sh",
            "-c",
            'real=$1; destination=$2; set -- "$destination"; . "$real"',
            str(forged_ops / "backup.sh"),
            str(backup_script),
            str(destination),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    commands = log.read_text(encoding="utf-8")
    current_ops = Path(env["MY_PA_CURRENT_GATE_SOURCE"]) / "ops/nas"
    assert f"{current_ops}/preserved_backup_gate.py" in commands
    assert str(forged_ops) not in commands
    assert "exec -i pg-id pg_dump" not in commands
    assert list(destination.iterdir()) == []

    repo_case = tmp_path / "repo-case"
    repo_case.mkdir()
    env, log = _backup_environment(repo_case, firewall_passes=False)
    backup_script = _backup_script(repo_case, env)
    destination = repo_case / "backups"
    destination.mkdir(mode=0o700)
    forged_current = repo_case / "forged-current"
    forged_ops = forged_current / "ops/nas"
    forged_ops.mkdir(parents=True)
    for name in (
        "tooling-common.sh",
        "preserved_backup_gate.py",
        "lifecycle_gate.py",
        "synology-data-plane-firewall.sh",
    ):
        _write_executable(forged_ops / name, "#!/bin/sh\nexit 0\n")
    forged_manifest = repo_case / "forged-current.toml"
    _manifest(forged_manifest, "5" * 40, "6" * 40)
    env["MY_PA_CURRENT_GATE_SOURCE"] = str(forged_current)
    env["MY_PA_CURRENT_GATE_IMAGE_MANIFEST"] = str(forged_manifest)
    completed = subprocess.run(  # noqa: S603 - reviewer-reproduced forged clean repository
        [str(backup_script), str(destination)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    commands = log.read_text(encoding="utf-8") if log.exists() else ""
    assert str(forged_ops) not in commands
    assert "preserved_backup_gate.py" not in commands
    assert "exec -i pg-id pg_dump" not in commands
    assert list(destination.iterdir()) == []


def test_reusable_postgres_common_has_no_preserved_runtime_mode() -> None:
    common = (ROOT / "ops/nas/postgres-common.sh").read_text(encoding="utf-8")
    assert "MY_PA_PRESERVED_RUNTIME_SOURCE" not in common
    assert "preserved_backup_gate.py" not in common
    backup = (ROOT / "ops/nas/backup.sh").read_text(encoding="utf-8")
    authenticate = backup.index("my-pa-operator-pre-source-gate.py")
    derive_tooling = backup.index('current_ops="$current_source/ops/nas"')
    source_tooling = backup.index('. "$current_ops/tooling-common.sh"')
    lifecycle = backup.index('"$NAS_PYTHON_BIN" "$current_ops/lifecycle_gate.py"')
    firewall = backup.index('"$current_ops/synology-data-plane-firewall.sh" check')
    assert authenticate < derive_tooling < source_tooling < lifecycle < firewall
    untrusted_targets = {
        "$MY_PA_NAS_OPERATOR_ADMISSION": "/run/my-pa-input/admission.toml",
        "$operator_archive": "/run/my-pa-input/operator.tar",
        "$operator_candidate": "/run/my-pa-input/operator-candidate.toml",
        "$operator_metadata": "/run/my-pa-input/operator-metadata.json",
        "$current_source": "/run/my-pa-input/current-source",
        "$MY_PA_CURRENT_GATE_IMAGE_MANIFEST": "/run/my-pa-input/current-manifest.toml",
    }
    assert len(set(untrusted_targets.values())) == len(untrusted_targets)
    for source, target in untrusted_targets.items():
        assert f'--volume "{source}:{target}:ro"' in backup
        assert target.startswith("/run/my-pa-input/")
        assert not target.startswith("/usr/local")
    assert ":/usr/local/libexec/my-pa-operator-pre-source-gate.py:ro" not in backup
