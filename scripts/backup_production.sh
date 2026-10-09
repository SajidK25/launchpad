#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly project_name="launchpad-production"
readonly config_files=(postgres.env redis.env api.env worker.env scheduler.env migrate.env)

fail() {
    printf '[backup] %s\n' "$1" >&2
    exit 1
}

usage() {
    printf 'Usage: %s <database|media> <weekly|pre-migration>\n' "$0" >&2
    exit 2
}

[[ $# -eq 2 ]] || usage
kind="$1"
reason="$2"
[[ "$kind" == database || "$kind" == media ]] || fail "Unsupported backup kind: $kind"
[[ "$reason" == weekly || ( "$kind" == database && "$reason" == pre-migration ) ]] || usage

: "${LAUNCHPAD_BACKUP_PASSWORD_FILE:?Restic password file is required}"
: "${LAUNCHPAD_PRODUCTION_COMPOSE_FILE:?Production Compose file is required}"
: "${LAUNCHPAD_PRODUCTION_RELEASE_ENV:?Production release environment file is required}"
: "${LAUNCHPAD_PRODUCTION_STATE_DIR:?Production state directory is required}"

work_dir="${LAUNCHPAD_BACKUP_WORK_DIR:-/var/lib/launchpad/backups}"
minimum_free_bytes="${LAUNCHPAD_BACKUP_MIN_FREE_BYTES:-1073741824}"
compose=(docker compose --project-name "$project_name" --file "$LAUNCHPAD_PRODUCTION_COMPOSE_FILE" --env-file "$LAUNCHPAD_PRODUCTION_RELEASE_ENV")
password_file="$LAUNCHPAD_BACKUP_PASSWORD_FILE"
config_dir="$LAUNCHPAD_BACKUP_CONFIG_DIR"
release_manifest="$LAUNCHPAD_PRODUCTION_STATE_DIR/current-release.json"

[[ -f "$password_file" && ! -L "$password_file" ]] || fail "Restic password file is missing or unsafe."
password_mode="$(stat -c '%a' "$password_file")"
(( (8#$password_mode & 077) == 0 )) || fail "Restic password file must not be accessible by group or others."
[[ -d "$config_dir" && ! -L "$config_dir" ]] || fail "Protected runtime configuration directory is missing or unsafe."
[[ -f "$LAUNCHPAD_PRODUCTION_COMPOSE_FILE" && -f "$LAUNCHPAD_PRODUCTION_RELEASE_ENV" ]] || fail "Production Compose inputs are missing."
[[ -f "$release_manifest" && ! -L "$release_manifest" ]] || fail "Current release metadata is missing or unsafe."
[[ "$minimum_free_bytes" =~ ^[0-9]+$ ]] || fail "Backup free-space threshold must be an integer."
[[ -n "${LAUNCHPAD_BACKUP_ACCESS_KEY_ID:-}" && -n "${LAUNCHPAD_BACKUP_SECRET_ACCESS_KEY:-}" ]] || fail "Dedicated Restic backup credentials are incomplete."

identity="$(python3 - "$release_manifest" <<'PY'
import json
import re
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    manifest = json.load(source)
commit = manifest.get("commit")
schema = manifest.get("schema_revision")
if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
    raise SystemExit("invalid release commit")
if not isinstance(schema, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", schema):
    raise SystemExit("invalid schema revision")
print(f"{commit}\t{schema}")
PY
)" || fail "Current release metadata is invalid."
IFS=$'\t' read -r release_commit release_schema <<<"$identity"

mkdir -p "$work_dir"
chmod 0700 "$work_dir"
free_bytes="$(df -Pk -- "$work_dir" | awk 'NR == 2 { printf "%.0f", $4 * 1024 }')"
[[ "$free_bytes" =~ ^[0-9]+$ ]] || fail "Could not determine free space for backup."
(( free_bytes >= minimum_free_bytes )) || fail "Insufficient free space for backup."

if [[ "$kind" == media ]]; then
    : "${LAUNCHPAD_BACKUP_MEDIA_REPOSITORY:?Media backup repository is required}"
    : "${LAUNCHPAD_BACKUP_MEDIA_BUCKET:?Production media bucket is required}"
    : "${LAUNCHPAD_BACKUP_MEDIA_ENDPOINT_URL:?Production media endpoint is required}"
    : "${LAUNCHPAD_BACKUP_MEDIA_ACCESS_KEY_ID:?Read-only media access key is required}"
    : "${LAUNCHPAD_BACKUP_MEDIA_SECRET_ACCESS_KEY:?Read-only media secret is required}"
    : "${LAUNCHPAD_BACKUP_MEDIA_MAX_BYTES:?Media backup byte budget is required}"
    [[ "$LAUNCHPAD_BACKUP_MEDIA_MAX_BYTES" =~ ^[1-9][0-9]*$ ]] || fail "Media byte budget must be a positive integer."
    [[ "$LAUNCHPAD_BACKUP_MEDIA_ENDPOINT_URL" == https://* ]] || fail "Media endpoint must use HTTPS."
    [[ "$LAUNCHPAD_BACKUP_MEDIA_BUCKET" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]] || fail "Production media bucket name is invalid."
    [[ "$LAUNCHPAD_BACKUP_MEDIA_REPOSITORY" != "${LAUNCHPAD_BACKUP_DATABASE_REPOSITORY:-}" ]] || fail "Media and database backup repositories must be separate."
    [[ "$LAUNCHPAD_BACKUP_MEDIA_ACCESS_KEY_ID" != "$LAUNCHPAD_BACKUP_ACCESS_KEY_ID" && "$LAUNCHPAD_BACKUP_MEDIA_SECRET_ACCESS_KEY" != "$LAUNCHPAD_BACKUP_SECRET_ACCESS_KEY" ]] || fail "Media and Restic credentials must be separate."
    server_version="$("${compose[@]}" exec -T postgres sh -ec "psql -XAt --username=\$POSTGRES_USER --dbname=\$POSTGRES_DB --command 'SHOW server_version'")" || fail "Could not read the production PostgreSQL version."
    schema_revision="$("${compose[@]}" exec -T postgres sh -ec "psql -XAt --username=\$POSTGRES_USER --dbname=\$POSTGRES_DB --command 'SELECT version_num FROM alembic_version'")" || fail "Could not read the production schema revision."
    [[ "$server_version" =~ ^[0-9]+\.[0-9]+([.][0-9]+)?$ ]] || fail "Production PostgreSQL returned an invalid version."
    [[ "$schema_revision" =~ ^[A-Za-z0-9_.-]{1,128}$ ]] || fail "Production database must have exactly one valid Alembic revision."
    [[ "$schema_revision" == "$release_schema" ]] || fail "Current release metadata does not match the production schema revision."

    export RCLONE_CONFIG=/dev/null
    export RCLONE_CONFIG_BACKUPMEDIA_TYPE=s3
    export RCLONE_CONFIG_BACKUPMEDIA_PROVIDER=Cloudflare
    export RCLONE_CONFIG_BACKUPMEDIA_ENV_AUTH=false
    export RCLONE_CONFIG_BACKUPMEDIA_ACCESS_KEY_ID="$LAUNCHPAD_BACKUP_MEDIA_ACCESS_KEY_ID"
    export RCLONE_CONFIG_BACKUPMEDIA_SECRET_ACCESS_KEY="$LAUNCHPAD_BACKUP_MEDIA_SECRET_ACCESS_KEY"
    export RCLONE_CONFIG_BACKUPMEDIA_ENDPOINT="$LAUNCHPAD_BACKUP_MEDIA_ENDPOINT_URL"
    export RCLONE_CONFIG_BACKUPMEDIA_REGION=auto
    remote="backupmedia:$LAUNCHPAD_BACKUP_MEDIA_BUCKET"
    stage=""
    size_output=""
    reference_file=""
    command_output=""
    trap '[[ -z "$stage" ]] || rm -rf -- "$stage"; [[ -z "$size_output" ]] || rm -f -- "$size_output"; [[ -z "$reference_file" ]] || rm -f -- "$reference_file"; [[ -z "$command_output" ]] || rm -f -- "$command_output"' EXIT
    stage="$(mktemp -d "$work_dir/media.XXXXXXXX")" || fail "Could not allocate private media staging directory."
    size_output="$(mktemp "$work_dir/media-size.XXXXXXXX")" || fail "Could not allocate private media size result storage."
    reference_file="$(mktemp "$work_dir/media-references.XXXXXXXX")" || fail "Could not allocate private media reference storage."
    command_output="$(mktemp "$work_dir/media-command.XXXXXXXX")" || fail "Could not allocate private media command storage."

    if ! rclone size --json "$remote" >"$size_output" 2>"$command_output"; then fail "Could not inspect configured production media bucket."; fi
    remote_bytes="$(python3 - "$size_output" <<'PY'
import json, sys
try:
    value = json.load(open(sys.argv[1], encoding="utf-8"))["bytes"]
except (OSError, KeyError, TypeError, json.JSONDecodeError):
    raise SystemExit(1)
if not isinstance(value, int) or value < 0:
    raise SystemExit(1)
print(value)
PY
)" || fail "Production media size response was invalid."
    preflight="$(python3 - "$remote_bytes" "$LAUNCHPAD_BACKUP_MEDIA_MAX_BYTES" "$free_bytes" "$minimum_free_bytes" <<'PY'
import sys

remote_bytes, budget, free_bytes, reserve = map(int, sys.argv[1:])
if remote_bytes > budget:
    print("over-budget")
elif free_bytes < budget + reserve:
    print("no-space")
else:
    print("ready")
PY
)" || fail "Could not validate media staging limits."
    [[ "$preflight" != over-budget ]] || fail "Production media bucket exceeds the configured byte budget."
    [[ "$preflight" == ready ]] || fail "Insufficient free space for bounded media staging."

    if ! rclone copy --max-transfer "${LAUNCHPAD_BACKUP_MEDIA_MAX_BYTES}B" --cutoff-mode HARD --transfers 1 --checkers 1 --quiet "$remote" "$stage/objects" >"$command_output" 2>&1; then fail "Production media copy failed or exceeded its byte budget."; fi
    actual_bytes="$(python3 - "$stage/objects" <<'PY'
import os, sys
root = sys.argv[1]
total = 0
for current, _, files in os.walk(root):
    for name in files:
        total += os.path.getsize(os.path.join(current, name))
print(total)
PY
)" || fail "Could not measure staged production media."
    (( actual_bytes <= LAUNCHPAD_BACKUP_MEDIA_MAX_BYTES )) || fail "Staged production media exceeded the configured byte budget."
    if ! rclone check "$remote" "$stage/objects" --one-way >"$command_output" 2>&1; then fail "Production media copy did not pass verification."; fi

    if ! "${compose[@]}" exec -T postgres sh -ec "psql -XAt --username=\$POSTGRES_USER --dbname=\$POSTGRES_DB --command \"SELECT photo_key FROM profiles WHERE photo_key IS NOT NULL UNION ALL SELECT clean_key FROM product_assets WHERE state = 'clean' AND clean_key IS NOT NULL\"" >"$reference_file" 2>"$command_output"; then fail "Could not reconcile production media references."; fi
    reference_count=0
    while IFS= read -r key || [[ -n "$key" ]]; do
        [[ "$key" =~ ^profile-clean/[0-9a-f]{32}/[0-9a-f]{32}$ || "$key" =~ ^product-clean/[0-9a-f]{32}/[0-9a-f]{32}/[0-9a-f]{32}$ ]] || fail "Production database contains an invalid clean media reference."
        [[ -f "$stage/objects/$key" && ! -L "$stage/objects/$key" ]] || fail "A referenced production media object is missing from the staged copy."
        ((reference_count += 1))
    done <"$reference_file"
    python3 - "$stage/metadata.json" "$reason" "$server_version" "$schema_revision" "$release_commit" "$LAUNCHPAD_BACKUP_MEDIA_BUCKET" "$actual_bytes" "$reference_count" <<'PY'
import json
import os
import sys
from datetime import UTC, datetime

path, reason, db_version, schema, commit, bucket, byte_count, references = sys.argv[1:]
objects_dir = os.path.join(os.path.dirname(path), "objects")
object_count = sum(len(files) for _, _, files in os.walk(objects_dir))
metadata = {
    "kind": "media",
    "reason": reason,
    "database_version": db_version,
    "schema_revision": schema,
    "release_commit": commit,
    "media_bucket": bucket,
    "media_bytes": int(byte_count),
    "object_count": object_count,
    "database_reference_count": int(references),
    "created_at": datetime.now(UTC).isoformat(),
}
with open(path, "w", encoding="utf-8") as output:
    json.dump(metadata, output, sort_keys=True)
    output.write("\n")
PY
    export RESTIC_REPOSITORY="$LAUNCHPAD_BACKUP_MEDIA_REPOSITORY"
    export RESTIC_PASSWORD_FILE="$password_file"
    export AWS_ACCESS_KEY_ID="$LAUNCHPAD_BACKUP_ACCESS_KEY_ID"
    export AWS_SECRET_ACCESS_KEY="$LAUNCHPAD_BACKUP_SECRET_ACCESS_KEY"
    export AWS_DEFAULT_REGION="${LAUNCHPAD_BACKUP_REGION:-auto}"
    unset RCLONE_CONFIG_BACKUPMEDIA_ACCESS_KEY_ID RCLONE_CONFIG_BACKUPMEDIA_SECRET_ACCESS_KEY
    unset LAUNCHPAD_STORAGE_ACCESS_KEY_ID LAUNCHPAD_STORAGE_SECRET_ACCESS_KEY LAUNCHPAD_RESEND_API_KEY
    if ! restic backup --json --host launchpad-production --tag media --tag weekly --tag "schema:$schema_revision" --tag "release:$release_commit" "$stage" >"$command_output" 2>&1; then fail "Encrypted production media backup failed."; fi
    snapshot_id="$(python3 - "$command_output" <<'PY'
import json, sys
for line in open(sys.argv[1], encoding="utf-8"):
    try: event = json.loads(line)
    except json.JSONDecodeError: continue
    if event.get("message_type") == "summary" and isinstance(event.get("snapshot_id"), str):
        print(event["snapshot_id"]); break
else: raise SystemExit(1)
PY
)" || fail "Restic did not confirm a completed media snapshot."
    [[ "$snapshot_id" =~ ^[0-9a-fA-Z-]{8,64}$ ]] || fail "Restic returned an invalid media snapshot identifier."
    restic forget --group-by host --tag media --keep-within 30d --keep-last 1 --prune >"$command_output" 2>&1 || fail "Media backup succeeded, but retention could not be applied."
    printf '[backup] kind=media reason=weekly snapshot=%s objects=%s bytes=%s references=%s\n' "$snapshot_id" "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["object_count"])' "$stage/metadata.json")" "$actual_bytes" "$reference_count"
    exit 0
fi

: "${LAUNCHPAD_BACKUP_DATABASE_REPOSITORY:?Database backup repository is required}"
: "${LAUNCHPAD_BACKUP_CONFIG_DIR:?Protected runtime configuration directory is required}"
[[ -n "$LAUNCHPAD_BACKUP_DATABASE_REPOSITORY" ]] || fail "Database backup repository is required."

for file in "${config_files[@]}"; do
    [[ -f "$config_dir/$file" && ! -L "$config_dir/$file" ]] || fail "Required protected configuration is missing: $file"
    config_mode="$(stat -c '%a' "$config_dir/$file")"
    (( (8#$config_mode & 077) == 0 )) || fail "Protected configuration must not be accessible by group or others: $file"
done

server_version="$("${compose[@]}" exec -T postgres sh -ec "psql -XAt --username=\$POSTGRES_USER --dbname=\$POSTGRES_DB --command 'SHOW server_version'")" || fail "Could not read the production PostgreSQL version."
schema_revision="$("${compose[@]}" exec -T postgres sh -ec "psql -XAt --username=\$POSTGRES_USER --dbname=\$POSTGRES_DB --command 'SELECT version_num FROM alembic_version'")" || fail "Could not read the production schema revision."
[[ "$server_version" =~ ^[0-9]+\.[0-9]+([.][0-9]+)?$ ]] || fail "Production PostgreSQL returned an invalid version."
[[ "$schema_revision" =~ ^[A-Za-z0-9_.-]{1,128}$ ]] || fail "Production database must have exactly one valid Alembic revision."
[[ "$schema_revision" == "$release_schema" ]] || fail "Current release metadata does not match the production schema revision."

dump_version="$("${compose[@]}" exec -T postgres pg_dump --version)" || fail "Could not inspect the production pg_dump version."
dump_major="${dump_version##* }"
dump_major="${dump_major%%.*}"
server_major="${server_version%%.*}"
[[ "$dump_major" == "$server_major" ]] || fail "pg_dump major version does not match the PostgreSQL server."

stage="$(mktemp -d "$work_dir/database.XXXXXXXX")" || fail "Could not allocate a private backup staging directory."
cleanup() {
    rm -rf -- "$stage"
}
trap cleanup EXIT
mkdir -m 0700 "$stage/configuration"
for file in "${config_files[@]}"; do
    install -m 0600 -- "$config_dir/$file" "$stage/configuration/$file"
done
install -m 0600 -- "$LAUNCHPAD_PRODUCTION_COMPOSE_FILE" "$stage/configuration/compose.production.yaml"
install -m 0600 -- "$LAUNCHPAD_PRODUCTION_RELEASE_ENV" "$stage/configuration/release.env"

"${compose[@]}" exec -T postgres sh -ec "pg_dump --format=custom --no-owner --no-privileges --username=\$POSTGRES_USER --dbname=\$POSTGRES_DB" >"$stage/database.dump" || fail "Production database dump failed."
[[ -s "$stage/database.dump" ]] || fail "Production database dump is empty."
"${compose[@]}" exec -T postgres pg_restore --list <"$stage/database.dump" >"$stage/restore-validation.txt" || fail "Production database dump failed archive validation."
rm -f -- "$stage/restore-validation.txt"

python3 - "$stage/metadata.json" "$kind" "$reason" "$server_version" "$dump_version" "$schema_revision" "$release_commit" <<'PY'
import json
import sys
from datetime import UTC, datetime

path, kind, reason, db_version, dump_version, schema, commit = sys.argv[1:]
metadata = {
    "kind": kind,
    "reason": reason,
    "database_version": db_version,
    "pg_dump_version": dump_version.removeprefix("pg_dump (PostgreSQL) "),
    "schema_revision": schema,
    "release_commit": commit,
    "created_at": datetime.now(UTC).isoformat(),
}
with open(path, "w", encoding="utf-8") as destination:
    json.dump(metadata, destination, sort_keys=True)
    destination.write("\n")
PY

export RESTIC_REPOSITORY="$LAUNCHPAD_BACKUP_DATABASE_REPOSITORY"
export RESTIC_PASSWORD_FILE="$password_file"
export AWS_ACCESS_KEY_ID="$LAUNCHPAD_BACKUP_ACCESS_KEY_ID"
export AWS_SECRET_ACCESS_KEY="$LAUNCHPAD_BACKUP_SECRET_ACCESS_KEY"
export AWS_DEFAULT_REGION="${LAUNCHPAD_BACKUP_REGION:-auto}"
unset LAUNCHPAD_STORAGE_ACCESS_KEY_ID LAUNCHPAD_STORAGE_SECRET_ACCESS_KEY LAUNCHPAD_RESEND_API_KEY

backup_output="$(mktemp "$work_dir/restic-output.XXXXXXXX")" || fail "Could not allocate private Restic result storage."
trap 'cleanup; rm -f -- "$backup_output"' EXIT
restic backup --json --host launchpad-production \
    --tag database --tag "$reason" --tag "schema:$schema_revision" \
    --tag "release:$release_commit" "$stage" >"$backup_output" || fail "Encrypted database backup failed."
snapshot_id="$(python3 - "$backup_output" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    for line in source:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("message_type") == "summary" and isinstance(message.get("snapshot_id"), str):
            print(message["snapshot_id"])
            break
    else:
        raise SystemExit(1)
PY
)" || fail "Restic did not confirm a completed snapshot."
[[ "$snapshot_id" =~ ^[0-9a-fA-Z-]{8,64}$ ]] || fail "Restic returned an invalid snapshot identifier."

restic forget --group-by host --tag database --keep-within 30d --keep-last 1 --prune || fail "Backup succeeded, but retention could not be applied."
printf '[backup] kind=%s reason=%s snapshot=%s schema=%s\n' "$kind" "$reason" "$snapshot_id" "$schema_revision"
