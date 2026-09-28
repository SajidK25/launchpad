#!/bin/sh
set -eu

compose() {
    docker compose -p "${COMPOSE_PROJECT_NAME:-launchpad-quality}" -f compose.checks.yaml "$@"
}

run_category() {
    category="$1"
    shift
    printf '[quality] %s\n' "$category"
    if [ "${LAUNCHPAD_QUALITY_FAIL_CATEGORY:-}" = "$category" ]; then
        printf '[quality] %s failed: controlled failure\n' "$category" >&2
        return 1
    fi
    "$@"
}

only="${LAUNCHPAD_QUALITY_ONLY:-}"
if [ -n "$only" ]; then
    case "$only" in
        controlled-failure)
            run_category controlled-failure false
            ;;
        security)
            run_category security sh scripts/quality/security.sh
            ;;
        *)
            printf '[quality] unknown category: %s\n' "$only" >&2
            exit 2
            ;;
    esac
    exit $?
fi

run_category format compose run --rm --no-deps python-checks ruff format --check apps tests
run_category lint compose run --rm --no-deps python-checks ruff check apps tests
run_category types compose run --rm --no-deps python-checks mypy apps/api
run_category tests compose run --rm integration python -m pytest
run_category web-format compose run --rm --no-deps web-checks npm run format:check
run_category web-lint compose run --rm --no-deps web-checks npm run lint
run_category web-types compose run --rm --no-deps web-checks npm run typecheck
run_category web-tests compose run --rm --no-deps web-checks npm run test
run_category migrations compose run --rm prepare
run_category contracts sh scripts/quality/contracts.sh --check
run_category builds compose build python-checks web-checks web quality browser
run_category security sh scripts/quality/security.sh
run_category browser compose run --rm browser npm run test:browser
printf '[quality] graphql: generated schema and operation types covered by contracts\n'
printf '[quality] websocket: not applicable (no WebSocket feature in this foundation)\n'
