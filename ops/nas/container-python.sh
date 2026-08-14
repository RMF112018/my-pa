#!/bin/sh
set -eu

: "${MY_PA_NAS_DOCKER:=/usr/local/bin/docker}"
: "${MY_PA_NAS_COMPOSE_PLUGIN:=/usr/local/bin/docker-compose}"
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
[ -x "$docker_host_binary" ] || { echo "resolved Docker binary is unavailable" >&2; exit 1; }

compose_host_binary=$MY_PA_NAS_COMPOSE_PLUGIN
case "$compose_host_binary" in
  /*) ;;
  *) compose_host_binary=$(command -v "$compose_host_binary") ;;
esac
if [ -L "$compose_host_binary" ]; then
  link=$(readlink "$compose_host_binary")
  case "$link" in
    /*) compose_host_binary=$link ;;
    *) compose_host_binary=$(dirname "$compose_host_binary")/$link ;;
  esac
fi
[ -x "$compose_host_binary" ] || { echo "resolved Docker Compose plugin is unavailable" >&2; exit 1; }
compose_plugin_dir=/usr/local/lib/docker/cli-plugins

python_arguments=$#
[ "$python_arguments" -gt 0 ] || { echo "Python arguments are required" >&2; exit 64; }
python_args=""
for value in "$@"; do
  case "$value" in
    *'
'*) echo "newline-containing Python arguments are prohibited" >&2; exit 64 ;;
  esac
  python_args="${python_args}${python_args:+
}${value}"
done

# Preserve only the closed Compose interpolation and synthetic-acceptance
# environment. `--env NAME` asks Docker to copy the value without placing it in
# this process's command line or output.
env_args=""
for name in \
  MY_PA_POSTGRES_IMAGE_ID MY_PA_APP_IMAGE_ID MY_PA_WEB_IMAGE_ID \
  MY_PA_PROXY_IMAGE MY_PA_PROXY_IMAGE_DIGEST MY_PA_DB_PASSWORD \
  MY_PA_NAS_ROOT MY_PA_UID MY_PA_GID MY_PA_NAS_ENV_FILE MY_PA_WEB_ENV_FILE \
  MY_PA_PROXY_UID MY_PA_PROXY_GID MY_PA_PROXY_PORT MY_PA_TAILNET_HOST \
  MYPA_CANONICAL_ORIGIN MYPA_ENTRA_REDIRECT_URI \
  MY_PA_NAS10_SYNTHETIC_DATABASE_URL MY_PA_NAS10_DISPOSABLE_DATABASE_ACK
do
  eval "present=\${$name+x}"
  if [ "$present" = x ]; then
    env_args="${env_args}${env_args:+
}--env
${name}"
  fi
done

# Live ingress verification also needs the NAS Tailscale control socket. Keep
# that authority opt-in so ordinary image, database, and lifecycle gates retain
# only the Docker authority they already require.
tailscale_args=""
if [ "${MY_PA_NAS_TAILSCALE+x}" = x ] || [ "${MY_PA_NAS_TAILSCALE_SOCKET+x}" = x ]; then
  : "${MY_PA_NAS_TAILSCALE:?exact NAS Tailscale executable required}"
  : "${MY_PA_NAS_TAILSCALE_SOCKET:?exact NAS Tailscale socket required}"
  case "$MY_PA_NAS_TAILSCALE$MY_PA_NAS_TAILSCALE_SOCKET" in
    *'
'*) echo "newline-containing Tailscale paths are prohibited" >&2; exit 64 ;;
  esac
  case "$MY_PA_NAS_TAILSCALE" in
    /*) tailscale_host_binary=$MY_PA_NAS_TAILSCALE ;;
    *) echo "Tailscale executable path must be absolute" >&2; exit 64 ;;
  esac
  case "$MY_PA_NAS_TAILSCALE_SOCKET" in
    /*) ;;
    *) echo "Tailscale socket path must be absolute" >&2; exit 64 ;;
  esac
  [ -f "$tailscale_host_binary" ] && [ -x "$tailscale_host_binary" ] || {
    echo "Tailscale executable is unavailable" >&2
    exit 1
  }
  [ -S "$MY_PA_NAS_TAILSCALE_SOCKET" ] || {
    echo "Tailscale socket is unavailable" >&2
    exit 1
  }
  tailscale_args="--volume
${tailscale_host_binary}:/usr/local/bin/tailscale:ro
--volume
${MY_PA_NAS_TAILSCALE_SOCKET}:/var/run/tailscale/tailscaled.sock:ro"
fi

# Reconstruct allowlisted environment options, the image, then the original
# Python argv. Repository gate arguments are ordinary newline-free paths/flags.
old_ifs=$IFS
IFS='
'
set --
for value in $env_args; do set -- "$@" "$value"; done
for value in $tailscale_args; do set -- "$@" "$value"; done
set -- "$@" "$image_id"
for value in $python_args; do set -- "$@" "$value"; done
IFS=$old_ifs

"$docker_bin" run --rm -i \
  --network none \
  --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=32m \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --user 0:0 \
  --volume /var/run/docker.sock:/var/run/docker.sock \
  --volume "$docker_host_binary:/usr/local/bin/docker:ro" \
  --volume "$compose_host_binary:$compose_plugin_dir/docker-compose:ro" \
  --volume /volume1/my-pa:/volume1/my-pa \
  --volume /etc/my-pa:/etc/my-pa \
  --volume "$repo_root:$repo_root:ro" \
  --env MY_PA_NAS_DOCKER=/usr/local/bin/docker \
  --env DOCKER_CLI_PLUGIN_EXTRA_DIRS="$compose_plugin_dir" \
  --workdir "$repo_root" \
  --entrypoint python \
  "$@"
