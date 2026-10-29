#!/usr/bin/env bash
# Deploy Sherlock to a Nebius Serverless Endpoint.
#
#   ./scripts/deploy.sh setup   first time: registry, /data filesystem, LLM key secret,
#                               build + push, create the endpoint, print its URL
#   ./scripts/deploy.sh         redeploy: build, push the same tag, restart the endpoint
#   ./scripts/deploy.sh check   the /data exit check: restart and compare /healthz and /me
#   ./scripts/deploy.sh url     print the endpoint's public URL
#
# Needs bash, docker, jq, curl and the nebius CLI with a profile whose parent is the
# project (docs.nebius.com/cli/install). Run from the repo root on Linux, macOS or WSL.
# Endpoint settings are immutable: changing env vars, preset or volume means deleting
# and recreating the endpoint, which changes its URL. Redeploys keep the URL because
# they reuse the image tag.
set -euo pipefail

REGION="${NEBIUS_REGION:-eu-north1}"
NAME="${SHERLOCK_ENDPOINT_NAME:-sherlock}"
TAG="${SHERLOCK_IMAGE_TAG:-prod}"
PLATFORM="${SHERLOCK_PLATFORM:-cpu-d3}"
PRESET="${SHERLOCK_PRESET:-4vcpu-16gb}"
DISK="${SHERLOCK_DISK:-40Gi}"
FS_GIB="${SHERLOCK_FS_GIB:-50}"
SECRET_NAME="${SHERLOCK_SECRET_NAME:-sherlock-llm}"
STATE_FILE="scripts/.deploy-state"   # registry path and filesystem id; git-ignored
ENV_FILE=".env"

die() { echo "deploy: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null || die "missing '$1'"; }
for tool in docker jq curl nebius; do need "$tool"; done
[ -f api/Dockerfile ] || die "run from the repo root"

load_state() { [ -f "$STATE_FILE" ] && . "$STATE_FILE"; true; }
save_state() { printf 'REGISTRY_PATH=%s\nFS_ID=%s\n' "${REGISTRY_PATH:-}" "${FS_ID:-}" > "$STATE_FILE"; }

# Read one KEY=value from .env without echoing it.
env_value() { grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2-; }

image() { echo "cr.$REGION.nebius.cloud/$REGISTRY_PATH/sherlock:$TAG"; }

endpoint_id() {
  nebius ai endpoint get-by-name --name "$NAME" --format jsonpath='{.metadata.id}' 2>/dev/null || true
}

endpoint_url() {
  nebius ai endpoint get "$(endpoint_id)" --format json \
    | jq -r '.status.public_endpoints[] | select(startswith("https://"))' | head -1
}

wait_healthy() {
  local url="$1"
  for _ in $(seq 1 90); do
    if curl -sf "$url/healthz" >/dev/null; then return 0; fi
    sleep 10
  done
  die "$url/healthz did not answer within 15 minutes"
}

build_and_push() {
  load_state
  [ -n "${REGISTRY_PATH:-}" ] || die "no registry yet; run './scripts/deploy.sh setup'"
  nebius iam get-access-token | docker login "cr.$REGION.nebius.cloud" --username iam --password-stdin
  docker build --platform linux/amd64 -f api/Dockerfile -t "$(image)" .
  docker push "$(image)"
}

setup() {
  [ -f "$ENV_FILE" ] || die "no .env (copy .env.example and fill it in)"
  load_state
  if [ -z "${REGISTRY_PATH:-}" ]; then
    REGISTRY_PATH=$(nebius registry create --name sherlock --format json | jq -r '.metadata.id' | cut -d- -f2)
    save_state
  fi
  if [ -z "${FS_ID:-}" ]; then
    FS_ID=$(nebius compute filesystem create --name sherlock-data --type network_ssd \
      --size-gibibytes "$FS_GIB" --format json | jq -r '.metadata.id')
    save_state
  fi
  if ! nebius mysterybox secret list --format json | jq -e --arg n "$SECRET_NAME" \
      '.items[]? | select(.metadata.name == $n)' >/dev/null; then
    local key; key=$(env_value LLM_API_KEY)
    [ -n "$key" ] || die "LLM_API_KEY is empty in .env"
    nebius mysterybox secret create --name "$SECRET_NAME" \
      --description "Sherlock: Token Factory key" \
      --secret-version-payload "$(jq -n --arg v "$key" '[{key: "LLM_API_KEY", string_value: $v}]')" \
      >/dev/null
  fi

  build_and_push

  [ -z "$(endpoint_id)" ] || die "endpoint '$NAME' already exists; use './scripts/deploy.sh' to redeploy"
  local envs=()
  for var in LLM_BASE_URL MODEL_LARGE MODEL_MEDIUM MODEL_SMALL MODEL_EMBED NVIDIA_EMBED_MODELS LLM_TOOLS_MODE; do
    envs+=(--env "$var=$(env_value "$var")")
  done
  nebius ai endpoint create \
    --name "$NAME" \
    --image "$(image)" \
    --platform "$PLATFORM" \
    --preset "$PRESET" \
    --disk-size "$DISK" \
    --container-port 8080 \
    --volume "$FS_ID:/data:rw" \
    --env-secret "LLM_API_KEY=$SECRET_NAME" \
    "${envs[@]}"
  local url; url=$(endpoint_url)
  wait_healthy "$url"
  echo "Sherlock is up at $url"
  curl -s "$url/healthz"; echo
}

redeploy() {
  local id; id=$(endpoint_id)
  [ -n "$id" ] || die "no endpoint '$NAME'; run './scripts/deploy.sh setup'"
  build_and_push
  nebius ai endpoint restart --id "$id"
  local url; url=$(endpoint_url)
  wait_healthy "$url"
  echo "Redeployed: $url"
  curl -s "$url/healthz"; echo
}

check() {
  local id url jar before after user_before user_after
  id=$(endpoint_id); [ -n "$id" ] || die "no endpoint '$NAME'"
  url=$(endpoint_url)
  jar=$(mktemp)
  before=$(curl -sf "$url/healthz")
  user_before=$(curl -sf -c "$jar" "$url/api/v1/me" | jq -r '.user_id')
  nebius ai endpoint restart --id "$id"
  sleep 20
  wait_healthy "$url"
  after=$(curl -sf "$url/healthz")
  user_after=$(curl -sf -b "$jar" "$url/api/v1/me" | jq -r '.user_id')
  rm -f "$jar"
  echo "before: $(jq -c '.storage' <<<"$before")"
  echo "after:  $(jq -c '.storage' <<<"$after")"
  if [ "$(jq '.storage.boots' <<<"$after")" -gt "$(jq '.storage.boots' <<<"$before")" ] \
    && [ "$(jq -r '.storage.first_boot_at' <<<"$after")" = "$(jq -r '.storage.first_boot_at' <<<"$before")" ] \
    && [ "$(jq '.storage.sqlite_lock' <<<"$after")" = "true" ] \
    && [ "$user_before" = "$user_after" ]; then
    echo "PASS: /data survived the restart, SQLite locking works, the cookie user persisted"
  else
    echo "FAIL: switch to the AI Cloud VM fallback" >&2
    exit 1
  fi
}

case "${1:-deploy}" in
  setup) setup ;;
  deploy) redeploy ;;
  check) check ;;
  url) endpoint_url ;;
  *) die "usage: $0 [setup|deploy|check|url]" ;;
esac
