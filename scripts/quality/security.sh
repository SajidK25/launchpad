#!/bin/sh
set -eu

mode="${LAUNCHPAD_SECURITY_MODE:-scan}"
case "$mode" in
    unavailable)
        printf '[security] scanner unavailable; refusing a skipped pass\n' >&2
        exit 2
        ;;
    secret)
        printf '[security] secret finding blocks the gate\n' >&2
        exit 1
        ;;
    high)
        printf '[security] high-severity finding blocks the gate\n' >&2
        exit 1
        ;;
    low)
        printf '[security] low-severity finding recorded for review\n'
        exit 0
        ;;
    scan)
        ;;
    *)
        printf '[security] unsupported scanner mode: %s\n' "$mode" >&2
        exit 2
        ;;
esac

project="${COMPOSE_PROJECT_NAME:-launchpad-quality}"
compose() {
    docker compose -p "$project" -f compose.checks.yaml "$@"
}

# Dependency scanning is deliberately limited to production packages. The test
# runners stay pinned and are checked by the normal lockfile/build categories.
compose run --rm --no-deps web-checks npm audit --omit=dev --audit-level=high
compose run --rm --no-deps quality fs --scanners secret --exit-code 1 /workspace

# Scan the immutable web image without giving an application container the
# Docker socket. The host orchestrator owns the short-lived archive instead.
archive="$(mktemp)"
trap 'rm -f "$archive"' EXIT
image_id="$(compose images -q web)"
if [ -z "$image_id" ]; then
    printf '[security] web image is unavailable; refusing a skipped pass\n' >&2
    exit 2
fi
docker image save "$image_id" -o "$archive"
compose run --rm --no-deps -v "$archive:/image.tar:ro" quality \
    image --input /image.tar --scanners secret --exit-code 1
