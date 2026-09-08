#!/bin/sh
(
  set -eu
  script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

  if [ -n "${MY_PA_PRESERVED_RUNTIME_SOURCE:-}" ]; then
    : "${MY_PA_NAS_COMPOSE_FILE:?exact NAS compose file required}"
    : "${MY_PA_POSTGRES_RESOURCES:?verified PostgreSQL resource manifest required}"
    : "${MY_PA_IMAGE_MANIFEST:?exact preserved deployable image manifest required}"
    : "${MY_PA_CURRENT_GATE_SOURCE:?exact current-gate source required}"
    : "${MY_PA_CURRENT_GATE_IMAGE_MANIFEST:?current-gate image manifest required}"
    : "${MY_PA_NAS_OPERATOR_ADMISSION:=/etc/my-pa/operator-runtime.toml}"
    : "${MY_PA_POSTGRES_BOOTSTRAP_ADMISSION:?preserved PostgreSQL bootstrap admission required}"
    [ "${MY_PA_LIFECYCLE_MODE:-smoke}" = smoke ] || {
      echo "preserved-runtime backup requires smoke lifecycle mode" >&2
      exit 1
    }
    case "$MY_PA_PRESERVED_RUNTIME_SOURCE" in
      /*) ;;
      *) echo "preserved runtime source must be absolute" >&2; exit 64 ;;
    esac
    [ ! -L "$MY_PA_PRESERVED_RUNTIME_SOURCE" ] || {
      echo "preserved runtime source must not be linked" >&2
      exit 1
    }
    preserved_source=$MY_PA_PRESERVED_RUNTIME_SOURCE
    preserved_ops="$preserved_source/ops/nas"
    preserved_compose="$preserved_ops/compose.example.yml"
    preserved_pilot="$preserved_ops/compose.pilot.example.yml"
    current_source=$MY_PA_CURRENT_GATE_SOURCE
    case "$current_source" in
      /*) ;;
      *) echo "current-gate source must be absolute" >&2; exit 64 ;;
    esac
    [ ! -L "$current_source" ] && [ -d "$current_source" ] || {
      echo "current-gate source must be an unlinked directory" >&2
      exit 1
    }
    [ -f "$MY_PA_NAS_OPERATOR_ADMISSION" ] && [ ! -L "$MY_PA_NAS_OPERATOR_ADMISSION" ] || {
      echo "current operator admission is unavailable or linked" >&2
      exit 1
    }
    [ "$(stat -c '%u:%a:%h' "$MY_PA_NAS_OPERATOR_ADMISSION")" = "0:400:1" ] || {
      echo "current operator admission must be root-owned mode 0400 with one link" >&2
      exit 1
    }
    operator_image_id=$(sed -n 's/^operator_image_id = "\(sha256:[0-9a-f][0-9a-f]*\)"$/\1/p' "$MY_PA_NAS_OPERATOR_ADMISSION")
    operator_archive=$(sed -n 's/^operator_archive_path = "\([^"]*\)"$/\1/p' "$MY_PA_NAS_OPERATOR_ADMISSION")
    operator_candidate=$(sed -n 's/^operator_candidate_path = "\([^"]*\)"$/\1/p' "$MY_PA_NAS_OPERATOR_ADMISSION")
    operator_metadata=$(sed -n 's/^operator_metadata_path = "\([^"]*\)"$/\1/p' "$MY_PA_NAS_OPERATOR_ADMISSION")
    [ "${#operator_image_id}" -eq 71 ] && [ -n "$operator_archive" ] && \
      [ -n "$operator_candidate" ] && [ -n "$operator_metadata" ] || {
      echo "current operator admission bootstrap identity is invalid" >&2
      exit 1
    }
    for artifact in "$operator_archive" "$operator_candidate" "$operator_metadata" \
      "$MY_PA_CURRENT_GATE_IMAGE_MANIFEST"; do
      [ -f "$artifact" ] && [ ! -L "$artifact" ] || {
        echo "pre-source gate input is unavailable or linked" >&2
        exit 1
      }
    done
    [ "$MY_PA_NAS_COMPOSE_FILE" = "$preserved_compose" ] || {
      echo "preserved runtime Compose identity mismatch" >&2
      exit 1
    }

    canonical_docker=/usr/local/bin/docker
    canonical_compose=/usr/local/bin/docker-compose
    [ -x "$canonical_docker" ] && [ -x "$canonical_compose" ] || {
      echo "canonical Docker tooling is unavailable" >&2
      exit 1
    }
    "$canonical_docker" run --rm \
      --network none --read-only --tmpfs /tmp:rw,nosuid,nodev,noexec,size=16m \
      --cap-drop ALL --security-opt no-new-privileges --user 0:0 \
      --volume /var/run/docker.sock:/var/run/docker.sock \
      --volume "$canonical_docker:/usr/local/bin/docker:ro" \
      --volume "$canonical_compose:/usr/local/lib/docker/cli-plugins/docker-compose:ro" \
      --volume "$MY_PA_NAS_OPERATOR_ADMISSION:/run/my-pa-input/admission.toml:ro" \
      --volume "$operator_archive:/run/my-pa-input/operator.tar:ro" \
      --volume "$operator_candidate:/run/my-pa-input/operator-candidate.toml:ro" \
      --volume "$operator_metadata:/run/my-pa-input/operator-metadata.json:ro" \
      --volume "$current_source:/run/my-pa-input/current-source:ro" \
      --volume "$MY_PA_CURRENT_GATE_IMAGE_MANIFEST:/run/my-pa-input/current-manifest.toml:ro" \
      --env MY_PA_NAS_DOCKER=/usr/local/bin/docker \
      --env DOCKER_CLI_PLUGIN_EXTRA_DIRS=/usr/local/lib/docker/cli-plugins \
      --entrypoint python "$operator_image_id" \
      /usr/local/libexec/my-pa-operator-pre-source-gate.py \
      /run/my-pa-input/admission.toml /run/my-pa-input/current-source \
      /run/my-pa-input/current-manifest.toml \
      "$MY_PA_NAS_OPERATOR_ADMISSION" "$current_source" \
      "$MY_PA_CURRENT_GATE_IMAGE_MANIFEST" \
      "$operator_archive" "$operator_candidate" "$operator_metadata" \
      /run/my-pa-input/operator.tar /run/my-pa-input/operator-candidate.toml \
      /run/my-pa-input/operator-metadata.json
    current_ops="$current_source/ops/nas"
    . "$current_ops/tooling-common.sh"
    "$NAS_PYTHON_BIN" "$current_ops/preserved_backup_gate.py" \
      "$current_source" "$MY_PA_CURRENT_GATE_IMAGE_MANIFEST" "$preserved_source" \
      "$MY_PA_IMAGE_MANIFEST" "$preserved_compose"
    "$NAS_PYTHON_BIN" "$current_ops/lifecycle_gate.py" \
      "$current_ops/compose.example.yml" "$current_ops/compose.pilot.example.yml" \
      --image-manifest "$MY_PA_CURRENT_GATE_IMAGE_MANIFEST" --live
    "$NAS_PYTHON_BIN" "$preserved_ops/lifecycle_gate.py" \
      "$preserved_compose" "$preserved_pilot" \
      --image-manifest "$MY_PA_IMAGE_MANIFEST" --live
    "$NAS_PYTHON_BIN" "$preserved_ops/runtime_identity_gate.py" \
      "$preserved_compose" "$MY_PA_IMAGE_MANIFEST"
    "$NAS_PYTHON_BIN" "$preserved_ops/postgres-bootstrap-identity-gate.py" \
      "$preserved_compose" "$MY_PA_IMAGE_MANIFEST" \
      --admission "$MY_PA_POSTGRES_BOOTSTRAP_ADMISSION"
    nas_compose() {
      nas_docker compose --file "$preserved_compose" \
        --profile nas-01-contract-only "$@"
    }
    postgres_container_id=$(nas_compose ps -q postgres)
    [ -n "$postgres_container_id" ] || {
      echo "Compose postgres service is not running" >&2
      exit 1
    }
    "$NAS_PYTHON_BIN" "$preserved_ops/postgres_gate.py" \
      "$MY_PA_POSTGRES_RESOURCES" --live --container-id "$postgres_container_id"
    "$current_ops/synology-data-plane-firewall.sh" check
    nas_docker exec -i "$postgres_container_id" sh -eu -c \
      'test -w /var/lib/postgresql/data && postgres --version | grep -Eq "PostgreSQL[)]? 17[.]10([[:space:]]|$)"'
    pg_exec() {
      current=$(nas_compose ps -q postgres)
      [ "$current" = "$postgres_container_id" ] || {
        echo "Compose postgres identity drift" >&2
        exit 1
      }
      nas_docker exec -i "$postgres_container_id" "$@"
    }
  else
    . "$script_dir/postgres-common.sh"
    current_source=$script_dir
  fi

  [ "$#" -eq 1 ] || {
    echo "usage: $0 EXISTING_BACKUP_DIRECTORY" >&2
    exit 64
  }
  case "$1" in
    /*) ;;
    *) echo "backup destination must be an absolute physical directory" >&2; exit 64 ;;
  esac
  [ -d "$1" ] && [ ! -L "$1" ] || {
    echo "backup destination must be an existing unlinked directory" >&2
    exit 1
  }
  destination=$(CDPATH= cd -- "$1" && pwd -P)
  [ "$destination" = "${1%/}" ] || {
    echo "backup destination must be an absolute physical directory" >&2
    exit 1
  }
  [ "$(stat -c '%u:%a' "$destination")" = "$(id -u):700" ] || {
    echo "backup destination must be operator-owned mode 0700" >&2
    exit 1
  }
  repo_root=$(git -C "$current_source" rev-parse --show-toplevel)
  repo_root=$(CDPATH= cd -- "$repo_root" && pwd -P)
  preserved_repo_root=""
  if [ -n "${preserved_source:-}" ]; then
    preserved_repo_root=$(git -C "$preserved_source" rev-parse --show-toplevel)
    preserved_repo_root=$(CDPATH= cd -- "$preserved_repo_root" && pwd -P)
  fi
  case "$destination/" in
    "$repo_root/"*) echo "backup destination must be outside repository" >&2; exit 1 ;;
  esac
  if [ -n "$preserved_repo_root" ]; then
    case "$destination/" in
      "$preserved_repo_root/"*)
        echo "backup destination must be outside preserved repository" >&2
        exit 1
        ;;
    esac
  fi
  umask 077
  timestamp=$(date -u +%Y%m%dT%H%M%SZ)
  final="$destination/my-pa-$timestamp.dump"
  partial="$final.partial.$$"
  receipt="$final.sha256"
  [ ! -e "$final" ] && [ ! -e "$receipt" ] || {
    echo "backup collision" >&2
    exit 1
  }
  set -C
  exec 3> "$partial"
  set +C
  trap 'rm -f "$partial"' EXIT HUP INT TERM
  pg_exec pg_dump --username my_pa --dbname my_pa \
    --format custom --compress=zstd:9 --no-owner --no-privileges >&3
  exec 3>&-
  pg_exec pg_restore --list < "$partial" >/dev/null
  mv "$partial" "$final"
  digest=$(sha256_file "$final")
  printf '%s  %s\n' "$digest" "$(basename "$final")" > "$receipt"
  trap - EXIT HUP INT TERM
  echo "$receipt"
)
