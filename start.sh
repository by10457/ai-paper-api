#!/usr/bin/env sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$PROJECT_DIR"

APP_ROLE="${APP_ROLE:-auto}"
IMAGE_NAME="${IMAGE_NAME:-ai-paper-api:latest}"
ENV_FILE="${ENV_FILE:-.env}"
HOST_PORT="${HOST_PORT:-}"
CONTAINER_PORT="${CONTAINER_PORT:-}"
HOST_LOG_DIR="${HOST_LOG_DIR:-logs}"
CONTAINER_LOG_DIR="${CONTAINER_LOG_DIR:-/app/logs}"
HOST_OUTPUT_DIR="${HOST_OUTPUT_DIR:-public/output/thesis}"
CONTAINER_OUTPUT_DIR="${CONTAINER_OUTPUT_DIR:-/app/public/output/thesis}"
NETWORK_NAME="${NETWORK_NAME:-}"
BUILD_NO_CACHE="${BUILD_NO_CACHE:-false}"
ADD_HOST_GATEWAY="${ADD_HOST_GATEWAY:-true}"
RUN_AS_HOST_USER="${RUN_AS_HOST_USER:-true}"
SANITIZED_ENV_FILE=""
RESOLVED_APP_ROLE=""

log() {
  printf '[start.sh] %s\n' "$*"
}

fail() {
  printf '[start.sh][ERROR] %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<EOF
Usage:
  sh start.sh

Optional environment variables:
  IMAGE_NAME        Docker image tag (default: ai-paper-api:latest)
  APP_ROLE          Container role: auto, all, api or scheduler (default: auto)
                    auto: APP_DEBUG=true or SCHEDULER_ENABLED=false starts api only;
                    otherwise starts api+scheduler.
  CONTAINER_NAME    Docker container name (default: ai-paper-api or ai-paper-api-scheduler)
  ENV_FILE          Env file path passed to docker run (default: .env)
  HOST_PORT         Host port exposed outside Docker (default: APP_PORT in env file, fallback 10462)
  CONTAINER_PORT    Container listening port (default: APP_PORT in env file, fallback 10462)
  HOST_LOG_DIR      Host log directory to mount (default: ./logs)
  HOST_OUTPUT_DIR   Host thesis output directory to mount (default: ./public/output/thesis)
  NETWORK_NAME      Existing/new Docker network to attach (optional)
  BUILD_NO_CACHE    true/1 to disable Docker build cache (default: false)
  ADD_HOST_GATEWAY  true/1 to add host.docker.internal mapping (default: true)
  RUN_AS_HOST_USER  true/1 to run container as current host UID:GID for writable bind mounts (default: true)

Middleware connection examples:
  1. MySQL/Redis installed on host:
     set MYSQL_HOST=host.docker.internal and REDIS_HOST=host.docker.internal in ENV_FILE.
     Host Redis must also listen on the Docker bridge address. If Redis only binds 127.0.0.1,
     containers still cannot reach it.

  2. MySQL/Redis installed as Docker containers in the same network:
     set NETWORK_NAME=<network>, MYSQL_HOST=<mysql-container-or-service>, REDIS_HOST=<redis-container-or-service> in ENV_FILE.

Examples:
  sh start.sh
  ENV_FILE=.env.docker sh start.sh
  HOST_PORT=10462 CONTAINER_NAME=ai-paper-api-prod sh start.sh
  APP_ROLE=api ENV_FILE=.env.docker sh start.sh
  APP_ROLE=scheduler ENV_FILE=.env.docker sh start.sh
  NETWORK_NAME=backend sh start.sh
EOF
}

read_env_value() {
  key="$1"
  awk -v key="$key" '
    $0 ~ "^[[:space:]]*" key "[[:space:]]*=" {
      sub("^[[:space:]]*" key "[[:space:]]*=[[:space:]]*", "", $0)
      sub("[[:space:]]*#.*$", "", $0)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", $0)
      gsub(/^"|"$/, "", $0)
      print $0
    }
  ' "$ENV_FILE" | tail -n 1 | tr -d '\r'
}

is_truthy() {
  case "$1" in
    true|TRUE|True|1|yes|YES|Yes|on|ON|On) return 0 ;;
    *) return 1 ;;
  esac
}

combined_container_command() {
  cat <<'EOF'
set -eu

api_pid=""
scheduler_pid=""

# This shell is PID 1 in APP_ROLE=all mode. It keeps API and scheduler
# as one deployment unit: stop both on SIGTERM, and stop the sibling
# process when either child exits so Docker restart policy can recover.
shutdown() {
  trap - INT TERM
  kill -TERM "$api_pid" "$scheduler_pid" 2>/dev/null || true
  wait "$api_pid" 2>/dev/null || true
  wait "$scheduler_pid" 2>/dev/null || true
  exit 143
}

stop_other_process() {
  stopped_pid="$1"
  other_pid="$2"

  set +e
  wait "$stopped_pid"
  status="$?"
  set -e

  kill -TERM "$other_pid" 2>/dev/null || true
  wait "$other_pid" 2>/dev/null || true

  exit "$status"
}

trap shutdown INT TERM

# Start scheduler outside API workers. Production API workers must not
# start APScheduler in app.py, otherwise scheduled jobs run repeatedly.
python -m tasks.runner &
scheduler_pid="$!"

python main.py &
api_pid="$!"

# POSIX sh has no portable "wait -n", so poll both child processes.
while :; do
  if ! kill -0 "$api_pid" 2>/dev/null; then
    stop_other_process "$api_pid" "$scheduler_pid"
  fi

  if ! kill -0 "$scheduler_pid" 2>/dev/null; then
    stop_other_process "$scheduler_pid" "$api_pid"
  fi

  sleep 1
done
EOF
}

cleanup() {
  if [ -n "$SANITIZED_ENV_FILE" ] && [ -f "$SANITIZED_ENV_FILE" ]; then
    rm -f "$SANITIZED_ENV_FILE"
  fi
}

trap cleanup EXIT INT TERM

sanitize_env_file() {
  SANITIZED_ENV_FILE=$(mktemp "${TMPDIR:-/tmp}/ai-paper-api-env.XXXXXX")
  awk '
    /^[[:space:]]*($|#)/ { next }
    /^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*[[:space:]]*=/ {
      line = $0
      sub(/\r$/, "", line)

      key = line
      sub(/[[:space:]]*=.*/, "", key)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", key)

      value = line
      sub(/^[^=]*=/, "", value)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      if (value !~ /^["'\''"]/) {
        sub(/[[:space:]]+#.*$/, "", value)
        gsub(/[[:space:]]+$/, "", value)
      }
      if (value ~ /^".*"$/ || value ~ /^'\''.*'\''$/) {
        value = substr(value, 2, length(value) - 2)
      }

      print key "=" value
    }
  ' "$ENV_FILE" > "$SANITIZED_ENV_FILE"
}

is_loopback_host() {
  case "$1" in
    localhost|127.0.0.1|0.0.0.0) return 0 ;;
    *) return 1 ;;
  esac
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

command -v docker >/dev/null 2>&1 || fail "Docker is not installed or not in PATH."
docker info >/dev/null 2>&1 || fail "Docker daemon is not running."

case "$APP_ROLE" in
  auto|all|api|scheduler) ;;
  *) fail "Unsupported APP_ROLE=$APP_ROLE. Use auto, all, api or scheduler." ;;
esac

[ -f "$ENV_FILE" ] || fail "Env file not found: $ENV_FILE"
[ -f Dockerfile ] || fail "Dockerfile not found in $PROJECT_DIR"

sanitize_env_file

APP_DEBUG_VALUE=$(read_env_value APP_DEBUG)
SCHEDULER_ENABLED_VALUE=$(read_env_value SCHEDULER_ENABLED)
[ -n "$SCHEDULER_ENABLED_VALUE" ] || SCHEDULER_ENABLED_VALUE="true"
SCHEDULER_ENABLED="false"
if is_truthy "$SCHEDULER_ENABLED_VALUE"; then
  SCHEDULER_ENABLED="true"
fi

if [ "$APP_ROLE" = "auto" ]; then
  if is_truthy "$APP_DEBUG_VALUE" || [ "$SCHEDULER_ENABLED" != "true" ]; then
    RESOLVED_APP_ROLE="api"
  else
    RESOLVED_APP_ROLE="all"
  fi
else
  RESOLVED_APP_ROLE="$APP_ROLE"
fi

if [ "$SCHEDULER_ENABLED" != "true" ]; then
  case "$RESOLVED_APP_ROLE" in
    all)
      log "SCHEDULER_ENABLED=false, APP_ROLE=all will run api only."
      RESOLVED_APP_ROLE="api"
      ;;
    scheduler)
      fail "SCHEDULER_ENABLED=false, APP_ROLE=scheduler has no scheduler process to start."
      ;;
  esac
fi

if [ -z "${CONTAINER_NAME:-}" ]; then
  case "$RESOLVED_APP_ROLE" in
    scheduler) CONTAINER_NAME="ai-paper-api-scheduler" ;;
    *) CONTAINER_NAME="ai-paper-api" ;;
  esac
fi

log "Resolved APP_ROLE=$APP_ROLE to $RESOLVED_APP_ROLE"

APP_PORT_FROM_ENV=$(read_env_value APP_PORT)
if [ -z "$CONTAINER_PORT" ]; then
  CONTAINER_PORT="${APP_PORT_FROM_ENV:-10462}"
fi
if [ -z "$HOST_PORT" ]; then
  HOST_PORT="$CONTAINER_PORT"
fi

MYSQL_HOST_VALUE=$(read_env_value MYSQL_HOST)
REDIS_HOST_VALUE=$(read_env_value REDIS_HOST)

if is_loopback_host "$MYSQL_HOST_VALUE"; then
  log "WARNING: MYSQL_HOST=$MYSQL_HOST_VALUE points to the container itself after Docker startup."
  log "WARNING: For host MySQL, use MYSQL_HOST=host.docker.internal. For Docker MySQL, use its container/service name."
fi

if is_loopback_host "$REDIS_HOST_VALUE"; then
  log "WARNING: REDIS_HOST=$REDIS_HOST_VALUE points to the container itself after Docker startup."
  log "WARNING: For host Redis, use REDIS_HOST=host.docker.internal. For Docker Redis, use its container/service name."
  log "WARNING: Host Redis must listen on the Docker bridge address; binding only 127.0.0.1 is not reachable from containers."
fi

if [ -n "$NETWORK_NAME" ]; then
  if ! docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then
    log "Creating Docker network: $NETWORK_NAME"
    docker network create "$NETWORK_NAME" >/dev/null
  fi
fi

case "$HOST_LOG_DIR" in
  /*) HOST_LOG_PATH="$HOST_LOG_DIR" ;;
  *) HOST_LOG_PATH="$PROJECT_DIR/$HOST_LOG_DIR" ;;
esac

case "$HOST_OUTPUT_DIR" in
  /*) HOST_OUTPUT_PATH="$HOST_OUTPUT_DIR" ;;
  *) HOST_OUTPUT_PATH="$PROJECT_DIR/$HOST_OUTPUT_DIR" ;;
esac

mkdir -p "$HOST_LOG_PATH"
mkdir -p "$HOST_OUTPUT_PATH"

if docker ps -a --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"; then
  log "Removing existing container: $CONTAINER_NAME"
  docker rm -f "$CONTAINER_NAME" >/dev/null
fi

log "Building image: $IMAGE_NAME"
if [ "$BUILD_NO_CACHE" = "true" ] || [ "$BUILD_NO_CACHE" = "1" ]; then
  docker build --pull --no-cache -t "$IMAGE_NAME" .
else
  docker build --pull -t "$IMAGE_NAME" .
fi

RUN_ARGS="
  -d
  --name $CONTAINER_NAME
  --restart unless-stopped
  --env-file $SANITIZED_ENV_FILE
  -v $HOST_LOG_PATH:$CONTAINER_LOG_DIR
  -v $HOST_OUTPUT_PATH:$CONTAINER_OUTPUT_DIR
"

if [ "$RESOLVED_APP_ROLE" = "api" ] || [ "$RESOLVED_APP_ROLE" = "all" ]; then
  RUN_ARGS="$RUN_ARGS -p $HOST_PORT:$CONTAINER_PORT"
else
  RUN_ARGS="$RUN_ARGS --no-healthcheck"
fi

if [ "$RUN_AS_HOST_USER" = "true" ] || [ "$RUN_AS_HOST_USER" = "1" ]; then
  RUN_ARGS="$RUN_ARGS --user $(id -u):$(id -g)"
fi

if [ -n "$NETWORK_NAME" ]; then
  RUN_ARGS="$RUN_ARGS --network $NETWORK_NAME"
fi

if [ "$ADD_HOST_GATEWAY" = "true" ] || [ "$ADD_HOST_GATEWAY" = "1" ]; then
  RUN_ARGS="$RUN_ARGS --add-host host.docker.internal:host-gateway"
fi

log "Starting $RESOLVED_APP_ROLE container: $CONTAINER_NAME"
if [ "$RESOLVED_APP_ROLE" = "scheduler" ]; then
  # shellcheck disable=SC2086
  CONTAINER_ID=$(docker run $RUN_ARGS "$IMAGE_NAME" python -m tasks.runner)
elif [ "$RESOLVED_APP_ROLE" = "all" ]; then
  COMBINED_CONTAINER_COMMAND=$(combined_container_command)
  # shellcheck disable=SC2086
  CONTAINER_ID=$(docker run $RUN_ARGS "$IMAGE_NAME" sh -c "$COMBINED_CONTAINER_COMMAND")
else
  # shellcheck disable=SC2086
  CONTAINER_ID=$(docker run $RUN_ARGS "$IMAGE_NAME")
fi

sleep 3
RUNNING=$(docker inspect --format '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null || true)
[ "$RUNNING" = "true" ] || fail "Container failed to start. Check logs: docker logs $CONTAINER_NAME"

HEALTH=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$CONTAINER_NAME" 2>/dev/null || true)

log "Container id: $CONTAINER_ID"
if [ "$RESOLVED_APP_ROLE" = "api" ] || [ "$RESOLVED_APP_ROLE" = "all" ]; then
  log "Service URL: http://localhost:$HOST_PORT"
  log "Health endpoint: http://localhost:$HOST_PORT/api/v1/health"
fi
log "Mounted logs: $HOST_LOG_PATH -> $CONTAINER_LOG_DIR"
log "Mounted thesis output: $HOST_OUTPUT_PATH -> $CONTAINER_OUTPUT_DIR"
log "Container health: $HEALTH"
log "View logs: docker logs -f $CONTAINER_NAME"
