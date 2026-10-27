#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: scripts/seed_demo.sh seed|cleanup|rotate-credentials [options]

Options:
  --target-id ID                  Seed target (default: local-development)
  --compose-file PATH             Compose file (default: compose.yaml)
  --credential-file PATH          Private credential manifest override
  --confirm-no-customer-data      Required for the explicitly marked VM target
  --account-key KEY               Repeat for rotate-credentials
  --                               Pass remaining arguments to the seed command
EOF
}

fail() {
  printf 'Demo seed wrapper: %s\n' "$1" >&2
  exit 2
}

command_name=${1:-}
case "$command_name" in
  seed|cleanup|rotate-credentials) shift ;;
  *) usage; exit 2 ;;
esac

target_id=${LAUNCHPAD_DEMO_TARGET_ID:-local-development}
compose_file=${LAUNCHPAD_DEMO_COMPOSE_FILE:-compose.yaml}
credential_file=${LAUNCHPAD_DEMO_CREDENTIAL_FILE:-}
confirm_no_customer_data=false
account_keys=()
forward_args=()
while (($#)); do
  case "$1" in
    --target-id)
      (($# >= 2)) || fail "--target-id requires a value"
      target_id=$2
      shift 2
      ;;
    --compose-file)
      (($# >= 2)) || fail "--compose-file requires a path"
      compose_file=$2
      shift 2
      ;;
    --credential-file)
      (($# >= 2)) || fail "--credential-file requires a path"
      credential_file=$2
      shift 2
      ;;
    --confirm-no-customer-data)
      confirm_no_customer_data=true
      shift
      ;;
    --account-key)
      (($# >= 2)) || fail "--account-key requires a value"
      account_keys+=(--account-key "$2")
      shift 2
      ;;
    --)
      shift
      forward_args+=("$@")
      break
      ;;
    *) fail "unknown wrapper option: $1" ;;
  esac
done

[[ "$target_id" =~ ^[A-Za-z0-9._-]{1,120}$ ]] || fail "target ID has unsafe characters"
[[ -f "$compose_file" ]] || fail "Compose file does not exist: $compose_file"

if [[ -z "$credential_file" ]]; then
  credential_dir=.launchpad-demo-credentials
  mkdir -p -- "$credential_dir"
  chmod 700 -- "$credential_dir"
  credential_file="$credential_dir/$target_id.json"
fi
credential_dir=$(dirname -- "$credential_file")
mkdir -p -- "$credential_dir"
chmod 700 -- "$credential_dir"

if [[ -e "$credential_file" || -L "$credential_file" ]]; then
  [[ -f "$credential_file" && ! -L "$credential_file" ]] || fail "credential path must be a regular file"
  [[ "$(stat -c '%a' -- "$credential_file")" == 600 ]] || fail "credential file must have mode 0600"
  [[ "$(stat -c '%u' -- "$credential_file")" == "$(id -u)" ]] || fail "credential file must belong to the current operator"
fi

if [[ "$command_name" == seed && ! -e "$credential_file" ]]; then
  create_credentials=true
elif [[ "$command_name" == seed ]]; then
  create_credentials=false
elif [[ "$command_name" == rotate-credentials ]]; then
  create_credentials=true
else
  create_credentials=false
fi

umask 077
capture=$(mktemp "$credential_dir/.demo-seed-output.XXXXXX")
trap 'rm -f -- "$capture"' EXIT
compose_args=(docker compose --file "$compose_file" --profile ops run --rm --interactive --no-TTY demo-seed)
operation_args=("$command_name" --target-id "$target_id")
if [[ "$confirm_no_customer_data" == true ]]; then
  operation_args+=(--confirm-no-customer-data)
fi
operation_args+=("${account_keys[@]}" "${forward_args[@]}")

set +e
if [[ "$command_name" == seed && -f "$credential_file" ]]; then
  "${compose_args[@]}" "${operation_args[@]}" <"$credential_file" >"$capture"
  status=$?
else
  "${compose_args[@]}" "${operation_args[@]}" </dev/null >"$capture"
  status=$?
fi
set -e

if [[ -s "$capture" ]]; then
  python3 -c 'import json,sys; value=json.load(sys.stdin); assert isinstance(value, dict)' <"$capture" \
    || fail "operation returned invalid credential data; secret output was retained only in a private temporary file"
  chmod 600 -- "$capture"
  if [[ "$command_name" == rotate-credentials ]]; then
    destination="$credential_dir/$target_id-rotation-$(date -u +%Y%m%dT%H%M%SZ).json"
  else
    destination=$credential_file
  fi
  if ! ln -- "$capture" "$destination"; then
    fail "credential destination already exists; no file was overwritten"
  fi
  printf 'Private credentials saved to %s (mode 0600).\n' "$destination" >&2
fi

if [[ "$create_credentials" == true && ! -s "$capture" && ! -e "$credential_file" ]]; then
  printf 'No new credentials were returned; existing account passwords remain unchanged.\n' >&2
fi
exit "$status"
