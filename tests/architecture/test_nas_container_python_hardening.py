"""Synthetic fail-closed coverage for the NAS operator Python launcher."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from tempfile import gettempdir

import pytest

ROOT = Path(__file__).resolve().parents[2]
IMAGE_ID = "sha256:" + "a" * 64
COMMIT = "b" * 40
TREE = "c" * 40
_SYNTHETIC_SOCKET_PATHS: set[Path] = set()
_SYNTHETIC_SOCKET_ROOTS: set[Path] = set()
_FUNCTION_SECTION_END = "# A relative $0 lets an attacker select the resolution base."


@pytest.fixture(autouse=True)
def _remove_synthetic_socket_paths() -> None:
    yield
    _SYNTHETIC_SOCKET_PATHS.clear()
    while _SYNTHETIC_SOCKET_ROOTS:
        shutil.rmtree(_SYNTHETIC_SOCKET_ROOTS.pop(), ignore_errors=True)


def _admission_contents(
    repository_source_path: Path,
    *,
    schema: str = "my-pa.nas-operator-runtime-admission.v1",
    status: str = "admitted",
    commit: str = COMMIT,
    tree: str = TREE,
) -> str:
    """Return the complete non-secret operator-admission contract fixture."""
    fields = (
        ("schema", schema),
        ("status", status),
        ("repository_commit", commit),
        ("repository_tree", tree),
        ("repository_source_path", str(repository_source_path)),
        ("docker_engine_id", "synthetic-engine-id"),
        ("docker_engine_name", "synthetic-engine"),
        ("operator_image_id", IMAGE_ID),
        ("operator_manifest_digest", "sha256:" + "d" * 64),
        ("operator_archive_path", "/synthetic/operator.tar"),
        ("operator_archive_sha256", "e" * 64),
        ("operator_candidate_path", "/synthetic/operator.toml"),
        ("operator_candidate_sha256", "f" * 64),
        ("operator_metadata_path", "/synthetic/operator.json"),
        ("operator_metadata_sha256", "1" * 64),
        ("python_version", "3.12.1"),
        ("git_version", "git version 2.47.0"),
        ("openssl_version", "OpenSSL 3.0.0"),
        ("compose_version", "2.20.1"),
    )
    return "".join(f'{name} = "{value}"\n' for name, value in fields)


def _write(path: Path, content: str, *, mode: int = 0o700) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)


def _rewrite_admission(admission: Path, contents: str) -> None:
    """Mutate a synthetic admission while preserving the launch precondition."""
    admission.chmod(0o600)
    admission.write_text(contents, encoding="utf-8")
    admission.chmod(0o400)
    assert admission.stat().st_mode & 0o777 == 0o400


def _socket_root(tmp_path: Path) -> Path:
    """Return a short socket root; AF_UNIX paths are length-limited."""
    socket_suffix = sha256(str(tmp_path).encode("utf-8")).hexdigest()[:12]
    return Path(gettempdir()) / f"my-pa-ds-{socket_suffix}"


def _dsm_paths(tmp_path: Path) -> dict[str, Path]:
    """Return the synthetic stand-ins for the pinned Synology alias constants."""
    dsm = tmp_path / "dsm"
    socket_root = _socket_root(tmp_path)
    docker_store_alias = dsm / "var/packages/ContainerManager/target"
    docker_store_target = dsm / "volume1/@appstore/ContainerManager"
    git_store_alias = dsm / "var/packages/Git/target"
    git_store_target = dsm / "volume1/@appstore/Git"
    return {
        "docker_store_alias": docker_store_alias,
        "docker_store_target": docker_store_target,
        "docker_alias_target": docker_store_alias / "usr/bin/docker",
        "compose_alias_target": docker_store_alias / "usr/bin/docker-compose",
        "docker_real": docker_store_target / "usr/bin/docker",
        "compose_real": docker_store_target / "usr/bin/docker-compose",
        "git_store_alias": git_store_alias,
        "git_store_target": git_store_target,
        "git_alias_target": git_store_alias / "bin/git",
        "git_real": git_store_target / "bin/git",
        "socket_root": socket_root,
        "socket_alias_dir": socket_root / "var/run",
        "socket_real": socket_root / "run/docker.sock",
    }


# The production source must keep each fixed assignment on its own line; every
# such line is redirected below and asserted verbatim by the source-pin test.
_PINNED_ALIAS_LINES = {
    "docker_alias_target": "/var/packages/ContainerManager/target/usr/bin/docker",
    "compose_alias_target": "/var/packages/ContainerManager/target/usr/bin/docker-compose",
    "docker_store_alias": "/var/packages/ContainerManager/target",
    "docker_store_target": "/volume1/@appstore/ContainerManager",
    "docker_real_path": "/volume1/@appstore/ContainerManager/usr/bin/docker",
    "compose_real_path": "/volume1/@appstore/ContainerManager/usr/bin/docker-compose",
    "git_alias_target": "/var/packages/Git/target/bin/git",
    "git_store_alias": "/var/packages/Git/target",
    "git_store_target": "/volume1/@appstore/Git",
    "git_real_path": "/volume1/@appstore/Git/bin/git",
    "docker_socket_alias_dir": "/var/run",
    "docker_socket_alias_dir_target": "../run",
    "docker_socket_real_path": "/run/docker.sock",
}

_STAT_STUB = r"""#!/bin/sh
format=$2
path=$4
emit() { printf '%s\n' "$1"; exit 0; }
# early-nonroot: the matched alias is faulty only until the guarded real path
# is first inspected, so only a check that runs before that real-path access
# can refuse it.
if [ "${SYNTH_ALIAS_CASE:-}" = early-nonroot ] && [ "$path" = "${SYNTH_ALIAS_RELEASE:-}" ]; then
  : > "@COUNTER@.released"
fi
case "$format" in
  '%u:%a:%F')
    case "${SYNTH_TOOL_CASE:-}:$path" in
      writable-store:*/@appstore/ContainerManager) emit '0:775:directory' ;;
      writable-alias-parent:*/var/packages/Git) emit '0:777:directory' ;;
    esac
    case "${SYNTH_POSTGRES_DATA_CASE:-}:$path" in
      postgres-owned:*/nas/postgres/data) emit '999:700:directory' ;;
      writable-ancestor:*/nas/postgres) emit '0:777:directory' ;;
      unsafe-leaf:*/nas/postgres/data) emit '999:770:directory' ;;
    esac
    case "${SYNTH_DOCKER_SOCKET_CASE:-}:$path" in
      docker-nonroot-ancestor:*/my-pa-ds-*) emit '1000:700:directory' ;;
      docker-writable-ancestor:*/my-pa-ds-*) emit '0:777:directory' ;;
    esac
    case "${SYNTH_GIT_CASE:-}:$path" in
      open-source-root:*/trusted-source) emit '0:755:directory' ;;
      nonroot-ancestor:*/trusted-source) emit '1000:700:directory' ;;
      writable-ancestor:*/trusted-source) emit '0:777:directory' ;;
      nonroot-objects:*/.git/objects) emit '1000:700:directory' ;;
      writable-objects:*/.git/objects) emit '0:777:directory' ;;
      nonroot-refs:*/.git/refs) emit '1000:700:directory' ;;
      writable-refs:*/.git/refs) emit '0:777:directory' ;;
      *:*/.git/*) emit '0:700:directory' ;;
    esac
    case "${SYNTH_SOCKET_CASE:-}:$path" in
      writable-ancestor:*/socket-parent) emit '0:777:directory' ;;
    esac
    case "${SYNTH_EVIDENCE_CASE:-}:$path" in
      not-private:*/evidence) emit '0:755:directory' ;;
    esac
    case ${SYNTH_STAT_CASE:-ok} in
      bad-ancestor-mode) emit '0:777:directory' ;;
      bad-ancestor-owner) emit '1000:700:directory' ;;
    esac
    emit '0:700:directory' ;;
  '%u:%a:%h:%F')
    case "$path" in
      *operator-runtime.toml) emit "${SYNTH_ADMISSION_METADATA:-0:400:1:regular file}" ;;
    esac
    case "${SYNTH_GIT_CASE:-}:$path" in
      nonroot-config:*/.git/config|nonroot-head:*/.git/HEAD|nonroot-index:*/.git/index)
        emit '1000:400:1:regular file' ;;
      writable-config:*/.git/config|writable-head:*/.git/HEAD|writable-index:*/.git/index)
        emit '0:620:1:regular file' ;;
      malformed-metadata:*/.git/config) emit 'malformed metadata' ;;
      *:*/.git/*) emit '0:400:1:regular file' ;;
    esac
    case "${SYNTH_TOOL_CASE:-}:$path" in
      docker-real-nlink:*/@appstore/ContainerManager/usr/bin/docker)
        emit '0:755:2:regular file' ;;
      compose-real-nlink:*/@appstore/ContainerManager/usr/bin/docker-compose)
        emit '0:755:2:regular file' ;;
      git-mode-750:*/@appstore/Git/bin/git) emit '0:750:142:regular file' ;;
      git-mode-775:*/@appstore/Git/bin/git) emit '0:775:142:regular file' ;;
      git-nonroot:*/@appstore/Git/bin/git) emit '1000:755:142:regular file' ;;
      git-zero-links:*/@appstore/Git/bin/git) emit '0:755:0:regular file' ;;
      *:*/@appstore/Git/bin/git) emit '0:755:142:regular file' ;;
      *:*/@appstore/*) emit '0:755:1:regular file' ;;
    esac
    case ${SYNTH_STAT_CASE:-ok} in
      bad-file-mode) emit '0:620:1:regular file' ;;
      bad-file-owner) emit '1000:400:1:regular file' ;;
      bad-nlink) emit '0:400:2:regular file' ;;
    esac
    emit '0:400:1:regular file' ;;
  '%u:%g:%a:%h:%F')
    case "${SYNTH_DOCKER_SOCKET_CASE:-}:$path" in
      docker-nonroot:*/my-pa-ds-*/docker.sock) emit '1000:0:600:1:socket' ;;
      docker-writable-socket:*/my-pa-ds-*/docker.sock) emit '0:0:620:1:socket' ;;
      docker-bad-link:*/my-pa-ds-*/docker.sock) emit '0:0:600:2:socket' ;;
      docker-unsupported-metadata:*/my-pa-ds-*/docker.sock) emit 'unsupported metadata' ;;
      docker-0660:*/my-pa-ds-*/docker.sock) emit '0:0:660:1:socket' ;;
      docker-0660-nonroot-group:*/my-pa-ds-*/docker.sock) emit '0:1000:660:1:socket' ;;
      docker-0666:*/my-pa-ds-*/docker.sock) emit '0:0:666:1:socket' ;;
      docker-0670:*/my-pa-ds-*/docker.sock) emit '0:0:670:1:socket' ;;
      docker-0662:*/my-pa-ds-*/docker.sock) emit '0:0:662:1:socket' ;;
      *:*/my-pa-ds-*/docker.sock) emit '0:0:600:1:socket' ;;
    esac
    case "${SYNTH_SOCKET_CASE:-}:$path" in
      nonroot:*/socket-parent/tailscale.sock) emit '1000:0:600:1:socket' ;;
      unsupported-metadata:*/socket-parent/tailscale.sock) emit '0:0:600:1:unknown' ;;
      tailscale-0660:*/socket-parent/tailscale.sock) emit '0:0:660:1:socket' ;;
      *:*/socket-parent/tailscale.sock) emit '0:0:600:1:socket' ;;
    esac
    exit 97 ;;
  '%u:%h:%F:%d:%i:%Y:%Z')
    # Owner and link count are synthetic (tmp files are not root-owned); the
    # type and identity are the real lstat values of the synthetic link.
    real=$(/usr/bin/stat -c '%F:%d:%i:%Y:%Z' -- "$path") || exit 1
    owner=0
    links=1
    if [ -n "${SYNTH_ALIAS_MATCH:-}" ]; then
      case "$path" in
        *"$SYNTH_ALIAS_MATCH")
          case "${SYNTH_ALIAS_CASE:-}" in
            nonroot) owner=1000 ;;
            links) links=2 ;;
            kind-directory) real="directory:${real#*:}" ;;
            kind-link) real="symbolic link:${real#*:}" ;;
            early-nonroot) [ -e "@COUNTER@.released" ] || owner=1000 ;;
            drift|late-nonroot)
              count=$(/bin/cat "@COUNTER@" 2>/dev/null || printf 0)
              count=$((count + 1))
              printf '%s\n' "$count" > "@COUNTER@"
              if [ "$SYNTH_ALIAS_CASE" = drift ]; then
                real="$real$count"
              elif [ "$count" -gt 2 ]; then
                owner=1000
              fi
              ;;
          esac
          ;;
      esac
    fi
    emit "$owner:$links:$real" ;;
  '%d:%i')
    case "${SYNTH_STAT_CASE:-ok}:$path" in
      fd-mismatch:/proc/*|fd-mismatch:/dev/fd/*) emit '11:23' ;;
    esac
    emit '11:22' ;;
  *) exit 97 ;;
esac
"""


def _bind_socket(path: Path) -> None:
    socket_handle = socket.socket(socket.AF_UNIX)
    socket_handle.bind(str(path))
    socket_handle.close()


def _synthetic_wrapper(
    tmp_path: Path, *, dsm_layout: bool = False
) -> tuple[Path, Path, Path, Path, Path, Path, Path]:
    """Copy the checked-in launcher with only its fixed host paths redirected.

    The production source is separately asserted to contain the canonical paths.
    This fixture never resolves a real Docker client, admission, or NAS path.
    With ``dsm_layout`` the tool and socket-directory paths become the exact
    two-level Synology alias chains (real symbolic links with literal targets)
    rooted in ``tmp_path`` and the short socket root.
    """
    if sys.platform != "linux":
        pytest.skip("requires Linux filesystem sockets and /proc descriptor behavior")
    tools = tmp_path / "trusted-tools"
    repo = tmp_path / "trusted-source"
    launcher = repo / "ops/nas/container-python.sh"
    dsm = _dsm_paths(tmp_path)
    socket_root = dsm["socket_root"]
    if dsm_layout:
        docker_socket_alias_dir = dsm["socket_alias_dir"]
        docker_socket_real = dsm["socket_real"]
        docker_socket = docker_socket_alias_dir / "docker.sock"
    else:
        docker_socket_alias_dir = socket_root
        docker_socket_real = dsm["socket_real"]
        docker_socket = socket_root / "docker.sock"
    admission = tmp_path / "operator-runtime.toml"
    git_state = tmp_path / "git-state"
    calls = tmp_path / "docker-calls"
    run_argv = tmp_path / "docker-run-argv"
    environment = tmp_path / "docker-environment"
    engine_projection = tools / "engine-projection"
    git_calls = tmp_path / "git-calls"
    git_environment = tmp_path / "git-environment"
    git_endpoint = tmp_path / "git-endpoint"
    nas_root = tmp_path / "nas"
    for relative in ("deployment", "backups", "postgres/data", "secrets"):
        (nas_root / relative).mkdir(parents=True)
    _write(nas_root / "secrets/nas.env", "SYNTHETIC_ONLY=1\n", mode=0o400)
    _write(nas_root / "secrets/web.env", "SYNTHETIC_ONLY=1\n", mode=0o400)
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    etc_root = tmp_path / "admissions"
    etc_root.mkdir()
    tools.mkdir()
    _write(engine_projection, "synthetic-engine-id|synthetic-engine\n", mode=0o600)
    launcher.parent.mkdir(parents=True)
    socket_root.mkdir()
    _SYNTHETIC_SOCKET_ROOTS.add(socket_root)
    if dsm_layout:
        docker_socket_real.parent.mkdir()
        _bind_socket(docker_socket_real)
        _SYNTHETIC_SOCKET_PATHS.add(docker_socket_real)
        docker_socket_alias_dir.parent.mkdir()
        docker_socket_alias_dir.symlink_to("../run", target_is_directory=True)
    else:
        _bind_socket(docker_socket)
        _SYNTHETIC_SOCKET_PATHS.add(docker_socket)
    git_dir = repo / ".git"
    (git_dir / "objects/info").mkdir(parents=True)
    (git_dir / "refs").mkdir()
    for name in ("config", "HEAD", "index"):
        _write(git_dir / name, "synthetic\n", mode=0o600)
    admission.write_text(_admission_contents(repo), encoding="utf-8")
    admission.chmod(0o400)
    git_state.write_text(f"{COMMIT}\n{TREE}\n\n{repo}\n", encoding="utf-8")

    stat = tools / "stat"
    _write(stat, _STAT_STUB.replace("@COUNTER@", str(tmp_path / "alias-stat-count")))
    docker = tools / "docker"
    compose = tools / "docker-compose"
    git = tools / "git"
    if dsm_layout:
        docker_body, compose_body, git_body = (
            dsm["docker_real"],
            dsm["compose_real"],
            dsm["git_real"],
        )
        for directory in (docker_body.parent, git_body.parent):
            directory.mkdir(parents=True)
        for alias in ("docker_store_alias", "git_store_alias"):
            dsm[alias].parent.mkdir(parents=True)
        dsm["docker_store_alias"].symlink_to(
            str(dsm["docker_store_target"]), target_is_directory=True
        )
        dsm["git_store_alias"].symlink_to(str(dsm["git_store_target"]), target_is_directory=True)
        docker.symlink_to(str(dsm["docker_alias_target"]))
        compose.symlink_to(str(dsm["compose_alias_target"]))
        git.symlink_to(str(dsm["git_alias_target"]))
    else:
        docker_body, compose_body, git_body = docker, compose, git
    _write(
        docker_body,
        "#!/bin/sh\n"
        f'calls="{calls}"\n'
        f'run_argv="{run_argv}"\n'
        f'environment="{environment}"\n'
        f'engine_projection="{engine_projection}"\n'
        'printf \'%s\\n\' "$*" >> "$calls"\n'
        'if [ "$1" = run ]; then printf \'%s\\0\' "$@" > "$run_argv"; fi\n'
        'if [ "$1 $2" = "info --format" ]; then\n'
        '  [ "$3" = "{{.ID}}|{{.Name}}" ] || exit 98\n'
        '  /bin/cat "$engine_projection"\n'
        "  exit 0\n"
        "fi\n"
        'if [ "$1 $2" = "image inspect" ]; then\n'
        f'  printf "{IMAGE_ID}|linux|amd64\\n"\n'
        "  exit 0\n"
        "fi\n"
        'env | LC_ALL=C sort > "$environment"\n',
    )
    _write(compose_body, "#!/bin/sh\nexit 0\n")
    _write(
        git_body,
        "#!/bin/sh\n"
        f'git_state="{git_state}"\n'
        f'printf "%s\\n" "$*" >> "{git_calls}"\n'
        f'printf "%s\\n" "$0" >> "{git_endpoint}"\n'
        f'env | LC_ALL=C sort > "{git_environment}"\n'
        'case "$*" in\n'
        '  *"rev-parse --show-toplevel") /usr/bin/sed -n "4p" "$git_state" ;;\n'
        '  *"rev-parse HEAD^{tree}") /usr/bin/sed -n "2p" "$git_state" ;;\n'
        '  *"rev-parse HEAD") /usr/bin/sed -n "1p" "$git_state" ;;\n'
        '  *"status --porcelain --untracked-files=all") /usr/bin/sed -n "3p" "$git_state" ;;\n'
        "  *) exit 98 ;;\n"
        "esac\n",
    )

    source = (ROOT / "ops/nas/container-python.sh").read_text(encoding="utf-8")
    replacements = {
        "stat_bin=/usr/bin/stat": f"stat_bin={stat}",
        "docker_path=/usr/local/bin/docker": f"docker_path={docker}",
        "compose_path=/usr/local/bin/docker-compose": f"compose_path={compose}",
        "git_path=/usr/bin/git": f"git_path={git}",
        "docker_socket_path=/var/run/docker.sock": f"docker_socket_path={docker_socket}",
        "admission_path=/etc/my-pa/operator-runtime.toml": f"admission_path={admission}",
        "compose_plugin_dir=/usr/local/lib/docker/cli-plugins": (
            f"compose_plugin_dir={tools}/plugins"
        ),
    }
    for before, after in replacements.items():
        assert before in source
        source = source.replace(before, after)
    # Redirect every pinned alias constant by its whole line. The literal
    # socket-directory target `../run` stays exact: the synthetic layout uses
    # the same relative link shape.
    alias_values = {
        "docker_alias_target": dsm["docker_alias_target"],
        "compose_alias_target": dsm["compose_alias_target"],
        "docker_store_alias": dsm["docker_store_alias"],
        "docker_store_target": dsm["docker_store_target"],
        "docker_real_path": dsm["docker_real"],
        "compose_real_path": dsm["compose_real"],
        "git_alias_target": dsm["git_alias_target"],
        "git_store_alias": dsm["git_store_alias"],
        "git_store_target": dsm["git_store_target"],
        "git_real_path": dsm["git_real"],
        "docker_socket_alias_dir": docker_socket_alias_dir,
        "docker_socket_alias_dir_target": "../run",
        "docker_socket_real_path": docker_socket_real,
    }
    for name, production in _PINNED_ALIAS_LINES.items():
        before = f"\n{name}={production}\n"
        assert source.count(before) == 1, name
        source = source.replace(before, f"\n{name}={alias_values[name]}\n")
    # The literal readlink stays the real host program so literal-target
    # comparisons exercise real symbolic links.
    assert "\nreadlink_bin=/usr/bin/readlink\n" in source
    source = source.replace("/volume1/my-pa", str(nas_root))
    source = source.replace("/var/lib/my-pa/postgres-backup-attestations", str(evidence_root))
    source = source.replace("/etc/my-pa", str(etc_root))
    # The production descriptor paths are Linux-specific and intentionally
    # remain unchanged in the copied source. Linux executes them; macOS has no
    # procfs and therefore skips only the success-path execution test below.
    assert "verify_fd_path=/proc/$$/fd/3" in source
    assert "execution_fd_path=/proc/self/fd/3" in source
    _write(launcher, source)
    return launcher, calls, environment, git_calls, tools, admission, git_state


def _run(
    launcher: Path,
    tools: Path,
    *,
    extra_environment: dict[str, str] | None = None,
    python_argv: tuple[str, ...] = ("-c", "pass"),
    disable_globbing: bool = False,
) -> subprocess.CompletedProcess[str]:
    shadow = tools.parent / "path-shadow"
    shadow.mkdir(exist_ok=True)
    _write(shadow / "docker", "#!/bin/sh\nexit 99\n")
    _write(shadow / "git", "#!/bin/sh\nexit 99\n")
    _write(shadow / "stat", "#!/bin/sh\nexit 99\n")
    command = [str(launcher), *python_argv]
    if disable_globbing:
        # Invoke the copied launcher through a shell that retains `-f`; this
        # exercises the wrapper's branch for a caller that already disabled
        # pathname expansion without changing the production launcher path.
        command = ["/bin/sh", "-f", *command]
    return subprocess.run(  # noqa: S603 - checked-in launcher with synthetic host tools
        command,
        cwd=launcher.parent,
        env={
            **os.environ,
            "PATH": str(shadow),
            "MY_PA_NAS_DOCKER": "/attacker/docker",
            "MY_PA_NAS_COMPOSE_PLUGIN": "/attacker/docker-compose",
            "MY_PA_NAS_OPERATOR_ADMISSION": "/attacker/admission.toml",
            **(extra_environment or {}),
        },
        check=False,
        capture_output=True,
        text=True,
    )


def test_container_python_uses_fixed_host_authorities_and_clears_overrides() -> None:
    source = (ROOT / "ops/nas/container-python.sh").read_text(encoding="utf-8")
    assert "PATH=/usr/bin:/bin" in source
    assert "unset MY_PA_NAS_DOCKER MY_PA_NAS_COMPOSE_PLUGIN MY_PA_NAS_OPERATOR_ADMISSION" in source
    assert "docker_path=/usr/local/bin/docker" in source
    assert "docker_socket_path=/var/run/docker.sock" in source
    assert "compose_path=/usr/local/bin/docker-compose" in source
    assert "git_path=/usr/bin/git" in source
    assert "admission_path=/etc/my-pa/operator-runtime.toml" in source
    assert "operator admission must be root-owned mode 0400 with one link" in source
    assert "repository source root must be root-owned mode 0700" in source
    assert '"$docker_fd" image inspect' in source
    assert '"$docker_fd" run' in source
    assert "\"$docker_fd\" info --format '{{.ID}}|{{.Name}}'" in source
    assert "trusted_git()" in source
    assert '"$git_fd" --no-pager --no-replace-objects' in source
    assert "verify_fd_path=/proc/$$/fd/3" in source
    assert "execution_fd_path=/proc/self/fd/3" in source
    assert source.count('open_verified_file_descriptor "$compose_path"') == 1
    # The non-DSM canonical socket keeps the base private policy verbatim; only
    # the pinned DSM real socket may pass the root-group policy.
    assert "\n  verify_root_owned_socket \"$docker_socket_path\" 'Docker socket'\n" in source
    assert "\"$docker_socket_path\" 'Docker socket' docker-root-group" not in source
    assert (
        "verify_root_owned_socket \"$docker_socket_host_path\" 'Docker socket' docker-root-group"
        in source
    )
    # Exact Synology aliases are fixed assignments, never environment input.
    assert "\nreadlink_bin=/usr/bin/readlink\n" in source
    for name, value in _PINNED_ALIAS_LINES.items():
        assert source.count(f"\n{name}={value}\n") == 1, name
        assert f"${{{name}:" not in source and f"${{{name}-" not in source
        assert f"${{{name}=" not in source and f"${{{name}+" not in source
    assert "docker_host_path=$docker_real_path" in source
    assert "compose_host_path=$compose_real_path" in source
    assert "docker_socket_host_path=$docker_socket_real_path" in source
    assert '--volume "$docker_socket_host_path:/var/run/docker.sock"' in source
    assert '--volume "$docker_host_path:/usr/local/bin/docker:ro"' in source
    assert '--volume "$compose_host_path:$compose_plugin_dir/docker-compose:ro"' in source
    assert '--volume "$docker_socket_path:' not in source
    assert '"$git_store_target" "$git_real_path" Git 5 pinned-git-shared-link' in source
    assert source.count("pinned-git-shared-link") == 3
    assert '"$readlink_bin" -- "$alias_link" && printf x' in source
    assert "readlink -f" not in source and '"$readlink_bin" -f' not in source


def test_synthetic_admission_fixture_has_the_exact_nineteen_key_contract() -> None:
    fields = tuple(
        line.partition(" = ")[0]
        for line in _admission_contents(Path("/synthetic/source")).splitlines()
    )
    assert fields == (
        "schema",
        "status",
        "repository_commit",
        "repository_tree",
        "repository_source_path",
        "docker_engine_id",
        "docker_engine_name",
        "operator_image_id",
        "operator_manifest_digest",
        "operator_archive_path",
        "operator_archive_sha256",
        "operator_candidate_path",
        "operator_candidate_sha256",
        "operator_metadata_path",
        "operator_metadata_sha256",
        "python_version",
        "git_version",
        "openssl_version",
        "compose_version",
    )
    source = (ROOT / "ops/nas/container-python.sh").read_text(encoding="utf-8")
    assert '[ "$admission_field_count" -eq 19 ]' in source


def test_container_python_keeps_tailscale_authority_opt_in_and_prevalidated() -> None:
    source = (ROOT / "ops/nas/container-python.sh").read_text(encoding="utf-8")
    assert 'if [ "${MY_PA_NAS_TAILSCALE+x}" = x ] ||' in source
    assert (
        "verify_root_owned_regular_file \"$tailscale_host_binary\" 'Tailscale executable'" in source
    )
    assert "verify_root_owned_socket \"$tailscale_socket_path\" 'Tailscale socket'" in source
    assert "${tailscale_host_binary}:/usr/local/bin/tailscale:ro" in source
    assert "${tailscale_socket_path}:/var/run/tailscale/tailscaled.sock:ro" in source


def test_attestation_mode_has_fixed_program_and_narrow_mounts() -> None:
    source = (ROOT / "ops/nas/container-python.sh").read_text(encoding="utf-8")
    assert 'if [ "${1-}" = --postgres-backup-attestation ]; then' in source
    assert (
        'set -- "$image_id" "$repo_root/ops/nas/write-postgres-backup-runtime-attestation.py"'
        in source
    )
    assert (
        'set -- "$image_id" '
        '"$repo_root/ops/nas/write-postgres-backup-runtime-attestation.py" --verify' in source
    )
    assert "unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT" in source
    assert "Tailscale authority is unavailable in attestation mode" in source
    assert (
        "verify_root_owned_private_directory /var/lib/my-pa/postgres-backup-attestations" in source
    )
    assert "--volume /volume1/my-pa/deployment:/volume1/my-pa/deployment:ro" in source
    assert "--volume /volume1/my-pa/backups:/volume1/my-pa/backups:ro" in source
    assert "--volume /volume1/my-pa/postgres/data:/volume1/my-pa/postgres/data:ro" in source
    assert "--volume /volume1/my-pa/secrets:/volume1/my-pa/secrets:ro" in source
    assert "verify_root_owned_regular_file /volume1/my-pa/secrets/nas.env" in source
    assert "verify_root_owned_regular_file /volume1/my-pa/secrets/web.env" in source
    assert "--volume /etc/my-pa:/etc/my-pa:ro" in source
    assert (
        "--volume /var/lib/my-pa/postgres-backup-attestations:"
        "/var/lib/my-pa/postgres-backup-attestations:ro" in source
    )
    assert (
        "--volume /var/lib/my-pa/postgres-backup-attestations:"
        "/var/lib/my-pa/postgres-backup-attestations \\" in source
    )


@pytest.mark.parametrize(
    "argv",
    (
        ("--postgres-backup-attestation", "--bad"),
        ("--postgres-backup-attestation", "--verify", "extra"),
    ),
)
def test_attestation_mode_refuses_extra_argv_before_host_access(argv: tuple[str, ...]) -> None:
    launcher = ROOT / "ops/nas/container-python.sh"
    result = subprocess.run(  # noqa: S603 - exits before host access by contract
        [str(launcher), *argv],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 64
    assert result.stderr == "invalid attestation arguments\n"


def test_attestation_mode_refuses_authority_and_path_overrides_before_host_access() -> None:
    launcher = ROOT / "ops/nas/container-python.sh"
    cases = (
        ("MY_PA_NAS_TAILSCALE", "Tailscale authority is unavailable in attestation mode"),
        ("MY_PA_NAS_ROOT", "attestation NAS root must be canonical"),
        ("MY_PA_NAS_ENV_FILE", "attestation NAS environment path must be canonical"),
        ("MY_PA_WEB_ENV_FILE", "attestation web environment path must be canonical"),
    )
    for name, expected in cases:
        result = subprocess.run(  # noqa: S603 - exits before host access by contract
            [str(launcher), "--postgres-backup-attestation"],
            env={name: "/synthetic/forbidden"},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 64
        assert result.stderr == expected + "\n"


@pytest.mark.skipif(sys.platform != "linux", reason="requires Linux /proc descriptor execution")
@pytest.mark.parametrize("verify", (False, True), ids=("publish", "verify"))
def test_attestation_mode_uses_fixed_script_and_mount_permissions(
    tmp_path: Path, verify: bool
) -> None:
    launcher, calls, environment, _git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path
    )
    argv = (
        ("--postgres-backup-attestation", "--verify")
        if verify
        else ("--postgres-backup-attestation",)
    )
    result = _run(
        launcher,
        tools,
        python_argv=argv,
        extra_environment={
            "MY_PA_NAS_ROOT": str(tmp_path / "nas"),
            "SYNTH_POSTGRES_DATA_CASE": "postgres-owned",
            "PYTHONPATH": "/synthetic/forbidden-import-hook",
            "SENSITIVE_PARENT_SENTINEL": "synthetic-secret-marker",
        },
    )
    assert result.returncode == 0, result.stderr
    arguments = [
        part.decode() for part in calls.with_name("docker-run-argv").read_bytes().split(b"\0")[:-1]
    ]
    image_index = arguments.index(IMAGE_ID)
    expected_script = str(
        launcher.parents[2] / "ops/nas/write-postgres-backup-runtime-attestation.py"
    )
    assert arguments[image_index + 1 :] == (
        [expected_script, "--verify"] if verify else [expected_script]
    )
    mounts = [
        arguments[index + 1] for index, value in enumerate(arguments[:-1]) if value == "--volume"
    ]
    nas_root = tmp_path / "nas"
    assert f"{nas_root}/deployment:{nas_root}/deployment:ro" in mounts
    assert f"{nas_root}/backups:{nas_root}/backups:ro" in mounts
    assert f"{nas_root}/postgres/data:{nas_root}/postgres/data:ro" in mounts
    assert f"{nas_root}/secrets:{nas_root}/secrets:ro" in mounts
    evidence_root = tmp_path / "evidence"
    evidence_mount = f"{evidence_root}:{evidence_root}" + (":ro" if verify else "")
    assert evidence_mount in mounts
    assert f"{nas_root}:{nas_root}" not in mounts
    assert not any("tailscale" in mount for mount in mounts)
    assert "synthetic-secret-marker" not in result.stdout + result.stderr
    observed_environment = environment.read_text(encoding="utf-8")
    assert f"MY_PA_NAS_ENV_FILE={nas_root}/secrets/nas.env" in observed_environment
    assert f"MY_PA_WEB_ENV_FILE={nas_root}/secrets/web.env" in observed_environment
    assert "PYTHONPATH=" not in observed_environment
    assert "SENSITIVE_PARENT_SENTINEL=" not in observed_environment


@pytest.mark.skipif(sys.platform != "linux", reason="requires Linux /proc descriptor execution")
@pytest.mark.parametrize("mutation", ("symlink", "not-private"))
def test_attestation_mode_refuses_untrusted_host_evidence_before_git_or_docker(
    tmp_path: Path, mutation: str
) -> None:
    launcher, calls, _environment, git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path
    )
    evidence = tmp_path / "evidence"
    extra_environment = {"MY_PA_NAS_ROOT": str(tmp_path / "nas")}
    if mutation == "symlink":
        evidence.rename(tmp_path / "evidence-real")
        evidence.symlink_to(tmp_path / "evidence-real", target_is_directory=True)
    else:
        extra_environment["SYNTH_EVIDENCE_CASE"] = "not-private"
    result = _run(
        launcher,
        tools,
        python_argv=("--postgres-backup-attestation",),
        extra_environment=extra_environment,
    )
    assert result.returncode != 0
    if mutation == "not-private":
        assert "attestation evidence directory must be root-owned mode 0700" in result.stderr
    assert not calls.exists()
    assert not git_calls.exists()


@pytest.mark.skipif(sys.platform != "linux", reason="requires Linux /proc descriptor execution")
@pytest.mark.parametrize("mutation", ("symlink", "writable-ancestor", "unsafe-leaf"))
def test_attestation_mode_refuses_untrusted_postgres_data_path_before_git_or_docker(
    tmp_path: Path, mutation: str
) -> None:
    launcher, calls, _environment, git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path
    )
    data_path = tmp_path / "nas/postgres/data"
    extra_environment = {"MY_PA_NAS_ROOT": str(tmp_path / "nas")}
    if mutation == "symlink":
        data_path.rename(tmp_path / "nas/postgres/data-real")
        data_path.symlink_to(tmp_path / "nas/postgres/data-real", target_is_directory=True)
    else:
        extra_environment["SYNTH_POSTGRES_DATA_CASE"] = mutation
    result = _run(
        launcher,
        tools,
        python_argv=("--postgres-backup-attestation",),
        extra_environment=extra_environment,
    )
    assert result.returncode != 0
    if mutation == "symlink":
        assert "PostgreSQL data directory is unavailable" in result.stderr
    elif mutation == "writable-ancestor":
        assert "trusted path ancestors must not be group- or world-writable" in result.stderr
    else:
        assert "PostgreSQL data directory must be mode 0700" in result.stderr
    assert not calls.exists()
    assert not git_calls.exists()


@pytest.mark.parametrize(
    "metadata",
    (
        "0:600:1:regular file",
        "1000:400:1:regular file",
        "0:400:2:regular file",
    ),
)
def test_container_python_refuses_noncanonical_operator_admission_before_docker_or_git(
    tmp_path: Path, metadata: str
) -> None:
    launcher, calls, _environment, git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path
    )
    result = _run(launcher, tools, extra_environment={"SYNTH_ADMISSION_METADATA": metadata})
    assert result.returncode != 0
    assert "operator admission must be root-owned mode 0400 with one link" in result.stderr
    assert not calls.exists()
    assert not git_calls.exists()


@pytest.mark.skipif(
    sys.platform != "linux", reason="requires Linux /proc/self descriptor execution"
)
@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    (
        ("missing", "operator admission shape is invalid"),
        ("extra", "operator admission shape is invalid"),
        ("duplicate", "operator admission contains duplicate fields"),
        ("invalid-status", "operator admission shape is invalid"),
        ("invalid-schema", "operator admission shape is invalid"),
        ("unterminated-extra", "operator admission shape is invalid"),
    ),
)
def test_container_python_refuses_malformed_full_admission_before_docker(
    tmp_path: Path, mutation: str, expected_error: str
) -> None:
    launcher, calls, _environment, _git_calls, tools, admission, _git_state = _synthetic_wrapper(
        tmp_path
    )
    contents = _admission_contents(
        launcher.parents[2],
        schema=(
            "wrong.schema"
            if mutation == "invalid-schema"
            else "my-pa.nas-operator-runtime-admission.v1"
        ),
        status=("candidate" if mutation == "invalid-status" else "admitted"),
    )
    if mutation == "missing":
        contents = contents.replace('compose_version = "2.20.1"\n', "")
    elif mutation == "extra":
        contents += 'unexpected = "synthetic"\n'
    elif mutation == "duplicate":
        contents += 'status = "admitted"\n'
    elif mutation == "unterminated-extra":
        contents += 'unexpected = "synthetic"'
    _rewrite_admission(admission, contents)

    result = _run(launcher, tools)

    assert result.returncode != 0
    assert expected_error in result.stderr
    assert not calls.exists()


@pytest.mark.skipif(
    sys.platform != "linux", reason="requires Linux /proc/self descriptor execution"
)
@pytest.mark.parametrize(
    ("identity_case", "expected_error"),
    (
        ("source-path", "operator admission source path does not match resolved repository"),
        ("git-root", "repository source root is unavailable"),
        ("dirty", "operator admission source identity does not match resolved repository"),
        ("commit", "operator admission source identity does not match resolved repository"),
        ("tree", "operator admission source identity does not match resolved repository"),
    ),
)
def test_container_python_refuses_admission_source_identity_mismatch_before_docker(
    tmp_path: Path, identity_case: str, expected_error: str
) -> None:
    launcher, calls, _environment, _git_calls, tools, admission, git_state = _synthetic_wrapper(
        tmp_path
    )
    repository_path = launcher.parents[2]
    if identity_case == "source-path":
        _rewrite_admission(admission, _admission_contents(Path("/synthetic/wrong-source")))
    elif identity_case == "commit":
        git_state.write_text(f"{'2' * 40}\n{TREE}\n\n{repository_path}\n", encoding="utf-8")
    elif identity_case == "tree":
        git_state.write_text(f"{COMMIT}\n{'3' * 40}\n\n{repository_path}\n", encoding="utf-8")
    elif identity_case == "dirty":
        git_state.write_text(
            f"{COMMIT}\n{TREE}\n M synthetic-dirty\n{repository_path}\n", encoding="utf-8"
        )
    else:
        git_state.write_text(f"{COMMIT}\n{TREE}\n\n/synthetic/wrong-root\n", encoding="utf-8")

    result = _run(launcher, tools)

    assert result.returncode != 0
    assert expected_error in result.stderr
    assert not calls.exists()


@pytest.mark.skipif(
    sys.platform != "linux", reason="requires Linux /proc/self descriptor execution"
)
def test_container_python_admitted_matching_source_proceeds_with_closed_environment(
    tmp_path: Path,
) -> None:
    launcher, calls, environment, git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path
    )
    result = _run(
        launcher,
        tools,
        extra_environment={
            "MY_PA_DB_PASSWORD": "synthetic-password",
            "UNAPPROVED_OPERATOR_VALUE": "must-not-pass",
            "SENSITIVE_PARENT_SENTINEL": "must-not-inherit",
            "GIT_DIR": "/attacker/git-dir",
            "GIT_CONFIG_GLOBAL": "/attacker/gitconfig",
            "GIT_ASKPASS": "/attacker/askpass",
        },
    )
    assert result.returncode == 0, result.stderr
    observed_calls = calls.read_text(encoding="utf-8")
    assert "image inspect" in observed_calls
    assert "--env MY_PA_DB_PASSWORD" in observed_calls
    assert "--env UNAPPROVED_OPERATOR_VALUE" not in observed_calls
    observed_git_calls = git_calls.read_text(encoding="utf-8")
    assert "--git-dir=" + str(launcher.parents[2] / ".git") in observed_git_calls
    assert "--work-tree=" + str(launcher.parents[2]) in observed_git_calls
    assert "--no-pager --no-replace-objects" in observed_git_calls
    assert "-c core.hooksPath=/dev/null" in observed_git_calls
    assert "-c core.fsmonitor=false" in observed_git_calls
    assert "-c credential.helper=" in observed_git_calls
    assert "/proc/self/fd/5" in git_calls.with_name("git-endpoint").read_text(encoding="utf-8")
    observed_git_environment = git_calls.with_name("git-environment").read_text(encoding="utf-8")
    assert "GIT_CONFIG=/dev/null" in observed_git_environment
    assert "GIT_CONFIG_NOSYSTEM=1" in observed_git_environment
    assert "GIT_CONFIG_GLOBAL=/dev/null" in observed_git_environment
    assert "GIT_DIR=/attacker/git-dir" not in observed_git_environment
    assert "GIT_CONFIG_GLOBAL=/attacker/gitconfig" not in observed_git_environment
    assert "GIT_ASKPASS=/attacker/askpass" not in observed_git_environment
    observed_environment = environment.read_text(encoding="utf-8")
    assert "MY_PA_DB_PASSWORD=synthetic-password" in observed_environment
    assert "MY_PA_NAS_DOCKER=/attacker/docker" not in observed_environment
    assert "MY_PA_NAS_COMPOSE_PLUGIN=/attacker/docker-compose" not in observed_environment
    assert "MY_PA_NAS_OPERATOR_ADMISSION=/attacker/admission.toml" not in observed_environment
    assert "UNAPPROVED_OPERATOR_VALUE=must-not-pass" not in observed_environment
    assert "SENSITIVE_PARENT_SENTINEL=must-not-inherit" not in observed_environment


@pytest.mark.skipif(
    sys.platform != "linux", reason="requires Linux /proc/self descriptor execution"
)
@pytest.mark.parametrize("disable_globbing", (False, True), ids=("globbing-on", "globbing-off"))
def test_container_python_preserves_literal_wildcard_python_argv(
    tmp_path: Path, disable_globbing: bool
) -> None:
    launcher, calls, _environment, _git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path
    )
    python_argv = ("glob-star-*", "glob-question-?", "glob-bracket-[ab]")
    expanded_entries = ("glob-star-match", "glob-question-x", "glob-bracket-a")
    for entry in expanded_entries:
        (launcher.parent / entry).touch()

    result = _run(
        launcher,
        tools,
        python_argv=python_argv,
        disable_globbing=disable_globbing,
    )

    assert result.returncode == 0, result.stderr
    docker_run_argv = calls.read_text(encoding="utf-8").splitlines()[-1].split()
    assert docker_run_argv[-len(python_argv) :] == list(python_argv)
    assert not set(expanded_entries).intersection(docker_run_argv)


@pytest.mark.skipif(
    sys.platform != "linux", reason="requires Linux /proc/self descriptor execution"
)
@pytest.mark.parametrize("disable_globbing", (False, True), ids=("globbing-on", "globbing-off"))
def test_container_python_preserves_exact_python_argv_with_empty_newline_and_wildcards(
    tmp_path: Path, disable_globbing: bool
) -> None:
    launcher, calls, _environment, _git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path
    )
    python_argv = ("", "line-one\nline-two", "glob-star-*", "glob-question-?", "glob-bracket-[ab]")
    for entry in ("glob-star-match", "glob-question-x", "glob-bracket-a"):
        (launcher.parent / entry).touch()

    result = _run(
        launcher,
        tools,
        python_argv=python_argv,
        disable_globbing=disable_globbing,
    )

    assert result.returncode == 0, result.stderr
    run_argv = calls.with_name("docker-run-argv").read_bytes().split(b"\0")[:-1]
    arguments = [value.decode("utf-8") for value in run_argv]
    assert arguments[0] == "run"
    image_index = arguments.index(IMAGE_ID)
    assert arguments[image_index + 1 :] == list(python_argv)
    assert "" not in arguments[:image_index]


@pytest.mark.skipif(
    sys.platform != "linux", reason="requires Linux /proc/self descriptor execution"
)
@pytest.mark.parametrize(
    ("projection", "expected_error"),
    (
        ("other-engine-id|synthetic-engine", "admitted Docker engine identity does not match"),
        ("synthetic-engine-id|other-engine", "admitted Docker engine identity does not match"),
        ("malformed-projection", "admitted Docker engine identity is malformed"),
        (
            "synthetic-engine-id|synthetic-engine|extra",
            "admitted Docker engine identity is malformed",
        ),
        ("", "admitted Docker engine identity is malformed"),
    ),
)
def test_container_python_refuses_unadmitted_engine_projection_before_image_inspect_or_run(
    tmp_path: Path, projection: str, expected_error: str
) -> None:
    launcher, calls, _environment, _git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path
    )
    _write(tools / "engine-projection", projection + "\n", mode=0o600)

    result = _run(launcher, tools)

    assert result.returncode != 0
    assert expected_error in result.stderr
    assert calls.read_text(encoding="utf-8").splitlines() == ["info --format {{.ID}}|{{.Name}}"]


@pytest.mark.parametrize(
    ("stat_case", "expected_error"),
    (
        ("bad-ancestor-mode", "trusted path ancestors must not be group- or world-writable"),
        ("bad-ancestor-owner", "trusted path ancestors must be root-owned directories"),
        ("bad-file-mode", "Docker must not be group- or world-writable"),
        ("bad-file-owner", "Docker must be a root-owned unlinked regular file"),
        ("bad-nlink", "Docker must be a root-owned unlinked regular file"),
        ("fd-mismatch", "Docker changed while opening"),
    ),
)
def test_container_python_refuses_untrusted_host_authorities_before_docker_or_git(
    tmp_path: Path, stat_case: str, expected_error: str
) -> None:
    launcher, calls, _environment, git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path
    )
    result = _run(launcher, tools, extra_environment={"SYNTH_STAT_CASE": stat_case})
    assert result.returncode != 0
    assert expected_error in result.stderr
    assert not calls.exists()
    assert not git_calls.exists()


def test_container_python_refuses_symlinked_host_authority_before_docker_or_git(
    tmp_path: Path,
) -> None:
    launcher, calls, _environment, git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path
    )
    docker = tools / "docker"
    replacement = tools / "docker-real"
    docker.rename(replacement)
    docker.symlink_to(replacement)
    result = _run(launcher, tools)
    assert result.returncode != 0
    # A canonical-path link is admitted only as the exact pinned DSM chain.
    assert "Docker alias target is not pinned" in result.stderr
    assert not calls.exists()
    assert not git_calls.exists()


@pytest.mark.parametrize(
    ("metadata_case", "expected_error"),
    (
        ("git-file", "repository Git metadata must be a direct directory"),
        ("git-symlink", "repository Git metadata must be a direct directory"),
        ("commondir", "repository Git worktree indirection is not supported"),
        ("config-worktree", "repository Git worktree configuration is not supported"),
        ("alternates", "repository Git object alternates are not supported"),
        ("http-alternates", "repository Git object alternates are not supported"),
    ),
)
def test_container_python_refuses_hostile_git_metadata_before_git(
    tmp_path: Path, metadata_case: str, expected_error: str
) -> None:
    launcher, calls, _environment, git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path
    )
    git_dir = launcher.parents[2] / ".git"
    if metadata_case == "git-file":
        git_dir.rename(launcher.parents[2] / ".git-real")
        git_dir.write_text("gitdir: /synthetic/elsewhere\n", encoding="utf-8")
    elif metadata_case == "git-symlink":
        git_dir.rename(launcher.parents[2] / ".git-real")
        git_dir.symlink_to(launcher.parents[2] / ".git-real", target_is_directory=True)
    elif metadata_case == "commondir":
        _write(git_dir / "commondir", "synthetic\n", mode=0o600)
    elif metadata_case == "config-worktree":
        _write(git_dir / "config.worktree", "synthetic\n", mode=0o600)
    else:
        alternate = "alternates" if metadata_case == "alternates" else "http-alternates"
        _write(git_dir / "objects/info" / alternate, "synthetic\n", mode=0o600)

    result = _run(launcher, tools)

    assert result.returncode != 0
    assert expected_error in result.stderr
    assert not calls.exists()
    assert not git_calls.exists()


@pytest.mark.parametrize(
    ("git_case", "expected_error"),
    (
        ("nonroot-config", "repository Git config must be a root-owned unlinked regular file"),
        ("writable-config", "repository Git config must not be group- or world-writable"),
        ("nonroot-head", "repository Git HEAD must be a root-owned unlinked regular file"),
        ("writable-head", "repository Git HEAD must not be group- or world-writable"),
        ("nonroot-index", "repository Git index must be a root-owned unlinked regular file"),
        ("writable-index", "repository Git index must not be group- or world-writable"),
        ("nonroot-objects", "trusted path ancestors must be root-owned directories"),
        ("writable-objects", "trusted path ancestors must not be group- or world-writable"),
        ("nonroot-refs", "trusted path ancestors must be root-owned directories"),
        ("writable-refs", "trusted path ancestors must not be group- or world-writable"),
        ("nonroot-ancestor", "trusted path ancestors must be root-owned directories"),
        ("writable-ancestor", "trusted path ancestors must not be group- or world-writable"),
        ("malformed-metadata", "repository Git config must be a root-owned unlinked regular file"),
    ),
)
def test_container_python_refuses_untrusted_git_metadata_before_git(
    tmp_path: Path, git_case: str, expected_error: str
) -> None:
    launcher, calls, _environment, git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path
    )
    result = _run(launcher, tools, extra_environment={"SYNTH_GIT_CASE": git_case})

    assert result.returncode != 0
    assert expected_error in result.stderr
    assert not calls.exists()
    assert not git_calls.exists()


@pytest.mark.skipif(
    sys.platform != "linux", reason="requires Linux /proc/self descriptor execution"
)
def test_container_python_refuses_open_source_root_before_git_or_docker(tmp_path: Path) -> None:
    launcher, calls, _environment, git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path
    )
    repo_root = launcher.parents[2]
    repo_root.chmod(0o755)
    lower_privilege_writable = repo_root / "src/my_pa/observed.py"
    lower_privilege_writable.parent.mkdir(parents=True)
    _write(lower_privilege_writable, "synthetic tracked content\n", mode=0o666)

    result = _run(launcher, tools, extra_environment={"SYNTH_GIT_CASE": "open-source-root"})

    assert result.returncode != 0
    assert "repository source root must be root-owned mode 0700" in result.stderr
    assert not calls.exists()
    assert not git_calls.exists()


@pytest.mark.parametrize(
    ("socket_case", "expected_error"),
    (
        ("symlink", "Docker socket must not be a symbolic link"),
        ("wrong-type", "Docker socket is unavailable"),
        ("docker-nonroot", "Docker socket must be a root-owned single-link socket"),
        ("docker-writable-socket", "Docker socket must not be group- or world-writable"),
        # Off DSM the canonical socket keeps the private policy: root:root 0660
        # is refused there; only the pinned DSM real socket admits it.
        ("docker-0660", "Docker socket must not be group- or world-writable"),
        ("docker-0660-nonroot-group", "Docker socket must not be group- or world-writable"),
        ("docker-0666", "Docker socket must not be group- or world-writable"),
        ("docker-0670", "Docker socket must not be group- or world-writable"),
        ("docker-0662", "Docker socket must not be group- or world-writable"),
        ("docker-bad-link", "Docker socket must be a root-owned single-link socket"),
        ("docker-unsupported-metadata", "Docker socket must be a root-owned single-link socket"),
        ("docker-nonroot-ancestor", "trusted path ancestors must be root-owned directories"),
        ("docker-writable-ancestor", "trusted path ancestors must not be group- or world-writable"),
    ),
)
def test_container_python_refuses_hostile_docker_socket_before_all_docker_use(
    tmp_path: Path, socket_case: str, expected_error: str
) -> None:
    launcher, calls, _environment, git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path
    )
    docker_socket = next(path for path in _SYNTHETIC_SOCKET_PATHS if path.name == "docker.sock")
    if socket_case == "symlink":
        target = docker_socket.with_name("docker-real.sock")
        docker_socket.rename(target)
        docker_socket.symlink_to(target)
    elif socket_case == "wrong-type":
        docker_socket.unlink()
        _write(docker_socket, "not a socket\n", mode=0o600)

    result = _run(
        launcher,
        tools,
        extra_environment={"SYNTH_DOCKER_SOCKET_CASE": socket_case},
    )

    assert result.returncode != 0
    assert expected_error in result.stderr
    assert not calls.exists()
    assert not git_calls.exists()


@pytest.mark.skipif(
    sys.platform != "linux", reason="requires Linux /proc/self descriptor execution"
)
def test_container_python_refuses_trusted_git_root_mismatch_before_docker(tmp_path: Path) -> None:
    launcher, calls, _environment, git_calls, tools, _admission, git_state = _synthetic_wrapper(
        tmp_path
    )
    git_state.write_text(f"{COMMIT}\n{TREE}\n\n/synthetic/wrong-root\n", encoding="utf-8")

    result = _run(launcher, tools)

    assert result.returncode != 0
    assert "repository source root is unavailable" in result.stderr
    assert not calls.exists()
    assert git_calls.exists()


@pytest.mark.skipif(
    sys.platform != "linux", reason="requires Linux /proc/self descriptor execution"
)
@pytest.mark.parametrize(
    ("socket_case", "expected_error"),
    (
        ("symlink", "Tailscale socket"),
        (
            "writable-ancestor",
            "trusted path ancestors must not be group- or world-writable",
        ),
        ("nonroot", "Tailscale socket"),
        ("unsupported-metadata", "Tailscale socket"),
        # The Docker socket's root-group 0660 rule never extends to Tailscale.
        ("tailscale-0660", "Tailscale socket must not be group- or world-writable"),
    ),
)
def test_container_python_refuses_hostile_tailscale_socket_before_mount(
    tmp_path: Path, socket_case: str, expected_error: str
) -> None:
    launcher, calls, _environment, _git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path
    )
    tailscale = tools / "tailscale"
    _write(tailscale, "#!/bin/sh\nexit 0\n")
    socket_parent = tmp_path / "socket-parent"
    socket_parent.mkdir()
    socket_path = socket_parent / "tailscale.sock"
    socket_handle = socket.socket(socket.AF_UNIX)
    socket_handle.bind(str(socket_path))
    try:
        selected_socket_path = socket_path
        if socket_case == "symlink":
            selected_socket_path = tmp_path / "tailscale-link.sock"
            selected_socket_path.symlink_to(socket_path)
        result = _run(
            launcher,
            tools,
            extra_environment={
                "MY_PA_NAS_TAILSCALE": str(tailscale),
                "MY_PA_NAS_TAILSCALE_SOCKET": str(selected_socket_path),
                "SYNTH_SOCKET_CASE": socket_case,
            },
        )
    finally:
        socket_handle.close()
        socket_path.unlink(missing_ok=True)

    assert result.returncode != 0
    assert expected_error in result.stderr
    observed_calls = calls.read_text(encoding="utf-8")
    assert "run" not in observed_calls
    assert ":/var/run/tailscale/tailscaled.sock:ro" not in observed_calls


def _run_argv(calls: Path) -> list[str]:
    return [
        part.decode() for part in calls.with_name("docker-run-argv").read_bytes().split(b"\0")[:-1]
    ]


def _relink(link: Path, target: str) -> None:
    link.unlink()
    link.symlink_to(target)


@pytest.mark.skipif(
    sys.platform != "linux", reason="requires Linux /proc/self descriptor execution"
)
@pytest.mark.parametrize("socket_case", ("docker-0660", ""), ids=("root-group-0660", "0600"))
def test_container_python_accepts_exact_pinned_dsm_aliases(
    tmp_path: Path, socket_case: str
) -> None:
    launcher, calls, _environment, git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path, dsm_layout=True
    )
    dsm = _dsm_paths(tmp_path)
    assert str((tools / "git").readlink()) == str(dsm["git_alias_target"])
    assert str(dsm["socket_alias_dir"].readlink()) == "../run"

    result = _run(launcher, tools, extra_environment={"SYNTH_DOCKER_SOCKET_CASE": socket_case})

    assert result.returncode == 0, result.stderr
    arguments = _run_argv(calls)
    mounts = [
        arguments[index + 1] for index, value in enumerate(arguments[:-1]) if value == "--volume"
    ]
    assert f"{dsm['socket_real']}:/var/run/docker.sock" in mounts
    assert f"{dsm['docker_real']}:/usr/local/bin/docker:ro" in mounts
    assert f"{dsm['compose_real']}:{tools}/plugins/docker-compose:ro" in mounts
    sources = {mount.partition(":")[0] for mount in mounts}
    for alias in (
        tools / "docker",
        tools / "docker-compose",
        dsm["socket_alias_dir"] / "docker.sock",
        dsm["docker_alias_target"],
        dsm["compose_alias_target"],
    ):
        assert str(alias) not in sources
    assert "/proc/self/fd/5" in git_calls.with_name("git-endpoint").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("link_case", "expected_error"),
    (
        ("docker-canonical-absolute-real", "Docker alias target is not pinned"),
        ("docker-store-relative", "Docker package store alias target is not pinned"),
        ("compose-canonical-absolute-real", "Docker Compose plugin alias target is not pinned"),
        ("git-canonical-absolute-real", "Git alias target is not pinned"),
        ("git-canonical-trailing-newline", "Git alias target is not pinned"),
        ("git-store-trailing-slash", "Git package store alias target is not pinned"),
        ("socket-dir-absolute", "Docker socket directory alias target is not pinned"),
        ("socket-dir-trailing-slash", "Docker socket directory alias target is not pinned"),
    ),
)
def test_container_python_refuses_unpinned_dsm_alias_literal_target(
    tmp_path: Path, link_case: str, expected_error: str
) -> None:
    launcher, calls, _environment, git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path, dsm_layout=True
    )
    dsm = _dsm_paths(tmp_path)
    # Each replacement still resolves to the same pinned file or directory
    # (except the newline case), so only the literal-target compare refuses.
    if link_case == "docker-canonical-absolute-real":
        _relink(tools / "docker", str(dsm["docker_real"]))
    elif link_case == "docker-store-relative":
        store_alias = dsm["docker_store_alias"]
        _relink(store_alias, os.path.relpath(dsm["docker_store_target"], store_alias.parent))
    elif link_case == "compose-canonical-absolute-real":
        _relink(tools / "docker-compose", str(dsm["compose_real"]))
    elif link_case == "git-canonical-absolute-real":
        _relink(tools / "git", str(dsm["git_real"]))
    elif link_case == "git-canonical-trailing-newline":
        _relink(tools / "git", str(dsm["git_alias_target"]) + "\n")
    elif link_case == "git-store-trailing-slash":
        _relink(dsm["git_store_alias"], str(dsm["git_store_target"]) + "/")
    elif link_case == "socket-dir-absolute":
        _relink(dsm["socket_alias_dir"], str(dsm["socket_root"] / "run"))
    else:
        _relink(dsm["socket_alias_dir"], "../run/")

    result = _run(launcher, tools)

    assert result.returncode != 0
    assert expected_error in result.stderr
    assert not calls.exists()
    assert not git_calls.exists()


@pytest.mark.parametrize(
    ("alias_case", "alias_match", "expected_error"),
    (
        ("nonroot", "/trusted-tools/docker", "Docker alias is not the pinned symbolic link"),
        (
            "nonroot",
            "/packages/Git/target",
            "Git package store alias is not the pinned symbolic link",
        ),
        ("nonroot", "/var/run", "Docker socket directory alias is not the pinned symbolic link"),
        ("links", "/trusted-tools/git", "Git alias is not the pinned symbolic link"),
        (
            "links",
            "/packages/ContainerManager/target",
            "Docker package store alias is not the pinned symbolic link",
        ),
        ("links", "/var/run", "Docker socket directory alias is not the pinned symbolic link"),
        # A real link whose metadata type is not a link: only the type check.
        ("kind-directory", "/trusted-tools/docker", "Docker alias is not the pinned symbolic link"),
        ("drift", "/trusted-tools/docker-compose", "Docker Compose plugin alias changed"),
        ("drift", "/var/run", "Docker socket directory alias changed while verifying"),
        # Passes both pre-open checks, then changes: only the post-open
        # re-verification can refuse it.
        ("late-nonroot", "/trusted-tools/git", "Git alias is not the pinned symbolic link"),
        (
            "late-nonroot",
            "/packages/Git/target",
            "Git package store alias is not the pinned symbolic link",
        ),
        (
            "late-nonroot",
            "/var/run",
            "Docker socket directory alias is not the pinned symbolic link",
        ),
    ),
)
def test_container_python_refuses_untrusted_dsm_alias_metadata(
    tmp_path: Path, alias_case: str, alias_match: str, expected_error: str
) -> None:
    launcher, calls, _environment, git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path, dsm_layout=True
    )
    result = _run(
        launcher,
        tools,
        extra_environment={"SYNTH_ALIAS_CASE": alias_case, "SYNTH_ALIAS_MATCH": alias_match},
    )
    assert result.returncode != 0
    assert expected_error in result.stderr
    assert not calls.exists()
    assert not git_calls.exists()


@pytest.mark.parametrize(
    ("alias_match", "release_key", "expected_error"),
    (
        ("/trusted-tools/git", "git_real", "Git alias is not the pinned symbolic link"),
        (
            "/packages/Git/target",
            "git_real",
            "Git package store alias is not the pinned symbolic link",
        ),
        (
            "/packages/ContainerManager/target",
            "docker_real",
            "Docker package store alias is not the pinned symbolic link",
        ),
        (
            "/var/run",
            "socket_real",
            "Docker socket directory alias is not the pinned symbolic link",
        ),
    ),
)
def test_container_python_refuses_dsm_alias_fault_present_only_before_real_access(
    tmp_path: Path, alias_match: str, release_key: str, expected_error: str
) -> None:
    """The alias is non-root only until its real file or socket is first inspected.

    The post-open (post-check) re-verification sees a clean alias, so only the
    pre-open (pre-check) verification can refuse this fault.
    """
    launcher, calls, _environment, git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path, dsm_layout=True
    )
    release = tmp_path / "alias-stat-count.released"
    result = _run(
        launcher,
        tools,
        extra_environment={
            "SYNTH_ALIAS_CASE": "early-nonroot",
            "SYNTH_ALIAS_MATCH": alias_match,
            "SYNTH_ALIAS_RELEASE": str(_dsm_paths(tmp_path)[release_key]),
        },
    )
    assert result.returncode != 0
    assert expected_error in result.stderr
    assert not release.exists()
    assert not calls.exists()
    assert not git_calls.exists()


@pytest.mark.parametrize(
    ("tool_case", "expected_error"),
    (
        ("docker-real-nlink", "Docker must be a root-owned unlinked regular file"),
        (
            "compose-real-nlink",
            "Docker Compose plugin must be a root-owned unlinked regular file",
        ),
        ("git-mode-750", "Git must be a root-owned mode 0755 regular file"),
        ("git-mode-775", "Git must be a root-owned mode 0755 regular file"),
        ("git-nonroot", "Git must be a root-owned mode 0755 regular file"),
        ("git-zero-links", "Git must be a root-owned mode 0755 regular file"),
        ("writable-store", "trusted path ancestors must not be group- or world-writable"),
        ("writable-alias-parent", "trusted path ancestors must not be group- or world-writable"),
    ),
)
def test_container_python_refuses_untrusted_dsm_real_tool_metadata(
    tmp_path: Path, tool_case: str, expected_error: str
) -> None:
    launcher, calls, _environment, git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path, dsm_layout=True
    )
    result = _run(launcher, tools, extra_environment={"SYNTH_TOOL_CASE": tool_case})
    assert result.returncode != 0
    assert expected_error in result.stderr
    assert not calls.exists()
    assert not git_calls.exists()


@pytest.mark.parametrize(
    "socket_case",
    ("docker-0660-nonroot-group", "docker-0666", "docker-0670", "docker-0662"),
)
def test_container_python_refuses_wider_dsm_docker_socket_than_root_group_0660(
    tmp_path: Path, socket_case: str
) -> None:
    # The root-group rule applies only on the pinned DSM real socket, so its
    # exact group-0 and mode-0660 bounds are exercised on that path.
    launcher, calls, _environment, git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path, dsm_layout=True
    )
    result = _run(launcher, tools, extra_environment={"SYNTH_DOCKER_SOCKET_CASE": socket_case})
    assert result.returncode != 0
    assert "Docker socket must not be group- or world-writable" in result.stderr
    assert not calls.exists()
    assert not git_calls.exists()


@pytest.mark.parametrize("store", ("git_store_target", "docker_store_target"))
def test_container_python_refuses_unpinned_link_inside_dsm_real_ancestors(
    tmp_path: Path, store: str
) -> None:
    launcher, calls, _environment, git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path, dsm_layout=True
    )
    store_target = _dsm_paths(tmp_path)[store]
    nested = store_target / ("bin" if store == "git_store_target" else "usr")
    nested.rename(nested.with_name(nested.name + "-real"))
    nested.symlink_to(nested.name + "-real", target_is_directory=True)

    result = _run(launcher, tools)

    assert result.returncode != 0
    assert "trusted path contains a symbolic link" in result.stderr
    assert not calls.exists()
    assert not git_calls.exists()


@pytest.mark.parametrize("claimed_kind", ("real", "kind-link"))
def test_container_python_refuses_real_directory_in_place_of_dsm_store_alias(
    tmp_path: Path, claimed_kind: str
) -> None:
    launcher, calls, _environment, git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path, dsm_layout=True
    )
    dsm = _dsm_paths(tmp_path)
    store_alias = dsm["docker_store_alias"]
    store_alias.unlink()
    shutil.copytree(dsm["docker_store_target"], store_alias)
    # `kind-link` makes metadata claim a link, isolating the `[ -L ]` check.
    extra_environment = (
        {}
        if claimed_kind == "real"
        else {"SYNTH_ALIAS_CASE": claimed_kind, "SYNTH_ALIAS_MATCH": "/ContainerManager/target"}
    )

    result = _run(launcher, tools, extra_environment=extra_environment)

    assert result.returncode != 0
    assert "Docker package store alias is not the pinned symbolic link" in result.stderr
    assert not calls.exists()
    assert not git_calls.exists()


@pytest.mark.parametrize("constant", ("git_alias_target", "docker_socket_real_path"))
def test_container_python_refuses_inconsistent_pinned_alias_constants(
    tmp_path: Path, constant: str
) -> None:
    launcher, calls, _environment, git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path, dsm_layout=True
    )
    dsm = _dsm_paths(tmp_path)
    source = launcher.read_text(encoding="utf-8")
    if constant == "git_alias_target":
        # The canonical link matches its (drifted) pinned target exactly, but
        # that target no longer names the pinned real file that would be run.
        drifted = dsm["git_store_alias"] / "bin/git-other"
        before = f"\ngit_alias_target={dsm['git_alias_target']}\n"
        _relink(tools / "git", str(drifted))
        expected_error = "Git pinned alias layout is inconsistent"
    else:
        # A valid socket elsewhere that is not the alias's literal resolution.
        drifted = dsm["socket_root"] / "other/docker.sock"
        drifted.parent.mkdir()
        _bind_socket(drifted)
        before = f"\ndocker_socket_real_path={dsm['socket_real']}\n"
        expected_error = "Docker socket pinned alias layout is inconsistent"
    assert source.count(before) == 1
    _write(launcher, source.replace(before, f"\n{constant}={drifted}\n"))

    result = _run(launcher, tools)

    assert result.returncode != 0
    assert expected_error in result.stderr
    assert not calls.exists()
    assert not git_calls.exists()


@pytest.mark.parametrize("case", ("git-real-outside-store", "socket-path-outside-alias-dir"))
def test_container_python_refuses_pinned_alias_constants_only_layout_guard_detects(
    tmp_path: Path, case: str
) -> None:
    # Each rewrite is consistent everywhere except under one static layout
    # guard, so the wrapper would otherwise accept and run the drifted layout.
    launcher, calls, _environment, git_calls, tools, _admission, _git_state = _synthetic_wrapper(
        tmp_path, dsm_layout=True
    )
    dsm = _dsm_paths(tmp_path)
    source = launcher.read_text(encoding="utf-8")
    if case == "git-real-outside-store":
        # A real Git file on another volume, outside its store target, with the
        # alias target and canonical link rewritten so the store-alias join
        # still matches: a prefix strip that does not apply leaves the outside
        # path intact, and the file otherwise passes every real-file check.
        outside = tmp_path / "dsm/volume2/@appstore/Git/bin/git"
        outside.parent.mkdir(parents=True)
        shutil.copy2(dsm["git_real"], outside)
        alias_target = f"{dsm['git_store_alias']}{outside}"
        assert not str(outside).startswith(f"{dsm['git_store_target']}/")
        _relink(tools / "git", alias_target)
        rewrites = {
            "git_real_path": (dsm["git_real"], outside),
            "git_alias_target": (dsm["git_alias_target"], alias_target),
        }
        expected_error = "Git pinned alias layout is inconsistent"
    else:
        # The real socket stays the alias's literal resolution; only the
        # canonical socket path leaves the alias directory.
        outside = dsm["socket_root"] / "other/docker.sock"
        outside.parent.mkdir()
        _bind_socket(outside)
        rewrites = {
            "docker_socket_path": (dsm["socket_alias_dir"] / "docker.sock", outside),
        }
        expected_error = "Docker socket pinned alias layout is inconsistent"
    for name, (current, drifted) in rewrites.items():
        before = f"\n{name}={current}\n"
        assert source.count(before) == 1, name
        source = source.replace(before, f"\n{name}={drifted}\n")
    _write(launcher, source)

    result = _run(launcher, tools)

    assert result.returncode != 0
    assert expected_error in result.stderr
    assert not calls.exists()
    assert not git_calls.exists()


def _function_harness(tmp_path: Path, body: str) -> Path:
    """Return a script holding only the launcher's definitions plus ``body``.

    The launcher's top-level work starts at a fixed marker; everything before
    it is assignments and function definitions, so policy functions can be
    exercised directly against synthetic metadata.
    """
    if sys.platform != "linux":
        pytest.skip("requires Linux filesystem sockets and symlink-free temporary ancestors")
    source = (ROOT / "ops/nas/container-python.sh").read_text(encoding="utf-8")
    prefix, marker, _rest = source.partition(_FUNCTION_SECTION_END)
    assert marker
    stub = tmp_path / "harness-stat"
    _write(
        stub,
        "#!/bin/sh\n"
        'case "$2" in\n'
        "  '%u:%a:%F') printf '0:755:directory\\n' ;;\n"
        "  '%u:%a:%h:%F') printf '%s\\n' \"$SYNTH_FILE_METADATA\" ;;\n"
        "  '%u:%g:%a:%h:%F') printf '%s\\n' \"$SYNTH_SOCKET_METADATA\" ;;\n"
        "  '%u:%h:%F:%d:%i:%Y:%Z') printf '0:1:symbolic link:1:2:3:4\\n' ;;\n"
        "  *) exit 97 ;;\n"
        "esac\n",
    )
    prefix = prefix.replace("stat_bin=/usr/bin/stat", f"stat_bin={stub}")
    harness = tmp_path / "harness.sh"
    _write(harness, prefix + body)
    return harness


def _run_harness(
    harness: Path, environment: dict[str, str], *arguments: str, shell: str = "/bin/sh"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - checked-in definitions with synthetic metadata
        [shell, str(harness), *arguments],
        env={"PATH": "/usr/bin:/bin", **environment},
        check=False,
        capture_output=True,
        text=True,
    )


def test_shared_link_policy_is_restricted_to_the_pinned_git_binary(tmp_path: Path) -> None:
    pinned = tmp_path / "pinned-git"
    other = tmp_path / "other-tool"
    for path in (pinned, other):
        _write(path, "#!/bin/sh\nexit 0\n", mode=0o755)
    harness = _function_harness(
        tmp_path,
        f'git_real_path={pinned}\nverify_root_owned_regular_file "$1" Synthetic "$2"\n',
    )
    shared = {"SYNTH_FILE_METADATA": "0:755:142:regular file"}

    accepted = _run_harness(harness, shared, str(pinned), "pinned-git-shared-link")
    refused = _run_harness(harness, shared, str(other), "pinned-git-shared-link")
    default = _run_harness(harness, shared, str(pinned), "single-link")
    unknown = _run_harness(harness, shared, str(pinned), "shared")

    assert accepted.returncode == 0, accepted.stderr
    assert refused.returncode != 0
    assert "Synthetic shared-link policy is restricted to the pinned Git binary" in refused.stderr
    assert default.returncode != 0
    assert "Synthetic must be a root-owned unlinked regular file" in default.stderr
    assert unknown.returncode != 0
    assert "internal link policy selection is invalid" in unknown.stderr


def test_docker_root_group_socket_policy_is_restricted_to_the_docker_socket(
    tmp_path: Path,
) -> None:
    socket_root = _socket_root(tmp_path)
    socket_root.mkdir()
    _SYNTHETIC_SOCKET_ROOTS.add(socket_root)
    docker_socket = socket_root / "docker.sock"
    docker_real_socket = socket_root / "real-docker.sock"
    tailscale_socket = socket_root / "tailscale.sock"
    for path in (docker_socket, docker_real_socket, tailscale_socket):
        _bind_socket(path)
    harness = _function_harness(
        tmp_path,
        f"docker_socket_path={docker_socket}\n"
        f"docker_socket_real_path={docker_real_socket}\n"
        'verify_root_owned_socket "$1" "$2" "$3"\n',
    )
    group_writable = {"SYNTH_SOCKET_METADATA": "0:0:660:1:socket"}

    docker_real = _run_harness(
        harness, group_writable, str(docker_real_socket), "Docker socket", "docker-root-group"
    )
    docker_canonical = _run_harness(
        harness, group_writable, str(docker_socket), "Docker socket", "docker-root-group"
    )
    tailscale_policy = _run_harness(
        harness, group_writable, str(tailscale_socket), "Tailscale socket", "docker-root-group"
    )
    tailscale_private = _run_harness(
        harness, group_writable, str(tailscale_socket), "Tailscale socket", "private"
    )

    assert docker_real.returncode == 0, docker_real.stderr
    # The canonical non-DSM socket path never takes the root-group policy.
    assert docker_canonical.returncode != 0
    assert (
        "Docker socket root-group policy is restricted to the Docker socket"
        in docker_canonical.stderr
    )
    assert tailscale_policy.returncode != 0
    assert (
        "Tailscale socket root-group policy is restricted to the Docker socket"
        in tailscale_policy.stderr
    )
    assert tailscale_private.returncode != 0
    assert "Tailscale socket must not be group- or world-writable" in tailscale_private.stderr


@pytest.mark.parametrize("shell", ("/bin/sh", "/bin/bash"))
def test_pinned_alias_refuses_a_failed_literal_read(tmp_path: Path, shell: str) -> None:
    # dash propagates `set -e` into command substitutions, which already stops
    # a failed read; bash outside POSIX mode does not, so only the `&&` before
    # the sentinel refuses there. Exercise both interpreters.
    if not Path(shell).is_file():
        pytest.skip(f"{shell} is unavailable")
    target = tmp_path / "pinned-target"
    link = tmp_path / "pinned-link"
    link.symlink_to(str(target))
    # A reader that prints the exact pinned target but reports failure.
    failing_readlink = tmp_path / "failing-readlink"
    _write(failing_readlink, f"#!/bin/sh\nprintf '%s\\n' '{target}'\nexit 1\n")
    working = _function_harness(
        tmp_path,
        'verify_pinned_alias "$1" "$2" Synthetic\n',
    )
    failing = tmp_path / "failing-harness.sh"
    source = working.read_text(encoding="utf-8")
    assert "readlink_bin=/usr/bin/readlink" in source
    _write(
        failing,
        source.replace("readlink_bin=/usr/bin/readlink", f"readlink_bin={failing_readlink}"),
    )

    accepted = _run_harness(working, {}, str(link), str(target), shell=shell)
    refused = _run_harness(failing, {}, str(link), str(target), shell=shell)

    assert accepted.returncode == 0, accepted.stderr
    assert refused.returncode != 0
    assert "Synthetic alias target is not pinned" in refused.stderr
