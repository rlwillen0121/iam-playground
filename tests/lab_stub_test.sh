#!/usr/bin/env bash
set -eu

cd "$(dirname "$0")/.."

set +e
output="$(./lab doctor 2>&1)"
status=$?
set -e

if [[ "$status" -ne 2 ]]; then
  printf 'expected exit 2, got %s\n' "$status" >&2
  exit 1
fi

if ! printf '%s\n' "$output" | grep -q 'planned'; then
  echo 'output does not contain planned' >&2
  exit 1
fi

if printf '%s\n' "$output" | grep -q 'ready'; then
  echo 'output contains a success claim (ready)' >&2
  exit 1
fi
