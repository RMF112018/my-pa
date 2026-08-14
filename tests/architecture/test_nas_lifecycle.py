"""NAS-09 lifecycle, evidence trust, cleanup, and health contracts."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "ops/nas/compose.example.yml"
OVERLAY = ROOT / "ops/nas/compose.pilot.example.yml"
HEAD = "1" * 40
TREE = "2" * 40
ENGINE_ID = "engine-id"
ENGINE_NAME = "nas-name"


def _module(name: str) -> ModuleType:
    path = ROOT / "ops/nas" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(tmp_path: Path, *, commit: str = HEAD) -> Path:
    path = tmp_path / "image-manifest.toml"
    path.write_text(
        'schema = "my-pa.nas-image-manifest.v1"\nstatus = "deployable"\n'
        f'repository_commit = "{commit}"\nrepository_tree = "{TREE}"\n'
        f'docker_engine_id = "{ENGINE_ID}"\ndocker_engine_name = "{ENGINE_NAME}"\n',
        encoding="utf-8",
    )
    return path


def _complete_manifest(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    ids = {
        "app": "sha256:" + "a" * 64,
        "web": "sha256:" + "b" * 64,
        "postgres": "sha256:" + "c" * 64,
        "proxy": "sha256:" + "d" * 64,
    }
    digests = {
        "app": "1" * 64,
        "web": "2" * 64,
        "postgres": "dbbeb22a65db2503050cdbbe5e78f017478f10a1002a226463f049dbb017e99b",
        "proxy": "3" * 64,
    }
    path = tmp_path / "complete-image-manifest.toml"
    sections = []
    for name in ("app", "web", "postgres", "proxy"):
        digest = "sha256:" + digests[name]
        if name == "postgres":
            reference = (
                "postgres@sha256:dbbeb22a65db2503050cdbbe5e78f017478f10a1002a226463f049dbb017e99b"
            )
        elif name == "proxy":
            reference = f"caddy@{digest}"
        else:
            reference = f"my-pa-{name}@{digest}"
        sections.append(
            f'[images.{name}]\nreference = "{reference}"\nload_reference = "{ids[name]}"\n'
            f'oci_manifest_digest = "{digest}"\ndocker_image_id = "{ids[name]}"\n'
            f'archive_sha256 = "{"4" * 64}"\nbuild_metadata_sha256 = "{"5" * 64}"\n'
        )
    path.write_text(
        'schema = "my-pa.nas-image-manifest.v1"\nstatus = "deployable"\n'
        f'repository_commit = "{HEAD}"\nrepository_tree = "{TREE}"\nsource_clean = true\n'
        'built_at = "2026-08-13T12:00:00Z"\ntarget_os = "linux"\n'
        f'target_architecture = "amd64"\ndocker_engine_id = "{ENGINE_ID}"\n'
        f'docker_engine_name = "{ENGINE_NAME}"\npython_runtime_lock_sha256 = "{"6" * 64}"\n'
        'postgres_source_tag = "postgres:17.10"\n'
        "postgres_index_digest = "
        '"sha256:7958605b474b3d264a969cb3a123d6aa00ad1e1fe9da8a69984dabb704d93317"\n'
        + "".join(sections),
        encoding="utf-8",
    )
    return path, ids


def _runtime_fixture(
    tmp_path: Path,
) -> tuple[Path, Path, dict[str, str], dict[str, str], str, str]:
    manifest, ids = _complete_manifest(tmp_path)
    service_ids = {
        "postgres": ids["postgres"],
        "gateway": ids["app"],
        "worker-enrollment": ids["app"],
        "worker-capture": ids["app"],
        "web": ids["web"],
        "proxy": ids["proxy"],
    }
    service_images = {
        **service_ids,
        "proxy": "caddy@sha256:" + "8" * 64,
    }
    rendered = {"name": "my-pa-nas-contract", "services": {}}
    pilot_rendered = {"name": "my-pa-nas-contract", "services": {}}
    for name, image in service_images.items():
        rendered["services"][name] = {"image": image, "restart": "no"}
        pilot_rendered["services"][name] = {"image": image, "restart": "unless-stopped"}
    rendered_text = json.dumps(rendered)
    pilot_rendered_text = json.dumps(pilot_rendered)
    canonical = json.dumps(rendered, sort_keys=True, separators=(",", ":")).encode()
    pilot_canonical = json.dumps(pilot_rendered, sort_keys=True, separators=(",", ":")).encode()
    admission = tmp_path / "runtime-admission.toml"
    admission.write_text(
        'schema = "my-pa.nas-runtime-admission.v1"\nstatus = "admitted"\n'
        f'docker_engine_id = "{ENGINE_ID}"\ndocker_engine_name = "{ENGINE_NAME}"\n'
        f'image_manifest_sha256 = "{_sha(manifest)}"\n'
        "[resolved_compose_sha256]\n"
        f'smoke = "{hashlib.sha256(canonical).hexdigest()}"\n'
        f'pilot = "{hashlib.sha256(pilot_canonical).hexdigest()}"\n'
        "[service_images]\n"
        + "".join(f'{name} = "{value}"\n' for name, value in service_images.items())
        + "[service_image_ids]\n"
        + "".join(f'{name} = "{value}"\n' for name, value in service_ids.items()),
        encoding="utf-8",
    )
    admission.chmod(0o400)
    return (
        manifest,
        admission,
        service_images,
        service_ids,
        rendered_text,
        pilot_rendered_text,
    )


def _runner(command: list[str]) -> str:
    if command[-1] == "HEAD":
        return HEAD
    if command[-1] == "HEAD^{tree}":
        return TREE
    if command[-1] == "--porcelain":
        return ""
    if command[:2] == ["docker", "info"]:
        return json.dumps({"ID": ENGINE_ID, "Name": ENGINE_NAME})
    raise AssertionError(command)


def _signed_evidence(
    tmp_path: Path,
    manifest: Path,
    *,
    activated_at: str = "2026-08-13T12:01:00Z",
    canonical_origin: str = "https://my-pa.tailnet.ts.net",
) -> Path:
    trusted = tmp_path / "trusted"
    trusted.mkdir(mode=0o700)
    private = tmp_path / "operator-private.pem"
    subprocess.run(  # noqa: S603 - fixed OpenSSL with synthetic temporary key
        ["/usr/bin/openssl", "genrsa", "-out", str(private), "3072"],
        check=True,
    )
    public = trusted / "operator-public-key.pem"
    with public.open("wb") as output:
        subprocess.run(  # noqa: S603 - fixed OpenSSL with synthetic temporary key
            ["/usr/bin/openssl", "rsa", "-in", str(private), "-pubout"],
            check=True,
            stdout=output,
        )
    trust = trusted / "trust.toml"
    trust.write_text(
        'schema = "my-pa.nas-pilot-trust.v1"\nstatus = "provisioned"\n'
        f'operator_public_key_sha256 = "{_sha(public)}"\n'
        f'nas_engine_id = "{ENGINE_ID}"\nnas_engine_name = "{ENGINE_NAME}"\n',
        encoding="utf-8",
    )
    runtime_admission = tmp_path / "pilot-runtime-admission.toml"
    runtime_admission.write_text(
        f'[resolved_compose_sha256]\nsmoke = "{"6" * 64}"\npilot = "{"7" * 64}"\n',
        encoding="utf-8",
    )
    acceptance = trusted / "nas-10-acceptance.toml"
    acceptance.write_text(
        'schema = "my-pa.nas-10-acceptance.v1"\nstatus = "pass"\n'
        f'repository_commit = "{HEAD}"\nrepository_tree = "{TREE}"\n'
        f'reviewed_head = "{HEAD}"\ncompleted_at = "2026-08-13T12:00:00Z"\n'
        f'nas_engine_id = "{ENGINE_ID}"\nnas_engine_name = "{ENGINE_NAME}"\n'
        f'compose_sha256 = "{_sha(COMPOSE)}"\n'
        f'runtime_contract_sha256 = "{_sha(ROOT / "ops/nas/runtime-contract.toml")}"\n'
        f'image_manifest_sha256 = "{_sha(manifest)}"\n'
        f'runtime_admission_sha256 = "{_sha(runtime_admission)}"\n'
        f'resolved_compose_sha256 = "{"7" * 64}"\n',
        encoding="utf-8",
    )
    activation = trusted / "pilot-activation.toml"
    activation.write_text(
        'schema = "my-pa.nas-pilot-activation.v1"\nstatus = "activated"\n'
        f'repository_commit = "{HEAD}"\nrepository_tree = "{TREE}"\n'
        f'activated_at = "{activated_at}"\nactivated_by = "operator"\n'
        f'canonical_origin = "{canonical_origin}"\n'
        f'acceptance_sha256 = "{_sha(acceptance)}"\n'
        f'nas_engine_id = "{ENGINE_ID}"\nnas_engine_name = "{ENGINE_NAME}"\n'
        f'compose_sha256 = "{_sha(COMPOSE)}"\n'
        f'runtime_contract_sha256 = "{_sha(ROOT / "ops/nas/runtime-contract.toml")}"\n'
        f'image_manifest_sha256 = "{_sha(manifest)}"\n'
        f'runtime_admission_sha256 = "{_sha(runtime_admission)}"\n'
        f'resolved_compose_sha256 = "{"7" * 64}"\n',
        encoding="utf-8",
    )
    for artifact, signature in (
        (acceptance, trusted / "nas-10-acceptance.sig"),
        (activation, trusted / "pilot-activation.sig"),
    ):
        subprocess.run(  # noqa: S603 - fixed OpenSSL with synthetic temporary key
            [
                "/usr/bin/openssl",
                "dgst",
                "-sha256",
                "-sign",
                str(private),
                "-out",
                str(signature),
                str(artifact),
            ],
            check=True,
        )
    for path in trusted.iterdir():
        path.chmod(0o400)
    return trusted


def test_smoke_is_exact_live_repository_image_and_compose(tmp_path: Path) -> None:
    gate = _module("lifecycle_gate")
    manifest = _manifest(tmp_path)
    assert (
        gate.verify(COMPOSE, OVERLAY, image_manifest_path=manifest, live=True, runner=_runner) == []
    )
    old = _manifest(tmp_path, commit="3" * 40)
    assert "repository_image_drift" in gate.verify(
        COMPOSE, OVERLAY, image_manifest_path=old, live=True, runner=_runner
    )
    arbitrary = tmp_path / "compose.yml"
    arbitrary.write_text(COMPOSE.read_text(encoding="utf-8"), encoding="utf-8")
    assert "runtime_contract_path" in gate.verify(
        arbitrary, OVERLAY, image_manifest_path=manifest, live=True, runner=_runner
    )


def test_pilot_requires_root_published_signed_exact_target_evidence(tmp_path: Path) -> None:
    gate = _module("lifecycle_gate")
    manifest = _manifest(tmp_path)
    trusted = _signed_evidence(tmp_path, manifest)
    verified_origin: list[str] = []
    assert (
        gate.verify(
            COMPOSE,
            OVERLAY,
            image_manifest_path=manifest,
            pilot=True,
            live=True,
            runner=_runner,
            trusted_root=trusted,
            trusted_owner_uid=os.getuid(),
            runtime_admission_path=tmp_path / "pilot-runtime-admission.toml",
            verified_origin=verified_origin,
        )
        == []
    )
    assert verified_origin == ["https://my-pa.tailnet.ts.net"]
    acceptance = trusted / "nas-10-acceptance.toml"
    acceptance.chmod(0o600)
    acceptance.write_text(
        acceptance.read_text(encoding="utf-8").replace('status = "pass"', 'status = "fail"'),
        encoding="utf-8",
    )
    acceptance.chmod(0o400)
    errors = gate.verify(
        COMPOSE,
        OVERLAY,
        image_manifest_path=manifest,
        pilot=True,
        live=True,
        runner=_runner,
        trusted_root=trusted,
        trusted_owner_uid=os.getuid(),
        runtime_admission_path=tmp_path / "pilot-runtime-admission.toml",
    )
    assert "nas_10_signature" in errors and "nas_10_acceptance" in errors


def test_lifecycle_cli_reserves_stdout_for_verified_origin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    gate = _module("lifecycle_gate")

    def accepted(
        *_args: object, verified_origin: list[str] | None = None, **_kwargs: object
    ) -> list[str]:
        assert verified_origin is not None
        verified_origin.append("https://my-pa.tailnet.ts.net")
        return []

    monkeypatch.setattr(gate, "verify", accepted)
    monkeypatch.setattr(
        "sys.argv",
        [
            "lifecycle_gate.py",
            str(COMPOSE),
            str(OVERLAY),
            "--image-manifest",
            "manifest.toml",
            "--pilot",
            "--live",
            "--print-verified-origin",
        ],
    )
    assert gate.main() == 0
    streams = capsys.readouterr()
    assert streams.out == "https://my-pa.tailnet.ts.net\n"
    assert streams.err == ""

    monkeypatch.setattr(gate, "verify", lambda *_args, **_kwargs: ["signed_evidence_refused"])
    assert gate.main() == 1
    streams = capsys.readouterr()
    assert streams.out == ""
    assert streams.err == "NAS lifecycle gate refused: signed_evidence_refused\n"


def test_lifecycle_shell_preserves_refusal_and_stops_before_runtime(
    tmp_path: Path,
) -> None:
    tools = tmp_path / "bin"
    tools.mkdir()
    calls = tmp_path / "calls"
    fake_python = tools / "python3"
    fake_python.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> {calls}\n"
        '[ "$1" = -c ] && exit 0\n'
        'case "$1" in\n'
        "  *lifecycle_gate.py) echo 'NAS lifecycle gate refused: planted refusal' >&2; exit 1 ;;\n"
        "  *) echo 'unexpected continuation' >&2; exit 99 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_docker = tools / "docker"
    fake_docker.write_text(
        f"#!/bin/sh\nprintf 'docker %s\\n' \"$*\" >> {calls}\nexit 99\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o700)
    fake_docker.chmod(0o700)
    result = subprocess.run(  # noqa: S603 - checked-in shell with synthetic PATH
        [str(ROOT / "ops/nas/status.sh")],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{tools}:/usr/bin:/bin",
            "MY_PA_NAS_COMPOSE_FILE": str(COMPOSE),
            "MY_PA_IMAGE_MANIFEST": str(tmp_path / "manifest.toml"),
            "MY_PA_LIFECYCLE_MODE": "pilot",
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "NAS lifecycle gate refused: planted refusal\n"
    recorded = calls.read_text(encoding="utf-8").splitlines()
    assert len(recorded) == 2 and "lifecycle_gate.py" in recorded[1]


def test_origin_parser_and_evidence_chronology_fail_closed(tmp_path: Path) -> None:
    gate = _module("lifecycle_gate")
    assert gate._private_tailnet_origin("https://host.ts.net")
    for hostile in (
        "https://attacker.example/path.ts.net",
        "https://bad_label.ts.net",
        "https://-bad.ts.net",
        "https://bad-.ts.net",
        "https://bad..ts.net",
        "https://user@host.ts.net",
        "https://host.ts.net/path",
        "https://host.ts.net?next=.ts.net",
        "https://host.ts.net:8443",
        "http://host.ts.net",
    ):
        assert not gate._private_tailnet_origin(hostile)
    manifest = _manifest(tmp_path)
    trusted = _signed_evidence(tmp_path, manifest, activated_at="2026-08-13T11:59:59Z")
    errors = gate.verify(
        COMPOSE,
        OVERLAY,
        image_manifest_path=manifest,
        pilot=True,
        live=True,
        runner=_runner,
        trusted_root=trusted,
        trusted_owner_uid=os.getuid(),
        runtime_admission_path=tmp_path / "pilot-runtime-admission.toml",
    )
    assert "operator_activation" in errors

    weak_private = tmp_path / "weak-private.pem"
    weak_public = tmp_path / "weak-public.pem"
    subprocess.run(  # noqa: S603 - fixed OpenSSL with synthetic temporary key
        ["/usr/bin/openssl", "genrsa", "-out", str(weak_private), "2048"], check=True
    )
    with weak_public.open("wb") as output:
        subprocess.run(  # noqa: S603 - fixed OpenSSL with synthetic temporary key
            ["/usr/bin/openssl", "rsa", "-in", str(weak_private), "-pubout"],
            check=True,
            stdout=output,
        )
    assert not gate._strong_rsa_public_key(weak_public)


def test_http_diagnostics_prove_authenticated_bff_and_gateway_only_route(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    probe = _module("diagnostic_http_probe")
    credential = tmp_path / "session-cookie"
    secret = "synthetic-diagnostic-session-token.123456789"  # noqa: S105
    credential.write_text(secret, encoding="ascii")
    credential.chmod(0o400)
    requests: list[object] = []

    class Response:
        def __init__(self, status: int, headers: dict[str, str], body: bytes) -> None:
            self.status = status
            self.headers = headers
            self.body = body

        def read(self, amount: int = -1) -> bytes:
            return self.body[:amount]

        def close(self) -> None:
            return None

    def opener(request: object, *, timeout: int) -> Response:
        assert timeout == 10
        requests.append(request)
        if str(request.full_url).endswith("/api/system"):
            assert request.headers["Cookie"] == f"mypa_session={secret}"
            return Response(
                200,
                {"Content-Type": "application/json"},
                json.dumps(
                    {
                        "dataProvider": "backend",
                        "backend": {
                            "manifest": {},
                            "readiness": {},
                            "workerPlanes": {},
                        },
                    }
                ).encode(),
            )
        return Response(405, {"X-My-PA-Route": "gateway-only"}, b"method not allowed")

    assert (
        probe.verify(
            "https://my-pa.tailnet.ts.net/api/system",
            credential,
            "my-pa.tailnet.ts.net",
            "https://my-pa.tailnet.ts.net",
            owner_uid=os.getuid(),
            opener=opener,
        )
        == []
    )
    assert len(requests) == 2
    assert secret not in capsys.readouterr().out

    def nextjs_fallthrough(request: object, *, timeout: int) -> Response:
        response = opener(request, timeout=timeout)
        if str(request.full_url).endswith("/remote/v1/capture.create"):
            return Response(405, {}, b"")
        return response

    assert "remote_capture_route_probe" in probe.verify(
        "https://my-pa.tailnet.ts.net/api/system",
        credential,
        "my-pa.tailnet.ts.net",
        "https://my-pa.tailnet.ts.net",
        owner_uid=os.getuid(),
        opener=nextjs_fallthrough,
    )
    for endpoint, host, origin in (
        (
            "https://attacker.example/api/system",
            "attacker.example",
            "https://attacker.example",
        ),
        (
            "https://other.ts.net/api/system",
            "other.ts.net",
            "https://my-pa.tailnet.ts.net",
        ),
        (
            "https://my-pa.tailnet.ts.net/api/system",
            "other.ts.net",
            "https://my-pa.tailnet.ts.net",
        ),
    ):
        assert probe.verify(endpoint, credential, host, origin, owner_uid=os.getuid())


def test_diagnostic_transport_never_follows_redirect_or_forwards_cookie() -> None:
    probe = _module("diagnostic_http_probe")
    target_requests: list[tuple[str, str | None]] = []

    class TargetHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            target_requests.append((self.path, self.headers.get("Cookie")))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            return None

    target = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{target.server_port}{self.path}")
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            return None

    redirect = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    threads = [threading.Thread(target=server.serve_forever) for server in (target, redirect)]
    for thread in threads:
        thread.start()
    try:
        for path in ("/api/system", "/remote/v1/capture.create"):
            request = probe.Request(
                f"http://127.0.0.1:{redirect.server_port}{path}",
                headers={"Cookie": "mypa_session=must-not-leave-origin"},
            )
            result = probe._request(request, probe._open_no_redirect)
            assert result is not None and result[0] == 302
        assert target_requests == []
    finally:
        redirect.shutdown()
        target.shutdown()
        for thread in threads:
            thread.join()
        redirect.server_close()
        target.server_close()


def test_diagnostics_refuse_without_configured_authenticated_probe() -> None:
    result = subprocess.run(  # noqa: S603 - checked-in fail-closed shell contract
        [str(ROOT / "ops/nas/diagnostics.sh")],
        cwd=ROOT,
        env={
            **os.environ,
            "MY_PA_RUNTIME_SERVICES": "services.toml",
            "MY_PA_NAS_ROOT": "/srv/my-pa",
            "MY_PA_MIN_FREE_KIB": "1",
            "MY_PA_BACKUP_RECEIPT": "receipt.toml",
            "MY_PA_TAILNET_HOST": "my-pa.tailnet.ts.net",
            "MY_PA_WORKER_MAX_AGE_SECONDS": "60",
            "MY_PA_APPLE_MAX_AGE_SECONDS": "60",
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "MY_PA_DIAGNOSTIC_BFF_URL" in result.stderr


def test_resolved_and_running_images_close_caller_controlled_env(tmp_path: Path) -> None:
    gate = _module("runtime_identity_gate")
    manifest, admission, images, image_ids, rendered, _pilot_rendered = _runtime_fixture(tmp_path)

    def runner(command: list[str]) -> str:
        if command[-3:] == ["config", "--format", "json"]:
            return rendered
        if command[-2:] == ["config", "--images"]:
            return "\n".join(images.values())
        if command[-3:] == ["config", "--hash", "*"]:
            return "\n".join(f"{name} hash-{name}" for name in images)
        if command[:2] == ["docker", "info"]:
            return json.dumps({"ID": ENGINE_ID, "Name": ENGINE_NAME})
        if "ps" in command:
            return "container-" + command[-1]
        if command[:2] == ["docker", "inspect"]:
            service = command[-1].removeprefix("container-")
            return json.dumps(
                [
                    {
                        "Image": image_ids[service],
                        "Config": {
                            "Labels": {
                                "com.docker.compose.project": "my-pa-nas-contract",
                                "com.docker.compose.service": service,
                                "com.docker.compose.config-hash": f"hash-{service}",
                            }
                        },
                    }
                ]
            )
        raise AssertionError(command)

    assert (
        gate.verify(
            COMPOSE,
            manifest,
            admission_path=admission,
            owner_uid=os.getuid(),
            running=True,
            runner=runner,
        )
        == []
    )

    mismatched = json.loads(rendered)
    mismatched["services"]["gateway"]["image"] = "sha256:" + "e" * 64

    def bad_env(command: list[str]) -> str:
        if command[-3:] == ["config", "--format", "json"]:
            return json.dumps(mismatched)
        return runner(command)

    errors = gate.verify(
        COMPOSE,
        manifest,
        admission_path=admission,
        owner_uid=os.getuid(),
        runner=bad_env,
    )
    assert {"runtime_render_drift", "runtime_render_image_binding"} <= set(errors)

    def wrong_running(command: list[str]) -> str:
        value = runner(command)
        if command[:2] == ["docker", "inspect"] and command[-1] == "container-gateway":
            document = json.loads(value)
            document[0]["Image"] = "sha256:" + "f" * 64
            return json.dumps(document)
        if command[:2] == ["docker", "inspect"] and command[-1] == "container-web":
            document = json.loads(value)
            document[0]["Config"]["Labels"]["com.docker.compose.config-hash"] = "stale"
            return json.dumps(document)
        return value

    running_errors = gate.verify(
        COMPOSE,
        manifest,
        admission_path=admission,
        owner_uid=os.getuid(),
        running=True,
        runner=wrong_running,
    )
    assert {"gateway_running_image", "web_running_config"} <= set(running_errors)


def test_pilot_identity_binds_ordered_overlay_and_distinct_resolved_config(
    tmp_path: Path,
) -> None:
    gate = _module("runtime_identity_gate")
    manifest, admission, images, image_ids, smoke_rendered, pilot_rendered = _runtime_fixture(
        tmp_path
    )

    def runner(command: list[str]) -> str:
        if command[:2] == ["docker", "info"]:
            return json.dumps({"ID": ENGINE_ID, "Name": ENGINE_NAME})
        if command[:2] == ["docker", "inspect"]:
            service = command[-1].removeprefix("pilot-container-")
            return json.dumps(
                [
                    {
                        "Image": image_ids[service],
                        "Config": {
                            "Labels": {
                                "com.docker.compose.project": "my-pa-nas-contract",
                                "com.docker.compose.service": service,
                                "com.docker.compose.config-hash": f"pilot-hash-{service}",
                            }
                        },
                    }
                ]
            )
        overlay_index = command.index("--file", 4)
        assert command[2:6] == ["--file", str(COMPOSE), "--file", str(OVERLAY)]
        assert overlay_index == 4
        if command[-3:] == ["config", "--format", "json"]:
            return pilot_rendered
        if command[-2:] == ["config", "--images"]:
            return "\n".join(images.values())
        if command[-3:] == ["config", "--hash", "*"]:
            return "\n".join(f"{name} pilot-hash-{name}" for name in images)
        if "ps" in command:
            return "pilot-container-" + command[-1]
        raise AssertionError(command)

    assert (
        gate.verify(
            COMPOSE,
            manifest,
            pilot_overlay_path=OVERLAY,
            admission_path=admission,
            owner_uid=os.getuid(),
            running=True,
            runner=runner,
        )
        == []
    )

    def smoke_render_for_pilot(command: list[str]) -> str:
        if command[-3:] == ["config", "--format", "json"]:
            return smoke_rendered
        return runner(command)

    assert "runtime_render_drift" in gate.verify(
        COMPOSE,
        manifest,
        pilot_overlay_path=OVERLAY,
        admission_path=admission,
        owner_uid=os.getuid(),
        runner=smoke_render_for_pilot,
    )


def test_pilot_lifecycle_dispatches_identity_and_compose_with_same_overlay(
    tmp_path: Path,
) -> None:
    tools = tmp_path / "bin"
    tools.mkdir()
    python_log = tmp_path / "python-calls"
    docker_log = tmp_path / "docker-calls"
    fake_python = tools / "python3"
    fake_python.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {python_log}\nexit 0\n",
        encoding="utf-8",
    )
    fake_docker = tools / "docker"
    fake_docker.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {docker_log}\nexit 0\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o700)
    fake_docker.chmod(0o700)
    result = subprocess.run(  # noqa: S603 - checked-in script with synthetic PATH
        [str(ROOT / "ops/nas/status.sh")],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{tools}:/usr/bin:/bin",
            "MY_PA_NAS_COMPOSE_FILE": str(COMPOSE),
            "MY_PA_IMAGE_MANIFEST": str(tmp_path / "manifest.toml"),
            "MY_PA_LIFECYCLE_MODE": "pilot",
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    identity_calls = [
        line
        for line in python_log.read_text(encoding="utf-8").splitlines()
        if "runtime_identity_gate.py" in line
    ]
    assert len(identity_calls) == 2
    assert all(f"--pilot-overlay {OVERLAY}" in line for line in identity_calls)
    assert (
        f"compose --file {COMPOSE} --file {OVERLAY} --profile nas-01-contract-only ps"
        in docker_log.read_text(encoding="utf-8")
    )


def test_incomplete_image_manifest_is_refused(tmp_path: Path) -> None:
    gate = _module("runtime_identity_gate")
    incomplete = _manifest(tmp_path)
    admission = tmp_path / "runtime-admission.toml"
    admission.write_text("", encoding="utf-8")
    admission.chmod(0o400)
    errors = gate.verify(COMPOSE, incomplete, admission_path=admission, owner_uid=os.getuid())
    assert any(error.startswith("image_manifest_") for error in errors)


@pytest.mark.parametrize(
    ("source", "old", "new", "violation"),
    [
        (COMPOSE, 'restart: "no"', "restart: always", "smoke_restart_policy"),
        (OVERLAY, "restart: unless-stopped", "restart: always", "pilot_overlay_scope"),
        (
            OVERLAY,
            "  proxy:\n",
            "  extra:\n    restart: unless-stopped\n  proxy:\n",
            "pilot_service_set",
        ),
    ],
)
def test_restart_policy_planted_violations_fail(
    tmp_path: Path, source: Path, old: str, new: str, violation: str
) -> None:
    mutated = tmp_path / source.name
    mutated.write_text(source.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")
    compose = mutated if source == COMPOSE else COMPOSE
    overlay = mutated if source == OVERLAY else OVERLAY
    assert violation in _module("lifecycle_gate").verify(
        compose, overlay, image_manifest_path=_manifest(tmp_path)
    )


@pytest.mark.parametrize(
    "mode", ["firewall_missing", "up_nonzero", "ps_failure", "too_few", "stop_failure_partial"]
)
def test_failed_compose_start_always_stops_and_verifies_partial_stack(
    tmp_path: Path, mode: str
) -> None:
    tools = tmp_path / "bin"
    tools.mkdir()
    log = tmp_path / "calls"
    counter = tmp_path / "counter"
    fake_python = tools / "python3"
    fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_docker = tools / "docker"
    fake_docker.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> {log}\n"
        'case " $* " in\n'
        "  *' network inspect --format '*' my-pa-nas-contract_data-plane '*) "
        "echo 'd4d93b2566666666666666666666666666666666666666666666666666666666"
        "|my-pa-nas-contract_data-plane|bridge|local|true|my-pa-nas-contract"
        "|data-plane|172.22.0.0/16'; exit 0 ;;\n"
        "  *' up '*) [ \"$MY_TEST_MODE\" = up_nonzero ] || "
        '[ "$MY_TEST_MODE" = stop_failure_partial ] || exit 0; exit 1 ;;\n'
        "  *' stop --timeout 60 '*) "
        '[ "$MY_TEST_MODE" = stop_failure_partial ] && exit 1; exit 0 ;;\n'
        "  *' ps --status running -q '*)\n"
        f"    n=0; [ ! -f {counter} ] || n=$(cat {counter}); n=$((n+1)); echo $n > {counter}\n"
        '    [ "$MY_TEST_MODE" = ps_failure ] && [ $n -eq 1 ] && exit 1\n'
        '    [ "$MY_TEST_MODE" = too_few ] && [ $n -eq 1 ] && '
        "{ printf 'one\\ntwo\\n'; exit 0; }\n"
        '    [ "$MY_TEST_MODE" = stop_failure_partial ] && echo still-running\n'
        "    exit 0 ;;\n"
        "esac\nexit 0\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o700)
    fake_docker.chmod(0o700)
    fake_ip = tools / "ip"
    fake_ip.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_iptables = tools / "iptables"
    fake_iptables.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        "  '-S') printf '%s\\n' '-A FORWARD -j FORWARD_FIREWALL' "
        "'-A FORWARD -j DEFAULT_FORWARD' ;;\n"
        "  '-S FORWARD_FIREWALL') "
        '[ "$MY_TEST_MODE" = firewall_missing ] || '
        "printf '%s\\n' '-A FORWARD_FIREWALL -s 172.22.0.0/16 -d 172.22.0.0/16 "
        "-i docker-d4d93b25 -o docker-d4d93b25 -j RETURN';;\n"
        "  '-C DEFAULT_FORWARD -i docker-d4d93b25 -o docker-d4d93b25 -j ACCEPT') exit 0 ;;\n"
        "  '-C FORWARD_FIREWALL -i docker-d4d93b25 -o docker-d4d93b25 "
        "-s 172.22.0.0/16 -d 172.22.0.0/16 -j RETURN') exit 0 ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_ip.chmod(0o700)
    fake_iptables.chmod(0o700)
    result = subprocess.run(  # noqa: S603 - fixed checked-in script with synthetic PATH
        [str(ROOT / "ops/nas/start.sh"), str(tmp_path / "manifest"), str(tmp_path)],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{tools}:/usr/bin:/bin",
            "MY_PA_NAS_COMPOSE_FILE": str(COMPOSE),
            "MY_PA_NAS_IP": str(fake_ip),
            "MY_PA_NAS_IPTABLES": str(fake_iptables),
            "MY_TEST_MODE": mode,
        },
        check=False,
        capture_output=True,
        text=True,
    )
    calls = log.read_text(encoding="utf-8")
    assert result.returncode == 1
    if mode == "firewall_missing":
        assert " up --detach --no-build --pull never" not in calls
        assert " stop --timeout 60" not in calls
        assert " ps --status running -q" not in calls
        return
    assert " up --detach --no-build --pull never" in calls
    assert " stop --timeout 60" in calls
    assert " ps --status running -q" in calls


def _run_emergency_shell(
    tmp_path: Path, mode: str
) -> tuple[subprocess.CompletedProcess[str], str, str]:
    compose = tmp_path / "compose.yml"
    compose.write_text(COMPOSE.read_text(encoding="utf-8"), encoding="utf-8")
    compose.chmod(0o400)
    tools = tmp_path / "bin"
    tools.mkdir()
    calls = tmp_path / "calls"
    state = tmp_path / "running"
    initial = {
        "complete": "c1\nc2\nc3\nc4\nc5\nc6\n",
        "partial": "c1\nc2\n",
        "replacement": "c1\n",
        "unknown": "c1\nu1\n",
        "oneoff": "c1\no1\n",
        "duplicate": "c1\nd1\n",
        "stop-failure": "c1\n",
    }[mode]
    state.write_text(initial, encoding="utf-8")
    replacement_created = tmp_path / "replacement-created"
    fake_stat = tools / "stat"
    fake_stat.write_text("#!/bin/sh\nprintf '0:400:1\\n'\n", encoding="utf-8")
    fake_docker = tools / "docker"
    fake_docker.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> "{calls}"\n'
        'case " $* " in\n'
        "  *' config --no-interpolate --services '*) "
        "printf 'worker-enrollment\\nweb\\npostgres\\nproxy\\ngateway\\nworker-capture\\n';;\n"
        "  *' ps --filter label=com.docker.compose.project=my-pa-nas-contract "
        f'--filter status=running --format {{{{.ID}}}} \'*) cat "{state}";;\n'
        "  *' inspect --format '*'.Config.Labels'*' c1 '*) "
        "printf '%064d|my-pa-nas-contract|gateway|False\\n' 1;;\n"
        "  *' inspect --format '*'.Config.Labels'*' c2 '*) "
        "printf '%064d|my-pa-nas-contract|postgres|False\\n' 2;;\n"
        "  *' inspect --format '*'.Config.Labels'*' c3 '*) "
        "printf '%064d|my-pa-nas-contract|proxy|False\\n' 3;;\n"
        "  *' inspect --format '*'.Config.Labels'*' c4 '*) "
        "printf '%064d|my-pa-nas-contract|web|False\\n' 4;;\n"
        "  *' inspect --format '*'.Config.Labels'*' c5 '*) "
        "printf '%064d|my-pa-nas-contract|worker-capture|False\\n' 5;;\n"
        "  *' inspect --format '*'.Config.Labels'*' c6 '*) "
        "printf '%064d|my-pa-nas-contract|worker-enrollment|False\\n' 6;;\n"
        "  *' inspect --format '*'.Config.Labels'*' c7 '*) "
        "printf '%064d|my-pa-nas-contract|gateway|False\\n' 7;;\n"
        "  *' inspect --format '*'.Config.Labels'*' u1 '*) "
        "printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        "|my-pa-nas-contract|rogue|False\\n';;\n"
        "  *' inspect --format '*'.Config.Labels'*' o1 '*) "
        "printf 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        "|my-pa-nas-contract|gateway|True\\n';;\n"
        "  *' inspect --format '*'.Config.Labels'*' d1 '*) "
        "printf 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
        "|my-pa-nas-contract|gateway|False\\n';;\n"
        "  *' stop --time 10 '*)\n"
        "    for id do :; done\n"
        '    case "$id" in\n'
        "      0000000000000000000000000000000000000000000000000000000000000001) short=c1;;\n"
        "      0000000000000000000000000000000000000000000000000000000000000002) short=c2;;\n"
        "      0000000000000000000000000000000000000000000000000000000000000003) short=c3;;\n"
        "      0000000000000000000000000000000000000000000000000000000000000004) short=c4;;\n"
        "      0000000000000000000000000000000000000000000000000000000000000005) short=c5;;\n"
        "      0000000000000000000000000000000000000000000000000000000000000006) short=c6;;\n"
        "      0000000000000000000000000000000000000000000000000000000000000007) short=c7;;\n"
        "      cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc) short=d1;;\n"
        "      *) exit 1;;\n"
        "    esac\n"
        f'    [ "{mode}" != stop-failure ] || exit 1\n'
        f'    grep -Fvx "$short" "{state}" > "{state}.next" || true\n'
        f'    mv "{state}.next" "{state}"\n'
        f'    if [ "{mode}" = replacement ] && [ "$short" = c1 ] && '
        f'[ ! -e "{replacement_created}" ]; then echo c7 >> "{state}"; '
        f': > "{replacement_created}"; fi\n'
        "    exit 0;;\n"
        "  *) exit 1;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_stat.chmod(0o700)
    fake_docker.chmod(0o700)
    script = tmp_path / "emergency-shutdown.sh"
    script.write_text(
        (ROOT / "ops/nas/emergency-shutdown.sh")
        .read_text(encoding="utf-8")
        .replace("/etc/my-pa/compose.yml", str(compose)),
        encoding="utf-8",
    )
    script.chmod(0o700)
    result = subprocess.run(  # noqa: S603 - checked-in shell with synthetic Docker
        [str(script)],
        env={
            "PATH": f"{tools}:/usr/bin:/bin",
            "MY_PA_NAS_DOCKER": str(fake_docker),
            "MY_PA_NAS_OPERATOR_ADMISSION": str(tmp_path / "absent-admission"),
        },
        check=False,
        capture_output=True,
        text=True,
    )
    return result, calls.read_text(encoding="utf-8"), state.read_text(encoding="utf-8")


def test_emergency_stop_ignores_broken_control_evidence(tmp_path: Path) -> None:
    result, invoked, state = _run_emergency_shell(tmp_path, "complete")
    assert result.returncode == 0, result.stderr
    assert "config --no-interpolate --services" in invoked
    assert "ps --filter label=com.docker.compose.project=my-pa-nas-contract" in invoked
    assert invoked.count("stop --time 10") == 6
    assert "compose --project-name my-pa-nas-contract" in invoked
    assert "compose --project-name my-pa-nas-contract --file" in invoked
    assert "compose --project-name my-pa-nas-contract" not in "\n".join(
        line for line in invoked.splitlines() if " stop " in line or " ps " in line
    )
    assert "pilot-evidence" not in invoked
    assert "operator-runtime" not in invoked
    assert state == ""


@pytest.mark.parametrize("mode", ["partial", "replacement"])
def test_emergency_stop_contains_partial_and_concurrently_replaced_stacks(
    tmp_path: Path, mode: str
) -> None:
    result, invoked, state = _run_emergency_shell(tmp_path, mode)
    assert result.returncode == 0, result.stderr
    assert state == ""
    expected_stops = 2
    assert invoked.count("stop --time 10") == expected_stops
    assert invoked.count("--filter status=running") >= 2


@pytest.mark.parametrize("mode", ["unknown", "oneoff", "stop-failure"])
def test_emergency_stop_never_claims_success_with_uncontained_project_runtime(
    tmp_path: Path, mode: str
) -> None:
    result, invoked, state = _run_emergency_shell(tmp_path, mode)
    assert result.returncode == 1
    assert "NAS runtime stopped" not in result.stdout
    assert state
    assert "--filter status=running" in invoked


def test_emergency_stop_contains_duplicates_but_reports_identity_anomaly(tmp_path: Path) -> None:
    result, invoked, state = _run_emergency_shell(tmp_path, "duplicate")
    assert result.returncode == 1
    assert "unexpected project identity" in result.stderr
    assert "NAS runtime stopped" not in result.stdout
    assert invoked.count("stop --time 10") == 2
    assert state == ""


def test_health_is_readiness_and_diagnostics_cover_operational_signals() -> None:
    health = (ROOT / "ops/nas/health.sh").read_text(encoding="utf-8")
    diagnostics = (ROOT / "ops/nas/diagnostics.sh").read_text(encoding="utf-8")
    assert "not full operational health" in health and "diagnostics.sh" in health
    for marker in (
        "worker_heartbeats",
        "native_admission_authorities",
        "http://web:3000/",
        "http://proxy:8080/",
        "MY_PA_DIAGNOSTIC_BFF_URL",
        "MY_PA_DIAGNOSTIC_SESSION_COOKIE_FILE",
        "diagnostic_http_probe.py",
        "runtime_gate.py",
        "df -Pk",
        "verify-backup-receipt.sh",
    ):
        assert marker in diagnostics
