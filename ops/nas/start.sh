#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
  echo "usage: $0 IMAGE_MANIFEST ARCHIVE_DIRECTORY" >&2
  exit 64
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python3 "$script_dir/image_gate.py" "$1" --archive-dir "$2" --live

echo "NAS-02 image evidence passed, but start remains disabled until NAS-04 implements the gateway container bind." >&2
exit 1

# NAS-04+ may replace the refusal only after image_gate.py passes, then invoke:
# docker compose --file ops/nas/compose.yml up --detach --no-build --pull never
