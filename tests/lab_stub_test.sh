#!/usr/bin/env bash
set -eu

cd "$(dirname "$0")/.."

bash -n ./lab
bash -n infra/postgres/init.sh

helper="$(awk '/^py\(\)/,/^}/' ./lab)"
if ! printf '%s\n' "$helper" | grep -Fq '[[ -x "$ROOT/.venv/bin/python" ]]'; then
  echo 'py helper does not prefer an executable .venv python' >&2
  exit 1
fi
if ! printf '%s\n' "$helper" | grep -Fq '"$ROOT/.venv/bin/python" "$@"'; then
  echo 'py helper does not run .venv python' >&2
  exit 1
fi
doctor_body="$(awk '/^cmd_doctor\(\)/,/^}/' ./lab)"
if ! printf '%s\n' "$doctor_body" | grep -Fq 'py -m iam_playground.doctor'; then
  echo 'doctor does not use the py helper' >&2
  exit 1
fi
if printf '%s\n' "$doctor_body" | grep -Fq 'python3 -m iam_playground.doctor'; then
  echo 'doctor still calls python3 directly' >&2
  exit 1
fi

set +e
output="$(./lab doctor 2>&1)"
status=$?
set -e

if [[ "$status" -ne 1 ]]; then
  printf 'expected doctor exit 1 when the stack is down, got %s\n' "$status" >&2
  printf '%s\n' "$output" >&2
  exit 1
fi

if ! printf '%s\n' "$output" | grep -Eq 'postgres|keycloak|target|admin|workbench'; then
  echo 'doctor did not name a failed dependency' >&2
  printf '%s\n' "$output" >&2
  exit 1
fi

set +e
jdbc_output="$(./lab jdbc verify 2>&1)"
jdbc_status=$?
set -e

if [[ "$jdbc_status" -ne 0 ]]; then
  printf 'expected jdbc verify exit 0, got %s\n' "$jdbc_status" >&2
  printf '%s\n' "$jdbc_output" >&2
  exit 1
fi

if ! printf '%s\n' "$jdbc_output" | grep -q 'The JDBC client is implemented.'; then
  echo 'jdbc verify did not say the client is implemented' >&2
  exit 1
fi

if ! printf '%s\n' "$jdbc_output" | grep -q 'does not open a database'; then
  echo 'jdbc verify did not say it skips the database' >&2
  exit 1
fi

if printf '%s\n' "$jdbc_output" | grep -qi 'connected'; then
  echo 'jdbc verify pretended a connection succeeded' >&2
  exit 1
fi

set +e
list_output="$(./lab scenario list 2>&1)"
list_status=$?
set -e
if [[ "$list_status" -ne 0 ]]; then
  printf 'expected scenario list exit 0, got %s\n' "$list_status" >&2
  printf '%s\n' "$list_output" >&2
  exit 1
fi
if ! printf '%s\n' "$list_output" | grep -qx 'scim-login-revoke'; then
  echo 'scenario list did not name scim-login-revoke' >&2
  exit 1
fi
for scenario in authorization-failure joiner leaver mover-engineering-to-sales orphan partial-failure rehire rename retry-ambiguity; do
  if ! printf '%s\n' "$list_output" | grep -qx "$scenario"; then
    printf 'scenario list did not name %s\n' "$scenario" >&2
    exit 1
  fi
done
if ! printf '%s\n' "$list_output" | grep -qx 'transaction-rollback is unavailable'; then
  echo 'scenario list did not mark transaction-rollback unavailable' >&2
  exit 1
fi
if printf '%s\n' "$list_output" | grep -qx 'transaction-rollback'; then
  echo 'transaction-rollback was listed as available' >&2
  exit 1
fi

set +e
external_output="$(./lab scenario run scim-login-revoke --mode external 2>&1)"
external_status=$?
set -e
if [[ "$external_status" -ne 2 ]]; then
  printf 'expected external mode exit 2, got %s\n' "$external_status" >&2
  exit 1
fi
if ! printf '%s\n' "$external_output" | grep -q 'unavailable'; then
  echo 'external mode did not say unavailable' >&2
  exit 1
fi
if printf '%s\n' "$external_output" | grep -q 'PASSED'; then
  echo 'external mode printed PASSED' >&2
  exit 1
fi

set +e
reset_output="$(./lab reset --fixture other-fixture 2>&1)"
reset_status=$?
set -e
if [[ "$reset_status" -ne 2 ]]; then
  printf 'expected unknown fixture exit 2, got %s\n' "$reset_status" >&2
  exit 1
fi
if ! printf '%s\n' "$reset_output" | grep -q 'not in this checkpoint'; then
  echo 'unknown fixture was not rejected' >&2
  exit 1
fi
