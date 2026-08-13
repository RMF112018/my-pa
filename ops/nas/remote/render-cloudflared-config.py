#!/usr/bin/env python3
"""Render non-secret, exact-route cloudflared configuration."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from uuid import UUID


def render(template: Path, output: Path, *, tunnel_id: str, hostname: str) -> None:
    UUID(tunnel_id)
    if not re.fullmatch(
        r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}",
        hostname,
    ) or hostname.endswith(".invalid"):
        raise ValueError("hostname must be a production FQDN")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    source = template.read_text(encoding="utf-8")
    if source.count("__TUNNEL_ID__") != 1 or source.count("__MCP_HOSTNAME__") != 6:
        raise ValueError("unexpected template placeholders")
    rendered = source.replace("__TUNNEL_ID__", tunnel_id).replace("__MCP_HOSTNAME__", hostname)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    output.chmod(0o640)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--template",
        type=Path,
        default=Path(__file__).with_name("cloudflared-config.example.yml"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tunnel-id", required=True)
    parser.add_argument("--hostname", required=True)
    args = parser.parse_args()
    render(args.template, args.output, tunnel_id=args.tunnel_id, hostname=args.hostname)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
