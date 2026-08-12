#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
  echo "usage: $0 IMAGE_MANIFEST ARCHIVE_DIRECTORY" >&2
  exit 64
fi

echo "NAS-02 load is an operator/device gate and is deliberately disabled." >&2
echo "After live linux/amd64 NAS access is available, load all three manifest-bound archives, then run start.sh." >&2
exit 1
