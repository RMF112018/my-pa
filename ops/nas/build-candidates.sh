#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: $0 OUTPUT_DIRECTORY" >&2
  exit 64
fi

repo_root=$(git rev-parse --show-toplevel)
if [ -n "$(git -C "$repo_root" status --porcelain --untracked-files=all)" ]; then
  echo "refusing candidate build from a dirty source tree" >&2
  exit 1
fi

output_dir=$1
mkdir -p "$output_dir"
output_dir=$(CDPATH= cd -- "$output_dir" && pwd)
commit=$(git -C "$repo_root" rev-parse HEAD)
tree=$(git -C "$repo_root" rev-parse HEAD^{tree})
built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
lock_sha=$(shasum -a 256 "$repo_root/ops/docker/python-runtime.lock" | awk '{print $1}')
build_context=$(mktemp -d "${TMPDIR:-/tmp}/my-pa-nas-build.XXXXXX")
trap 'rm -rf "$build_context"' EXIT HUP INT TERM
git -C "$repo_root" archive "$commit" | tar -x -C "$build_context"

build_candidate() {
  name=$1
  dockerfile=$2
  tag="my-pa-$name:$commit"
  metadata="$output_dir/$name.metadata.json"
  archive="$output_dir/$name.tar"

  docker buildx build \
    --platform linux/amd64 \
    --file "$build_context/$dockerfile" \
    --tag "$tag" \
    --label "org.opencontainers.image.revision=$commit" \
    --label "io.my-pa.repository-tree=$tree" \
    --label "org.opencontainers.image.created=$built_at" \
    --label "io.my-pa.target-platform=linux/amd64" \
    --build-arg "SOURCE_COMMIT=$commit" \
    --build-arg "SOURCE_TREE=$tree" \
    --build-arg "BUILD_TIMESTAMP=$built_at" \
    --build-arg "PYTHON_RUNTIME_LOCK_SHA256=$lock_sha" \
    --metadata-file "$metadata" \
    --output "type=docker,dest=$archive" \
    "$build_context"
}

build_candidate app ops/docker/app.Dockerfile
build_candidate web ops/docker/web.Dockerfile

postgres_reference="postgres@sha256:dbbeb22a65db2503050cdbbe5e78f017478f10a1002a226463f049dbb017e99b"
docker buildx imagetools inspect postgres:17.10 --raw > "$output_dir/postgres.index.json"
python3 "$build_context/ops/nas/verify-postgres-index.py" "$output_dir/postgres.index.json"
docker pull --platform linux/amd64 "$postgres_reference"
docker save --output "$output_dir/postgres.tar" "$postgres_reference"
python3 "$build_context/ops/nas/write-image-metadata.py" \
  "$postgres_reference" "$output_dir/postgres.metadata.json"

python3 "$build_context/ops/nas/write-candidate-manifest.py" \
  "$output_dir" "$commit" "$tree" "$built_at" "$lock_sha"
echo "candidate archives and manifest created; they remain non-deployable until the live NAS gate passes"
