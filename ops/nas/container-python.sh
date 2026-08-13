#!/bin/sh
set -eu

: "${MY_PA_NAS_DOCKER:=/usr/local/bin/docker}"
: "${MY_PA_NAS_OPERATOR_ADMISSION:=/etc/my-pa/operator-runtime.toml}"
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(git -C "$script_dir" rev-parse --show-toplevel)

case "$MY_PA_NAS_DOCKER" in
  /*) docker_bin=$MY_PA_NAS_DOCKER ;;
  *) docker_bin=$(command -v "$MY_PA_NAS_DOCKER") ;;
esac
[ -x "$docker_bin" ] || { echo "Docker executable is unavailable" >&2; exit 1; }
[ -f "$MY_PA_NAS_OPERATOR_ADMISSION" ] || { echo "operator admission is unavailable" >&2; exit 1; }
[ "$(stat -c '%u:%a:%h' "$MY_PA_NAS_OPERATOR_ADMISSION")" = "0:400:1" ] || {
  echo "operator admission must be root-owned mode 0400 with one link" >&2
  exit 1
}
image_id=$(sed -n 's/^operator_image_id = "\(sha256:[0-9a-f][0-9a-f]*\)"$/\1/p' "$MY_PA_NAS_OPERATOR_ADMISSION")
[ "${#image_id}" -eq 71 ] || { echo "operator admission image identity is invalid" >&2; exit 1; }
loaded=$({ "$docker_bin" image inspect --format '{{.Id}}|{{.Os}}|{{.Architecture}}' "$image_id"; } 2>/dev/null)
[ "$loaded" = "$image_id|linux|amd64" ] || { echo "admitted operator image is unavailable" >&2; exit 1; }

docker_host_binary=$docker_bin
if [ -L "$docker_host_binary" ]; then
  link=$(readlink "$docker_host_binary")
  case "$link" in
    /*) docker_host_binary=$link ;;
    *) docker_host_binary=$(dirname "$docker_host_binary")/$link ;;
  esac
fi

set -- "$@"
"$docker_bin" run --rm \
  --network none \
  --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=32m \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --user 0:0 \
  --volume /var/run/docker.sock:/var/run/docker.sock \
  --volume "$docker_host_binary:/usr/local/bin/docker:ro" \
  --volume /volume1/my-pa:/volume1/my-pa \
  --volume /etc/my-pa:/etc/my-pa \
  --volume "$repo_root:$repo_root:ro" \
  --env MY_PA_NAS_DOCKER=/usr/local/bin/docker \
  --workdir "$repo_root" \
  --entrypoint python \
  "$image_id" "$@"
