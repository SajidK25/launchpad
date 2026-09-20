#!/bin/sh
set -eu

if [ "${1:-}" = "--check" ]; then
    generated_file="packages/contracts/src/generated.ts"
    saved_file="$(mktemp)"
    trap 'rm -f "$saved_file"' EXIT
    cp "$generated_file" "$saved_file"
    docker compose -p "${COMPOSE_PROJECT_NAME:-launchpad-quality}" -f compose.checks.yaml run --rm --no-deps web-checks npm run contracts:generate
    cmp -s "$saved_file" "$generated_file"
    exit $?
fi

docker compose -p "${COMPOSE_PROJECT_NAME:-launchpad-quality}" -f compose.checks.yaml run --rm --no-deps python-checks \
    python -c 'import json; from app.main import app; print(json.dumps(app.openapi(), indent=2, sort_keys=True))' \
    > packages/contracts/openapi.json
docker compose -p "${COMPOSE_PROJECT_NAME:-launchpad-quality}" -f compose.checks.yaml run --rm --no-deps web-checks npm run contracts:generate
