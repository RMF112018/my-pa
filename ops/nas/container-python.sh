#!/bin/sh
set -eu

# This wrapper is a trust boundary. Do not make host executable, admission, or
# repository paths configurable here: callers can provide Compose values, but
# cannot select the programs that interpret them.
PATH=/usr/bin:/bin
LC_ALL=C
LANG=C
IFS='
	 '
CDPATH=
export PATH LC_ALL LANG IFS CDPATH
unset ENV BASH_ENV ZDOTDIR
unset LD_PRELOAD LD_LIBRARY_PATH LD_AUDIT LD_DEBUG LD_ORIGIN_PATH
unset DYLD_INSERT_LIBRARIES DYLD_LIBRARY_PATH DYLD_FRAMEWORK_PATH
unset DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG DOCKER_CERT_PATH
unset DOCKER_TLS DOCKER_TLS_VERIFY DOCKER_API_VERSION DOCKER_CLI_HINTS
unset DOCKER_CLI_EXPERIMENTAL DOCKER_CLI_PLUGIN_EXTRA_DIRS
unset COMPOSE_FILE COMPOSE_PATH_SEPARATOR COMPOSE_PROJECT_NAME COMPOSE_PROFILES
unset MY_PA_NAS_DOCKER MY_PA_NAS_COMPOSE_PLUGIN MY_PA_NAS_OPERATOR_ADMISSION

stat_bin=/usr/bin/stat
docker_path=/usr/local/bin/docker
compose_path=/usr/local/bin/docker-compose
git_path=/usr/bin/git
admission_path=/etc/my-pa/operator-runtime.toml
docker_socket_path=/var/run/docker.sock
compose_plugin_dir=/usr/local/lib/docker/cli-plugins

fail() {
  echo "$1" >&2
  exit "${2:-1}"
}

has_group_or_other_write() {
  mode=$1
  tail=${mode#"${mode%??}"}
  case "$tail" in
    *[2367]*) return 0 ;;
    *) return 1 ;;
  esac
}

is_forwarded_environment_name() {
  case "$1" in
    PATH|LC_ALL|LANG|\
    MY_PA_POSTGRES_IMAGE_ID|MY_PA_APP_IMAGE_ID|MY_PA_WEB_IMAGE_ID|\
    MY_PA_PROXY_IMAGE|MY_PA_PROXY_IMAGE_DIGEST|MY_PA_DB_PASSWORD|\
    MY_PA_NAS_ROOT|MY_PA_UID|MY_PA_GID|MY_PA_NAS_ENV_FILE|MY_PA_WEB_ENV_FILE|\
    MY_PA_PROXY_UID|MY_PA_PROXY_GID|MY_PA_PROXY_PORT|MY_PA_TAILNET_HOST|\
    MYPA_CANONICAL_ORIGIN|MYPA_ENTRA_REDIRECT_URI|MYPA_SESSION_SERVICE_SECRET|\
    MY_PA_NAS10_SYNTHETIC_DATABASE_URL|MY_PA_NAS10_DISPOSABLE_DATABASE_ACK)
      return 0
      ;;
    *) return 1 ;;
  esac
}

sanitize_docker_client_environment() {
  # Extract variable names only. Values, including forwarded secrets, never
  # enter an argument, diagnostic, or generated file. The fixed environment
  # command and filter leave malformed/newline value continuations unmatched.
  environment_names=$(/usr/bin/env | /usr/bin/sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*$/\1/p')
  old_ifs=$IFS
  IFS='
'
  for name in $environment_names; do
    is_forwarded_environment_name "$name" || unset "$name" || {
      IFS=$old_ifs
      fail "unable to sanitize Docker client environment"
    }
  done
  IFS=$old_ifs
  unset environment_names
  PATH=/usr/bin:/bin
  LC_ALL=C
  LANG=C
  export PATH LC_ALL LANG
}

verify_root_owned_ancestors() {
  ancestor_path=$1
  while :; do
    [ ! -L "$ancestor_path" ] || fail "trusted path contains a symbolic link"
    [ -d "$ancestor_path" ] || fail "trusted path ancestor is unavailable"
    metadata=$("$stat_bin" -c '%u:%a:%F' -- "$ancestor_path") || fail "trusted path metadata is unavailable"
    owner=${metadata%%:*}
    remainder=${metadata#*:}
    mode=${remainder%%:*}
    kind=${remainder#*:}
    [ "$owner" = 0 ] && [ "$kind" = directory ] || fail "trusted path ancestors must be root-owned directories"
    has_group_or_other_write "$mode" && fail "trusted path ancestors must not be group- or world-writable"
    [ "$ancestor_path" = / ] && return
    ancestor_path=${ancestor_path%/*}
    [ -n "$ancestor_path" ] || ancestor_path=/
  done
}

verify_root_owned_regular_file() {
  path=$1
  label=$2
  case "$path" in
    /*) ;;
    *) fail "$label path must be absolute" 64 ;;
  esac
  case "$path" in
    *'
'*|*//*|*/./*|*/../*|*/.|*/..) fail "$label path is not canonical" 64 ;;
  esac
  [ ! -L "$path" ] || fail "$label must not be a symbolic link"
  [ -f "$path" ] || fail "$label is unavailable"
  parent=${path%/*}
  [ -n "$parent" ] || parent=/
  verify_root_owned_ancestors "$parent"
  metadata=$("$stat_bin" -c '%u:%a:%h:%F' -- "$path") || fail "$label metadata is unavailable"
  owner=${metadata%%:*}
  remainder=${metadata#*:}
  mode=${remainder%%:*}
  remainder=${remainder#*:}
  links=${remainder%%:*}
  kind=${remainder#*:}
  [ "$owner" = 0 ] && [ "$kind" = 'regular file' ] && [ "$links" = 1 ] || {
    fail "$label must be a root-owned unlinked regular file"
  }
  has_group_or_other_write "$mode" && fail "$label must not be group- or world-writable"
  return 0
}

verify_exact_operator_admission() {
  path=$1
  case "$path" in
    /*) ;;
    *) fail "operator admission path must be absolute" 64 ;;
  esac
  case "$path" in
    *'
'*|*//*|*/./*|*/../*|*/.|*/..) fail "operator admission path is not canonical" 64 ;;
  esac
  [ ! -L "$path" ] || fail "operator admission must not be a symbolic link"
  [ -f "$path" ] || fail "operator admission is unavailable"
  parent=${path%/*}
  [ -n "$parent" ] || parent=/
  verify_root_owned_ancestors "$parent"
  metadata=$("$stat_bin" -c '%u:%a:%h:%F' -- "$path") || fail "operator admission metadata is unavailable"
  [ "$metadata" = '0:400:1:regular file' ] || {
    fail "operator admission must be root-owned mode 0400 with one link"
  }
}

verify_root_owned_socket() {
  path=$1
  label=$2
  case "$path" in
    /*) ;;
    *) fail "$label path must be absolute" 64 ;;
  esac
  case "$path" in
    *'
'*|*//*|*/./*|*/../*|*/.|*/..) fail "$label path is not canonical" 64 ;;
  esac
  [ ! -L "$path" ] || fail "$label must not be a symbolic link"
  [ -S "$path" ] || fail "$label is unavailable"
  parent=${path%/*}
  [ -n "$parent" ] || parent=/
  verify_root_owned_ancestors "$parent"
  metadata=$("$stat_bin" -c '%u:%a:%h:%F' -- "$path") || fail "$label metadata is unavailable"
  owner=${metadata%%:*}
  remainder=${metadata#*:}
  mode=${remainder%%:*}
  remainder=${remainder#*:}
  links=${remainder%%:*}
  kind=${remainder#*:}
  [ "$owner" = 0 ] && [ "$kind" = socket ] && [ "$links" = 1 ] || {
    fail "$label must be a root-owned single-link socket"
  }
  has_group_or_other_write "$mode" && fail "$label must not be group- or world-writable"
  return 0
}

is_lower_hex() {
  value=$1
  expected_length=$2
  [ "${#value}" -eq "$expected_length" ] || return 1
  case "$value" in
    *[!0-9a-f]*) return 1 ;;
    *) return 0 ;;
  esac
}

is_git_object() {
  is_lower_hex "$1" 40
}

is_sha256_identity() {
  case "$1" in
    sha256:*) is_lower_hex "${1#sha256:}" 64 ;;
    *) return 1 ;;
  esac
}

is_absolute_path() {
  case "$1" in
    /*) return 0 ;;
    *) return 1 ;;
  esac
}

is_nonblank() {
  case "$1" in
    *[![:space:]]*) return 0 ;;
    *) return 1 ;;
  esac
}

is_numeric_version() {
  version=$1
  first=${version%%.*}
  remainder=${version#*.}
  [ "$remainder" != "$version" ] || return 1
  second=${remainder%%.*}
  third=${remainder#*.}
  [ "$third" != "$remainder" ] || return 1
  case "$first:$second:$third" in
    *[!0-9:]*|:*|*::*) return 1 ;;
    *:) return 1 ;;
    *) return 0 ;;
  esac
}

is_compose_version() {
  version=$1
  case "$version" in
    v*) version=${version#v} ;;
  esac
  base=${version%%[-+]*}
  suffix=${version#"$base"}
  is_numeric_version "$base" || return 1
  case "$suffix" in
    '') return 0 ;;
    -?*|+?*) ;;
    *) return 1 ;;
  esac
  suffix=${suffix#?}
  case "$suffix" in
    ''|*[!0-9A-Za-z.-]*) return 1 ;;
    *) return 0 ;;
  esac
}

set_admission_field() {
  name=$1
  value=$2
  case "$name" in
    schema) [ -z "${admission_schema_seen-}" ] || fail "operator admission contains duplicate fields"; admission_schema=$value; admission_schema_seen=x ;;
    status) [ -z "${admission_status_seen-}" ] || fail "operator admission contains duplicate fields"; admission_status=$value; admission_status_seen=x ;;
    repository_commit) [ -z "${admission_repository_commit_seen-}" ] || fail "operator admission contains duplicate fields"; admission_repository_commit=$value; admission_repository_commit_seen=x ;;
    repository_tree) [ -z "${admission_repository_tree_seen-}" ] || fail "operator admission contains duplicate fields"; admission_repository_tree=$value; admission_repository_tree_seen=x ;;
    repository_source_path) [ -z "${admission_repository_source_path_seen-}" ] || fail "operator admission contains duplicate fields"; admission_repository_source_path=$value; admission_repository_source_path_seen=x ;;
    docker_engine_id) [ -z "${admission_docker_engine_id_seen-}" ] || fail "operator admission contains duplicate fields"; admission_docker_engine_id=$value; admission_docker_engine_id_seen=x ;;
    docker_engine_name) [ -z "${admission_docker_engine_name_seen-}" ] || fail "operator admission contains duplicate fields"; admission_docker_engine_name=$value; admission_docker_engine_name_seen=x ;;
    operator_image_id) [ -z "${admission_operator_image_id_seen-}" ] || fail "operator admission contains duplicate fields"; admission_operator_image_id=$value; admission_operator_image_id_seen=x ;;
    operator_manifest_digest) [ -z "${admission_operator_manifest_digest_seen-}" ] || fail "operator admission contains duplicate fields"; admission_operator_manifest_digest=$value; admission_operator_manifest_digest_seen=x ;;
    operator_archive_path) [ -z "${admission_operator_archive_path_seen-}" ] || fail "operator admission contains duplicate fields"; admission_operator_archive_path=$value; admission_operator_archive_path_seen=x ;;
    operator_archive_sha256) [ -z "${admission_operator_archive_sha256_seen-}" ] || fail "operator admission contains duplicate fields"; admission_operator_archive_sha256=$value; admission_operator_archive_sha256_seen=x ;;
    operator_candidate_path) [ -z "${admission_operator_candidate_path_seen-}" ] || fail "operator admission contains duplicate fields"; admission_operator_candidate_path=$value; admission_operator_candidate_path_seen=x ;;
    operator_candidate_sha256) [ -z "${admission_operator_candidate_sha256_seen-}" ] || fail "operator admission contains duplicate fields"; admission_operator_candidate_sha256=$value; admission_operator_candidate_sha256_seen=x ;;
    operator_metadata_path) [ -z "${admission_operator_metadata_path_seen-}" ] || fail "operator admission contains duplicate fields"; admission_operator_metadata_path=$value; admission_operator_metadata_path_seen=x ;;
    operator_metadata_sha256) [ -z "${admission_operator_metadata_sha256_seen-}" ] || fail "operator admission contains duplicate fields"; admission_operator_metadata_sha256=$value; admission_operator_metadata_sha256_seen=x ;;
    python_version) [ -z "${admission_python_version_seen-}" ] || fail "operator admission contains duplicate fields"; admission_python_version=$value; admission_python_version_seen=x ;;
    git_version) [ -z "${admission_git_version_seen-}" ] || fail "operator admission contains duplicate fields"; admission_git_version=$value; admission_git_version_seen=x ;;
    openssl_version) [ -z "${admission_openssl_version_seen-}" ] || fail "operator admission contains duplicate fields"; admission_openssl_version=$value; admission_openssl_version_seen=x ;;
    compose_version) [ -z "${admission_compose_version_seen-}" ] || fail "operator admission contains duplicate fields"; admission_compose_version=$value; admission_compose_version_seen=x ;;
    *) fail "operator admission has an unexpected field" ;;
  esac
  admission_field_count=$((admission_field_count + 1))
}

read_and_validate_admission_contract() {
  admission_field_count=0
  while :; do
    line=
    if IFS= read -r line <&6; then
      :
    else
      [ -z "$line" ] && break
      fail "operator admission shape is invalid"
    fi
    case "$line" in
      schema\ =\ \"*\") field=schema ;;
      status\ =\ \"*\") field=status ;;
      repository_commit\ =\ \"*\") field=repository_commit ;;
      repository_tree\ =\ \"*\") field=repository_tree ;;
      repository_source_path\ =\ \"*\") field=repository_source_path ;;
      docker_engine_id\ =\ \"*\") field=docker_engine_id ;;
      docker_engine_name\ =\ \"*\") field=docker_engine_name ;;
      operator_image_id\ =\ \"*\") field=operator_image_id ;;
      operator_manifest_digest\ =\ \"*\") field=operator_manifest_digest ;;
      operator_archive_path\ =\ \"*\") field=operator_archive_path ;;
      operator_archive_sha256\ =\ \"*\") field=operator_archive_sha256 ;;
      operator_candidate_path\ =\ \"*\") field=operator_candidate_path ;;
      operator_candidate_sha256\ =\ \"*\") field=operator_candidate_sha256 ;;
      operator_metadata_path\ =\ \"*\") field=operator_metadata_path ;;
      operator_metadata_sha256\ =\ \"*\") field=operator_metadata_sha256 ;;
      python_version\ =\ \"*\") field=python_version ;;
      git_version\ =\ \"*\") field=git_version ;;
      openssl_version\ =\ \"*\") field=openssl_version ;;
      compose_version\ =\ \"*\") field=compose_version ;;
      *) fail "operator admission shape is invalid" ;;
    esac
    prefix="$field = \""
    value=${line#"$prefix"}
    value=${value%\"}
    [ "$value" != "$line" ] || fail "operator admission shape is invalid"
    case "$value" in
      *\"*|*\\*) fail "operator admission shape is invalid" ;;
    esac
    set_admission_field "$field" "$value"
  done
  [ "$admission_field_count" -eq 19 ] || fail "operator admission shape is invalid"
  [ "$admission_schema" = 'my-pa.nas-operator-runtime-admission.v1' ] && \
    [ "$admission_status" = admitted ] || fail "operator admission shape is invalid"
  is_git_object "$admission_repository_commit" && is_git_object "$admission_repository_tree" || \
    fail "operator admission repository identity is invalid"
  is_absolute_path "$admission_repository_source_path" || fail "operator admission repository path is invalid"
  is_nonblank "$admission_docker_engine_id" && is_nonblank "$admission_docker_engine_name" || \
    fail "operator admission engine identity is invalid"
  is_sha256_identity "$admission_operator_image_id" && \
    is_sha256_identity "$admission_operator_manifest_digest" || fail "operator admission image identity is invalid"
  for artifact_hash in "$admission_operator_archive_sha256" "$admission_operator_candidate_sha256" \
    "$admission_operator_metadata_sha256"; do
    is_lower_hex "$artifact_hash" 64 || fail "operator admission artifact identity is invalid"
  done
  for artifact_path in "$admission_operator_archive_path" "$admission_operator_candidate_path" \
    "$admission_operator_metadata_path"; do
    is_absolute_path "$artifact_path" || fail "operator admission artifact path is invalid"
  done
  is_numeric_version "$admission_python_version" || fail "operator admission Python identity is invalid"
  case "$admission_git_version" in 'git version '?*) ;; *) fail "operator admission Git identity is invalid" ;; esac
  case "$admission_openssl_version" in 'OpenSSL '?*) ;; *) fail "operator admission OpenSSL identity is invalid" ;; esac
  is_compose_version "$admission_compose_version" || fail "operator admission Compose identity is invalid"
}

open_verified_file_descriptor() {
  path=$1
  label=$2
  descriptor=$3
  verify_root_owned_regular_file "$path" "$label"
  before=$("$stat_bin" -c '%d:%i' -- "$path") || fail "$label identity is unavailable"
  case "$descriptor" in
    3) exec 3< "$path"; verify_fd_path=/proc/$$/fd/3; execution_fd_path=/proc/self/fd/3 ;;
    4) exec 4< "$path"; verify_fd_path=/proc/$$/fd/4; execution_fd_path=/proc/self/fd/4 ;;
    5) exec 5< "$path"; verify_fd_path=/proc/$$/fd/5; execution_fd_path=/proc/self/fd/5 ;;
    6) exec 6< "$path"; verify_fd_path=/proc/$$/fd/6; execution_fd_path=/proc/self/fd/6 ;;
    7) exec 7< "$path"; verify_fd_path=/proc/$$/fd/7; execution_fd_path=/proc/self/fd/7 ;;
    *) fail "internal descriptor selection is invalid" ;;
  esac
  after=$("$stat_bin" -Lc '%d:%i' -- "$verify_fd_path") || fail "$label descriptor is unavailable"
  [ "$before" = "$after" ] || fail "$label changed while opening"
  # `exec N<` descriptors are inherited by the child command. `/proc/self`
  # therefore resolves that child's verified descriptor, unlike `/proc/$$`,
  # which names the parent shell and is unavailable in command substitutions.
  verified_fd_path=$execution_fd_path
}

verify_root_owned_source_directory() {
  path=$1
  case "$path" in
    /*) ;;
    *) fail "repository source path must be absolute" ;;
  esac
  case "$path" in
    *'
'*|*//*|*/./*|*/../*|*/.|*/..) fail "repository source path is not canonical" ;;
  esac
  verify_root_owned_ancestors "$path"
}

verify_optional_root_owned_regular_file() {
  path=$1
  label=$2
  [ ! -L "$path" ] && [ ! -e "$path" ] && return 0
  verify_root_owned_regular_file "$path" "$label"
}

verify_trusted_git_metadata() {
  metadata_dir=$1
  [ ! -L "$metadata_dir" ] && [ -d "$metadata_dir" ] || \
    fail "repository Git metadata must be a direct directory"
  verify_root_owned_ancestors "$metadata_dir"
  verify_root_owned_regular_file "$metadata_dir/config" 'repository Git config'
  verify_root_owned_regular_file "$metadata_dir/HEAD" 'repository Git HEAD'
  verify_root_owned_regular_file "$metadata_dir/index" 'repository Git index'
  [ ! -L "$metadata_dir/objects" ] && [ -d "$metadata_dir/objects" ] || \
    fail "repository Git objects directory is unavailable"
  verify_root_owned_ancestors "$metadata_dir/objects"
  [ ! -L "$metadata_dir/refs" ] && [ -d "$metadata_dir/refs" ] || \
    fail "repository Git refs directory is unavailable"
  verify_root_owned_ancestors "$metadata_dir/refs"
  verify_optional_root_owned_regular_file "$metadata_dir/packed-refs" 'repository packed refs'
  verify_optional_root_owned_regular_file "$metadata_dir/shallow" 'repository shallow metadata'
  [ ! -L "$metadata_dir/commondir" ] && [ ! -e "$metadata_dir/commondir" ] || \
    fail "repository Git worktree indirection is not supported"
  [ ! -L "$metadata_dir/config.worktree" ] && [ ! -e "$metadata_dir/config.worktree" ] || \
    fail "repository Git worktree configuration is not supported"
  for alternate in "$metadata_dir/objects/info/alternates" \
    "$metadata_dir/objects/info/http-alternates"; do
    [ ! -L "$alternate" ] && [ ! -e "$alternate" ] || \
      fail "repository Git object alternates are not supported"
  done
}

trusted_git() {
  /usr/bin/env -i \
    PATH=/usr/bin:/bin LC_ALL=C LANG=C HOME=/nonexistent \
    GIT_CONFIG=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_SYSTEM=/dev/null GIT_CONFIG_GLOBAL=/dev/null \
    GIT_OPTIONAL_LOCKS=0 GIT_TERMINAL_PROMPT=0 GIT_PAGER=cat GIT_NO_REPLACE_OBJECTS=1 \
    "$git_fd" --no-pager --no-replace-objects \
    -c core.hooksPath=/dev/null \
    -c core.fsmonitor=false \
    -c core.useBuiltinFSMonitor=false \
    -c core.untrackedCache=false \
    -c core.attributesfile=/dev/null \
    -c credential.helper= \
    -c core.askPass=true \
    --git-dir="$git_dir" --work-tree="$repo_root" "$@"
}

# A relative $0 lets an attacker select the resolution base. The deployment
# playbook always invokes this checked-in wrapper by its absolute path.
case "$0" in
  /*) script_path=$0 ;;
  *) fail "container-python.sh must be invoked by absolute path" 64 ;;
esac
case "$script_path" in
  *'
'*|*//*|*/./*|*/../*|*/.|*/..) fail "launcher path is not canonical" 64 ;;
esac
script_dir=${script_path%/*}
[ -n "$script_dir" ] || script_dir=/
case "$script_dir" in
  */ops/nas) repo_root=${script_dir%/ops/nas} ;;
  *) fail "launcher is outside its fixed repository location" ;;
esac
[ -n "$repo_root" ] || repo_root=/
[ "$script_path" = "$repo_root/ops/nas/container-python.sh" ] || \
  fail "launcher path is not the fixed repository wrapper"
verify_root_owned_source_directory "$repo_root"
git_dir=$repo_root/.git
verify_trusted_git_metadata "$git_dir"
verify_root_owned_socket "$docker_socket_path" 'Docker socket'

# Verify every host file before the first Docker or Git invocation. The
# descriptors are used for execution, so a later pathname replacement cannot
# redirect the host client. Docker bind mounts retain canonical root-only
# pathnames because the daemon, rather than this process, resolves mount input.
open_verified_file_descriptor "$docker_path" Docker 3
docker_fd=$verified_fd_path
open_verified_file_descriptor "$compose_path" 'Docker Compose plugin' 4
compose_fd=$verified_fd_path
open_verified_file_descriptor "$git_path" Git 5
git_fd=$verified_fd_path
verify_exact_operator_admission "$admission_path"
open_verified_file_descriptor "$admission_path" 'operator admission' 6
admission_fd=$verified_fd_path
open_verified_file_descriptor "$script_path" launcher 7
unset verified_fd_path compose_fd admission_fd

resolved_repo_root=$(trusted_git rev-parse --show-toplevel) || fail "repository source is unavailable"
[ "$resolved_repo_root" = "$repo_root" ] || fail "repository source root is unavailable"

# Authenticate the entire trusted admission schema before any image or
# container operation. Its source binding must identify this resolved checkout
# exactly, at its admitted clean commit and tree.
read_and_validate_admission_contract
[ "$repo_root" = "$admission_repository_source_path" ] || \
  fail "operator admission source path does not match resolved repository"
git_head=$(trusted_git rev-parse HEAD) || fail "repository commit is unavailable"
git_tree=$(trusted_git rev-parse 'HEAD^{tree}') || fail "repository tree is unavailable"
git_root=$(trusted_git rev-parse --show-toplevel) || fail "repository root is unavailable"
git_dirty=$(trusted_git status --porcelain --untracked-files=all) || \
  fail "repository cleanliness is unavailable"
[ "$git_root" = "$repo_root" ] && [ -z "$git_dirty" ] && \
  [ "$git_head" = "$admission_repository_commit" ] && \
  [ "$git_tree" = "$admission_repository_tree" ] || \
  fail "operator admission source identity does not match resolved repository"
image_id=$admission_operator_image_id

# Bind the fixed, verified Docker client and socket to the admitted engine
# using only a bounded scalar projection. Do not request full engine JSON or
# any configuration/environment payload.
engine_projection=$({ /usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C LANG=C HOME=/nonexistent \
  "$docker_fd" info --format '{{.ID}}|{{.Name}}'; } 2>/dev/null) || \
  fail "admitted Docker engine identity is unavailable"
[ "${#engine_projection}" -le 512 ] || fail "admitted Docker engine identity is malformed"
case "$engine_projection" in
  *'
'*|*'|'*'|'*) fail "admitted Docker engine identity is malformed" ;;
esac
engine_id=${engine_projection%%|*}
engine_name=${engine_projection#*|}
[ "$engine_id" != "$engine_projection" ] && is_nonblank "$engine_id" && \
  is_nonblank "$engine_name" || fail "admitted Docker engine identity is malformed"
[ "$engine_id" = "$admission_docker_engine_id" ] && \
  [ "$engine_name" = "$admission_docker_engine_name" ] || \
  fail "admitted Docker engine identity does not match"

loaded=$({ /usr/bin/env -i PATH=/usr/bin:/bin HOME=/nonexistent "$docker_fd" image inspect \
  --format '{{.Id}}|{{.Os}}|{{.Architecture}}' "$image_id"; } 2>/dev/null)
[ "$loaded" = "$image_id|linux|amd64" ] || fail "admitted operator image is unavailable"

python_arguments=$#
[ "$python_arguments" -gt 0 ] || fail "Python arguments are required" 64
set -- "$image_id" "$@"

# Preserve only the closed Compose interpolation and synthetic-acceptance
# environment. `--env NAME` asks Docker to copy the value without placing it in
# this process's command line or output. All Docker client control variables
# were cleared above before the client can be run.
for name in \
  MY_PA_POSTGRES_IMAGE_ID MY_PA_APP_IMAGE_ID MY_PA_WEB_IMAGE_ID \
  MY_PA_PROXY_IMAGE MY_PA_PROXY_IMAGE_DIGEST MY_PA_DB_PASSWORD \
  MY_PA_NAS_ROOT MY_PA_UID MY_PA_GID MY_PA_NAS_ENV_FILE MY_PA_WEB_ENV_FILE \
  MY_PA_PROXY_UID MY_PA_PROXY_GID MY_PA_PROXY_PORT MY_PA_TAILNET_HOST \
  MYPA_CANONICAL_ORIGIN MYPA_ENTRA_REDIRECT_URI MYPA_SESSION_SERVICE_SECRET \
  MY_PA_NAS10_SYNTHETIC_DATABASE_URL MY_PA_NAS10_DISPOSABLE_DATABASE_ACK
do
  eval "present=\${$name+x}"
  if [ "$present" = x ]; then
    set -- --env "$name" "$@"
  fi
done

# Live ingress verification also needs the NAS Tailscale control socket. Keep
# that authority opt-in so ordinary image, database, and lifecycle gates retain
# only the Docker authority they already require. Its path is operator input,
# not a host executable this wrapper invokes, and is still constrained to a
# root-owned, non-writable executable and socket pair.
if [ "${MY_PA_NAS_TAILSCALE+x}" = x ] || [ "${MY_PA_NAS_TAILSCALE_SOCKET+x}" = x ]; then
  : "${MY_PA_NAS_TAILSCALE:?exact NAS Tailscale executable required}"
  : "${MY_PA_NAS_TAILSCALE_SOCKET:?exact NAS Tailscale socket required}"
  case "$MY_PA_NAS_TAILSCALE$MY_PA_NAS_TAILSCALE_SOCKET" in
    *'
'*) fail "newline-containing Tailscale paths are prohibited" 64 ;;
  esac
  tailscale_host_binary=$MY_PA_NAS_TAILSCALE
  tailscale_socket_path=$MY_PA_NAS_TAILSCALE_SOCKET
  verify_root_owned_regular_file "$tailscale_host_binary" 'Tailscale executable'
  verify_root_owned_socket "$tailscale_socket_path" 'Tailscale socket'
  # Sockets cannot be opened as ordinary read descriptors without connecting
  # to the service. Mount the verified canonical path only after its direct
  # no-link and full trusted-ancestor checks have passed.
  set -- --volume "${tailscale_socket_path}:/var/run/tailscale/tailscaled.sock:ro" "$@"
  set -- --volume "${tailscale_host_binary}:/usr/local/bin/tailscale:ro" "$@"
fi

# `--env NAME` copies only the retained allowlist. Drop every other inherited
# name before invoking Docker so the client cannot consume caller controls or
# expose unrelated sensitive process state to its child processes.
sanitize_docker_client_environment

"$docker_fd" run --rm -i \
  --network none \
  --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=32m \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --user 0:0 \
  --volume "$docker_socket_path:/var/run/docker.sock" \
  --volume "$docker_path:/usr/local/bin/docker:ro" \
  --volume "$compose_path:$compose_plugin_dir/docker-compose:ro" \
  --volume /volume1/my-pa:/volume1/my-pa \
  --volume /etc/my-pa:/etc/my-pa \
  --volume "$repo_root:$repo_root:ro" \
  --env MY_PA_NAS_DOCKER=/usr/local/bin/docker \
  --env DOCKER_CLI_PLUGIN_EXTRA_DIRS="$compose_plugin_dir" \
  --workdir "$repo_root" \
  --entrypoint python \
  "$@"
