"""Operator control plane for governed GSQS live-B0 preflight and execute."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from my_pa.application.goodnotes_gsqs_hw_corpus import load_public_catalog
from my_pa.application.goodnotes_gsqs_live_b0 import (
    PreflightReport,
    UnboundIncumbentAdapter,
    catalog_path,
    inspect_repository_identity,
    load_execution_authorization,
    preflight,
    prompt_config_identity,
    prompt_path,
    repo_root,
    write_public_evidence,
)

EXIT_OK = 0
EXIT_REFUSED = 1


def _preflight(args: argparse.Namespace) -> int:
    root = Path(args.repository_root) if args.repository_root else repo_root()
    authorization = (
        load_execution_authorization(Path(args.authorization)) if args.authorization else None
    )
    report = preflight(
        root=root,
        catalog=load_public_catalog(catalog_path(root)),
        repository=inspect_repository_identity(root),
        authorization=authorization,
    )
    print(json.dumps(_report_dict(report), indent=2, sort_keys=True))
    if args.evidence_dir:
        write_public_evidence(Path(args.evidence_dir), report=report)
    return EXIT_OK if report.go else EXIT_REFUSED


def _execute(args: argparse.Namespace) -> int:
    if args.authorization is None:
        raise ValueError("execute requires --authorization")
    root = Path(args.repository_root) if args.repository_root else repo_root()
    authorization = load_execution_authorization(Path(args.authorization))
    if args.model_identity != authorization.model_identity:
        raise ValueError("model identity mismatch")
    prompt_id = prompt_config_identity(root)
    if not _prompt_matches(root, args.prompt_config, prompt_id):
        raise ValueError("prompt identity mismatch")
    if args.repetitions != authorization.repetitions:
        raise ValueError("wrong repetition scope")
    report = preflight(
        root=root,
        catalog=load_public_catalog(catalog_path(root)),
        repository=inspect_repository_identity(root),
        authorization=authorization,
    )
    print(json.dumps(_report_dict(report), indent=2, sort_keys=True))
    if not report.go:
        return EXIT_REFUSED
    _ = UnboundIncumbentAdapter
    raise ValueError("incumbent transport is not bound; refusing disclosure")


def _prompt_matches(root: Path, supplied: str, prompt_id: str) -> bool:
    if supplied in {prompt_id, str(prompt_path(root)), str(prompt_path(root).resolve())}:
        return True
    candidate = Path(supplied)
    return candidate.is_file() and sha256(candidate.read_bytes()).hexdigest() == prompt_id


def _report_dict(report: PreflightReport) -> dict[str, object]:
    payload: dict[str, object] = asdict(report)
    payload["state"] = report.state.value
    payload["verdict"] = "GO" if report.go else "NO-GO"
    payload["disclosure_would_occur"] = False
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gsqs-b0", allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--repository-root", default=None)
    shared.add_argument("--authorization", default=None)
    shared.add_argument("--evidence-dir", default=None)
    preflight_cmd = commands.add_parser("preflight", parents=[shared])
    preflight_cmd.set_defaults(handler=_preflight)
    execute = commands.add_parser("execute", parents=[shared])
    execute.add_argument("--model-identity", required=True)
    execute.add_argument("--prompt-config", required=True)
    execute.add_argument("--repetitions", type=int, required=True)
    execute.set_defaults(handler=_execute)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return int(args.handler(args))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
