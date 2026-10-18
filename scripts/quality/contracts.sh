#!/bin/sh
set -eu

graphql_schema="packages/contracts/schema.graphql"
graphql_types="packages/contracts/src/graphql.generated.ts"
graphql_operations="packages/contracts/operations.graphql"

compose() {
    docker compose --progress quiet -p "${COMPOSE_PROJECT_NAME:-launchpad-quality}" -f compose.checks.yaml "$@"
}

generate_graphql_schema() {
    compose run --rm --no-deps -e LAUNCHPAD_PRODUCTS_ENABLED=true -e LAUNCHPAD_LAUNCHES_ENABLED=true -e LAUNCHPAD_REVIEW_WRITES_ENABLED=false python-checks \
        python -c 'import strawberry; from app.graphql import Query; print(strawberry.Schema(query=Query).as_str())' \
        > "$graphql_schema"
}

generate_graphql_types() {
    compose run --rm --no-deps -e LAUNCHPAD_PRODUCTS_ENABLED=true -e LAUNCHPAD_LAUNCHES_ENABLED=true -e LAUNCHPAD_REVIEW_WRITES_ENABLED=false python-checks \
        python scripts/quality/generate_graphql_types.py --schema "$graphql_schema" --operations "$graphql_operations" \
        > "$graphql_types"
}

verify_launch_disabled_graphql_schema() {
    compose run --rm --no-deps python-checks python -c 'from app.graphql import build_router; from graphql import GraphQLSchema; schema = build_router(lambda **_: {}, include_products=True, include_launches=False).schema; fields = set(schema._schema.query_type.fields); assert {"viewerProfile", "viewerProducts", "viewerNotificationInbox"} <= fields; assert not ({"viewerLaunchBookings", "viewerLaunchNotificationPreferences", "publicProduct"} & fields)'
}

generate_openapi() {
    compose run --rm --no-deps -e LAUNCHPAD_PRODUCTS_ENABLED=true -e LAUNCHPAD_LAUNCHES_ENABLED=true -e LAUNCHPAD_REVIEW_WRITES_ENABLED=false python-checks \
        python -c 'import json; from app.main import app; print(json.dumps(app.openapi(), indent=2, sort_keys=True))' \
        > packages/contracts/openapi.json
}

if [ "${1:-}" = "--check" ]; then
    generated_file="packages/contracts/src/generated.ts"
    saved_file="$(mktemp)"
    saved_schema="$(mktemp)"
    saved_graphql_types="$(mktemp)"
    restore_contracts() {
        cp "$saved_file" packages/contracts/src/generated.ts
        cp "$saved_schema" "$graphql_schema"
        cp "$saved_graphql_types" "$graphql_types"
        rm -f "$saved_file" "$saved_schema" "$saved_graphql_types"
    }
    trap restore_contracts EXIT
    cp "$generated_file" "$saved_file"
    saved_openapi="$(mktemp)"
    cp packages/contracts/openapi.json "$saved_openapi"
    restore_openapi() {
        cp "$saved_openapi" packages/contracts/openapi.json
        rm -f "$saved_openapi"
    }
    trap 'restore_contracts; restore_openapi' EXIT
    cp "$graphql_schema" "$saved_schema"
    cp "$graphql_types" "$saved_graphql_types"
    generate_openapi
    generate_graphql_schema
    generate_graphql_types
    verify_launch_disabled_graphql_schema
    compose run --rm --no-deps web-checks npm run contracts:generate
    cmp -s "$saved_openapi" packages/contracts/openapi.json && cmp -s "$saved_file" "$generated_file" && cmp -s "$saved_schema" "$graphql_schema" && cmp -s "$saved_graphql_types" "$graphql_types"
    exit $?
fi

generate_openapi
generate_graphql_schema
generate_graphql_types
verify_launch_disabled_graphql_schema
compose run --rm --no-deps web-checks npm run contracts:generate
