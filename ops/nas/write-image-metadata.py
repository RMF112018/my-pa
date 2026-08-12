#!/usr/bin/env python3
"""Write BuildKit-compatible identity metadata for an exact pulled image."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: write-image-metadata.py IMAGE_REFERENCE OUTPUT", file=sys.stderr)
        return 64
    reference, output = sys.argv[1], Path(sys.argv[2])
    result = subprocess.run(  # noqa: S603 - operator-supplied exact reference
        ["/usr/bin/env", "docker", "image", "inspect", reference],
        check=True,
        capture_output=True,
        text=True,
    )
    inspected = json.loads(result.stdout)[0]
    manifest_digest = reference.rpartition("@")[2]
    output.write_text(
        json.dumps(
            {
                "containerimage.digest": manifest_digest,
                "containerimage.config.digest": inspected["Id"],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
