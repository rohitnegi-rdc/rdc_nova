#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ENV_FILE="${ENV_FILE:-.env.production}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.production.yaml}"
APP_CONTAINER="rdc-nova"
DATA_VOLUME="rdc-nova-openwebui-data"
IMAGE_RETENTION_COUNT=2
SKIP_BACKUP=false
ALLOW_DIRTY=false
APP_REPLACEMENT_STARTED=false
OLD_IMAGE_ID=""

usage() {
  cat <<'EOF'
Usage: bash deploy.sh [--skip-backup] [--allow-dirty]

Build and deploy the current Git revision using the production Compose stack.

  --skip-backup  Skip the pre-deployment PostgreSQL and data-volume backup.
  --allow-dirty  Allow deployment when tracked or untracked files are present.
  -h, --help     Show this help.
EOF
}

log() {
  printf '[deploy] %s\n' "$*"
}

fail() {
  printf '[deploy] ERROR: %s\n' "$*" >&2
  exit 1
}

for argument in "$@"; do
  case "$argument" in
    --skip-backup) SKIP_BACKUP=true ;;
    --allow-dirty) ALLOW_DIRTY=true ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown argument: $argument" ;;
  esac
done

for command_name in git docker curl awk grep flock tar; do
  command -v "$command_name" >/dev/null 2>&1 \
    || fail "Required command is unavailable: $command_name"
done

docker compose version >/dev/null 2>&1 \
  || fail "Docker Compose v2 is unavailable."

[[ -f "$ENV_FILE" ]] || fail "$ENV_FILE does not exist."
[[ -f "$COMPOSE_FILE" ]] || fail "$COMPOSE_FILE does not exist."

exec 9>"${TMPDIR:-/tmp}/rdc-tara-ops-production-deploy.lock"
flock -n 9 || fail "Another RDC Tara Ops deployment is already running."

if [[ "$ALLOW_DIRTY" != true ]] && [[ -n "$(git status --porcelain)" ]]; then
  git status --short
  fail "The checkout is not clean. Commit, stash, or inspect these changes first."
fi

REVISION="$(git rev-parse --short=12 HEAD)"
IMAGE_TAG="git-${REVISION}"
BUILD_HASH="$REVISION"

compose() {
  IMAGE_TAG="$IMAGE_TAG" BUILD_HASH="$BUILD_HASH" \
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

missing_or_placeholder_variables="$({
  awk -F= '
    /^[[:space:]]*#/ || /^[[:space:]]*$/ { next }
    /^[A-Za-z_][A-Za-z0-9_]*=/ {
      value = substr($0, index($0, "=") + 1)
      if (value == "" || value ~ /CHANGE_ME/) print $1
    }
  ' "$ENV_FILE"
} | sort -u)"

if [[ -n "$missing_or_placeholder_variables" ]]; then
  printf '%s\n' "$missing_or_placeholder_variables" >&2
  fail "The variables listed above are empty or still contain placeholders."
fi

required_variables=(
  POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD WEBUI_SECRET_KEY
  WEBUI_URL CORS_ALLOW_ORIGIN GEMINI_API_KEY RAG_GEMINI_API_KEY
  KNOWLEDGE_BASE_ID LANGCHAIN_API_KEY WEBUI_BASE_PATH ROOT_PATH
)

for variable_name in "${required_variables[@]}"; do
  if ! awk -F= -v key="$variable_name" '
    $1 == key && substr($0, index($0, "=") + 1) != "" { found = 1 }
    END { exit(found ? 0 : 1) }
  ' "$ENV_FILE"; then
    fail "Required variable $variable_name is missing or empty in $ENV_FILE."
  fi
done

read_env_value() {
  awk -F= -v key="$1" '
    $1 == key {
      value = substr($0, index($0, "=") + 1)
      sub(/\r$/, "", value)
      print value
      exit
    }
  ' "$ENV_FILE"
}

WEBUI_BASE_PATH_VALUE="$(read_env_value WEBUI_BASE_PATH)"
ROOT_PATH_VALUE="$(read_env_value ROOT_PATH)"
WEBUI_URL_VALUE="$(read_env_value WEBUI_URL)"

[[ "$WEBUI_BASE_PATH_VALUE" == /* && "$WEBUI_BASE_PATH_VALUE" != */ ]] \
  || fail "WEBUI_BASE_PATH must start with / and must not end with /."
[[ "$ROOT_PATH_VALUE" == "$WEBUI_BASE_PATH_VALUE" ]] \
  || fail "ROOT_PATH must exactly match WEBUI_BASE_PATH."
[[ "${WEBUI_URL_VALUE%/}" == *"$WEBUI_BASE_PATH_VALUE" ]] \
  || fail "WEBUI_URL must end with WEBUI_BASE_PATH."

OPEN_WEBUI_PORT_VALUE="$(awk -F= '
  $1 == "OPEN_WEBUI_PORT" { print substr($0, index($0, "=") + 1); exit }
' "$ENV_FILE")"
OPEN_WEBUI_PORT_VALUE="${OPEN_WEBUI_PORT_VALUE:-6010}"
[[ "$OPEN_WEBUI_PORT_VALUE" =~ ^[0-9]+$ ]] \
  || fail "OPEN_WEBUI_PORT must be numeric."
HEALTH_URL="http://127.0.0.1:${OPEN_WEBUI_PORT_VALUE}/health"

if docker inspect "$APP_CONTAINER" >/dev/null 2>&1; then
  OLD_IMAGE_ID="$(docker inspect --format '{{.Image}}' "$APP_CONTAINER")"
fi

health_check() {
  local attempts="${1:-36}"
  local delay_seconds="${2:-5}"
  local response

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    response="$(curl --silent --show-error --fail --max-time 5 "$HEALTH_URL" 2>/dev/null || true)"
    if grep -Eq '"status"[[:space:]]*:[[:space:]]*true' <<<"$response"; then
      return 0
    fi
    sleep "$delay_seconds"
  done
  return 1
}

frontend_base_path_check() {
  local response
  local app_url="${HEALTH_URL%/health}/"

  response="$(curl --silent --show-error --fail --max-time 10 "$app_url")"
  grep -Fq "base: \"${WEBUI_BASE_PATH_VALUE}\"" <<<"$response" \
    || fail "The frontend image was not built for ${WEBUI_BASE_PATH_VALUE}."
  grep -Fq "${WEBUI_BASE_PATH_VALUE}/_app/" <<<"$response" \
    || fail "The frontend HTML does not reference base-prefixed Svelte assets."
}

socketio_check() {
  compose exec -T open-webui python - <<'PY'
from websockets.sync.client import connect

url = 'ws://127.0.0.1:8080/ws/socket.io/?EIO=4&transport=websocket'
with connect(url, open_timeout=10, close_timeout=1) as websocket:
    payload = websocket.recv(timeout=10)
    if not isinstance(payload, str) or not payload.startswith('0') or '"sid"' not in payload:
        raise RuntimeError(f'Unexpected Socket.IO handshake: {payload!r}')
PY
}

cleanup_old_application_images() {
  local current_image_id
  local image_id
  local image_tag
  local line
  local retained_count=1
  local removed_count=0
  local -a application_images=()
  local -A retained_image_ids=()

  current_image_id="$(docker inspect --format '{{.Image}}' "$APP_CONTAINER")"
  retained_image_ids["$current_image_id"]=1

  mapfile -t application_images < <(
    docker image ls --no-trunc \
      --filter 'reference=rdc-nova:*' \
      --format '{{.ID}} {{.Repository}}:{{.Tag}}'
  )

  # Docker lists images newest first. The running image is always retained;
  # retain the newest distinct predecessor as the single rollback image.
  for line in "${application_images[@]}"; do
    image_id="${line%% *}"
    if [[ -z "${retained_image_ids[$image_id]+present}" ]] \
      && ((retained_count < IMAGE_RETENTION_COUNT)); then
      retained_image_ids["$image_id"]=1
      ((retained_count += 1))
    fi
  done

  for line in "${application_images[@]}"; do
    image_id="${line%% *}"
    image_tag="${line#* }"
    if [[ -z "${retained_image_ids[$image_id]+present}" ]]; then
      if docker image rm "$image_tag" >/dev/null; then
        ((removed_count += 1))
      else
        log "Could not remove old image tag $image_tag; it may still be used by a container"
      fi
    fi
  done

  log "Image retention complete: kept up to ${IMAGE_RETENTION_COUNT} distinct rdc-nova images and removed ${removed_count} old tag(s)"
}

rollback_on_error() {
  local exit_code=$?
  local failed_line="${BASH_LINENO[0]:-unknown}"
  trap - ERR
  set +e

  printf '[deploy] Deployment failed near line %s (exit %s).\n' "$failed_line" "$exit_code" >&2
  compose logs --tail=200 postgres open-webui >&2

  if [[ "$APP_REPLACEMENT_STARTED" == true && -n "$OLD_IMAGE_ID" ]]; then
    log "Attempting application-image rollback to $OLD_IMAGE_ID"
    docker tag "$OLD_IMAGE_ID" "rdc-nova:${IMAGE_TAG}"
    compose up -d --no-deps --force-recreate open-webui
    if health_check 24 5; then
      log "Rollback is healthy. Investigate the failed revision before retrying."
    else
      printf '[deploy] ERROR: rollback did not become healthy.\n' >&2
      compose logs --tail=200 open-webui >&2
    fi
  fi

  exit "$exit_code"
}

trap rollback_on_error ERR

log "Validating Compose configuration for revision $REVISION"
compose config --quiet

log "Starting or verifying PostgreSQL"
compose up -d postgres
for attempt in {1..30}; do
  if compose exec -T postgres sh -c \
    'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then
    break
  fi
  [[ "$attempt" -lt 30 ]] || fail "PostgreSQL did not become ready."
  sleep 2
done

log "Building rdc-nova:${IMAGE_TAG}; the existing application remains online during the build"
compose build open-webui

if [[ -n "$OLD_IMAGE_ID" ]]; then
  if [[ "$SKIP_BACKUP" != true ]]; then
    log "Stopping Open WebUI for a consistent pre-deployment backup"
    compose stop open-webui
    APP_REPLACEMENT_STARTED=true

    BACKUP_ID="rdc-nova-predeploy-$(date -u +%Y%m%d-%H%M%S)-${REVISION}"
    BACKUP_DIR="${BACKUP_ROOT:-$HOME/backups}/${BACKUP_ID}"
    mkdir -p "$BACKUP_DIR"
    chmod 700 "$BACKUP_DIR"

    log "Backing up PostgreSQL and Open WebUI data to $BACKUP_DIR"
    compose exec -T postgres sh -c \
      'pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom --no-owner --no-privileges' \
      >"$BACKUP_DIR/openwebui-postgres.dump"

    docker run --rm --user 0:0 --entrypoint sh \
      -v "${DATA_VOLUME}:/data:ro" \
      -v "${BACKUP_DIR}:/backup" \
      postgres:16-alpine \
      -c "tar -czf /backup/openwebui-data.tar.gz -C /data . && chown $(id -u):$(id -g) /backup/openwebui-data.tar.gz"

    docker run --rm \
      -v "${BACKUP_DIR}:/backup:ro" \
      postgres:16-alpine \
      pg_restore --list /backup/openwebui-postgres.dump >/dev/null
    tar -tzf "$BACKUP_DIR/openwebui-data.tar.gz" >/dev/null
    chmod 600 "$BACKUP_DIR/openwebui-postgres.dump" "$BACKUP_DIR/openwebui-data.tar.gz"
    log "Backup validation passed"
  else
    log "Pre-deployment backup and backup-only stop skipped by request"
  fi
fi

APP_REPLACEMENT_STARTED=true
log "Recreating Open WebUI with rdc-nova:${IMAGE_TAG}"
compose up -d --no-deps --force-recreate open-webui

log "Waiting for $HEALTH_URL"
health_check 36 5

log "Verifying the frontend base path is ${WEBUI_BASE_PATH_VALUE}"
frontend_base_path_check

log "Verifying the Socket.IO handshake"
socketio_check

trap - ERR
cleanup_old_application_images

compose ps
log "Deployment succeeded for revision $REVISION"
log "The active image and one previous rdc-nova image were retained for rollback."
log "If tools/main_pipe.py changed, update Tara Ops V2 through Admin Panel > Functions; Functions are stored in PostgreSQL and are not copied into the image."
