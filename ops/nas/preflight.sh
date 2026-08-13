#!/bin/sh
set -eu
if [ "$#" -ne 2 ]; then
  echo "usage: $0 IMAGE_MANIFEST ARCHIVE_DIRECTORY" >&2
  exit 64
fi
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python3 "$script_dir/image_gate.py" "$1" --archive-dir "$2" --live
MY_PA_IMAGE_MANIFEST=$1
export MY_PA_IMAGE_MANIFEST
. "$script_dir/lifecycle-common.sh"
nas_compose config --quiet
echo "NAS lifecycle preflight passed for $MY_PA_LIFECYCLE_MODE mode"
