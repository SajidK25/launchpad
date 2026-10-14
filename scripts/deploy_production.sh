#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly state_dir="${LAUNCHPAD_PRODUCTION_STATE_DIR:-/srv/launchpad/state}"
readonly lock_timeout="${LAUNCHPAD_DEPLOY_LOCK_TIMEOUT_SECONDS:-60}"
readonly expected_repository="SajidK25/launchpad"
readonly state_file="$state_dir/last-deployment.json"
readonly compose_file="${LAUNCHPAD_PRODUCTION_COMPOSE_FILE:-/srv/launchpad/compose.production.yaml}"
readonly project_name="launchpad-production"

stage="waiting_for_lock"
status="failed"
failure_reason="Deployment did not complete."
commit=""
release_id=""
workflow_run_id=""
workflow_run_attempt=""
schema_revision=""
api_image=""
web_image=""
lock_acquired=0
candidate_tmp=""

fail() {
    failure_reason="$1"
    printf '[deploy] %s\n' "$1" >&2
    exit 1
}

usage() {
    printf 'Usage: %s <verified-release-manifest.json>\n' "$0" >&2
    exit 2
}

persist_attempt() {
    result=$?
    trap - EXIT
    if [[ -n "$candidate_tmp" ]]; then
        rm -f -- "$candidate_tmp"
    fi
    if (( lock_acquired )); then
        python3 - "$state_file" "$stage" "$status" "$failure_reason" "$commit" \
            "$release_id" "$workflow_run_id" "$workflow_run_attempt" "$schema_revision" \
            "$api_image" "$web_image" <<'PY' || printf '[deploy] could not persist deployment attempt state\n' >&2
import json
import os
import sys
import tempfile
from datetime import UTC, datetime

(
    state_path,
    stage,
    status,
    failure_reason,
    commit,
    release_id,
    run_id,
    run_attempt,
    schema_revision,
    api_image,
    web_image,
) = sys.argv[1:]
record = {
    "stage": stage,
    "status": status,
    "failure_reason": None if status in {"success", "verified"} else failure_reason,
    "commit": commit or None,
    "release_id": release_id or None,
    "workflow_run_id": int(run_id) if run_id else None,
    "workflow_run_attempt": int(run_attempt) if run_attempt else None,
    "schema_revision": schema_revision or None,
    "api_image": api_image or None,
    "web_image": web_image or None,
    "updated_at": datetime.now(UTC).isoformat(),
}
directory = os.path.dirname(state_path)
fd, temporary = tempfile.mkstemp(prefix=".last-deployment.", dir=directory)
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump(record, output, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, state_path)
    directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY
    fi
    exit "$result"
}

[[ $# -eq 1 ]] || usage
[[ "$lock_timeout" =~ ^[0-9]+$ ]] || fail "Deployment lock timeout must be an integer."
[[ -d "$state_dir" && ! -L "$state_dir" ]] || fail "Deployment state directory is missing or unsafe."
lock_file="$state_dir/deployment.lock"
[[ ! -L "$lock_file" ]] || fail "Deployment lock path must not be a symlink."
exec 9>>"$lock_file" || fail "Could not open deployment lock."
flock --exclusive --wait "$lock_timeout" 9 || fail "Another deployment or backup holds the shared operation lock."
lock_acquired=1
trap persist_attempt EXIT

stage="validating_manifest"
manifest_path="$1"
[[ -f "$manifest_path" && ! -L "$manifest_path" ]] || fail "Release manifest is missing or unsafe."
manifest_size="$(stat -c '%s' -- "$manifest_path")" || fail "Could not inspect release manifest."
[[ "$manifest_size" =~ ^[0-9]+$ ]] || fail "Release manifest size is invalid."
(( manifest_size > 0 && manifest_size <= 65536 )) || fail "Release manifest size is invalid."

identity="$(python3 - "$manifest_path" "$expected_repository" <<'PY'
import json
import re
import sys

repository = sys.argv[2]
commit_pattern = re.compile(r"[0-9a-f]{40}\Z")
digest_pattern = re.compile(r"sha256:[0-9a-f]{64}\Z")
schema_pattern = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")

def invalid() -> None:
    raise SystemExit(1)

def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            invalid()
        result[key] = value
    return result

def require_keys(value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        invalid()
    return value

try:
    with open(sys.argv[1], encoding="utf-8") as source:
        manifest = json.load(source, object_pairs_hook=unique_object)
except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
    invalid()

manifest = require_keys(
    manifest,
    {
        "manifest_version",
        "repository",
        "commit",
        "release_id",
        "platform",
        "schema_revision",
        "workflow",
        "verification",
        "images",
    },
)
if type(manifest["manifest_version"]) is not int or manifest["manifest_version"] != 1:
    invalid()
if manifest["repository"] != repository:
    invalid()
commit = manifest["commit"]
schema = manifest["schema_revision"]
if not isinstance(commit, str) or not commit_pattern.fullmatch(commit):
    invalid()
if not isinstance(schema, str) or not schema_pattern.fullmatch(schema):
    invalid()
if manifest["platform"] != "linux/amd64":
    invalid()

workflow = require_keys(
    manifest["workflow"],
    {
        "repository",
        "run_id",
        "run_attempt",
        "event",
        "ref",
        "head_sha",
        "conclusion",
    },
)
run_id = workflow["run_id"]
run_attempt = workflow["run_attempt"]
if workflow["repository"] != repository or workflow["head_sha"] != commit:
    invalid()
if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
    invalid()
if isinstance(run_attempt, bool) or not isinstance(run_attempt, int) or run_attempt <= 0:
    invalid()
if not isinstance(workflow["event"], str) or workflow["event"] not in {
    "push",
    "workflow_dispatch",
}:
    invalid()
if workflow["ref"] != "refs/heads/main" or workflow["conclusion"] != "success":
    invalid()

release_id = f"{run_id}-{run_attempt}-{commit}"
if manifest["release_id"] != release_id:
    invalid()
verification = require_keys(manifest["verification"], {"quality", "images"})
if verification != {"quality": "success", "images": "success"}:
    invalid()
images = require_keys(manifest["images"], {"api", "web"})
image_refs: list[str] = []
for name, package in (
    ("api", "ghcr.io/sajidk25/launchpad-api"),
    ("web", "ghcr.io/sajidk25/launchpad-web"),
):
    image = require_keys(
        images[name], {"package", "digest", "commit", "schema_revision", "platform"}
    )
    if image["package"] != package:
        invalid()
    digest = image["digest"]
    if not isinstance(digest, str) or not digest_pattern.fullmatch(digest):
        invalid()
    if image["commit"] != commit or image["schema_revision"] != schema:
        invalid()
    if image["platform"] != manifest["platform"]:
        invalid()
    image_refs.append(f"{package}@{digest}")

print("\t".join((commit, str(run_id), str(run_attempt), release_id, schema, *image_refs)))
PY
)" || fail "Release manifest failed validation."
IFS=$'\t' read -r commit workflow_run_id workflow_run_attempt release_id schema_revision api_image web_image <<<"$identity"
stage="verified"
failure_reason=""
printf '[deploy] release manifest verified commit=%s run=%s attempt=%s\n' \
    "$commit" "$workflow_run_id" "$workflow_run_attempt"

health_timeout="${LAUNCHPAD_DEPLOY_HEALTH_TIMEOUT_SECONDS:-180}"
dependency_timeout="${LAUNCHPAD_DEPLOY_DEPENDENCY_TIMEOUT_SECONDS:-120}"
[[ "$health_timeout" =~ ^[0-9]+$ && "$health_timeout" -gt 0 ]] || fail "Health timeout must be a positive integer."
[[ "$dependency_timeout" =~ ^[0-9]+$ && "$dependency_timeout" -gt 0 ]] || fail "Dependency timeout must be a positive integer."
[[ -f "$compose_file" && ! -L "$compose_file" ]] || fail "Production Compose file is missing or unsafe."

compose_base=(docker compose --project-name "$project_name" --file "$compose_file")
web_port="${LAUNCHPAD_WEB_PORT:-18080}"
[[ "$web_port" =~ ^[0-9]+$ && "$web_port" -ge 1024 && "$web_port" -le 65535 ]] || fail "Production web port is invalid."
candidate_tmp="$(mktemp "${TMPDIR:-/tmp}/launchpad-release.XXXXXX")" || fail "Could not prepare temporary release configuration."
printf 'LAUNCHPAD_API_DIGEST=%s\nLAUNCHPAD_WEB_DIGEST=%s\nLAUNCHPAD_STATE_DIR=%s\nLAUNCHPAD_WEB_PORT=%s\n' \
    "${api_image##*@}" "${web_image##*@}" "$state_dir" "$web_port" >"$candidate_tmp" || fail "Could not prepare release configuration."
chmod 0600 "$candidate_tmp" || fail "Could not protect release configuration."
compose=("${compose_base[@]}" --env-file "$candidate_tmp" --profile ops)
previous_env="${LAUNCHPAD_PRODUCTION_RELEASE_ENV:-$state_dir/current-release.env}"
previous_json="$state_dir/current-release.json"
previous_available=0
previous_commit=""
previous_schema=""
previous_api=""
previous_web=""
if [[ -f "$previous_json" && -f "$previous_env" ]]; then
    previous_identity="$(python3 - "$previous_json" <<'PY'
import json, re, sys
try:
    value = json.load(open(sys.argv[1], encoding="utf-8"))
    commit, schema, api, web = (value[k] for k in ("commit", "schema_revision", "api_image", "web_image"))
    if not re.fullmatch(r"[0-9a-f]{40}", commit): raise ValueError
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", schema): raise ValueError
    for name, package in ((api, "ghcr.io/sajidk25/launchpad-api"), (web, "ghcr.io/sajidk25/launchpad-web")):
        if not isinstance(name, str) or not re.fullmatch(re.escape(package) + r"@sha256:[0-9a-f]{64}", name): raise ValueError
    print("\t".join((commit, schema, api, web)))
except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
    raise SystemExit(1)
PY
)" || fail "Previous release state is invalid."
    IFS=$'\t' read -r previous_commit previous_schema previous_api previous_web <<<"$previous_identity"
    previous_available=1
elif [[ -e "$previous_json" || -e "$previous_env" ]]; then
    fail "Previous release state is incomplete."
fi

stage="preflight"
"${compose[@]}" config --quiet || fail "Production Compose configuration failed preflight."
for volume_spec in "launchpad-production-postgres:postgres_data" "launchpad-production-redis:redis_data"; do
    volume_name="${volume_spec%%:*}"
    logical_name="${volume_spec#*:}"
    if volume_labels="$(docker volume inspect --format '{{ index .Labels "com.docker.compose.project" }}|{{ index .Labels "com.docker.compose.volume" }}' "$volume_name" 2>/dev/null)"; then
        [[ "$volume_labels" == "$project_name|$logical_name" ]] || fail "A production volume name is owned by another Compose project."
    else
        existing_volume="$(docker volume ls --filter "name=^${volume_name}$" --format '{{.Name}}')" || fail "Could not inspect production volumes."
        [[ -z "$existing_volume" ]] || fail "An existing production volume could not be verified safely."
    fi
done
for network_spec in "${project_name}_ingress:ingress" "${project_name}_backend:backend"; do
    network_name="${network_spec%%:*}"
    logical_name="${network_spec#*:}"
    if network_labels="$(docker network inspect --format '{{ index .Labels "com.docker.compose.project" }}|{{ index .Labels "com.docker.compose.network" }}' "$network_name" 2>/dev/null)"; then
        [[ "$network_labels" == "$project_name|$logical_name" ]] || fail "A production network name is owned by another Compose project."
    else
        existing_network="$(docker network ls --filter "name=^${network_name}$" --format '{{.Name}}')" || fail "Could not inspect production networks."
        [[ -z "$existing_network" ]] || fail "An existing production network could not be verified safely."
    fi
done
existing_services="$(docker ps --all --filter "label=com.docker.compose.project=$project_name" --format '{{.Label "com.docker.compose.service"}}')" || fail "Could not inspect production project containers."
while IFS= read -r service_name; do
    [[ -z "$service_name" ]] && continue
    case "$service_name" in
        postgres|redis|web|api|worker|scheduler|migrate) ;;
        *) fail "Production Compose project name is already used by an unknown service." ;;
    esac
done <<<"$existing_services"
listeners="$(ss -Hln "sport = :$web_port")" || fail "Could not check production web port availability."
if [[ -n "$listeners" ]]; then
    owned_ports="$(docker ps --filter "label=com.docker.compose.project=$project_name" --filter "label=com.docker.compose.service=web" --format '{{.Ports}}')" || fail "Could not inspect the existing production web service."
    case "$owned_ports" in
        *"127.0.0.1:$web_port->"*) ;;
        *) fail "Production web port is already occupied by another service." ;;
    esac
fi

release_dir="$state_dir/releases"
mkdir -p -- "$release_dir" || fail "Could not prepare release state."
chmod 0700 -- "$release_dir" || fail "Could not protect release configuration."
candidate_env="$release_dir/$commit.env"
mv -f -- "$candidate_tmp" "$candidate_env" || fail "Could not persist release configuration."
candidate_tmp=""
compose=("${compose_base[@]}" --env-file "$candidate_env" --profile ops)

stage="pulling_images"
"${compose[@]}" pull postgres redis web api worker scheduler migrate || fail "Could not pull verified release images."
"${compose[@]}" up --detach --wait --wait-timeout "$dependency_timeout" postgres redis || fail "Production dependencies did not become healthy."

# shellcheck disable=SC2016
schema_state="$("${compose[@]}" exec --no-TTY postgres sh -ec 'psql -X -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT to_regclass('\''public.alembic_version'\'')"')" || fail "Could not inspect database schema."
schema_state="${schema_state//[$'\r\n ']/}"
database_has_schema=0
database_schema=""
if [[ -n "$schema_state" ]]; then
    database_has_schema=1
    # shellcheck disable=SC2016
    database_schema="$("${compose[@]}" exec --no-TTY postgres sh -ec 'psql -X -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version_num FROM public.alembic_version LIMIT 1"')" || fail "Could not inspect database revision."
    database_schema="${database_schema//$'\r'/}"
    database_schema="${database_schema//$'\n'/}"
fi
if (( previous_available )); then
    (( database_has_schema )) || fail "Database schema is missing despite an active release."
    [[ "$database_schema" == "$previous_schema" ]] || fail "Database schema does not match the active release; refusing deployment."
elif (( database_has_schema )); then
    fail "Database already has a schema but no previous release is recorded; refusing deployment."
fi

if (( database_has_schema )); then
    stage="backing_up"
    backup_env_file="${LAUNCHPAD_BACKUP_DATABASE_ENV_FILE:-/etc/launchpad/backup-database.env}"
    backup_script="${LAUNCHPAD_BACKUP_SCRIPT:-/srv/launchpad/bin/backup_production.sh}"
    [[ -f "$backup_env_file" && ! -L "$backup_env_file" && -x "$backup_script" && ! -L "$backup_script" ]] || fail "Pre-migration backup configuration is unavailable."
    backup_assignments="$(python3 - "$backup_env_file" <<'PY'
import os, re, sys
allowed = {"LAUNCHPAD_BACKUP_DATABASE_REPOSITORY", "LAUNCHPAD_BACKUP_PASSWORD_FILE", "LAUNCHPAD_BACKUP_ACCESS_KEY_ID", "LAUNCHPAD_BACKUP_SECRET_ACCESS_KEY", "LAUNCHPAD_BACKUP_CONFIG_DIR", "LAUNCHPAD_BACKUP_WORK_DIR", "LAUNCHPAD_BACKUP_MIN_FREE_BYTES", "LAUNCHPAD_BACKUP_REGION", "LAUNCHPAD_PRODUCTION_COMPOSE_FILE", "LAUNCHPAD_PRODUCTION_RELEASE_ENV", "LAUNCHPAD_PRODUCTION_STATE_DIR"}
path = sys.argv[1]
if os.stat(path).st_mode & 0o077: raise SystemExit(1)
seen = set()
try:
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if not line or line.startswith("#"): continue
        key, sep, value = line.partition("=")
        if not sep or key not in allowed or key in seen or not value or "\x00" in value: raise SystemExit(1)
        seen.add(key)
        print(f"{key}={value}")
except (OSError, UnicodeError): raise SystemExit(1)
if not {"LAUNCHPAD_BACKUP_DATABASE_REPOSITORY", "LAUNCHPAD_BACKUP_PASSWORD_FILE"} <= seen: raise SystemExit(1)
PY
)" || fail "Pre-migration backup configuration is invalid."
    # shellcheck disable=SC2163
    while IFS= read -r assignment; do export "$assignment"; done <<<"$backup_assignments"
    export LAUNCHPAD_PRODUCTION_COMPOSE_FILE="$compose_file" LAUNCHPAD_PRODUCTION_RELEASE_ENV="$previous_env" LAUNCHPAD_PRODUCTION_STATE_DIR="$state_dir"
    "$backup_script" database pre-migration || fail "Pre-migration backup failed; writers remain active."
fi

stage="maintenance"
chmod 0711 -- "$state_dir" || fail "Could not set safe maintenance-state traversal permissions."
maintenance_tmp="$state_dir/.maintenance.$$"
printf 'release=%s\nstarted_at=%s\n' "$release_id" "$(date -u +%FT%TZ)" >"$maintenance_tmp" || fail "Could not create maintenance marker."
chmod 0644 "$maintenance_tmp" || fail "Could not protect maintenance state."
mv -f -- "$maintenance_tmp" "$state_dir/maintenance" || fail "Could not activate maintenance mode."
rollback_or_leave() {
    reason="$1"
    failure_reason="$reason"
    actual=""
    if (( database_has_schema )); then
        # shellcheck disable=SC2016
        actual="$("${compose[@]}" exec --no-TTY postgres sh -ec 'psql -X -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version_num FROM public.alembic_version LIMIT 1"' 2>/dev/null)" || actual="unknown"
        actual="${actual//$'\r'/}"
        actual="${actual//$'\n'/}"
    else
        actual="empty"
    fi
    if (( previous_available )) && [[ "$actual" == "$database_schema" ]]; then
        stage="restoring_previous_images"
        restore_env="$release_dir/$previous_commit.env"
        printf 'LAUNCHPAD_API_DIGEST=%s\nLAUNCHPAD_WEB_DIGEST=%s\nLAUNCHPAD_STATE_DIR=%s\nLAUNCHPAD_WEB_PORT=%s\n' \
            "${previous_api##*@}" "${previous_web##*@}" "$state_dir" "${LAUNCHPAD_WEB_PORT:-18080}" >"$restore_env.tmp.$$" || return 1
        chmod 0600 "$restore_env.tmp.$$" && mv -f -- "$restore_env.tmp.$$" "$restore_env" || return 1
        restore=("${compose_base[@]}" --env-file "$restore_env" --profile ops)
        "${restore[@]}" up --detach --wait --wait-timeout "$health_timeout" web api worker scheduler || return 1
        "${restore[@]}" exec --no-TTY worker python apps/worker/worker.py --health || return 1
        "${restore[@]}" exec --no-TTY scheduler python apps/worker/scheduler.py --health || return 1
        if readiness_checks "$health_timeout"; then
            rm -f -- "$state_dir/maintenance"
            stage="rolled_back"
            return 0
        fi
    fi
    "${compose[@]}" stop api worker scheduler >/dev/null 2>&1 || true
    stage="maintenance_recovery_required"
    return 1
}
readiness_checks() {
    timeout_seconds="$1"
    deadline=$((SECONDS + timeout_seconds))
    local_url="${LAUNCHPAD_DEPLOY_LOCAL_HEALTH_URL:-http://127.0.0.1:18080/api/v1/health/ready}"
    public_url="${LAUNCHPAD_DEPLOY_PUBLIC_HEALTH_URL:-https://launchpad.t99ltd.com/api/v1/health/ready}"
    local_ready=0
    public_ready=0
    while (( ! local_ready || ! public_ready )); do
        had_failure=0
        for url in "$local_url" "$public_url"; do
            if [[ "$url" == "$local_url" && "$local_ready" -eq 1 ]] || [[ "$url" == "$public_url" && "$public_ready" -eq 1 ]]; then
                continue
            fi
            remaining=$((deadline - SECONDS))
            (( remaining > 0 )) || return 1
            request_timeout=5
            (( remaining < request_timeout )) && request_timeout="$remaining"
            if curl --fail --silent --show-error --max-time "$request_timeout" "$url" >/dev/null; then
                if [[ "$url" == "$local_url" ]]; then
                    local_ready=1
                else
                    public_ready=1
                fi
            else
                had_failure=1
            fi
        done
        (( local_ready && public_ready )) && return 0
        (( had_failure )) || continue
        remaining=$((deadline - SECONDS))
        (( remaining > 0 )) || return 1
        sleep_seconds=1
        (( remaining < sleep_seconds )) && sleep_seconds="$remaining"
        sleep "$sleep_seconds"
    done
}

stage="stopping_writers"
"${compose[@]}" stop api worker scheduler || { rollback_or_leave "Could not stop application writers." || true; fail "$failure_reason"; }
stage="migrating"
if ! "${compose[@]}" run --rm --no-deps migrate; then
    rollback_or_leave "Database migration failed."
    fail "$failure_reason"
fi
stage="starting_services"
if ! "${compose[@]}" up --detach --wait --wait-timeout "$health_timeout" web api worker scheduler; then
    rollback_or_leave "New release services failed to become healthy."
    fail "$failure_reason"
fi
if ! "${compose[@]}" exec --no-TTY worker python apps/worker/worker.py --health; then
    rollback_or_leave "Fresh worker health check failed."
    fail "$failure_reason"
fi
if ! "${compose[@]}" exec --no-TTY scheduler python apps/worker/scheduler.py --health; then
    rollback_or_leave "Fresh scheduler health check failed."
    fail "$failure_reason"
fi
actual_schema=""
# shellcheck disable=SC2016
post_migration_table="$("${compose[@]}" exec --no-TTY postgres sh -ec 'psql -X -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT to_regclass('\''public.alembic_version'\'')"')" || { rollback_or_leave "Could not verify migrated schema."; fail "$failure_reason"; }
post_migration_table="${post_migration_table//[$'\r\n ']/}"
if [[ -n "$post_migration_table" ]]; then
    # shellcheck disable=SC2016
    actual_schema="$("${compose[@]}" exec --no-TTY postgres sh -ec 'psql -X -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version_num FROM public.alembic_version LIMIT 1"')" || { rollback_or_leave "Could not verify migrated schema."; fail "$failure_reason"; }
    actual_schema="${actual_schema//$'\r'/}"
    actual_schema="${actual_schema//$'\n'/}"
fi
[[ "$actual_schema" == "$schema_revision" ]] || { rollback_or_leave "Database schema differs from the verified release; maintenance remains active."; fail "$failure_reason"; }
stage="checking_readiness"
if ! readiness_checks "$health_timeout"; then
    rollback_or_leave "Local or public readiness check failed before the deadline."
    fail "$failure_reason"
fi
stage="persisting_release"
python3 - "$state_dir" "$commit" "$schema_revision" "$api_image" "$web_image" "$release_id" "$previous_commit" "$previous_schema" "$previous_api" "$previous_web" <<'PY' || fail "Could not persist successful release state."
import json, os, sys, tempfile
from datetime import UTC, datetime
state, commit, schema, api, web, release_id, previous, previous_schema, previous_api, previous_web = sys.argv[1:]
records = {
    "current-release.json": {"commit": commit, "schema_revision": schema, "api_image": api, "web_image": web, "release_id": release_id, "updated_at": datetime.now(UTC).isoformat()},
    "current-release.env": None,
    "previous-release.json": {"commit": previous or None, "schema_revision": previous_schema or None, "api_image": previous_api or None, "web_image": previous_web or None},
}
for name, value in records.items():
    if value is None:
        content = f"LAUNCHPAD_API_DIGEST={api.split('@', 1)[1]}\nLAUNCHPAD_WEB_DIGEST={web.split('@', 1)[1]}\nLAUNCHPAD_STATE_DIR={state}\nLAUNCHPAD_WEB_PORT={os.environ.get('LAUNCHPAD_WEB_PORT', '18080')}\n"
    else:
        content = json.dumps(value, sort_keys=True) + "\n"
    fd, temp = tempfile.mkstemp(prefix=f".{name}.", dir=state)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(content); output.flush(); os.fsync(output.fileno())
        os.replace(temp, os.path.join(state, name))
    finally:
        if os.path.exists(temp): os.unlink(temp)
PY
rm -f -- "$state_dir/maintenance"
stage="healthy"
status="success"
failure_reason=""
printf '[deploy] release healthy commit=%s schema=%s\n' "$commit" "$schema_revision"
