#!/bin/sh
set -eu

if [ "$#" -ne 4 ]; then
  echo "usage: $0 OPERATOR_CANDIDATE OPERATOR_ARCHIVE OPERATOR_METADATA OUTPUT_ADMISSION" >&2
  exit 64
fi

: "${MY_PA_NAS_DOCKER:=/usr/local/bin/docker}"
candidate=$1
archive=$2
metadata=$3
output=$4
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(git -C "$script_dir" rev-parse --show-toplevel)

case "$MY_PA_NAS_DOCKER" in
  /*) NAS_DOCKER_BIN=$MY_PA_NAS_DOCKER ;;
  *) NAS_DOCKER_BIN=$(command -v "$MY_PA_NAS_DOCKER") ;;
esac
[ -x "$NAS_DOCKER_BIN" ] || { echo "Docker executable is unavailable" >&2; exit 1; }
[ -f "$candidate" ] && [ -f "$archive" ] && [ -f "$metadata" ] || {
  echo "operator candidate, archive, and metadata must exist" >&2
  exit 64
}
[ ! -e "$output" ] || { echo "operator admission output already exists" >&2; exit 1; }

expected_archive=$(sed -n 's/^archive_sha256 = "\([0-9a-f][0-9a-f]*\)"$/\1/p' "$candidate")
expected_image=$(sed -n 's/^docker_image_id = "\(sha256:[0-9a-f][0-9a-f]*\)"$/\1/p' "$candidate")
case "$expected_archive" in ????????*) ;; *) echo "operator archive checksum is invalid" >&2; exit 1;; esac
case "$expected_image" in sha256:????????*) ;; *) echo "operator image identity is invalid" >&2; exit 1;; esac
[ "${#expected_archive}" -eq 64 ] && [ "${#expected_image}" -eq 71 ] || {
  echo "operator candidate identities have invalid lengths" >&2
  exit 1
}

if command -v sha256sum >/dev/null 2>&1; then
  actual_archive=$(sha256sum "$archive" | awk '{print $1}')
elif command -v shasum >/dev/null 2>&1; then
  actual_archive=$(shasum -a 256 "$archive" | awk '{print $1}')
else
  echo "operator bootstrap requires sha256sum or shasum" >&2
  exit 1
fi
[ "$actual_archive" = "$expected_archive" ] || {
  echo "operator archive checksum mismatch" >&2
  exit 1
}

"$NAS_DOCKER_BIN" load --input "$archive" >/dev/null
loaded=$({ "$NAS_DOCKER_BIN" image inspect --format '{{.Id}}|{{.Os}}|{{.Architecture}}' "$expected_image"; } 2>/dev/null)
[ "$loaded" = "$expected_image|linux|amd64" ] || {
  echo "loaded operator image identity or platform mismatch" >&2
  exit 1
}

docker_host_binary=$NAS_DOCKER_BIN
if [ -L "$docker_host_binary" ]; then
  link=$(readlink "$docker_host_binary")
  case "$link" in
    /*) docker_host_binary=$link ;;
    *) docker_host_binary=$(dirname "$docker_host_binary")/$link ;;
  esac
fi
[ -x "$docker_host_binary" ] || { echo "resolved Docker binary is unavailable" >&2; exit 1; }

"$NAS_DOCKER_BIN" run --rm \
  --network none \
  --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=16m \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --user 0:0 \
  --volume /var/run/docker.sock:/var/run/docker.sock \
  --volume "$docker_host_binary:/usr/local/bin/docker:ro" \
  --volume "$repo_root:$repo_root:ro" \
  --volume "$candidate:$candidate:ro" \
  --volume "$archive:$archive:ro" \
  --volume "$metadata:$metadata:ro" \
  --volume "$(dirname "$output"):$(dirname "$output")" \
  --env MY_PA_NAS_DOCKER=/usr/local/bin/docker \
  --workdir "$repo_root" \
  --entrypoint python \
  "$expected_image" \
  "$script_dir/admit-operator-runtime.py" "$candidate" "$archive" "$metadata" "$output"
