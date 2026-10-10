#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly state_dir="${LAUNCHPAD_PRODUCTION_STATE_DIR:-/srv/launchpad/state}"
readonly lock_timeout="${LAUNCHPAD_DEPLOY_LOCK_TIMEOUT_SECONDS:-60}"
readonly expected_repository="SajidK25/launchpad"
readonly state_file="$state_dir/last-deployment.json"

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
status="verified"
failure_reason=""
printf '[deploy] release manifest verified commit=%s run=%s attempt=%s\n' \
    "$commit" "$workflow_run_id" "$workflow_run_attempt"
