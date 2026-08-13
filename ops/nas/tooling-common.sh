#!/bin/sh
# Resolve the exact host tools used by NAS lifecycle commands.

: "${MY_PA_NAS_DOCKER:=docker}"
: "${MY_PA_NAS_PYTHON:=python3}"

resolve_tool() {
  value=$1
  label=$2
  case "$value" in
    /*)
      [ -x "$value" ] || {
        echo "$label executable is unavailable: $value" >&2
        return 1
      }
      printf '%s\n' "$value"
      ;;
    *)
      resolved=$(command -v "$value" 2>/dev/null) || {
        echo "$label executable is unavailable: $value" >&2
        return 1
      }
      printf '%s\n' "$resolved"
      ;;
  esac
}

NAS_DOCKER_BIN=$(resolve_tool "$MY_PA_NAS_DOCKER" "Docker")
NAS_PYTHON_BIN=$(resolve_tool "$MY_PA_NAS_PYTHON" "Python")
export MY_PA_NAS_DOCKER="$NAS_DOCKER_BIN"
export MY_PA_NAS_PYTHON="$NAS_PYTHON_BIN"

"$NAS_PYTHON_BIN" -c \
  'import sys, tomllib; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' \
  >/dev/null 2>&1 || {
    echo "NAS tooling requires Python 3.12 or newer with tomllib" >&2
    exit 1
  }

nas_docker() {
  "$NAS_DOCKER_BIN" "$@"
}

if command -v sha256sum >/dev/null 2>&1; then
  sha256_file() {
    sha256sum "$1" | awk '{print $1}'
  }
  sha256_check_receipt() {
    sha256sum --check "$1"
  }
elif command -v shasum >/dev/null 2>&1; then
  sha256_file() {
    shasum -a 256 "$1" | awk '{print $1}'
  }
  sha256_check_receipt() {
    shasum -a 256 --check "$1"
  }
else
  echo "NAS tooling requires sha256sum or shasum" >&2
  exit 1
fi
