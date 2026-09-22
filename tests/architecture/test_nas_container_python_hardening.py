"""Synthetic fail-closed coverage for the NAS operator Python launcher."""

from __future__ import annotations

import os
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


@pytest.fixture(autouse=True)
def _remove_synthetic_socket_paths() -> None:
    yield
    while _SYNTHETIC_SOCKET_PATHS:
        socket_path = _SYNTHETIC_SOCKET_PATHS.pop()
        for entry in socket_path.parent.iterdir():
            entry.unlink(missing_ok=True)
        socket_path.parent.rmdir()


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


def _synthetic_wrapper(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path, Path, Path]:
    """Copy the checked-in launcher with only its fixed host paths redirected.

    The production source is separately asserted to contain the canonical paths.
    This fixture never resolves a real Docker client, admission, or NAS path.
    """
    if sys.platform != "linux":
        pytest.skip("requires Linux filesystem sockets and /proc descriptor behavior")
    tools = tmp_path / "trusted-tools"
    repo = tmp_path / "trusted-source"
    launcher = repo / "ops/nas/container-python.sh"
    socket_suffix = sha256(str(tmp_path).encode("utf-8")).hexdigest()[:12]
    docker_socket_parent = Path(gettempdir()) / f"my-pa-ds-{socket_suffix}"
    docker_socket = docker_socket_parent / "docker.sock"
    admission = tmp_path / "operator-runtime.toml"
    git_state = tmp_path / "git-state"
    calls = tmp_path / "docker-calls"
    environment = tmp_path / "docker-environment"
    engine_projection = tools / "engine-projection"
    git_calls = tmp_path / "git-calls"
    git_environment = tmp_path / "git-environment"
    git_endpoint = tmp_path / "git-endpoint"
    tools.mkdir()
    _write(engine_projection, "synthetic-engine-id|synthetic-engine\n", mode=0o600)
    launcher.parent.mkdir(parents=True)
    docker_socket_parent.mkdir()
    socket_handle = socket.socket(socket.AF_UNIX)
    socket_handle.bind(str(docker_socket))
    socket_handle.close()
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
    _write(
        stat,
        "#!/bin/sh\n"
        "format=$2\npath=$4\n"
        'case "$format" in\n'
        "  '%u:%a:%F')\n"
        '    case "${SYNTH_DOCKER_SOCKET_CASE:-}:$path" in\n'
        "      docker-nonroot-ancestor:*/my-pa-ds-*) printf '1000:700:directory\\n' ;;\n"
        "      docker-writable-ancestor:*/my-pa-ds-*) printf '0:777:directory\\n' ;;\n"
        "      *)\n"
        '    case "${SYNTH_GIT_CASE:-}:$path" in\n'
        "      nonroot-ancestor:*/trusted-source) printf '1000:700:directory\\n' ;;\n"
        "      writable-ancestor:*/trusted-source) printf '0:777:directory\\n' ;;\n"
        "      nonroot-objects:*/.git/objects) printf '1000:700:directory\\n' ;;\n"
        "      writable-objects:*/.git/objects) printf '0:777:directory\\n' ;;\n"
        "      nonroot-refs:*/.git/refs) printf '1000:700:directory\\n' ;;\n"
        "      writable-refs:*/.git/refs) printf '0:777:directory\\n' ;;\n"
        "      *:*/.git/*) printf '0:700:directory\\n' ;;\n"
        "      *)\n"
        '    case "${SYNTH_SOCKET_CASE:-}:$path" in\n'
        "      writable-ancestor:*/socket-parent) printf '0:777:directory\\n' ;;\n"
        "      nonroot:*/socket-parent/tailscale.sock) printf '1000:600:socket\\n' ;;\n"
        "      unsupported-metadata:*/socket-parent/tailscale.sock) printf '0:600:unknown\\n' ;;\n"
        "      *:*/socket-parent/tailscale.sock) printf '0:600:socket\\n' ;;\n"
        "      *)\n"
        "        case ${SYNTH_STAT_CASE:-ok} in\n"
        "          bad-ancestor-mode) printf '0:777:directory\\n' ;;\n"
        "          bad-ancestor-owner) printf '1000:700:directory\\n' ;;\n"
        "          *) printf '0:700:directory\\n' ;;\n"
        "        esac ;;\n"
        "    esac ;;\n"
        "    esac ;;\n"
        "    esac ;;\n"
        "  '%u:%a:%h:%F')\n"
        '    case "$path" in\n'
        "      *operator-runtime.toml)\n"
        "        printf '%s\\n' \"${SYNTH_ADMISSION_METADATA:-0:400:1:regular file}\" ;;\n"
        "      *)\n"
        '        case "${SYNTH_DOCKER_SOCKET_CASE:-}:$path" in\n'
        "          docker-nonroot:*/my-pa-ds-*/"
        "docker.sock) printf '1000:600:1:socket\\n' ;;\n"
        "          docker-writable-socket:*/my-pa-ds-*/"
        "docker.sock) printf '0:620:1:socket\\n' ;;\n"
        "          docker-bad-link:*/my-pa-ds-*/"
        "docker.sock) printf '0:600:2:socket\\n' ;;\n"
        "          docker-unsupported-metadata:*/my-pa-ds-*/"
        "docker.sock) printf 'unsupported metadata\\n' ;;\n"
        "          *:*/my-pa-ds-*/docker.sock) printf '0:600:1:socket\\n' ;;\n"
        "          *)\n"
        '        case "${SYNTH_GIT_CASE:-}:$path" in\n'
        "          nonroot-config:*/.git/config|nonroot-head:*/.git/HEAD|"
        "nonroot-index:*/.git/index)\n"
        "            printf '1000:400:1:regular file\\n' ;;\n"
        "          writable-config:*/.git/config|writable-head:*/.git/HEAD|"
        "writable-index:*/.git/index)\n"
        "            printf '0:620:1:regular file\\n' ;;\n"
        "          malformed-metadata:*/.git/config) printf 'malformed metadata\\n' ;;\n"
        "          *:*/.git/*) printf '0:400:1:regular file\\n' ;;\n"
        "          *)\n"
        "            case ${SYNTH_STAT_CASE:-ok} in\n"
        "              bad-file-mode) printf '0:620:1:regular file\\n' ;;\n"
        "              bad-file-owner) printf '1000:400:1:regular file\\n' ;;\n"
        "              bad-nlink) printf '0:400:2:regular file\\n' ;;\n"
        "              *) printf '0:400:1:regular file\\n' ;;\n"
        "            esac ;;\n"
        "        esac ;;\n"
        "        esac ;;\n"
        "    esac ;;\n"
        "  '%d:%i')\n"
        '    case "${SYNTH_STAT_CASE:-ok}:$path" in\n'
        "      fd-mismatch:/proc/*|fd-mismatch:/dev/fd/*) printf '11:23\\n' ;;\n"
        "      *) printf '11:22\\n' ;;\n"
        "    esac ;;\n"
        "  *) exit 97 ;;\n"
        "esac\n",
    )
    docker = tools / "docker"
    _write(
        docker,
        "#!/bin/sh\n"
        f'calls="{calls}"\n'
        f'environment="{environment}"\n'
        f'engine_projection="{engine_projection}"\n'
        'printf \'%s\\n\' "$*" >> "$calls"\n'
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
    compose = tools / "docker-compose"
    _write(compose, "#!/bin/sh\nexit 0\n")
    git = tools / "git"
    _write(
        git,
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
    assert '"$docker_fd" image inspect' in source
    assert '"$docker_fd" run' in source
    assert "\"$docker_fd\" info --format '{{.ID}}|{{.Name}}'" in source
    assert "trusted_git()" in source
    assert '"$git_fd" --no-pager --no-replace-objects' in source
    assert "verify_fd_path=/proc/$$/fd/3" in source
    assert "execution_fd_path=/proc/self/fd/3" in source
    assert source.count('open_verified_file_descriptor "$compose_path"') == 1
    assert "verify_root_owned_socket \"$docker_socket_path\" 'Docker socket'" in source
    assert '--volume "$docker_socket_path:/var/run/docker.sock"' in source


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
    admission.write_text(contents, encoding="utf-8")

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
        admission.write_text(_admission_contents(Path("/synthetic/wrong-source")), encoding="utf-8")
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
    assert "Docker must not be a symbolic link" in result.stderr
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


@pytest.mark.parametrize(
    ("socket_case", "expected_error"),
    (
        ("symlink", "Docker socket must not be a symbolic link"),
        ("wrong-type", "Docker socket is unavailable"),
        ("docker-nonroot", "Docker socket must be a root-owned single-link socket"),
        ("docker-writable-socket", "Docker socket must not be group- or world-writable"),
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
