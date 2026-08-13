#!/usr/bin/env python3
"""Write BuildKit-compatible metadata from an exact Docker archive."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from archive_image import inspect_archive


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: write-image-metadata.py IMAGE_REFERENCE ARCHIVE OUTPUT", file=sys.stderr)
        return 64
    reference, archive, output = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    manifest_digest = reference.rpartition("@")[2]
    image = inspect_archive(archive)
    output.write_text(
        json.dumps(
            {
                "containerimage.digest": manifest_digest,
                "containerimage.config.digest": image.config_digest,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
